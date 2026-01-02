"""
Silence detection algorithm.

dBFS tabanlı sessizlik tespiti:
- Frame-by-frame RMS analizi
- Histerezis ile jitter önleme
- Padding ve merge işlemleri
- Opsiyonel VAD entegrasyonu
- FFmpeg silencedetect entegrasyonu (frame-accurate)
"""

from __future__ import annotations

import re
import subprocess
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
    3. (Opsiyonel) Adaptif eşik hesapla
    4. Histerezis ile silence on/off kararı ver
    5. Ardışık silence frame'lerini segment'lere birleştir
    6. min_duration filtresi uygula
    7. Yakın segment'leri merge et
    8. Padding ekle
    """
    config: AnalysisConfig

    def _calculate_adaptive_threshold(self, db_values: np.ndarray) -> float:
        """
        Audio seviyesine göre adaptif eşik hesapla.

        Fikir: En sessiz %20'lik kısmın ortalaması + margin = sessizlik eşiği
        Bu sayede her ses dosyası için optimize edilmiş eşik bulunur.
        """
        # Alt %20 percentile (sessiz kısımlar)
        noise_floor = np.percentile(db_values, 20)

        # Üst %80 percentile (konuşma/ses kısımları)
        signal_level = np.percentile(db_values, 80)

        # Eşik: noise floor ile signal arasında dinamik bir nokta
        # noise_floor'a yakın ama biraz üstünde
        dynamic_range = signal_level - noise_floor

        if dynamic_range < 10:
            # Çok düşük dinamik aralık - muhtemelen çok sessiz veya çok gürültülü
            # Kullanıcı eşiğini kullan
            return self.config.silence_threshold_db

        # Adaptif eşik: noise floor + dinamik aralığın %25'i
        adaptive_threshold = noise_floor + (dynamic_range * 0.25)

        # Kullanıcı eşiği ile karşılaştır, daha yüksek olanı al (daha az agresif)
        final_threshold = max(adaptive_threshold, self.config.silence_threshold_db)

        logger.info(f"Adaptive threshold: noise_floor={noise_floor:.1f}dB, "
                   f"signal={signal_level:.1f}dB, range={dynamic_range:.1f}dB, "
                   f"adaptive={adaptive_threshold:.1f}dB, final={final_threshold:.1f}dB")

        return final_threshold

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
            progress_callback(0.25)

        # 2. Adaptif eşik hesapla (opsiyonel ama daha doğru sonuç verir)
        adaptive_threshold = self._calculate_adaptive_threshold(db_values)

        if progress_callback:
            progress_callback(0.3)

        # 3. Histerezis ile silence mask oluştur
        silence_mask = self._apply_hysteresis(db_values, threshold_override=adaptive_threshold)

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

    def _apply_hysteresis(
        self,
        db_values: np.ndarray,
        threshold_override: Optional[float] = None,
    ) -> np.ndarray:
        """
        Histerezis ile silence mask oluştur - optimized with numba-style logic.

        On threshold: silence_threshold_db - hysteresis_db
        Off threshold: silence_threshold_db + hysteresis_db

        Bu sayede threshold etrafında oscillation önlenir.
        """
        base_threshold = threshold_override if threshold_override is not None else self.config.silence_threshold_db
        on_threshold = base_threshold - self.config.hysteresis_db
        off_threshold = base_threshold + self.config.hysteresis_db

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


def detect_silence_ffmpeg(
    media_path: Path,
    config: Optional[AnalysisConfig] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    ffmpeg_path: str = "ffmpeg",
) -> list[Cut]:
    """
    FFmpeg silencedetect filtresi ile sessizlik tespiti.

    Bu yöntem daha doğru sonuç verir çünkü FFmpeg'in kendi iç
    zamanlamasını kullanır ve trim filtresiyle tam uyumlu çalışır.

    Args:
        media_path: Video veya audio dosya yolu
        config: Analiz konfigürasyonu
        progress_callback: İlerleme callback'i
        ffmpeg_path: FFmpeg binary yolu

    Returns:
        Cut listesi (kesilecek sessiz bölgeler)
    """
    if config is None:
        config = AnalysisConfig()

    logger.info(f"Starting FFmpeg silence detection: {media_path}")

    if progress_callback:
        progress_callback(0.1)

    # FFmpeg silencedetect komutu
    # n = noise threshold (dB), d = minimum duration (seconds)
    threshold_db = config.silence_threshold_db
    min_duration = config.silence_min_duration_ms / 1000.0

    cmd = [
        ffmpeg_path,
        "-i", str(media_path),
        "-af", f"silencedetect=n={threshold_db}dB:d={min_duration}",
        "-f", "null",
        "-"
    ]

    logger.debug(f"FFmpeg command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 dakika timeout
        )
        output = result.stderr  # FFmpeg çıktısı stderr'de
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timeout")
        return []
    except Exception as e:
        logger.error(f"FFmpeg error: {e}")
        return []

    if progress_callback:
        progress_callback(0.5)

    # Çıktıyı parse et
    # Format: [silencedetect @ 0x...] silence_start: 1.234
    #         [silencedetect @ 0x...] silence_end: 5.678 | silence_duration: 4.444
    silence_start_pattern = re.compile(r"silence_start:\s*([\d.]+)")
    silence_end_pattern = re.compile(r"silence_end:\s*([\d.]+)")

    silence_starts = []
    silence_ends = []

    for line in output.split("\n"):
        start_match = silence_start_pattern.search(line)
        if start_match:
            silence_starts.append(float(start_match.group(1)))

        end_match = silence_end_pattern.search(line)
        if end_match:
            silence_ends.append(float(end_match.group(1)))

    if progress_callback:
        progress_callback(0.7)

    # Eşleşmeleri Cut'lara dönüştür
    raw_cuts = []
    for i, start in enumerate(silence_starts):
        if i < len(silence_ends):
            end = silence_ends[i]
        else:
            # Son silence devam ediyorsa, video sonuna kadar
            end = start + 10.0  # Placeholder, aşağıda düzeltilecek

        raw_cuts.append((start, end))

    if not raw_cuts:
        logger.info("No silence detected by FFmpeg")
        return []

    # Video süresini al (son silence_end'den tahmin et veya ffprobe kullan)
    total_duration = max(silence_ends) if silence_ends else 0.0

    # Padding ve merge işlemleri
    pre_pad = config.pre_pad_ms / 1000.0
    post_pad = config.post_pad_ms / 1000.0
    merge_gap = config.merge_gap_ms / 1000.0
    keep_short = config.keep_short_pauses_ms / 1000.0

    # 1. Padding uygula
    padded_cuts = []
    for start, end in raw_cuts:
        new_start = start + pre_pad
        new_end = end - post_pad

        if new_start < new_end and (new_end - new_start) >= 0.05:  # min 50ms
            padded_cuts.append((max(0, new_start), new_end))

    if progress_callback:
        progress_callback(0.8)

    # 2. Kısa pause'ları filtrele
    if keep_short > 0:
        padded_cuts = [(s, e) for s, e in padded_cuts if (e - s) >= keep_short]

    # 3. Yakın segmentleri merge et
    if padded_cuts:
        merged_cuts = [padded_cuts[0]]
        for start, end in padded_cuts[1:]:
            last_start, last_end = merged_cuts[-1]
            if start - last_end <= merge_gap:
                # Birleştir
                merged_cuts[-1] = (last_start, end)
            else:
                merged_cuts.append((start, end))
        padded_cuts = merged_cuts

    if progress_callback:
        progress_callback(0.9)

    # Cut objelerine dönüştür
    cuts = []
    for start, end in padded_cuts:
        cut = Cut(
            start=start,
            end=end,
            cut_type=CutType.SILENCE,
            enabled=True,
            source_avg_db=threshold_db,  # FFmpeg threshold değerini kullan
            source_peak_db=threshold_db,
        )
        cuts.append(cut)

    if progress_callback:
        progress_callback(1.0)

    logger.info(f"FFmpeg detected {len(cuts)} silence regions")
    return cuts
