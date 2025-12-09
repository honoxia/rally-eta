# Rally ETA - Standalone EXE Kullanım Kılavuzu

## ✅ Tamamlanan İşlemler

### 1. EXE Başarıyla Oluşturuldu
- **Dosya**: `dist/RallyETA.exe`
- **Boyut**: 78.3 MB
- **Süre**: 138 saniye (2.3 dakika)
- **Icon**: Kırmızı-beyaz damalı ralli bayrağı

### 2. Portable Paket Hazır
- **Klasör**: `RallyETA_Portable_v1.0/`
- **ZIP**: `RallyETA_Portable_v1.0.zip` (77.7 MB)
- **İçerik**:
  - RallyETA.exe
  - config/ (konfigürasyon dosyaları)
  - data/ (boş klasörler: raw, processed, external)
  - models/ (boş model klasörü)
  - logs/ (log klasörü)
  - README.txt

## 🚀 Kullanım

### Yöntem 1: Doğrudan EXE'yi Çalıştır
```bash
cd dist
RallyETA.exe
```

- Console penceresi açılacak
- 3 saniye sonra tarayıcı otomatik açılacak
- Uygulama http://localhost:[random-port] adresinde çalışacak
- **ÖNEMLİ**: Console penceresini KAPATMAYIN!

### Yöntem 2: Portable Paketi Kullan
1. `RallyETA_Portable_v1.0.zip` dosyasını çıkar
2. `RallyETA.exe` dosyasına çift tıkla
3. Tarayıcı açılacak ve uygulama çalışacak

### Yöntem 3: Başka Bilgisayara Dağıt
1. `RallyETA_Portable_v1.0.zip` dosyasını kopyala
2. Hedef bilgisayarda çıkar
3. **Python kurulumu GEREKMİYOR**
4. Çift tıkla ve kullan!

## 📁 Dosya Yapısı

```
RallyETA_Portable_v1.0/
├── RallyETA.exe          # Ana program (78 MB)
├── README.txt            # Kullanım kılavuzu
├── config/               # Konfigürasyon
│   ├── config.yaml
│   └── logging.yaml
├── data/                 # Veri klasörleri (otomatik oluşturulur)
│   ├── raw/
│   ├── processed/
│   └── external/
├── models/               # Model klasörü
│   └── rally_eta_v1/
└── logs/                 # Log dosyaları
```

## 🔧 Teknik Detaylar

### PyInstaller Ayarları
- **Mod**: One-file (tek EXE)
- **Console**: Açık (debug için)
- **UPX**: Aktif (sıkıştırma)
- **Icon**: assets/icon.ico

### Dahil Edilen Paketler
- Streamlit 1.51.0
- Plotly (grafik)
- Pandas, NumPy (veri işleme)
- LightGBM (machine learning)
- BeautifulSoup4 (web scraping)
- Requests (HTTP)
- SQLite (veritabanı)
- Pillow (görsel işleme)

### Hidden Imports
- streamlit.web.cli
- streamlit.runtime
- sklearn.ensemble
- scipy.special
- altair (Streamlit grafikleri)

## 🛠️ Yeniden Build Etme

### 1. EXE'yi Yeniden Oluştur
```bash
python build_exe.py
```

### 2. Portable Paket Oluştur
```bash
python scripts/create_portable.py
```

### 3. Tümünü Temizle ve Yeniden Build Et
```bash
# Manuel temizlik
rmdir /s /q build dist
del RallyETA.spec

# Yeniden build
python build_exe.py
python scripts/create_portable.py
```

## 🎨 Icon Değiştirme

### Yeni Icon Oluştur
```python
from PIL import Image, ImageDraw

img = Image.new('RGBA', (256, 256), 'white')
draw = ImageDraw.Draw(img)
# Kendi tasarımınızı çizin
img.save('assets/icon.ico', format='ICO')
```

### Build'e Dahil Et
Icon otomatik olarak `RallyETA.spec` dosyasında tanımlı:
```python
icon='assets/icon.ico' if Path('assets/icon.ico').exists() else None
```

## 🐛 Sorun Giderme

### Problem 1: EXE Açılmıyor
**Çözüm**:
- Console penceresini aç ve hata mesajını oku
- Muhtemelen eksik DLL veya import hatası

### Problem 2: Streamlit Bulunamadı
**Çözüm**:
- `RallyETA.spec` dosyasında `hiddenimports` listesini kontrol et
- Yeniden build et

### Problem 3: EXE Çok Büyük (>100 MB)
**Çözüm**:
- `RallyETA.spec` içinde `excludes` listesine gereksiz paketleri ekle:
```python
excludes=['matplotlib', 'tensorflow', 'torch']
```

### Problem 4: Console Görünmesin
**Çözüm**:
- `RallyETA.spec` dosyasında:
```python
console=False  # True yerine False yap
```

### Problem 5: Port Çakışması
**Çözüm**:
- Launcher otomatik boş port buluyor
- Manuel port: `launcher.py` içinde `port = 8501` şeklinde sabitleyebilirsiniz

## 📦 Installer Oluşturma (Opsiyonel)

### Inno Setup ile MSI/EXE Installer

1. **Inno Setup İndir**
   - https://jrsoftware.org/isinfo.php

2. **Script Oluştur**
   - `build_exe.py` çalıştırınca otomatik `RallyETA.iss` oluşur

3. **Compile Et**
   - Inno Setup ile `RallyETA.iss` dosyasını aç
   - Build → Compile
   - `installer/RallyETA_Setup.exe` oluşacak

### Installer Özellikleri
- Program Files'a kurulum
- Start Menu kısayolu
- Desktop kısayolu
- Uninstaller
- Otomatik başlatma (opsiyonel)

## 🚢 Dağıtım Senaryoları

### Senaryo 1: Teknik Kullanıcı
- `dist/RallyETA.exe` dosyasını paylaş
- Kullanıcı manuel çalıştırır

### Senaryo 2: Son Kullanıcı (Portable)
- `RallyETA_Portable_v1.0.zip` dosyasını paylaş
- Kullanıcı çıkarıp çift tıklar
- README.txt otomatik açıklar

### Senaryo 3: Kurumsal Dağıtım
- Inno Setup ile installer oluştur
- `RallyETA_Setup.exe` dosyasını dağıt
- Otomatik kurulum ve kısayollar

## 📊 Performans

### İlk Açılış
- **Süre**: 30-60 saniye
- **Sebep**: PyInstaller temporary extraction
- **Konum**: `%TEMP%/_MEIxxxxxx/`

### Sonraki Açılışlar
- **Süre**: 10-20 saniye
- **Sebep**: Streamlit başlatma

### Optimizasyon
- UPX sıkıştırması aktif
- One-file mod (tek EXE)
- Gereksiz paketler exclude edilmiş

## 🔒 Güvenlik

### Antivirüs False Positive
- PyInstaller EXE'leri bazen antivirüs uyarısı verir
- **Çözüm**: Code signing sertifikası kullan
- Veya: Antivirüs'e exception ekle

### Code Signing (Gelişmiş)
```bash
# Windows SDK ile
signtool sign /f mycert.pfx /p password /t http://timestamp.digicert.com RallyETA.exe
```

## 📝 Notlar

1. **Database**: İlk çalıştırmada `data/raw/tosfed_raw.db` otomatik oluşturulur
2. **Logs**: `logs/` klasöründe saklanır
3. **Models**: Eğitilen modeller `models/rally_eta_v1/` altında
4. **Config**: `config/config.yaml` dosyasını düzenleyebilirsiniz
5. **Port**: Her açılışta rastgele port seçilir (çakışma önlemi)

## 🎉 Başarıyla Tamamlandı!

Artık Rally ETA uygulamanız:
- ✅ Standalone EXE olarak çalışıyor
- ✅ Python kurulumu gerektirmiyor
- ✅ Portable (ZIP olarak dağıtılabilir)
- ✅ Otomatik tarayıcı açılıyor
- ✅ Profesyonel icon var
- ✅ README dahil

**Test Edildi**: Windows 11, Console açık mod, Port otomatik seçim ✓

## 📧 Destek

Sorun yaşarsanız:
1. Console penceresini kontrol edin
2. `logs/` klasöründeki log dosyalarına bakın
3. `config/config.yaml` ayarlarını gözden geçirin
4. GitHub Issues'da soru sorun

**Versiyon**: 1.0
**Tarih**: Aralık 2025
**Platform**: Windows x64
