# Rally ETA v2.0 - Yapılanlar

## 2025-12-31

### 14:00 - Segmentasyon Planlaması
- `app.py` dosyası incelendi (1174 satır, tek dosya)
- Segmentasyon stratejisi belirlendi
- Veri akışı diyagramı oluşturuldu

### 14:05 - Segment Klasörü ve Dokümantasyon
- `D:\claude\Rally Eta v2\faz2\segment\` klasörü oluşturuldu
- `segment.md` dokümantasyon dosyası yazıldı:
  - Proje amacı
  - Neden segmentasyon
  - Veri akışı (pipeline)
  - Klasör yapısı
  - Her segment için input/output tanımları
  - Veri kontratları

### 14:10 - Shared Modülleri Oluşturuldu
```
segment/shared/
├── __init__.py
├── config.py        - Merkezi konfigürasyon, yollar, sabitler
├── db_helpers.py    - Database bağlantı, tablo oluşturma
├── data_loaders.py  - Pilot/rally/KML veri yükleme
└── ui_components.py - Ortak UI bileşenleri (HTML tablo vb.)
```

### 14:15 - Pages Modülleri Oluşturuldu
```
segment/pages/
├── __init__.py
├── home.py          - Ana sayfa / Dashboard
├── scraper.py       - TOSFED veri çekme
├── kml_manager.py   - KML yönetimi ve analiz
├── training.py      - Model eğitimi
├── prediction.py    - Tekli + Toplu tahmin
└── settings.py      - Ayarlar
```

### 14:20 - Ana Router Oluşturuldu
- `segment/app.py` - Sayfa yönlendirme, sidebar navigasyon

### 14:25 - İlk Test
- Tüm modüller başarıyla import edildi
- Streamlit uygulaması çalıştırıldı
- Test sonuçları:
  - DB bağlantısı: OK (146 pilot, 23 ralli)
  - KML dosyaları: OK (19 dosya)

### 14:30 - EXE Builder Güncellendi
- `D:\claude\build_exe.py` segment yapısına uygun güncellendi
- Yeni özellikler:
  - Segment klasörünü paketleme
  - Launcher script oluşturma
  - Data/models/kml-kmz kopyalama

### 14:35 - İlk EXE Build
- Build süresi: 396 saniye (~6.5 dk)
- EXE boyutu: 225 MB
- Hata: Plotly validator dosyası eksik

### 14:40 - EXE Build Düzeltme
- `--collect-all=plotly` eklendi
- Yeniden build: 335 saniye
- EXE boyutu: 192 MB
- Sonuç: Başarılı, uygulama çalışıyor

### 15:00 - Scraper İyileştirmesi
**Problem:**
- Scraper "0 sonuç kaydedildi" hatası
- Hatalar gizleniyor (`except: continue`)
- Ne scrape edildiği görünmüyor
- Excel export yok

**Çözüm - Yeni Scraper Özellikleri:**

1. **Canlı Önizleme**
   - Scrape sonuçları tablo olarak gösterilir
   - Özet istatistikler (ralli/etap/pilot sayısı)

2. **3 Tab Sistemi**
   - Önizleme (sonuç sayısı)
   - Log (detaylı işlem kaydı)
   - Hatalar (ayrı tablo)

3. **Kaydetme Seçenekleri**
   - [Excel'e Kaydet] → exports/ klasörüne
   - [Database'e Kaydet] → SQLite'a
   - [Ikisine de Kaydet]

4. **Gelişmiş Hata Gösterimi**
   - Her hata için: rally_id, stage, driver, error mesajı
   - Hatalar ayrı sekmede listelenir

**Yeni Akış:**
```
Rally ID gir → [Veri Cekmeye Basla]
      ↓
Scrape çalışır (progress bar)
      ↓
Önizleme | Log | Hatalar (3 tab)
      ↓
[Excel'e Kaydet] [Database'e Kaydet] [Ikisine de Kaydet]
```

---

## Dosya Listesi

### Oluşturulan Dosyalar
| Dosya | Satır | Açıklama |
|-------|-------|----------|
| segment/segment.md | ~300 | Dokümantasyon |
| segment/app.py | 68 | Ana router |
| segment/shared/config.py | 92 | Konfigürasyon |
| segment/shared/db_helpers.py | 153 | DB işlemleri |
| segment/shared/data_loaders.py | 175 | Veri yükleme |
| segment/shared/ui_components.py | 118 | UI bileşenleri |
| segment/pages/home.py | 69 | Dashboard |
| segment/pages/scraper.py | 487 | Veri çekme (güncel) |
| segment/pages/kml_manager.py | 370 | KML yönetimi |
| segment/pages/training.py | 100 | Model eğitimi |
| segment/pages/prediction.py | 148 | Tahmin |
| segment/pages/settings.py | 72 | Ayarlar |

### Güncellenen Dosyalar
| Dosya | Değişiklik |
|-------|------------|
| D:\claude\build_exe.py | Segment yapısına uygun güncellendi |

---

### 15:20 - Scraper Hata Düzeltmeleri

**Problem 1: Surface Hatası**
- Tüm ralliler "gravel" olarak kaydediliyordu
- TOSFED sitesinden surface bilgisi gelmiyor
- Çözüm: Kullanıcının manuel seçmesi için dropdown eklendi

**Problem 2: Database 469 Hata**
- Tablo şeması uyumsuzdu (yeni vs eski yapı)
- Çözüm: Eski çalışan tablo yapısına dönüldü

**Yapılan Değişiklikler:**

1. `segment/shared/db_helpers.py`:
   - `result_id INTEGER` → `result_id TEXT PRIMARY KEY`
   - `position INTEGER` kolonu kaldırıldı
   - Eski 14 kolonlu yapıya dönüldü

2. `segment/pages/scraper.py`:
   - Surface dropdown eklendi: "Toprak (Gravel)" / "Asfalt (Asphalt)"
   - `_run_scraper()` → surface parametresi eklendi
   - `_save_to_database()` → `INSERT OR IGNORE` kullanıyor
   - Yeni/atlanan/hata sayıları ayrı gösteriliyor

---

### 15:30 - Hata Düzeltmeleri

**KeyError: 'stage_id' Düzeltildi**
- `_display_scrape_results()` fonksiyonunda kolon adları güncellendi
- `stage_id` → `stage_number` kombinasyonu kullanıldı
- `driver_id` → `driver_name` düzeltildi

**Surface Seçenekleri Genişletildi**
- 2 seçenek → 4 seçenek:
  - Toprak (gravel)
  - Asfalt (asphalt)
  - Kar (snow)
  - Karışık (mixed)

---

### 16:00 - Database Şeması Düzeltmeleri

**Problem:** "table stage_results has no column named car_number"

**Çözüm:**
1. `db_helpers.py` → Otomatik tablo şeması kontrolü eklendi
2. Eksik kolonlar varsa tablo yedeklenip yeniden oluşturuluyor
3. `car_class` kolonu eklendi

**Yeni Tablo Yapısı (16 kolon):**
```
result_id TEXT PRIMARY KEY
rally_id, rally_name, stage_number, stage_name
car_number, driver_name, co_driver_name, car_class, vehicle
time_str, time_seconds, diff_str, diff_seconds
surface, created_at
```

---

### 17:00 - Rally Bazlı Surface Seçimi (Büyük Güncelleme)

**Yeni 3 Adımlı Akış:**

```
ADIM 1: Rally ID aralığı gir (1-180) → [Rallileri Tara]
           ↓
ADIM 2: Bulunan ralliler listelenir
        | Rally ID | Rally Adı           | Zemin (seç)   |
        |----------|---------------------|---------------|
        | 97       | Marmaris Rallisi    | [Toprak ▼]    |
        | 111      | Ankara Asfalt       | [Asfalt ▼]    |
        | 125      | Uludağ Kış Rallisi  | [Kar ▼]       |

        [Tümüne Uygula] butonu ile toplu seçim
           ↓
ADIM 3: [Verileri Çek] → Her ralli kendi zemini ile kaydedilir
```

**Yeni Fonksiyonlar:**
- `_scan_rallies()` - Sadece ralli listesini tarar (hızlı)
- `_run_scraper_with_surfaces()` - Her ralli için ayrı surface ile veri çeker

---

### 17:30 - Database İndirme Özelliği

**Eklenen:**
- "Database Yükle" sekmesinde **"Database'i İndir (.db)"** butonu
- Mevcut database'i tek tıkla indirebilme

---

## Güncel Dosya Listesi

### Güncellenen Dosyalar (Bugün)
| Dosya | Değişiklik |
|-------|------------|
| segment/shared/db_helpers.py | Otomatik şema kontrolü, car_class eklendi |
| segment/pages/scraper.py | 3 adımlı akış, rally bazlı surface, DB indirme |

### Scraper Özellikleri (Final)
- 3 adımlı akış (Tara → Zemin Seç → Çek)
- 4 zemin tipi (Toprak/Asfalt/Kar/Karışık)
- Her ralli için ayrı zemin seçimi
- Toplu zemin uygulama
- Excel export + indirme
- Database kayıt + indirme
- Önizleme / Log / Hatalar (3 tab)

---

### 18:00 - KML Manager Hata Düzeltmeleri

**Problem 1: "no such column: stage_id"**
- `stage_results` tablosunda `stage_id` kolonu yok
- Çözüm: `data_loaders.py` ve `batch_kml_processor.py` sorguları düzeltildi
- `stage_id` yerine `rally_id || '_ss' || stage_number` kullanıldı

**Problem 2: Emoji encoding hatası**
- Windows console 'charmap' codec emoji desteklemiyor
- Çözüm: `kml_analyzer.py` ve `add_new_rally_stages.py` emojileri ASCII ile değiştirildi
- Örnek: 🔄 → [INFO], ✅ → [OK], ⚠️ → [WARN]

**Problem 3: KML-Rally otomatik eşleştirme çalışmıyor**
- Otomatik matching algoritması sorunlu
- Çözüm: Otomatik eşleştirme tamamen devre dışı bırakıldı
- Sadece manuel tek etap analizi aktif

**Yapılan Değişiklikler:**

1. `segment/shared/data_loaders.py`:
   - `get_rally_list()` → `stage_id` yerine `stage_number` kullanıyor
   - `get_stages_for_rally()` → `stage_id` oluşturuluyor (rally_id + stage_number)

2. `src/data/batch_kml_processor.py`:
   - `get_geometry_stats()` → stage_id sorgusundan kaldırıldı

3. `src/stage_analyzer/kml_analyzer.py`:
   - Tüm emojiler ASCII ile değiştirildi

4. `src/stage_analyzer/add_new_rally_stages.py`:
   - Tüm emojiler ASCII ile değiştirildi

5. `segment/pages/kml_manager.py`:
   - Tab isimleri: "Yukle" | "Manuel Analiz" | "Geometrik Veri"
   - Checkbox kaldırıldı (manuel analiz artık ana özellik)
   - Otomatik eşleştirme devre dışı

---

## Ozet - Gunun Tum Calismalari

### Segmentasyon (14:00-14:40)
- Monolitik app.py (1174 satir) → Moduler yapi
- 6 sayfa modulu + 4 shared modul olusturuldu
- EXE build basarili (192 MB)

### Scraper Iyilestirmeleri (15:00-17:30)
- 3 adimli akis: Tara → Zemin Sec → Cek
- 4 zemin tipi destegi
- Rally bazli surface secimi
- Database indirme butonu

### KML Manager Duzeltmeleri (18:00)
- "no such column: stage_id" duzeltildi
- Emoji encoding hatalari giderildi
- Otomatik eslestirme devre disi
- Manuel tek etap analizi ana ozellik oldu

### Guncel KML Manager Yapisi
```
Tab 1: Yukle          → KML dosya yukleme
Tab 2: Manuel Analiz  → Tek etap analiz ve kaydet
Tab 3: Geometrik Veri → Mevcut verileri goruntule
```

---

### 18:30 - Model Egitimi Duzeltmeleri

**Problem:** Model egitim verisi 0, R² = 0, Feature Importance = 0

**Cozum:**
1. `src/ml/model_trainer.py` SQL sorgulari guncellendi:
   - `sr.stage_id` → `(sr.rally_id || '_ss' || sr.stage_number)`
   - `sr.driver_id` → `sr.driver_name`
   - `sr.status IN ('FINISHED', 'OK')` → `sr.time_seconds > 0`

2. R² hesaplamasi eklendi (sklearn r2_score)

3. Feature Importance: Permutation importance kullanildi
   - Onceki: Tum degerler 0.0
   - Sonra: Gercek onem degerleri

**Model Sonuclari:**
- Egitim verisi: 941 kayit
- R² = 0.3361
- MAPE = 2.66%
- Top Features: driver_avg_ratio (0.93), baseline_ratio (0.65), momentum_factor (0.21)

---

### 18:45 - Tahmin Modulu Duzeltmeleri

**Problem:** "no such column: stage_id" hatasi

**Cozum - `src/prediction/notional_time_predictor.py`:**
1. `predict_for_manual_input()` SQL sorgulari guncellendi:
   - `driver_id` → `driver_name`
   - `stage_id` → `rally_id || '_ss' || stage_number`
   - `status = 'FINISHED'` → `time_seconds > 0`
   - `rally_date` → `rally_id` (siralama icin)

2. `_get_surface_experience()` duzeltildi

---

### 19:00 - KML Bazli Tahmin Ozelligi (Yeni)

**Yeni Ana Ozellik: KML yukle → Analiz et → Pilot sec → Tahmin al**

**Akis:**
```
1. KML/KMZ dosyasi yukle
        ↓
2. Etap sec (birden fazla varsa)
        ↓
3. Zemin tipi sec (gravel/asphalt/snow/mixed)
        ↓
4. [Etabi Analiz Et] → Geometrik ozellikler hesaplanir
   - Mesafe, Hairpin sayisi, Tirmanis/Inis
   - Egrilik, Max egim, Duz oran
        ↓
5. Pilot sec
        ↓
6. [Tahmin Et] → Sure tahmini
   - Pilot gecmisi + Geometrik ozellikler + ML model
   - Detayli aciklama ile birlikte
```

**Tahmin Hesaplama:**
- Baseline ratio (pilotun son 10 etap performansi)
- Surface adjustment (zemin deneyimi)
- Geometric correction (egitilmis model ile)
- Geometrik zorluk faktoru (hairpin/km, egim)

**Yeni Tab Yapisi:**
```
Tab 1: KML Tahmin    → Ana ozellik (KML yukle + tahmin)
Tab 2: Manuel Tahmin → Basit tahmin (uzunluk + zemin)
Tab 3: Toplu Tahmin  → Birden fazla pilot
```

---

### 19:15 - KML Analyzer Hata Duzeltmeleri

**Problem:** "float division by zero" hatasi

**Cozum - `src/stage_analyzer/kml_analyzer.py`:**
1. `_resample_path()`: Sifira bolme korumasi eklendi
2. `_resample_coordinates()`: Sifira bolme korumasi eklendi
3. `_extract_features()`: Minimum mesafe (0.001 km) ve bos array kontrolu
4. Hairpin hesaplama: Array boyut uyumsuzlugu korumasi

---

## Guncel Ozellikler Ozeti

### Tahmin Sayfasi (Final)
| Tab | Ozellik | Aciklama |
|-----|---------|----------|
| KML Tahmin | KML yukle → Analiz → Tahmin | Geometrik ozellikler + ML model |
| Manuel Tahmin | Uzunluk + Zemin gir → Tahmin | Basit baseline tahmin |
| Toplu Tahmin | Birden fazla pilot sec → Tahmin | CSV export |

### Model Egitimi
- 941 egitim verisi
- R² = 0.3361, MAPE = 2.66%
- Permutation importance ile feature onemi
- HistGradientBoostingRegressor

### KML Manager
- Manuel tek etap analizi
- Geometrik veri goruntuleme
- Excel export/import

---

---

## 2026-02-06

### 00:00 - Kritik Hata Duzeltmeleri

**Problem 1: time_seconds yanlis hesaplaniyor**
- `04:02:1` formati 14521 saniye (4 saat) olarak hesaplaniyordu
- Dogru deger: 242.1 saniye (4 dakika 2.1 saniye)
- Neden: `_parse_time()` fonksiyonu MM:SS:d formatini HH:MM:SS olarak yorumluyordu

**Cozum:**
- `segment/pages/scraper.py` → `_parse_time()` fonksiyonu duzeltildi
- `app.py` → Ayni duzeltme burada da yapildi
- Format tespiti: Ucuncu kisim < 10 ise MM:SS:d, degilse HH:MM:SS

```python
if len(parts) == 3:
    if third < 10 and second < 60:
        # MM:SS:d formatı (04:02:1 = 4 dakika 2.1 saniye)
        return first * 60 + second + third / 10.0
    else:
        # HH:MM:SS formatı
        return first * 3600 + second * 60 + third
```

---

### 00:15 - stage_length_km Kolonu Eklendi

**Problem:** Scraper etap uzunlugunu cekiyor ama database'e kaydetmiyordu

**Cozum:**
1. `segment/shared/db_helpers.py` → `stage_length_km REAL` kolonu eklendi
2. `segment/pages/scraper.py` → INSERT sorgusuna `stage_length_km` eklendi
3. ALTER TABLE ile mevcut tablolara kolon ekleme destegi

---

### 00:30 - Mevcut Verileri Duzeltme (Migration)

**Olusturulan:** `scripts/fix_time_seconds.py`

**Islem:**
- 2873 kayit duzeltildi
- time_seconds degerleri yeniden hesaplandi
- stage_length_km stage_name'den cikarildi (ornek: "SS1 - Etap Adi (8.0 km)" → 8.0)

**Dogrulama:**
```
Onceki: 04:02:1 → 14521 saniye (YANLIS)
Sonra:  04:02:1 → 242.1 saniye (DOGRU)
```

---

### 00:45 - Database Yolu Sorunu (EXE icin)

**Problem:** EXE calisirken database temp klasorunde araniyordu
- `C:\Users\...\AppData\Local\Temp\_MEIxxxxxx\data\raw\`
- Bu klasor EXE extract edildiginde olusturuluyor, database yok

**Cozum - `segment/shared/config.py`:**
```python
def get_app_root() -> Path:
    if getattr(sys, 'frozen', False):
        # PyInstaller exe - exe'nin bulundugu klasoru kullan
        return Path(sys.executable).parent
    else:
        # Normal Python calismasi
        return Path(__file__).parent.parent.parent
```

**Sonuc:** EXE artik kendi klasorundeki `data/raw/rally_results.db` dosyasini kullaniyor

---

### 01:00 - Settings Sayfasi Guncellendi

**Yeni Ozellikler:**
- Surukle-birak ile database yukleme (file_uploader)
- Kaydetme yeri secimi (Varsayilan / Ozel konum)
- Manuel yol degistirme (expander icinde)
- Otomatik klasor olusturma
- Debug bilgileri (PROJECT_ROOT, Frozen status)

---

### 01:15 - EXE Yeniden Build

**Sorunlar ve Cozumler:**

1. **"No module named 'streamlit'"**
   - Python 3.12'de streamlit yuklu degildi
   - `pip install streamlit pandas numpy scikit-learn scipy ...` ile yuklendi

2. **scipy._cyutility hatasi**
   - `collect_all('scipy')` spec dosyasina eklendi

3. **Browser otomatik acilmiyor**
   - `launcher.py` → `webbrowser.open()` thread ile eklendi

**Final EXE:**
- Konum: `D:\claude\Rally Eta v2\faz2\dist\RallyETA_v2.exe`
- Boyut: 176 MB
- Gerekli dosyalar: `data/raw/rally_results.db`, `kml-kmz/`, `models/`

---

### 01:30 - KML Analizi Test

**Sonuc:** Basarili
- 2 etap kaydedildi: `38_ss1`, `38_ss3`
- Ayni fiziksel parkur (1-3 REMED ASSISTANCE) farkli stage_id'lerle kaydedildi
- Bu rallilerde normal - ayni etap birden fazla kez kullanilabiliyor

---

## Guncellenen Dosyalar (2026-02-06)

| Dosya | Degisiklik |
|-------|------------|
| segment/pages/scraper.py | _parse_time() duzeltildi, stage_length_km eklendi |
| segment/shared/db_helpers.py | stage_length_km kolonu eklendi |
| segment/shared/config.py | get_app_root() - EXE icin path duzeltmesi |
| segment/pages/settings.py | Surukle-birak DB yukleme, debug bilgileri |
| launcher.py | Browser otomatik acma |
| RallyETA_v2.spec | scipy, streamlit collect_all eklendi |
| app.py | _parse_time() duzeltildi |
| scripts/fix_time_seconds.py | Yeni - migration script |

---

## Kritik Duzeltmeler Ozeti

| Sorun | Etki | Cozum |
|-------|------|-------|
| time_seconds yanlis | Tum tahminler hatali | _parse_time() MM:SS:d formati |
| stage_length_km kayitli degil | Geometrik analiz eksik | DB sema + scraper guncelleme |
| EXE database bulamiyor | Uygulama acilmiyor | sys.executable.parent kullanimi |
| scipy eksik | KML analizi calismiyor | collect_all('scipy') |
| streamlit eksik | EXE acilmiyor | Python 3.12'ye yukleme |

---

## Sonraki Adimlar (Oneriler)
1. Daha fazla KML verisi eklenmeli (geometrik ozellik etkisi icin)
2. Toplu KML tahmin ozelligi eklenebilir
3. Model yeniden egitilmeli (duzeltilmis time_seconds ile)
