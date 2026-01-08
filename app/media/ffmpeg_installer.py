"""
FFmpeg auto-installer for macOS.

Provides automatic FFmpeg installation via Homebrew on macOS.
"""

import subprocess
import shutil
import sys
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def is_ffmpeg_installed() -> bool:
    """Check if FFmpeg is installed and accessible."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def is_homebrew_installed() -> bool:
    """Check if Homebrew is installed."""
    return shutil.which("brew") is not None


def get_homebrew_install_command() -> str:
    """Get the Homebrew installation command."""
    return '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'


def install_ffmpeg_via_homebrew(progress_callback=None) -> Tuple[bool, str]:
    """
    Install FFmpeg via Homebrew on macOS.

    Args:
        progress_callback: Optional callback(progress: int, message: str)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if sys.platform != "darwin":
        return False, "This installer only works on macOS"

    if progress_callback:
        progress_callback(10, "Checking Homebrew...")

    # Check if Homebrew is installed
    if not is_homebrew_installed():
        return False, "Homebrew is not installed. Please install Homebrew first:\n\n" + get_homebrew_install_command()

    if progress_callback:
        progress_callback(20, "Homebrew found. Installing FFmpeg...")

    logger.info("Installing FFmpeg via Homebrew...")

    try:
        # Run brew install ffmpeg
        process = subprocess.Popen(
            ["brew", "install", "ffmpeg"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output_lines = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                output_lines.append(line.strip())
                logger.debug(f"brew: {line.strip()}")

                # Update progress based on output
                if progress_callback:
                    if "Downloading" in line:
                        progress_callback(40, "Downloading FFmpeg...")
                    elif "Pouring" in line or "Installing" in line:
                        progress_callback(70, "Installing FFmpeg...")
                    elif "Summary" in line:
                        progress_callback(90, "Finishing installation...")

        return_code = process.wait()

        if return_code == 0:
            if progress_callback:
                progress_callback(100, "FFmpeg installed successfully!")
            logger.info("FFmpeg installed successfully via Homebrew")
            return True, "FFmpeg installed successfully!"
        else:
            error_msg = "\n".join(output_lines[-10:])  # Last 10 lines
            logger.error(f"Homebrew install failed: {error_msg}")
            return False, f"Installation failed:\n{error_msg}"

    except FileNotFoundError:
        return False, "Homebrew command not found"
    except Exception as e:
        logger.exception(f"FFmpeg installation error: {e}")
        return False, f"Installation error: {str(e)}"


def get_ffmpeg_install_instructions() -> str:
    """Get platform-specific FFmpeg installation instructions."""
    if sys.platform == "darwin":
        return """FFmpeg is required but not installed.

Install via Homebrew (recommended):
  brew install ffmpeg

Or download from: https://ffmpeg.org/download.html"""

    elif sys.platform == "win32":
        return """FFmpeg is required but not installed.

Download from: https://ffmpeg.org/download.html
Or use winget: winget install ffmpeg

After installation, add FFmpeg to your PATH."""

    else:  # Linux
        return """FFmpeg is required but not installed.

Install via package manager:
  Ubuntu/Debian: sudo apt install ffmpeg
  Fedora: sudo dnf install ffmpeg
  Arch: sudo pacman -S ffmpeg"""


def check_and_offer_install() -> Tuple[bool, Optional[str]]:
    """
    Check if FFmpeg is installed and offer to install if not.

    Returns:
        Tuple of (is_available: bool, error_message: Optional[str])
    """
    if is_ffmpeg_installed():
        return True, None

    # FFmpeg not found
    if sys.platform == "darwin" and is_homebrew_installed():
        # Can offer automatic installation
        return False, "auto_install_available"
    else:
        # Manual installation required
        return False, get_ffmpeg_install_instructions()
