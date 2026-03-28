# Rally ETA v2.0 - Yapilacaklar

## Tarih: 2026-02-12

---

## TAMAMLANDI (2026-02-12)

### DB Sema Migrasyonu
- [x] `normalized_class`, `ratio_to_class_best`, `class_position` kolonlari eklendi
- [x] 2879 kayit icin normalized_class hesaplandi (11 sinif)
- [x] 2873 kayit icin ratio_to_class_best ve class_position hesaplandi
- [x] Migration idempotent: tekrar calistirildiginda sadece eksikleri tamamlar

### Arac Sinifi Normalizasyonu (Gorev #2)
- [x] CarClassNormalizer'a TOSFED kisa kodlari eklendi (2->Rally2, 3->Rally3, 4->Rally4, 5->Rally5, K1-K4, H1-H2, N)
- [x] Scraper'a normalized_class entegrasyonu yapildi (kayit sirasinda otomatik normalize)
- [x] data_loaders.py normalized_class'tan okuyor

### Guncel Form Duzeltmesi (Gorev #4)
- [x] driver_performance.py: Etap bazli degil, RALLI bazli agirlikli ortalama
- [x] Son 5 ralli: %40, %30, %20, %10 agirlik
- [x] driver_id yerine driver_name kullanimi
- [x] rally_date yerine CAST(rally_id AS INTEGER) siralama

### Rally Momentum Duzeltmesi (Gorev #3)
- [x] rally_momentum.py: driver_id -> driver_name duzeltmesi
- [x] ratio_to_class_best ve class_position DB'den okunuyor
- [x] Yeni: calculate_momentum_from_live_data() metodu (canli TOSFED verisiyle)
- [x] Sinif ici siralama trendi hesaplama (yukseliyor/dusuyor/sabit)
- [x] momentum_factor hesaplama (tahmine uygulanacak carpan)

### Mevcut Yaris Bilgisi Girisi (Gorev #1)
- [x] TOSFED URL parser: fetch_rally_from_url() metodu (tosfed_sonuc_scraper.py)
- [x] Yeni "Canli Tahmin" tab'i prediction.py'ye eklendi
- [x] URL gir -> Verileri Cek -> Ralli ozeti + Pilot listesi
- [x] Pilotun onceki etap sonuclari tablosu
- [x] Canli momentum hesaplama (TOSFED verisinden)
- [x] Tarihsel baseline + canli momentum + surface adj + geometrik duzeltme birlestirme

### Sinif En Iyisi Normalizasyon (Gorev #5)
- [x] class_best_calculator.py: car_class yerine COALESCE(normalized_class, car_class) kullanimi
- [x] stage_id yerine stage_number ile sorgu duzeltmesi

### Prediction.py Guncelleme
- [x] KML tahmin: normalized_class kullanimi
- [x] KML tahmin: ralli bazli baseline (DriverPerformanceAnalyzer)
- [x] KML tahmin: momentum_factor (RallyMomentumAnalyzer)
- [x] Ortak fonksiyonlar: _fallback_baseline, _calculate_surface_adjustment, _apply_geometric_correction, _calculate_reference_time, _calculate_confidence

---

## KRITIK EKSIKLIKLER (Plan vs Gercek Karsilastirmasi) - TAMAMLANDI

### 1. Mevcut Yaris Bilgisi Girisi (YOK)

**Problem:** Tahmin yaparken sadece gecmis verilere bakiliyor. Mevcut yarista pilotun nasil gittigi bilinmiyor.

**Gerekli:**
- [ ] TOSFED URL'si giris alani (ornek: `https://tosfedsonuc.com/yaris/171/ralli_etap_sonuclari/?etp=7`)
- [ ] URL'den otomatik veri cekme (scraper.py zaten yapiyor - entegre edilmeli)
- [ ] Mevcut rallinin onceki etap sonuclarini gosterme
- [ ] Tahmin edilecek etap secimi (SS6, SS7 vb.)

**UI Tasarimi:**
```
Tahmin Sayfasi:
+---------------------------------------+
| 1. Yaris Bilgisi Girisi               |
|    TOSFED URL: [_____________________]|
|    [Verileri Cek]                     |
|                                       |
|    Ralli: 2024 Marmaris Rallisi       |
|    Onceki Etaplar: SS1-SS5 yuklendi   |
+---------------------------------------+
| 2. Tahmin Edilecek Etap               |
|    KML Dosyasi: [SS6.kml v]           |
|    Zemin: [Toprak v]                  |
|    Pilot: [Ali Turkkan v]             |
+---------------------------------------+
| [TAHMIN YAP]                          |
+---------------------------------------+
```

---

### 2. Arac Sinifi Normalizasyonu (FAZ 1A - YAPILMADI)

**Problem:** `car_class` kolonu var ama normalize edilmemis. Ayni sinif farkli isimlerle:
- "R5", "Rally2", "RALLY2" → hepsi ayni
- "S2000", "Super 2000" → hepsi ayni

**Gerekli:**
- [ ] `normalized_class` kolonu ekle (stage_results tablosuna)
- [ ] Normalizasyon mapping'i olustur:
  ```python
  CLASS_MAPPING = {
      'R5': 'Rally2', 'RALLY2': 'Rally2', 'Rally 2': 'Rally2',
      'R4': 'Rally4', 'RALLY4': 'Rally4',
      'S2000': 'S2000', 'Super 2000': 'S2000',
      ...
  }
  ```
- [ ] Mevcut verileri migrate et
- [ ] Scraper'a normalizasyon ekle

---

### 3. Rally Momentum YANLIS Hesaplaniyor (FAZ 1D)

**Planda:**
> "Mevcut rallide pilotun sinif ici siralama trendi"
> - SS3: 5/12 → SS4: 3/12 → SS5: 2/12 = Yukseliyor

**Simdi Ne Yapiyor:**
- Genel performans trendi (son N etap / onceki N etap)
- Sinif ici degil, genel siralama
- Mevcut ralli degil, tarihsel veri

**Duzeltme:**
- [ ] Mevcut ralli sonuclarini al (TOSFED'den)
- [ ] Her etapta pilotun SINIF ICI siralamasini hesapla
- [ ] Siralama trendini hesapla (yukseliyor/dusuyor/sabit)
- [ ] Bu trendi tahmine dahil et

---

### 4. Guncel Form YANLIS Hesaplaniyor (FAZ 1C)

**Planda:**
> "Son 3-5 RALLI performansi, agirlikli ortalama"
> - Son ralli: %40 agirlik
> - Onceki ralli: %30 agirlik
> - 3. ralli: %20 agirlik
> - 4-5. ralli: %10 agirlik

**Simdi Ne Yapiyor:**
- Son 5 ETAP performansi (ralli degil!)
- Agirliksiz ortalama

**Duzeltme:**
- [ ] Ralli bazli gruplama yap
- [ ] Her rallinin ortalama baseline_ratio'sunu hesapla
- [ ] Agirlikli ortalama uygula

---

### 5. Sinif En Iyisi (Class Best) Eksik Normalizasyon (FAZ 1B)

**Problem:** `car_class` normalize edilmeden kullaniliyor.
- "R5" ve "Rally2" farkli sinifmis gibi hesaplaniyor

**Duzeltme:**
- [ ] Class best hesaplarken `normalized_class` kullan
- [ ] Ayni sinifin tum varyantlarini birlestir

---

## TAMAMLANDI (Onceki Oturumlar)

### 2026-02-06
- [x] time_seconds parsing duzeltildi (MM:SS:d formati)
- [x] stage_length_km kolonu eklendi
- [x] Mevcut veriler migrate edildi (2873 kayit)
- [x] EXE database yolu duzeltildi
- [x] Settings sayfasina drag-drop eklendi
- [x] EXE yeniden build edildi

### 2026-02-06 (Gece)
- [x] Driver name duplicates duzeltildi (175 → 130 unique pilot)
- [x] sklearn.inspection EXE'ye eklendi
- [x] KML analiz export/import eklendi

### 2025-12-31
- [x] KML Manager hatalari duzeltildi
- [x] Model egitimi tamamlandi (R²=0.34, MAPE=2.66%)
- [x] Tahmin modulu calisiyor

---

## ONCELIK SIRASI

1. **Mevcut Yaris Bilgisi Girisi** - En kritik. Bu olmadan gercek momentum hesaplanamaz.
2. **Arac Sinifi Normalizasyonu** - Class best ve sinif ici siralama icin gerekli.
3. **Rally Momentum Duzeltmesi** - #1 ve #2 tamamlandiktan sonra.
4. **Guncel Form Duzeltmesi** - Son adim.

---

## HEDEF

- [ ] Tahmin hatasi %2-3 arasina dusurulmeli
- [ ] Ali Turkkan gibi tutarli pilotlarda %1'e yakin hata
- [ ] Demir Sancakli gibi degisken pilotlarda %5'e yakin hata

---

## NOTLAR

- Scraper zaten TOSFED'den veri cekiyor - sadece tahmin sayfasina entegre edilmeli
- `planfazv2.md` dosyasi referans olarak kullanilmali
- Model yeniden egitilmeli (duzeltmelerden sonra)
