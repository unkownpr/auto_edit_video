"""
Core data models for AutoCut.

Tüm zaman değerleri saniye (float) cinsinden tutulur.
Frame-accurate işlemler için sample_rate ile çarpılır.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class CutType(Enum):
    """Cut segment türleri."""
    SILENCE = "silence"      # Sessizlik - kesilecek
    BREATH = "breath"        # Nefes - opsiyonel koru/sil
    KEEP = "keep"           # Korunacak (konuşma)
    MANUAL = "manual"       # Kullanıcı tanımlı


@dataclass
class MediaInfo:
    """Video/audio dosyası metadata bilgileri."""
    file_path: Path
    duration: float              # saniye
    fps: float                   # video frame rate
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    sample_rate: int = 48000     # audio sample rate
    channels: int = 2
    bit_depth: int = 16
    file_size: int = 0           # bytes

    # Proxy bilgileri
    proxy_path: Optional[Path] = None
    audio_path: Optional[Path] = None   # extracted wav

    @property
    def has_video(self) -> bool:
        return self.width > 0 and self.height > 0

    @property
    def has_audio(self) -> bool:
        return self.sample_rate > 0

    @property
    def total_frames(self) -> int:
        """Toplam video frame sayısı."""
        return int(self.duration * self.fps) if self.fps > 0 else 0

    @property
    def total_samples(self) -> int:
        """Toplam audio sample sayısı."""
        return int(self.duration * self.sample_rate)

    def time_to_frame(self, time_sec: float) -> int:
        """Zaman -> frame numarası."""
        return int(time_sec * self.fps)

    def frame_to_time(self, frame: int) -> float:
        """Frame -> zaman (saniye)."""
        return frame / self.fps if self.fps > 0 else 0.0

    def time_to_samples(self, time_sec: float) -> int:
        """Zaman -> sample sayısı."""
        return int(time_sec * self.sample_rate)

    def samples_to_time(self, samples: int) -> float:
        """Sample -> zaman (saniye)."""
        return samples / self.sample_rate if self.sample_rate > 0 else 0.0


@dataclass
class AudioSegment:
    """
    Analiz edilmiş audio segmenti.
    Silence detector çıktısı.
    """
    start: float          # saniye
    end: float            # saniye
    avg_db: float         # ortalama dBFS
    peak_db: float        # peak dBFS
    is_silence: bool      # sessizlik mi?

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlaps(self, other: AudioSegment) -> bool:
        """İki segment örtüşüyor mu?"""
        return self.start < other.end and self.end > other.start

    def merge_with(self, other: AudioSegment) -> AudioSegment:
        """İki segmenti birleştir."""
        return AudioSegment(
            start=min(self.start, other.start),
            end=max(self.end, other.end),
            avg_db=(self.avg_db + other.avg_db) / 2,
            peak_db=max(self.peak_db, other.peak_db),
            is_silence=self.is_silence and other.is_silence,
        )


@dataclass
class Cut:
    """
    Timeline üzerinde bir kesim noktası.
    Kullanıcı tarafından düzenlenebilir.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start: float = 0.0           # saniye
    end: float = 0.0             # saniye
    cut_type: CutType = CutType.SILENCE
    enabled: bool = True         # False = bu kesim uygulanmaz
    label: str = ""              # opsiyonel etiket

    # Kaynak analiz verisi
    source_avg_db: float = -60.0
    source_peak_db: float = -60.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def is_removable(self) -> bool:
        """Bu segment kesilecek mi?"""
        return self.enabled and self.cut_type in (CutType.SILENCE, CutType.BREATH)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "cut_type": self.cut_type.value,
            "enabled": self.enabled,
            "label": self.label,
            "source_avg_db": self.source_avg_db,
            "source_peak_db": self.source_peak_db,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Cut:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            start=data["start"],
            end=data["end"],
            cut_type=CutType(data.get("cut_type", "silence")),
            enabled=data.get("enabled", True),
            label=data.get("label", ""),
            source_avg_db=data.get("source_avg_db", -60.0),
            source_peak_db=data.get("source_peak_db", -60.0),
        )


@dataclass
class TranscriptWord:
    """Kelime seviyesinde transcript verisi."""
    text: str
    start: float        # saniye
    end: float          # saniye
    confidence: float   # 0.0 - 1.0

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class TranscriptSegment:
    """Segment seviyesinde transcript verisi (cümle/paragraf)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str = ""
    start: float = 0.0
    end: float = 0.0
    language: str = "en"
    words: list[TranscriptWord] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def word_count(self) -> int:
        return len(self.words) if self.words else len(self.text.split())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "language": self.language,
            "words": [
                {"text": w.text, "start": w.start, "end": w.end, "confidence": w.confidence}
                for w in self.words
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> TranscriptSegment:
        words = [
            TranscriptWord(
                text=w["text"],
                start=w["start"],
                end=w["end"],
                confidence=w.get("confidence", 1.0),
            )
            for w in data.get("words", [])
        ]
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            text=data["text"],
            start=data["start"],
            end=data["end"],
            language=data.get("language", "en"),
            words=words,
        )


@dataclass
class AnalysisConfig:
    """Sessizlik analizi konfigürasyonu."""
    # Temel eşikler
    silence_threshold_db: float = -35.0     # dBFS altı = sessizlik
    hysteresis_db: float = 3.0              # açma/kapama histerezisi

    # Süre limitleri (milisaniye)
    silence_min_duration_ms: int = 250      # min sessizlik süresi
    merge_gap_ms: int = 120                 # bu kadar yakın sessizlikleri birleştir
    keep_short_pauses_ms: int = 0           # bu süreden kısa duraklamaları koru (0=devre dışı)

    # Padding
    pre_pad_ms: int = 80                    # kesimden önce padding
    post_pad_ms: int = 120                  # kesimden sonra padding

    # Analiz parametreleri
    frame_ms: int = 10                      # analiz pencere boyutu

    # Nefes modu
    breath_detection: bool = False
    breath_threshold_db: float = -45.0
    breath_min_duration_ms: int = 100
    breath_max_duration_ms: int = 400

    # VAD modu
    use_vad: bool = False
    vad_aggressiveness: int = 2             # 0-3, 3 en agresif

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AnalysisConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Project:
    """
    Proje dosyası - tüm durumu saklar.
    JSON olarak serialize edilir.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Project"
    created_at: str = ""
    modified_at: str = ""

    # Medya
    media_info: Optional[MediaInfo] = None

    # Analiz
    config: AnalysisConfig = field(default_factory=AnalysisConfig)
    cuts: list[Cut] = field(default_factory=list)

    # Transcript
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)
    transcript_language: str = "auto"
    transcript_model: str = "faster-whisper-medium"

    # Cache paths
    waveform_cache_path: Optional[Path] = None

    def get_keep_segments(self) -> list[tuple[float, float]]:
        """
        Kesilmeyecek (korunacak) zaman aralıklarını döndür.
        FCPXML export için kullanılır.
        """
        if not self.media_info:
            return []

        duration = self.media_info.duration

        # Aktif kesimleri topla ve sırala
        active_cuts = sorted(
            [c for c in self.cuts if c.is_removable],
            key=lambda x: x.start
        )

        if not active_cuts:
            return [(0.0, duration)]

        # Korunacak segmentleri hesapla
        keep_segments = []
        current_pos = 0.0

        for cut in active_cuts:
            if cut.start > current_pos:
                keep_segments.append((current_pos, cut.start))
            current_pos = max(current_pos, cut.end)

        # Son segment
        if current_pos < duration:
            keep_segments.append((current_pos, duration))

        return keep_segments

    def get_total_cut_duration(self) -> float:
        """Toplam kesilecek süre."""
        return sum(c.duration for c in self.cuts if c.is_removable)

    def get_final_duration(self) -> float:
        """Kesimlerden sonra kalan süre."""
        if not self.media_info:
            return 0.0
        return self.media_info.duration - self.get_total_cut_duration()

    def save(self, path: Path) -> None:
        """Projeyi JSON olarak kaydet."""
        data = {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "media_path": str(self.media_info.file_path) if self.media_info else None,
            "config": self.config.to_dict(),
            "cuts": [c.to_dict() for c in self.cuts],
            "transcript_segments": [s.to_dict() for s in self.transcript_segments],
            "transcript_language": self.transcript_language,
            "transcript_model": self.transcript_model,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> Project:
        """Projeyi JSON'dan yükle."""
        data = json.loads(path.read_text())

        project = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", "Untitled"),
            created_at=data.get("created_at", ""),
            modified_at=data.get("modified_at", ""),
            config=AnalysisConfig.from_dict(data.get("config", {})),
            cuts=[Cut.from_dict(c) for c in data.get("cuts", [])],
            transcript_segments=[
                TranscriptSegment.from_dict(s)
                for s in data.get("transcript_segments", [])
            ],
            transcript_language=data.get("transcript_language", "auto"),
            transcript_model=data.get("transcript_model", "faster-whisper-medium"),
        )

        return project
