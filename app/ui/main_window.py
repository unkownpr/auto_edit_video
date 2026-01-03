"""
Main application window.

Modern 3-panel layout:
- Left: Project/Media panel + Settings
- Center: Player + Timeline
- Right: Cut list + Transcript
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThreadPool, QSize
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
    QApplication,
    QMenuBar,
    QMenu,
    QToolBar,
    QStatusBar,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QGroupBox,
    QFormLayout,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QTabWidget,
    QFrame,
    QSizePolicy,
    QDialog,
    QDialogButtonBox,
    QRadioButton,
    QButtonGroup,
)
from PySide6.QtGui import QAction, QKeySequence, QIcon, QFont, QPalette, QColor, QPixmap, QImage
import importlib.resources
# Video player disabled due to Qt/FFmpeg crash on macOS
# from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
# from PySide6.QtMultimediaWidgets import QVideoWidget

from app.core.models import Project, MediaInfo, AnalysisConfig, Cut
from app.core.settings import Settings, Preset, DEFAULT_PRESETS
from app.core.i18n import tr, set_language, get_language, detect_system_language
from app.media.ffmpeg import probe_media, extract_audio, FFmpegError, FFmpegNotFoundError
from app.media.waveform import WaveformGenerator, WaveformData
from app.analysis.silence_detector import detect_silence, detect_silence_ffmpeg
from app.export.fcpxml import export_fcpxml
from app.export.edl import export_edl
from app.export.premiere_xml import export_premiere_xml

from .timeline_widget import TimelineWidget
from .settings_dialog import SettingsDialog
from .worker import Worker
from .video_player import VideoPlayer

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Ana uygulama penceresi."""

    # Signals
    project_changed = Signal()
    analysis_complete = Signal(list)
    export_complete = Signal(Path)

    def __init__(self):
        super().__init__()

        self.settings = Settings.load()
        self.project: Optional[Project] = None
        self.waveform_data: Optional[WaveformData] = None
        self.thread_pool = QThreadPool()
        self._project_path: Optional[Path] = None
        self._progress_dialog: Optional[QProgressDialog] = None
        self._progress_active: bool = False  # Flag to safely ignore progress updates after close
        self._video_path: Optional[Path] = None
        self._updating_position: bool = False  # Prevent recursion between video and timeline
        self._active_workers: list = []  # Keep workers alive until callbacks complete

        # Dil ayarı
        if self.settings.language:
            set_language(self.settings.language)
        else:
            detected = detect_system_language()
            set_language(detected)
            self.settings.language = detected

        # FFmpeg kontrolü
        if not self._check_ffmpeg():
            return

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_shortcuts()
        self._setup_statusbar()
        self._apply_theme()
        self._update_ui_language()
        self._set_app_icon()

        # Autosave timer
        if self.settings.autosave_enabled:
            self.autosave_timer = QTimer(self)
            self.autosave_timer.timeout.connect(self._autosave)
            self.autosave_timer.start(self.settings.autosave_interval_sec * 1000)

    def _start_worker(self, worker: Worker):
        """Start a worker and keep it alive until finished.

        This prevents garbage collection of worker objects while signals are still
        being processed, which can cause segmentation faults.
        """
        # Keep reference to prevent garbage collection
        self._active_workers.append(worker)

        # Remove from list when finished (after all signals processed)
        def cleanup():
            try:
                self._active_workers.remove(worker)
                logger.debug(f"Worker removed from active list, {len(self._active_workers)} remaining")
            except ValueError:
                pass  # Already removed

        # Use QTimer.singleShot to defer cleanup, ensuring signals complete first
        worker.signals.finished.connect(lambda: QTimer.singleShot(100, cleanup))

        # Start the worker
        self.thread_pool.start(worker)
        logger.debug(f"Worker started, {len(self._active_workers)} active workers")

    def _set_app_icon(self):
        """Set application icon."""
        try:
            icon_path = Path(__file__).parent.parent.parent / "resources" / "icon.png"
            if icon_path.exists():
                icon = QIcon(str(icon_path))
                self.setWindowIcon(icon)
                QApplication.instance().setWindowIcon(icon)
                logger.debug(f"App icon set from: {icon_path}")
            else:
                logger.warning(f"Icon not found: {icon_path}")
        except Exception as e:
            logger.warning(f"Failed to set app icon: {e}")

    def _check_ffmpeg(self) -> bool:
        """FFmpeg kurulumunu kontrol et."""
        try:
            from app.media.ffmpeg import FFmpegWrapper
            FFmpegWrapper()
            return True
        except FFmpegNotFoundError:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle(tr("dialog_error"))
            msg.setText(tr("error_ffmpeg_not_found"))
            msg.setInformativeText(tr("error_ffmpeg_install"))
            msg.exec()
            return False

    @Slot(int, str)
    def _update_progress(self, value: int, message: str):
        """Thread-safe progress update slot."""
        # Check flag first to avoid race conditions with deleted dialogs
        if not self._progress_active:
            return
        try:
            dialog = self._progress_dialog
            if dialog is not None and not dialog.wasCanceled():
                dialog.setValue(value)
                if message:
                    dialog.setLabelText(message)
        except (RuntimeError, AttributeError):
            # Dialog was deleted or in invalid state
            self._progress_active = False
            self._progress_dialog = None

    def _show_progress_dialog(self, title: str, cancel_text: str):
        """Create and show a progress dialog safely."""
        self._close_progress_dialog()  # Close any existing dialog first
        self._progress_dialog = QProgressDialog(title, cancel_text, 0, 100, self)
        self._progress_dialog.setWindowModality(Qt.ApplicationModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_active = True
        self._progress_dialog.show()
        QApplication.processEvents()  # Ensure dialog is visible

    def _close_progress_dialog(self):
        """Close progress dialog safely."""
        self._progress_active = False  # Set flag first to block any queued signals
        dialog = self._progress_dialog
        self._progress_dialog = None
        if dialog is not None:
            try:
                dialog.close()
                dialog.deleteLater()
            except (RuntimeError, AttributeError):
                pass  # Dialog already deleted

    def _setup_ui(self):
        """UI bileşenlerini oluştur."""
        self.setWindowTitle(tr("app_name"))
        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)

        # Center panel
        center_panel = self._create_center_panel()
        splitter.addWidget(center_panel)

        # Right panel
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)

        # Splitter sizes
        splitter.setSizes([300, 900, 350])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

    def _create_left_panel(self) -> QWidget:
        """Sol panel - Kontroller ve ayarlar."""
        panel = QFrame()
        panel.setObjectName("leftPanel")
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(400)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Logo/Title
        title_label = QLabel("🎬 AutoCut")
        title_label.setObjectName("appTitle")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Media info
        media_group = QGroupBox(tr("panel_media"))
        media_layout = QVBoxLayout(media_group)

        self.media_label = QLabel(tr("no_file_loaded"))
        self.media_label.setWordWrap(True)
        self.media_label.setObjectName("mediaInfo")
        media_layout.addWidget(self.media_label)

        import_btn = QPushButton(tr("btn_import_video"))
        import_btn.setObjectName("primaryButton")
        import_btn.clicked.connect(self.import_media)
        media_layout.addWidget(import_btn)

        layout.addWidget(media_group)

        # Preset selection
        preset_group = QGroupBox(tr("preset"))
        preset_layout = QVBoxLayout(preset_group)

        self.preset_combo = QComboBox()
        self._populate_presets()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)

        layout.addWidget(preset_group)

        # Analysis settings
        settings_group = QGroupBox(tr("panel_settings"))
        settings_layout = QFormLayout(settings_group)
        settings_layout.setSpacing(8)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-60, -10)
        self.threshold_spin.setValue(-30)  # Updated default (less aggressive)
        self.threshold_spin.setSuffix(" dB")
        self.threshold_spin.setDecimals(1)
        settings_layout.addRow(tr("threshold") + ":", self.threshold_spin)

        self.min_duration_spin = QSpinBox()
        self.min_duration_spin.setRange(50, 2000)
        self.min_duration_spin.setValue(500)  # Updated default (0.5s)
        self.min_duration_spin.setSuffix(" ms")
        settings_layout.addRow(tr("min_duration") + ":", self.min_duration_spin)

        self.pre_pad_spin = QSpinBox()
        self.pre_pad_spin.setRange(0, 500)
        self.pre_pad_spin.setValue(100)  # Updated default
        self.pre_pad_spin.setSuffix(" ms")
        settings_layout.addRow(tr("pre_padding") + ":", self.pre_pad_spin)

        self.post_pad_spin = QSpinBox()
        self.post_pad_spin.setRange(0, 500)
        self.post_pad_spin.setValue(150)  # Updated default
        self.post_pad_spin.setSuffix(" ms")
        settings_layout.addRow(tr("post_padding") + ":", self.post_pad_spin)

        self.merge_gap_spin = QSpinBox()
        self.merge_gap_spin.setRange(0, 1000)
        self.merge_gap_spin.setValue(300)  # Updated default
        self.merge_gap_spin.setSuffix(" ms")
        settings_layout.addRow(tr("merge_gap") + ":", self.merge_gap_spin)

        self.keep_short_spin = QSpinBox()
        self.keep_short_spin.setRange(0, 500)
        self.keep_short_spin.setValue(150)  # Preserve natural pauses
        self.keep_short_spin.setSuffix(" ms")
        self.keep_short_spin.setToolTip(tr("keep_short_tooltip"))
        settings_layout.addRow(tr("keep_short_pauses") + ":", self.keep_short_spin)

        self.vad_check = QCheckBox(tr("use_vad"))
        settings_layout.addRow(self.vad_check)

        layout.addWidget(settings_group)

        # Action buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        self.analyze_btn = QPushButton(tr("btn_analyze"))
        self.analyze_btn.setObjectName("primaryButton")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self.run_analysis)
        btn_layout.addWidget(self.analyze_btn)

        # Delete silent areas button - renders new video
        self.render_btn = QPushButton(tr("btn_render_video"))
        self.render_btn.setObjectName("primaryButton")
        self.render_btn.setEnabled(False)
        self.render_btn.clicked.connect(self._render_video_without_silences)
        btn_layout.addWidget(self.render_btn)

        self.export_btn = QPushButton(tr("btn_export"))
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._show_export_dialog)
        btn_layout.addWidget(self.export_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        # Developer credit
        dev_label = QLabel("developed by ssilistre.dev")
        dev_label.setObjectName("developerCredit")
        dev_label.setAlignment(Qt.AlignCenter)
        dev_label.setStyleSheet("""
            color: #666666;
            font-size: 10px;
            padding: 8px;
            font-style: italic;
        """)
        layout.addWidget(dev_label)

        return panel

    def _create_center_panel(self) -> QWidget:
        """Orta panel - Video Preview + Timeline."""
        panel = QFrame()
        panel.setObjectName("centerPanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Video player (OpenCV-based)
        self.video_player = VideoPlayer()
        self.video_player.position_changed.connect(self._on_video_position_changed)
        layout.addWidget(self.video_player, 2)

        # Timeline widget
        self.timeline = TimelineWidget()
        self.timeline.cut_selected.connect(self._on_cut_selected)
        self.timeline.cut_toggled.connect(self._on_cut_toggled)
        self.timeline.playhead_moved.connect(self._on_playhead_moved)
        layout.addWidget(self.timeline, 1)

        # Timeline zoom controls
        zoom_controls = QFrame()
        zoom_controls.setObjectName("zoomControls")
        zoom_layout = QHBoxLayout(zoom_controls)
        zoom_layout.setContentsMargins(8, 4, 8, 4)
        zoom_layout.setSpacing(4)

        zoom_layout.addStretch()

        zoom_label = QLabel("Timeline Zoom:")
        zoom_label.setStyleSheet("color: #888888;")
        zoom_layout.addWidget(zoom_label)

        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setObjectName("zoomButton")
        zoom_out_btn.setFixedSize(28, 28)
        zoom_out_btn.clicked.connect(lambda: self.timeline.zoom_out())
        zoom_layout.addWidget(zoom_out_btn)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setObjectName("zoomButton")
        zoom_in_btn.setFixedSize(28, 28)
        zoom_in_btn.clicked.connect(lambda: self.timeline.zoom_in())
        zoom_layout.addWidget(zoom_in_btn)

        fit_btn = QPushButton(tr("timeline_fit"))
        fit_btn.setObjectName("zoomButton")
        fit_btn.clicked.connect(lambda: self.timeline.zoom_fit())
        zoom_layout.addWidget(fit_btn)

        layout.addWidget(zoom_controls)

        return panel

    def _create_right_panel(self) -> QWidget:
        """Sağ panel - Cut list ve Transcript."""
        panel = QFrame()
        panel.setObjectName("rightPanel")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(450)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.setObjectName("rightTabs")

        # Cuts tab
        cuts_widget = QWidget()
        cuts_layout = QVBoxLayout(cuts_widget)
        cuts_layout.setContentsMargins(0, 8, 0, 0)

        self.cuts_list = QListWidget()
        self.cuts_list.setObjectName("cutsList")
        self.cuts_list.itemClicked.connect(self._on_cut_list_clicked)
        self.cuts_list.itemDoubleClicked.connect(self._on_cut_list_double_clicked)
        cuts_layout.addWidget(self.cuts_list)

        self.cut_info_label = QLabel(tr("no_file_loaded"))
        self.cut_info_label.setObjectName("cutInfo")
        cuts_layout.addWidget(self.cut_info_label)

        cut_actions = QHBoxLayout()
        toggle_btn = QPushButton(tr("btn_toggle"))
        toggle_btn.clicked.connect(self._toggle_selected_cut)
        cut_actions.addWidget(toggle_btn)

        delete_btn = QPushButton(tr("btn_delete"))
        delete_btn.clicked.connect(self._delete_selected_cut)
        cut_actions.addWidget(delete_btn)

        cuts_layout.addLayout(cut_actions)
        tabs.addTab(cuts_widget, tr("panel_cuts"))

        # Transcript tab
        transcript_widget = QWidget()
        transcript_layout = QVBoxLayout(transcript_widget)
        transcript_layout.setContentsMargins(0, 8, 0, 0)

        self.transcript_list = QListWidget()
        self.transcript_list.setObjectName("transcriptList")
        transcript_layout.addWidget(self.transcript_list)

        transcribe_btn = QPushButton(tr("btn_transcribe"))
        transcribe_btn.clicked.connect(self._run_transcription)
        transcript_layout.addWidget(transcribe_btn)

        tabs.addTab(transcript_widget, tr("panel_transcript"))
        layout.addWidget(tabs, 1)

        # Stats
        stats_group = QGroupBox(tr("panel_statistics"))
        stats_group.setObjectName("statsGroup")
        stats_layout = QFormLayout(stats_group)

        self.original_duration_label = QLabel("—")
        stats_layout.addRow(tr("stats_original") + ":", self.original_duration_label)

        self.cut_duration_label = QLabel("—")
        self.cut_duration_label.setStyleSheet("color: #ff6b6b;")
        stats_layout.addRow(tr("stats_removed") + ":", self.cut_duration_label)

        self.final_duration_label = QLabel("—")
        self.final_duration_label.setStyleSheet("color: #51cf66;")
        stats_layout.addRow(tr("stats_final") + ":", self.final_duration_label)

        self.cut_count_label = QLabel("—")
        stats_layout.addRow(tr("stats_cuts") + ":", self.cut_count_label)

        layout.addWidget(stats_group)

        return panel

    def _populate_presets(self):
        """Preset listesini doldur."""
        self.preset_combo.clear()
        preset_names = {
            "Podcast": tr("preset_podcast"),
            "Tutorial": tr("preset_tutorial"),
            "Meeting": tr("preset_meeting"),
            "Noisy Room": tr("preset_noisy"),
            "Aggressive": tr("preset_aggressive"),
        }
        for preset in DEFAULT_PRESETS:
            name = preset_names.get(preset.name, preset.name)
            self.preset_combo.addItem(name, preset)

    def _setup_menu(self):
        """Menü bar oluştur."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu(tr("menu_file"))

        open_action = QAction(tr("menu_open"), self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.import_media)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        save_action = QAction(tr("menu_save"), self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction(tr("menu_save_as"), self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self.save_project_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        export_action = QAction(tr("menu_export"), self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._show_export_dialog)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        settings_action = QAction(tr("menu_settings"), self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        quit_action = QAction(tr("menu_quit"), self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Edit menu
        edit_menu = menubar.addMenu(tr("menu_edit"))

        undo_action = QAction(tr("menu_undo"), self)
        undo_action.setShortcut(QKeySequence.Undo)
        edit_menu.addAction(undo_action)

        redo_action = QAction(tr("menu_redo"), self)
        redo_action.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(redo_action)

        # View menu
        view_menu = menubar.addMenu(tr("menu_view"))

        zoom_in_action = QAction(tr("menu_zoom_in"), self)
        zoom_in_action.setShortcut("Ctrl+=")
        zoom_in_action.triggered.connect(lambda: self.timeline.zoom_in())
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction(tr("menu_zoom_out"), self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(lambda: self.timeline.zoom_out())
        view_menu.addAction(zoom_out_action)

        zoom_fit_action = QAction(tr("menu_zoom_fit"), self)
        zoom_fit_action.setShortcut("Ctrl+0")
        zoom_fit_action.triggered.connect(lambda: self.timeline.zoom_fit())
        view_menu.addAction(zoom_fit_action)

        # Help menu
        help_menu = menubar.addMenu(tr("menu_help"))

        about_action = QAction(tr("menu_about"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self):
        """Toolbar oluştur."""
        toolbar = QToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)

        open_action = QAction(tr("toolbar_open"), self)
        open_action.triggered.connect(self.import_media)
        toolbar.addAction(open_action)

        toolbar.addSeparator()

        self.analyze_action = QAction(tr("toolbar_analyze"), self)
        self.analyze_action.setEnabled(False)
        self.analyze_action.triggered.connect(self.run_analysis)
        toolbar.addAction(self.analyze_action)

        self.export_action = QAction(tr("toolbar_export"), self)
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self._show_export_dialog)
        toolbar.addAction(self.export_action)

        toolbar.addSeparator()

        settings_action = QAction(tr("toolbar_settings"), self)
        settings_action.triggered.connect(self._show_settings)
        toolbar.addAction(settings_action)

    def _setup_shortcuts(self):
        """Keyboard shortcuts."""
        pass

    def _setup_statusbar(self):
        """Status bar oluştur."""
        self.statusbar = QStatusBar()
        self.statusbar.setObjectName("statusBar")
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage(tr("status_ready"))

    def _apply_theme(self):
        """Tema uygula - Siyah/Beyaz minimal tema."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }

            #leftPanel, #rightPanel {
                background-color: #222222;
                border: none;
            }

            #centerPanel {
                background-color: #1a1a1a;
            }

            #appTitle {
                color: #ffffff;
                padding: 8px 0;
            }

            QGroupBox {
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                margin-top: 12px;
                padding: 12px 8px 8px 8px;
                font-weight: 500;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #888888;
            }

            QLabel {
                color: #ffffff;
                background: transparent;
            }

            #mediaInfo, #cutInfo {
                color: #888888;
                font-size: 12px;
                padding: 8px;
                background-color: #2a2a2a;
                border-radius: 6px;
            }

            QPushButton {
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 10px 16px;
                font-weight: 500;
            }

            QPushButton:hover {
                background-color: #444444;
                border-color: #666666;
            }

            QPushButton:pressed {
                background-color: #222222;
            }

            QPushButton:disabled {
                background-color: #1a1a1a;
                color: #555555;
                border-color: #2a2a2a;
            }

            #primaryButton {
                background-color: #ffffff;
                color: #000000;
                border-color: #ffffff;
            }

            #primaryButton:hover {
                background-color: #e0e0e0;
            }

            #primaryButton:disabled {
                background-color: #444444;
                color: #888888;
                border-color: #444444;
            }

            #playButton {
                background-color: #ffffff;
                color: #000000;
                border-radius: 20px;
                font-size: 16px;
            }

            #playButton:hover {
                background-color: #e0e0e0;
            }

            #zoomButton {
                padding: 4px 10px;
                min-width: 28px;
            }

            QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 8px 12px;
            }

            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
                border-color: #666666;
            }

            QComboBox::drop-down {
                border: none;
                width: 24px;
            }

            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #444444;
            }

            QListWidget {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
            }

            QListWidget::item {
                padding: 8px;
                border-radius: 4px;
            }

            QListWidget::item:selected {
                background-color: #ffffff;
                color: #000000;
            }

            QListWidget::item:hover:!selected {
                background-color: #3a3a3a;
            }

            QCheckBox {
                color: #ffffff;
                spacing: 8px;
            }

            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #444444;
                border-radius: 4px;
                background-color: #2a2a2a;
            }

            QCheckBox::indicator:checked {
                background-color: #ffffff;
                border-color: #ffffff;
            }

            QTabWidget::pane {
                border: 1px solid #333333;
                border-radius: 6px;
                background-color: #222222;
            }

            QTabBar::tab {
                background-color: #2a2a2a;
                color: #888888;
                border: none;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }

            QTabBar::tab:selected {
                background-color: #222222;
                color: #ffffff;
                border-bottom: 2px solid #ffffff;
            }

            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }

            QSlider::handle:horizontal {
                background: #ffffff;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }

            QSlider::sub-page:horizontal {
                background: #888888;
                border-radius: 3px;
            }

            #timeLabel {
                color: #ffffff;
                font-family: "Menlo", "Consolas", "DejaVu Sans Mono";
                font-size: 13px;
                font-weight: bold;
            }

            #playbackControls {
                background-color: #222222;
                border-radius: 8px;
                margin: 0 12px;
            }

            QMenuBar {
                background-color: #222222;
                color: #ffffff;
                border-bottom: 1px solid #333333;
            }

            QMenuBar::item:selected {
                background-color: #333333;
            }

            QMenu {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
            }

            QMenu::item:selected {
                background-color: #444444;
            }

            QToolBar {
                background-color: #222222;
                border-bottom: 1px solid #333333;
                padding: 4px;
                spacing: 4px;
            }

            #statusBar {
                background-color: #222222;
                color: #888888;
                border-top: 1px solid #333333;
            }

            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 10px;
            }

            QScrollBar::handle:vertical {
                background-color: #444444;
                border-radius: 5px;
                min-height: 30px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #666666;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }

            QProgressDialog {
                background-color: #2a2a2a;
            }

            QMessageBox {
                background-color: #2a2a2a;
            }

            QMessageBox QLabel {
                color: #ffffff;
            }
        """)

    def _update_ui_language(self):
        """UI dilini güncelle."""
        self.setWindowTitle(tr("app_name"))
        self._populate_presets()
        # Diğer UI elementleri güncellenmeli...

    # ========================================================================
    # Actions
    # ========================================================================

    def import_media(self):
        """Video/audio dosyası import et."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("btn_import_video"),
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm);;Audio Files (*.wav *.mp3 *.aac *.flac);;All Files (*)"
        )

        if not file_path:
            return

        self._load_media(Path(file_path))

    def _load_media(self, file_path: Path):
        """Medya dosyasını yükle."""
        self.statusbar.showMessage(tr("progress_loading"))

        try:
            media_info = probe_media(file_path)

            self.project = Project(
                name=file_path.stem,
                created_at=datetime.now().isoformat(),
                media_info=media_info,
            )

            # Store video path for playback
            self._video_path = file_path

            # Load video into player
            if self.video_player.load_video(file_path):
                logger.info(f"Video loaded into player: {file_path}")
            else:
                logger.warning(f"Failed to load video into player: {file_path}")

            # Set video path for timeline thumbnails
            self.timeline.set_video(file_path)

            self._update_media_info()
            self.analyze_btn.setEnabled(True)
            self.analyze_action.setEnabled(True)

            self._extract_and_analyze()

            self.statusbar.showMessage(tr("status_loaded", file_path.name))

        except FFmpegError as e:
            QMessageBox.critical(self, tr("dialog_error"), tr("error_analysis_failed", str(e)))
            self.statusbar.showMessage(tr("status_ready"))

    def _update_media_info(self):
        """Media info labelını güncelle."""
        if not self.project or not self.project.media_info:
            self.media_label.setText(tr("no_file_loaded"))
            return

        info = self.project.media_info
        duration = self._format_time(info.duration)

        text = f"📁 {info.file_path.name}\n"
        text += f"📐 {info.width}×{info.height} @ {info.fps:.2f}fps\n"
        text += f"⏱ {duration}\n"
        text += f"🔊 {info.sample_rate}Hz, {info.channels}ch"

        self.media_label.setText(text)
        self.original_duration_label.setText(duration)

    def _extract_and_analyze(self):
        """Audio extract ve waveform üretimi."""
        if not self.project or not self.project.media_info:
            return

        media = self.project.media_info

        self._show_progress_dialog(tr("progress_extracting"), tr("btn_cancel"))

        def do_work(progress_callback):
            cache_dir = Settings.get_cache_dir()
            audio_path = cache_dir / f"{media.file_path.stem}_audio.wav"

            progress_callback(10, tr("progress_extracting"))
            extract_audio(media.file_path, audio_path, sample_rate=48000, mono=True)
            media.audio_path = audio_path

            progress_callback(50, tr("progress_generating_waveform"))
            generator = WaveformGenerator(samples_per_bucket=256, cache_dir=cache_dir)
            waveform = generator.generate(audio_path)

            progress_callback(100, "")
            return waveform

        def on_complete(waveform):
            try:
                logger.info("on_complete (waveform): closing progress dialog")
                self._close_progress_dialog()

                logger.info("on_complete (waveform): setting waveform data")
                self.waveform_data = waveform

                # Use QTimer to ensure UI updates happen safely in main thread
                def update_timeline():
                    try:
                        logger.info(f"update_timeline: waveform duration={waveform.duration}")
                        self.timeline.set_waveform(waveform)
                        logger.info("update_timeline: set_waveform done")
                        if self.project and self.project.media_info:
                            self.timeline.set_duration(self.project.media_info.duration)
                        logger.info("update_timeline: all done successfully")
                    except Exception as e:
                        logger.exception(f"Error in update_timeline: {e}")

                QTimer.singleShot(100, update_timeline)

            except Exception as e:
                logger.exception(f"Error in on_complete: {e}")
                QMessageBox.critical(self, tr("dialog_error"), str(e))

        def on_error(error):
            self._close_progress_dialog()
            logger.error(f"Worker error: {error}")
            QMessageBox.warning(self, tr("dialog_warning"), tr("error_analysis_failed", str(error)))

        worker = Worker(do_work)
        worker.signals.progress.connect(self._update_progress, Qt.QueuedConnection)
        worker.signals.result.connect(on_complete, Qt.QueuedConnection)
        worker.signals.error.connect(on_error, Qt.QueuedConnection)
        self._start_worker(worker)

    def run_analysis(self):
        """Sessizlik analizi çalıştır."""
        if not self.project or not self.project.media_info:
            return

        media = self.project.media_info

        config = AnalysisConfig(
            silence_threshold_db=self.threshold_spin.value(),
            silence_min_duration_ms=self.min_duration_spin.value(),
            pre_pad_ms=self.pre_pad_spin.value(),
            post_pad_ms=self.post_pad_spin.value(),
            merge_gap_ms=self.merge_gap_spin.value(),
            keep_short_pauses_ms=self.keep_short_spin.value(),
            use_vad=self.vad_check.isChecked(),
        )
        self.project.config = config

        self._show_progress_dialog(tr("progress_analyzing"), tr("btn_cancel"))

        def do_work(progress_callback):
            from app.media.ffmpeg import FFmpegWrapper

            # FFmpeg silencedetect kullan (daha doğru, frame-accurate)
            try:
                ffmpeg = FFmpegWrapper()
                logger.info("Using FFmpeg silencedetect for frame-accurate detection")
                return detect_silence_ffmpeg(
                    media.file_path,
                    config,
                    lambda p: progress_callback(int(p * 100), tr("progress_analyzing")),
                    ffmpeg_path=ffmpeg.ffmpeg_path,
                )
            except Exception as e:
                # Fallback: numpy-based detection
                logger.warning(f"FFmpeg silencedetect failed, falling back to numpy: {e}")
                if not media.audio_path or not media.audio_path.exists():
                    raise ValueError(tr("error_no_audio"))
                return detect_silence(
                    media.audio_path,
                    config,
                    lambda p: progress_callback(int(p * 100), tr("progress_analyzing")),
                )

        def on_complete(cuts):
            logger.info(f"=== on_complete callback START ===")
            logger.info(f"on_complete callback called with {type(cuts)}")
            try:
                logger.info(f"Cuts received: {cuts is not None}, count: {len(cuts) if cuts else 0}")
                self._close_progress_dialog()
                logger.info("Progress dialog closed")

                logger.info(f"Analysis complete: {len(cuts)} silence regions found")

                # Log first 5 cuts for debugging
                for i, cut in enumerate(cuts[:5]):
                    logger.info(f"  Cut {i+1}: {cut.start:.2f}s - {cut.end:.2f}s ({cut.duration:.2f}s)")
                if len(cuts) > 5:
                    logger.info(f"  ... and {len(cuts) - 5} more cuts")

                logger.info("Setting project.cuts...")
                self.project.cuts = cuts
                logger.info("Updating cuts list UI...")
                self._update_cuts_list()
                logger.info("Updating stats...")
                self._update_stats()
                logger.info("Setting cuts on timeline...")
                self.timeline.set_cuts(cuts)
                logger.info("Setting cuts on video player...")
                self.video_player.set_cuts(cuts)  # Pass cuts to video player for skip feature
                logger.info("Enabling export buttons...")
                self.export_btn.setEnabled(True)
                self.export_action.setEnabled(True)
                self.render_btn.setEnabled(True)  # Enable render button
                logger.info("=== render_btn enabled! ===")

                # Show message box with summary
                total_cut_duration = sum(c.duration for c in cuts if c.enabled)
                msg = tr("analysis_complete_msg", len(cuts), self._format_time(total_cut_duration))

                QMessageBox.information(self, tr("analysis_complete_title"), msg)

                self.statusbar.showMessage(tr("status_found_cuts", len(cuts)))
            except Exception as e:
                logger.exception(f"Error in on_complete: {e}")
                QMessageBox.critical(self, tr("dialog_error"), tr("analysis_error", str(e)))

        def on_error(error):
            self._close_progress_dialog()
            logger.error(f"Analysis error: {error}")
            QMessageBox.critical(self, tr("dialog_error"), tr("error_analysis_failed", str(error)))

        worker = Worker(do_work)
        worker.signals.progress.connect(self._update_progress, Qt.QueuedConnection)

        # Use a wrapper that ensures callback runs on main thread
        def safe_on_complete(cuts):
            logger.info(f"safe_on_complete called with {len(cuts) if cuts else 0} cuts")
            # Schedule on main thread using QTimer
            QTimer.singleShot(0, lambda: on_complete(cuts))

        def safe_on_error(error):
            logger.info(f"safe_on_error called: {error}")
            QTimer.singleShot(0, lambda: on_error(error))

        worker.signals.result.connect(safe_on_complete)
        worker.signals.error.connect(safe_on_error)
        worker.signals.finished.connect(lambda: logger.info("Analysis worker finished signal received"))

        self._start_worker(worker)
        logger.info("Analysis worker started")

    def _show_export_dialog(self):
        """Export format seçim dialogu."""
        if not self.project or not self.project.media_info:
            QMessageBox.warning(self, tr("dialog_warning"), tr("no_file_loaded"))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("export_title"))
        dialog.setMinimumWidth(450)

        layout = QVBoxLayout(dialog)

        format_group = QGroupBox(tr("export_format"))
        format_layout = QVBoxLayout(format_group)

        self._export_format_group = QButtonGroup(dialog)

        fcp_radio = QRadioButton(tr("export_fcp"))
        fcp_radio.setChecked(True)
        self._export_format_group.addButton(fcp_radio, 0)
        format_layout.addWidget(fcp_radio)

        premiere_radio = QRadioButton(tr("export_premiere"))
        self._export_format_group.addButton(premiere_radio, 1)
        format_layout.addWidget(premiere_radio)

        resolve_radio = QRadioButton(tr("export_resolve"))
        self._export_format_group.addButton(resolve_radio, 2)
        format_layout.addWidget(resolve_radio)

        layout.addWidget(format_group)

        info_label = QLabel()
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #888; font-size: 11px; padding: 8px;")

        def update_info():
            fmt_id = self._export_format_group.checkedId()
            hints = [tr("export_fcp_hint"), tr("export_premiere_hint"), tr("export_resolve_hint")]
            info_label.setText(f"💡 {hints[fmt_id]}")

        self._export_format_group.idClicked.connect(update_info)
        update_info()
        layout.addWidget(info_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            self._do_export(self._export_format_group.checkedId())

    def _do_export(self, format_id: int):
        """Seçilen formatta export yap."""
        if not self.project or not self.project.media_info:
            return

        stem = self.project.media_info.file_path.stem

        formats = [
            (f"{stem}_edited.fcpxml", "FCPXML Files (*.fcpxml);;All Files (*)", export_fcpxml, "FCPXML"),
            (f"{stem}_edited.xml", "XML Files (*.xml);;All Files (*)", export_premiere_xml, "Premiere XML"),
            (f"{stem}_edited.edl", "EDL Files (*.edl);;All Files (*)", export_edl, "EDL"),
        ]

        default_name, filter_str, export_func, format_name = formats[format_id]

        file_path, _ = QFileDialog.getSaveFileName(self, f"Export {format_name}", default_name, filter_str)

        if not file_path:
            return

        try:
            output_path = export_func(self.project, Path(file_path))
            QMessageBox.information(self, tr("export_success"), f"{format_name} exported to:\n{output_path}")
            self.statusbar.showMessage(tr("status_exported", output_path.name))
        except Exception as e:
            QMessageBox.critical(self, tr("export_failed"), tr("error_export_failed", str(e)))

    def _show_settings(self):
        """Settings dialogunu göster."""
        dialog = SettingsDialog(self.settings, self)
        dialog.language_changed.connect(self._on_language_changed)
        dialog.settings_saved.connect(self._on_settings_saved)
        dialog.exec()

    def _on_language_changed(self, lang: str):
        """Dil değişti."""
        set_language(lang)
        self._update_ui_language()
        QMessageBox.information(
            self,
            tr("dialog_info"),
            tr("settings_restart_required")
        )

    def _on_settings_saved(self):
        """Ayarlar kaydedildi."""
        self.settings = Settings.load()

    def save_project(self):
        """Projeyi kaydet."""
        if not self.project:
            return

        if not self._project_path:
            self.save_project_as()
            return

        self.project.modified_at = datetime.now().isoformat()
        self.project.save(self._project_path)
        self.statusbar.showMessage(tr("status_saved", self._project_path.name))

    def save_project_as(self):
        """Projeyi farklı kaydet."""
        if not self.project:
            return

        default_name = f"{self.project.name}.autocut"
        file_path, _ = QFileDialog.getSaveFileName(self, tr("menu_save_as"), default_name, "AutoCut Project (*.autocut);;All Files (*)")

        if not file_path:
            return

        self._project_path = Path(file_path)
        self.save_project()

    # ========================================================================
    # UI Updates
    # ========================================================================

    def _update_cuts_list(self):
        """Cuts listesini güncelle."""
        logger.info("_update_cuts_list called")
        self.cuts_list.clear()

        if not self.project:
            logger.info("No project, returning")
            return

        logger.info(f"Adding {len(self.project.cuts)} cuts to list")
        for cut in self.project.cuts:
            start = self._format_time(cut.start)
            end = self._format_time(cut.end)
            duration = self._format_time(cut.duration)

            status = "✅" if cut.enabled else "⬜"
            text = f"{status} {start} → {end} ({duration})"

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, cut.id)

            self.cuts_list.addItem(item)

    def _update_stats(self):
        """İstatistikleri güncelle."""
        if not self.project or not self.project.media_info:
            return

        original = self.project.media_info.duration
        cut_total = self.project.get_total_cut_duration()
        final = self.project.get_final_duration()

        self.original_duration_label.setText(self._format_time(original))
        self.cut_duration_label.setText(f"−{self._format_time(cut_total)}")
        self.final_duration_label.setText(self._format_time(final))
        self.cut_count_label.setText(str(len([c for c in self.project.cuts if c.enabled])))

    def _format_time(self, seconds: float) -> str:
        """Saniyeyi HH:MM:SS.mmm formatına dönüştür."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

    # ========================================================================
    # Event Handlers
    # ========================================================================

    def _on_preset_changed(self, index: int):
        """Preset değişti."""
        preset = self.preset_combo.itemData(index)
        if preset:
            config = preset.config
            self.threshold_spin.setValue(config.silence_threshold_db)
            self.min_duration_spin.setValue(config.silence_min_duration_ms)
            self.pre_pad_spin.setValue(config.pre_pad_ms)
            self.post_pad_spin.setValue(config.post_pad_ms)
            self.merge_gap_spin.setValue(config.merge_gap_ms)
            self.vad_check.setChecked(config.use_vad)

    def _on_cut_selected(self, cut_id: str):
        """Timeline'da cut seçildi."""
        for i in range(self.cuts_list.count()):
            item = self.cuts_list.item(i)
            if item.data(Qt.UserRole) == cut_id:
                self.cuts_list.setCurrentItem(item)
                break

    def _on_cut_toggled(self, cut_id: str, enabled: bool):
        """Cut enable/disable."""
        if not self.project:
            return

        for cut in self.project.cuts:
            if cut.id == cut_id:
                cut.enabled = enabled
                break

        self._update_cuts_list()
        self._update_stats()

    def _on_playhead_moved(self, time_sec: float):
        """Timeline playhead hareket etti - video'yu da güncelle."""
        if self._updating_position:
            return
        self._updating_position = True
        try:
            if hasattr(self, 'video_player'):
                self.video_player.seek(time_sec)
        finally:
            self._updating_position = False

    def _on_video_position_changed(self, time_sec: float):
        """Video pozisyonu değişti - timeline'ı güncelle."""
        if self._updating_position:
            return
        self._updating_position = True
        try:
            self.timeline.set_playhead(time_sec)
        finally:
            self._updating_position = False


    def _on_cut_list_clicked(self, item: QListWidgetItem):
        """Cuts listesinde tıklama."""
        cut_id = item.data(Qt.UserRole)
        if not self.project:
            return

        for cut in self.project.cuts:
            if cut.id == cut_id:
                self.cut_info_label.setText(
                    f"⏱ Start: {self._format_time(cut.start)}\n"
                    f"⏱ End: {self._format_time(cut.end)}\n"
                    f"📊 Avg dB: {cut.source_avg_db:.1f}\n"
                    f"{'✅ Enabled' if cut.enabled else '⬜ Disabled'}"
                )
                break

    def _on_cut_list_double_clicked(self, item: QListWidgetItem):
        """Cuts listesinde çift tıklama."""
        cut_id = item.data(Qt.UserRole)
        if not self.project:
            return

        for cut in self.project.cuts:
            if cut.id == cut_id:
                self.timeline.set_playhead(cut.start)
                self.timeline.zoom_to_range(cut.start - 1, cut.end + 1)
                break

    def _toggle_selected_cut(self):
        """Seçili cut'ı toggle et."""
        item = self.cuts_list.currentItem()
        if not item or not self.project:
            return

        cut_id = item.data(Qt.UserRole)
        for cut in self.project.cuts:
            if cut.id == cut_id:
                cut.enabled = not cut.enabled
                break

        self._update_cuts_list()
        self._update_stats()
        self.timeline.update()

    def _delete_selected_cut(self):
        """Seçili cut'ı sil."""
        item = self.cuts_list.currentItem()
        if not item or not self.project:
            return

        cut_id = item.data(Qt.UserRole)
        self.project.cuts = [c for c in self.project.cuts if c.id != cut_id]

        self._update_cuts_list()
        self._update_stats()
        self.timeline.set_cuts(self.project.cuts)



    def _run_transcription(self):
        """Transkripsiyon çalıştır."""
        if not self.project or not self.project.media_info:
            QMessageBox.warning(self, tr("dialog_warning"), tr("no_file_loaded"))
            return

        media = self.project.media_info
        if not media.audio_path or not media.audio_path.exists():
            QMessageBox.warning(self, tr("dialog_warning"), tr("error_no_audio"))
            return

        # Check if Gemini is enabled
        use_gemini = self.settings.gemini_enabled and self.settings.gemini_api_key

        if use_gemini:
            # Use Gemini for transcription
            self._run_gemini_transcription(media)
        else:
            # Use Whisper for transcription
            self._run_whisper_transcription(media)

    def _run_gemini_transcription(self, media):
        """Gemini ile transkripsiyon."""
        self._show_progress_dialog(tr("progress_transcribing"), tr("btn_cancel"))

        def do_work(progress_callback):
            from app.transcript.transcriber import transcribe_with_gemini

            progress_callback(5, "Gemini API'ye bağlanılıyor...")
            return transcribe_with_gemini(
                media.audio_path,
                api_key=self.settings.gemini_api_key,
                model=self.settings.gemini_model,
                progress_callback=lambda p, msg: progress_callback(int(p), msg),
            )

        def on_complete(segments):
            self._close_progress_dialog()
            self.project.transcript_segments = segments
            self.transcript_list.clear()
            for seg in segments:
                self.transcript_list.addItem(f"[{self._format_time(seg.start)}] {seg.text}")
            self.statusbar.showMessage(f"Gemini: {len(segments)} segment transkript edildi")

        def on_error(error):
            self._close_progress_dialog()
            QMessageBox.critical(self, tr("dialog_error"), f"Gemini Error: {error}")

        worker = Worker(do_work)
        worker.signals.progress.connect(self._update_progress, Qt.QueuedConnection)
        worker.signals.result.connect(on_complete, Qt.QueuedConnection)
        worker.signals.error.connect(on_error, Qt.QueuedConnection)
        self._start_worker(worker)

    def _run_whisper_transcription(self, media):
        """Whisper ile transkripsiyon."""
        # Model seçim dialogu
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("transcription_title"))
        dialog.setMinimumWidth(450)

        layout = QVBoxLayout(dialog)

        # Check which models are downloaded
        from app.transcript.transcriber import is_model_downloaded

        # Model seçimi
        model_group = QGroupBox(tr("transcription_model_select"))
        model_layout = QVBoxLayout(model_group)

        model_combo = QComboBox()
        models = [
            ("tiny", "Tiny - En Hızlı (~10x)", "~1 dk / 10 dk video"),
            ("base", "Base - Hızlı (~5x)", "~2 dk / 10 dk video (Önerilen)"),
            ("small", "Small - Dengeli (~2x)", "~5 dk / 10 dk video"),
            ("medium", "Medium - Doğru", "~10 dk / 10 dk video"),
            ("large-v3", "Large - En Doğru", "~20+ dk / 10 dk video"),
        ]

        default_index = 1  # Default: base
        for i, (model_id, name, desc) in enumerate(models):
            is_downloaded = is_model_downloaded(model_id)
            status = "✅" if is_downloaded else "⬇️"
            model_combo.addItem(f"{status} {name} - {desc}", model_id)
            # Select first downloaded model as default if base is not downloaded
            if is_downloaded and not is_model_downloaded("base") and default_index == 1:
                default_index = i

        model_combo.setCurrentIndex(default_index)
        model_layout.addWidget(model_combo)

        # Download status info
        downloaded_count = sum(1 for m, _, _ in models if is_model_downloaded(m))
        status_label = QLabel(f"✅ = {tr('transcription_downloaded')} ({downloaded_count}/5)  |  ⬇️ = {tr('transcription_will_download')}")
        status_label.setStyleSheet("color: #888; font-size: 10px; padding: 4px;")
        model_layout.addWidget(status_label)

        layout.addWidget(model_group)

        # Info
        info_label = QLabel(f"💡 {tr('transcription_speed_hint')}")
        info_label.setStyleSheet("color: #888; font-size: 11px; padding: 8px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        selected_model = model_combo.currentData()

        self._show_progress_dialog(tr("progress_transcribing"), tr("btn_cancel"))

        def do_work(progress_callback):
            from app.transcript.transcriber import transcribe_audio, TranscriptConfig, ModelSize

            # Convert string to ModelSize enum
            model_size_map = {
                "tiny": ModelSize.TINY,
                "base": ModelSize.BASE,
                "small": ModelSize.SMALL,
                "medium": ModelSize.MEDIUM,
                "large": ModelSize.LARGE,
                "large-v3": ModelSize.LARGE,
            }
            model_size = model_size_map.get(selected_model, ModelSize.BASE)

            # Optimized config for speed
            config = TranscriptConfig(
                model_size=model_size,
                device="auto" if self.settings.gpu_acceleration else "cpu",
                beam_size=1 if model_size in (ModelSize.TINY, ModelSize.BASE) else 3,
                best_of=1,  # Fastest
                word_timestamps=False,  # Faster without word-level timestamps
                vad_filter=True,  # Skip silent parts
            )

            progress_callback(5, f"Model yükleniyor: {model_size.value}...")
            return transcribe_audio(
                media.audio_path,
                config,
                lambda p, msg: progress_callback(int(p), msg),
            )

        def on_complete(segments):
            self._close_progress_dialog()
            self.project.transcript_segments = segments
            self.transcript_list.clear()
            for seg in segments:
                self.transcript_list.addItem(f"[{self._format_time(seg.start)}] {seg.text}")
            self.statusbar.showMessage(f"Transcribed {len(segments)} segments")

        def on_error(error):
            self._close_progress_dialog()
            QMessageBox.critical(self, tr("dialog_error"), str(error))

        worker = Worker(do_work)
        worker.signals.progress.connect(self._update_progress, Qt.QueuedConnection)
        worker.signals.result.connect(on_complete, Qt.QueuedConnection)
        worker.signals.error.connect(on_error, Qt.QueuedConnection)
        self._start_worker(worker)

    def _render_video_without_silences(self):
        """Sessiz alanları silip yeni video oluştur."""
        if not self.project or not self.project.media_info:
            QMessageBox.warning(self, tr("dialog_warning"), tr("no_file_loaded"))
            return

        if not self.project.cuts:
            QMessageBox.warning(self, tr("dialog_warning"), tr("render_analyze_first"))
            return

        # Get enabled cuts
        enabled_cuts = [c for c in self.project.cuts if c.enabled]
        if not enabled_cuts:
            QMessageBox.warning(self, tr("dialog_warning"), tr("render_no_cuts"))
            return

        # Ask for output file
        media = self.project.media_info
        default_name = f"{media.file_path.stem}_edited{media.file_path.suffix}"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("render_save_title"),
            default_name,
            f"Video Files (*{media.file_path.suffix});;All Files (*)"
        )

        if not file_path:
            return

        output_path = Path(file_path)

        # Safety check: don't overwrite input file
        if output_path.resolve() == media.file_path.resolve():
            QMessageBox.warning(self, tr("dialog_warning"), tr("render_same_file"))
            return

        logger.info(f"Input: {media.file_path}")
        logger.info(f"Output: {output_path}")

        # Calculate segments to keep (inverse of cuts)
        duration = media.duration
        segments = []
        last_end = 0.0

        # Sort cuts by start time
        sorted_cuts = sorted(enabled_cuts, key=lambda c: c.start)

        for cut in sorted_cuts:
            if cut.start > last_end:
                segments.append((last_end, cut.start))
            last_end = max(last_end, cut.end)

        # Add final segment if needed
        if last_end < duration:
            segments.append((last_end, duration))

        if not segments:
            QMessageBox.warning(self, tr("dialog_warning"), tr("render_no_segments"))
            return

        # Calculate total duration of segments
        total_segment_duration = sum(end - start for start, end in segments)
        total_cut_duration = sum(c.duration for c in enabled_cuts)

        logger.info(f"=== RENDER INFO ===")
        logger.info(f"Original duration: {duration:.2f}s")
        logger.info(f"Total cut duration: {total_cut_duration:.2f}s")
        logger.info(f"Expected output duration: {total_segment_duration:.2f}s")
        logger.info(f"Rendering video with {len(segments)} segments (removing {len(enabled_cuts)} cuts)")
        for i, (start, end) in enumerate(segments[:10]):
            logger.info(f"  Segment {i+1}: {start:.2f}s - {end:.2f}s (duration: {end-start:.2f}s)")
        if len(segments) > 10:
            logger.info(f"  ... and {len(segments) - 10} more segments")

        self._show_progress_dialog(tr("render_progress"), tr("btn_cancel"))

        def do_work(progress_callback):
            from app.media.ffmpeg import FFmpegWrapper
            import subprocess

            ffmpeg = FFmpegWrapper()

            progress_callback(5, tr("render_cutting"))

            # Log segments info
            logger.info(f"=== RENDER START ===")
            logger.info(f"Total segments to keep: {len(segments)}")
            for i, (start, end) in enumerate(segments[:5]):
                logger.info(f"  Segment {i+1}: {start:.3f}s - {end:.3f}s")
            if len(segments) > 5:
                logger.info(f"  ... and {len(segments) - 5} more")

            # Delete output file if exists
            if output_path.exists():
                logger.info(f"Deleting existing output: {output_path}")
                output_path.unlink()

            progress_callback(10, tr("render_merging"))

            # Build FFmpeg filter_complex for selecting and concatenating segments
            # This does everything in one pass - more reliable than many temp files

            # For many segments, use trim filter approach
            filter_parts = []
            concat_inputs = []

            for i, (start, end) in enumerate(segments):
                # Trim video and audio for each segment
                filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]")
                filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]")
                concat_inputs.append(f"[v{i}][a{i}]")

            # Concat all segments
            filter_complex = ";".join(filter_parts)
            filter_complex += f";{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=1[outv][outa]"

            logger.info(f"Filter has {len(segments)} segments")

            # Build FFmpeg command
            cmd = [
                ffmpeg.ffmpeg_path,
                "-y",
                "-i", str(media.file_path),
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_path)
            ]

            logger.info(f"Running FFmpeg with filter_complex (re-encoding)...")

            # Run with progress updates
            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Monitor progress
            while True:
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                if "time=" in line:
                    # Extract time from FFmpeg output
                    try:
                        time_str = line.split("time=")[1].split()[0]
                        parts = time_str.split(":")
                        current_time = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                        progress = min(95, 10 + int((current_time / total_segment_duration) * 85))
                        progress_callback(progress, f"{current_time:.0f}s / {total_segment_duration:.0f}s")
                    except:
                        pass

            return_code = process.wait()

            if return_code != 0:
                logger.error(f"FFmpeg error (code {return_code})")
                raise RuntimeError(f"FFmpeg encoding failed")

            # Verify output
            if output_path.exists():
                output_size = output_path.stat().st_size
                logger.info(f"Output created: {output_path} ({output_size/1024/1024:.2f}MB)")
            else:
                raise RuntimeError("Output file was not created")

            progress_callback(100, tr("render_complete"))
            return output_path

        def on_complete(result_path):
            self._close_progress_dialog()

            # Calculate saved time
            total_cut = sum(c.duration for c in enabled_cuts)

            msg = tr("render_success_msg",
                     result_path,
                     self._format_time(total_cut),
                     self._format_time(media.duration - total_cut))

            QMessageBox.information(self, tr("render_success_title"), msg)
            self.statusbar.showMessage(tr("status_saved", result_path.name))

        def on_error(error):
            self._close_progress_dialog()
            QMessageBox.critical(self, tr("dialog_error"), tr("render_error", error))

        worker = Worker(do_work)
        worker.signals.progress.connect(self._update_progress, Qt.QueuedConnection)
        worker.signals.result.connect(on_complete, Qt.QueuedConnection)
        worker.signals.error.connect(on_error, Qt.QueuedConnection)
        self._start_worker(worker)

    def _autosave(self):
        """Otomatik kaydet."""
        if self.project and self._project_path:
            try:
                self.project.modified_at = datetime.now().isoformat()
                self.project.save(self._project_path)
            except Exception as e:
                logger.warning(f"Autosave failed: {e}")

    def _show_about(self):
        """About dialog."""
        from app import __version__
        about_text = f"""
<h2>AutoCut</h2>
<p>Version {__version__}</p>
<p>Otomatik sessizlik algılama ve video düzenleme aracı.</p>
<p><b>Özellikler:</b></p>
<ul>
<li>Sessiz bölgeleri otomatik tespit</li>
<li>Final Cut Pro tarzı timeline</li>
<li>FCPXML, Premiere XML, EDL export</li>
<li>Sessiz alanları kesip yeni video oluşturma</li>
</ul>
<hr>
<p style="color: #888;">developed by <b>ssilistre.dev</b></p>
"""
        QMessageBox.about(self, "AutoCut Hakkında", about_text)
