import streamlit.web.cli as stcli
import sys
import os
from pathlib import Path
import webbrowser
import time
import threading
import subprocess
import atexit

def cleanup_processes():
    """Program kapanırken kalan processleri temizle"""
    try:
        # Kill any stuck streamlit/python processes on port 8501
        subprocess.run(['taskkill', '/F', '/IM', 'streamlit.exe'],
                      capture_output=True, stderr=subprocess.DEVNULL)

        # Find and kill process using port 8501
        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if ':8501' in line and 'LISTENING' in line:
                parts = line.split()
                if len(parts) > 0:
                    pid = parts[-1]
                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                 capture_output=True, stderr=subprocess.DEVNULL)
    except:
        pass  # Silent cleanup

def open_browser():
    """Tarayıcıyı otomatik aç"""
    time.sleep(4)  # Streamlit'in başlaması için bekle
    webbrowser.open('http://localhost:8501')

if __name__ == '__main__':
    # Cleanup processes on exit
    atexit.register(cleanup_processes)

    try:
        # Başlamadan önce varsa eski processleri temizle
        cleanup_processes()

        # Çalışma dizinini ayarla
        if getattr(sys, 'frozen', False):
            # EXE içindeysek - EXE'nin bulunduğu dizinde kal
            # (data, config, models klasörleri burada)
            exe_dir = Path(sys.executable).parent
            os.chdir(exe_dir)

            # app.py ise _MEIPASS içinde
            app_path = Path(sys._MEIPASS) / "app.py"

            if not app_path.exists():
                # Hata mesajı göster
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("Rally ETA Error", "app.py bulunamadi!\n\nLutfen programi yeniden yuklemeyi deneyin.")
                sys.exit(1)
        else:
            # Development modunda
            app_path = Path(__file__).parent / "app.py"

        # Tarayıcıyı ayrı thread'de aç
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()

        # Streamlit başlat
        sys.argv = [
            "streamlit",
            "run",
            str(app_path),
            "--global.developmentMode=false",
        ]

        sys.exit(stcli.main())

    except Exception as e:
        # Hata durumunda messagebox göster
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Rally ETA Error", f"Bir hata olustu:\n\n{str(e)}\n\nLutfen programi yeniden baslatmayi deneyin.")
        sys.exit(1)
