"""
Timeline widget with video thumbnails, waveform display and cut overlays.

Final Cut Pro / Adobe Premiere style timeline:
- Video thumbnails track
- Audio waveform track
- Cut region overlays
- Playhead
- Zoom/pan
"""

from __future__ import annotations

from typing import Optional, List
from pathlib import Path
import logging
import cv2
import numpy as np

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer, QThread, QObject, Slot
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QWidget,
    QVBoxLayout,
)
from PySide6.QtGui import (
    QPainter,
    QPen,
    QBrush,
    QColor,
    QPainterPath,
    QLinearGradient,
    QFont,
    QPixmap,
    QImage,
)

from app.core.models import Cut, CutType
from app.media.waveform import WaveformData

logger = logging.getLogger(__name__)


# Colors - Final Cut Pro style
COLOR_BACKGROUND = QColor("#1a1a1a")
COLOR_TRACK_BG = QColor("#2a2a2a")
COLOR_WAVEFORM = QColor("#4a90d9")  # Blue like FCP
COLOR_WAVEFORM_FILL = QColor("#4a90d980")
COLOR_SILENCE = QColor("#ff4444")
COLOR_SILENCE_ALPHA = QColor(255, 68, 68, 100)
COLOR_PLAYHEAD = QColor("#ff6b00")  # Orange playhead like FCP
COLOR_RULER = QColor("#666666")
COLOR_RULER_TEXT = QColor("#aaaaaa")
COLOR_TRACK_BORDER = QColor("#444444")

# Track heights
RULER_HEIGHT = 25
VIDEO_TRACK_HEIGHT = 60
AUDIO_TRACK_HEIGHT = 80
TOTAL_HEIGHT = RULER_HEIGHT + VIDEO_TRACK_HEIGHT + AUDIO_TRACK_HEIGHT


class VideoThumbnailItem(QGraphicsItem):
    """Video thumbnails track."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration: float = 0.0
        self.pixels_per_second: float = 100.0
        self.height: float = VIDEO_TRACK_HEIGHT
        self.thumbnails: List[tuple] = []  # [(time, QPixmap), ...]
        self._video_path: Optional[Path] = None
        self._extraction_pending: bool = False

    def set_video(self, video_path: Path, duration: float):
        """Set video for later thumbnail extraction."""
        self._video_path = video_path
        self.duration = duration
        self._extraction_pending = True
        self.prepareGeometryChange()
        self.update()

    def extract_thumbnails_safe(self):
        """Extract thumbnails safely (call from timer/delayed)."""
        if not self._extraction_pending:
            return
        self._extraction_pending = False

        if not self._video_path or not self._video_path.exists():
            return

        self.thumbnails = []
        cap = None

        try:
            cap = cv2.VideoCapture(str(self._video_path))

            if not cap.isOpened():
                logger.warning(f"Could not open video for thumbnails: {self._video_path}")
                return

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count <= 0:
                return

            duration = frame_count / fps

            # Extract thumbnails - fewer to be safer
            num_thumbnails = min(20, max(5, int(duration / 10)))  # One every ~10 seconds
            interval = duration / num_thumbnails

            thumb_height = int(self.height - 4)
            thumb_width = int(thumb_height * 16 / 9)  # Assume 16:9 aspect

            for i in range(num_thumbnails):
                time_sec = i * interval
                frame_num = int(time_sec * fps)

                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()

                if ret and frame is not None:
                    try:
                        # Resize frame
                        frame_resized = cv2.resize(frame, (thumb_width, thumb_height))
                        frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                        frame_rgb = np.ascontiguousarray(frame_rgb)

                        h, w, ch = frame_rgb.shape
                        q_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
                        pixmap = QPixmap.fromImage(q_img)

                        self.thumbnails.append((time_sec, pixmap))
                    except Exception as e:
                        logger.warning(f"Error processing thumbnail {i}: {e}")
                        continue

            logger.info(f"Extracted {len(self.thumbnails)} thumbnails")

        except Exception as e:
            logger.error(f"Error extracting thumbnails: {e}")
        finally:
            if cap is not None:
                cap.release()

        self.prepareGeometryChange()
        self.update()

    def set_scale(self, pixels_per_second: float):
        """Update zoom level."""
        self.pixels_per_second = pixels_per_second
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QRectF:
        width = self.duration * self.pixels_per_second
        return QRectF(0, 0, max(width, 100), self.height)

    def paint(self, painter: QPainter, option, widget):
        rect = self.boundingRect()

        # Track background
        painter.fillRect(rect, QBrush(COLOR_TRACK_BG))

        # Draw thumbnails
        if self.thumbnails:
            thumb_width = self.thumbnails[0][1].width() if self.thumbnails else 80

            # Calculate visible area
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view:
                visible_rect = view.mapToScene(view.viewport().rect()).boundingRect()
                start_x = max(0, visible_rect.left())
                end_x = min(rect.width(), visible_rect.right())
            else:
                start_x = 0
                end_x = rect.width()

            for time_sec, pixmap in self.thumbnails:
                x = time_sec * self.pixels_per_second
                if x + thumb_width < start_x or x > end_x:
                    continue  # Skip if not visible

                painter.drawPixmap(int(x), 2, pixmap)

        # Border
        painter.setPen(QPen(COLOR_TRACK_BORDER, 1))
        painter.drawRect(rect)

        # Track label
        painter.setPen(QPen(QColor("#888888")))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(5, 14, "V1")


class WaveformItem(QGraphicsItem):
    """Audio waveform track - Final Cut Pro style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.waveform_data: Optional[WaveformData] = None
        self.pixels_per_second: float = 100.0
        self.height: float = AUDIO_TRACK_HEIGHT

    def set_waveform(self, data: WaveformData):
        """Set waveform data."""
        logger.info(f"WaveformItem.set_waveform called, duration={data.duration if data else 'None'}")
        self.waveform_data = data
        if data:
            self.prepareGeometryChange()
            # Defer update to avoid immediate repaint issues
            QTimer.singleShot(0, self.update)

    def set_scale(self, pixels_per_second: float):
        """Update zoom level."""
        if self.pixels_per_second != pixels_per_second:
            self.pixels_per_second = pixels_per_second
            self.prepareGeometryChange()
            self.update()

    def boundingRect(self) -> QRectF:
        if not self.waveform_data:
            return QRectF(0, 0, 100, self.height)
        width = self.waveform_data.duration * self.pixels_per_second
        return QRectF(0, 0, width, self.height)

    def paint(self, painter: QPainter, option, widget):
        rect = self.boundingRect()

        # Track background
        painter.fillRect(rect, QBrush(COLOR_TRACK_BG))

        if not self.waveform_data:
            return

        try:
            painter.setRenderHint(QPainter.Antialiasing)

            width = int(rect.width())
            if width <= 0:
                return
            center_y = self.height / 2

            # Calculate visible area
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view:
                visible_rect = view.mapToScene(view.viewport().rect()).boundingRect()
                start_x = max(0, int(visible_rect.left()))
                end_x = min(width, int(visible_rect.right()) + 1)
            else:
                start_x = 0
                end_x = min(width, 2000)

            # Get peak data
            start_time = start_x / self.pixels_per_second
            end_time = end_x / self.pixels_per_second
            num_points = max(1, end_x - start_x)

            if num_points <= 0:
                return

            min_peaks, max_peaks = self.waveform_data.get_peaks_for_range(
                start_time, end_time, num_points
            )

            if len(max_peaks) == 0:
                return

            # Create waveform path
            path = QPainterPath()
            path.moveTo(start_x, center_y)

            # Upper half (max peaks)
            for i, peak in enumerate(max_peaks):
                x = start_x + i
                y = center_y - (peak * center_y * 0.85)
                path.lineTo(x, y)

            # Lower half (min peaks) - reversed
            for i in range(len(min_peaks) - 1, -1, -1):
                x = start_x + i
                y = center_y - (min_peaks[i] * center_y * 0.85)
                path.lineTo(x, y)

            path.closeSubpath()

            # Gradient fill - FCP style blue
            gradient = QLinearGradient(0, 0, 0, self.height)
            gradient.setColorAt(0, COLOR_WAVEFORM)
            gradient.setColorAt(0.5, COLOR_WAVEFORM_FILL)
            gradient.setColorAt(1, COLOR_WAVEFORM)

            painter.fillPath(path, QBrush(gradient))

            # Outline
            painter.setPen(QPen(COLOR_WAVEFORM, 0.5))
            painter.drawPath(path)

            # Center line
            painter.setPen(QPen(QColor("#404040"), 1))
            painter.drawLine(QPointF(start_x, center_y), QPointF(end_x, center_y))

        except Exception as e:
            logger.exception(f"Error painting waveform: {e}")

        # Border
        painter.setPen(QPen(COLOR_TRACK_BORDER, 1))
        painter.drawRect(rect)

        # Track label
        painter.setPen(QPen(QColor("#888888")))
        painter.setFont(QFont("Arial", 9))
        painter.drawText(5, 14, "A1")


class CutOverlayItem(QGraphicsRectItem):
    """Cut region overlay."""

    def __init__(self, cut: Cut, pixels_per_second: float, height: float, parent=None):
        super().__init__(parent)
        self.cut = cut
        self.pixels_per_second = pixels_per_second
        self.height = height
        self._update_rect()
        self._update_style()

        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

    def _update_rect(self):
        """Update rect position and size."""
        x = self.cut.start * self.pixels_per_second
        width = self.cut.duration * self.pixels_per_second
        self.setRect(x, 0, width, self.height)

    def _update_style(self):
        """Update visual style."""
        if not self.cut.enabled:
            color = QColor("#444444")
            alpha = 60
        elif self.cut.cut_type == CutType.SILENCE:
            color = COLOR_SILENCE
            alpha = 100
        else:
            color = QColor("#ff8844")
            alpha = 100

        fill_color = QColor(color)
        fill_color.setAlpha(alpha)

        self.setBrush(QBrush(fill_color))
        self.setPen(QPen(color, 2))

    def set_scale(self, pixels_per_second: float):
        """Update zoom."""
        self.pixels_per_second = pixels_per_second
        self._update_rect()

    def update_from_cut(self):
        """Apply cut changes."""
        self._update_rect()
        self._update_style()

    def hoverEnterEvent(self, event):
        pen = self.pen()
        pen.setWidth(3)
        self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._update_style()
        super().hoverLeaveEvent(event)


class PlayheadItem(QGraphicsLineItem):
    """Playhead line - FCP style orange."""

    def __init__(self, height: float, parent=None):
        super().__init__(0, 0, 0, height, parent)
        self.setPen(QPen(COLOR_PLAYHEAD, 2))
        self.setZValue(100)

    def set_position(self, x: float):
        line = self.line()
        self.setLine(x, line.y1(), x, line.y2())

    def set_height(self, height: float):
        line = self.line()
        self.setLine(line.x1(), 0, line.x1(), height)


class TimeRulerItem(QGraphicsItem):
    """Time ruler."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration: float = 0.0
        self.pixels_per_second: float = 100.0
        self.height: float = RULER_HEIGHT

    def set_duration(self, duration: float):
        self.duration = duration
        self.prepareGeometryChange()
        self.update()

    def set_scale(self, pixels_per_second: float):
        self.pixels_per_second = pixels_per_second
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QRectF:
        width = self.duration * self.pixels_per_second
        return QRectF(0, 0, max(width, 100), self.height)

    def paint(self, painter: QPainter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.boundingRect()

        # Background
        painter.fillRect(rect, QBrush(QColor("#252525")))

        # Calculate tick interval
        seconds_per_major = 1.0
        if self.pixels_per_second < 20:
            seconds_per_major = 10.0
        elif self.pixels_per_second < 50:
            seconds_per_major = 5.0
        elif self.pixels_per_second < 100:
            seconds_per_major = 2.0
        elif self.pixels_per_second > 500:
            seconds_per_major = 0.5

        # Visible area
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if view:
            visible_rect = view.mapToScene(view.viewport().rect()).boundingRect()
            start_time = max(0, visible_rect.left() / self.pixels_per_second)
            end_time = min(self.duration, visible_rect.right() / self.pixels_per_second)
        else:
            start_time = 0
            end_time = self.duration

        # Major ticks
        painter.setPen(QPen(COLOR_RULER, 1))
        painter.setFont(QFont("Menlo", 9))

        t = (int(start_time / seconds_per_major)) * seconds_per_major
        while t <= end_time:
            x = t * self.pixels_per_second

            # Tick line
            painter.setPen(QPen(COLOR_RULER, 1))
            painter.drawLine(QPointF(x, self.height - 10), QPointF(x, self.height))

            # Time label
            hours = int(t // 3600)
            minutes = int((t % 3600) // 60)
            seconds = int(t % 60)
            frames = int((t % 1) * 30)  # Assume 30fps for timecode display

            if hours > 0:
                label = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
            else:
                label = f"{minutes:02d}:{seconds:02d}:{frames:02d}"

            painter.setPen(QPen(COLOR_RULER_TEXT))
            painter.drawText(QPointF(x + 3, self.height - 12), label)

            t += seconds_per_major

        # Bottom line
        painter.setPen(QPen(COLOR_RULER, 1))
        painter.drawLine(QPointF(0, self.height - 1), QPointF(rect.width(), self.height - 1))


class TimelineWidget(QWidget):
    """
    Main timeline widget - Final Cut Pro / Premiere style.

    Signals:
        cut_selected(cut_id): Cut selected
        cut_toggled(cut_id, enabled): Cut enable/disable
        playhead_moved(time_sec): Playhead moved
    """

    cut_selected = Signal(str)
    cut_toggled = Signal(str, bool)
    playhead_moved = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.duration: float = 0.0
        self.pixels_per_second: float = 100.0
        self.playhead_time: float = 0.0
        self.cuts: List[Cut] = []
        self._cut_items: dict[str, CutOverlayItem] = {}
        self._video_path: Optional[Path] = None

        self._setup_ui()

    def _setup_ui(self):
        """Create UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Graphics view
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(COLOR_BACKGROUND))

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        # Mouse tracking for playhead
        self.view.viewport().installEventFilter(self)
        self.view.setMouseTracking(True)

        layout.addWidget(self.view)

        # Items
        self.ruler_item = TimeRulerItem()
        self.scene.addItem(self.ruler_item)

        self.video_item = VideoThumbnailItem()
        self.video_item.setPos(0, RULER_HEIGHT)
        self.scene.addItem(self.video_item)

        self.waveform_item = WaveformItem()
        self.waveform_item.setPos(0, RULER_HEIGHT + VIDEO_TRACK_HEIGHT)
        self.scene.addItem(self.waveform_item)

        self.playhead_item = PlayheadItem(TOTAL_HEIGHT)
        self.scene.addItem(self.playhead_item)

        # Scene rect
        self._update_scene_rect()

    def _update_scene_rect(self):
        """Update scene size."""
        width = max(self.duration * self.pixels_per_second, self.view.width())
        self.scene.setSceneRect(0, 0, width, TOTAL_HEIGHT)

    def set_video(self, video_path: Path):
        """Set video path for thumbnails (extracted later when waveform is ready)."""
        self._video_path = video_path
        # Thumbnails will be extracted when set_waveform is called (after audio extraction)

    def _extract_thumbnails_delayed(self):
        """Extract thumbnails after delay."""
        self.video_item.extract_thumbnails_safe()

    def set_waveform(self, data: WaveformData):
        """Set waveform data."""
        self.waveform_item.set_waveform(data)
        self.duration = data.duration
        self.ruler_item.set_duration(data.duration)
        self.video_item.duration = data.duration

        # Thumbnail extraction disabled - causes segfault with OpenCV
        # TODO: Extract thumbnails in a separate process to avoid conflicts

        self._update_scene_rect()

    def set_duration(self, duration: float):
        """Set duration."""
        self.duration = duration
        self.ruler_item.set_duration(duration)
        self.video_item.duration = duration
        self._update_scene_rect()

    def set_cuts(self, cuts: List[Cut]):
        """Set cut list."""
        logger.info(f"Setting {len(cuts)} cuts on timeline")

        # Remove old items
        for item in self._cut_items.values():
            self.scene.removeItem(item)
        self._cut_items.clear()

        self.cuts = cuts

        # Create new cut overlays (span both video and audio tracks)
        cut_height = VIDEO_TRACK_HEIGHT + AUDIO_TRACK_HEIGHT
        for cut in cuts:
            item = CutOverlayItem(cut, self.pixels_per_second, cut_height)
            item.setPos(0, RULER_HEIGHT)
            item.setZValue(50)
            self.scene.addItem(item)
            self._cut_items[cut.id] = item

        # Force update
        self.scene.update()
        self.view.viewport().update()
        logger.info(f"Timeline updated with {len(self._cut_items)} cut overlays")

    def set_playhead(self, time_sec: float, emit_signal: bool = False):
        """Set playhead position."""
        self.playhead_time = max(0, min(time_sec, self.duration)) if self.duration > 0 else 0
        x = self.playhead_time * self.pixels_per_second
        self.playhead_item.set_position(x)
        if emit_signal:
            self.playhead_moved.emit(self.playhead_time)

    def zoom_in(self):
        """Zoom in."""
        self._set_zoom(self.pixels_per_second * 1.5)

    def zoom_out(self):
        """Zoom out."""
        self._set_zoom(self.pixels_per_second / 1.5)

    def zoom_fit(self):
        """Fit timeline to view."""
        logger.debug(f"zoom_fit called, duration={self.duration}, view_width={self.view.width()}")
        if self.duration > 0 and self.view.width() > 50:
            target_pps = (self.view.width() - 50) / self.duration
            target_pps = max(1, target_pps)  # Minimum zoom level
            logger.debug(f"zoom_fit: target_pps={target_pps}")
            self._set_zoom(target_pps)
            # Scroll to beginning
            self.view.horizontalScrollBar().setValue(0)

    def zoom_to_range(self, start: float, end: float):
        """Zoom to specific range."""
        if end <= start:
            return

        range_duration = end - start
        target_pps = (self.view.width() - 50) / range_duration
        self._set_zoom(target_pps)

        # Scroll to range
        center_x = ((start + end) / 2) * self.pixels_per_second
        self.view.centerOn(center_x, TOTAL_HEIGHT / 2)

    def _set_zoom(self, pixels_per_second: float):
        """Set zoom level."""
        # Allow very low zoom for long videos (0.5 pps = 2 seconds per pixel)
        pixels_per_second = max(0.5, min(2000, pixels_per_second))

        if abs(self.pixels_per_second - pixels_per_second) < 0.01:
            return

        self.pixels_per_second = pixels_per_second
        logger.debug(f"_set_zoom: new pps={pixels_per_second}")

        # Update items
        self.waveform_item.set_scale(pixels_per_second)
        self.video_item.set_scale(pixels_per_second)
        self.ruler_item.set_scale(pixels_per_second)

        for item in self._cut_items.values():
            item.set_scale(pixels_per_second)

        # Playhead
        x = self.playhead_time * self.pixels_per_second
        self.playhead_item.set_position(x)

        self._update_scene_rect()

        # Force redraw
        self.scene.update()
        self.view.viewport().update()

    def eventFilter(self, obj, event):
        """Event filter for mouse interactions."""
        if obj == self.view.viewport():
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    # Click -> move playhead (emit signal for video sync)
                    pos = self.view.mapToScene(event.pos())
                    time_sec = pos.x() / self.pixels_per_second
                    self.set_playhead(time_sec, emit_signal=True)
                    return True

            elif event.type() == event.Type.Wheel:
                # Ctrl+wheel -> zoom
                if event.modifiers() & Qt.ControlModifier:
                    delta = event.angleDelta().y()
                    if delta > 0:
                        self.zoom_in()
                    else:
                        self.zoom_out()
                    return True

        return super().eventFilter(obj, event)

    def mouseDoubleClickEvent(self, event):
        """Double click -> toggle cut."""
        pos = self.view.mapToScene(self.view.mapFromGlobal(event.globalPos()))

        items = self.scene.items(pos)
        for item in items:
            if isinstance(item, CutOverlayItem):
                cut = item.cut
                cut.enabled = not cut.enabled
                item.update_from_cut()
                self.cut_toggled.emit(cut.id, cut.enabled)
                break

    def resizeEvent(self, event):
        """Resize."""
        super().resizeEvent(event)
        self._update_scene_rect()
