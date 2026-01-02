"""
OpenCV-based video player widget with threaded frame reading.

Embedded video playback without Qt Multimedia (which crashes on macOS).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, List
from threading import Thread, Lock
from queue import Queue, Empty
import time

import cv2
import numpy as np

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QObject
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QFrame
from PySide6.QtGui import QImage, QPixmap

from app.core.models import Cut

logger = logging.getLogger(__name__)


class FrameReader(QObject):
    """Background thread for reading video frames."""

    frame_ready = Signal(np.ndarray, int)  # frame, frame_number

    def __init__(self):
        super().__init__()
        self._capture: Optional[cv2.VideoCapture] = None
        self._running = False
        self._thread: Optional[Thread] = None
        self._lock = Lock()
        self._seek_frame: Optional[int] = None
        self._playing = False
        self._fps = 30.0
        self._frame_count = 0
        self._current_frame = 0

    def open(self, path: str) -> bool:
        """Open video file."""
        with self._lock:
            if self._capture is not None:
                self._capture.release()

            self._capture = cv2.VideoCapture(path)
            if not self._capture.isOpened():
                return False

            self._fps = self._capture.get(cv2.CAP_PROP_FPS) or 30.0
            self._frame_count = int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT))
            self._current_frame = 0
            return True

    def start_thread(self):
        """Start the reader thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._running = True
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop_thread(self):
        """Stop the reader thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def play(self):
        """Start playback."""
        self._playing = True

    def pause(self):
        """Pause playback."""
        self._playing = False

    def seek(self, frame_num: int):
        """Request seek to frame."""
        self._seek_frame = frame_num

    def _run(self):
        """Main reader loop."""
        frame_interval = 1.0 / self._fps
        last_frame_time = 0

        while self._running:
            # Check for seek request
            with self._lock:
                if self._seek_frame is not None:
                    target = self._seek_frame
                    self._seek_frame = None
                    if self._capture is not None:
                        self._capture.set(cv2.CAP_PROP_POS_FRAMES, target)
                        ret, frame = self._capture.read()
                        if ret:
                            self._current_frame = target
                            self.frame_ready.emit(frame.copy(), target)
                    continue

            # If playing, read next frame at appropriate rate
            if self._playing:
                current_time = time.time()
                if current_time - last_frame_time >= frame_interval:
                    with self._lock:
                        if self._capture is not None:
                            ret, frame = self._capture.read()
                            if ret:
                                self._current_frame += 1
                                self.frame_ready.emit(frame.copy(), self._current_frame)
                                last_frame_time = current_time
                            else:
                                self._playing = False
            else:
                time.sleep(0.01)  # Small sleep when not playing

    def close(self):
        """Close video and stop thread."""
        self.stop_thread()
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def current_frame(self) -> int:
        return self._current_frame


class VideoPlayer(QWidget):
    """
    OpenCV-based video player widget with threaded frame reading.

    Signals:
        position_changed(float): Current position in seconds
        duration_changed(float): Video duration in seconds
        playback_started()
        playback_paused()
    """

    position_changed = Signal(float)
    duration_changed = Signal(float)
    playback_started = Signal()
    playback_paused = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._video_path: Optional[Path] = None
        self._frame_reader = FrameReader()
        self._frame_reader.frame_ready.connect(self._on_frame_ready)

        self._duration: float = 0.0
        self._is_playing: bool = False
        self._cuts: List[Cut] = []
        self._skip_cuts: bool = True
        self._slider_pressed = False

        self._setup_ui()

    def _setup_ui(self):
        """Setup UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Video display
        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignCenter)
        self._video_label.setMinimumHeight(200)
        self._video_label.setStyleSheet("background-color: #000000; border-radius: 4px;")
        self._video_label.setText("Video yüklemek için 'Video İçe Aktar' butonuna tıklayın")
        layout.addWidget(self._video_label, 1)

        # Controls frame
        controls = QFrame()
        controls.setStyleSheet("background-color: #222222; border-radius: 4px; padding: 4px;")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(8, 4, 8, 4)
        controls_layout.setSpacing(4)

        # Seek slider
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setValue(0)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        controls_layout.addWidget(self._seek_slider)

        # Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        # Time label
        self._time_label = QLabel("00:00:00 / 00:00:00")
        self._time_label.setStyleSheet("color: #ffffff; font-family: monospace; font-size: 12px;")
        self._time_label.setFixedWidth(150)
        btn_layout.addWidget(self._time_label)

        # Play button
        self._play_btn = QPushButton("▶ Oynat")
        self._play_btn.setFixedWidth(100)
        self._play_btn.clicked.connect(self.toggle_playback)
        btn_layout.addWidget(self._play_btn)

        # Stop button
        self._stop_btn = QPushButton("⏹ Durdur")
        self._stop_btn.setFixedWidth(80)
        self._stop_btn.clicked.connect(self.stop)
        btn_layout.addWidget(self._stop_btn)

        # Skip cuts checkbox
        self._skip_cuts_btn = QPushButton("✂ Kesimleri Atla: AÇIK")
        self._skip_cuts_btn.setCheckable(True)
        self._skip_cuts_btn.setChecked(True)
        self._skip_cuts_btn.clicked.connect(self._toggle_skip_cuts)
        btn_layout.addWidget(self._skip_cuts_btn)

        btn_layout.addStretch()

        controls_layout.addLayout(btn_layout)
        layout.addWidget(controls)

    def load_video(self, path: Path) -> bool:
        """Load a video file."""
        self.stop()
        self._frame_reader.close()

        self._video_path = path

        if not self._frame_reader.open(str(path)):
            logger.error(f"Failed to open video: {path}")
            self._video_label.setText(f"Video açılamadı: {path.name}")
            return False

        self._duration = self._frame_reader.frame_count / self._frame_reader.fps

        logger.info(f"Loaded video: {path.name}, {self._frame_reader.fps:.2f} fps, "
                   f"{self._duration:.2f}s, {self._frame_reader.frame_count} frames")

        self.duration_changed.emit(self._duration)
        self._update_time_label()

        # Start frame reader thread
        self._frame_reader.start_thread()

        # Show first frame
        self._frame_reader.seek(0)

        return True

    def set_cuts(self, cuts: List[Cut]):
        """Set the list of cuts to skip during playback."""
        self._cuts = cuts
        logger.info(f"Video player received {len(cuts)} cuts")

    def _toggle_skip_cuts(self):
        """Toggle cut skipping."""
        self._skip_cuts = self._skip_cuts_btn.isChecked()
        if self._skip_cuts:
            self._skip_cuts_btn.setText("✂ Kesimleri Atla: AÇIK")
        else:
            self._skip_cuts_btn.setText("✂ Kesimleri Atla: KAPALI")

    def play(self):
        """Start playback."""
        if self._frame_reader.frame_count == 0:
            return

        self._is_playing = True
        self._frame_reader.play()
        self._play_btn.setText("⏸ Duraklat")
        self.playback_started.emit()

    def pause(self):
        """Pause playback."""
        self._is_playing = False
        self._frame_reader.pause()
        self._play_btn.setText("▶ Oynat")
        self.playback_paused.emit()

    def toggle_playback(self):
        """Toggle play/pause."""
        if self._is_playing:
            self.pause()
        else:
            self.play()

    def stop(self):
        """Stop playback and reset to beginning."""
        self.pause()
        self.seek(0)

    def seek(self, time_sec: float):
        """Seek to a specific time in seconds."""
        if self._frame_reader.frame_count == 0:
            return

        frame = int(time_sec * self._frame_reader.fps)
        frame = max(0, min(frame, self._frame_reader.frame_count - 1))
        self._frame_reader.seek(frame)

    @Slot(np.ndarray, int)
    def _on_frame_ready(self, frame: np.ndarray, frame_num: int):
        """Handle frame from reader thread."""
        # Check if we need to skip a cut region
        if self._is_playing and self._skip_cuts and self._cuts:
            current_time = frame_num / self._frame_reader.fps
            for cut in self._cuts:
                if cut.enabled and cut.start <= current_time < cut.end:
                    # Skip to end of cut
                    skip_frame = int(cut.end * self._frame_reader.fps) + 1
                    logger.debug(f"Skipping cut: {cut.start:.2f}s - {cut.end:.2f}s")
                    self._frame_reader.seek(skip_frame)
                    return

        # Display the frame
        self._display_frame(frame)
        self._update_time_label_for_frame(frame_num)

        if not self._slider_pressed:
            self._update_slider(frame_num)

        current_time = frame_num / self._frame_reader.fps
        self.position_changed.emit(current_time)

        # Check if reached end
        if frame_num >= self._frame_reader.frame_count - 1:
            self.pause()

    def _display_frame(self, frame: np.ndarray):
        """Convert and display a frame."""
        try:
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w

            # Create QImage
            q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

            # Scale to fit label while maintaining aspect ratio
            label_size = self._video_label.size()
            pixmap = QPixmap.fromImage(q_img)
            scaled_pixmap = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

            self._video_label.setPixmap(scaled_pixmap)
        except Exception as e:
            logger.error(f"Error displaying frame: {e}")

    def _update_time_label(self):
        """Update the time display."""
        current = self._frame_reader.current_frame / self._frame_reader.fps if self._frame_reader.fps > 0 else 0
        total = self._duration

        current_str = self._format_time(current)
        total_str = self._format_time(total)

        self._time_label.setText(f"{current_str} / {total_str}")

    def _update_time_label_for_frame(self, frame_num: int):
        """Update time label for specific frame."""
        current = frame_num / self._frame_reader.fps if self._frame_reader.fps > 0 else 0
        total = self._duration

        current_str = self._format_time(current)
        total_str = self._format_time(total)

        self._time_label.setText(f"{current_str} / {total_str}")

    def _format_time(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _update_slider(self, frame_num: int):
        """Update slider position."""
        if self._frame_reader.frame_count > 0:
            pos = int((frame_num / self._frame_reader.frame_count) * 1000)
            self._seek_slider.blockSignals(True)
            self._seek_slider.setValue(pos)
            self._seek_slider.blockSignals(False)

    def _on_slider_pressed(self):
        """Slider pressed - pause updates."""
        self._slider_pressed = True
        self._was_playing = self._is_playing
        if self._is_playing:
            self._frame_reader.pause()

    def _on_slider_released(self):
        """Slider released - resume if was playing."""
        self._slider_pressed = False
        if hasattr(self, '_was_playing') and self._was_playing:
            self._frame_reader.play()

    def _on_slider_moved(self, value: int):
        """Slider moved - seek to position."""
        if self._frame_reader.frame_count > 0:
            frame = int((value / 1000) * self._frame_reader.frame_count)
            self._frame_reader.seek(frame)

    @property
    def duration(self) -> float:
        """Get video duration in seconds."""
        return self._duration

    @property
    def current_time(self) -> float:
        """Get current playback time in seconds."""
        return self._frame_reader.current_frame / self._frame_reader.fps if self._frame_reader.fps > 0 else 0

    @property
    def is_playing(self) -> bool:
        """Check if video is currently playing."""
        return self._is_playing

    def closeEvent(self, event):
        """Clean up on close."""
        self.stop()
        self._frame_reader.close()
        super().closeEvent(event)
