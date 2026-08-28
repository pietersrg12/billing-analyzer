@echo off
REM ============================================================
REM Build script PLN Billing Analyzer v1.0
REM ============================================================
REM Prerequisites:
REM   - Python 3.10 dengan semua dependency terinstall
REM   - PyInstaller (pip install pyinstaller)
REM   - Inno Setup 6 (untuk step installer; bisa skip kalau hanya butuh .exe)
REM
REM Output:
REM   - dist\PLN-Billing\PLN-Billing.exe  (folder distribution)
REM   - Output\PLN-Billing-Setup-v1.0.exe (installer, kalau Inno Setup terinstall)
REM ============================================================

setlocal

echo.
echo === [1/4] Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Output rmdir /s /q Output

echo.
echo === [2/4] Generating icon (assets\icon.ico) ===
if not exist assets mkdir assets
if not exist assets\icon.ico (
    python -c "from PIL import Image; im = Image.open('icon.png').convert('RGBA'); im.save('assets/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    if errorlevel 1 (
        echo ERROR: Gagal generate icon
        exit /b 1
    )
)

echo.
echo === [3/4] Building .exe with PyInstaller ===
python -m PyInstaller pln_billing.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build gagal
    exit /b 1
)

echo.
echo === [4/4] Building installer with Inno Setup ===
where iscc >nul 2>&1
if errorlevel 1 (
    echo INFO: iscc.exe tidak ditemukan di PATH.
    echo       Skip installer build. Hasil .exe ada di dist\PLN-Billing\
    echo       Untuk build installer, install Inno Setup 6 dari:
    echo       https://jrsoftware.org/isinfo.php
    goto :done
)

iscc installer.iss
if errorlevel 1 (
    echo ERROR: Inno Setup compilation gagal
    exit /b 1
)

:done
echo.
echo === BUILD SELESAI ===
echo.
if exist dist\PLN-Billing\PLN-Billing.exe (
    echo   Folder dist : dist\PLN-Billing\
    echo   .exe        : dist\PLN-Billing\PLN-Billing.exe
)
if exist Output (
    for %%f in (Output\*.exe) do echo   Installer   : %%f
)
echo.

REM Reset errorlevel: 'where iscc' di atas menyisakan 1 saat Inno Setup
REM tidak terpasang, sehingga build yang sukses ikut terlaporkan gagal.
endlocal
exit /b 0
