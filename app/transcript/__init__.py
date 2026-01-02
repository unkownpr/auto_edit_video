"""Transcript module - Whisper integration."""

from .transcriber import Transcriber, transcribe_audio

__all__ = [
    "Transcriber",
    "transcribe_audio",
]
