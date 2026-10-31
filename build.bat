@echo off
REM ============================================================
REM Build script SIMBA (Sistem Monitoring Baca Meter) v2.7
REM ============================================================
REM Prasyarat:
REM   - Python 3.10 dengan semua dependency terinstall
REM   - PyInstaller  (pip install pyinstaller)
REM   - PyArmor      (pip install pyarmor)
REM   - Inno Setup 6 (opsional, untuk installer)
REM
REM Output:
REM   - dist\PLN-Billing\PLN-Billing.exe   (folder distribution)
REM   - Output\SIMBA-Setup-v2.7.exe        (installer)
REM
REM CATATAN: yang di-build adalah build_obf\ (salinan teracak PyArmor),
REM bukan source folder ini. Lihat pln_billing.spec.
REM ============================================================

setlocal

echo.
echo === [1/5] Membersihkan hasil build sebelumnya ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Output rmdir /s /q Output
REM build_obf WAJIB ikut dibersihkan: sisa acakan lama akan ikut terbundel
REM diam-diam kalau ada file yang sudah dihapus dari source.
if exist build_obf rmdir /s /q build_obf

echo.
echo === [2/5] Menyiapkan icon (assets\icon.ico) ===
if not exist assets mkdir assets
if not exist assets\icon.ico (
    python -c "from PIL import Image; im = Image.open('icon.png').convert('RGBA'); im.save('assets/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    if errorlevel 1 (
        echo ERROR: Gagal generate icon
        exit /b 1
    )
)

echo.
echo === [3/5] Mengacak kode dengan PyArmor ===
python -m pyarmor.cli gen -O build_obf --recursive main.py ui.py ui_dialogs.py config.py core
if errorlevel 1 (
    echo ERROR: PyArmor gagal.
    echo        Pastikan sudah terpasang: pip install pyarmor
    echo        Catatan: versi trial menolak code object di atas 35.728 byte -
    echo        kalau ada modul yang membengkak, pecah dulu modulnya.
    exit /b 1
)
if not exist build_obf\main.py (
    echo ERROR: build_obf\main.py tidak terbentuk. Build dihentikan supaya
    echo        tidak diam-diam membundel source yang TIDAK teracak.
    exit /b 1
)

echo.
echo === [4/5] Membangun .exe dengan PyInstaller ===
python -m PyInstaller pln_billing.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build gagal
    exit /b 1
)

echo.
echo === [5/5] Membangun installer dengan Inno Setup ===
REM Installer Inno Setup TIDAK menambahkan dirinya ke PATH, jadi `where iscc`
REM saja tidak cukup - tanpa fallback ini langkah installer terlewat diam-diam
REM padahal Inno Setup sebenarnya sudah terpasang.
set "ISCC="
for /f "delims=" %%i in ('where iscc 2^>nul') do set "ISCC=%%i"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo INFO: ISCC.exe tidak ditemukan.
    echo       Skip pembuatan installer. Hasil .exe ada di dist\PLN-Billing\
    echo       Install Inno Setup 6 dari https://jrsoftware.org/isdl.php
    echo       lalu cukup jalankan: iscc installer.iss
    goto :done
)

echo Memakai: %ISCC%
"%ISCC%" installer.iss
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

REM Reset errorlevel: 'where iscc' di atas menyisakan 1 saat Inno Setup tidak
REM terpasang, sehingga build yang sukses ikut terlaporkan gagal.
endlocal
exit /b 0
