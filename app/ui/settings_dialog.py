"""
Settings dialog with tabs for different categories.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QGroupBox,
    QFormLayout,
    QLabel,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QPushButton,
    QProgressBar,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QLineEdit,
)

from app.core.settings import Settings, Theme
from app.core.i18n import tr, set_language, get_language, get_supported_languages

logger = logging.getLogger(__name__)


# Whisper model bilgileri
WHISPER_MODELS = {
    "tiny": {"size": "39 MB", "speed": "~32x", "accuracy": "Low"},
    "base": {"size": "74 MB", "speed": "~16x", "accuracy": "Low"},
    "small": {"size": "244 MB", "speed": "~6x", "accuracy": "Medium"},
    "medium": {"size": "769 MB", "speed": "~2x", "accuracy": "Good"},
    "large-v3": {"size": "1550 MB", "speed": "~1x", "accuracy": "Best"},
}

# Gemini model bilgileri
GEMINI_MODELS = {
    "gemini-2.0-flash-exp": {"desc": "Fast, experimental", "speed": "Very Fast"},
    "gemini-1.5-flash": {"desc": "Fast, production ready", "speed": "Fast"},
    "gemini-1.5-pro": {"desc": "Most capable", "speed": "Slower"},
}


class ModelDownloadThread(QThread):
    """Whisper model indirme thread'i."""
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            # faster-whisper modeli indir
            from faster_whisper import WhisperModel

            self.progress.emit(10)

            # Model indirilirken yüklenir
            model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                download_root=None,  # Default cache
            )

            self.progress.emit(100)
            self.finished.emit(True, "")

        except ImportError:
            self.finished.emit(False, "faster-whisper not installed")
        except Exception as e:
            self.finished.emit(False, str(e))


class SettingsDialog(QDialog):
    """Ayarlar dialogu."""

    language_changed = Signal(str)
    theme_changed = Signal(str)
    settings_saved = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._download_thread: Optional[ModelDownloadThread] = None

        self.setWindowTitle(tr("settings_title"))
        self.setMinimumSize(700, 600)
        self.resize(750, 650)
        self.setModal(True)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """UI oluştur."""
        layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()

        # General tab
        self.tabs.addTab(self._create_general_tab(), tr("settings_general"))

        # Transcription tab
        self.tabs.addTab(self._create_transcription_tab(), tr("settings_transcription"))

        # Export tab
        self.tabs.addTab(self._create_export_tab(), tr("settings_export"))

        # Appearance tab
        self.tabs.addTab(self._create_appearance_tab(), tr("settings_appearance"))

        layout.addWidget(self.tabs)

        # Buttons with translated text
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.button(QDialogButtonBox.Ok).setText(tr("btn_ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("btn_cancel"))
        buttons.button(QDialogButtonBox.Apply).setText(tr("btn_apply"))
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply_settings)

        layout.addWidget(buttons)

    def _create_general_tab(self) -> QWidget:
        """Genel ayarlar sekmesi."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Language
        lang_group = QGroupBox(tr("settings_language"))
        lang_layout = QFormLayout(lang_group)

        self.language_combo = QComboBox()
        for code, name in get_supported_languages().items():
            self.language_combo.addItem(name, code)

        lang_layout.addRow(tr("settings_language") + ":", self.language_combo)
        layout.addWidget(lang_group)

        # Auto-save
        autosave_group = QGroupBox(tr("settings_autosave"))
        autosave_layout = QFormLayout(autosave_group)

        self.autosave_check = QCheckBox(tr("settings_autosave"))
        autosave_layout.addRow(self.autosave_check)

        self.autosave_interval_spin = QSpinBox()
        self.autosave_interval_spin.setRange(10, 600)
        self.autosave_interval_spin.setSuffix(" s")
        autosave_layout.addRow(tr("settings_autosave_interval") + ":", self.autosave_interval_spin)

        layout.addWidget(autosave_group)

        # Proxy
        proxy_group = QGroupBox(tr("settings_proxy_group"))
        proxy_layout = QFormLayout(proxy_group)

        self.proxy_check = QCheckBox(tr("settings_proxy"))
        proxy_layout.addRow(self.proxy_check)

        self.proxy_resolution_combo = QComboBox()
        self.proxy_resolution_combo.addItems(["480p", "720p", "1080p"])
        proxy_layout.addRow(tr("settings_proxy_resolution") + ":", self.proxy_resolution_combo)

        layout.addWidget(proxy_group)

        # Tour
        tour_group = QGroupBox(tr("tour_title"))
        tour_layout = QVBoxLayout(tour_group)

        self.restart_tour_btn = QPushButton(tr("settings_restart_tour"))
        self.restart_tour_btn.clicked.connect(self._restart_tour)
        tour_layout.addWidget(self.restart_tour_btn)

        layout.addWidget(tour_group)

        layout.addStretch()
        return widget

    def _restart_tour(self):
        """Turu yeniden başlat."""
        from app.ui.tour_dialog import TourDialog
        tour = TourDialog(self)
        tour.exec()

    def _create_transcription_tab(self) -> QWidget:
        """Transkripsiyon ayarları sekmesi."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)

        # Gemini API Settings
        gemini_group = QGroupBox("Gemini API")
        gemini_form = QFormLayout(gemini_group)
        gemini_form.setSpacing(12)
        gemini_form.setContentsMargins(12, 16, 12, 12)

        # Enable checkbox
        self.gemini_enabled_check = QCheckBox(tr("settings_gemini_enabled"))
        self.gemini_enabled_check.toggled.connect(self._on_gemini_toggled)
        gemini_form.addRow(self.gemini_enabled_check)

        # API Key row with buttons
        api_row = QWidget()
        api_row_layout = QHBoxLayout(api_row)
        api_row_layout.setContentsMargins(0, 0, 0, 0)
        api_row_layout.setSpacing(8)

        self.gemini_api_key_edit = QLineEdit()
        self.gemini_api_key_edit.setPlaceholderText("AIza...")
        self.gemini_api_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_api_key_edit.setMinimumWidth(200)
        api_row_layout.addWidget(self.gemini_api_key_edit, 1)

        self.show_key_btn = QPushButton(tr("settings_show_key"))
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.toggled.connect(self._toggle_api_key_visibility)
        api_row_layout.addWidget(self.show_key_btn)

        self.test_key_btn = QPushButton(tr("settings_test_key"))
        self.test_key_btn.clicked.connect(self._test_gemini_key)
        api_row_layout.addWidget(self.test_key_btn)

        gemini_form.addRow(tr("settings_gemini_api_key") + ":", api_row)

        # Model selection
        self.gemini_model_combo = QComboBox()
        for model_id, info in GEMINI_MODELS.items():
            self.gemini_model_combo.addItem(f"{model_id} ({info['speed']})", model_id)
        gemini_form.addRow(tr("settings_gemini_model") + ":", self.gemini_model_combo)

        # Status label
        self.gemini_status_label = QLabel()
        self.gemini_status_label.setStyleSheet("color: #ff9800; font-size: 12px;")
        gemini_form.addRow(self.gemini_status_label)

        layout.addWidget(gemini_group)

        # Model selection
        model_group = QGroupBox(tr("settings_whisper_model"))
        model_form = QFormLayout(model_group)
        model_form.setSpacing(12)
        model_form.setContentsMargins(12, 16, 12, 12)

        # Model combo with download button on same row
        model_row = QWidget()
        model_row_layout = QHBoxLayout(model_row)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.setSpacing(8)

        self.model_combo = QComboBox()

        # Accuracy translation mapping
        accuracy_map = {
            "Low": "accuracy_low",
            "Medium": "accuracy_medium",
            "Good": "accuracy_good",
            "Best": "accuracy_best",
        }

        for model_id, info in WHISPER_MODELS.items():
            acc_key = accuracy_map.get(info['accuracy'], "accuracy_medium")
            label = f"{model_id.capitalize()} ({info['size']}) - {tr(acc_key)}"
            self.model_combo.addItem(label, model_id)

        model_row_layout.addWidget(self.model_combo, 1)

        self.download_btn = QPushButton(tr("settings_whisper_download"))
        self.download_btn.clicked.connect(self._download_model)
        model_row_layout.addWidget(self.download_btn)

        model_form.addRow(tr("settings_gemini_model") + ":", model_row)

        # Download progress (hidden by default)
        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        model_form.addRow(self.download_progress)

        # Model info
        self.model_info_label = QLabel()
        self.model_info_label.setWordWrap(True)
        self.model_info_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        model_form.addRow(self.model_info_label)

        self.model_combo.currentIndexChanged.connect(self._update_model_info)

        # Model status
        self.model_status_label = QLabel()
        model_form.addRow(self.model_status_label)

        layout.addWidget(model_group)

        # Device selection
        device_group = QGroupBox(tr("settings_whisper_device"))
        device_layout = QFormLayout(device_group)

        self.device_combo = QComboBox()
        self.device_combo.addItem(tr("settings_whisper_device_auto"), "auto")
        self.device_combo.addItem(tr("settings_whisper_device_cpu"), "cpu")
        self.device_combo.addItem(tr("settings_whisper_device_gpu"), "cuda")

        device_layout.addRow(tr("settings_whisper_device") + ":", self.device_combo)

        layout.addWidget(device_group)

        # Check model status
        self._check_model_status()

        layout.addStretch()
        return widget

    def _create_export_tab(self) -> QWidget:
        """Export ayarları sekmesi."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        export_group = QGroupBox(tr("settings_default_export"))
        export_layout = QFormLayout(export_group)

        self.default_export_combo = QComboBox()
        self.default_export_combo.addItem(tr("export_fcp"), "fcpxml")
        self.default_export_combo.addItem(tr("export_premiere"), "premiere")
        self.default_export_combo.addItem(tr("export_resolve"), "edl")

        export_layout.addRow(tr("settings_default_export") + ":", self.default_export_combo)

        layout.addWidget(export_group)
        layout.addStretch()
        return widget

    def _create_appearance_tab(self) -> QWidget:
        """Görünüm ayarları sekmesi."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        theme_group = QGroupBox(tr("settings_theme"))
        theme_layout = QFormLayout(theme_group)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem(tr("settings_theme_system"), "system")
        self.theme_combo.addItem(tr("settings_theme_light"), "light")
        self.theme_combo.addItem(tr("settings_theme_dark"), "dark")

        theme_layout.addRow(tr("settings_theme") + ":", self.theme_combo)

        layout.addWidget(theme_group)

        # Restart warning
        restart_label = QLabel(tr("settings_restart_required"))
        restart_label.setStyleSheet("color: #f0a030; font-size: 11px;")
        layout.addWidget(restart_label)

        layout.addStretch()
        return widget

    def _load_settings(self):
        """Mevcut ayarları yükle."""
        # Language
        lang_index = self.language_combo.findData(self.settings.language)
        if lang_index >= 0:
            self.language_combo.setCurrentIndex(lang_index)

        # Theme
        theme_index = self.theme_combo.findData(self.settings.theme.value)
        if theme_index >= 0:
            self.theme_combo.setCurrentIndex(theme_index)

        # Auto-save
        self.autosave_check.setChecked(self.settings.autosave_enabled)
        self.autosave_interval_spin.setValue(self.settings.autosave_interval_sec)

        # Proxy
        self.proxy_check.setChecked(self.settings.proxy_enabled)
        proxy_index = self.proxy_resolution_combo.findText(self.settings.proxy_resolution)
        if proxy_index >= 0:
            self.proxy_resolution_combo.setCurrentIndex(proxy_index)

        # Whisper model
        model_index = self.model_combo.findData(
            self.settings.default_transcript_model.replace("faster-whisper-", "")
        )
        if model_index >= 0:
            self.model_combo.setCurrentIndex(model_index)

        # Device
        device_index = self.device_combo.findData("auto")
        if self.settings.gpu_acceleration:
            device_index = self.device_combo.findData("auto")
        else:
            device_index = self.device_combo.findData("cpu")
        if device_index >= 0:
            self.device_combo.setCurrentIndex(device_index)

        # Export format
        export_index = self.default_export_combo.findData(self.settings.default_export_format)
        if export_index >= 0:
            self.default_export_combo.setCurrentIndex(export_index)

        self._update_model_info()

        # Gemini
        self.gemini_enabled_check.setChecked(self.settings.gemini_enabled)
        self.gemini_api_key_edit.setText(self.settings.gemini_api_key)

        gemini_model_index = self.gemini_model_combo.findData(self.settings.gemini_model)
        if gemini_model_index >= 0:
            self.gemini_model_combo.setCurrentIndex(gemini_model_index)

        self._on_gemini_toggled(self.settings.gemini_enabled)
        self._update_gemini_status()

    def _apply_settings(self):
        """Ayarları uygula."""
        # Language
        new_lang = self.language_combo.currentData()
        if new_lang != self.settings.language:
            self.settings.language = new_lang
            set_language(new_lang)
            self.language_changed.emit(new_lang)

        # Theme
        new_theme = Theme(self.theme_combo.currentData())
        if new_theme != self.settings.theme:
            self.settings.theme = new_theme
            self.theme_changed.emit(new_theme.value)

        # Auto-save
        self.settings.autosave_enabled = self.autosave_check.isChecked()
        self.settings.autosave_interval_sec = self.autosave_interval_spin.value()

        # Proxy
        self.settings.proxy_enabled = self.proxy_check.isChecked()
        self.settings.proxy_resolution = self.proxy_resolution_combo.currentText()

        # Whisper
        model_id = self.model_combo.currentData()
        self.settings.default_transcript_model = f"faster-whisper-{model_id}"
        self.settings.gpu_acceleration = self.device_combo.currentData() != "cpu"

        # Export
        self.settings.default_export_format = self.default_export_combo.currentData()

        # Gemini
        self.settings.gemini_enabled = self.gemini_enabled_check.isChecked()
        self.settings.gemini_api_key = self.gemini_api_key_edit.text().strip()
        self.settings.gemini_model = self.gemini_model_combo.currentData()

        # Save
        self.settings.save()
        self.settings_saved.emit()

    def _save_and_close(self):
        """Kaydet ve kapat."""
        self._apply_settings()
        self.accept()

    def _update_model_info(self):
        """Model bilgisini güncelle."""
        model_id = self.model_combo.currentData()
        if model_id and model_id in WHISPER_MODELS:
            info = WHISPER_MODELS[model_id]
            # Accuracy translation
            accuracy_map = {
                "Low": "accuracy_low",
                "Medium": "accuracy_medium",
                "Good": "accuracy_good",
                "Best": "accuracy_best",
            }
            acc_key = accuracy_map.get(info['accuracy'], "accuracy_medium")
            acc_text = tr(acc_key)

            text = (
                f"{tr('model_size')}: {info['size']}\n"
                f"{tr('model_speed')}: {info['speed']} ({tr('model_speed_desc')})\n"
                f"{tr('model_accuracy')}: {acc_text}"
            )
            self.model_info_label.setText(text)

    def _check_model_status(self):
        """Model durumunu kontrol et."""
        try:
            from faster_whisper.utils import download_model

            # Cache dizinini kontrol et
            model_id = self.model_combo.currentData() or "medium"

            # Model yüklü mü kontrol et
            try:
                from huggingface_hub import scan_cache_dir
                cache_info = scan_cache_dir()

                model_found = False
                for repo in cache_info.repos:
                    if model_id in repo.repo_id.lower():
                        model_found = True
                        break

                if model_found:
                    self.model_status_label.setText("✅ " + tr("settings_model_ready"))
                    self.model_status_label.setStyleSheet("color: #4caf50;")
                else:
                    self.model_status_label.setText("⚠️ " + tr("settings_model_not_downloaded"))
                    self.model_status_label.setStyleSheet("color: #ff9800;")
            except Exception:
                self.model_status_label.setText("❓ " + tr("settings_status_unknown"))
                self.model_status_label.setStyleSheet("color: #888;")

        except ImportError:
            self.model_status_label.setText("❌ " + tr("settings_whisper_not_installed"))
            self.model_status_label.setStyleSheet("color: #f44336;")
            self.download_btn.setEnabled(False)

    def _download_model(self):
        """Model indir."""
        model_id = self.model_combo.currentData()
        if not model_id:
            return

        # Check if model is already downloaded
        try:
            from huggingface_hub import scan_cache_dir
            cache_info = scan_cache_dir()
            for repo in cache_info.repos:
                if model_id in repo.repo_id.lower():
                    # Model already downloaded
                    QMessageBox.information(
                        self,
                        tr("dialog_info"),
                        tr("settings_model_already_downloaded")
                    )
                    self.model_status_label.setText("✅ " + tr("settings_model_ready"))
                    self.model_status_label.setStyleSheet("color: #4caf50;")
                    return
        except Exception:
            pass  # If check fails, proceed with download

        self.download_btn.setEnabled(False)
        self.download_progress.setVisible(True)
        self.download_progress.setValue(0)
        self.model_status_label.setText(tr("progress_downloading"))

        self._download_thread = ModelDownloadThread(model_id)
        self._download_thread.progress.connect(self.download_progress.setValue)
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.start()

    def _on_download_finished(self, success: bool, error: str):
        """İndirme tamamlandı."""
        self.download_btn.setEnabled(True)
        self.download_progress.setVisible(False)

        if success:
            self.model_status_label.setText("✅ " + tr("settings_model_ready"))
            self.model_status_label.setStyleSheet("color: #4caf50;")
            QMessageBox.information(
                self,
                tr("dialog_info"),
                tr("settings_download_success")
            )
        else:
            self.model_status_label.setText("❌ " + tr("settings_download_failed"))
            self.model_status_label.setStyleSheet("color: #f44336;")
            QMessageBox.critical(
                self,
                tr("dialog_error"),
                tr("error_model_download", error)
            )

        self._download_thread = None

    def _on_gemini_toggled(self, enabled: bool):
        """Gemini toggle edildiğinde UI'ı güncelle."""
        self.gemini_api_key_edit.setEnabled(enabled)
        self.gemini_model_combo.setEnabled(enabled)
        self.show_key_btn.setEnabled(enabled)
        self.test_key_btn.setEnabled(enabled)

        # Whisper'ı devre dışı bırak/etkinleştir
        self.model_combo.setEnabled(not enabled)
        self.download_btn.setEnabled(not enabled)
        self.device_combo.setEnabled(not enabled)

        self._update_gemini_status()

    def _toggle_api_key_visibility(self, show: bool):
        """API key görünürlüğünü değiştir."""
        if show:
            self.gemini_api_key_edit.setEchoMode(QLineEdit.Normal)
            self.show_key_btn.setText(tr("settings_hide_key"))
        else:
            self.gemini_api_key_edit.setEchoMode(QLineEdit.Password)
            self.show_key_btn.setText(tr("settings_show_key"))

    def _update_gemini_status(self):
        """Gemini durum bilgisini güncelle."""
        if not self.gemini_enabled_check.isChecked():
            self.gemini_status_label.setText(tr("settings_gemini_disabled"))
            self.gemini_status_label.setStyleSheet("color: #888;")
            return

        api_key = self.gemini_api_key_edit.text().strip()
        if not api_key:
            self.gemini_status_label.setText(tr("settings_gemini_no_key"))
            self.gemini_status_label.setStyleSheet("color: #ff9800;")
        elif api_key.startswith("AIza"):
            self.gemini_status_label.setText(tr("settings_gemini_key_set"))
            self.gemini_status_label.setStyleSheet("color: #4caf50;")
        else:
            self.gemini_status_label.setText(tr("settings_gemini_invalid_key"))
            self.gemini_status_label.setStyleSheet("color: #f44336;")

    def _test_gemini_key(self):
        """Gemini API key'ini test et."""
        api_key = self.gemini_api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(self, tr("dialog_warning"), tr("settings_gemini_no_key"))
            return

        self.test_key_btn.setEnabled(False)
        self.gemini_status_label.setText(tr("settings_gemini_testing"))
        self.gemini_status_label.setStyleSheet("color: #2196f3;")

        # Test API key with a simple request
        try:
            import urllib.request
            import json

            model = self.gemini_model_combo.currentData()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

            data = json.dumps({
                "contents": [{"parts": [{"text": "Say 'API key works!' in 3 words."}]}]
            }).encode('utf-8')

            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                if "candidates" in result:
                    self.gemini_status_label.setText("✅ " + tr("settings_gemini_key_valid"))
                    self.gemini_status_label.setStyleSheet("color: #4caf50;")
                    QMessageBox.information(self, tr("dialog_info"), tr("settings_gemini_key_valid"))
                else:
                    raise Exception("Invalid response")

        except urllib.error.HTTPError as e:
            if e.code == 400:
                self.gemini_status_label.setText("❌ " + tr("settings_gemini_invalid_key"))
            elif e.code == 403:
                self.gemini_status_label.setText("❌ " + tr("settings_gemini_key_forbidden"))
            else:
                self.gemini_status_label.setText(f"❌ HTTP {e.code}")
            self.gemini_status_label.setStyleSheet("color: #f44336;")
            QMessageBox.critical(self, tr("dialog_error"), f"API Error: {e}")

        except Exception as e:
            self.gemini_status_label.setText(f"❌ {str(e)[:30]}")
            self.gemini_status_label.setStyleSheet("color: #f44336;")
            QMessageBox.critical(self, tr("dialog_error"), str(e))

        finally:
            self.test_key_btn.setEnabled(True)
