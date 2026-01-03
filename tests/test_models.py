"""Tests for core models."""

import pytest
from pathlib import Path
import tempfile
import json

from app.core.models import (
    MediaInfo,
    AudioSegment,
    Cut,
    CutType,
    TranscriptSegment,
    TranscriptWord,
    AnalysisConfig,
    Project,
)


class TestMediaInfo:
    """MediaInfo testleri."""

    def test_create_media_info(self):
        """Temel MediaInfo oluşturma."""
        info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=120.5,
            fps=29.97,
            width=1920,
            height=1080,
            sample_rate=48000,
        )

        assert info.duration == 120.5
        assert info.fps == 29.97
        assert info.has_video is True
        assert info.has_audio is True

    def test_time_frame_conversion(self):
        """Zaman <-> frame dönüşüm."""
        info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=60.0,
            fps=30.0,
            width=1920,
            height=1080,
        )

        # 1 saniye = 30 frame
        assert info.time_to_frame(1.0) == 30
        assert info.frame_to_time(30) == 1.0

    def test_total_frames(self):
        """Toplam frame hesaplama."""
        info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=10.0,
            fps=24.0,
            width=1920,
            height=1080,
        )

        assert info.total_frames == 240


class TestAudioSegment:
    """AudioSegment testleri."""

    def test_segment_duration(self):
        """Segment süresi hesaplama."""
        segment = AudioSegment(
            start=5.0,
            end=10.0,
            avg_db=-40.0,
            peak_db=-35.0,
            is_silence=True,
        )

        assert segment.duration == 5.0

    def test_segment_overlap(self):
        """Segment örtüşme kontrolü."""
        seg1 = AudioSegment(start=0, end=10, avg_db=-40, peak_db=-35, is_silence=True)
        seg2 = AudioSegment(start=5, end=15, avg_db=-40, peak_db=-35, is_silence=True)
        seg3 = AudioSegment(start=15, end=20, avg_db=-40, peak_db=-35, is_silence=True)

        assert seg1.overlaps(seg2) is True
        assert seg1.overlaps(seg3) is False

    def test_segment_merge(self):
        """Segment birleştirme."""
        seg1 = AudioSegment(start=0, end=10, avg_db=-40, peak_db=-35, is_silence=True)
        seg2 = AudioSegment(start=8, end=20, avg_db=-45, peak_db=-38, is_silence=True)

        merged = seg1.merge_with(seg2)

        assert merged.start == 0
        assert merged.end == 20
        assert merged.avg_db == -42.5  # Average of averages


class TestCut:
    """Cut testleri."""

    def test_cut_creation(self):
        """Cut oluşturma."""
        cut = Cut(
            start=5.0,
            end=10.0,
            cut_type=CutType.SILENCE,
            enabled=True,
        )

        assert cut.duration == 5.0
        assert cut.is_removable is True

    def test_cut_disabled(self):
        """Disabled cut."""
        cut = Cut(
            start=5.0,
            end=10.0,
            cut_type=CutType.SILENCE,
            enabled=False,
        )

        assert cut.is_removable is False

    def test_cut_serialization(self):
        """Cut serialization."""
        cut = Cut(
            start=5.0,
            end=10.0,
            cut_type=CutType.SILENCE,
            enabled=True,
            label="Test cut",
        )

        data = cut.to_dict()
        restored = Cut.from_dict(data)

        assert restored.start == cut.start
        assert restored.end == cut.end
        assert restored.cut_type == cut.cut_type
        assert restored.label == cut.label


class TestTranscriptSegment:
    """TranscriptSegment testleri."""

    def test_segment_with_words(self):
        """Word-level timestamp."""
        words = [
            TranscriptWord(text="Hello", start=0.0, end=0.5, confidence=0.95),
            TranscriptWord(text="world", start=0.6, end=1.0, confidence=0.92),
        ]

        segment = TranscriptSegment(
            text="Hello world",
            start=0.0,
            end=1.0,
            language="en",
            words=words,
        )

        assert segment.word_count == 2
        assert segment.duration == 1.0

    def test_segment_serialization(self):
        """Segment serialization."""
        segment = TranscriptSegment(
            text="Test text",
            start=5.0,
            end=8.0,
            language="tr",
        )

        data = segment.to_dict()
        restored = TranscriptSegment.from_dict(data)

        assert restored.text == segment.text
        assert restored.start == segment.start
        assert restored.language == segment.language


class TestAnalysisConfig:
    """AnalysisConfig testleri."""

    def test_default_config(self):
        """Varsayılan konfigürasyon."""
        config = AnalysisConfig()

        assert config.silence_threshold_db == -30.0
        assert config.silence_min_duration_ms == 500
        assert config.pre_pad_ms == 100
        assert config.post_pad_ms == 150

    def test_config_serialization(self):
        """Config serialization."""
        config = AnalysisConfig(
            silence_threshold_db=-40.0,
            use_vad=True,
        )

        data = config.to_dict()
        restored = AnalysisConfig.from_dict(data)

        assert restored.silence_threshold_db == -40.0
        assert restored.use_vad is True


class TestProject:
    """Project testleri."""

    def test_project_creation(self):
        """Proje oluşturma."""
        project = Project(name="Test Project")

        assert project.name == "Test Project"
        assert len(project.cuts) == 0

    def test_keep_segments_no_cuts(self):
        """Kesim yokken tüm içerik korunur."""
        project = Project()
        project.media_info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=60.0,
            fps=30.0,
            width=1920,
            height=1080,
        )

        segments = project.get_keep_segments()

        assert len(segments) == 1
        assert segments[0] == (0.0, 60.0)

    def test_keep_segments_with_cuts(self):
        """Kesimlerle korunan segmentler."""
        project = Project()
        project.media_info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=60.0,
            fps=30.0,
            width=1920,
            height=1080,
        )

        # 10-20 ve 40-50 arası kesilecek
        project.cuts = [
            Cut(start=10.0, end=20.0, cut_type=CutType.SILENCE, enabled=True),
            Cut(start=40.0, end=50.0, cut_type=CutType.SILENCE, enabled=True),
        ]

        segments = project.get_keep_segments()

        assert len(segments) == 3
        assert segments[0] == (0.0, 10.0)
        assert segments[1] == (20.0, 40.0)
        assert segments[2] == (50.0, 60.0)

    def test_total_cut_duration(self):
        """Toplam kesilecek süre."""
        project = Project()
        project.media_info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=60.0,
            fps=30.0,
            width=1920,
            height=1080,
        )

        project.cuts = [
            Cut(start=10.0, end=20.0, cut_type=CutType.SILENCE, enabled=True),
            Cut(start=40.0, end=50.0, cut_type=CutType.SILENCE, enabled=True),
            Cut(start=55.0, end=58.0, cut_type=CutType.SILENCE, enabled=False),  # Disabled
        ]

        assert project.get_total_cut_duration() == 20.0  # 10 + 10, disabled dahil değil
        assert project.get_final_duration() == 40.0

    def test_project_save_load(self):
        """Proje kaydet/yükle."""
        project = Project(name="Test Save")
        project.config = AnalysisConfig(silence_threshold_db=-38.0)
        project.cuts = [
            Cut(start=5.0, end=10.0, cut_type=CutType.SILENCE, enabled=True),
        ]

        with tempfile.NamedTemporaryFile(suffix=".autocut", delete=False) as f:
            path = Path(f.name)

        try:
            project.save(path)
            loaded = Project.load(path)

            assert loaded.name == "Test Save"
            assert loaded.config.silence_threshold_db == -38.0
            assert len(loaded.cuts) == 1
            assert loaded.cuts[0].start == 5.0
        finally:
            path.unlink()
