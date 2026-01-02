"""
Waveform data generation and caching.

Peak-based waveform verisi üretir ve cache'ler.
Timeline çizimi için optimize edilmiş format.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
import logging

import numpy as np
from scipy.io import wavfile

logger = logging.getLogger(__name__)


@dataclass
class WaveformData:
    """
    Waveform peak verisi.

    Her "bucket" için min ve max değerler tutulur.
    Bu sayede farklı zoom seviyelerinde hızlı çizim yapılabilir.
    """
    peaks_min: np.ndarray   # (n_buckets,) float32, -1.0 to 1.0
    peaks_max: np.ndarray   # (n_buckets,) float32, -1.0 to 1.0
    sample_rate: int
    samples_per_bucket: int
    total_samples: int
    duration: float         # saniye

    @property
    def num_buckets(self) -> int:
        return len(self.peaks_min)

    def get_peaks_for_range(
        self,
        start_time: float,
        end_time: float,
        num_points: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Belirli bir zaman aralığı için peak verisi döndür.

        Args:
            start_time: Başlangıç zamanı (saniye)
            end_time: Bitiş zamanı (saniye)
            num_points: İstenen nokta sayısı

        Returns:
            (min_peaks, max_peaks) tuple
        """
        start_bucket = int(start_time * self.sample_rate / self.samples_per_bucket)
        end_bucket = int(end_time * self.sample_rate / self.samples_per_bucket)

        start_bucket = max(0, start_bucket)
        end_bucket = min(self.num_buckets, end_bucket)

        if start_bucket >= end_bucket:
            return np.zeros(num_points), np.zeros(num_points)

        # Bucket'ları al
        min_data = self.peaks_min[start_bucket:end_bucket]
        max_data = self.peaks_max[start_bucket:end_bucket]

        # Resample if needed
        if len(min_data) != num_points:
            indices = np.linspace(0, len(min_data) - 1, num_points).astype(int)
            min_data = min_data[indices]
            max_data = max_data[indices]

        return min_data, max_data

    def save(self, path: Path) -> None:
        """Waveform verisini .npz olarak kaydet."""
        np.savez_compressed(
            path,
            peaks_min=self.peaks_min,
            peaks_max=self.peaks_max,
            metadata=np.array([
                self.sample_rate,
                self.samples_per_bucket,
                self.total_samples,
            ]),
        )
        logger.debug(f"Waveform saved to {path}")

    @classmethod
    def load(cls, path: Path) -> WaveformData:
        """Waveform verisini .npz'den yükle."""
        data = np.load(path)
        metadata = data["metadata"]
        sample_rate = int(metadata[0])
        total_samples = int(metadata[2])

        return cls(
            peaks_min=data["peaks_min"],
            peaks_max=data["peaks_max"],
            sample_rate=sample_rate,
            samples_per_bucket=int(metadata[1]),
            total_samples=total_samples,
            duration=total_samples / sample_rate,
        )


class WaveformGenerator:
    """
    WAV dosyasından waveform peak verisi üret.
    """

    def __init__(
        self,
        samples_per_bucket: int = 256,
        cache_dir: Optional[Path] = None,
    ):
        """
        Args:
            samples_per_bucket: Her bucket için sample sayısı
            cache_dir: Cache dizini (None ise cache kullanılmaz)
        """
        self.samples_per_bucket = samples_per_bucket
        self.cache_dir = cache_dir

        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, wav_path: Path) -> Optional[Path]:
        """Cache dosyası path'i."""
        if not self.cache_dir:
            return None

        # Hash: file path + mtime + size
        stat = wav_path.stat()
        hash_input = f"{wav_path}:{stat.st_mtime}:{stat.st_size}:{self.samples_per_bucket}"
        file_hash = hashlib.md5(hash_input.encode()).hexdigest()[:16]

        return self.cache_dir / f"waveform_{file_hash}.npz"

    def generate(
        self,
        wav_path: Path,
        progress_callback: Optional[Callable[[float], None]] = None,
        use_cache: bool = True,
    ) -> WaveformData:
        """
        WAV dosyasından waveform verisi üret.

        Args:
            wav_path: WAV dosya yolu
            progress_callback: İlerleme callback'i (0.0 - 1.0)
            use_cache: Cache kullan

        Returns:
            WaveformData
        """
        # Cache kontrol
        cache_path = self._get_cache_path(wav_path)
        if use_cache and cache_path and cache_path.exists():
            try:
                logger.debug(f"Loading cached waveform from {cache_path}")
                return WaveformData.load(cache_path)
            except Exception as e:
                logger.warning(f"Cache load failed: {e}")

        # WAV yükle
        logger.debug(f"Generating waveform for {wav_path}")
        sample_rate, audio_data = wavfile.read(wav_path)

        # Mono'ya dönüştür
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)

        # Normalize et (-1.0 to 1.0)
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.int32:
            audio_data = audio_data.astype(np.float32) / 2147483648.0
        elif audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        total_samples = len(audio_data)
        num_buckets = (total_samples + self.samples_per_bucket - 1) // self.samples_per_bucket

        peaks_min = np.zeros(num_buckets, dtype=np.float32)
        peaks_max = np.zeros(num_buckets, dtype=np.float32)

        # Bucket'ları hesapla
        for i in range(num_buckets):
            start = i * self.samples_per_bucket
            end = min(start + self.samples_per_bucket, total_samples)
            chunk = audio_data[start:end]

            if len(chunk) > 0:
                peaks_min[i] = chunk.min()
                peaks_max[i] = chunk.max()

            # Progress
            if progress_callback and i % 1000 == 0:
                progress_callback(i / num_buckets)

        if progress_callback:
            progress_callback(1.0)

        waveform = WaveformData(
            peaks_min=peaks_min,
            peaks_max=peaks_max,
            sample_rate=sample_rate,
            samples_per_bucket=self.samples_per_bucket,
            total_samples=total_samples,
            duration=total_samples / sample_rate,
        )

        # Cache'e kaydet
        if cache_path:
            try:
                waveform.save(cache_path)
            except Exception as e:
                logger.warning(f"Cache save failed: {e}")

        return waveform

    def generate_multi_resolution(
        self,
        wav_path: Path,
        resolutions: list[int] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> dict[int, WaveformData]:
        """
        Birden fazla çözünürlükte waveform üret.

        Farklı zoom seviyelerinde hızlı çizim için.
        """
        if resolutions is None:
            resolutions = [64, 256, 1024, 4096]

        result = {}
        for i, res in enumerate(resolutions):
            generator = WaveformGenerator(
                samples_per_bucket=res,
                cache_dir=self.cache_dir,
            )

            def sub_progress(p: float):
                if progress_callback:
                    base = i / len(resolutions)
                    progress_callback(base + p / len(resolutions))

            result[res] = generator.generate(wav_path, sub_progress)

        return result


def compute_rms_db(audio_data: np.ndarray, frame_size: int) -> np.ndarray:
    """
    Audio verisinden frame bazlı RMS dBFS hesapla.

    Args:
        audio_data: Normalized audio (-1.0 to 1.0)
        frame_size: Frame boyutu (sample)

    Returns:
        dBFS değerleri array'i
    """
    num_frames = len(audio_data) // frame_size
    rms_values = np.zeros(num_frames, dtype=np.float32)

    for i in range(num_frames):
        start = i * frame_size
        end = start + frame_size
        frame = audio_data[start:end]

        # RMS hesapla
        rms = np.sqrt(np.mean(frame ** 2))

        # dBFS'e dönüştür
        if rms > 0:
            rms_values[i] = 20 * np.log10(rms)
        else:
            rms_values[i] = -96.0  # Minimum dB

    return rms_values
