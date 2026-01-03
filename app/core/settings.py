"""
Application settings and preset configurations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from enum import Enum

from platformdirs import user_data_dir, user_cache_dir

from .models import AnalysisConfig


APP_NAME = "AutoCut"
APP_AUTHOR = "AutoCut"


class Theme(Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


@dataclass
class Preset:
    """Analiz preset'i."""
    name: str
    description: str
    config: AnalysisConfig

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "config": self.config.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Preset:
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            config=AnalysisConfig.from_dict(data["config"]),
        )


# Varsayılan preset'ler
DEFAULT_PRESETS = [
    Preset(
        name="Podcast",
        description="Podcast/interview - doğal duraklamalar korunur",
        config=AnalysisConfig(
            silence_threshold_db=-30.0,
            silence_min_duration_ms=600,
            pre_pad_ms=120,
            post_pad_ms=180,
            merge_gap_ms=400,
            keep_short_pauses_ms=200,
            breath_detection=False,
        ),
    ),
    Preset(
        name="Tutorial",
        description="Eğitim videosu - dengeli kesim",
        config=AnalysisConfig(
            silence_threshold_db=-32.0,
            silence_min_duration_ms=500,
            pre_pad_ms=100,
            post_pad_ms=150,
            merge_gap_ms=300,
            keep_short_pauses_ms=150,
            breath_detection=False,
        ),
    ),
    Preset(
        name="Meeting",
        description="Toplantı kaydı - orta seviye temizlik",
        config=AnalysisConfig(
            silence_threshold_db=-28.0,
            silence_min_duration_ms=800,
            pre_pad_ms=150,
            post_pad_ms=200,
            merge_gap_ms=500,
            keep_short_pauses_ms=250,
            breath_detection=False,
        ),
    ),
    Preset(
        name="Noisy Room",
        description="Gürültülü ortam - VAD kullan",
        config=AnalysisConfig(
            silence_threshold_db=-25.0,
            silence_min_duration_ms=600,
            pre_pad_ms=120,
            post_pad_ms=180,
            merge_gap_ms=400,
            keep_short_pauses_ms=200,
            use_vad=True,
            vad_aggressiveness=2,
        ),
    ),
    Preset(
        name="Aggressive",
        description="Agresif kesim - sıkı düzenleme",
        config=AnalysisConfig(
            silence_threshold_db=-35.0,
            silence_min_duration_ms=300,
            pre_pad_ms=80,
            post_pad_ms=100,
            merge_gap_ms=200,
            keep_short_pauses_ms=100,
            breath_detection=True,
        ),
    ),
]


@dataclass
class Settings:
    """Uygulama ayarları."""
    # UI
    theme: Theme = Theme.SYSTEM
    language: str = "en"
    recent_projects: list[str] = field(default_factory=list)
    max_recent_projects: int = 10

    # Paths
    default_export_dir: Optional[str] = None
    proxy_cache_dir: Optional[str] = None
    waveform_cache_dir: Optional[str] = None

    # Performance
    proxy_enabled: bool = True
    proxy_resolution: str = "720p"  # 480p, 720p, 1080p
    waveform_samples_per_pixel: int = 256
    max_waveform_cache_mb: int = 500

    # Transcript
    default_transcript_model: str = "faster-whisper-base"  # Changed from medium for speed
    transcript_language: str = "auto"
    gpu_acceleration: bool = True
    transcript_beam_size: int = 1  # 1=fastest, 5=more accurate

    # Gemini API (for transcription)
    gemini_api_key: str = ""
    gemini_enabled: bool = False
    gemini_model: str = "gemini-2.0-flash-exp"  # or gemini-1.5-pro, gemini-1.5-flash

    # Export
    default_export_format: str = "fcpxml"  # fcpxml, edl, xmeml
    fcpxml_version: str = "1.10"
    include_disabled_cuts: bool = False

    # Autosave
    autosave_enabled: bool = True
    autosave_interval_sec: int = 60

    # Presets
    custom_presets: list[Preset] = field(default_factory=list)
    last_used_preset: str = "Podcast"

    # Keyboard shortcuts (key -> action mapping)
    shortcuts: dict = field(default_factory=lambda: {
        "play_pause": "Space",
        "seek_back_1s": "Left",
        "seek_forward_1s": "Right",
        "seek_back_5s": "Shift+Left",
        "seek_forward_5s": "Shift+Right",
        "mark_in": "I",
        "mark_out": "O",
        "toggle_cut": "C",
        "delete_cut": "Delete",
        "undo": "Ctrl+Z",
        "redo": "Ctrl+Shift+Z",
        "save": "Ctrl+S",
        "export": "Ctrl+E",
        "zoom_in": "Ctrl+=",
        "zoom_out": "Ctrl+-",
        "zoom_fit": "Ctrl+0",
    })

    @classmethod
    def get_data_dir(cls) -> Path:
        """Uygulama veri dizini."""
        path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def get_cache_dir(cls) -> Path:
        """Uygulama cache dizini."""
        path = Path(user_cache_dir(APP_NAME, APP_AUTHOR))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def get_settings_path(cls) -> Path:
        """Settings dosyası path'i."""
        return cls.get_data_dir() / "settings.json"

    def get_all_presets(self) -> list[Preset]:
        """Tüm preset'leri döndür (default + custom)."""
        return DEFAULT_PRESETS + self.custom_presets

    def get_preset_by_name(self, name: str) -> Optional[Preset]:
        """İsme göre preset bul."""
        for preset in self.get_all_presets():
            if preset.name == name:
                return preset
        return None

    def add_recent_project(self, path: str) -> None:
        """Recent projects listesine ekle."""
        if path in self.recent_projects:
            self.recent_projects.remove(path)
        self.recent_projects.insert(0, path)
        self.recent_projects = self.recent_projects[:self.max_recent_projects]

    def save(self) -> None:
        """Ayarları kaydet."""
        data = {
            "theme": self.theme.value,
            "language": self.language,
            "recent_projects": self.recent_projects,
            "default_export_dir": self.default_export_dir,
            "proxy_cache_dir": self.proxy_cache_dir,
            "waveform_cache_dir": self.waveform_cache_dir,
            "proxy_enabled": self.proxy_enabled,
            "proxy_resolution": self.proxy_resolution,
            "waveform_samples_per_pixel": self.waveform_samples_per_pixel,
            "max_waveform_cache_mb": self.max_waveform_cache_mb,
            "default_transcript_model": self.default_transcript_model,
            "transcript_language": self.transcript_language,
            "gpu_acceleration": self.gpu_acceleration,
            "gemini_api_key": self.gemini_api_key,
            "gemini_enabled": self.gemini_enabled,
            "gemini_model": self.gemini_model,
            "default_export_format": self.default_export_format,
            "fcpxml_version": self.fcpxml_version,
            "include_disabled_cuts": self.include_disabled_cuts,
            "autosave_enabled": self.autosave_enabled,
            "autosave_interval_sec": self.autosave_interval_sec,
            "custom_presets": [p.to_dict() for p in self.custom_presets],
            "last_used_preset": self.last_used_preset,
            "shortcuts": self.shortcuts,
        }
        self.get_settings_path().write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> Settings:
        """Ayarları yükle veya varsayılanları döndür."""
        path = cls.get_settings_path()
        if not path.exists():
            return cls()

        try:
            data = json.loads(path.read_text())
            settings = cls(
                theme=Theme(data.get("theme", "system")),
                language=data.get("language", "en"),
                recent_projects=data.get("recent_projects", []),
                default_export_dir=data.get("default_export_dir"),
                proxy_cache_dir=data.get("proxy_cache_dir"),
                waveform_cache_dir=data.get("waveform_cache_dir"),
                proxy_enabled=data.get("proxy_enabled", True),
                proxy_resolution=data.get("proxy_resolution", "720p"),
                waveform_samples_per_pixel=data.get("waveform_samples_per_pixel", 256),
                max_waveform_cache_mb=data.get("max_waveform_cache_mb", 500),
                default_transcript_model=data.get("default_transcript_model", "faster-whisper-base"),
                transcript_language=data.get("transcript_language", "auto"),
                gpu_acceleration=data.get("gpu_acceleration", True),
                gemini_api_key=data.get("gemini_api_key", ""),
                gemini_enabled=data.get("gemini_enabled", False),
                gemini_model=data.get("gemini_model", "gemini-2.0-flash-exp"),
                default_export_format=data.get("default_export_format", "fcpxml"),
                fcpxml_version=data.get("fcpxml_version", "1.10"),
                include_disabled_cuts=data.get("include_disabled_cuts", False),
                autosave_enabled=data.get("autosave_enabled", True),
                autosave_interval_sec=data.get("autosave_interval_sec", 60),
                custom_presets=[
                    Preset.from_dict(p) for p in data.get("custom_presets", [])
                ],
                last_used_preset=data.get("last_used_preset", "Podcast"),
                shortcuts=data.get("shortcuts", {}),
            )
            return settings
        except (json.JSONDecodeError, KeyError):
            return cls()
