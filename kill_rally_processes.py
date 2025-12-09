import subprocess
import sys

print("=" * 60)
print("RallyETA Process Temizleyici")
print("=" * 60)

# Find all RallyETA and Streamlit processes
try:
    result = subprocess.run(
        ['tasklist', '/FI', 'IMAGENAME eq RallyETA.exe'],
        capture_output=True,
        text=True
    )

    if "RallyETA.exe" in result.stdout:
        print("\n[+] RallyETA.exe calisiyor, kapatiliyor...")
        subprocess.run(['taskkill', '/F', '/IM', 'RallyETA.exe'], capture_output=True)
        print("  -> Kapatildi")
    else:
        print("\n[-] RallyETA.exe calismiyor")

    # Check for streamlit
    result = subprocess.run(
        ['tasklist', '/FI', 'IMAGENAME eq streamlit.exe'],
        capture_output=True,
        text=True
    )

    if "streamlit.exe" in result.stdout:
        print("\n[+] streamlit.exe calisiyor, kapatiliyor...")
        subprocess.run(['taskkill', '/F', '/IM', 'streamlit.exe'], capture_output=True)
        print("  -> Kapatildi")

    # Check for python processes running streamlit
    result = subprocess.run(
        ['netstat', '-ano'],
        capture_output=True,
        text=True
    )

    # Look for port 8501 (Streamlit default)
    for line in result.stdout.split('\n'):
        if ':8501' in line and 'LISTENING' in line:
            parts = line.split()
            pid = parts[-1]
            print(f"\n[+] Port 8501 kullanimda (PID: {pid}), kapatiliyor...")
            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
            print("  -> Kapatildi")
            break

    print("\n" + "=" * 60)
    print("[OK] Temizlik tamamlandi! Simdi programi tekrar calistirabilisiniz.")
    print("=" * 60)

except Exception as e:
    print(f"\n[ERROR] Hata: {e}")
    sys.exit(1)
