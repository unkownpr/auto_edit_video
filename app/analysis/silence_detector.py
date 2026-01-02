"""
Silence detection algorithm.

dBFS tabanlı sessizlik tespiti:
- Frame-by-frame RMS analizi
- Histerezis ile jitter önleme
- Padding ve merge işlemleri
- Opsiyonel VAD entegrasyonu
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
import logging

import numpy as np
from scipy.io import wavfile

from app.core.models import AnalysisConfig, AudioSegment, Cut, CutType

logger = logging.getLogger(__name__)


@dataclass
class SilenceDetector:
    """
    Sessizlik tespit motoru.

    Algoritma:
    1. Audio'yu frame'lere böl (frame_ms)
    2. Her frame için RMS -> dBFS hesapla
    3. Histerezis ile silence on/off kararı ver
    4. Ardışık silence frame'lerini segment'lere birleştir
    5. min_duration filtresi uygula
    6. Yakın segment'leri merge et
    7. Padding ekle
    """
    config: AnalysisConfig

    def detect(
        self,
        wav_path: Path,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> list[Cut]:
        """
        WAV dosyasında sessizlikleri tespit et.

        Args:
            wav_path: WAV dosya yolu
            progress_callback: İlerleme callback'i

        Returns:
            Cut listesi (kesilecek segmentler)
        """
        logger.info(f"Starting silence detection: {wav_path}")
        logger.debug(f"Config: threshold={self.config.silence_threshold_db}dB, "
                    f"min_duration={self.config.silence_min_duration_ms}ms")

        # WAV yükle
        sample_rate, audio_data = wavfile.read(wav_path)

        # Mono'ya dönüştür
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)

        # Normalize
        if audio_data.dtype == np.int16:
            audio_data = audio_data.astype(np.float32) / 32768.0
        elif audio_data.dtype == np.int32:
            audio_data = audio_data.astype(np.float32) / 2147483648.0

        duration = len(audio_data) / sample_rate

        # Frame boyutu (sample cinsinden)
        frame_samples = int(sample_rate * self.config.frame_ms / 1000)

        if progress_callback:
            progress_callback(0.1)

        # 1. Frame-by-frame dBFS hesapla
        db_values = self._compute_frame_db(audio_data, frame_samples)

        if progress_callback:
            progress_callback(0.3)

        # 2. Histerezis ile silence mask oluştur
        silence_mask = self._apply_hysteresis(db_values)

        if progress_callback:
            progress_callback(0.5)

        # 3. Mask'tan segment'ler çıkar
        raw_segments = self._mask_to_segments(
            silence_mask, db_values, frame_samples, sample_rate
        )

        if progress_callback:
            progress_callback(0.6)

        # 4. Min duration filtresi
        filtered_segments = self._filter_by_duration(raw_segments)

        if progress_callback:
            progress_callback(0.7)

        # 5. Yakın segment'leri merge et
        merged_segments = self._merge_close_segments(filtered_segments)

        if progress_callback:
            progress_callback(0.8)

        # 6. Padding uygula
        padded_segments = self._apply_padding(merged_segments, duration)

        if progress_callback:
            progress_callback(0.9)

        # 7. Cut objelerine dönüştür
        cuts = self._segments_to_cuts(padded_segments)

        if progress_callback:
            progress_callback(1.0)

        logger.info(f"Detected {len(cuts)} silence regions")
        return cuts

    def _compute_frame_db(
        self,
        audio_data: np.ndarray,
        frame_samples: int,
    ) -> np.ndarray:
        """Frame bazlı dBFS hesapla - VECTORIZED for speed."""
        num_frames = len(audio_data) // frame_samples

        # Trim audio to exact frame boundaries
        trimmed_length = num_frames * frame_samples
        audio_trimmed = audio_data[:trimmed_length]

        # Reshape to (num_frames, frame_samples) for vectorized computation
        frames = audio_trimmed.reshape(num_frames, frame_samples)

        # Vectorized RMS calculation
        rms_values = np.sqrt(np.mean(frames ** 2, axis=1))

        # Vectorized dBFS calculation
        # Avoid log(0) by clipping minimum value
        rms_clipped = np.maximum(rms_values, 1e-10)
        db_values = 20 * np.log10(rms_clipped)

        return db_values.astype(np.float32)

    def _apply_hysteresis(self, db_values: np.ndarray) -> np.ndarray:
        """
        Histerezis ile silence mask oluştur - optimized with numba-style logic.

        On threshold: silence_threshold_db - hysteresis_db
        Off threshold: silence_threshold_db + hysteresis_db

        Bu sayede threshold etrafında oscillation önlenir.
        """
        on_threshold = self.config.silence_threshold_db - self.config.hysteresis_db
        off_threshold = self.config.silence_threshold_db + self.config.hysteresis_db

        # Pre-compute boolean arrays for speed
        below_on = db_values < on_threshold
        above_off = db_values > off_threshold

        mask = np.zeros(len(db_values), dtype=bool)
        in_silence = False

        # This loop is inherently sequential due to state dependency
        # but we minimized array access overhead
        for i in range(len(db_values)):
            if in_silence:
                if above_off[i]:
                    in_silence = False
                else:
                    mask[i] = True
            else:
                if below_on[i]:
                    in_silence = True
                    mask[i] = True

        return mask

    def _mask_to_segments(
        self,
        mask: np.ndarray,
        db_values: np.ndarray,
        frame_samples: int,
        sample_rate: int,
    ) -> list[AudioSegment]:
        """Silence mask'tan segment'ler oluştur."""
        segments = []
        in_silence = False
        start_frame = 0

        for i, is_silent in enumerate(mask):
            if is_silent and not in_silence:
                # Silence başlıyor
                in_silence = True
                start_frame = i
            elif not is_silent and in_silence:
                # Silence bitiyor
                in_silence = False
                segment = self._create_segment(
                    start_frame, i, db_values, frame_samples, sample_rate
                )
                segments.append(segment)

        # Son segment
        if in_silence:
            segment = self._create_segment(
                start_frame, len(mask), db_values, frame_samples, sample_rate
            )
            segments.append(segment)

        return segments

    def _create_segment(
        self,
        start_frame: int,
        end_frame: int,
        db_values: np.ndarray,
        frame_samples: int,
        sample_rate: int,
    ) -> AudioSegment:
        """AudioSegment oluştur."""
        start_time = start_frame * frame_samples / sample_rate
        end_time = end_frame * frame_samples / sample_rate

        # Segment içindeki dB değerleri
        segment_db = db_values[start_frame:end_frame]
        avg_db = float(np.mean(segment_db)) if len(segment_db) > 0 else -96.0
        peak_db = float(np.max(segment_db)) if len(segment_db) > 0 else -96.0

        return AudioSegment(
            start=start_time,
            end=end_time,
            avg_db=avg_db,
            peak_db=peak_db,
            is_silence=True,
        )

    def _filter_by_duration(
        self,
        segments: list[AudioSegment],
    ) -> list[AudioSegment]:
        """Min duration filtresi."""
        min_duration = self.config.silence_min_duration_ms / 1000.0
        keep_threshold = self.config.keep_short_pauses_ms / 1000.0

        filtered = []
        for seg in segments:
            # Min duration kontrolü
            if seg.duration < min_duration:
                continue

            # Kısa pause koruma (eğer aktifse)
            if keep_threshold > 0 and seg.duration < keep_threshold:
                continue

            filtered.append(seg)

        return filtered

    def _merge_close_segments(
        self,
        segments: list[AudioSegment],
    ) -> list[AudioSegment]:
        """Yakın segment'leri birleştir."""
        if not segments:
            return []

        merge_gap = self.config.merge_gap_ms / 1000.0
        merged = [segments[0]]

        for seg in segments[1:]:
            last = merged[-1]

            # İki segment yeterince yakın mı?
            gap = seg.start - last.end
            if gap <= merge_gap:
                # Birleştir
                merged[-1] = last.merge_with(seg)
            else:
                merged.append(seg)

        return merged

    def _apply_padding(
        self,
        segments: list[AudioSegment],
        total_duration: float,
    ) -> list[AudioSegment]:
        """Padding uygula (sessizliği daralt, konuşmayı koru)."""
        pre_pad = self.config.pre_pad_ms / 1000.0
        post_pad = self.config.post_pad_ms / 1000.0

        padded = []
        for seg in segments:
            # Padding uygula
            new_start = seg.start + pre_pad
            new_end = seg.end - post_pad

            # Geçerli mi?
            if new_start < new_end and new_end - new_start >= 0.01:  # min 10ms
                padded.append(AudioSegment(
                    start=max(0, new_start),
                    end=min(total_duration, new_end),
                    avg_db=seg.avg_db,
                    peak_db=seg.peak_db,
                    is_silence=True,
                ))

        return padded

    def _segments_to_cuts(self, segments: list[AudioSegment]) -> list[Cut]:
        """AudioSegment'leri Cut objelerine dönüştür."""
        cuts = []
        for seg in segments:
            cut = Cut(
                start=seg.start,
                end=seg.end,
                cut_type=CutType.SILENCE,
                enabled=True,
                source_avg_db=seg.avg_db,
                source_peak_db=seg.peak_db,
            )
            cuts.append(cut)
        return cuts


def detect_silence(
    wav_path: Path,
    config: Optional[AnalysisConfig] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> list[Cut]:
    """
    Convenience function for silence detection.

    Args:
        wav_path: WAV dosya yolu
        config: Analiz konfigürasyonu (None ise default)
        progress_callback: İlerleme callback'i

    Returns:
        Cut listesi
    """
    if config is None:
        config = AnalysisConfig()

    detector = SilenceDetector(config=config)
    return detector.detect(wav_path, progress_callback)


def detect_silence_with_vad(
    wav_path: Path,
    config: AnalysisConfig,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> list[Cut]:
    """
    VAD (Voice Activity Detection) ile sessizlik tespiti.

    WebRTC VAD kullanarak konuşma olmayan bölgeleri tespit eder.
    Gürültülü ortamlar için daha iyi çalışır.
    """
    try:
        import webrtcvad
    except ImportError:
        logger.warning("webrtcvad not installed, falling back to dBFS detection")
        return detect_silence(wav_path, config, progress_callback)

    # WAV yükle
    sample_rate, audio_data = wavfile.read(wav_path)

    # VAD için gereksinimler: 8000, 16000, 32000, 48000 Hz
    if sample_rate not in (8000, 16000, 32000, 48000):
        logger.warning(f"VAD requires specific sample rates, got {sample_rate}")
        return detect_silence(wav_path, config, progress_callback)

    # Mono ve int16
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)

    if audio_data.dtype != np.int16:
        if audio_data.dtype == np.float32:
            audio_data = (audio_data * 32767).astype(np.int16)
        else:
            audio_data = audio_data.astype(np.int16)

    # VAD oluştur
    vad = webrtcvad.Vad(config.vad_aggressiveness)

    # Frame boyutu: 10, 20, veya 30 ms
    frame_ms = 30  # VAD için optimal
    frame_samples = int(sample_rate * frame_ms / 1000)

    # VAD ile analiz
    is_speech = []
    for i in range(0, len(audio_data) - frame_samples, frame_samples):
        frame = audio_data[i:i + frame_samples]
        frame_bytes = frame.tobytes()

        try:
            speech = vad.is_speech(frame_bytes, sample_rate)
            is_speech.append(speech)
        except Exception:
            is_speech.append(True)  # Hata durumunda konuşma varsay

        if progress_callback and i % 10000 == 0:
            progress_callback(0.5 * i / len(audio_data))

    # Silence mask (is_speech'in tersi)
    silence_mask = np.array([not s for s in is_speech], dtype=bool)

    # dBFS değerleri de hesapla (metadata için)
    audio_float = audio_data.astype(np.float32) / 32768.0
    num_frames = len(silence_mask)
    db_values = np.zeros(num_frames, dtype=np.float32)

    for i in range(num_frames):
        start = i * frame_samples
        end = start + frame_samples
        if end <= len(audio_float):
            frame = audio_float[start:end]
            rms = np.sqrt(np.mean(frame ** 2))
            db_values[i] = 20 * np.log10(rms) if rms > 1e-10 else -96.0

    # Segment'lere dönüştür
    duration = len(audio_data) / sample_rate
    detector = SilenceDetector(config=config)

    raw_segments = detector._mask_to_segments(
        silence_mask, db_values, frame_samples, sample_rate
    )

    if progress_callback:
        progress_callback(0.7)

    # Filter, merge, pad
    filtered = detector._filter_by_duration(raw_segments)
    merged = detector._merge_close_segments(filtered)
    padded = detector._apply_padding(merged, duration)

    if progress_callback:
        progress_callback(1.0)

    return detector._segments_to_cuts(padded)
