from copy import deepcopy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from src.data.master_schema import apply_master_schema
from src.prediction.live_rally import calculate_rally_tables
from src.prediction.prediction_service import PredictionService


URL = 'https://www.tosfedsonuc.org.tr/yaris/224/ralli_etap_sonuclari/'


def fixture():
    return {
        'rally_id': 224, 'rally_name': 'Test Rallisi', 'surface': 'gravel',
        'entrants': [{'driver_name': name, 'car_number': str(i), 'car_class': 'K3'}
                     for i, name in enumerate(['Pilot A', 'Pilot B', 'Pilot C'], 1)],
        'stages': [
            {'stage_number': 1, 'stage_name': 'Orman', 'stage_length_km': 10,
             'results': [
                 {'driver_name': 'Pilot A', 'car_class': 'K3', 'time_str': '11:00:000'},
                 {'driver_name': 'Pilot B', 'car_class': 'K3', 'time_str': '10:00:000'},
             ]},
            {'stage_number': 2, 'stage_name': 'Tepe', 'stage_length_km': 10,
             'results': [{'driver_name': 'Pilot B', 'car_class': 'K3', 'time_str': '09:00:000'}]},
            {'stage_number': 3, 'stage_name': 'Göl', 'stage_length_km': 12, 'results': []},
        ],
    }


class LiveCalculationTests(unittest.TestCase):
    def test_all_stages_and_entrants_with_no_future_reference_leakage(self):
        rally = fixture()
        original = deepcopy(rally)
        tables = calculate_rally_tables(rally)
        self.assertEqual(rally, original)
        self.assertEqual(list(tables), [1, 2, 3])
        self.assertTrue(all(len(rows) == 3 for rows in tables.values()))
        self.assertEqual(tables[1][0]['Durum'], 'Veri bekleniyor')
        self.assertEqual(tables[2][0]['Km Bazlı'], '10:00:000')
        self.assertEqual(tables[2][0]['Yüzde Bazlı'], '09:54:000')
        self.assertEqual(tables[2][0]['Gerçek Derece'], '—')
        self.assertEqual(tables[2][2]['Durum'], 'Veri bekleniyor')
        self.assertEqual(tables[3][0]['Durum'], 'Veri bekleniyor')
        rally['stages'][2]['results'] = [{'driver_name': 'Pilot A', 'car_class': 'K3', 'time_str': '30:00:000'}]
        self.assertEqual(calculate_rally_tables(rally)[2], tables[2])

    def test_new_and_corrected_times_recalculate_every_affected_stage(self):
        rally = fixture()
        rally['stages'][2]['results'] = [{'driver_name': 'Pilot B', 'car_class': 'K3', 'time_str': '12:00:000'}]
        before = calculate_rally_tables(rally)
        rally['stages'][0]['results'][0]['time_str'] = '10:30:000'
        after = calculate_rally_tables(rally)
        self.assertNotEqual(before[2][0]['Km Bazlı'], after[2][0]['Km Bazlı'])
        self.assertNotEqual(before[3][0]['Km Bazlı'], after[3][0]['Km Bazlı'])

    def test_dnf_time_cannot_become_a_reference(self):
        rally = fixture()
        rally['stages'][0]['results'][0]['status'] = 'DNF'
        row = calculate_rally_tables(rally)[2][0]
        self.assertEqual(row['Km Bazlı'], '—')
        self.assertEqual(row['Referans'], 0)

    def test_baseline_uses_read_only_prediction_without_saving_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'test.db')
            apply_master_schema(path)
            service = PredictionService(path)
            tables = calculate_rally_tables(fixture(), service)
            self.assertNotEqual(tables[3][0]['Baz Tahmin'], '—')
            self.assertEqual(tables[1][0]['Baz Tahmin'], '—')
            self.assertEqual(tables[3][2]['Baz Tahmin'], '—')
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM prediction_log').fetchone()[0], 0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM operation_decisions').fetchone()[0], 0)


class LiveDashboardTests(unittest.TestCase):
    def setUp(self):
        original_path = sys.path[:]
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'segment'))
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), original_path))

    def test_start_select_refresh_pause_and_recover(self):
        app = AppTest.from_string('from pages.operations import render\nrender()')
        service = Mock()
        service.predict_live_stage.return_value = {'predicted_time_seconds': 650}
        with patch('src.scraper.tosfed_sonuc_scraper.TOSFEDSonucScraper.fetch_live_snapshot', return_value=fixture()) as fetch, patch(
            'pages.live_rally.get_prediction_service', return_value=service
        ):
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(app.selectbox)
            app.text_input(key='race_watch_input').set_value(URL).run()
            app.button(key='race_watch_start').click().run()
            self.assertFalse(app.exception)
            fetch.assert_called_once_with(URL)
            self.assertEqual(len(app.selectbox), 1)  # No pilot selector or calculate button.
            self.assertEqual(app.selectbox(key='race_watch_stage').value, 1)
            app.selectbox(key='race_watch_stage').set_value(2).run()
            self.assertEqual(len(app.dataframe[0].value), 3)
            self.assertEqual(app.dataframe[0].value.iloc[0]['Km Bazlı'], '10:00:000')
            calls = service.predict_live_stage.call_count
            self.assertEqual(fetch.call_count, 1)
            app.button(key='race_watch_refresh').click().run()
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(service.predict_live_stage.call_count, calls)  # Unchanged snapshot.
            changed = fixture()
            changed['stages'][0]['results'][0]['time_str'] = '10:30:000'
            fetch.return_value = changed
            # Simulate the next timer tick, without any calculate button.
            app.session_state['race_watch_attempt'] = 0
            app.run()
            self.assertEqual(app.selectbox(key='race_watch_stage').value, 2)
            self.assertEqual(app.dataframe[0].value.iloc[0]['Km Bazlı'], '09:30:000')
            fetch.side_effect = OSError('offline')
            app.button(key='race_watch_refresh').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('son başarılı' in item.value for item in app.warning))
            self.assertEqual(app.dataframe[0].value.iloc[0]['Km Bazlı'], '09:30:000')
            app.toggle(key='race_watch_enabled').set_value(False).run()
            count = fetch.call_count
            app.session_state['race_watch_attempt'] = 0
            app.run()
            self.assertEqual(fetch.call_count, count)
            fetch.side_effect = None
            app.button(key='race_watch_refresh').click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.warning)

    def test_not_started_rally_retries_and_fills_table_automatically(self):
        app = AppTest.from_string('from pages.live_rally import render\nrender()')
        empty = {**fixture(), 'stages': [], 'entrants': []}
        with patch('src.scraper.tosfed_sonuc_scraper.TOSFEDSonucScraper.fetch_live_snapshot', return_value=empty) as fetch, patch(
            'pages.live_rally.get_prediction_service', return_value=None
        ):
            app.run()
            app.text_input(key='race_watch_input').set_value(URL).run()
            app.button(key='race_watch_start').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('henüz yayımlanmamış' in item.value for item in app.info))
            fetch.return_value = fixture()
            app.session_state['race_watch_attempt'] = 0
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.dataframe[0].value), 3)


if __name__ == '__main__':
    unittest.main()
