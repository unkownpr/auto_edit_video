#!/bin/bash
# AutoCut - Sanal Ortam Kurulum Scripti
# Kullanım: ./setup.sh

set -e  # Hata durumunda dur

VENV_DIR=".venv"
PYTHON_CMD="python3"

echo "🎬 AutoCut Kurulum Başlıyor..."
echo "================================"

# Python sürümünü kontrol et
echo "📌 Python sürümü kontrol ediliyor..."
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "❌ Python3 bulunamadı! Lütfen Python 3.11+ yükleyin."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "   Python $PYTHON_VERSION bulundu"

# Sanal ortam oluştur
echo ""
echo "📦 Sanal ortam oluşturuluyor ($VENV_DIR)..."
if [ -d "$VENV_DIR" ]; then
    echo "   Mevcut sanal ortam siliniyor..."
    rm -rf "$VENV_DIR"
fi

$PYTHON_CMD -m venv "$VENV_DIR"
echo "   ✅ Sanal ortam oluşturuldu"

# Sanal ortamı aktifle
echo ""
echo "🔄 Sanal ortam aktifleştiriliyor..."
source "$VENV_DIR/bin/activate"

# pip güncelle
echo ""
echo "⬆️  pip güncelleniyor..."
pip install --upgrade pip --quiet

# Bağımlılıkları yükle
echo ""
echo "📥 Bağımlılıklar yükleniyor..."
pip install -r requirements.txt

# Geliştirme bağımlılıkları (opsiyonel)
echo ""
read -p "🔧 Geliştirme bağımlılıklarını da yüklemek ister misiniz? (pytest, ruff, mypy) [y/N]: " install_dev
if [[ "$install_dev" =~ ^[Yy]$ ]]; then
    echo "   Geliştirme bağımlılıkları yükleniyor..."
    pip install pytest pytest-qt pytest-cov ruff mypy
fi

# FFmpeg kontrolü
echo ""
echo "🎥 FFmpeg kontrol ediliyor..."
if command -v ffmpeg &> /dev/null; then
    FFMPEG_VERSION=$(ffmpeg -version | head -n1)
    echo "   ✅ $FFMPEG_VERSION"
else
    echo "   ⚠️  FFmpeg bulunamadı!"
    echo "   Yüklemek için:"
    echo "     macOS:  brew install ffmpeg"
    echo "     Ubuntu: sudo apt install ffmpeg"
    echo "     Windows: choco install ffmpeg"
fi

# Kurulum tamamlandı
echo ""
echo "================================"
echo "✅ Kurulum tamamlandı!"
echo ""
echo "🚀 Uygulamayı çalıştırmak için:"
echo ""
echo "   # Sanal ortamı aktifle"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo "   # Uygulamayı başlat"
echo "   python main.py"
echo ""
echo "   # Veya direkt video dosyası ile"
echo "   python main.py /path/to/video.mp4"
echo ""
echo "   # Testleri çalıştır"
echo "   pytest tests/"
echo ""
