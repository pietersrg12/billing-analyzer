@echo off
REM ============================================================
REM  PLN Billing Analyzer - Launcher
REM  Double-click file ini untuk menjalankan aplikasi
REM ============================================================

cd /d "%~dp0"

REM Cek python tersedia
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan di PATH.
    echo Install Python 3.10+ dari https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Menjalankan PLN Billing Analyzer...
echo.

python main.py
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
    echo.
    echo [ERROR] Aplikasi keluar dengan kode %EXITCODE%
    pause
)

exit /b %EXITCODE%
