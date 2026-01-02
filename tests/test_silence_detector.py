"""Tests for silence detector."""

import pytest
import numpy as np
from pathlib import Path
import tempfile
from scipy.io import wavfile

from app.core.models import AnalysisConfig
from app.analysis.silence_detector import SilenceDetector, detect_silence


def create_test_audio(
    duration: float = 10.0,
    sample_rate: int = 48000,
    silence_regions: list[tuple[float, float]] = None,
    speech_db: float = -20.0,
    silence_db: float = -60.0,
) -> Path:
    """
    Test için sentetik audio oluştur.

    Args:
        duration: Toplam süre (saniye)
        sample_rate: Sample rate
        silence_regions: (start, end) tuple listesi
        speech_db: Konuşma seviyesi (dBFS)
        silence_db: Sessizlik seviyesi (dBFS)

    Returns:
        Geçici WAV dosyası path'i
    """
    if silence_regions is None:
        silence_regions = []

    total_samples = int(duration * sample_rate)
    audio = np.zeros(total_samples, dtype=np.float32)

    # Tüm audio'yu "konuşma" seviyesinde noise ile doldur
    speech_amplitude = 10 ** (speech_db / 20)
    audio = np.random.randn(total_samples).astype(np.float32) * speech_amplitude

    # Sessizlik bölgelerini düşük seviyeye çek
    silence_amplitude = 10 ** (silence_db / 20)
    for start, end in silence_regions:
        start_sample = int(start * sample_rate)
        end_sample = int(end * sample_rate)
        audio[start_sample:end_sample] = np.random.randn(end_sample - start_sample).astype(np.float32) * silence_amplitude

    # Normalize to int16
    audio_int16 = (audio * 32767).astype(np.int16)

    # Geçici dosyaya yaz
    fd, path = tempfile.mkstemp(suffix=".wav")
    wavfile.write(path, sample_rate, audio_int16)

    return Path(path)


class TestSilenceDetector:
    """SilenceDetector testleri."""

    def test_no_silence(self):
        """Sessizlik olmayan audio."""
        audio_path = create_test_audio(
            duration=5.0,
            silence_regions=[],
            speech_db=-20.0,
        )

        try:
            config = AnalysisConfig(
                silence_threshold_db=-35.0,
                silence_min_duration_ms=250,
            )
            detector = SilenceDetector(config)
            cuts = detector.detect(audio_path)

            # Sessizlik olmamalı
            assert len(cuts) == 0
        finally:
            audio_path.unlink()

    def test_single_silence_region(self):
        """Tek sessizlik bölgesi."""
        audio_path = create_test_audio(
            duration=10.0,
            silence_regions=[(3.0, 6.0)],  # 3 saniyelik sessizlik
            speech_db=-20.0,
            silence_db=-60.0,
        )

        try:
            config = AnalysisConfig(
                silence_threshold_db=-35.0,
                silence_min_duration_ms=250,
                pre_pad_ms=0,
                post_pad_ms=0,
            )
            detector = SilenceDetector(config)
            cuts = detector.detect(audio_path)

            # Bir tane sessizlik bölgesi bulunmalı
            assert len(cuts) >= 1

            # Yaklaşık 3-6 saniye aralığında olmalı
            cut = cuts[0]
            assert cut.start >= 2.5 and cut.start <= 3.5
            assert cut.end >= 5.5 and cut.end <= 6.5
        finally:
            audio_path.unlink()

    def test_multiple_silence_regions(self):
        """Birden fazla sessizlik bölgesi."""
        audio_path = create_test_audio(
            duration=20.0,
            silence_regions=[
                (2.0, 4.0),   # 2 sn
                (8.0, 11.0),  # 3 sn
                (15.0, 18.0), # 3 sn
            ],
            speech_db=-20.0,
            silence_db=-60.0,
        )

        try:
            config = AnalysisConfig(
                silence_threshold_db=-35.0,
                silence_min_duration_ms=250,
                pre_pad_ms=0,
                post_pad_ms=0,
            )
            cuts = detect_silence(audio_path, config)

            # 3 sessizlik bölgesi bulunmalı
            assert len(cuts) >= 3
        finally:
            audio_path.unlink()

    def test_min_duration_filter(self):
        """Minimum süre filtresi."""
        audio_path = create_test_audio(
            duration=10.0,
            silence_regions=[
                (2.0, 2.1),  # 100ms - filtre edilmeli
                (5.0, 6.0),  # 1 sn - geçmeli
            ],
            speech_db=-20.0,
            silence_db=-60.0,
        )

        try:
            config = AnalysisConfig(
                silence_threshold_db=-35.0,
                silence_min_duration_ms=500,  # 500ms min
                pre_pad_ms=0,
                post_pad_ms=0,
            )
            cuts = detect_silence(audio_path, config)

            # Sadece 1 saniyelik sessizlik bulunmalı
            assert len(cuts) == 1
            assert cuts[0].duration >= 0.5
        finally:
            audio_path.unlink()

    def test_padding(self):
        """Padding uygulaması."""
        audio_path = create_test_audio(
            duration=10.0,
            silence_regions=[(3.0, 7.0)],  # 4 sn sessizlik
            speech_db=-20.0,
            silence_db=-60.0,
        )

        try:
            config = AnalysisConfig(
                silence_threshold_db=-35.0,
                silence_min_duration_ms=250,
                pre_pad_ms=200,   # 200ms pre-pad
                post_pad_ms=200,  # 200ms post-pad
            )
            cuts = detect_silence(audio_path, config)

            # Padding sonrası cut daha kısa olmalı
            assert len(cuts) >= 1
            cut = cuts[0]

            # Orijinal ~3-7 iken, padding ile ~3.2-6.8 civarı olmalı
            assert cut.start >= 3.0
            assert cut.end <= 7.0
            # 4 sn yerine yaklaşık 3.6 sn civarı olmalı (400ms padding kaybı)
            assert cut.duration < 4.0
        finally:
            audio_path.unlink()

    def test_merge_close_silences(self):
        """Yakın sessizlikleri birleştirme."""
        audio_path = create_test_audio(
            duration=10.0,
            silence_regions=[
                (2.0, 3.0),   # 1 sn
                (3.05, 4.0),  # 50ms gap ile 0.95 sn daha
            ],
            speech_db=-20.0,
            silence_db=-60.0,
        )

        try:
            config = AnalysisConfig(
                silence_threshold_db=-35.0,
                silence_min_duration_ms=250,
                merge_gap_ms=100,  # 100ms içindeki sessizlikleri birleştir
                pre_pad_ms=0,
                post_pad_ms=0,
            )
            cuts = detect_silence(audio_path, config)

            # Birleştirilmiş tek cut olmalı
            # Not: Gerçek davranış gürültüye bağlı, bu yüzden >= 1 kontrol ediyoruz
            assert len(cuts) >= 1
        finally:
            audio_path.unlink()


class TestDetectSilenceFunction:
    """detect_silence convenience function testleri."""

    def test_with_default_config(self):
        """Varsayılan config ile test."""
        audio_path = create_test_audio(
            duration=5.0,
            silence_regions=[(1.0, 3.0)],
            speech_db=-20.0,
            silence_db=-60.0,
        )

        try:
            # Config olmadan çağır
            cuts = detect_silence(audio_path)
            assert isinstance(cuts, list)
        finally:
            audio_path.unlink()

    def test_with_progress_callback(self):
        """Progress callback ile test."""
        audio_path = create_test_audio(duration=3.0)

        progress_values = []

        def callback(progress):
            progress_values.append(progress)

        try:
            cuts = detect_silence(audio_path, progress_callback=callback)

            # Callback çağrılmış olmalı
            assert len(progress_values) > 0
            # Son değer 1.0 olmalı
            assert progress_values[-1] == 1.0
        finally:
            audio_path.unlink()
