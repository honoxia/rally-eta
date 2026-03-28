# Rally ETA v2.0 - Segmentasyon Dokümantasyonu

## Proje Amacı

Rally ETA, yarış sırasında herhangi bir nedenle duran veya derecesi olmayan pilotlara **notional time (tahmini derece)** hesaplayan bir sistemdir.

Tahmin şu verilere dayanır:
1. **Tarihi veriler:** Eski yarış sonuçları (TOSFED'den çekilen)
2. **Geometrik özellikler:** Etap rotasının KML analizinden çıkarılan metrikler (curvature, elevation, hairpin sayısı vb.)
3. **Makine öğrenmesi:** Pilot performansı ve etap zorluğunu modelleyen algoritma

---

## Neden Segmentasyon?

### Problemler
- `app.py` tek dosyada 1174 satır kod
- Bir özellik değiştiğinde tüm dosyayı anlamak gerekiyor
- Test etmesi zor
- Birden fazla kişi aynı anda çalışamaz

### Hedefler
- Her segment bağımsız geliştirilebilir olmalı
- Bir segmentten çıkan veri, diğer segmentler için **kullanıma hazır** olmalı
- EXE oluştururken tüm segmentler otomatik birleşmeli

---

## Veri Akışı (Data Pipeline)

```
┌─────────────────┐
│    SCRAPER      │  Rally ID → TOSFED'den veri çek
│   scraper.py    │
└────────┬────────┘
         │
         ▼ stage_results (SQLite tablo)
         │
         │  Kolonlar: rally_id, stage_id, driver_id, driver_name,
         │            time_seconds, stage_length_km, surface, car_class...
         │
┌────────┴────────┐
│   KML MANAGER   │  KML dosyaları + stage_results → geometrik analiz
│  kml_manager.py │
└────────┬────────┘
         │
         ▼ stages_metadata (SQLite tablo)
         │
         │  Kolonlar: stage_id, distance_km, curvature_density, p95_curvature,
         │            max_grade, hairpin_count, straight_ratio, total_ascent...
         │
┌────────┴────────┐
│    TRAINING     │  stage_results + stages_metadata → model eğit
│   training.py   │
└────────┬────────┘
         │
         ▼ geometric_model_latest.pkl (dosya)
         │
         │  İçerik: Eğitilmiş ML modeli + feature listesi + metrikler
         │
┌────────┴────────┐
│   PREDICTION    │  model + pilot + etap bilgisi → tahmin
│  prediction.py  │
└────────┬────────┘
         │
         ▼ Tahmin Sonucu
         │
         │  Çıktı: predicted_time_str, predicted_speed_kmh,
         │         predicted_ratio, confidence_level
```

---

## Segment Yapısı

```
D:\claude\Rally Eta v2\faz2\segment\
│
├── segment.md           ← Bu döküman
├── app.py               ← Ana router (sayfa yönlendirme)
│
├── pages/
│   ├── __init__.py
│   ├── home.py          ← Ana sayfa / Dashboard
│   ├── scraper.py       ← TOSFED veri çekme + DB yükleme
│   ├── kml_manager.py   ← KML yükleme, eşleştirme, analiz, export/import
│   ├── training.py      ← Model eğitimi
│   ├── prediction.py    ← Tekli + Toplu tahmin
│   └── settings.py      ← Ayarlar
│
└── shared/
    ├── __init__.py
    ├── config.py        ← Sabit değerler, varsayılan yollar
    ├── db_helpers.py    ← DB bağlantı, tablo oluşturma/kontrol
    ├── data_loaders.py  ← Pilot/rally/KML listesi yükleme
    └── ui_components.py ← Ortak UI bileşenleri (HTML tablo vb.)
```

---

## Segment Detayları

### 1. shared/config.py
**Amaç:** Merkezi konfigürasyon

**İçerik:**
- Varsayılan DB yolu
- Varsayılan KML klasörü
- Model klasörü
- Sabit değerler (surface tipleri, status değerleri vb.)

**Bağımlılık:** Yok (en temel modül)

---

### 2. shared/db_helpers.py
**Amaç:** Veritabanı işlemleri

**İçerik:**
- `get_db_connection()` - SQLite bağlantısı
- `ensure_tables_exist()` - Tablo oluşturma
- `get_database_info()` - DB istatistikleri

**Bağımlılık:** config.py

**Output:** DB bağlantısı, tablo durumu

---

### 3. shared/data_loaders.py
**Amaç:** Veri yükleme fonksiyonları

**İçerik:**
- `get_driver_list()` - Pilot listesi
- `get_rally_list()` - Ralli listesi
- `get_kml_files()` - KML dosya listesi
- `get_stage_metadata_df()` - Geometrik veri

**Bağımlılık:** config.py, db_helpers.py

**Output:** DataFrame veya dict listesi (kullanıma hazır)

---

### 4. shared/ui_components.py
**Amaç:** Tekrar eden UI elementleri

**İçerik:**
- `show_html_table()` - DataFrame'i HTML tablo olarak göster
- `show_db_status()` - DB durumu widget'ı
- CSS stilleri

**Bağımlılık:** Yok (sadece Streamlit)

---

### 5. pages/home.py
**Amaç:** Dashboard / Ana sayfa

**Gösterilen:**
- Toplam sonuç sayısı
- Pilot sayısı
- KML dosya sayısı
- Model durumu
- Kullanım adımları

**Bağımlılık:** shared/*

---

### 6. pages/scraper.py
**Amaç:** Veri toplama

**Fonksiyonlar:**
- TOSFED'den rally verisi çekme
- Harici DB dosyası yükleme
- Geometrik veri export/import (.db formatı)

**Input:** Rally ID aralığı veya .db dosyası

**Output:** `stage_results` tablosu (dolu)

**Bağımlılık:** shared/*, src/scraper/*

---

### 7. pages/kml_manager.py
**Amaç:** KML dosya yönetimi ve geometrik analiz

**Fonksiyonlar:**
- KML/KMZ dosya yükleme
- KML-Rally eşleştirme (otomatik + manuel)
- Tek etap analizi
- Geometrik veri durumu görüntüleme
- Excel export/import

**Input:** KML dosyaları + stage_results

**Output:** `stages_metadata` tablosu (dolu)

**Bağımlılık:** shared/*, src/stage_analyzer/*, src/data/*

---

### 8. pages/training.py
**Amaç:** ML model eğitimi

**Fonksiyonlar:**
- Eğitim verisi hazırlama (stage_results + stages_metadata JOIN)
- Model eğitimi
- Metrik gösterimi (MAE, RMSE, MAPE)

**Input:** stage_results + stages_metadata

**Output:** `models/geometric_model_latest.pkl`

**Bağımlılık:** shared/*, src/ml/*

---

### 9. pages/prediction.py
**Amaç:** Tahmin yapma

**Fonksiyonlar:**
- Tekli tahmin (bir pilot, manuel etap bilgisi)
- Toplu tahmin (birden fazla pilot, aynı etap)
- Sonuç export (CSV)

**Input:** model.pkl + pilot seçimi + etap parametreleri

**Output:** Tahmin sonuçları (ekranda + CSV)

**Bağımlılık:** shared/*, src/prediction/*

---

### 10. pages/settings.py
**Amaç:** Uygulama ayarları

**Fonksiyonlar:**
- DB yolu değiştirme
- KML klasörü değiştirme
- Versiyon bilgisi

**Bağımlılık:** shared/config.py

---

### 11. app.py (Ana Router)
**Amaç:** Sayfa yönlendirme

**Fonksiyonlar:**
- Streamlit page config
- Sidebar navigasyon
- Sayfa import ve render

**Bağımlılık:** pages/*, shared/*

---

## Segment Arası Veri Kontratları

### stage_results Tablosu (Scraper → Diğerleri)
| Kolon | Tip | Açıklama | Zorunlu |
|-------|-----|----------|---------|
| rally_id | TEXT | Ralli ID | Evet |
| stage_id | TEXT | Etap ID (rally_id + ss + no) | Evet |
| driver_id | TEXT | Pilot ID | Evet |
| driver_name | TEXT | Pilot adı | Evet |
| time_seconds | REAL | Derece (saniye) | Hayır (DNF için 0) |
| stage_length_km | REAL | Etap uzunluğu | Evet |
| surface | TEXT | Zemin tipi | Evet |
| car_class | TEXT | Araç sınıfı | Evet |
| status | TEXT | FINISHED/DNF | Evet |

### stages_metadata Tablosu (KML Manager → Training/Prediction)
| Kolon | Tip | Açıklama | Zorunlu |
|-------|-----|----------|---------|
| stage_id | TEXT | Etap ID (PRIMARY KEY) | Evet |
| distance_km | REAL | Hesaplanan mesafe | Evet |
| curvature_density | REAL | Viraj yoğunluğu | Evet |
| p95_curvature | REAL | 95. persentil curvature | Evet |
| max_grade | REAL | Max eğim | Hayır |
| hairpin_count | INTEGER | Hairpin sayısı | Hayır |
| straight_ratio | REAL | Düz yol oranı | Hayır |
| surface | TEXT | Zemin tipi | Hayır |

### Model Dosyası (Training → Prediction)
- Format: pickle (.pkl)
- İçerik: Trained model + feature names + training metrics
- Konum: `models/geometric_model_latest.pkl`

---

## Geliştirme Kuralları

1. **Bir segmenti değiştirirken** sadece o dosyayı düzenle
2. **Yeni özellik eklerken** hangi segmente ait olduğunu belirle
3. **Shared fonksiyon eklerken** birden fazla segment kullanıyorsa shared'a koy
4. **Veri formatı değişirse** bu dökümanı güncelle
5. **Test ederken** her segmenti bağımsız test et

---

## EXE Oluşturma

Tüm segmentler `app.py` üzerinden import edildiği için:

```bash
cd D:\claude\Rally Eta v2\faz2\segment
pyinstaller --onefile --windowed app.py
```

PyInstaller otomatik olarak:
- pages/*.py
- shared/*.py
- src/* (mevcut modüller)

hepsini tek EXE'ye paketler.

---

## Versiyon Geçmişi

| Tarih | Değişiklik |
|-------|------------|
| 2025-12-31 | Segmentasyon planı oluşturuldu |

---

## Notlar

- Orjinal `app.py` dosyası `D:\claude\Rally Eta v2\faz2\app.py` konumunda korunuyor
- Bu segmentasyon deneysel - sorun çıkarsa orjinale dönülebilir
- Her segment için ayrı test yazılması önerilir
