"""Recalculate every stage and entrant from one consistent rally snapshot."""

from copy import deepcopy

from src.prediction.manual_calculator import (
    build_manual_payload_from_rally,
    calculate_manual_stage_estimate,
    format_manual_time,
    parse_manual_time_input,
)


def finished_seconds(result):
    if str(result.get('status', 'OK')).upper() not in ('OK', 'FINISHED', ''):
        return None
    try:
        return parse_manual_time_input(result.get('time_str', ''))
    except ValueError:
        return None


def calculate_rally_tables(rally_data, prediction_service=None):
    """Return stage -> rows without writing predictions or official decisions.

    Roster metadata may come from any stage. Reference times always come from
    stages before the target; target and future times never enter that average.
    """
    rally = deepcopy(rally_data)
    roster = {entry['driver_name']: dict(entry) for entry in rally.get('entrants', [])}
    stages = sorted(rally.get('stages', []), key=lambda item: int(item['stage_number']))
    for stage in stages:
        for result in stage.get('results', []):
            if result.get('driver_name'):
                roster[result['driver_name']] = {key: result.get(key, '') for key in
                                               ('driver_name', 'car_number', 'car_class')}

    # Supply class metadata for entrants still on stage without inventing times.
    for stage in stages:
        results = stage.get('results', [])
        names = {row.get('driver_name') for row in results}
        stage['results'] = [
            row if finished_seconds(row) is not None else {**row, 'time_str': ''}
            for row in results
        ] + [{**entry, 'time_str': ''} for name, entry in roster.items() if name not in names]

    tables = {}
    for original_stage, stage in zip(sorted(rally_data.get('stages', []), key=lambda s: int(s['stage_number'])), stages):
        number = int(stage['stage_number'])
        actual = {row['driver_name']: row for row in original_stage.get('results', []) if row.get('driver_name')}
        rows = []
        for name, entrant in sorted(roster.items()):
            result = actual.get(name, {})
            seconds = finished_seconds(result)
            row = {
                'No': entrant.get('car_number', ''), 'Pilot': name,
                'Sınıf': result.get('car_class') or entrant.get('car_class', ''),
                'Gerçek Derece': format_manual_time(seconds) if seconds is not None else '—',
                'Km Bazlı': '—', 'Yüzde Bazlı': '—', 'Baz Tahmin': '—',
                'Referans': 0, 'Durum': 'Veri bekleniyor', 'Açıklama': '',
            }
            try:
                payload = build_manual_payload_from_rally(rally, name, number)
                estimate = calculate_manual_stage_estimate(payload['references'], payload['target'], payload['class_name'])
                row.update({
                    'Km Bazlı': format_manual_time(estimate.km_based_prediction_seconds),
                    'Yüzde Bazlı': format_manual_time(estimate.percentage_prediction_seconds),
                    'Referans': estimate.used_stage_count,
                    'Durum': 'Hesaplandı', 'Açıklama': ' '.join(estimate.warnings),
                })
            except ValueError as exc:
                row['Açıklama'] = str(exc)

            # A baseline requires at least one real previous result and a known
            # distance. Do not display default-history guesses before SS1.
            previous = any(
                int(s['stage_number']) < number and any(
                    r.get('driver_name') == name and finished_seconds(r) is not None
                    for r in s.get('results', [])
                ) for s in stages
            )
            if prediction_service and previous and float(stage.get('stage_length_km') or 0) > 0:
                try:
                    prediction = prediction_service.predict_live_stage(
                        rally_data=rally, driver_name=name, driver_class=row['Sınıf'],
                        predict_stage_num=number, surface=rally.get('surface') or 'gravel',
                        geo_features=None, log_prediction=False,
                    )
                    row['Baz Tahmin'] = format_manual_time(prediction['predicted_time_seconds'])
                    if row['Durum'] != 'Hesaplandı':
                        row['Durum'] = 'Yalnız baz tahmin'
                except Exception as exc:
                    row['Açıklama'] += f' Baz tahmin kullanılamadı: {exc}'
            rows.append(row)
        tables[number] = rows
    return tables
