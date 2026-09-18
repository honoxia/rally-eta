"""Live race dashboard: one URL, every stage and every entrant."""

from datetime import datetime
import hashlib
import json
import time

import pandas as pd
import streamlit as st

from shared.config import get_db_path, get_model_path
from shared.services import get_prediction_service
from shared.ui_components import render_page_header
from src.prediction.live_rally import calculate_rally_tables
from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper


REFRESH_SECONDS = 60


def render():
    render_page_header(
        'Canlı Yarış',
        'Yarış ilerledikçe tüm pilotların hesapları güncellenir. Görmek istediğiniz etabı seçin.',
        badge='Otomatik Takip', eyebrow='Operasyon Modu',
    )
    url = st.text_input('TOSFED Sonuç URL’si', key='race_watch_input',
                        placeholder='https://www.tosfedsonuc.org.tr/yaris/224/ralli_etap_sonuclari/')
    start = st.button('Yarışı Takip Et', type='primary', key='race_watch_start')
    if start:
        if not url.strip():
            st.error('Yarış sonuç URL’sini girin.')
        else:
            if st.session_state.get('race_watch_url') != url.strip():
                for key in ('race_watch_snapshot', 'race_watch_tables', 'race_watch_fingerprint',
                            'race_watch_updated', 'race_watch_stage', 'race_watch_error'):
                    st.session_state.pop(key, None)
            st.session_state['race_watch_url'] = url.strip()
            st.session_state['race_watch_attempt'] = 0
            st.session_state['race_watch_enabled'] = True
    if not st.session_state.get('race_watch_url'):
        st.info('Yarış bağlantısını girip takibi başlatın. Pilotları tek tek seçmeniz gerekmez.')
        return
    if url.strip() != st.session_state['race_watch_url']:
        st.warning('Takip mevcut yarışta sürüyor. Yeni URL için Yarışı Takip Et’e basın.')
    _render_live_content()


def _refresh_race(force=False):
    now = time.monotonic()
    if not force and now - st.session_state.get('race_watch_attempt', 0) < REFRESH_SECONDS:
        return
    st.session_state['race_watch_attempt'] = now
    try:
        with st.spinner('Etap sonuçları kontrol ediliyor; tüm pilotların hesapları güncelleniyor...'):
            scraper = TOSFEDSonucScraper()
            try:
                snapshot = scraper.fetch_live_snapshot(st.session_state['race_watch_url'])
            finally:
                scraper.session.close()
            model = get_model_path()
            fingerprint = hashlib.sha256(json.dumps(
                [snapshot, get_db_path(), model.stat().st_mtime_ns if model.exists() else 0],
                sort_keys=True, ensure_ascii=False,
            ).encode()).hexdigest()
            if fingerprint != st.session_state.get('race_watch_fingerprint'):
                service = get_prediction_service() if snapshot.get('stages') else None
                tables = calculate_rally_tables(snapshot, service)
                st.session_state['race_watch_tables'] = tables
                st.session_state['race_watch_snapshot'] = snapshot
                st.session_state['race_watch_fingerprint'] = fingerprint
            st.session_state['race_watch_updated'] = datetime.now().strftime('%H:%M:%S')
            st.session_state.pop('race_watch_error', None)
    except Exception as exc:
        st.session_state['race_watch_error'] = f'Güncelleme alınamadı: {exc}'


@st.fragment(run_every='30s')
def _render_live_content():
    controls = st.columns([2, 1])
    enabled = controls[0].toggle('Otomatik güncelle (60 saniye)', value=True, key='race_watch_enabled')
    refresh = controls[1].button('Şimdi Yenile', key='race_watch_refresh', use_container_width=True)
    if refresh or enabled:
        _refresh_race(force=refresh)
    if st.session_state.get('race_watch_error'):
        st.warning(st.session_state['race_watch_error'])
        if st.session_state.get('race_watch_snapshot'):
            st.warning('Aşağıdaki tablo son başarılı güncellemedendir; yeni sonuçları içermeyebilir.')
    updated = st.session_state.get('race_watch_updated')
    if updated:
        st.caption(f'Son başarılı kontrol: {updated} · Takip {"açık" if enabled else "duraklatıldı"}.')
    st.caption('Otomatik takip bu sayfa açıkken çalışır. Yeni veya düzeltilen dereceler tüm etapların hesabına yansır.')
    snapshot = st.session_state.get('race_watch_snapshot')
    if not snapshot:
        return
    st.subheader(snapshot['rally_name'])
    if snapshot.get('roster_warning'):
        st.info(snapshot['roster_warning'])
    stages = snapshot.get('stages', [])
    if not stages:
        st.info('Etap bilgileri henüz yayımlanmamış. Otomatik takip açıkken yeniden kontrol edilecek.')
        return
    stage_map = {int(stage['stage_number']): stage for stage in stages}
    options = sorted(stage_map)
    if st.session_state.get('race_watch_stage') not in options:
        st.session_state['race_watch_stage'] = options[0]
    selected = st.selectbox(
        'Etap', options, key='race_watch_stage',
        format_func=lambda number: f"SS{number} · {stage_map[number]['stage_name']}",
    )
    rows = st.session_state.get('race_watch_tables', {}).get(selected, [])
    if not rows:
        st.info('Yarışmacı listesi bekleniyor. Veriler geldiğinde pilotlar otomatik eklenecek.')
        return
    metrics = st.columns(3)
    metrics[0].metric('Yarışmacı', len(rows))
    metrics[1].metric('Hesaplanan', sum(row['Durum'] != 'Veri bekleniyor' for row in rows))
    metrics[2].metric('Gerçek derece', sum(row['Gerçek Derece'] != '—' for row in rows))
    st.caption(
        'Km ve yüzde hesabı önceki etaplara ve hedef etabın aynı sınıf bestine dayanır. '
        'İlk etapta önceki referans olmadığı için hesap bekler. Baz Tahmin ML sonucu değildir. '
        'Bu tablo güncel veriye göre yeniden hesaplanır; etap öncesinde sabitlenmiş tahmin veya resmi karar değildir.'
    )
    frame = pd.DataFrame(rows)
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.download_button('Bu Etabı CSV İndir', frame.to_csv(index=False).encode('utf-8-sig'),
                       file_name=f"yaris_{snapshot['rally_id']}_ss{selected}.csv", mime='text/csv')
