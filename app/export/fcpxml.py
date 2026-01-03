"""
FCPXML (Final Cut Pro XML) export module.

FCPXML 1.10 format - Final Cut Pro 10.6+ uyumlu.

Yapı:
- fcpxml root
  - resources: asset tanımları (video/audio dosyaları)
  - library
    - event
      - project
        - sequence
          - spine: ana timeline
            - asset-clip: her korunan segment için

Referans: https://developer.apple.com/documentation/professional_video_applications/fcpxml_reference
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote
import logging

from lxml import etree

from app.core.models import MediaInfo, Project, Cut

logger = logging.getLogger(__name__)


def time_to_rational(seconds: float, fps: float = 30.0) -> str:
    """
    Saniyeyi FCPXML rational time formatına dönüştür.

    FCPXML time format: "numerator/denominator s"
    Örnek: "1001/30000s" = 1/29.97 saniye

    Args:
        seconds: Zaman (saniye)
        fps: Frame rate

    Returns:
        FCPXML time string
    """
    # Common frame rates için denominator
    fps_denominators = {
        23.976: (1001, 24000),
        24.0: (1, 24),
        25.0: (1, 25),
        29.97: (1001, 30000),
        30.0: (1, 30),
        50.0: (1, 50),
        59.94: (1001, 60000),
        60.0: (1, 60),
    }

    # En yakın fps'i bul
    closest_fps = min(fps_denominators.keys(), key=lambda x: abs(x - fps))
    num_per_frame, den = fps_denominators[closest_fps]

    # Frame sayısı
    frames = round(seconds * den / num_per_frame)

    # Rational format
    numerator = frames * num_per_frame

    return f"{numerator}/{den}s"


def duration_to_rational(seconds: float, fps: float = 30.0) -> str:
    """Duration için rational format."""
    return time_to_rational(seconds, fps)


def path_to_url(path: Path) -> str:
    """Path'i file:// URL'e dönüştür."""
    abs_path = path.resolve()
    # URL encode (boşluklar vs.)
    encoded = quote(str(abs_path), safe="/:@")
    return f"file://{encoded}"


def sanitize_name(name: str) -> str:
    """FCPXML için güvenli isim oluştur."""
    # Özel karakterleri kaldır
    name = re.sub(r'[<>&"\']', '', name)
    return name[:50]  # Max 50 karakter


@dataclass
class FCPXMLBuilder:
    """
    FCPXML document builder.

    Usage:
        builder = FCPXMLBuilder(project, output_path)
        builder.build()
        builder.save()
    """
    project: Project
    output_path: Path
    version: str = "1.10"

    # Internal state
    _root: Optional[etree._Element] = None
    _resources: Optional[etree._Element] = None
    _asset_id: str = ""
    _format_id: str = ""

    def build(self) -> etree._Element:
        """FCPXML document oluştur."""
        if not self.project.media_info:
            raise ValueError("Project has no media info")

        media = self.project.media_info
        keep_segments = self.project.get_keep_segments()

        logger.info(f"Building FCPXML with {len(keep_segments)} segments")

        # Root element
        self._root = etree.Element("fcpxml", version=self.version)

        # Resources
        self._resources = etree.SubElement(self._root, "resources")
        self._build_format(media)
        self._build_asset(media)

        # Library -> Event -> Project -> Sequence
        library = etree.SubElement(self._root, "library")
        event = etree.SubElement(
            library, "event",
            name=f"AutoCut Export {datetime.now().strftime('%Y-%m-%d')}"
        )

        project_elem = etree.SubElement(
            event, "project",
            name=sanitize_name(self.project.name or media.file_path.stem)
        )

        # Sequence
        sequence = self._build_sequence(media, keep_segments)
        project_elem.append(sequence)

        return self._root

    def _build_format(self, media: MediaInfo) -> None:
        """Video format resource."""
        self._format_id = "r1"

        # Frame duration
        fps = media.fps or 30.0
        frame_duration = time_to_rational(1.0 / fps, fps)

        # Format element - sadece video format bilgileri
        # audioSampleRate ve audioChannels DTD'de yok
        etree.SubElement(
            self._resources, "format",
            id=self._format_id,
            name=f"FFVideoFormat{media.height or 1080}p{int(fps)}",
            frameDuration=frame_duration,
            width=str(media.width) if media.width else "1920",
            height=str(media.height) if media.height else "1080",
        )

    def _build_asset(self, media: MediaInfo) -> None:
        """Media asset resource."""
        self._asset_id = "r2"

        fps = media.fps or 30.0

        # Asset element - src attribute yerine media-rep child kullanılmalı
        asset = etree.SubElement(
            self._resources, "asset",
            id=self._asset_id,
            name=sanitize_name(media.file_path.stem),
            start="0s",
            duration=duration_to_rational(media.duration, fps),
            hasVideo="1" if media.has_video else "0",
            hasAudio="1" if media.has_audio else "0",
            format=self._format_id,
        )

        # media-rep child element - source file location
        etree.SubElement(
            asset, "media-rep",
            kind="original-media",
            src=path_to_url(media.file_path),
        )

    def _build_sequence(
        self,
        media: MediaInfo,
        keep_segments: list[tuple[float, float]],
    ) -> etree._Element:
        """Timeline sequence oluştur."""
        fps = media.fps or 30.0

        # Toplam duration (korunan segmentlerin toplamı)
        total_duration = sum(end - start for start, end in keep_segments)

        sequence = etree.Element(
            "sequence",
            duration=duration_to_rational(total_duration, fps),
            format=self._format_id,
            tcStart="0s",
            tcFormat="NDF",  # Non-drop frame
        )

        # Spine (ana timeline)
        spine = etree.SubElement(sequence, "spine")

        # Her korunan segment için asset-clip
        timeline_offset = 0.0

        for i, (seg_start, seg_end) in enumerate(keep_segments):
            seg_duration = seg_end - seg_start

            clip = etree.SubElement(
                spine, "asset-clip",
                name=f"Clip {i + 1}",
                ref=self._asset_id,
                offset=time_to_rational(timeline_offset, fps),
                duration=duration_to_rational(seg_duration, fps),
                start=time_to_rational(seg_start, fps),
                tcFormat="NDF",
            )

            # Audio/video roles
            if media.has_video:
                clip.set("videoRole", "video")
            if media.has_audio:
                clip.set("audioRole", "dialogue")

            timeline_offset += seg_duration

        return sequence

    def save(self) -> Path:
        """FCPXML dosyasını kaydet."""
        if self._root is None:
            self.build()

        # XML string oluştur - DOCTYPE dahil
        xml_string = etree.tostring(
            self._root,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
            doctype="<!DOCTYPE fcpxml>",
        )

        # Dosyaya yaz
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(xml_string)

        logger.info(f"FCPXML saved to {self.output_path}")
        return self.output_path

    def to_string(self) -> str:
        """FCPXML'i string olarak döndür."""
        if self._root is None:
            self.build()

        xml_content = etree.tostring(
            self._root,
            pretty_print=True,
            encoding="unicode",
        )
        return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + xml_content


def export_fcpxml(
    project: Project,
    output_path: Path,
    version: str = "1.10",
) -> Path:
    """
    Convenience function for FCPXML export.

    Args:
        project: AutoCut project
        output_path: Çıktı dosya yolu
        version: FCPXML version

    Returns:
        Kaydedilen dosya path'i
    """
    builder = FCPXMLBuilder(
        project=project,
        output_path=output_path,
        version=version,
    )
    return builder.save()


# ============================================================================
# Örnek FCPXML Şablonu (referans için)
# ============================================================================
EXAMPLE_FCPXML = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
    <resources>
        <format id="r1" name="FFVideoFormat1080p30"
                frameDuration="1001/30000s"
                width="1920" height="1080"/>
        <asset id="r2" name="my_video"
               start="0s" duration="3603603/30000s"
               hasVideo="1" hasAudio="1" format="r1">
            <media-rep kind="original-media" src="file:///path/to/video.mp4"/>
        </asset>
    </resources>
    <library>
        <event name="AutoCut Export">
            <project name="Edited Video">
                <sequence duration="1801801/30000s" format="r1" tcStart="0s" tcFormat="NDF">
                    <spine>
                        <!-- İlk korunan segment: 0-10 saniye -->
                        <asset-clip name="Clip 1" ref="r2"
                                   offset="0s"
                                   duration="300300/30000s"
                                   start="0s"
                                   tcFormat="NDF"/>
                        <!-- İkinci korunan segment: 15-25 saniye (5 sn silence atlandı) -->
                        <asset-clip name="Clip 2" ref="r2"
                                   offset="300300/30000s"
                                   duration="300300/30000s"
                                   start="450450/30000s"
                                   tcFormat="NDF"/>
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>
'''
