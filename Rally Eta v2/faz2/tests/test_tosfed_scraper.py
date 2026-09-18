import unittest
from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup

from src.scraper.tosfed_sonuc_scraper import ResultsNotPublishedError, TOSFEDSonucScraper


URL = 'https://www.tosfedsonuc.org.tr/yaris/224/ralli_etap_sonuclari/'
HEADER = '''<title>E1 - TOSFED</title><ul class="text-center">
<li>Petrol Ofisi Maxima 2026 Türkiye Ralli Şampiyonası - 5</li>
<li>Eskişehir Rallisi</li><li>18 - 20 Eylül 2026</li></ul>
<h1>Geçici Neticeler / Provisional Results</h1>'''
ROW = '''<tr><td>1</td><td>37</td><td>Pilot A<br>Co Pilot</td>
<td>TUR</td><td>K3</td><td>Team<br>Car</td><td>10:12.3<br>80 km/h</td><td></td></tr>'''


def page(rows=''):
    return HEADER + '''<table><thead><tr><th colspan="8">ÖE-1 Test - 13.77km</th></tr>
<tr><th>Sıra</th><th>No</th><th>Pilot</th><th>Uyruk</th><th>S/K</th>
<th>Takım</th><th>Zaman/Hız</th><th>Fark</th></tr></thead><tbody>''' + rows + '''</tbody></table>
<table><tr><th>Sıradaki Araçlar</th></tr>''' + ROW * 4 + '</table>'


def response(html, status=200):
    return Mock(status_code=status, content=html.encode('utf-8'))


class TosfedScraperTests(unittest.TestCase):
    def setUp(self):
        self.scraper = TOSFEDSonucScraper()

    def test_new_domain_and_results_with_larger_queue(self):
        with patch.object(self.scraper.session, 'get', side_effect=[
            response(page(ROW)), response(page(ROW)), response('', 404),
            response('', 404), response('', 404),
        ]) as get:
            data = self.scraper.fetch_rally_from_url(URL + '?etp=1')
        self.assertTrue(get.call_args_list[0].args[0].startswith('https://www.tosfedsonuc.org.tr/'))
        self.assertEqual(data['rally_name'], 'Eskişehir Rallisi')
        self.assertEqual(data['suggested_stage'], 1)
        self.assertEqual(len(data['stages']), 1)
        self.assertEqual(data['stages'][0]['stage_length_km'], 13.77)
        self.assertEqual(len(data['stages'][0]['results']), 1)
        self.assertEqual(data['stages'][0]['results'][0]['time_str'], '10:12.3')

    def test_empty_stage_is_not_replaced_by_queue_or_overall(self):
        with patch.object(self.scraper.session, 'get', return_value=response(page())):
            with self.assertRaisesRegex(ResultsNotPublishedError, 'finiş dereceleri'):
                self.scraper.fetch_rally_from_url(URL)
        overall = BeautifulSoup('<table><tr><th>Genel Klasman</th></tr>' + ROW + '</table>', 'html.parser')
        self.assertIsNone(self.scraper._select_results_table(overall))

    def test_not_started_page_has_specific_message(self):
        with patch.object(self.scraper.session, 'get', return_value=response(
            HEADER + '<h4>Yarış Henüz Başlamadı</h4>'
        )) as get:
            with self.assertRaisesRegex(ResultsNotPublishedError, 'henüz başlamadı'):
                self.scraper.fetch_rally_from_url(URL)
        self.assertEqual(get.call_count, 1)

    def test_network_failure_is_not_reported_as_unpublished_results(self):
        with patch.object(self.scraper.session, 'get', return_value=response(page())):
            with self.assertRaises(ResultsNotPublishedError):
                self.scraper.fetch_rally_from_url(URL)
        with patch.object(self.scraper.session, 'get', side_effect=requests.ConnectionError):
            self.assertIsNone(self.scraper.fetch_rally_from_url(URL))

    def test_repeated_default_stage_is_not_recorded_as_later_stages(self):
        with patch.object(self.scraper.session, 'get', return_value=response(page(ROW))):
            data = self.scraper.fetch_rally_from_url(URL)
        self.assertEqual([stage['stage_number'] for stage in data['stages']], [1])

    def test_unknown_host_is_never_fetched(self):
        with patch.object(self.scraper.session, 'get', return_value=response(page(ROW))) as get:
            self.scraper.fetch_rally_from_url('http://127.0.0.1/yaris/224/')
        self.assertTrue(all(call.args[0].startswith('https://www.tosfedsonuc.org.tr/') for call in get.call_args_list))

    def test_legacy_host_is_preferred_and_plain_stage_header_still_parses(self):
        with patch.object(self.scraper.session, 'get', return_value=response(page(ROW))) as get:
            self.scraper.fetch_rally_from_url('https://sonuc.tosfed.org.tr/yaris/171/')
        self.assertTrue(get.call_args_list[0].args[0].startswith('https://sonuc.tosfed.org.tr/'))
        self.assertEqual(self.scraper._parse_stage_header('SS7 Test 10,5km')[1:], (7, 10.5))

    def test_live_snapshot_keeps_empty_stages_and_queue_entrants(self):
        html = page() + ''.join(f'<a id="et{n}">Etap-{n}</a>' for n in range(1, 6))

        def stage_response(url, **kwargs):
            number = int(url.split('etp=')[1])
            # A populated SS5 must be read even after three empty stages.
            return response(page(ROW if number == 5 else '').replace('ÖE-1', f'ÖE-{number}'))

        with patch.object(self.scraper.session, 'get', return_value=response(html)), patch(
            'src.scraper.tosfed_sonuc_scraper.requests.get', side_effect=stage_response,
        ) as get:
            data = self.scraper.fetch_live_snapshot(URL)
        self.assertEqual(len(data['stages']), 5)
        self.assertEqual(get.call_count, 4)
        self.assertEqual(data['stages'][0]['results'], [])
        self.assertEqual(len(data['stages'][4]['results']), 1)
        self.assertEqual(data['entrants'], [{'driver_name': 'Pilot A', 'car_number': '37', 'car_class': 'K3'}])
        self.assertNotIn('time_str', data['entrants'][0])

    def test_live_snapshot_does_not_copy_redirected_stage_times(self):
        html = page(ROW) + '<a id="et1">1</a><a id="et2">2</a>'
        with patch.object(self.scraper.session, 'get', return_value=response(html)), patch(
            'src.scraper.tosfed_sonuc_scraper.requests.get', return_value=response(html),
        ):
            data = self.scraper.fetch_live_snapshot(URL)
        self.assertEqual(data['stages'][1]['results'], [])
        self.assertEqual(data['stages'][1]['stage_number'], 2)

    def test_live_snapshot_includes_startlist_drivers_without_any_results(self):
        html = page() + '<a id="et1">1</a><a href="/yaris/224/1/startlist_ralli_gun1_print/">Start</a>'
        startlist = '''<table><tr><th>Sıra</th><th>No</th><th>Pilot</th><th>Co-Pilot</th>
        <th>Uyruk</th><th>S/K</th></tr>
        <tr><td>1</td><td>99</td><td>Not On Stage</td><td>Co</td><td>TUR</td><td>K2</td></tr>
        <tr><td>2</td><td>100</td><td>Another Driver</td><td>Co</td><td>TUR</td><td>K1</td></tr></table>'''
        with patch.object(self.scraper.session, 'get', side_effect=[response(html), response(startlist)]):
            data = self.scraper.fetch_live_snapshot(URL)
        self.assertEqual({entrant['driver_name'] for entrant in data['entrants']},
                         {'Pilot A', 'Not On Stage', 'Another Driver'})
        self.assertNotIn('roster_warning', data)
        self.assertEqual(data['stages'][0]['results'], [])

    def test_live_snapshot_rejects_partial_network_failure(self):
        html = page(ROW) + '<a id="et1">1</a><a id="et2">2</a>'
        with patch.object(self.scraper.session, 'get', return_value=response(html)), patch(
            'src.scraper.tosfed_sonuc_scraper.requests.get', side_effect=requests.Timeout,
        ):
            with self.assertRaises(requests.Timeout):
                self.scraper.fetch_live_snapshot(URL)

    def test_live_snapshot_not_started_and_unknown_host(self):
        with patch.object(self.scraper.session, 'get', return_value=response(
            HEADER + '<h4>Yarış Henüz Başlamadı</h4>'
        )):
            data = self.scraper.fetch_live_snapshot(URL)
        self.assertEqual(data['stages'], [])
        with patch.object(self.scraper.session, 'get') as get:
            with self.assertRaises(ValueError):
                self.scraper.fetch_live_snapshot('http://localhost/yaris/224/')
        get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
