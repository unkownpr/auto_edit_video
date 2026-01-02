"""
Adobe Premiere Pro XML (XMEML) export module.

Premiere Pro ve After Effects için FCP 7 XML formatı.
Premiere Pro CC bu formatı "Final Cut Pro XML" olarak import eder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote
import logging
import uuid

from lxml import etree

from app.core.models import MediaInfo, Project

logger = logging.getLogger(__name__)


def seconds_to_ticks(seconds: float, timebase: int = 30) -> int:
    """Saniyeyi tick'e dönüştür."""
    return int(seconds * timebase)


def path_to_url(path: Path) -> str:
    """Path'i file:// URL'e dönüştür."""
    abs_path = path.resolve()
    encoded = quote(str(abs_path), safe="/:@")
    return f"file://localhost{encoded}"


@dataclass
class PremiereXMLBuilder:
    """
    Adobe Premiere Pro XML (XMEML/FCP7 XML) builder.

    Premiere Pro CC, After Effects ve Final Cut Pro 7 ile uyumlu.
    """
    project: Project
    output_path: Path

    def build(self) -> etree._Element:
        """XML document oluştur."""
        if not self.project.media_info:
            raise ValueError("Project has no media info")

        media = self.project.media_info
        keep_segments = self.project.get_keep_segments()
        fps = media.fps or 30.0
        timebase = round(fps)

        # Root element
        root = etree.Element("xmeml", version="5")

        # Project
        project = etree.SubElement(root, "project")
        etree.SubElement(project, "name").text = self.project.name or media.file_path.stem

        # Children (bins)
        children = etree.SubElement(project, "children")

        # Bin for media
        media_bin = etree.SubElement(children, "bin")
        etree.SubElement(media_bin, "name").text = "Media"
        media_children = etree.SubElement(media_bin, "children")

        # Master clip
        master_clip = self._create_master_clip(media, timebase)
        media_children.append(master_clip)

        # Sequence
        sequence = self._create_sequence(media, keep_segments, timebase)
        children.append(sequence)

        return root

    def _create_master_clip(self, media: MediaInfo, timebase: int) -> etree._Element:
        """Master clip oluştur."""
        clip = etree.Element("clip", id=f"masterclip-1")
        etree.SubElement(clip, "name").text = media.file_path.stem

        # Duration
        duration = int(media.duration * timebase)
        etree.SubElement(clip, "duration").text = str(duration)

        # Rate
        rate = etree.SubElement(clip, "rate")
        etree.SubElement(rate, "timebase").text = str(timebase)
        etree.SubElement(rate, "ntsc").text = "FALSE"

        # Media
        media_elem = etree.SubElement(clip, "media")

        # Video
        if media.has_video:
            video = etree.SubElement(media_elem, "video")
            track = etree.SubElement(video, "track")
            clip_item = etree.SubElement(track, "clipitem", id="clipitem-1")
            etree.SubElement(clip_item, "name").text = media.file_path.stem
            etree.SubElement(clip_item, "duration").text = str(duration)

            rate2 = etree.SubElement(clip_item, "rate")
            etree.SubElement(rate2, "timebase").text = str(timebase)
            etree.SubElement(rate2, "ntsc").text = "FALSE"

            # File reference
            file_elem = etree.SubElement(clip_item, "file", id="file-1")
            etree.SubElement(file_elem, "name").text = media.file_path.name
            etree.SubElement(file_elem, "pathurl").text = path_to_url(media.file_path)
            etree.SubElement(file_elem, "duration").text = str(duration)

            file_rate = etree.SubElement(file_elem, "rate")
            etree.SubElement(file_rate, "timebase").text = str(timebase)
            etree.SubElement(file_rate, "ntsc").text = "FALSE"

        # Audio
        if media.has_audio:
            audio = etree.SubElement(media_elem, "audio")
            track = etree.SubElement(audio, "track")
            clip_item = etree.SubElement(track, "clipitem", id="clipitem-2")
            etree.SubElement(clip_item, "name").text = media.file_path.stem
            etree.SubElement(clip_item, "duration").text = str(duration)

        return clip

    def _create_sequence(
        self,
        media: MediaInfo,
        keep_segments: list[tuple[float, float]],
        timebase: int,
    ) -> etree._Element:
        """Sequence oluştur."""
        sequence = etree.Element("sequence", id="sequence-1")
        etree.SubElement(sequence, "name").text = f"{self.project.name or media.file_path.stem} - Edited"
        etree.SubElement(sequence, "uuid").text = str(uuid.uuid4())

        # Toplam süre
        total_duration = sum(end - start for start, end in keep_segments)
        etree.SubElement(sequence, "duration").text = str(int(total_duration * timebase))

        # Rate
        rate = etree.SubElement(sequence, "rate")
        etree.SubElement(rate, "timebase").text = str(timebase)
        etree.SubElement(rate, "ntsc").text = "FALSE"

        # Timecode
        tc = etree.SubElement(sequence, "timecode")
        etree.SubElement(tc, "string").text = "00:00:00:00"
        etree.SubElement(tc, "frame").text = "0"
        tc_rate = etree.SubElement(tc, "rate")
        etree.SubElement(tc_rate, "timebase").text = str(timebase)
        etree.SubElement(tc_rate, "ntsc").text = "FALSE"

        # Media
        seq_media = etree.SubElement(sequence, "media")

        # Video track
        if media.has_video:
            video = etree.SubElement(seq_media, "video")

            # Format
            fmt = etree.SubElement(video, "format")
            sample_char = etree.SubElement(fmt, "samplecharacteristics")
            etree.SubElement(sample_char, "width").text = str(media.width)
            etree.SubElement(sample_char, "height").text = str(media.height)

            # Track
            track = etree.SubElement(video, "track")

            timeline_offset = 0
            for i, (seg_start, seg_end) in enumerate(keep_segments):
                seg_duration = seg_end - seg_start

                clip_item = etree.SubElement(track, "clipitem", id=f"v-clipitem-{i+1}")
                etree.SubElement(clip_item, "name").text = f"Clip {i+1}"

                etree.SubElement(clip_item, "duration").text = str(int(seg_duration * timebase))
                etree.SubElement(clip_item, "start").text = str(int(timeline_offset * timebase))
                etree.SubElement(clip_item, "end").text = str(int((timeline_offset + seg_duration) * timebase))

                # In/out points (source)
                etree.SubElement(clip_item, "in").text = str(int(seg_start * timebase))
                etree.SubElement(clip_item, "out").text = str(int(seg_end * timebase))

                # File reference
                file_ref = etree.SubElement(clip_item, "file", id="file-1")

                timeline_offset += seg_duration

        # Audio track
        if media.has_audio:
            audio = etree.SubElement(seq_media, "audio")

            # Format
            fmt = etree.SubElement(audio, "format")
            sample_char = etree.SubElement(fmt, "samplecharacteristics")
            etree.SubElement(sample_char, "samplerate").text = str(media.sample_rate)
            etree.SubElement(sample_char, "depth").text = str(media.bit_depth)

            # Track
            track = etree.SubElement(audio, "track")

            timeline_offset = 0
            for i, (seg_start, seg_end) in enumerate(keep_segments):
                seg_duration = seg_end - seg_start

                clip_item = etree.SubElement(track, "clipitem", id=f"a-clipitem-{i+1}")
                etree.SubElement(clip_item, "name").text = f"Clip {i+1}"

                etree.SubElement(clip_item, "duration").text = str(int(seg_duration * timebase))
                etree.SubElement(clip_item, "start").text = str(int(timeline_offset * timebase))
                etree.SubElement(clip_item, "end").text = str(int((timeline_offset + seg_duration) * timebase))

                etree.SubElement(clip_item, "in").text = str(int(seg_start * timebase))
                etree.SubElement(clip_item, "out").text = str(int(seg_end * timebase))

                file_ref = etree.SubElement(clip_item, "file", id="file-1")

                timeline_offset += seg_duration

        return sequence

    def save(self) -> Path:
        """XML dosyasını kaydet."""
        root = self.build()

        xml_string = etree.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
            doctype='<!DOCTYPE xmeml>',
        )

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(xml_string)

        logger.info(f"Premiere XML saved to {self.output_path}")
        return self.output_path


def export_premiere_xml(
    project: Project,
    output_path: Path,
) -> Path:
    """
    Adobe Premiere XML export.

    Args:
        project: AutoCut project
        output_path: Çıktı dosya yolu (.xml)

    Returns:
        Kaydedilen dosya path'i
    """
    builder = PremiereXMLBuilder(
        project=project,
        output_path=output_path,
    )
    return builder.save()
