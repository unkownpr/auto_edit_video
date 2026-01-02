#!/usr/bin/env python3
"""
AutoCut - Automatic silence removal and FCPXML export tool.

Entry point for the application.
"""

import sys
import os
import logging
from pathlib import Path

# Disable Qt multimedia to prevent FFmpeg crashes on macOS
os.environ.setdefault("QT_MEDIA_BACKEND", "")

# Fix macOS dock name showing "Python" instead of app name
def _set_macos_app_name(name: str):
    """Set the application name in macOS dock."""
    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        if bundle:
            info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
            if info:
                info['CFBundleName'] = name
    except ImportError:
        pass  # PyObjC not installed, skip

if sys.platform == 'darwin':
    _set_macos_app_name('AutoCut')

from PySide6.QtWidgets import QApplication

from app import __version__, __app_name__
from app.ui.main_window import MainWindow
from app.core.settings import Settings


def setup_logging(debug: bool = False):
    """Logging konfigürasyonu."""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Reduce noise from external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)


def main():
    """Ana uygulama giriş noktası."""
    # Parse arguments
    debug = "--debug" in sys.argv

    setup_logging(debug)
    # Note: Qt 6 handles HiDPI automatically

    logger = logging.getLogger(__name__)
    logger.info(f"Starting {__app_name__} v{__version__}")

    # Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)  # This shows in macOS dock/menu
    app.setApplicationVersion(__version__)
    app.setOrganizationName("AutoCut")
    app.setDesktopFileName("autocut")  # For Linux .desktop file

    # Default font
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)

    # Ana pencere
    window = MainWindow()
    window.show()

    # Komut satırından dosya açma
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        if not file_path.startswith("--") and Path(file_path).exists():
            window._load_media(Path(file_path))

    # Event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
