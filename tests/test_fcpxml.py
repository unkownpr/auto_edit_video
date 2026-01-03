"""Tests for FCPXML export."""

import pytest
from pathlib import Path
import tempfile
from lxml import etree

from app.core.models import MediaInfo, Project, Cut, CutType
from app.export.fcpxml import (
    FCPXMLBuilder,
    export_fcpxml,
    time_to_rational,
    duration_to_rational,
    path_to_url,
    sanitize_name,
)


class TestTimeConversion:
    """Zaman dönüşüm fonksiyonları testleri."""

    def test_time_to_rational_30fps(self):
        """30fps için rational format."""
        # 1 saniye @ 30fps
        result = time_to_rational(1.0, 30.0)
        assert result == "30/30s" or "1/1s" in result or "/30s" in result

    def test_time_to_rational_29_97fps(self):
        """29.97fps için rational format."""
        # 29.97fps drop-frame
        result = time_to_rational(1.0, 29.97)
        assert "30000s" in result  # 1001/30000 bazlı olmalı

    def test_time_to_rational_24fps(self):
        """24fps için rational format."""
        result = time_to_rational(1.0, 24.0)
        assert "/24s" in result

    def test_duration_to_rational(self):
        """Duration için rational format."""
        result = duration_to_rational(10.0, 30.0)
        # 10 saniye = 300 frame @ 30fps
        assert "s" in result


class TestPathConversion:
    """Path dönüşüm fonksiyonları testleri."""

    def test_path_to_url_simple(self):
        """Basit path dönüşümü."""
        path = Path("/Users/test/video.mp4")
        url = path_to_url(path)

        assert url.startswith("file://")
        assert "video.mp4" in url

    def test_path_to_url_with_spaces(self):
        """Boşluklu path dönüşümü."""
        path = Path("/Users/test user/my video.mp4")
        url = path_to_url(path)

        assert "file://" in url
        assert "%20" in url or "test%20user" in url

    def test_sanitize_name(self):
        """İsim temizleme."""
        assert sanitize_name("Normal Name") == "Normal Name"
        assert sanitize_name("Name<with>special&chars") == "Namewithspecialchars"
        assert len(sanitize_name("A" * 100)) == 50  # Max 50 karakter


class TestFCPXMLBuilder:
    """FCPXMLBuilder testleri."""

    @pytest.fixture
    def sample_project(self) -> Project:
        """Örnek proje."""
        project = Project(name="Test Export")
        project.media_info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=120.0,  # 2 dakika
            fps=30.0,
            width=1920,
            height=1080,
            video_codec="h264",
            audio_codec="aac",
            sample_rate=48000,
            channels=2,
        )
        return project

    def test_build_no_cuts(self, sample_project):
        """Kesim olmadan export."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
            output_path = Path(f.name)

        try:
            builder = FCPXMLBuilder(
                project=sample_project,
                output_path=output_path,
            )
            root = builder.build()

            # FCPXML yapısını kontrol et
            assert root.tag == "fcpxml"
            assert root.get("version") == "1.10"

            # Resources
            resources = root.find("resources")
            assert resources is not None

            # Format
            format_elem = resources.find("format")
            assert format_elem is not None
            assert format_elem.get("width") == "1920"
            assert format_elem.get("height") == "1080"

            # Asset
            asset = resources.find("asset")
            assert asset is not None
            # src is now in media-rep child element
            media_rep = asset.find("media-rep")
            assert media_rep is not None
            assert "video.mp4" in media_rep.get("src")

            # Library -> Event -> Project -> Sequence -> Spine
            library = root.find("library")
            assert library is not None

            event = library.find("event")
            assert event is not None

            project_elem = event.find("project")
            assert project_elem is not None

            sequence = project_elem.find("sequence")
            assert sequence is not None

            spine = sequence.find("spine")
            assert spine is not None

            # Tek clip olmalı (tüm video)
            clips = spine.findall("asset-clip")
            assert len(clips) == 1
        finally:
            output_path.unlink(missing_ok=True)

    def test_build_with_cuts(self, sample_project):
        """Kesimlerle export."""
        # 10-20 ve 60-80 saniye arası kesilecek
        sample_project.cuts = [
            Cut(start=10.0, end=20.0, cut_type=CutType.SILENCE, enabled=True),
            Cut(start=60.0, end=80.0, cut_type=CutType.SILENCE, enabled=True),
        ]

        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
            output_path = Path(f.name)

        try:
            builder = FCPXMLBuilder(
                project=sample_project,
                output_path=output_path,
            )
            root = builder.build()

            # Spine'daki clip'leri kontrol et
            spine = root.find(".//spine")
            clips = spine.findall("asset-clip")

            # 3 segment olmalı: 0-10, 20-60, 80-120
            assert len(clips) == 3
        finally:
            output_path.unlink(missing_ok=True)

    def test_build_disabled_cuts_ignored(self, sample_project):
        """Devre dışı kesimler yok sayılır."""
        sample_project.cuts = [
            Cut(start=10.0, end=20.0, cut_type=CutType.SILENCE, enabled=True),
            Cut(start=30.0, end=40.0, cut_type=CutType.SILENCE, enabled=False),  # Disabled
        ]

        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
            output_path = Path(f.name)

        try:
            builder = FCPXMLBuilder(
                project=sample_project,
                output_path=output_path,
            )
            root = builder.build()

            spine = root.find(".//spine")
            clips = spine.findall("asset-clip")

            # 2 segment olmalı (disabled cut yok sayıldı)
            # 0-10 ve 20-120 -> ama disabled olduğu için 30-40 dahil
            # Yani: 0-10, 20-120 = 2 clip
            assert len(clips) == 2
        finally:
            output_path.unlink(missing_ok=True)

    def test_save_valid_xml(self, sample_project):
        """Geçerli XML dosyası oluşturma."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
            output_path = Path(f.name)

        try:
            builder = FCPXMLBuilder(
                project=sample_project,
                output_path=output_path,
            )
            builder.save()

            # Dosya oluşturuldu mu?
            assert output_path.exists()

            # Geçerli XML mi?
            tree = etree.parse(str(output_path))
            root = tree.getroot()
            assert root.tag == "fcpxml"
        finally:
            output_path.unlink(missing_ok=True)

    def test_to_string(self, sample_project):
        """XML string çıktısı."""
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
            output_path = Path(f.name)

        builder = FCPXMLBuilder(
            project=sample_project,
            output_path=output_path,
        )
        xml_string = builder.to_string()

        assert '<?xml version' in xml_string
        assert '<fcpxml' in xml_string
        assert '</fcpxml>' in xml_string


class TestExportFunction:
    """export_fcpxml convenience function testleri."""

    def test_export_creates_file(self):
        """Dosya oluşturma."""
        project = Project(name="Export Test")
        project.media_info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=60.0,
            fps=30.0,
            width=1920,
            height=1080,
        )

        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
            output_path = Path(f.name)

        try:
            result = export_fcpxml(project, output_path)

            assert result == output_path
            assert output_path.exists()
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_with_version(self):
        """Farklı FCPXML versiyonu."""
        project = Project(name="Version Test")
        project.media_info = MediaInfo(
            file_path=Path("/test/video.mp4"),
            duration=60.0,
            fps=30.0,
            width=1920,
            height=1080,
        )

        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as f:
            output_path = Path(f.name)

        try:
            export_fcpxml(project, output_path, version="1.9")

            tree = etree.parse(str(output_path))
            root = tree.getroot()
            assert root.get("version") == "1.9"
        finally:
            output_path.unlink(missing_ok=True)
