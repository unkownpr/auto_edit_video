"""
Timeline widget with waveform display and cut overlays.

QGraphicsView tabanlı timeline:
- Waveform görselleştirme
- Cut bölgelerini overlay olarak gösterme
- Playhead
- Zoom/pan
- Cut seçimi ve düzenleme
"""

from __future__ import annotations

from typing import Optional, List
import logging

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsLineItem,
    QGraphicsTextItem,
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
    QWheelEvent,
    QMouseEvent,
)

from app.core.models import Cut, CutType
from app.media.waveform import WaveformData

logger = logging.getLogger(__name__)


# Colors
COLOR_BACKGROUND = QColor("#1a1a1a")
COLOR_WAVEFORM = QColor("#4CAF50")  # Green for visibility
COLOR_WAVEFORM_FILL = QColor("#4CAF5080")
COLOR_SILENCE = QColor("#ff4444")
COLOR_SILENCE_ALPHA = QColor(255, 68, 68, 80)
COLOR_KEEP = QColor("#ffffff")
COLOR_PLAYHEAD = QColor("#ffffff")
COLOR_RULER = QColor("#666666")
COLOR_RULER_TEXT = QColor("#aaaaaa")
COLOR_SELECTION = QColor("#ffffff")
COLOR_DISABLED = QColor("#444444")


class WaveformItem(QGraphicsItem):
    """Waveform çizimi için custom graphics item."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.waveform_data: Optional[WaveformData] = None
        self.pixels_per_second: float = 100.0
        self.height: float = 150.0
        self._cache_path: Optional[QPainterPath] = None
        self._cache_scale: float = 0.0

    def set_waveform(self, data: WaveformData):
        """Waveform verisini ayarla."""
        self.waveform_data = data
        self._cache_path = None
        self.prepareGeometryChange()
        self.update()

    def set_scale(self, pixels_per_second: float):
        """Zoom seviyesini ayarla."""
        if self.pixels_per_second != pixels_per_second:
            self.pixels_per_second = pixels_per_second
            self._cache_path = None
            self.prepareGeometryChange()
            self.update()

    def boundingRect(self) -> QRectF:
        if not self.waveform_data:
            return QRectF(0, 0, 100, self.height)
        width = self.waveform_data.duration * self.pixels_per_second
        return QRectF(0, 0, width, self.height)

    def paint(self, painter: QPainter, option, widget):
        if not self.waveform_data:
            return

        try:
            painter.setRenderHint(QPainter.Antialiasing)

            rect = self.boundingRect()
            width = int(rect.width())
            if width <= 0:
                return
            center_y = self.height / 2

            # Görünür alanı hesapla
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view:
                visible_rect = view.mapToScene(view.viewport().rect()).boundingRect()
                start_x = max(0, int(visible_rect.left()))
                end_x = min(width, int(visible_rect.right()) + 1)
            else:
                start_x = 0
                end_x = min(width, 2000)  # Limit for safety

            # Waveform path oluştur
            path = QPainterPath()
            path.moveTo(start_x, center_y)

            # Peak verisi al
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

            # Üst yarı (max peaks)
            for i, peak in enumerate(max_peaks):
                x = start_x + i
                y = center_y - (peak * center_y * 0.9)
                path.lineTo(x, y)

            # Alt yarı (min peaks) - ters sırada
            for i in range(len(min_peaks) - 1, -1, -1):
                x = start_x + i
                y = center_y - (min_peaks[i] * center_y * 0.9)
                path.lineTo(x, y)

            path.closeSubpath()

            # Gradient fill
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


class CutOverlayItem(QGraphicsRectItem):
    """Cut bölgesi overlay'i."""

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
        """Rect'i güncelle."""
        x = self.cut.start * self.pixels_per_second
        width = self.cut.duration * self.pixels_per_second
        self.setRect(x, 0, width, self.height)

    def _update_style(self):
        """Stili güncelle."""
        if not self.cut.enabled:
            color = COLOR_DISABLED
            alpha = 60
        elif self.cut.cut_type == CutType.SILENCE:
            color = COLOR_SILENCE
            alpha = 120  # More visible
        elif self.cut.cut_type == CutType.BREATH:
            color = QColor("#ff8844")
            alpha = 120
        else:
            color = COLOR_KEEP
            alpha = 80

        fill_color = QColor(color)
        fill_color.setAlpha(alpha)

        self.setBrush(QBrush(fill_color))
        self.setPen(QPen(color, 2))  # Thicker border

    def set_scale(self, pixels_per_second: float):
        """Zoom güncelle."""
        self.pixels_per_second = pixels_per_second
        self._update_rect()

    def update_from_cut(self):
        """Cut değişikliklerini uygula."""
        self._update_rect()
        self._update_style()

    def hoverEnterEvent(self, event):
        """Hover enter."""
        pen = self.pen()
        pen.setWidth(2)
        self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Hover leave."""
        self._update_style()
        super().hoverLeaveEvent(event)


class PlayheadItem(QGraphicsLineItem):
    """Playhead çizgisi."""

    def __init__(self, height: float, parent=None):
        super().__init__(0, 0, 0, height, parent)
        self.setPen(QPen(COLOR_PLAYHEAD, 2))
        self.setZValue(100)  # En üstte

    def set_position(self, x: float):
        """Pozisyonu ayarla."""
        line = self.line()
        self.setLine(x, line.y1(), x, line.y2())

    def set_height(self, height: float):
        """Yüksekliği ayarla."""
        line = self.line()
        self.setLine(line.x1(), 0, line.x1(), height)


class TimeRulerItem(QGraphicsItem):
    """Zaman cetvel'i."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration: float = 0.0
        self.pixels_per_second: float = 100.0
        self.height: float = 25.0

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

        # Tick aralığını hesapla
        # Yaklaşık her 50-100 piksel bir major tick
        seconds_per_major = 1.0
        if self.pixels_per_second < 20:
            seconds_per_major = 10.0
        elif self.pixels_per_second < 50:
            seconds_per_major = 5.0
        elif self.pixels_per_second < 100:
            seconds_per_major = 2.0
        elif self.pixels_per_second > 500:
            seconds_per_major = 0.5

        # Görünür alan
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
        painter.setFont(QFont("Menlo", 9))  # macOS; falls back to default on other platforms

        t = (int(start_time / seconds_per_major)) * seconds_per_major
        while t <= end_time:
            x = t * self.pixels_per_second
            painter.drawLine(QPointF(x, self.height - 10), QPointF(x, self.height))

            # Label
            minutes = int(t // 60)
            seconds = t % 60
            label = f"{minutes}:{seconds:05.2f}"
            painter.setPen(QPen(COLOR_RULER_TEXT))
            painter.drawText(QPointF(x + 3, self.height - 12), label)
            painter.setPen(QPen(COLOR_RULER, 1))

            t += seconds_per_major

        # Bottom line
        painter.drawLine(QPointF(0, self.height - 1), QPointF(rect.width(), self.height - 1))


class TimelineWidget(QWidget):
    """
    Ana timeline widget'ı.

    Signals:
        cut_selected(cut_id): Cut seçildi
        cut_toggled(cut_id, enabled): Cut enable/disable
        playhead_moved(time_sec): Playhead hareket etti
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

        self._setup_ui()

    def _setup_ui(self):
        """UI oluştur."""
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

        self.waveform_item = WaveformItem()
        self.waveform_item.setPos(0, 25)  # Ruler altında
        self.scene.addItem(self.waveform_item)

        self.playhead_item = PlayheadItem(175)
        self.scene.addItem(self.playhead_item)

        # Scene rect
        self._update_scene_rect()

    def _update_scene_rect(self):
        """Scene boyutunu güncelle."""
        width = max(self.duration * self.pixels_per_second, self.view.width())
        self.scene.setSceneRect(0, 0, width, 175)

    def set_waveform(self, data: WaveformData):
        """Waveform verisini ayarla."""
        self.waveform_item.set_waveform(data)
        self.duration = data.duration
        self.ruler_item.set_duration(data.duration)
        self._update_scene_rect()

    def set_duration(self, duration: float):
        """Duration ayarla."""
        self.duration = duration
        self.ruler_item.set_duration(duration)
        self._update_scene_rect()

    def set_cuts(self, cuts: List[Cut]):
        """Cut listesini ayarla."""
        logger.info(f"Setting {len(cuts)} cuts on timeline")

        # Eski item'ları temizle
        for item in self._cut_items.values():
            self.scene.removeItem(item)
        self._cut_items.clear()

        self.cuts = cuts

        # Yeni item'lar oluştur
        for cut in cuts:
            item = CutOverlayItem(cut, self.pixels_per_second, 150)
            item.setPos(0, 25)  # Ruler altında
            item.setZValue(50)  # Above waveform
            self.scene.addItem(item)
            self._cut_items[cut.id] = item
            logger.debug(f"Added cut overlay: {cut.start:.2f}s - {cut.end:.2f}s")

        # Force scene update
        self.scene.update()
        self.view.viewport().update()
        logger.info(f"Timeline updated with {len(self._cut_items)} cut overlays")

    def set_playhead(self, time_sec: float):
        """Playhead pozisyonunu ayarla."""
        self.playhead_time = max(0, min(time_sec, self.duration))
        x = self.playhead_time * self.pixels_per_second
        self.playhead_item.set_position(x)
        self.playhead_moved.emit(self.playhead_time)

    def zoom_in(self):
        """Zoom in."""
        self._set_zoom(self.pixels_per_second * 1.5)

    def zoom_out(self):
        """Zoom out."""
        self._set_zoom(self.pixels_per_second / 1.5)

    def zoom_fit(self):
        """Timeline'ı görünür alana sığdır."""
        if self.duration > 0:
            target_pps = (self.view.width() - 50) / self.duration
            self._set_zoom(target_pps)

    def zoom_to_range(self, start: float, end: float):
        """Belirli bir aralığa zoom."""
        if end <= start:
            return

        range_duration = end - start
        target_pps = (self.view.width() - 50) / range_duration
        self._set_zoom(target_pps)

        # O aralığa scroll
        center_x = ((start + end) / 2) * self.pixels_per_second
        self.view.centerOn(center_x, 87)

    def _set_zoom(self, pixels_per_second: float):
        """Zoom seviyesini ayarla."""
        # Limit zoom
        pixels_per_second = max(5, min(2000, pixels_per_second))

        if self.pixels_per_second == pixels_per_second:
            return

        self.pixels_per_second = pixels_per_second

        # Items'ı güncelle
        self.waveform_item.set_scale(pixels_per_second)
        self.ruler_item.set_scale(pixels_per_second)

        for item in self._cut_items.values():
            item.set_scale(pixels_per_second)

        # Playhead
        x = self.playhead_time * self.pixels_per_second
        self.playhead_item.set_position(x)

        self._update_scene_rect()

    def eventFilter(self, obj, event):
        """Event filter for mouse interactions."""
        if obj == self.view.viewport():
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    # Click -> playhead taşı
                    pos = self.view.mapToScene(event.pos())
                    time_sec = pos.x() / self.pixels_per_second
                    self.set_playhead(time_sec)
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
        """Double click -> cut toggle."""
        pos = self.view.mapToScene(self.view.mapFromGlobal(event.globalPos()))

        # Cut item'a tıklandı mı?
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
