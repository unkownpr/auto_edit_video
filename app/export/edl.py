"""
EDL (Edit Decision List) export module.

DaVinci Resolve ve diğer NLE'ler için CMX 3600 formatında EDL.

Format:
    TITLE: Project Name
    FCM: NON-DROP FRAME

    001  AX       V     C        00:00:00:00 00:00:10:00 00:00:00:00 00:00:10:00
    * FROM CLIP NAME: video.mp4

    002  AX       V     C        00:00:20:00 00:00:40:00 00:00:10:00 00:00:30:00
    ...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

from app.core.models import MediaInfo, Project

logger = logging.getLogger(__name__)


def frames_to_timecode(frames: int, fps: float, drop_frame: bool = False) -> str:
    """
    Frame sayısını timecode'a dönüştür.

    Args:
        frames: Frame sayısı
        fps: Frame rate
        drop_frame: Drop frame kullan

    Returns:
        HH:MM:SS:FF formatında timecode
    """
    # Drop frame hesaplaması (29.97fps için)
    if drop_frame and abs(fps - 29.97) < 0.1:
        # Drop frame: her dakika başında 2 frame atlanır (00 ve 10. dakikalar hariç)
        d = frames // 17982
        m = frames % 17982
        frames = frames + 18 * d + 2 * ((m - 2) // 1798)

    fps_int = round(fps)
    total_seconds = frames // fps_int
    remaining_frames = frames % fps_int

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    # Drop frame separator
    sep = ";" if drop_frame else ":"

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{sep}{remaining_frames:02d}"


def seconds_to_timecode(seconds: float, fps: float, drop_frame: bool = False) -> str:
    """Saniyeyi timecode'a dönüştür."""
    frames = int(seconds * fps)
    return frames_to_timecode(frames, fps, drop_frame)


@dataclass
class EDLBuilder:
    """
    EDL (CMX 3600) builder.

    DaVinci Resolve, Avid, ve diğer profesyonel NLE'ler için.
    """
    project: Project
    output_path: Path
    drop_frame: bool = False  # 29.97fps için True yapılabilir

    def build(self) -> str:
        """EDL içeriğini oluştur."""
        if not self.project.media_info:
            raise ValueError("Project has no media info")

        media = self.project.media_info
        keep_segments = self.project.get_keep_segments()
        fps = media.fps or 30.0

        lines = []

        # Header
        title = self.project.name or media.file_path.stem
        lines.append(f"TITLE: {title}")

        if self.drop_frame:
            lines.append("FCM: DROP FRAME")
        else:
            lines.append("FCM: NON-DROP FRAME")

        lines.append("")

        # Timeline üzerindeki pozisyon
        timeline_offset = 0.0

        for i, (seg_start, seg_end) in enumerate(keep_segments):
            event_num = i + 1
            seg_duration = seg_end - seg_start

            # Source timecodes (orijinal videodaki pozisyon)
            src_in = seconds_to_timecode(seg_start, fps, self.drop_frame)
            src_out = seconds_to_timecode(seg_end, fps, self.drop_frame)

            # Record timecodes (timeline üzerindeki pozisyon)
            rec_in = seconds_to_timecode(timeline_offset, fps, self.drop_frame)
            rec_out = seconds_to_timecode(timeline_offset + seg_duration, fps, self.drop_frame)

            # Event line
            # Format: EVENT  REEL  TRACK  TYPE  SRC_IN  SRC_OUT  REC_IN  REC_OUT
            lines.append(
                f"{event_num:03d}  AX       V     C        "
                f"{src_in} {src_out} {rec_in} {rec_out}"
            )

            # Source clip name
            lines.append(f"* FROM CLIP NAME: {media.file_path.name}")

            # Boş satır
            lines.append("")

            timeline_offset += seg_duration

        return "\n".join(lines)

    def save(self) -> Path:
        """EDL dosyasını kaydet."""
        content = self.build()

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(content, encoding="utf-8")

        logger.info(f"EDL saved to {self.output_path}")
        return self.output_path


def export_edl(
    project: Project,
    output_path: Path,
    drop_frame: bool = False,
) -> Path:
    """
    EDL export convenience function.

    Args:
        project: AutoCut project
        output_path: Çıktı dosya yolu (.edl)
        drop_frame: Drop frame timecode kullan

    Returns:
        Kaydedilen dosya path'i
    """
    builder = EDLBuilder(
        project=project,
        output_path=output_path,
        drop_frame=drop_frame,
    )
    return builder.save()
