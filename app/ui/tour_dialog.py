"""
Guided tour dialog for first-time users.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)
from PySide6.QtGui import QPixmap, QFont

from app.core.i18n import tr


class TourDialog(QDialog):
    """İlk açılış rehber turu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_step = 0
        self.steps = self._get_steps()

        self.setWindowTitle(tr("tour_title"))
        self.setMinimumSize(600, 400)
        self.setModal(True)

        self._setup_ui()
        self._show_step(0)

    def _get_steps(self) -> list[dict]:
        """Tur adımlarını döndür."""
        return [
            {
                "title": tr("tour_welcome_title"),
                "content": tr("tour_welcome_content"),
                "icon": "🎬",
            },
            {
                "title": tr("tour_step1_title"),
                "content": tr("tour_step1_content"),
                "icon": "📂",
            },
            {
                "title": tr("tour_step2_title"),
                "content": tr("tour_step2_content"),
                "icon": "🔊",
            },
            {
                "title": tr("tour_step3_title"),
                "content": tr("tour_step3_content"),
                "icon": "✂️",
            },
            {
                "title": tr("tour_step4_title"),
                "content": tr("tour_step4_content"),
                "icon": "🎤",
            },
            {
                "title": tr("tour_step5_title"),
                "content": tr("tour_step5_content"),
                "icon": "📤",
            },
            {
                "title": tr("tour_finish_title"),
                "content": tr("tour_finish_content"),
                "icon": "🎉",
            },
        ]

    def _setup_ui(self):
        """UI oluştur."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Icon
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 64px;")
        layout.addWidget(self.icon_label)

        # Title
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)

        # Content
        self.content_label = QLabel()
        self.content_label.setAlignment(Qt.AlignCenter)
        self.content_label.setWordWrap(True)
        self.content_label.setStyleSheet("font-size: 14px; color: #cccccc; line-height: 1.5;")
        layout.addWidget(self.content_label)

        layout.addStretch()

        # Progress dots
        self.dots_widget = QWidget()
        dots_layout = QHBoxLayout(self.dots_widget)
        dots_layout.setAlignment(Qt.AlignCenter)
        dots_layout.setSpacing(8)
        self.dots = []
        for i in range(len(self.steps)):
            dot = QLabel("●")
            dot.setStyleSheet("font-size: 12px; color: #555555;")
            dots_layout.addWidget(dot)
            self.dots.append(dot)
        layout.addWidget(self.dots_widget)

        # Buttons
        btn_layout = QHBoxLayout()

        self.skip_btn = QPushButton(tr("tour_skip"))
        self.skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.skip_btn)

        btn_layout.addStretch()

        self.prev_btn = QPushButton(tr("tour_prev"))
        self.prev_btn.clicked.connect(self._prev_step)
        btn_layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton(tr("tour_next"))
        self.next_btn.clicked.connect(self._next_step)
        self.next_btn.setDefault(True)
        btn_layout.addWidget(self.next_btn)

        layout.addLayout(btn_layout)

    def _show_step(self, step: int):
        """Belirtilen adımı göster."""
        if step < 0 or step >= len(self.steps):
            return

        self.current_step = step
        data = self.steps[step]

        self.icon_label.setText(data["icon"])
        self.title_label.setText(data["title"])
        self.content_label.setText(data["content"])

        # Update dots
        for i, dot in enumerate(self.dots):
            if i == step:
                dot.setStyleSheet("font-size: 12px; color: #4CAF50;")
            else:
                dot.setStyleSheet("font-size: 12px; color: #555555;")

        # Update buttons
        self.prev_btn.setVisible(step > 0)

        if step == len(self.steps) - 1:
            self.next_btn.setText(tr("tour_finish"))
            self.skip_btn.setVisible(False)
        else:
            self.next_btn.setText(tr("tour_next"))
            self.skip_btn.setVisible(True)

    def _next_step(self):
        """Sonraki adıma geç."""
        if self.current_step < len(self.steps) - 1:
            self._show_step(self.current_step + 1)
        else:
            self.accept()

    def _prev_step(self):
        """Önceki adıma dön."""
        if self.current_step > 0:
            self._show_step(self.current_step - 1)
