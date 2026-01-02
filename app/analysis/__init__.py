"""Audio analysis module."""

from .silence_detector import SilenceDetector, detect_silence

__all__ = [
    "SilenceDetector",
    "detect_silence",
]
