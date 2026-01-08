"""
FFmpeg/FFprobe wrapper for media operations.

Provides:
- Media probing (duration, fps, codec info)
- Audio extraction to WAV
- Proxy generation (lower resolution)
"""

from __future__ import annotations

import json
import subprocess
import shutil
import sys
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
import logging

from app.core.models import MediaInfo

logger = logging.getLogger(__name__)


def get_bundle_bin_path() -> Optional[Path]:
    """Get the path to bundled binaries (for PyInstaller builds)."""
    if getattr(sys, 'frozen', False):
        # Running as bundled app
        bundle_dir = Path(sys._MEIPASS)
        bin_path = bundle_dir / "bin"
        if bin_path.exists():
            return bin_path
    return None


def get_static_ffmpeg_path() -> Optional[Path]:
    """Get path to static-ffmpeg package binaries."""
    try:
        import static_ffmpeg
        import importlib.util
        import platform as plat

        spec = importlib.util.find_spec("static_ffmpeg")
        if spec and spec.origin:
            static_bin_dir = Path(spec.origin).parent / "bin"

            # Platform'a göre klasör
            if plat.system() == "Darwin":
                return static_bin_dir / "darwin"
            elif plat.system() == "Windows":
                return static_bin_dir / "win32"
            else:
                return static_bin_dir / "linux"
    except ImportError:
        pass
    return None


def find_ffmpeg() -> Optional[str]:
    """Find ffmpeg binary, checking bundle first, then static-ffmpeg, then system."""
    # 1. Check bundle first (PyInstaller)
    bundle_bin = get_bundle_bin_path()
    if bundle_bin:
        ffmpeg_path = bundle_bin / "ffmpeg"
        if ffmpeg_path.exists() and os.access(ffmpeg_path, os.X_OK):
            logger.info(f"Using bundled ffmpeg: {ffmpeg_path}")
            return str(ffmpeg_path)

    # 2. Check static-ffmpeg package
    static_bin = get_static_ffmpeg_path()
    if static_bin:
        ffmpeg_path = static_bin / "ffmpeg"
        if ffmpeg_path.exists() and os.access(ffmpeg_path, os.X_OK):
            logger.info(f"Using static-ffmpeg: {ffmpeg_path}")
            return str(ffmpeg_path)

    # 3. Fall back to system PATH
    return shutil.which("ffmpeg")


def find_ffprobe() -> Optional[str]:
    """Find ffprobe binary, checking bundle first, then static-ffmpeg, then system."""
    # 1. Check bundle first (PyInstaller)
    bundle_bin = get_bundle_bin_path()
    if bundle_bin:
        ffprobe_path = bundle_bin / "ffprobe"
        if ffprobe_path.exists() and os.access(ffprobe_path, os.X_OK):
            logger.info(f"Using bundled ffprobe: {ffprobe_path}")
            return str(ffprobe_path)

    # 2. Check static-ffmpeg package
    static_bin = get_static_ffmpeg_path()
    if static_bin:
        ffprobe_path = static_bin / "ffprobe"
        if ffprobe_path.exists() and os.access(ffprobe_path, os.X_OK):
            logger.info(f"Using static-ffprobe: {ffprobe_path}")
            return str(ffprobe_path)

    # 3. Fall back to system PATH
    return shutil.which("ffprobe")


class FFmpegError(Exception):
    """FFmpeg işlemi hatası."""
    pass


class FFmpegNotFoundError(FFmpegError):
    """FFmpeg/FFprobe bulunamadı."""
    pass


@dataclass
class FFmpegWrapper:
    """FFmpeg/FFprobe binary wrapper."""
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    def __post_init__(self):
        # Binary'leri kontrol et - önce bundle, sonra sistem PATH
        self._ffmpeg = find_ffmpeg() or shutil.which(self.ffmpeg_path)
        self._ffprobe = find_ffprobe() or shutil.which(self.ffprobe_path)

        if not self._ffmpeg:
            raise FFmpegNotFoundError(
                f"FFmpeg not found: {self.ffmpeg_path}. "
                "Please install FFmpeg and ensure it's in your PATH."
            )
        if not self._ffprobe:
            raise FFmpegNotFoundError(
                f"FFprobe not found: {self.ffprobe_path}. "
                "Please install FFmpeg and ensure it's in your PATH."
            )

        logger.info(f"FFmpeg: {self._ffmpeg}")
        logger.info(f"FFprobe: {self._ffprobe}")

    def probe(self, file_path: Path) -> MediaInfo:
        """
        Medya dosyasını analiz et ve metadata döndür.

        Args:
            file_path: Video/audio dosya yolu

        Returns:
            MediaInfo object

        Raises:
            FFmpegError: Probe başarısız olursa
        """
        if not file_path.exists():
            raise FFmpegError(f"File not found: {file_path}")

        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                raise FFmpegError(f"FFprobe failed: {result.stderr}")

            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            raise FFmpegError("FFprobe timeout")
        except json.JSONDecodeError as e:
            raise FFmpegError(f"Failed to parse FFprobe output: {e}")

        return self._parse_probe_result(file_path, data)

    def _parse_probe_result(self, file_path: Path, data: dict) -> MediaInfo:
        """FFprobe JSON çıktısını MediaInfo'ya dönüştür."""
        format_info = data.get("format", {})
        streams = data.get("streams", [])

        # Video stream bul
        video_stream = None
        audio_stream = None
        for stream in streams:
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = stream
            elif stream.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = stream

        # Duration
        duration = float(format_info.get("duration", 0))

        # Video bilgileri
        width = 0
        height = 0
        fps = 0.0
        video_codec = ""

        if video_stream:
            width = int(video_stream.get("width", 0))
            height = int(video_stream.get("height", 0))
            video_codec = video_stream.get("codec_name", "")

            # FPS hesapla
            fps_str = video_stream.get("r_frame_rate", "0/1")
            try:
                num, den = map(int, fps_str.split("/"))
                fps = num / den if den > 0 else 0.0
            except (ValueError, ZeroDivisionError):
                fps = float(video_stream.get("avg_frame_rate", "0").split("/")[0] or 0)

        # Audio bilgileri
        sample_rate = 48000
        channels = 2
        bit_depth = 16
        audio_codec = ""

        if audio_stream:
            sample_rate = int(audio_stream.get("sample_rate", 48000))
            channels = int(audio_stream.get("channels", 2))
            audio_codec = audio_stream.get("codec_name", "")

            # Bit depth
            bits = audio_stream.get("bits_per_sample", 0)
            if bits:
                bit_depth = int(bits)
            elif audio_stream.get("sample_fmt") in ("s16", "s16p"):
                bit_depth = 16
            elif audio_stream.get("sample_fmt") in ("s32", "s32p", "flt", "fltp"):
                bit_depth = 32

        return MediaInfo(
            file_path=file_path,
            duration=duration,
            fps=fps,
            width=width,
            height=height,
            video_codec=video_codec,
            audio_codec=audio_codec,
            sample_rate=sample_rate,
            channels=channels,
            bit_depth=bit_depth,
            file_size=file_path.stat().st_size,
        )

    def extract_audio(
        self,
        input_path: Path,
        output_path: Path,
        sample_rate: int = 48000,
        mono: bool = True,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> Path:
        """
        Video/audio'dan WAV çıkart.

        Args:
            input_path: Kaynak dosya
            output_path: Hedef WAV dosyası
            sample_rate: Çıktı sample rate
            mono: True ise mono'ya dönüştür
            progress_callback: İlerleme callback'i (0.0 - 1.0)

        Returns:
            Çıktı dosya path'i
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        channels = "1" if mono else "2"

        cmd = [
            self._ffmpeg,
            "-y",  # Overwrite
            "-i", str(input_path),
            "-vn",  # Video'yu atla
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", channels,
            "-f", "wav",
            str(output_path)
        ]

        # Progress için duration al
        duration = None
        if progress_callback:
            try:
                info = self.probe(input_path)
                duration = info.duration
            except FFmpegError:
                pass

        self._run_with_progress(cmd, duration, progress_callback)
        return output_path

    def generate_proxy(
        self,
        input_path: Path,
        output_path: Path,
        resolution: str = "720p",
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> Path:
        """
        Düşük çözünürlüklü proxy video oluştur.

        Args:
            input_path: Kaynak video
            output_path: Hedef proxy dosyası
            resolution: 480p, 720p, 1080p
            progress_callback: İlerleme callback'i

        Returns:
            Çıktı dosya path'i
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Resolution mapping
        res_map = {
            "480p": "854:480",
            "720p": "1280:720",
            "1080p": "1920:1080",
        }
        scale = res_map.get(resolution, "1280:720")

        cmd = [
            self._ffmpeg,
            "-y",
            "-i", str(input_path),
            "-vf", f"scale={scale}:force_original_aspect_ratio=decrease",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            str(output_path)
        ]

        # Duration al
        duration = None
        if progress_callback:
            try:
                info = self.probe(input_path)
                duration = info.duration
            except FFmpegError:
                pass

        self._run_with_progress(cmd, duration, progress_callback)
        return output_path

    def _run_with_progress(
        self,
        cmd: list[str],
        duration: Optional[float],
        progress_callback: Optional[Callable[[float], None]],
    ) -> None:
        """FFmpeg komutunu progress tracking ile çalıştır."""
        # Progress için -progress pipe ekle
        if progress_callback and duration:
            cmd.insert(1, "-progress")
            cmd.insert(2, "pipe:1")
            cmd.insert(3, "-stats_period")
            cmd.insert(4, "0.5")

        logger.debug(f"Running FFmpeg: {' '.join(cmd)}")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if progress_callback and duration and process.stdout:
                current_time = 0.0
                for line in process.stdout:
                    if line.startswith("out_time_ms="):
                        try:
                            time_ms = int(line.split("=")[1].strip())
                            current_time = time_ms / 1_000_000  # microseconds to seconds
                            progress = min(current_time / duration, 1.0)
                            progress_callback(progress)
                        except (ValueError, IndexError):
                            pass

            stdout, stderr = process.communicate(timeout=3600)  # 1 hour timeout

            if process.returncode != 0:
                raise FFmpegError(f"FFmpeg failed (code {process.returncode}): {stderr}")

        except subprocess.TimeoutExpired:
            process.kill()
            raise FFmpegError("FFmpeg process timeout")

    def get_frame_at_time(
        self,
        input_path: Path,
        time_sec: float,
        output_path: Path,
        width: int = 320,
    ) -> Path:
        """
        Belirli bir zamandaki frame'i çıkart (thumbnail).

        Args:
            input_path: Video dosyası
            time_sec: Zaman (saniye)
            output_path: Çıktı image path
            width: Thumbnail genişliği

        Returns:
            Çıktı dosya path'i
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._ffmpeg,
            "-y",
            "-ss", str(time_sec),
            "-i", str(input_path),
            "-vframes", "1",
            "-vf", f"scale={width}:-1",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise FFmpegError(f"Frame extraction failed: {result.stderr}")

        return output_path


# Convenience functions
_wrapper: Optional[FFmpegWrapper] = None


def get_wrapper() -> FFmpegWrapper:
    """Singleton FFmpegWrapper instance."""
    global _wrapper
    if _wrapper is None:
        _wrapper = FFmpegWrapper()
    return _wrapper


def probe_media(file_path: Path) -> MediaInfo:
    """Medya dosyasını probe et."""
    return get_wrapper().probe(file_path)


def extract_audio(
    input_path: Path,
    output_path: Path,
    sample_rate: int = 48000,
    mono: bool = True,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> Path:
    """Audio çıkart."""
    return get_wrapper().extract_audio(
        input_path, output_path, sample_rate, mono, progress_callback
    )


def generate_proxy(
    input_path: Path,
    output_path: Path,
    resolution: str = "720p",
    progress_callback: Optional[Callable[[float], None]] = None,
) -> Path:
    """Proxy video oluştur."""
    return get_wrapper().generate_proxy(
        input_path, output_path, resolution, progress_callback
    )
