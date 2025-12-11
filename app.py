"""
Rally ETA Prediction System - Main Streamlit App
Kırmızı Bayrak Durumunda Notional Time Hesaplama
"""

import streamlit as st
import pandas as pd
import sys
import os
import time
from pathlib import Path
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Imports
from src.utils.database import Database
from src.utils.logger import setup_logger
from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper
from src.preprocessing.clean_data import DataCleaner
from src.features.engineer_features_v1_1 import FeatureEngineerV1_1 as FeatureEngineer  # v1.1
from src.models.train_model import RallyETAModel
from src.inference.predict_notional_times import NotionalTimePredictor
from config.config_loader import config

# Page config
st.set_page_config(
    page_title="Rally ETA Tahmin Sistemi",
    page_icon="🏁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        text-align: center;
        color: #FF4B4B;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 5px;
        padding: 15px;
        margin: 10px 0;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        border-radius: 5px;
        padding: 15px;
        margin: 10px 0;
    }
    .stMetric {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #dee2e6;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'db' not in st.session_state:
    st.session_state.db = Database()
if 'logger' not in st.session_state:
    st.session_state.logger = setup_logger('app')

# Helper functions
def get_system_status():
    """Sistem durumunu kontrol et"""
    status = {
        'database': False,
        'data_count': 0,
        'clean_data': False,
        'clean_count': 0,
        'features': False,
        'model': False,
        'model_metrics': None
    }

    try:
        # Database
        count = st.session_state.db.load_dataframe("SELECT COUNT(*) as count FROM stage_results")
        status['data_count'] = int(count.iloc[0]['count'])
        status['database'] = status['data_count'] > 0

        # Clean data
        try:
            clean = st.session_state.db.load_dataframe("SELECT COUNT(*) as count FROM clean_stage_results")
            status['clean_count'] = int(clean.iloc[0]['count'])
            status['clean_data'] = status['clean_count'] > 0
        except:
            pass

        # Features
        status['features'] = Path('data/processed/features.parquet').exists()

        # Model
        model_path = Path('models/rally_eta_v1/model.pkl')
        status['model'] = model_path.exists()

        # Model metrics
        metrics_path = Path('models/rally_eta_v1/evaluation_metrics.json')
        if status['model'] and metrics_path.exists():
            with open(metrics_path, 'r') as f:
                status['model_metrics'] = json.load(f)

    except Exception as e:
        st.session_state.logger.error(f"Status check error: {e}")

    return status

# Sidebar navigation
st.sidebar.title("🏁 Rally ETA System")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigasyon",
    [
        "🏠 Ana Sayfa",
        "🕷️ Veri Toplama",
        "🧹 Veri İşleme",
        "🎓 Model Eğitimi",
        "🎯 Tahmin Yap",
        "📊 Raporlar",
        "⚙️ Ayarlar"
    ]
)

# Quick stats in sidebar
status = get_system_status()
st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Sistem Durumu")
st.sidebar.metric("Raw Veri", f"{status['data_count']:,}" if status['database'] else "0")
st.sidebar.metric("Temiz Veri", f"{status['clean_count']:,}" if status['clean_data'] else "0")
st.sidebar.metric("Model", "✅ Hazır" if status['model'] else "❌ Yok")

# ========== ANA SAYFA ==========
if page == "🏠 Ana Sayfa":
    st.markdown('<div class="main-header">🏁 Rally Etap Zamanı Tahmin Sistemi v1.2</div>', unsafe_allow_html=True)
    st.markdown("### Kırmızı Bayrak Durumunda Notional Time Hesaplama")

    st.markdown("---")
    st.subheader("📊 Sistem Durumu")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Ham Veri",
            f"{status['data_count']:,}" if status['database'] else "Yok",
            "sonuç"
        )

    with col2:
        st.metric(
            "Temiz Veri",
            f"{status['clean_count']:,}" if status['clean_data'] else "Yok",
            "✅" if status['clean_data'] else "❌"
        )

    with col3:
        st.metric(
            "Features",
            "✅ Hazır" if status['features'] else "❌ Yok",
            ""
        )

    with col4:
        st.metric(
            "Model",
            "✅ Eğitilmiş" if status['model'] else "❌ Yok",
            ""
        )

    # Model metrikleri
    if status['model'] and status['model_metrics']:
        st.markdown("---")
        st.subheader("🎯 Model Performansı")

        test_metrics = status['model_metrics'].get('test', {})

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            mape = test_metrics.get('mape', 0)
            st.metric("MAPE", f"{mape:.2f}%",
                     "✅ Hedef: <2.5%" if mape < 2.5 else "⚠️ Hedef: <2.5%")

        with col2:
            mae = test_metrics.get('mae_seconds', 0)
            st.metric("MAE", f"{mae:.1f}s", "ortalama hata")

        with col3:
            r2 = test_metrics.get('r2', 0)
            st.metric("R² Score", f"{r2:.4f}", "")

        with col4:
            model_path = Path('models/rally_eta_v1/model.pkl')
            if model_path.exists():
                model_date = datetime.fromtimestamp(model_path.stat().st_mtime)
                st.metric("Son Eğitim", model_date.strftime("%d.%m.%Y"), "")

    # Hızlı başlangıç
    st.markdown("---")
    st.subheader("🚀 Hızlı Başlangıç")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.button("📥 Veri Topla", use_container_width=True, type="primary",
                 key="btn_scrape", help="TOSFED'den veri çek")

    with col2:
        st.button("🎓 Model Eğit", use_container_width=True,
                 disabled=not status['features'], key="btn_train",
                 help="Modeli eğit" if status['features'] else "Önce feature oluştur")

    with col3:
        st.button("🎯 Tahmin Yap", use_container_width=True,
                 disabled=not status['model'], key="btn_predict",
                 help="Notional time tahmin et" if status['model'] else "Önce model eğit")

    # Kullanım talimatları
    st.markdown("---")
    st.subheader("📖 Kullanım Talimatları")

    with st.expander("1️⃣ Veri Toplama"):
        st.markdown("""
        **TOSFED Sonuç sitesinden otomatik veri çekme**

        - Ralli ID aralığı belirle (örn: 50-100)
        - Sadece **Ralli** kategorisi çekilir
        - Baja ve Offroad otomatik atlanır
        - Progress bar ile takip
        - Database'e otomatik kaydedilir

        **Önerilen ID Aralıkları:**
        - 2024 Rallileri: 50-100
        - Tüm veriler: 1-100 (uzun sürer)
        """)

    with st.expander("2️⃣ Veri İşleme"):
        st.markdown("""
        **İki aşamalı veri işleme**

        **Adım 1: Veri Temizleme**
        - Anomali tespiti (Z-score, IQR)
        - DNF/DNS durumlarını ayıklama
        - Geçersiz zamanları filtreleme
        - Temiz veri → `clean_stage_results` tablosu

        **Adım 2: Feature Engineering**
        - Temporal-safe özellikler
        - Sınıf içi performans oranları
        - Historical averages
        - Weather/surface features (gelecekte)
        - Output → `data/processed/features.parquet`
        """)

    with st.expander("3️⃣ Model Eğitimi"):
        st.markdown("""
        **LightGBM ile makine öğrenimi**

        - **Rally-based split**: Temporal leakage önlenir
        - Train/Val/Test: 60/20/20
        - Otomatik hyperparameter tuning (opsiyonel)
        - Feature importance analizi
        - Evaluation metrics kaydedilir

        **Hedef Metrikler:**
        - MAPE < 2.5%
        - MAE < 3 saniye
        - R² > 0.95
        """)

    with st.expander("4️⃣ Tahmin"):
        st.markdown("""
        **Kırmızı bayrak durumu için notional time**

        1. Rally ve etap seç
        2. Etkilenen pilotları işaretle
        3. Model tahmin yapar:
           - Sınıf lideri zamanlarına göre ratio
           - Historical performance
           - Confidence score hesabı
        4. Sonuçları dışa aktar (Excel/CSV/PDF)

        **Confidence Seviyeleri:**
        - 🟢 High: >80% güven
        - 🟡 Medium: 60-80%
        - 🔴 Low: <60% (manuel kontrol önerilir)
        """)

    # Sistem gereksinimleri
    st.markdown("---")
    with st.expander("ℹ️ Sistem Gereksinimleri"):
        st.markdown("""
        **Minimum Veri:**
        - En az 500 temiz etap sonucu
        - En az 3 farklı ralli
        - En az 2 farklı sınıf

        **Önerilen Veri:**
        - 2000+ etap sonucu
        - 10+ ralli
        - Tüm sınıfları kapsayan veriler

        **Donanım:**
        - RAM: 4GB+ (8GB önerilir)
        - Disk: 1GB boş alan
        - CPU: Multicore önerilir
        """)

# ========== VERİ TOPLAMA ==========
elif page == "🕷️ Veri Toplama":
    st.header("🕷️ Otomatik Veri Toplama")
    st.markdown("TOSFED Sonuç sitesinden rally verilerini çek")

    st.info("ℹ️ Sadece **Ralli** kategorisindeki yarışlar çekilir. Baja ve Offroad atlanır.")

    # Ayarlar
    col1, col2 = st.columns(2)

    with col1:
        start_id = st.number_input("Başlangıç Rally ID",
                                   min_value=1, max_value=200, value=50)

    with col2:
        end_id = st.number_input("Bitiş Rally ID",
                                 min_value=1, max_value=200, value=100)

    if start_id >= end_id:
        st.error("❌ Bitiş ID başlangıçtan büyük olmalı!")
        st.stop()

    total_to_check = end_id - start_id + 1
    estimated_time = total_to_check * 3  # ~3 saniye per rally

    st.warning(f"⚠️ **{total_to_check}** rally kontrol edilecek. Tahmini süre: **~{estimated_time//60} dakika**")

    # Scraping butonu
    if st.button("🚀 Scraping Başlat", type="primary", use_container_width=True):

        from src.preprocessing.time_parser import TimeParser

        scraper = TOSFEDSonucScraper()
        parser = TimeParser()
        db = st.session_state.db

        # Progress tracking
        progress_bar = st.progress(0)
        status_text = st.empty()

        # Metrics
        col1, col2, col3, col4 = st.columns(4)
        metric_rally = col1.empty()
        metric_skip = col2.empty()
        metric_404 = col3.empty()
        metric_results = col4.empty()

        # Results table
        results_placeholder = st.empty()

        rally_ids = list(range(start_id, end_id + 1))
        total = len(rally_ids)

        rally_count = 0
        skip_count = 0
        not_found_count = 0
        total_results = 0

        rally_details = []
        all_results = []

        for i, rally_id in enumerate(rally_ids):
            progress_bar.progress((i + 1) / total)
            status_text.text(f"İşleniyor: Rally {rally_id}/{end_id}")

            try:
                rally_data = scraper.fetch_rally_stages(rally_id)

                if rally_data is None:
                    # Kategori filtresi tarafından atlandı
                    skip_count += 1
                    metric_skip.metric("⏭️ Atlanan", skip_count)
                    continue

                # Rally bulundu
                rally_count += 1
                stage_count = len(rally_data['stages'])
                result_count = sum(len(stage['results']) for stage in rally_data['stages'])
                total_results += result_count

                rally_details.append({
                    'ID': rally_id,
                    'Rally Adı': rally_data['rally_name'][:50],
                    'Etap': stage_count,
                    'Sonuç': result_count,
                    'Durum': '✅'
                })

                # Database'e kaydet
                for stage in rally_data['stages']:
                    for result in stage['results']:
                        row = {
                            'result_id': f"{rally_data['rally_id']}_ss{stage['stage_number']}_{result['car_number']}",
                            'rally_id': str(rally_data['rally_id']),
                            'rally_name': rally_data['rally_name'],
                            'stage_id': f"{rally_data['rally_id']}_ss{stage['stage_number']}",
                            'stage_name': stage['stage_name'],
                            'stage_number': stage['stage_number'],
                            'stage_length_km': stage['stage_length_km'],
                            'driver_id': result['car_number'],
                            'driver_name': result['driver_name'],
                            'car_model': result['car_model'],
                            'car_class': result['car_class'],
                            'raw_time_str': result['time_str'],
                            'time_seconds': parser.parse(result['time_str']),
                            'status': result['status'],
                            'surface': rally_data.get('surface', 'gravel'),
                        }
                        all_results.append(row)

                # Metrikleri güncelle
                metric_rally.metric("✅ Rally", rally_count)
                metric_404.metric("❌ 404", not_found_count)
                metric_results.metric("📊 Sonuç", total_results)

                # Tablo güncelle
                if rally_details:
                    results_placeholder.dataframe(
                        pd.DataFrame(rally_details),
                        use_container_width=True,
                        hide_index=True
                    )

            except Exception as e:
                if '404' in str(e):
                    not_found_count += 1
                    metric_404.metric("❌ 404", not_found_count)
                st.session_state.logger.error(f"Rally {rally_id} error: {e}")

        # Database'e toplu kaydet
        if all_results:
            status_text.text("💾 Database'e kaydediliyor...")
            df = pd.DataFrame(all_results)
            db.save_dataframe(df, 'stage_results', if_exists='append')

        progress_bar.progress(1.0)
        status_text.text("✅ Scraping tamamlandı!")

        st.success(f"""
        ✅ **Scraping Tamamlandı!**

        - ✅ Rally bulundu: **{rally_count}**
        - 📊 Toplam sonuç: **{total_results:,}**
        - ⏭️ Atlanan (Baja/Offroad): **{skip_count}**
        - ❌ Bulunamayan (404): **{not_found_count}**
        """)

        st.balloons()

# ========== VERİ İŞLEME ==========
elif page == "🧹 Veri İşleme":
    st.header("🧹 Veri İşleme")

    if not status['database']:
        st.warning("⚠️ Önce veri toplamalısınız!")
        st.stop()

    st.success(f"✅ Mevcut ham veri: {status['data_count']:,} sonuç")

    # Adım 1: Veri Temizleme
    st.subheader("1️⃣ Veri Temizleme")
    st.markdown("Anomali tespiti ve geçersiz sonuçların temizlenmesi")

    if st.button("🧹 Veriyi Temizle", type="primary"):
        with st.spinner("Temizleniyor..."):
            try:
                cleaner = DataCleaner()
                clean_df = cleaner.clean()

                st.success(f"✅ Temizleme tamamlandı! {len(clean_df):,} temiz sonuç oluşturuldu.")

                # İstatistikler
                try:
                    anomaly_df = st.session_state.db.load_dataframe(
                        "SELECT COUNT(*) as count FROM stage_results WHERE is_anomaly = 1"
                    )
                    anomaly_count = int(anomaly_df.iloc[0]['count'])
                except:
                    anomaly_count = status['data_count'] - len(clean_df)

                col1, col2, col3 = st.columns(3)
                col1.metric("Temiz Veri", f"{len(clean_df):,}")
                col2.metric("Anomali", f"{anomaly_count:,}")
                total_count = len(clean_df) + anomaly_count
                anomaly_ratio = (anomaly_count / total_count * 100) if total_count > 0 else 0.0
                col3.metric("Anomali Oranı", f"{anomaly_ratio:.1f}%")

                # Refresh status
                st.rerun()

            except Exception as e:
                st.error(f"❌ Hata: {e}")
                st.session_state.logger.error(f"Cleaning error: {e}")

    st.markdown("---")

    # Adım 2: Feature Engineering
    st.subheader("2️⃣ Feature Engineering")
    st.markdown("Makine öğrenimi için özelliklerin oluşturulması")

    # Re-check clean data status (in case just cleaned)
    try:
        clean_check = st.session_state.db.load_dataframe("SELECT COUNT(*) as count FROM clean_stage_results")
        current_clean_count = int(clean_check.iloc[0]['count'])
        has_clean_data = current_clean_count > 0
    except:
        has_clean_data = False
        current_clean_count = 0

    if not has_clean_data:
        st.warning("⚠️ Önce veri temizleme yapmalısınız!")
    else:
        st.info(f"✅ Temiz veri hazır: {current_clean_count:,} sonuç")

        if st.button("⚙️ Feature Oluştur", type="primary"):
            with st.spinner("Feature engineering yapılıyor... (Bu 1-2 dakika sürebilir)"):
                try:
                    df = st.session_state.db.load_dataframe("SELECT * FROM clean_stage_results")

                    progress = st.progress(0)
                    progress.progress(0.2)

                    engineer = FeatureEngineer()
                    features = engineer.engineer_all(df)

                    progress.progress(0.8)

                    # Save
                    Path('data/processed').mkdir(parents=True, exist_ok=True)
                    features.to_parquet('data/processed/features.parquet')

                    progress.progress(1.0)

                    st.success(f"✅ Feature engineering tamamlandı!")

                    col1, col2 = st.columns(2)
                    col1.metric("Veri Sayısı", f"{len(features):,}")
                    col2.metric("Feature Sayısı", len(features.columns))

                    # Örnek feature'lar göster
                    with st.expander("🔍 Feature Listesi (İlk 30)"):
                        feature_list = [col for col in features.columns
                                      if col not in ['rally_id', 'driver_id', 'stage_id', 'time_seconds']]
                        for i, feat in enumerate(feature_list[:30], 1):
                            st.text(f"{i:2d}. {feat}")

                    # Refresh status
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Hata: {e}")
                    st.session_state.logger.error(f"Feature engineering error: {e}")

# ========== MODEL EĞİTİMİ ==========
elif page == "🎓 Model Eğitimi":
    st.header("🎓 Model Eğitimi")

    if not status['features']:
        st.warning("⚠️ Önce feature engineering yapmalısınız!")
        st.stop()

    st.success("✅ Feature data hazır")

    # Feature bilgisi göster
    try:
        df = pd.read_parquet('data/processed/features.parquet')
        col1, col2, col3 = st.columns(3)
        col1.metric("Toplam Veri", f"{len(df):,}")
        col2.metric("Feature Sayısı", len(df.columns))
        col3.metric("Sınıf Sayısı", df['car_class'].nunique() if 'car_class' in df.columns else "?")
    except:
        st.error("Feature dosyası okunamadı!")
        st.stop()

    st.markdown("---")

    # Model parametreleri
    with st.expander("⚙️ Model Parametreleri (LightGBM)"):
        col1, col2 = st.columns(2)

        with col1:
            n_estimators = st.slider("N Estimators", 100, 1000, 500, 50)
            learning_rate = st.slider("Learning Rate", 0.01, 0.1, 0.03, 0.01)
            max_depth = st.slider("Max Depth", 3, 15, 8)

        with col2:
            num_leaves = st.slider("Num Leaves", 15, 63, 31)
            min_child_samples = st.slider("Min Child Samples", 10, 50, 20)

    st.markdown("---")

    # Eğitim butonu
    if st.button("🎓 Modeli Eğit", type="primary", use_container_width=True):
        with st.spinner("Model eğitiliyor... (Bu 2-5 dakika sürebilir)"):
            try:
                df = pd.read_parquet('data/processed/features.parquet')

                progress = st.progress(0)
                status_msg = st.empty()

                # Initialize model
                status_msg.text("Model hazırlanıyor...")
                model = RallyETAModel()
                progress.progress(0.1)

                # Split
                status_msg.text("Veri bölünüyor...")
                train_df, val_df, test_df = model.prepare_data_split(df)
                progress.progress(0.2)

                st.info(f"📊 Train: {len(train_df):,} | Val: {len(val_df):,} | Test: {len(test_df):,}")

                # Train
                status_msg.text("Model eğitiliyor...")
                model.train(train_df, val_df)
                progress.progress(0.7)

                # Evaluate
                status_msg.text("Değerlendiriliyor...")
                val_metrics = model.evaluate(val_df, "Validation")
                test_metrics = model.evaluate(test_df, "Test")
                progress.progress(0.9)

                # Save
                status_msg.text("Kaydediliyor...")
                model.save()

                # Save metrics (exclude numpy arrays for JSON)
                metrics_output = {
                    'validation': {
                        'mae': float(val_metrics['mae']),
                        'mape': float(val_metrics['mape']),
                        'correlation': float(val_metrics['correlation'])
                    },
                    'test': {
                        'mae': float(test_metrics['mae']),
                        'mape': float(test_metrics['mape']),
                        'correlation': float(test_metrics['correlation'])
                    },
                    'timestamp': datetime.now().isoformat(),
                    'data_size': {
                        'train': len(train_df),
                        'val': len(val_df),
                        'test': len(test_df)
                    }
                }

                Path('models/rally_eta_v1').mkdir(parents=True, exist_ok=True)
                with open('models/rally_eta_v1/evaluation_metrics.json', 'w') as f:
                    json.dump(metrics_output, f, indent=2)

                progress.progress(1.0)
                status_msg.text("✅ Tamamlandı!")

                # Sonuçları göster
                st.success("✅ Model eğitimi tamamlandı!")

                col1, col2, col3, col4 = st.columns(4)

                col1.metric("Test MAPE", f"{test_metrics['mape']:.2f}%",
                           "✅" if test_metrics['mape'] < 2.5 else "⚠️")
                col2.metric("Test MAE", f"{test_metrics['mae']:.4f}")
                col3.metric("Test Correlation", f"{test_metrics['correlation']:.4f}")
                col4.metric("Val MAPE", f"{val_metrics['mape']:.2f}%")

                # Feature importance
                if hasattr(model, 'feature_importance') and model.feature_importance is not None:
                    st.markdown("---")
                    st.subheader("📊 Feature Importance (Top 20)")

                    # Convert dict to DataFrame and get top 20
                    importance_df = pd.DataFrame(
                        list(model.feature_importance.items()),
                        columns=['feature', 'importance']
                    ).sort_values('importance', ascending=False).head(20)

                    fig = px.bar(
                        importance_df,
                        x='importance',
                        y='feature',
                        orientation='h',
                        title='En Önemli 20 Feature',
                        labels={'importance': 'Importance Score', 'feature': 'Feature'}
                    )
                    fig.update_layout(
                        yaxis={'categoryorder':'total ascending'},
                        height=600
                    )
                    st.plotly_chart(fig, use_container_width=True)

                st.balloons()

                # Refresh status
                st.rerun()

            except Exception as e:
                st.error(f"❌ Hata: {e}")
                st.session_state.logger.error(f"Training error: {e}")
                import traceback
                st.code(traceback.format_exc())

# ========== TAHMİN YAP ==========
elif page == "🎯 Tahmin Yap":
    st.header("🎯 Yeni Yarış Tahmini")
    st.markdown("Gelecek yarışlar için pilot performansı tahmini")

    if not status['model']:
        st.warning("⚠️ Önce model eğitmelisiniz!")
        st.stop()

    st.success("✅ Model hazır")

    # Tahmin modu seçimi
    st.markdown("---")
    prediction_mode = st.radio(
        "📊 Tahmin Modu:",
        ["🔗 TOSFED Linkinden Otomatik", "✍️ Manuel Giriş"],
        horizontal=True
    )

    if prediction_mode == "🔗 TOSFED Linkinden Otomatik":
        st.markdown("### 🔗 TOSFED Yarış Linki")
        tosfed_url = st.text_input(
            "TOSFED Yarış Linki",
            placeholder="https://sonuc.tosfed.org.tr/yaris/123/",
            help="Örnek: https://sonuc.tosfed.org.tr/yaris/123/"
        )

        if tosfed_url:
            if st.button("📥 Yarış Bilgilerini Çek", use_container_width=True):
                with st.spinner("TOSFED'den veriler çekiliyor..."):
                    try:
                        from src.scraper.tosfed_sonuc_scraper import TOSFEDSonucScraper
                        scraper = TOSFEDSonucScraper()

                        # Extract rally ID from URL
                        import re
                        match = re.search(r'/yaris/(\d+)', tosfed_url)
                        if not match:
                            st.error("❌ Geçersiz TOSFED linki!")
                            st.stop()

                        rally_id = int(match.group(1))

                        # Scrape rally data
                        rally_info = scraper.fetch_rally_stages(rally_id)

                        if rally_info and 'stages' in rally_info and len(rally_info['stages']) > 0:
                            # Convert stages to DataFrame
                            stages_list = []
                            for stage in rally_info['stages']:
                                # Stage data is directly in the dict, not under 'stage_info'
                                stages_list.append({
                                    'stage_name': stage.get('stage_name', 'N/A'),
                                    'stage_number': stage.get('stage_number', 0),
                                    'stage_length_km': stage.get('stage_length_km', 0),
                                    'surface': rally_info.get('surface', 'gravel')
                                })

                            rally_data_df = pd.DataFrame(stages_list)

                            # Filter out stages with 0 km (invalid)
                            rally_data_df = rally_data_df[rally_data_df['stage_length_km'] > 0]

                            if len(rally_data_df) > 0:
                                st.success(f"✅ {len(rally_data_df)} etap bilgisi çekildi!")
                                st.session_state['scraped_rally_data'] = rally_data_df
                                st.session_state['rally_url'] = tosfed_url
                                st.session_state['rally_name'] = rally_info.get('rally_name', 'Bilinmeyen Yarış')
                            else:
                                st.error("❌ Geçerli etap bulunamadı! (Tüm etaplar 0 km)")
                        else:
                            st.error("❌ Yarış verileri çekilemedi veya etap bulunamadı!")
                    except Exception as e:
                        st.error(f"❌ Hata: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        # Show scraped data if available
        if 'scraped_rally_data' in st.session_state:
            rally_data = st.session_state['scraped_rally_data']

            st.markdown("---")
            st.subheader("📋 Etap Seçimi")

            # Extract unique stages
            stages = rally_data[['stage_name', 'stage_number', 'stage_length_km', 'surface']].drop_duplicates()
            stage_options = {
                f"SS{row['stage_number']} - {row['stage_name']} ({row['stage_length_km']}km, {row['surface']})": idx
                for idx, row in stages.iterrows()
            }

            selected_stage_label = st.selectbox("Etap Seç", list(stage_options.keys()))
            selected_stage_idx = stage_options[selected_stage_label]
            selected_stage = stages.loc[selected_stage_idx]

            # Show stage info
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📏 Uzunluk", f"{selected_stage['stage_length_km']} km")
            with col2:
                st.metric("🛣️ Yüzey", selected_stage['surface'].title())
            with col3:
                st.metric("🔢 Etap No", f"SS{selected_stage['stage_number']}")

            st.markdown("---")
            st.subheader("👤 Pilot Seçimi")

            # Get available drivers from database
            drivers = st.session_state.db.load_dataframe(
                "SELECT DISTINCT driver_id, driver_name, car_class FROM clean_stage_results ORDER BY driver_name"
            )

            driver_options = {f"{row['driver_name']} ({row['car_class']})": row['driver_id']
                            for _, row in drivers.iterrows()}

            selected_driver_label = st.selectbox("Pilot Seç", list(driver_options.keys()))
            selected_driver_id = driver_options[selected_driver_label]

            st.markdown("---")

            # Prediction button for TOSFED mode
            if st.button("🎯 Tahmin Et", type="primary", use_container_width=True, key="tosfed_predict"):
                with st.spinner("Tahmin yapılıyor..."):
                    try:
                        predictor = NotionalTimePredictor()
                        
                        # Extract driver name from selected label (format: "Driver Name (Class)")
                        selected_driver_name = selected_driver_label.rsplit(" (", 1)[0]

                        prediction = predictor.predict_for_manual_input(
                            driver_id=selected_driver_id,
                            driver_name=selected_driver_name,  # Pass driver name from UI
                            stage_length_km=selected_stage['stage_length_km'],
                            surface=selected_stage['surface'],
                            day_or_night='day',  # Can be extracted from TOSFED if available
                            stage_number=selected_stage['stage_number'],
                            rally_name=st.session_state['rally_url']
                        )

                        st.success("✅ Tahmin tamamlandı!")

                        # Show results (same as manual mode)
                        st.markdown("---")
                        st.subheader("📊 Tahmin Sonuçları")

                        col1, col2, col3, col4 = st.columns(4)

                        with col1:
                            st.metric("⏱️ Tahmini Zaman", prediction['predicted_time_str'])

                        with col2:
                            st.metric("🏎️ Ortalama Hız", f"{prediction['predicted_speed_kmh']} km/h")

                        with col3:
                            st.metric(
                                "📊 Oran",
                                f"{prediction['predicted_ratio']:.3f}",
                                delta=f"{(prediction['predicted_ratio']-1)*100:.1f}%"
                            )

                        with col4:
                            st.metric(
                                "🎯 Momentum",
                                prediction['momentum'],
                                delta=f"{prediction['momentum_delta']:+.1f}%"
                            )

                        st.info(f"📌 **Referans Zaman**: {prediction['reference_time_str']}")

                        with st.expander("💡 Açıklama"):
                            st.write(prediction['explanation'])

                    except Exception as e:
                        st.error(f"❌ Hata: {e}")
                        import traceback
                        st.code(traceback.format_exc())

    else:  # Manuel Giriş
        st.markdown("### ✍️ Manuel Etap Bilgileri")

        col1, col2 = st.columns(2)

        with col1:
            stage_length = st.number_input(
                "📏 Etap Uzunluğu (km)",
                min_value=1.0,
                max_value=50.0,
                value=15.0,
                step=0.5
            )

            surface = st.selectbox(
                "🛣️ Yüzey Tipi",
                ["gravel", "asphalt"]
            )

        with col2:
            day_or_night = st.selectbox(
                "🌞 Zaman",
                ["day", "night"]
            )

            stage_number = st.number_input(
                "🔢 Etap Numarası",
                min_value=1,
                max_value=30,
                value=1
            )

        st.markdown("---")
        st.subheader("👤 Pilot Seçimi")

        # Get available drivers from database
        drivers = st.session_state.db.load_dataframe(
            "SELECT DISTINCT driver_id, driver_name, car_class FROM clean_stage_results ORDER BY driver_name"
        )

        if len(drivers) == 0:
            st.warning("❌ Veritabanında pilot bulunamadı!")
            st.stop()

        driver_options = {f"{row['driver_name']} ({row['car_class']})": row['driver_id']
                        for _, row in drivers.iterrows()}

        selected_driver_label = st.selectbox("Pilot Seç", list(driver_options.keys()))
        selected_driver_id = driver_options[selected_driver_label]

        # Get driver info
        driver_info = drivers[drivers['driver_id'] == selected_driver_id].iloc[0]

        st.markdown("---")
        st.subheader("📊 Pilot İstatistikleri")

        # Calculate driver momentum (last 3-5 races trend)
        # Calculate class_best_time per stage by finding minimum time in each class
        driver_history = st.session_state.db.load_dataframe(f"""
            WITH stage_class_best AS (
                SELECT stage_id, car_class, MIN(time_seconds) as class_best_time
                FROM clean_stage_results
                WHERE time_seconds > 0
                GROUP BY stage_id, car_class
            )
            SELECT c.rally_date, c.rally_name, c.stage_name, c.surface, c.stage_length_km,
                   c.time_seconds, s.class_best_time,
                   CAST(c.time_seconds AS REAL) / CAST(s.class_best_time AS REAL) as ratio_to_class_best
            FROM clean_stage_results c
            INNER JOIN stage_class_best s
                ON c.stage_id = s.stage_id AND c.car_class = s.car_class
            WHERE c.driver_id = '{selected_driver_id}'
            AND s.class_best_time > 0
            ORDER BY c.rally_date DESC, c.stage_number DESC
            LIMIT 15
        """)

        if len(driver_history) > 0:
            col1, col2, col3 = st.columns(3)

            with col1:
                avg_ratio = driver_history['ratio_to_class_best'].mean()
                st.metric(
                    "⏱️ Ortalama Oran",
                    f"{avg_ratio:.3f}",
                    delta=f"{(avg_ratio-1)*100:.1f}% sınıf liderinden yavaş"
                )

            with col2:
                surface_history = driver_history[driver_history['surface'] == surface]
                if len(surface_history) > 0:
                    surface_avg = surface_history['ratio_to_class_best'].mean()
                    st.metric(
                        f"🛣️ {surface.title()} Ort.",
                        f"{surface_avg:.3f}"
                    )
                else:
                    st.metric(f"🛣️ {surface.title()} Ort.", "N/A")

            with col3:
                # Momentum: Last 5 vs Previous 5
                if len(driver_history) >= 10:
                    recent_5 = driver_history.iloc[:5]['ratio_to_class_best'].mean()
                    prev_5 = driver_history.iloc[5:10]['ratio_to_class_best'].mean()
                    momentum = prev_5 - recent_5  # Positive = getting faster

                    if momentum > 0.02:
                        momentum_str = "📈 Hızlanıyor"
                        momentum_color = "normal"
                    elif momentum < -0.02:
                        momentum_str = "📉 Yavaşlıyor"
                        momentum_color = "inverse"
                    else:
                        momentum_str = "➡️ Stabil"
                        momentum_color = "off"

                    st.metric(
                        "🎯 Momentum",
                        momentum_str,
                        delta=f"{momentum*100:.1f}%",
                        delta_color=momentum_color
                    )
                else:
                    st.metric("🎯 Momentum", "Yetersiz veri")

            # Show recent races
            with st.expander("📜 Son Yarışlar"):
                display_history = driver_history.head(5)[[
                    'rally_name', 'stage_name', 'surface', 'ratio_to_class_best'
                ]].copy()
                display_history.columns = ['Yarış', 'Etap', 'Yüzey', 'Oran']
                st.dataframe(display_history, use_container_width=True, hide_index=True)

        st.markdown("---")

        # Prediction button
        if st.button("🎯 Tahmin Et", type="primary", use_container_width=True):
            with st.spinner("Tahmin yapılıyor..."):
                try:
                    predictor = NotionalTimePredictor()
                    
                    # Extract driver name from selected label (format: "Driver Name (Class)")
                    selected_driver_name = selected_driver_label.rsplit(" (", 1)[0]

                    prediction = predictor.predict_for_manual_input(
                        driver_id=selected_driver_id,
                        driver_name=selected_driver_name,  # Pass the selected driver name from UI
                        stage_length_km=stage_length,
                        surface=surface,
                        day_or_night=day_or_night,
                        stage_number=stage_number,
                        rally_name="Manuel T ahmin"
                    )

                    st.success("✅ Tahmin tamamlandı!")

                    # Show results
                    st.markdown("---")
                    st.subheader("📊 Tahmin Sonuçları")

                    # Main metrics
                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        st.metric(
                            "⏱️ Tahmini Zaman",
                            prediction['predicted_time_str'],
                            help="Pilot için tahmini etap zamanı"
                        )

                    with col2:
                        st.metric(
                            "🏎️ Ortalama Hız",
                            f"{prediction['predicted_speed_kmh']} km/h"
                        )

                    with col3:
                        st.metric(
                            "📊 Oran",
                            f"{prediction['predicted_ratio']:.3f}",
                            delta=f"{(prediction['predicted_ratio']-1)*100:.1f}% sınıf liderinden yavaş"
                        )

                    with col4:
                        st.metric(
                            "🎯 Momentum",
                            prediction['momentum'],
                            delta=f"{prediction['momentum_delta']:+.1f}%"
                        )

                    # Reference time
                    st.info(f"📌 **Referans Zaman** (sınıf lideri tahmini): {prediction['reference_time_str']}")

                    # Explanation
                    with st.expander("💡 Açıklama"):
                        st.write(prediction['explanation'])

                        st.markdown("**Momentum Detayları:**")
                        st.write(f"- Son 5 yarış ortalaması: {prediction['recent_avg_ratio']:.3f}")
                        st.write(f"- Önceki 5 yarış ortalaması: {prediction['historical_avg_ratio']:.3f}")
                        st.write(f"- Trend: {prediction['momentum']}")

                    # Detailed table
                    st.markdown("---")
                    st.subheader("📋 Detaylı Bilgiler")

                    details_df = pd.DataFrame([{
                        'Pilot': prediction['driver_name'],
                        'Sınıf': prediction['car_class'],
                        'Etap Uzunluğu': f"{prediction['stage_length_km']} km",
                        'Yüzey': prediction['surface'].title(),
                        'Zaman': prediction['day_or_night'].title(),
                        'Tahmini Zaman': prediction['predicted_time_str'],
                        'Ortalama Hız': f"{prediction['predicted_speed_kmh']} km/h",
                        'Oran': f"{prediction['predicted_ratio']:.3f}",
                        'Momentum': prediction['momentum']
                    }])

                    st.dataframe(details_df, use_container_width=True, hide_index=True)

                    # Export button
                    st.markdown("---")
                    col1, col2 = st.columns(2)

                    with col1:
                        # Save to session for later export
                        if 'predictions' not in st.session_state:
                            st.session_state.predictions = []

                        st.session_state.predictions.append(prediction)

                        st.success(f"✅ {len(st.session_state.predictions)} tahmin kaydedildi")

                    with col2:
                        if st.button("📥 Tahminleri İndir (CSV)", use_container_width=True):
                            predictions_df = pd.DataFrame(st.session_state.predictions)
                            csv = predictions_df.to_csv(index=False)
                            st.download_button(
                                "💾 CSV İndir",
                                csv,
                                file_name=f"tahminler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv",
                                use_container_width=True
                            )

                except Exception as e:
                    st.error(f"❌ Hata: {e}")
                    st.session_state.logger.error(f"Manual prediction error: {e}")
                    import traceback
                    st.code(traceback.format_exc())

# ========== RAPORLAR ==========
elif page == "📊 Raporlar":
    st.header("📊 Raporlar ve Analizler")

    if not status['database']:
        st.warning("⚠️ Henüz veri yok!")
        st.stop()

    tab1, tab2, tab3 = st.tabs(["📈 Veri İstatistikleri", "🎯 Model Analizi", "🏁 Rally Özeti"])

    with tab1:
        st.subheader("📈 Veri İstatistikleri")

        try:
            # Genel istatistikler
            stats_query = """
            SELECT
                COUNT(*) as total_results,
                COUNT(DISTINCT rally_id) as total_rallies,
                COUNT(DISTINCT driver_name) as total_drivers,
                COUNT(DISTINCT car_class) as total_classes
            FROM stage_results
            """
            stats_df = st.session_state.db.load_dataframe(stats_query)

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Toplam Sonuç", f"{stats_df.iloc[0]['total_results']:,}")
            col2.metric("Toplam Ralli", f"{stats_df.iloc[0]['total_rallies']}")
            col3.metric("Toplam Pilot", f"{stats_df.iloc[0]['total_drivers']}")
            col4.metric("Sınıf Sayısı", f"{stats_df.iloc[0]['total_classes']}")

            # Sınıf dağılımı
            st.markdown("---")
            class_query = """
            SELECT car_class, COUNT(*) as count
            FROM stage_results
            GROUP BY car_class
            ORDER BY count DESC
            """
            class_df = st.session_state.db.load_dataframe(class_query)

            fig = px.pie(class_df, values='count', names='car_class',
                        title='Sınıf Dağılımı')
            st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f"İstatistik yüklenemedi: {e}")

    with tab2:
        st.subheader("🎯 Model Analizi")

        if not status['model'] or not status['model_metrics']:
            st.warning("Model henüz eğitilmemiş!")
        else:
            metrics = status['model_metrics']

            # Test metrikleri
            test = metrics.get('test', {})
            val = metrics.get('validation', {})

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Test Set**")
                st.metric("MAPE", f"{test.get('mape', 0):.2f}%")
                st.metric("MAE", f"{test.get('mae_seconds', 0):.2f}s")
                st.metric("R²", f"{test.get('r2', 0):.4f}")

            with col2:
                st.markdown("**Validation Set**")
                st.metric("MAPE", f"{val.get('mape', 0):.2f}%")
                st.metric("MAE", f"{val.get('mae_seconds', 0):.2f}s")
                st.metric("R²", f"{val.get('r2', 0):.4f}")

    with tab3:
        st.subheader("🏁 Rally Özeti")

        try:
            rally_query = """
            SELECT
                rally_name,
                COUNT(DISTINCT stage_id) as stages,
                COUNT(*) as results
            FROM stage_results
            GROUP BY rally_id, rally_name
            ORDER BY rally_id DESC
            LIMIT 10
            """
            rally_df = st.session_state.db.load_dataframe(rally_query)

            st.dataframe(rally_df, use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Rally özeti yüklenemedi: {e}")

# ========== AYARLAR ==========
elif page == "⚙️ Ayarlar":
    st.header("⚙️ Ayarlar")

    tab1, tab2, tab3 = st.tabs(["🗄️ Database", "🗑️ Temizlik", "ℹ️ Hakkında"])

    with tab1:
        st.subheader("🗄️ Database Yönetimi")

        db_path = config.get('data.raw_db_path')
        st.info(f"📊 Database: `{db_path}`")

        # Database stats
        if os.path.exists(db_path):
            db_size = os.path.getsize(db_path) / (1024 * 1024)  # MB
            st.metric("📁 Database Boyutu", f"{db_size:.1f} MB")

        st.markdown("---")

        # Backup/Restore section
        st.markdown("### 💾 Yedekleme & Geri Yükleme")
        st.caption("Toplanan veriyi kaydedin veya daha önce kaydedilmiş veriyi yükleyin")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**📤 Database'i İndir**")
            st.caption("Mevcut veriyi bilgisayarınıza kaydedin")

            if os.path.exists(db_path):
                with open(db_path, 'rb') as f:
                    db_bytes = f.read()

                st.download_button(
                    label="📥 Database İndir (.db)",
                    data=db_bytes,
                    file_name=f"rally_results_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                    mime="application/x-sqlite3",
                    use_container_width=True,
                    help="Mevcut database'i yedeğini indirin"
                )
            else:
                st.warning("Database dosyası bulunamadı")

        with col2:
            st.markdown("**📥 Database Yükle**")
            st.caption("Daha önce kaydedilmiş .db dosyasını yükleyin")

            uploaded_file = st.file_uploader(
                "Database dosyası seçin",
                type=['db'],
                help="Rally veri database'inizi (.db) yükleyin",
                key="db_upload"
            )

            if uploaded_file is not None:
                st.info(f"📁 Seçilen dosya: {uploaded_file.name} ({uploaded_file.size / (1024*1024):.1f} MB)")

                if st.button("✅ Yükle ve Değiştir", type="primary", use_container_width=True, key="db_upload_btn"):
                    try:
                        # Backup current if exists
                        if os.path.exists(db_path):
                            backup_path = db_path.replace('.db', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
                            import shutil
                            shutil.copy2(db_path, backup_path)
                            st.info(f"✅ Mevcut database yedeklendi: {backup_path}")

                        # Create directory if not exists
                        os.makedirs(os.path.dirname(db_path), exist_ok=True)

                        # Write uploaded file
                        with open(db_path, 'wb') as f:
                            f.write(uploaded_file.getvalue())

                        # Reinitialize database connection
                        st.session_state.db = Database()

                        st.success("✅ Database başarıyla yüklendi!")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ Hata: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        st.markdown("---")

        # Other database operations
        st.markdown("### 🔧 Database İşlemleri")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("🔄 Bağlantıyı Yenile", use_container_width=True):
                st.session_state.db = Database()
                st.success("✅ Yenilendi!")
                st.rerun()

        with col2:
            if st.button("📊 Tablo Listesi", use_container_width=True):
                try:
                    tables = st.session_state.db.load_dataframe(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                    st.dataframe(tables, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"Hata: {e}")

    with tab2:
        st.subheader("🗑️ Veri Temizliği")

        st.warning("⚠️ Bu işlemler geri alınamaz!")

        if st.button("🗑️ Tüm Ham Veriyi Sil", type="secondary"):
            if st.checkbox("Eminim, sil"):
                try:
                    st.session_state.db.get_connection().execute("DELETE FROM stage_results")
                    st.success("✅ Silindi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

        if st.button("🗑️ Temiz Veriyi Sil", type="secondary"):
            if st.checkbox("Eminim, temiz veriyi sil"):
                try:
                    st.session_state.db.get_connection().execute("DELETE FROM clean_stage_results")
                    st.success("✅ Silindi!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

    with tab3:
        st.subheader("ℹ️ Hakkında")

        st.markdown("""
        ### Rally ETA Tahmin Sistemi

        **Versiyon:** 1.0.0

        **Geliştirici:** Rally Data Science Team

        **Amaç:** Kırmızı bayrak durumlarında pilotlar için notional time tahmini

        **Teknolojiler:**
        - Python 3.9+
        - Streamlit
        - LightGBM
        - Pandas, Plotly
        - SQLite

        **Lisans:** MIT

        ---

        **Destek:** github.com/rally-eta
        """)
