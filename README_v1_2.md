# RallyETA v1.2 – Scraper Overhaul, Dataset Expansion, Driver Name Bug Fix

**Release Date:** 2025-12-10  
**Status:** Stable  
**Scope:** Data Pipeline Upgrade, Data Quality, Bug Fixes, Repo Cleanup

RallyETA v1.2, sistemin veri toplama, veri kalitesi ve kullanım stabilitesini doğrudan etkileyen en büyük altyapı güncellemesidir.  
Bu sürüm, TOSFED scraper'ının tamamen yeniden yazılması, 2023–2025 arası geniş bir dataset'in toplanması ve UI’da görülen kritik “yanlış sürücü ismi” hatasının düzeltilmesini içerir.

---

# 📌 1. TOSFED Web Scraper v1.2 (Complete)

### 🚀 Yenilikler
- Selenium tamamen kaldırıldı → 10x daha hızlı ve çok daha stabil
- URL parametre tabanlı veri çekme (etp=1,2,3…) kullanıldı
- Etaplar otomatik keşfediliyor (hardcode yok)
- Ralli yüzeyi otomatik belirleniyor:
  - Asphalt  
  - Gravel  
  - Snow (Sarıkamış özel durumu destekleniyor)
- Error handling ve timeout mekanizmaları eklendi
- Çoklu sezon desteği getirildi (2023, 2024, 2025)

### 📁 Kullanım
```bash
python -m src.scraper.tosfed_sonuc_scraper
📌 2. Dataset v2 – 8,286 Stage Results (2023–2025)
Yeni scraper ile üç sezondan veri çekildi:

Year	Rallies	Surface Types
2023	5+	Asphalt + Gravel
2024	6+	Asphalt + Gravel + Snow
2025	3+	Asphalt + Gravel

📊 Toplam:
8,286 satır

14 ralli

Tüm etaplar / tüm sınıflar

Eksiksiz zaman verileri

📄 Üretilen dosyalar:
bash
Kodu kopyala
data/raw/rally_results_v1.2.csv
data/raw/rally_results_v1.2.xlsx
Bu dataset, model v2 (v1.3) için ana kaynak olacak.

📌 3. Surface Metadata Güncellemesi
Yeni mapping dosyası:

bash
Kodu kopyala
data/rally_surface_metadata.json
✔ Doğru yüzey eşleşmeleri:
Marmaris → Asphalt

Bodrum → Asphalt

Eskişehir → Asphalt

Yeşil Bursa → Asphalt

Ege → Asphalt

Kocaeli → Gravel

İstanbul → Gravel

Hitit → Gravel

Sarıkamış → Snow

Bu bilgiler scraper tarafından otomatik kullanılıyor.

📌 4. Driver Name Bug Fix (Critical)
❗ Sorun
Tahmin ekranında seçilen pilot → açıklamada yanlış bir isimle görünüyordu.

Örnek:

UI seçimi: Ali Türkkan

Açıklamada görünen: “Uras Can Özdemir için tahmin”

🧠 Kök neden
predict_notional_times.py fonksiyonu:

driver_name değerini UI’dan almıyor

Database sorgusundaki ilk kaydı kullanıyordu

Bu da ID eşleşmesi bozuk olan eski dataset satırlarında yanlış isim getiriyordu.

✔ Çözüm
UI → seçilen label’dan driver_name ayrıştırıldı

predictor → artık driver_name parametresini doğrudan alıyor

database isim alanı yalnızca car_class belirlemek için kullanılıyor

Bu düzeltme ile tüm tahmin açıklamaları artık doğru pilot ismini gösteriyor.

📌 5. Config Loader Fix
Eski yapı:

python
Kodu kopyala
open("config.yaml")
Yeni yapı:

python
Kodu kopyala
os.path.join(os.path.dirname(__file__), "config.yaml")
✔ Portable build'de path sorunları tamamen çözüldü
✔ Her platformda config stabil şekilde yükleniyor

📌 6. Repo Temizliği (Important)
Yapılanlar:
Yanlışlıkla commitlenen RallyETA_Portable_v1.1/ klasörü temizlendi

.gitignore güncellendi:

Portable klasörleri

Log dosyaları

Büyük dataset dosyaları

Build artefact’leri

Sonuç:
Repo artık temiz, hafif ve profesyonel.

📌 7. Excel Export (New Feature)
Scraper artık sonuçları hem CSV hem XLSX biçiminde kaydediyor:

bash
Kodu kopyala
data/raw/rally_results_v1.2.xlsx
Bu özellikle Excel kullanıcıları için doğrulama sürecini kolaylaştırdı.

📌 8. Uyumluluk: v1.1 → v1.2
Değişmeyen modüller:
Feature Engineering v1.1

Short-stage correction sistemi

Anomaly detector mantığı

Değişen modüller:
scraper (tamamen yeniden yazıldı)

config loader

driver-name resolution

portable build ayarları

🚀 Next Steps: Coming in v1.3
Model v2 eğitim pipeline’ı

Surface-aware model splitting

Driver consistency index

Stage technicality score

8,286 satırlık dataset üzerinde doğrulama ve benchmark testleri