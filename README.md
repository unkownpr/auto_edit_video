# AutoCut

Automatic silence removal tool with NLE export support.

## Features

- **Silence Detection**: Automatically detect silent regions in video/audio files
- **Waveform Timeline**: Visual timeline with waveform display and cut overlays
- **Multiple Export Formats**: Export to FCPXML (Final Cut Pro), EDL, Premiere XML
- **Transcription**: Optional Whisper-based transcription support
- **Multi-language**: Turkish and English UI support
- **Configurable**: Adjustable thresholds, padding, and merge settings

## Requirements

- Python 3.10+
- FFmpeg (must be installed and in PATH)
- PySide6

## Installation

```bash
# Clone the repository
git clone https://github.com/unkownpr/auto_edit_video.git
cd auto_edit_video

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Usage

1. Click "Import Video" to load a video file
2. Adjust silence detection settings (threshold, min duration, padding)
3. Click "Analyze" to detect silent regions
4. Review detected cuts in the timeline and cuts list
5. Toggle individual cuts on/off as needed
6. Export to your preferred NLE format

## Presets

- **Podcast**: Optimized for podcast editing
- **Tutorial**: Balanced settings for tutorial videos
- **Meeting**: Conservative settings for meeting recordings
- **Noisy Room**: Higher threshold for noisy environments
- **Aggressive**: Maximum silence removal

## Building

```bash
# Install build dependencies
pip install pyinstaller

# Build executable
python build.py
```

## License

MIT License
