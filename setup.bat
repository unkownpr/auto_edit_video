@echo off
REM AutoCut - Sanal Ortam Kurulum Scripti (Windows)
REM Kullanim: setup.bat

setlocal enabledelayedexpansion

set VENV_DIR=.venv
set PYTHON_CMD=python

echo 🎬 AutoCut Kurulum Basliyor...
echo ================================

REM Python kontrolu
echo 📌 Python surumu kontrol ediliyor...
%PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python bulunamadi! Lutfen Python 3.11+ yukleyin.
    exit /b 1
)

for /f "tokens=2" %%i in ('%PYTHON_CMD% --version') do set PYTHON_VERSION=%%i
echo    Python %PYTHON_VERSION% bulundu

REM Sanal ortam olustur
echo.
echo 📦 Sanal ortam olusturuluyor (%VENV_DIR%)...
if exist "%VENV_DIR%" (
    echo    Mevcut sanal ortam siliniyor...
    rmdir /s /q "%VENV_DIR%"
)

%PYTHON_CMD% -m venv "%VENV_DIR%"
echo    ✅ Sanal ortam olusturuldu

REM Sanal ortami aktifle
echo.
echo 🔄 Sanal ortam aktiflestiriliyor...
call "%VENV_DIR%\Scripts\activate.bat"

REM pip guncelle
echo.
echo ⬆️  pip guncelleniyor...
pip install --upgrade pip --quiet

REM Bagimliliklari yukle
echo.
echo 📥 Bagimliliklar yukleniyor...
pip install -r requirements.txt

REM FFmpeg kontrolu
echo.
echo 🎥 FFmpeg kontrol ediliyor...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo    ⚠️  FFmpeg bulunamadi!
    echo    Yuklemek icin: choco install ffmpeg
    echo    veya https://ffmpeg.org/download.html
) else (
    echo    ✅ FFmpeg bulundu
)

REM Kurulum tamamlandi
echo.
echo ================================
echo ✅ Kurulum tamamlandi!
echo.
echo 🚀 Uygulamayi calistirmak icin:
echo.
echo    REM Sanal ortami aktifle
echo    %VENV_DIR%\Scripts\activate.bat
echo.
echo    REM Uygulamayi baslat
echo    python main.py
echo.

endlocal
