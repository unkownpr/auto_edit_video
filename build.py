#!/usr/bin/env python3
"""
AutoCut Build Script

PyInstaller ile macOS .app ve Windows .exe oluşturur.

Kullanım:
    python build.py          # Mevcut platform için build
    python build.py --all    # Tüm platformlar için (cross-compile desteklenmiyor)
    python build.py --clean  # Build artifacts temizle
"""

import os
import sys
import shutil
import subprocess
import platform
from pathlib import Path

# Build dizinleri
ROOT_DIR = Path(__file__).parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
SPEC_DIR = ROOT_DIR / "specs"

# Uygulama bilgileri
APP_NAME = "AutoCut"
APP_VERSION = "0.1.0"
APP_BUNDLE_ID = "com.autocut.app"


def clean():
    """Build artifacts temizle."""
    print("🧹 Temizleniyor...")

    for dir_path in [DIST_DIR, BUILD_DIR, SPEC_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"   Silindi: {dir_path}")

    # .spec dosyaları
    for spec in ROOT_DIR.glob("*.spec"):
        spec.unlink()
        print(f"   Silindi: {spec}")

    print("   ✅ Temizlik tamamlandı")


def check_dependencies():
    """Gerekli araçları kontrol et."""
    print("🔍 Bağımlılıklar kontrol ediliyor...")

    # PyInstaller
    try:
        import PyInstaller
        print(f"   ✅ PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("   ❌ PyInstaller bulunamadı!")
        print("   Yüklemek için: pip install pyinstaller")
        sys.exit(1)

    # PySide6
    try:
        import PySide6
        print(f"   ✅ PySide6 {PySide6.__version__}")
    except ImportError:
        print("   ❌ PySide6 bulunamadı!")
        sys.exit(1)


def find_ffmpeg_binaries() -> list:
    """FFmpeg binary'lerini bul ve --add-binary argümanları oluştur.

    Önce static-ffmpeg paketini kontrol eder (static binary, bağımlılık yok),
    bulamazsa sistem FFmpeg'ini kullanır.
    """
    binaries = []

    # Önce static-ffmpeg paketini dene (tercih edilen - static binary)
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()

        # static-ffmpeg binary konumunu bul
        import importlib.util
        spec = importlib.util.find_spec("static_ffmpeg")
        if spec and spec.origin:
            static_bin_dir = Path(spec.origin).parent / "bin"

            # Platform'a göre klasör
            if platform.system() == "Darwin":
                platform_dir = static_bin_dir / "darwin"
            elif platform.system() == "Windows":
                platform_dir = static_bin_dir / "win32"
            else:
                platform_dir = static_bin_dir / "linux"

            ffmpeg_static = platform_dir / "ffmpeg"
            ffprobe_static = platform_dir / "ffprobe"

            if ffmpeg_static.exists():
                binaries.extend(["--add-binary", f"{ffmpeg_static}{os.pathsep}bin"])
                print(f"   📦 FFmpeg (static): {ffmpeg_static}")

            if ffprobe_static.exists():
                binaries.extend(["--add-binary", f"{ffprobe_static}{os.pathsep}bin"])
                print(f"   📦 FFprobe (static): {ffprobe_static}")

            if binaries:
                return binaries

    except ImportError:
        print("   ℹ️  static-ffmpeg paketi bulunamadı, sistem FFmpeg'i aranıyor...")

    # Fallback: Sistem FFmpeg'i (Homebrew vb.)
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if ffmpeg_path:
        ffmpeg_real = os.path.realpath(ffmpeg_path)
        binaries.extend(["--add-binary", f"{ffmpeg_real}{os.pathsep}bin"])
        print(f"   📦 FFmpeg (system): {ffmpeg_real}")

    if ffprobe_path:
        ffprobe_real = os.path.realpath(ffprobe_path)
        binaries.extend(["--add-binary", f"{ffprobe_real}{os.pathsep}bin"])
        print(f"   📦 FFprobe (system): {ffprobe_real}")

    if not binaries:
        print("   ⚠️  FFmpeg bulunamadı, bundle'a dahil edilmeyecek")

    return binaries


def get_platform_args() -> list:
    """Platform'a özel PyInstaller argümanları."""
    system = platform.system()

    # FFmpeg binary'lerini bul
    ffmpeg_binaries = find_ffmpeg_binaries()

    common_args = [
        "--name", APP_NAME,
        "--windowed",  # GUI app, konsol penceresi yok
        "--noconfirm",  # Eski build'i üzerine yaz
        "--clean",  # Temiz build
        # Hidden imports
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "numpy",
        "--hidden-import", "scipy",
        "--hidden-import", "lxml",
        # Data files
        "--add-data", f"app/ui/styles{os.pathsep}app/ui/styles",
    ] + ffmpeg_binaries

    if system == "Darwin":  # macOS
        return common_args + [
            "--osx-bundle-identifier", APP_BUNDLE_ID,
            "--icon", "resources/icon.icns",
        ]

    elif system == "Windows":
        return common_args + [
            # Windows için ikon (varsa)
            # "--icon", "resources/icon.ico",
            "--version-file", "version_info.txt",
        ]

    elif system == "Linux":
        return common_args + [
            # Linux için
        ]

    return common_args


def create_version_info():
    """Windows için version info dosyası oluştur."""
    if platform.system() != "Windows":
        return

    version_parts = APP_VERSION.split(".")
    while len(version_parts) < 4:
        version_parts.append("0")

    version_tuple = ", ".join(version_parts[:4])

    content = f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({version_tuple}),
    prodvers=({version_tuple}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'AutoCut'),
            StringStruct('FileDescription', 'Automatic Silence Removal Tool'),
            StringStruct('FileVersion', '{APP_VERSION}'),
            StringStruct('InternalName', '{APP_NAME}'),
            StringStruct('OriginalFilename', '{APP_NAME}.exe'),
            StringStruct('ProductName', '{APP_NAME}'),
            StringStruct('ProductVersion', '{APP_VERSION}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''
    (ROOT_DIR / "version_info.txt").write_text(content)


def build():
    """Uygulamayı build et."""
    system = platform.system()
    print(f"🔨 Build başlıyor ({system})...")

    check_dependencies()
    create_version_info()

    # PyInstaller çalıştır
    args = ["pyinstaller"] + get_platform_args() + ["main.py"]

    print(f"   Komut: {' '.join(args)}")
    print()

    result = subprocess.run(args, cwd=ROOT_DIR)

    if result.returncode != 0:
        print("❌ Build başarısız!")
        sys.exit(1)

    # Sonuç
    print()
    print("=" * 50)
    print("✅ Build tamamlandı!")
    print()

    if system == "Darwin":
        app_path = DIST_DIR / f"{APP_NAME}.app"
        print(f"   📦 macOS App: {app_path}")
        print()
        print("   Çalıştırmak için:")
        print(f"   open {app_path}")
        print()
        print("   DMG oluşturmak için:")
        print("   pip install dmgbuild")
        print("   dmgbuild -s dmg_settings.py 'AutoCut' AutoCut.dmg")

    elif system == "Windows":
        exe_path = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
        print(f"   📦 Windows EXE: {exe_path}")
        print()
        print("   Installer oluşturmak için NSIS veya Inno Setup kullanabilirsiniz.")

    elif system == "Linux":
        exe_path = DIST_DIR / APP_NAME / APP_NAME
        print(f"   📦 Linux Binary: {exe_path}")
        print()
        print("   AppImage oluşturmak için:")
        print("   pip install python-appimage")

    print()


def create_dmg_settings():
    """macOS DMG ayarları dosyası oluştur."""
    if platform.system() != "Darwin":
        return

    content = f'''# -*- coding: utf-8 -*-
# DMG ayarları - dmgbuild için

import os

application = "dist/{APP_NAME}.app"
appname = os.path.basename(application)

# Volume icon - uses the app icon
badge_icon = "resources/icon.icns"

# Volume ayarları
volume_name = "{APP_NAME} {APP_VERSION}"
format = "UDBZ"  # Sıkıştırılmış

# Pencere ayarları
size = (640, 480)
background = None

# İkon pozisyonları
icon_size = 128
icon_locations = {{
    appname: (140, 240),
    "Applications": (500, 240),
}}

# Applications symlink
symlinks = {{"Applications": "/Applications"}}
'''
    (ROOT_DIR / "dmg_settings.py").write_text(content)
    print("   📝 dmg_settings.py oluşturuldu")


def main():
    """Ana giriş noktası."""
    if len(sys.argv) > 1:
        arg = sys.argv[1]

        if arg == "--clean":
            clean()
            return

        if arg == "--help" or arg == "-h":
            print(__doc__)
            return

    clean()
    build()

    if platform.system() == "Darwin":
        create_dmg_settings()


if __name__ == "__main__":
    main()
