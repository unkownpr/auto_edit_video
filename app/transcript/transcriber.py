"""
Audio transcription using Whisper or Gemini.

Supports:
- faster-whisper (recommended, CPU/GPU)
- openai-whisper (GPU)
- Gemini API (cloud-based)

Features:
- Segment-level timestamps
- Word-level timestamps (optional)
- Language detection
- Multiple model sizes
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
import base64
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, Literal
from enum import Enum
import logging

from app.core.models import TranscriptSegment, TranscriptWord

logger = logging.getLogger(__name__)


def get_model_cache_path(model_name: str) -> Path:
    """Get the cache path for a whisper model."""
    from pathlib import Path
    import os

    # faster-whisper uses huggingface hub cache
    cache_dir = Path(os.environ.get(
        "HF_HOME",
        Path.home() / ".cache" / "huggingface" / "hub"
    ))
    return cache_dir


def is_model_downloaded(model_name: str) -> bool:
    """Check if a whisper model is already downloaded."""
    try:
        from pathlib import Path
        import os

        # faster-whisper model names map to huggingface repo names
        model_map = {
            "tiny": "Systran/faster-whisper-tiny",
            "base": "Systran/faster-whisper-base",
            "small": "Systran/faster-whisper-small",
            "medium": "Systran/faster-whisper-medium",
            "large-v3": "Systran/faster-whisper-large-v3",
            "large": "Systran/faster-whisper-large-v3",
        }

        repo_name = model_map.get(model_name, f"Systran/faster-whisper-{model_name}")
        repo_id = repo_name.replace("/", "--")

        # Check huggingface cache directory
        cache_dir = Path(os.environ.get(
            "HF_HOME",
            Path.home() / ".cache" / "huggingface" / "hub"
        ))

        model_dir = cache_dir / f"models--{repo_id}"

        if model_dir.exists():
            # Check if model files are present (not just the directory)
            snapshots_dir = model_dir / "snapshots"
            if snapshots_dir.exists():
                for snapshot in snapshots_dir.iterdir():
                    if snapshot.is_dir():
                        # Check for model.bin or other model files
                        model_files = list(snapshot.glob("*.bin")) + list(snapshot.glob("*.safetensors"))
                        if model_files:
                            return True
        return False
    except Exception as e:
        logger.debug(f"Error checking model {model_name}: {e}")
        return False


def get_downloaded_models() -> list[str]:
    """Get list of downloaded model names."""
    models = ["tiny", "base", "small", "medium", "large-v3"]
    return [m for m in models if is_model_downloaded(m)]


class TranscriptBackend(Enum):
    """Transkript backend seçenekleri."""
    FASTER_WHISPER = "faster-whisper"
    OPENAI_WHISPER = "openai-whisper"


class ModelSize(Enum):
    """Whisper model boyutları."""
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large-v3"


@dataclass
class TranscriptConfig:
    """Transkript konfigürasyonu."""
    backend: TranscriptBackend = TranscriptBackend.FASTER_WHISPER
    model_size: ModelSize = ModelSize.BASE  # Changed from MEDIUM for speed
    language: Optional[str] = None  # None = auto-detect
    word_timestamps: bool = False  # Disabled by default for speed
    device: str = "auto"  # auto, cpu, cuda
    compute_type: str = "auto"  # auto, int8, float16, float32

    # VAD filter - helps speed by skipping silent parts
    vad_filter: bool = True
    vad_min_silence_duration_ms: int = 300  # Reduced for faster processing

    # Output
    include_word_timestamps: bool = False  # Disabled for speed

    # Performance options
    beam_size: int = 1  # 1 = greedy (fastest), 5 = default beam search
    best_of: int = 1  # Number of candidates (1 = fastest)
    num_workers: int = 4  # Parallel workers for faster-whisper


class Transcriber:
    """
    Audio transkript motoru.

    Usage:
        transcriber = Transcriber(config)
        segments = transcriber.transcribe(audio_path, progress_callback)
    """

    def __init__(self, config: Optional[TranscriptConfig] = None):
        self.config = config or TranscriptConfig()
        self._model = None
        self._backend_module = None

    def _load_model(self):
        """Model'i yükle (lazy loading)."""
        if self._model is not None:
            return

        if self.config.backend == TranscriptBackend.FASTER_WHISPER:
            self._load_faster_whisper()
        else:
            self._load_openai_whisper()

    def _load_faster_whisper(self):
        """faster-whisper model'ini yükle."""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper not installed. "
                "Install with: pip install faster-whisper"
            )

        # Device seçimi
        device = self.config.device
        compute_type = self.config.compute_type

        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        logger.info(f"Loading faster-whisper model: {self.config.model_size.value} "
                   f"on {device} with {compute_type}")

        self._model = WhisperModel(
            self.config.model_size.value,
            device=device,
            compute_type=compute_type,
        )
        self._backend_module = "faster_whisper"

    def _load_openai_whisper(self):
        """openai-whisper model'ini yükle."""
        try:
            import whisper
        except ImportError:
            raise ImportError(
                "openai-whisper not installed. "
                "Install with: pip install openai-whisper"
            )

        device = self.config.device
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        logger.info(f"Loading openai-whisper model: {self.config.model_size.value} on {device}")

        self._model = whisper.load_model(self.config.model_size.value, device=device)
        self._backend_module = "openai_whisper"

    def transcribe(
        self,
        audio_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[TranscriptSegment]:
        """
        Audio dosyasını transkript et.

        Args:
            audio_path: WAV dosya yolu
            progress_callback: İlerleme callback'i (0-100, message)

        Returns:
            TranscriptSegment listesi
        """
        self._load_model()

        if progress_callback:
            progress_callback(10, "Model loaded, starting transcription...")

        if self._backend_module == "faster_whisper":
            return self._transcribe_faster_whisper(audio_path, progress_callback)
        else:
            return self._transcribe_openai_whisper(audio_path, progress_callback)

    def _transcribe_faster_whisper(
        self,
        audio_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[TranscriptSegment]:
        """faster-whisper ile transkript."""
        segments_iter, info = self._model.transcribe(
            str(audio_path),
            language=self.config.language,
            word_timestamps=self.config.word_timestamps,
            vad_filter=self.config.vad_filter,
            vad_parameters={
                "min_silence_duration_ms": self.config.vad_min_silence_duration_ms,
            },
            beam_size=self.config.beam_size,
            best_of=self.config.best_of,
            without_timestamps=False,
            condition_on_previous_text=False,  # Faster, less context
        )

        detected_language = info.language
        logger.info(f"Detected language: {detected_language} "
                   f"(probability: {info.language_probability:.2f})")

        if progress_callback:
            progress_callback(20, f"Language: {detected_language}")

        result = []
        total_duration = info.duration
        processed_time = 0

        for segment in segments_iter:
            # Word-level timestamps
            words = []
            if self.config.include_word_timestamps and segment.words:
                for word in segment.words:
                    words.append(TranscriptWord(
                        text=word.word.strip(),
                        start=word.start,
                        end=word.end,
                        confidence=word.probability,
                    ))

            transcript_segment = TranscriptSegment(
                text=segment.text.strip(),
                start=segment.start,
                end=segment.end,
                language=detected_language,
                words=words,
            )
            result.append(transcript_segment)

            # Progress
            processed_time = segment.end
            if progress_callback and total_duration > 0:
                progress = 20 + (processed_time / total_duration) * 75
                progress_callback(progress, f"Transcribing... {processed_time:.1f}s")

        if progress_callback:
            progress_callback(100, "Transcription complete")

        logger.info(f"Transcribed {len(result)} segments")
        return result

    def _transcribe_openai_whisper(
        self,
        audio_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[TranscriptSegment]:
        """openai-whisper ile transkript."""
        import whisper

        if progress_callback:
            progress_callback(20, "Transcribing with OpenAI Whisper...")

        # Transkript
        result = self._model.transcribe(
            str(audio_path),
            language=self.config.language,
            word_timestamps=self.config.word_timestamps,
            verbose=False,
        )

        detected_language = result.get("language", "en")

        if progress_callback:
            progress_callback(80, "Processing segments...")

        segments = []
        for segment_data in result.get("segments", []):
            words = []
            if self.config.include_word_timestamps and "words" in segment_data:
                for word_data in segment_data["words"]:
                    words.append(TranscriptWord(
                        text=word_data.get("word", "").strip(),
                        start=word_data.get("start", 0),
                        end=word_data.get("end", 0),
                        confidence=word_data.get("probability", 1.0),
                    ))

            segment = TranscriptSegment(
                text=segment_data.get("text", "").strip(),
                start=segment_data.get("start", 0),
                end=segment_data.get("end", 0),
                language=detected_language,
                words=words,
            )
            segments.append(segment)

        if progress_callback:
            progress_callback(100, "Transcription complete")

        logger.info(f"Transcribed {len(segments)} segments")
        return segments

    def detect_language(self, audio_path: Path) -> tuple[str, float]:
        """
        Dil tespiti yap.

        Returns:
            (language_code, confidence)
        """
        self._load_model()

        if self._backend_module == "faster_whisper":
            # İlk 30 saniye ile dil tespiti
            _, info = self._model.transcribe(
                str(audio_path),
                language=None,
                task="transcribe",
            )
            return info.language, info.language_probability
        else:
            import whisper
            # openai-whisper için ayrı dil tespiti
            audio = whisper.load_audio(str(audio_path))
            audio = whisper.pad_or_trim(audio)
            mel = whisper.log_mel_spectrogram(audio).to(self._model.device)
            _, probs = self._model.detect_language(mel)
            detected = max(probs, key=probs.get)
            return detected, probs[detected]


def transcribe_audio(
    audio_path: Path,
    config: Optional[TranscriptConfig] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[TranscriptSegment]:
    """
    Convenience function for transcription.

    Args:
        audio_path: Audio dosya yolu
        config: Transkript konfigürasyonu
        progress_callback: İlerleme callback'i

    Returns:
        TranscriptSegment listesi
    """
    transcriber = Transcriber(config)
    return transcriber.transcribe(audio_path, progress_callback)


# =============================================================================
# Gemini Transcriber
# =============================================================================

@dataclass
class GeminiConfig:
    """Gemini transcription configuration."""
    api_key: str
    model: str = "gemini-2.0-flash-exp"
    language: Optional[str] = None  # None = auto-detect


class GeminiTranscriber:
    """
    Gemini API kullanarak audio transcription.

    Usage:
        transcriber = GeminiTranscriber(api_key, model)
        segments = transcriber.transcribe(audio_path, progress_callback)
    """

    def __init__(self, config: GeminiConfig):
        self.config = config

    def transcribe(
        self,
        audio_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[TranscriptSegment]:
        """
        Audio dosyasını Gemini ile transkript et.

        Args:
            audio_path: Audio dosya yolu (WAV, MP3, etc.)
            progress_callback: İlerleme callback'i

        Returns:
            TranscriptSegment listesi
        """
        if progress_callback:
            progress_callback(10, "Preparing audio for Gemini...")

        # Read and encode audio file
        audio_data = audio_path.read_bytes()
        audio_base64 = base64.standard_b64encode(audio_data).decode('utf-8')

        # Determine MIME type
        suffix = audio_path.suffix.lower()
        mime_types = {
            '.wav': 'audio/wav',
            '.mp3': 'audio/mp3',
            '.m4a': 'audio/mp4',
            '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',
            '.flac': 'audio/flac',
        }
        mime_type = mime_types.get(suffix, 'audio/wav')

        if progress_callback:
            progress_callback(20, "Sending to Gemini API...")

        # Prepare the prompt for transcription with timestamps
        language_hint = f" The audio is in {self.config.language}." if self.config.language else ""
        prompt = f"""Transcribe this audio file accurately.{language_hint}

Return the transcription in JSON format with timestamps:
{{
  "language": "detected language code (e.g., en, tr)",
  "segments": [
    {{"start": 0.0, "end": 2.5, "text": "First sentence here."}},
    {{"start": 2.5, "end": 5.0, "text": "Second sentence here."}}
  ]
}}

Rules:
- Use accurate timestamps in seconds
- Each segment should be a complete sentence or phrase
- Preserve the original language
- Include punctuation
- Return ONLY the JSON, no other text"""

        # Build API request
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:generateContent?key={self.config.api_key}"

        request_data = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": audio_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for accurate transcription
                "maxOutputTokens": 8192,
            }
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(request_data).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            if progress_callback:
                progress_callback(40, "Waiting for Gemini response...")

            with urllib.request.urlopen(req, timeout=300) as response:
                result = json.loads(response.read().decode('utf-8'))

            if progress_callback:
                progress_callback(80, "Processing transcription...")

            # Extract text from response
            if "candidates" not in result or not result["candidates"]:
                raise ValueError("No response from Gemini API")

            response_text = result["candidates"][0]["content"]["parts"][0]["text"]

            # Parse JSON from response
            segments = self._parse_response(response_text)

            if progress_callback:
                progress_callback(100, "Transcription complete")

            logger.info(f"Gemini transcribed {len(segments)} segments")
            return segments

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            logger.error(f"Gemini API error: {e.code} - {error_body}")
            raise RuntimeError(f"Gemini API error: {e.code}")

        except Exception as e:
            logger.error(f"Gemini transcription error: {e}")
            raise

    def _parse_response(self, response_text: str) -> list[TranscriptSegment]:
        """Parse Gemini response to TranscriptSegment list."""
        logger.debug(f"Parsing Gemini response, length: {len(response_text)}")

        json_text = response_text.strip()

        # Method 1: Extract content from markdown code blocks
        if '```' in json_text:
            lines = json_text.split('\n')
            cleaned_lines = []
            in_code_block = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('```'):
                    in_code_block = not in_code_block
                    continue  # Skip the ``` lines themselves
                if in_code_block:
                    cleaned_lines.append(line)  # Keep lines inside code block
            if cleaned_lines:
                json_text = '\n'.join(cleaned_lines).strip()
            logger.debug(f"After code block removal: {json_text[:200]}...")

        # Method 2: Find JSON object boundaries
        brace_start = json_text.find('{')
        if brace_start != -1:
            # Find matching closing brace
            depth = 0
            brace_end = -1
            for i, char in enumerate(json_text[brace_start:], brace_start):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        brace_end = i
                        break

            if brace_end > brace_start:
                json_text = json_text[brace_start:brace_end + 1]

        logger.debug(f"Cleaned JSON text starts with: {json_text[:100]}...")

        try:
            data = json.loads(json_text)
            logger.debug(f"Successfully parsed JSON with {len(data.get('segments', []))} segments")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            logger.error(f"JSON text was: {json_text[:500]}...")
            # Return single segment with cleaned text (without JSON/code blocks)
            clean_text = response_text.replace('```json', '').replace('```', '').strip()
            return [TranscriptSegment(
                text=clean_text,
                start=0.0,
                end=0.0,
                language="unknown",
            )]

        language = data.get("language", "unknown")
        segments = []

        for seg_data in data.get("segments", []):
            text = seg_data.get("text", "").strip()
            if text:  # Only add segments with text
                segment = TranscriptSegment(
                    text=text,
                    start=float(seg_data.get("start", 0)),
                    end=float(seg_data.get("end", 0)),
                    language=language,
                )
                segments.append(segment)

        logger.info(f"Parsed {len(segments)} transcript segments")
        return segments


def transcribe_with_gemini(
    audio_path: Path,
    api_key: str,
    model: str = "gemini-2.0-flash-exp",
    language: Optional[str] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[TranscriptSegment]:
    """
    Convenience function for Gemini transcription.

    Args:
        audio_path: Audio dosya yolu
        api_key: Gemini API key
        model: Gemini model name
        language: Language hint (optional)
        progress_callback: İlerleme callback'i

    Returns:
        TranscriptSegment listesi
    """
    config = GeminiConfig(api_key=api_key, model=model, language=language)
    transcriber = GeminiTranscriber(config)
    return transcriber.transcribe(audio_path, progress_callback)
