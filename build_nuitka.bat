@echo off
REM ============================================================
REM Build SIMBA dengan Nuitka (eksperimen, berdampingan dengan build.bat)
REM ============================================================
REM Prasyarat:
REM   - Python 3.10 dengan semua dependency terinstall
REM   - Nuitka (pip install nuitka ordered-set zstandard)
REM   - MinGW64 diunduh otomatis oleh Nuitka (--assume-yes-for-downloads)
REM
REM Output:
REM   - dist_nuitka\PLN-Billing\PLN-Billing.exe
REM
REM Yang dikompilasi adalah source POLOS lewat tools\nuitka_entry.py, bukan
REM build_obf\: blob PyArmor tidak bisa dikompilasi ke C. build.bat, dist\
REM dan build_obf\ tidak disentuh.
REM ============================================================

setlocal

echo.
echo === [1/3] Membersihkan hasil build Nuitka sebelumnya ===
if exist build_nuitka rmdir /s /q build_nuitka
if exist dist_nuitka rmdir /s /q dist_nuitka

if not exist assets\icon.ico (
    echo ERROR: assets\icon.ico tidak ada. Jalankan build.bat sekali, atau buat icon dulu.
    exit /b 1
)

echo.
echo === [2/3] Mengompilasi dengan Nuitka ===
REM PYTHONPATH = root proyek supaya tools\nuitka_entry.py menemukan main.py.
set "PYTHONPATH=%~dp0"
python -m nuitka tools\nuitka_entry.py ^
    --standalone ^
    --mingw64 ^
    --assume-yes-for-downloads ^
    --output-dir=build_nuitka ^
    --output-filename=PLN-Billing.exe ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets\icon.ico ^
    --enable-plugin=tk-inter ^
    --module-parameter=torch-disable-jit=yes ^
    --include-module=main ^
    --include-module=ui ^
    --include-module=ui_dialogs ^
    --include-module=ui_koreksi ^
    --include-package=core ^
    --include-package=msoffcrypto ^
    --include-package=webview ^
    --include-package-data=webview ^
    --include-module=clr ^
    --include-package=clr_loader ^
    --include-package-data=clr_loader ^
    --include-package-data=pythonnet ^
    --include-module=xlsxwriter ^
    --include-module=pyxlsb ^
    --include-package-data=tkinterdnd2 ^
    --include-package-data=ttkbootstrap ^
    --include-package-data=openpyxl ^
    --include-package-data=ultralytics ^
    --include-data-files=model\best.pt=model\best.pt ^
    --include-data-files=model\digit_detector.pt=model\digit_detector.pt ^
    --include-data-files=model\display_detector.pt=model\display_detector.pt ^
    --include-data-files=assets\icon.ico=assets\icon.ico ^
    --include-data-files=assets\logo_emblem.png=assets\logo_emblem.png ^
    --include-data-files=assets\logo_simba.png=assets\logo_simba.png ^
    --nofollow-import-to=matplotlib,scipy,IPython,jupyter,notebook,ipykernel,pytest,tornado,sphinx,tensorboard,onnx,onnxruntime,torchaudio,pandas.tests,numpy.tests,trio ^
    --low-memory ^
    --jobs=4
if errorlevel 1 (
    echo ERROR: Nuitka build gagal
    exit /b 1
)

echo.
echo === [3/3] Memindahkan hasil ke dist_nuitka\PLN-Billing ===
mkdir dist_nuitka
move build_nuitka\nuitka_entry.dist dist_nuitka\PLN-Billing >nul
if not exist dist_nuitka\PLN-Billing\PLN-Billing.exe (
    echo ERROR: dist_nuitka\PLN-Billing\PLN-Billing.exe tidak terbentuk
    exit /b 1
)

echo.
echo === BUILD NUITKA SELESAI ===
echo   .exe : dist_nuitka\PLN-Billing\PLN-Billing.exe
echo.
endlocal
exit /b 0
