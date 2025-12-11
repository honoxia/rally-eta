import customtkinter as ctk
import tkinter.filedialog as filedialog
import xml.etree.ElementTree as ET
import pandas as pd
import requests
import re
import os
import json
import zipfile
import math
import threading
import queue
from tkinter import messagebox
from bs4 import BeautifulSoup
from datetime import datetime

# ---------- Sabit Dosya Adları ve Ayarlar ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

# ---------- Konsol Çıktısını GUI'ye Yönlendirme ----------
log_queue = queue.Queue()
progress_queue = queue.Queue()

class TextRedirector:
    """Konsol (stdout) çıktısını bir kuyruğa yönlendirir."""
    def __init__(self, queue_):
        self.queue = queue_
    def write(self, text):
        self.queue.put(text)
    def flush(self):
        pass

# ---------- Yardımcı Fonksiyonlar ----------
def _time_to_sec(t):
    """Farklı zaman formatlarını (örn: '12:34.5', '1:23,4') saniyeye çevirir."""
    try:
        if pd.isna(t) or str(t).strip() == "": return None
        t_str = str(t).strip().replace(",", ".")
        parts = list(map(float, re.split(r"[:.]", t_str)))
        sec = 0
        if len(parts) == 4: sec = parts[0] * 3600 + parts[1] * 60 + parts[2] + parts[3] / 10.0
        elif len(parts) == 3: sec = parts[0] * 60 + parts[1] + parts[2] / 10.0
        elif len(parts) == 2: sec = parts[0] * 60 + parts[1]
        return sec if sec > 0 else None
    except (ValueError, IndexError): return None

def _sec_to_time(sec):
    """Saniyeyi 'MM:SS,T' formatına çevirir."""
    if sec is None or sec <= 0: return "00:00,0"
    m = int(sec // 60)
    s = int(sec % 60)
    t = int(round((sec % 1) * 10))
    if t >= 10: t = 9
    return f"{m:02d}:{s:02d},{t}"

def normalize_pilot_name(name):
    """Pilot isimlerini standart bir formata (büyük harf, Türkçe karakterler olmadan) getirir."""
    if pd.isna(name) or not name: return "BILINMEYEN"
    name = str(name).strip().upper()
    tr_map = str.maketrans('İĞÜŞÖÇ', 'IGUSOC')
    return name.translate(tr_map)

# ---------- Ana Uygulama Sınıfı ----------
class RallyDataCollector(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Ralli Veri Toplama ve Birleştirme Sistemi v1.0")
        self.geometry("1400x800")

        # Günler ve KML dosyaları için veri yapıları
        self.days_data = {}
        self.kml_stage_mappings = {}
        self.current_race_data = {}

        # Ana layout yapılandırması
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Sekme yapısı
        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.tab_race_info = self.tabs.add("1. Yarış Bilgileri")
        self.tab_kml_days = self.tabs.add("2. Günler ve KML Dosyaları")
        self.tab_mapping = self.tabs.add("3. KML-Etap Eşleştirme")
        self.tab_preview = self.tabs.add("4. Önizleme ve Export")

        # Alt kısım (Log ve İlerleme Çubuğu)
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.bottom_frame.grid_columnconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self.bottom_frame, height=120, wrap="word")
        self.log_textbox.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.progress_bar = ctk.CTkProgressBar(self.bottom_frame)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.progress_bar.set(0)

        # Sekmeleri oluştur
        self.create_race_info_tab()
        self.create_kml_days_tab()
        self.create_mapping_tab()
        self.create_preview_tab()
        
        # Konsol yönlendirme ve kuyruk işleme
        import sys
        sys.stdout = TextRedirector(log_queue)
        self.process_queues()
        
        print("Ralli Veri Toplama Sistemi başlatıldı.")

    def process_queues(self):
        """Log ve ilerleme kuyruklarını işleyerek GUI'yi günceller."""
        try:
            while not log_queue.empty():
                self.log_textbox.insert("end", log_queue.get())
                self.log_textbox.see("end")
            while not progress_queue.empty():
                self.progress_bar.set(progress_queue.get())
        except Exception:
            pass
        self.after(100, self.process_queues)

    def start_threaded_task(self, target_func, args=()):
        """Uzun süren işlemleri arayüzü kilitlemeden bir thread içinde başlatır."""
        self.log_textbox.delete("1.0", "end")
        progress_queue.put(0)
        thread = threading.Thread(target=target_func, args=args, daemon=True)
        thread.start()

    # ==================================================================
    # SEKMELERİ OLUŞTURAN FONKSİYONLAR
    # ==================================================================

    def create_race_info_tab(self):
        """1. Yarış Bilgileri sekmesinin arayüzünü oluşturur."""
        self.tab_race_info.grid_columnconfigure(1, weight=1)
        
        # Yarış Temel Bilgileri Frame
        race_info_frame = ctk.CTkFrame(self.tab_race_info)
        race_info_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        race_info_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(race_info_frame, text="Yarış Temel Bilgileri", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=10)
        
        ctk.CTkLabel(race_info_frame, text="Yarış URL:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.race_url_entry = ctk.CTkEntry(race_info_frame, placeholder_text="https://tosfedsonuc.org.tr/.../ralli_etap_sonuclari_print/")
        self.race_url_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        
        row2_frame = ctk.CTkFrame(race_info_frame)
        row2_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        row2_frame.grid_columnconfigure((0,1,2,3), weight=1)
        
        ctk.CTkLabel(row2_frame, text="Tarih:").grid(row=0, column=0, padx=5, pady=5)
        self.race_date_entry = ctk.CTkEntry(row2_frame, placeholder_text="YYYY-MM-DD")
        self.race_date_entry.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        
        ctk.CTkLabel(row2_frame, text="Sezon:").grid(row=0, column=1, padx=5, pady=5)
        self.race_season_entry = ctk.CTkEntry(row2_frame, placeholder_text="2024")
        self.race_season_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        
        ctk.CTkLabel(row2_frame, text="Zemin:").grid(row=0, column=2, padx=5, pady=5)
        self.race_surface_menu = ctk.CTkOptionMenu(row2_frame, values=["asfalt", "toprak", "kar", "karışık"])
        self.race_surface_menu.grid(row=1, column=2, padx=5, pady=5, sticky="ew")
        
        ctk.CTkLabel(row2_frame, text="Toplam Etap:").grid(row=0, column=3, padx=5, pady=5)
        self.total_stages_entry = ctk.CTkEntry(row2_frame, placeholder_text="10")
        self.total_stages_entry.grid(row=1, column=3, padx=5, pady=5, sticky="ew")
        
        # Fetch Race Data Button
        self.fetch_race_data_button = ctk.CTkButton(race_info_frame, text="Yarış Verilerini Çek", 
                                                   command=self.fetch_race_data_clicked)
        self.fetch_race_data_button.grid(row=3, column=0, columnspan=2, padx=10, pady=10)
        
        # Race Data Preview
        preview_frame = ctk.CTkFrame(self.tab_race_info)
        preview_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(preview_frame, text="Yarış Verileri Önizleme", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=10, pady=5)
        
        self.race_data_preview = ctk.CTkTextbox(preview_frame, font=ctk.CTkFont(family="monospace"))
        self.race_data_preview.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    def create_kml_days_tab(self):
        """2. Günler ve KML Dosyaları sekmesinin arayüzünü oluşturur."""
        self.tab_kml_days.grid_columnconfigure(0, weight=1)
        self.tab_kml_days.grid_rowconfigure(1, weight=1)
        
        # Gün Ekleme Frame
        add_day_frame = ctk.CTkFrame(self.tab_kml_days)
        add_day_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        add_day_frame.grid_columnconfigure(2, weight=1)
        
        ctk.CTkLabel(add_day_frame, text="Yeni Gün Ekle", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=4, padx=10, pady=10)
        
        ctk.CTkLabel(add_day_frame, text="Gün No:").grid(row=1, column=0, padx=5, pady=5)
        self.day_number_entry = ctk.CTkEntry(add_day_frame, width=80, placeholder_text="1")
        self.day_number_entry.grid(row=1, column=1, padx=5, pady=5)
        
        ctk.CTkLabel(add_day_frame, text="Etaplar (virgülle ayır):").grid(row=1, column=2, padx=5, pady=5, sticky="w")
        self.day_stages_entry = ctk.CTkEntry(add_day_frame, placeholder_text="1,2,3,4,5,6")
        self.day_stages_entry.grid(row=1, column=3, padx=5, pady=5, sticky="ew")
        
        ctk.CTkButton(add_day_frame, text="KML Dosyası Seç", command=self.select_kml_file).grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        self.selected_kml_label = ctk.CTkLabel(add_day_frame, text="Seçili dosya: Yok")
        self.selected_kml_label.grid(row=2, column=2, columnspan=2, padx=5, pady=5, sticky="w")
        
        ctk.CTkButton(add_day_frame, text="Günü Ekle", command=self.add_day_clicked).grid(row=3, column=0, columnspan=4, padx=5, pady=10)
        
        # Günler Listesi
        days_list_frame = ctk.CTkFrame(self.tab_kml_days)
        days_list_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        days_list_frame.grid_columnconfigure(0, weight=1)
        days_list_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(days_list_frame, text="Eklenen Günler", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=10, pady=5)
        
        self.days_list_text = ctk.CTkTextbox(days_list_frame, font=ctk.CTkFont(family="monospace"))
        self.days_list_text.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        # Temporary variables for KML selection
        self.selected_kml_path = None

    def create_mapping_tab(self):
        """3. KML-Etap Eşleştirme sekmesinin arayüzünü oluşturur."""
        self.tab_mapping.grid_columnconfigure(0, weight=1)
        self.tab_mapping.grid_rowconfigure(1, weight=1)
        
        # Instructions
        instructions_frame = ctk.CTkFrame(self.tab_mapping)
        instructions_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        instructions_text = ("KML dosyalarındaki etap isimlerini yarış etap numaralarıyla eşleştirin.\n"
                           "Aynı rota birden fazla etapta kullanılıyorsa, aynı KML etabını farklı yarış etaplarına atayabilirsiniz.")
        ctk.CTkLabel(instructions_frame, text=instructions_text, wraplength=800).grid(row=0, column=0, padx=10, pady=10)
        
        ctk.CTkButton(instructions_frame, text="KML Analizi Yap ve Eşleştirme Tablosu Oluştur", 
                     command=self.analyze_kmls_and_create_mapping).grid(row=1, column=0, padx=10, pady=10)
        
        # Mapping Frame
        mapping_frame = ctk.CTkFrame(self.tab_mapping)
        mapping_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        mapping_frame.grid_columnconfigure(0, weight=1)
        mapping_frame.grid_rowconfigure(0, weight=1)
        
        self.mapping_scroll_frame = ctk.CTkScrollableFrame(mapping_frame)
        self.mapping_scroll_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        # Mapping widgets will be created dynamically
        self.mapping_widgets = []

    def create_preview_tab(self):
        """4. Önizleme ve Export sekmesinin arayüzünü oluşturur."""
        self.tab_preview.grid_columnconfigure(0, weight=1)
        self.tab_preview.grid_rowconfigure(1, weight=1)
        
        # Buttons Frame
        buttons_frame = ctk.CTkFrame(self.tab_preview)
        buttons_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        buttons_frame.grid_columnconfigure((0,1), weight=1)
        
        ctk.CTkButton(buttons_frame, text="Verileri Birleştir ve Önizle", 
                     command=self.generate_preview).grid(row=0, column=0, padx=5, pady=10, sticky="ew")
        
        ctk.CTkButton(buttons_frame, text="JSON'u Dışarı Aktar", 
                     command=self.export_json).grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        
        # Preview Frame
        preview_frame = ctk.CTkFrame(self.tab_preview)
        preview_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(preview_frame, text="Birleştirilmiş Veri Önizlemesi", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=10, pady=5)
        
        self.final_preview_text = ctk.CTkTextbox(preview_frame, font=ctk.CTkFont(family="monospace"))
        self.final_preview_text.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    # ==================================================================
    # EVENT HANDLER FONKSİYONLARI
    # ==================================================================

    def fetch_race_data_clicked(self):
        """Yarış verilerini çekme butonuna tıklandığında çalışır."""
        url = self.race_url_entry.get().strip()
        if not url:
            messagebox.showerror("Hata", "Lütfen yarış URL'sini girin.")
            return
        
        try:
            total_stages = int(self.total_stages_entry.get().strip() or "0")
            if total_stages <= 0:
                messagebox.showerror("Hata", "Geçerli bir toplam etap sayısı girin.")
                return
        except ValueError:
            messagebox.showerror("Hata", "Toplam etap sayısı sayı olmalıdır.")
            return
        
        self.start_threaded_task(self.fetch_race_data_worker, (url, total_stages))

    def select_kml_file(self):
        """KML dosyası seçim dialog'unu açar."""
        file_path = filedialog.askopenfilename(
            title="KML/KMZ Dosyası Seç",
            filetypes=(("KML/KMZ dosyaları", "*.kml *.kmz"), ("Tüm dosyalar", "*.*"))
        )
        if file_path:
            self.selected_kml_path = file_path
            filename = os.path.basename(file_path)
            self.selected_kml_label.configure(text=f"Seçili dosya: {filename}")

    def add_day_clicked(self):
        """Gün ekleme butonuna tıklandığında çalışır."""
        try:
            day_num = int(self.day_number_entry.get().strip())
            stages_str = self.day_stages_entry.get().strip()
            
            if not stages_str or not self.selected_kml_path:
                messagebox.showerror("Hata", "Gün numarası, etaplar ve KML dosyası gerekli.")
                return
            
            stages = [int(s.strip()) for s in stages_str.split(',')]
            
            if day_num in self.days_data:
                messagebox.showerror("Hata", f"Gün {day_num} zaten eklenmiş.")
                return
            
            self.days_data[day_num] = {
                'kml_path': self.selected_kml_path,
                'kml_filename': os.path.basename(self.selected_kml_path),
                'stages': stages
            }
            
            self.update_days_list_display()
            
            # Reset form
            self.day_number_entry.delete(0, "end")
            self.day_stages_entry.delete(0, "end")
            self.selected_kml_path = None
            self.selected_kml_label.configure(text="Seçili dosya: Yok")
            
            messagebox.showinfo("Başarılı", f"Gün {day_num} eklendi.")
            
        except ValueError as e:
            messagebox.showerror("Hata", f"Geçersiz veri girişi: {e}")

    def analyze_kmls_and_create_mapping(self):
        """KML dosyalarını analiz ederek eşleştirme tablosunu oluşturur."""
        if not self.days_data:
            messagebox.showerror("Hata", "Önce günleri ve KML dosyalarını ekleyin.")
            return
        
        self.start_threaded_task(self.analyze_kmls_worker)

    def generate_preview(self):
        """Tüm verileri birleştirip önizleme oluşturur."""
        if not self.current_race_data or not self.days_data or not self.kml_stage_mappings:
            messagebox.showerror("Hata", "Önce tüm adımları tamamlayın.")
            return
        
        self.start_threaded_task(self.generate_preview_worker)

    def export_json(self):
        """JSON dosyasını dışarı aktarır."""
        if not hasattr(self, 'final_race_data') or not self.final_race_data:
            messagebox.showerror("Hata", "Önce verileri birleştirin.")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Dosyaları", "*.json"), ("Tüm Dosyalar", "*.*")],
            title="Yarış Verilerini Kaydet"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.final_race_data, f, ensure_ascii=False, indent=2)
                messagebox.showinfo("Başarılı", f"Veriler başarıyla kaydedildi:\n{os.path.basename(file_path)}")
                print(f"JSON dosyası başarıyla kaydedildi: {file_path}")
            except Exception as e:
                messagebox.showerror("Hata", f"Dosya kaydedilirken hata oluştu:\n{e}")

    # ==================================================================
    # YENİ EKLENMİŞ FONKSİYONLAR - ÇOK ÖNEMLİ!
    # ==================================================================

    def add_stage_mapping_dropdown(self, mapping_key, stage_options):
        """Bir KML etabı için yeni bir eşleştirme dropdown'ı ekler."""
        mapping_info = self.kml_stage_mappings[mapping_key]
        mapping_frame = mapping_info['mapping_frame']
        actions_frame = mapping_info['actions_frame']
        
        # Mevcut eşleştirme sayısı
        current_count = len(mapping_info['mapped_stages'])
        
        # Yeni dropdown için frame
        dropdown_frame = ctk.CTkFrame(mapping_frame)
        dropdown_frame.grid(row=current_count, column=0, padx=2, pady=1, sticky="ew")
        
        # Dropdown menü
        mapping_var = ctk.StringVar(value="Seç")
        mapping_dropdown = ctk.CTkOptionMenu(
            dropdown_frame, 
            values=["Seç"] + stage_options, 
            variable=mapping_var,
            width=80
        )
        mapping_dropdown.grid(row=0, column=0, padx=2, pady=1)
        
        # Silme butonu
        remove_button = ctk.CTkButton(
            dropdown_frame, 
            text="×", 
            width=30,
            height=25,
            command=lambda: self.remove_stage_mapping(mapping_key, current_count)
        )
        remove_button.grid(row=0, column=1, padx=2, pady=1)
        
        # Eşleştirme verilerini sakla
        mapping_info['mapped_stages'].append({
            'var': mapping_var,
            'dropdown': mapping_dropdown,
            'frame': dropdown_frame,
            'remove_button': remove_button,
            'index': current_count
        })
        
        # İlk eşleştirme ise "Etap Ekle" butonunu oluştur
        if current_count == 0:
            add_button = ctk.CTkButton(
                actions_frame,
                text="+ Etap Ekle",
                width=100,
                command=lambda: self.add_stage_mapping_dropdown(mapping_key, stage_options)
            )
            add_button.grid(row=0, column=0, padx=2, pady=1)
            mapping_info['add_button'] = add_button
            self.mapping_widgets.append(add_button)
        
        # Widget'ları listeye ekle
        self.mapping_widgets.extend([dropdown_frame, mapping_dropdown, remove_button])

    def remove_stage_mapping(self, mapping_key, index_to_remove):
        """Belirli bir eşleştirme dropdown'ını kaldırır."""
        mapping_info = self.kml_stage_mappings[mapping_key]
        mapped_stages = mapping_info['mapped_stages']
        
        # En az bir eşleştirme kalmalı
        if len(mapped_stages) <= 1:
            return
        
        # Silinecek eşleştirmeyi bul
        stage_to_remove = None
        for stage in mapped_stages:
            if stage['index'] == index_to_remove:
                stage_to_remove = stage
                break
        
        if stage_to_remove:
            # Widget'ları yok et
            stage_to_remove['frame'].destroy()
            
            # Widget'ları listeden çıkar
            if stage_to_remove['dropdown'] in self.mapping_widgets:
                self.mapping_widgets.remove(stage_to_remove['dropdown'])
            if stage_to_remove['remove_button'] in self.mapping_widgets:
                self.mapping_widgets.remove(stage_to_remove['remove_button'])
            if stage_to_remove['frame'] in self.mapping_widgets:
                self.mapping_widgets.remove(stage_to_remove['frame'])
            
            # Listeden çıkar
            mapped_stages.remove(stage_to_remove)
            
            # Kalan eşleştirmelerin sırasını yeniden düzenle
            for i, stage in enumerate(mapped_stages):
                stage['index'] = i
                stage['frame'].grid(row=i, column=0, padx=2, pady=1, sticky="ew")

    # ==================================================================
    # WORKER FONKSİYONLARI (THREAD'LERDE ÇALIŞAN)
    # ==================================================================

    def fetch_race_data_worker(self, url, total_stages):
        """Yarış verilerini URL'den çeker."""
        try:
            print(f"Yarış verileri çekiliyor: {total_stages} etap")
            race_data = {}
            base_url = url
            sep = "?" if "?" not in base_url else "&"

            for stage in range(1, total_stages + 1):
                progress_queue.put(stage / total_stages)
                try:
                    current_url = f"{base_url}{sep}etp={stage}"
                    print(f"  Etap {stage}/{total_stages} çekiliyor...")
                    
                    response = requests.get(current_url, headers=UA, timeout=20)
                    response.raise_for_status()
                    html_content = response.text
                    soup = BeautifulSoup(html_content, 'lxml')
                    
                    table = soup.find('table')
                    if not table:
                        print(f"    -> Uyarı: Etap {stage} için tablo bulunamadı.")
                        continue

                    stage_results = []
                    for row in table.find_all('tr')[1:]:  # İlk satır header
                        cells = row.find_all('td')
                        if len(cells) < 7:
                            continue

                        # Süper Ralli (SR) filtresi
                        no_cell_text = cells[1].get_text(strip=True)
                        if "SR" in no_cell_text:
                            continue
                        
                        no_val = no_cell_text
                        pilot_name = ' '.join(cells[2].get_text(strip=True).split())
                        sk_class = cells[4].get_text(strip=True)
                        
                        # Süre bilgisini çek
                        time_li = cells[6].find('li')
                        if not time_li:
                            continue
                        
                        time_str = time_li.get_text(strip=True)
                        saniye = _time_to_sec(time_str)

                        if not pilot_name or saniye is None:
                            continue
                        
                        # Derece bilgisini çek (genellikle ilk sütun)
                        derece_str = cells[0].get_text(strip=True)
                        try:
                            derece = int(derece_str) if derece_str.isdigit() else None
                        except:
                            derece = None
                            
                        stage_results.append({
                            "derece": derece,
                            "kapi_no": no_val,
                            "pilot": normalize_pilot_name(pilot_name),
                            "sinif": sk_class,
                            "sure": time_str,
                            "saniye": saniye
                        })

                    race_data[stage] = stage_results
                    print(f"    -> {len(stage_results)} pilot kaydedildi")

                except Exception as ex:
                    print(f"  Hata: Etap {stage} işlenirken sorun oluştu: {ex}")
                    continue

            self.current_race_data = race_data
            
            # UI güncelleme
            def update_preview():
                self.race_data_preview.delete("1.0", "end")
                preview_text = f"Toplam {len(race_data)} etap verisi çekildi.\n\n"
                for stage_num, results in race_data.items():
                    preview_text += f"Etap {stage_num}: {len(results)} pilot\n"
                    if results:
                        preview_text += f"  Örnek: {results[0]['pilot']} - {results[0]['sure']}\n"
                self.race_data_preview.insert("end", preview_text)
            
            self.after(0, update_preview)
            print(f"Yarış verileri başarıyla çekildi: {len(race_data)} etap")

        except Exception as e:
            print(f"Yarış verileri çekilirken hata: {e}")
        finally:
            progress_queue.put(0)

    def analyze_kmls_worker(self):
        """KML dosyalarını analiz eder ve eşleştirme arayüzünü oluşturur."""
        try:
            print("KML dosyaları analiz ediliyor...")
            kml_stages = {}  # {day_num: {stage_name: stage_data}}
            
            for day_num, day_info in self.days_data.items():
                progress_queue.put(day_num / len(self.days_data))
                print(f"  Gün {day_num} KML dosyası analiz ediliyor...")
                
                kml_path = day_info['kml_path']
                stages_data = self.analyze_single_kml(kml_path)
                kml_stages[day_num] = stages_data
                
                print(f"    -> {len(stages_data)} etap bulundu")

            # UI'da eşleştirme tablosunu oluştur
            def create_mapping_ui():
                # Önceki widget'ları temizle
                for widget in self.mapping_widgets:
                    widget.destroy()
                self.mapping_widgets.clear()

                row = 0
                # Header
                ctk.CTkLabel(self.mapping_scroll_frame, text="Gün", font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, padx=5, pady=5)
                ctk.CTkLabel(self.mapping_scroll_frame, text="KML Etap Adı", font=ctk.CTkFont(weight="bold")).grid(row=row, column=1, padx=5, pady=5)
                ctk.CTkLabel(self.mapping_scroll_frame, text="Mesafe (km)", font=ctk.CTkFont(weight="bold")).grid(row=row, column=2, padx=5, pady=5)
                ctk.CTkLabel(self.mapping_scroll_frame, text="Yarış Etap Numaraları", font=ctk.CTkFont(weight="bold")).grid(row=row, column=3, padx=5, pady=5)
                ctk.CTkLabel(self.mapping_scroll_frame, text="İşlemler", font=ctk.CTkFont(weight="bold")).grid(row=row, column=4, padx=5, pady=5)
                row += 1

                # Tüm yarış etaplarının listesini oluştur
                all_race_stages = []
                for day_info in self.days_data.values():
                    all_race_stages.extend(day_info['stages'])
                all_race_stages = sorted(set(all_race_stages))
                stage_options = [str(s) for s in all_race_stages]

                # Her gün ve KML etabı için eşleştirme oluştur
                for day_num, day_stages in kml_stages.items():
                    for stage_name, stage_data in day_stages.items():
                        # Gün
                        day_label = ctk.CTkLabel(self.mapping_scroll_frame, text=str(day_num))
                        day_label.grid(row=row, column=0, padx=5, pady=2)
                        self.mapping_widgets.append(day_label)

                        # KML Etap Adı
                        stage_label = ctk.CTkLabel(self.mapping_scroll_frame, text=stage_name)
                        stage_label.grid(row=row, column=1, padx=5, pady=2)
                        self.mapping_widgets.append(stage_label)

                        # Mesafe
                        distance = stage_data.get('Toplam Uzaklık (km)', 0)
                        distance_label = ctk.CTkLabel(self.mapping_scroll_frame, text=f"{distance:.1f}")
                        distance_label.grid(row=row, column=2, padx=5, pady=2)
                        self.mapping_widgets.append(distance_label)

                        # Eşleştirme container frame
                        mapping_frame = ctk.CTkFrame(self.mapping_scroll_frame)
                        mapping_frame.grid(row=row, column=3, padx=5, pady=2, sticky="ew")
                        self.mapping_widgets.append(mapping_frame)

                        # İşlemler frame
                        actions_frame = ctk.CTkFrame(self.mapping_scroll_frame)
                        actions_frame.grid(row=row, column=4, padx=5, pady=2)
                        self.mapping_widgets.append(actions_frame)

                        # Eşleştirme verisini sakla
                        mapping_key = f"{day_num}_{stage_name}"
                        self.kml_stage_mappings[mapping_key] = {
                            'day': day_num,
                            'kml_stage_name': stage_name,
                            'kml_stage_data': stage_data,
                            'mapping_frame': mapping_frame,
                            'actions_frame': actions_frame,
                            'mapped_stages': []  # Eşleştirilen etapları tutacak liste
                        }

                        # İlk eşleştirme dropdown'ını ekle
                        self.add_stage_mapping_dropdown(mapping_key, stage_options)

                        row += 1

            self.after(0, create_mapping_ui)
            print("KML analizi tamamlandı ve eşleştirme tablosu oluşturuldu.")

        except Exception as e:
            print(f"KML analizi sırasında hata: {e}")
        finally:
            progress_queue.put(0)

    def analyze_single_kml(self, kml_path):
        """Tek bir KML dosyasını analiz eder ve etap verilerini döndürür."""
        kml_content = None
        file_extension = os.path.splitext(kml_path)[1].lower()

        # KML içeriğini oku
        if file_extension == ".kmz":
            try:
                with zipfile.ZipFile(kml_path, 'r') as kmz:
                    for name in kmz.namelist():
                        if name.endswith('.kml'):
                            kml_content = kmz.read(name).decode('utf-8')
                            break
            except Exception as e:
                print(f"KMZ okuma hatası: {e}")
                return {}
        elif file_extension == ".kml":
            try:
                with open(kml_path, 'r', encoding='utf-8') as f:
                    kml_content = f.read()
            except Exception as e:
                print(f"KML okuma hatası: {e}")
                return {}

        if not kml_content:
            return {}

        # KML'i analiz et
        return self.parse_kml_and_analyze_path(kml_content)

    def parse_kml_and_analyze_path(self, kml_content, rdp_epsilon=5.0):
        """KML içeriğini analiz ederek etap verilerini çıkarır."""
        results = {}
        try:
            root = ET.fromstring(kml_content)
            namespace = ''
            for elem in root.iter():
                if '}' in elem.tag:
                    namespace = elem.tag.split('}')[0] + '}'
                    break
            
            for placemark in root.findall(f'.//{namespace}Placemark'):
                name_elem = placemark.find(f'{namespace}name')
                name = name_elem.text if name_elem is not None else "İsimsiz Etap"

                if "ÖE" not in name:
                    continue

                linestring_elem = placemark.find(f'.//{namespace}LineString')
                if linestring_elem is None:
                    continue

                coordinates_elem = linestring_elem.find(f'{namespace}coordinates')
                if coordinates_elem is None or not coordinates_elem.text.strip():
                    continue

                coords_text = coordinates_elem.text.strip()
                original_points = []
                for coord_str in coords_text.split():
                    parts = coord_str.split(',')
                    try:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        alt = float(parts[2]) if len(parts) > 2 else 0.0 
                        original_points.append((lat, lon, alt))
                    except ValueError:
                        continue
                
                points = self._rdp_simplify(original_points, rdp_epsilon)
                
                if len(points) < 2:
                    results[name] = {'Toplam Uzaklık (km)': 0, 'Not': 'Yetersiz nokta sayısı'}
                    continue

                # Coğrafi analiz
                stage_analysis = self.calculate_geographic_metrics(points)
                results[name] = stage_analysis

            return results

        except ET.ParseError as e:
            print(f"XML Ayrıştırma Hatası: {e}")
            return {}
        except Exception as e:
            print(f"KML analizi genel hata: {e}")
            return {}

    def calculate_geographic_metrics(self, points):
        """Noktalar listesinden coğrafi metrikleri hesaplar."""
        total_distance_km = 0
        total_elevation_gain_m = 0
        total_elevation_loss_m = 0
        segment_slopes_degrees = []

        num_general_corners = 0
        sharp_turns_count = 0
        medium_turns_count = 0
        gentle_turns_count = 0
        significant_turn_angles = []

        total_straight_length_km = 0
        longest_straight_km = 0
        current_straight_length_km = 0
        num_straight_sections = 0

        general_corner_threshold_degrees = 15
        straight_threshold_degrees = 5
        sharp_turn_threshold_degrees = 45

        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i+1]

            segment_horizontal_distance_km = self._calculate_horizontal_distance(p1, p2)
            total_distance_km += segment_horizontal_distance_km

            elevation_diff_m = p2[2] - p1[2]
            if elevation_diff_m > 0:
                total_elevation_gain_m += elevation_diff_m
            else:
                total_elevation_loss_m += abs(elevation_diff_m)
            
            segment_horizontal_distance_m = segment_horizontal_distance_km * 1000
            if segment_horizontal_distance_m > 0:
                segment_slope_rad = math.atan2(elevation_diff_m, segment_horizontal_distance_m)
                segment_slopes_degrees.append(math.degrees(segment_slope_rad))

            if i < len(points) - 2:
                p_next_next = points[i+2]
                turn_angle_at_p2 = self._calculate_turn_angle(p1, p2, p_next_next)
                
                if turn_angle_at_p2 <= straight_threshold_degrees:
                     current_straight_length_km += segment_horizontal_distance_km
                else:
                    if current_straight_length_km > 0:
                        total_straight_length_km += current_straight_length_km
                        longest_straight_km = max(longest_straight_km, current_straight_length_km)
                        num_straight_sections += 1
                    current_straight_length_km = 0

                    if turn_angle_at_p2 > general_corner_threshold_degrees:
                        num_general_corners += 1
                        significant_turn_angles.append(turn_angle_at_p2)
                        if turn_angle_at_p2 > sharp_turn_threshold_degrees:
                            sharp_turns_count += 1
                        else:
                            medium_turns_count += 1
                    elif turn_angle_at_p2 > straight_threshold_degrees:
                        gentle_turns_count += 1
            else:
                current_straight_length_km += segment_horizontal_distance_km

        if current_straight_length_km > 0:
            total_straight_length_km += current_straight_length_km
            longest_straight_km = max(longest_straight_km, current_straight_length_km)
            num_straight_sections += 1

        avg_abs_slope_degree = 0
        if segment_slopes_degrees:
            avg_abs_slope_degree = sum(abs(s) for s in segment_slopes_degrees) / len(segment_slopes_degrees)

        average_turn_angle_degrees = sum(significant_turn_angles) / len(significant_turn_angles) if significant_turn_angles else 0
        max_turn_angle_degrees = max(significant_turn_angles) if significant_turn_angles else 0
        
        percentage_straightness = (total_straight_length_km / total_distance_km) * 100 if total_distance_km > 0 else 0

        return {
            'Orijinal Nokta Sayısı': len(points),
            'Sadeleştirilmiş Nokta Sayısı': len(points),
            'Toplam Uzaklık (km)': round(total_distance_km, 2),
            'Viraj Sayısı': num_general_corners,
            'Toplam Yükseklik Kazanımı (m)': round(total_elevation_gain_m, 2),
            'Toplam Yükseklik Kaybı (m)': round(total_elevation_loss_m, 2),
            'Ortalama Mutlak Eğim (Derece)': round(avg_abs_slope_degree, 2),
            'Keskin Viraj Sayısı (>45°)': sharp_turns_count,
            'Orta Viraj Sayısı (15°-45°)': medium_turns_count,
            'Hafif Viraj Sayısı (5°-15°)': gentle_turns_count,
            'Ortalama Viraj Açısı (Derece)': round(average_turn_angle_degrees, 2),
            'En Keskin Viraj Açısı (Derece)': round(max_turn_angle_degrees, 2),
            'Toplam Düzlük Mesafesi (km)': round(total_straight_length_km, 2),
            'En Uzun Düzlük (km)': round(longest_straight_km, 2),
            'Düzlük Yüzdesi (%)': round(percentage_straightness, 2),
            'Düzlük Bölüm Sayısı': num_straight_sections,
        }

    def generate_preview_worker(self):
        """Tüm verileri birleştirip önizleme oluşturur."""
        try:
            print("Veriler birleştirilerek önizleme oluşturuluyor...")
            
            # Temel yarış bilgileri
            race_info = {
                "url": self.race_url_entry.get().strip(),
                "tarih": self.race_date_entry.get().strip() or datetime.now().strftime("%Y-%m-%d"),
                "sezon": int(self.race_season_entry.get().strip() or datetime.now().year),
                "zemin": self.race_surface_menu.get(),
                "toplam_etap": len(self.current_race_data),
                "toplam_gun": len(self.days_data)
            }

            # Günler bilgisi
            gunler = {}
            for day_num, day_info in self.days_data.items():
                gunler[str(day_num)] = {
                    "kml_dosya": day_info['kml_filename'],
                    "etaplar": day_info['stages']
                }

            # Eşleştirme verilerini kontrol et - ÇOK ÖNEMLİ DEĞİŞİKLİK!
            mapping_data = {}
            for mapping_key, mapping_info in self.kml_stage_mappings.items():
                for stage_mapping in mapping_info['mapped_stages']:
                    selected_stage = stage_mapping['var'].get()
                    if selected_stage != "Seç" and selected_stage.isdigit():
                        race_stage_num = int(selected_stage)
                        mapping_data[race_stage_num] = {
                            'day': mapping_info['day'],
                            'kml_stage_name': mapping_info['kml_stage_name'],
                            'kml_stage_data': mapping_info['kml_stage_data']
                        }

            # Etap verilerini birleştir
            etap_verileri = {}
            for stage_num, stage_results in self.current_race_data.items():
                etap_data = {
                    "gun": None,
                    "cografi": {},
                    "sonuclar": stage_results
                }

                # Coğrafi veriyi ekle (eğer eşleştirme yapılmışsa)
                if stage_num in mapping_data:
                    map_info = mapping_data[stage_num]
                    etap_data["gun"] = map_info['day']
                    etap_data["cografi"] = map_info['kml_stage_data']

                etap_verileri[str(stage_num)] = etap_data

            # Final veri yapısı
            self.final_race_data = {
                "yarisInfo": race_info,
                "gunler": gunler,
                "etap_verileri": etap_verileri
            }

            # Önizleme metni oluştur
            def update_preview():
                self.final_preview_text.delete("1.0", "end")
                
                preview_text = f"""YARIŞ BİLGİLERİ:
URL: {race_info['url']}
Tarih: {race_info['tarih']}
Sezon: {race_info['sezon']}
Zemin: {race_info['zemin']}
Toplam Etap: {race_info['toplam_etap']}
Toplam Gün: {race_info['toplam_gun']}

GÜNLER:
"""
                for day_num, day_info in gunler.items():
                    preview_text += f"Gün {day_num}: {day_info['kml_dosya']} - Etaplar: {day_info['etaplar']}\n"

                preview_text += f"\nETAP VERİLERİ:\n"
                for stage_num, stage_data in etap_verileri.items():
                    preview_text += f"\nEtap {stage_num}:\n"
                    preview_text += f"  Gün: {stage_data['gun'] or 'Belirtilmemiş'}\n"
                    preview_text += f"  Pilot Sayısı: {len(stage_data['sonuclar'])}\n"
                    
                    if stage_data['cografi']:
                        geo = stage_data['cografi']
                        preview_text += f"  Coğrafi Veriler:\n"
                        preview_text += f"    Mesafe: {geo.get('Toplam Uzaklık (km)', 0)} km\n"
                        preview_text += f"    Viraj Sayısı: {geo.get('Viraj Sayısı', 0)}\n"
                        preview_text += f"    Yükseklik Kazanımı: {geo.get('Toplam Yükseklik Kazanımı (m)', 0)} m\n"
                    else:
                        preview_text += f"  Coğrafi Veriler: Eşleştirilmemiş\n"

                # EŞLEŞTIRME ÖZETİ EKLE
                preview_text += f"\nEŞLEŞTİRME ÖZETİ:\n"
                for mapping_key, mapping_info in self.kml_stage_mappings.items():
                    kml_name = mapping_info['kml_stage_name']
                    day = mapping_info['day']
                    mapped_stages_list = []
                    for stage_mapping in mapping_info['mapped_stages']:
                        selected = stage_mapping['var'].get()
                        if selected != "Seç":
                            mapped_stages_list.append(selected)
                    
                    if mapped_stages_list:
                        preview_text += f"  {kml_name} (Gün {day}) -> Etaplar: {', '.join(mapped_stages_list)}\n"

                self.final_preview_text.insert("end", preview_text)

            self.after(0, update_preview)
            print("Önizleme başarıyla oluşturuldu.")

        except Exception as e:
            print(f"Önizleme oluşturulurken hata: {e}")
        finally:
            progress_queue.put(0)

    def update_days_list_display(self):
        """Günler listesi görüntüsünü günceller."""
        self.days_list_text.delete("1.0", "end")
        if not self.days_data:
            self.days_list_text.insert("end", "Henüz gün eklenmedi.")
            return
        
        for day_num, day_info in sorted(self.days_data.items()):
            text = f"Gün {day_num}:\n"
            text += f"  KML: {day_info['kml_filename']}\n"
            text += f"  Etaplar: {', '.join(map(str, day_info['stages']))}\n\n"
            self.days_list_text.insert("end", text)

    # ==================================================================
    # YARDIMCI FONKSİYONLAR (KML ANALİZİ İÇİN)
    # ==================================================================

    def _calculate_horizontal_distance(self, p1, p2):
        """İki nokta arasındaki yatay mesafeyi km cinsinden hesaplar."""
        lat1, lon1, _ = p1
        lat2, lon2, _ = p2

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        R = 6371  # Dünya yarıçapı km
        a = math.sin(dlat / 2) * math.sin(dlat / 2) + \
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
            math.sin(dlon / 2) * math.sin(dlon / 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c
        return distance

    def _calculate_turn_angle(self, p1, p2, p3):
        """Üç nokta arasındaki dönüş açısını hesaplar."""
        lat1, lon1, _ = p1
        lat2, lon2, _ = p2
        lat3, lon3, _ = p3

        bearing1 = self._calculate_bearing(lat1, lon1, lat2, lon2)
        bearing2 = self._calculate_bearing(lat2, lon2, lat3, lon3)

        angle_diff = abs(bearing2 - bearing1)
        if angle_diff > 180:
            angle_diff = 360 - angle_diff
        return angle_diff

    def _calculate_bearing(self, lat1, lon1, lat2, lon2):
        """İki nokta arasındaki pusula açısını hesaplar."""
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        delta_lon = lon2_rad - lon1_rad
        
        x = math.sin(delta_lon) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - (math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon))
        
        initial_bearing = math.atan2(x, y)
        initial_bearing = math.degrees(initial_bearing)
        compass_bearing = (initial_bearing + 360) % 360
        
        return compass_bearing

    def _perpendicular_distance_m(self, pt, line_start, line_end):
        """Bir noktanın bir doğruya olan dik uzaklığını metre cinsinden hesaplar."""
        lat, lon, _ = pt
        lat_s, lon_s, _ = line_start
        lat_e, lon_e, _ = line_end

        METERS_PER_DEGREE_LAT = 111320 
        mid_lat_rad = math.radians((lat_s + lat_e) / 2)
        METERS_PER_DEGREE_LON = METERS_PER_DEGREE_LAT * math.cos(mid_lat_rad)

        p_x = (lon - lon_s) * METERS_PER_DEGREE_LON
        p_y = (lat - lat_s) * METERS_PER_DEGREE_LAT

        s_x, s_y = 0, 0 
        e_x = (lon_e - lon_s) * METERS_PER_DEGREE_LON
        e_y = (lat_e - lat_s) * METERS_PER_DEGREE_LAT

        se_x = e_x - s_x
        se_y = e_y - s_y

        len_sq = se_x**2 + se_y**2
        
        if len_sq == 0:
            return math.sqrt(p_x**2 + p_y**2)

        t = ((p_x - s_x) * se_x + (p_y - s_y) * se_y) / len_sq
        t = max(0, min(1, t))

        closest_x = s_x + t * se_x
        closest_y = s_y + t * se_y

        dist = math.sqrt((p_x - closest_x)**2 + (p_y - closest_y)**2)
        return dist

    def _rdp_simplify(self, points, epsilon):
        """Ramer-Douglas-Peucker algoritması ile nokta sadeleştirmesi."""
        if len(points) < 2:
            return points

        dmax = 0.0
        index = 0
        end = len(points) - 1

        for i in range(1, end):
            d = self._perpendicular_distance_m(points[i], points[0], points[end])
            if d > dmax:
                index = i
                dmax = d

        if dmax > epsilon:
            rec_results1 = self._rdp_simplify(points[0:index+1], epsilon)
            rec_results2 = self._rdp_simplify(points[index:end+1], epsilon)

            return rec_results1[:-1] + rec_results2
        else:
            return [points[0], points[end]]

if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = RallyDataCollector()
    app.mainloop()