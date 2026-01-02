"""
Internationalization (i18n) module.

Türkçe ve İngilizce dil desteği.
"""

from __future__ import annotations

from typing import Optional
import locale

# Desteklenen diller
SUPPORTED_LANGUAGES = {
    "en": "English",
    "tr": "Türkçe",
}

# Çeviriler
TRANSLATIONS = {
    "en": {
        # App
        "app_name": "AutoCut",
        "app_description": "Automatic Silence Removal Tool",

        # Menu
        "menu_file": "&File",
        "menu_edit": "&Edit",
        "menu_view": "&View",
        "menu_help": "&Help",
        "menu_open": "&Open...",
        "menu_save": "&Save Project",
        "menu_save_as": "Save Project &As...",
        "menu_export": "&Export...",
        "menu_settings": "Se&ttings...",
        "menu_quit": "&Quit",
        "menu_undo": "&Undo",
        "menu_redo": "&Redo",
        "menu_zoom_in": "Zoom &In",
        "menu_zoom_out": "Zoom &Out",
        "menu_zoom_fit": "Zoom to &Fit",
        "menu_about": "&About",

        # Toolbar
        "toolbar_open": "Open",
        "toolbar_analyze": "Analyze",
        "toolbar_export": "Export",
        "toolbar_settings": "Settings",

        # Panels
        "panel_media": "Media",
        "panel_settings": "Detection Settings",
        "panel_cuts": "Cuts",
        "panel_transcript": "Transcript",
        "panel_statistics": "Statistics",

        # Media Panel
        "no_file_loaded": "No file loaded",
        "btn_import_video": "Import Video...",
        "btn_import_audio": "Import Audio...",

        # Settings Panel
        "preset": "Preset",
        "threshold": "Threshold",
        "min_duration": "Min Duration",
        "pre_padding": "Pre Padding",
        "post_padding": "Post Padding",
        "merge_gap": "Merge Gap",
        "use_vad": "Use Voice Activity Detection",
        "breath_detection": "Detect Breaths",

        # Presets
        "preset_podcast": "Podcast",
        "preset_tutorial": "Tutorial",
        "preset_meeting": "Meeting",
        "preset_noisy": "Noisy Room",
        "preset_aggressive": "Aggressive",
        "preset_custom": "Custom",

        # Actions
        "btn_analyze": "Analyze Audio",
        "btn_export": "Export Timeline",
        "btn_transcribe": "Transcribe",
        "btn_cancel": "Cancel",
        "btn_ok": "OK",
        "btn_apply": "Apply",
        "btn_reset": "Reset",
        "btn_toggle": "Toggle",
        "btn_delete": "Delete",

        # Timeline
        "timeline_zoom_in": "Zoom In",
        "timeline_zoom_out": "Zoom Out",
        "timeline_fit": "Fit",

        # Statistics
        "stats_original": "Original Duration",
        "stats_removed": "Removed",
        "stats_final": "Final Duration",
        "stats_cuts": "Total Cuts",
        "stats_saved": "Time Saved",

        # Export Dialog
        "export_title": "Export Timeline",
        "export_format": "Export Format",
        "export_fcp": "Final Cut Pro (FCPXML)",
        "export_premiere": "Adobe Premiere Pro (XML)",
        "export_resolve": "DaVinci Resolve (EDL)",
        "export_fcp_hint": "Import in Final Cut Pro via File → Import → XML.\nOriginal media file must be in the same location.",
        "export_premiere_hint": "Import in Premiere Pro via File → Import.\nCan also import from Media Browser.",
        "export_resolve_hint": "Import in DaVinci Resolve via File → Import → Timeline → Import AAF, EDL, XML...\nYou may need to import media first.",
        "export_success": "Export Complete",
        "export_failed": "Export Failed",

        # Dialogs
        "dialog_warning": "Warning",
        "dialog_error": "Error",
        "dialog_info": "Information",
        "dialog_confirm": "Confirm",
        "dialog_unsaved": "Unsaved Changes",
        "dialog_unsaved_msg": "You have unsaved changes. Do you want to save before closing?",

        # Settings Dialog
        "settings_title": "Settings",
        "settings_general": "General",
        "settings_analysis": "Analysis",
        "settings_export": "Export",
        "settings_transcription": "Transcription",
        "settings_appearance": "Appearance",
        "settings_language": "Language",
        "settings_theme": "Theme",
        "settings_theme_system": "System",
        "settings_theme_light": "Light",
        "settings_theme_dark": "Dark",
        "settings_autosave": "Auto-save projects",
        "settings_autosave_interval": "Auto-save interval (seconds)",
        "settings_proxy": "Generate proxy for large files",
        "settings_proxy_resolution": "Proxy resolution",
        "settings_whisper_model": "Whisper Model",
        "settings_whisper_download": "Download Model",
        "settings_whisper_device": "Device",
        "settings_whisper_device_auto": "Auto (GPU if available)",
        "settings_whisper_device_cpu": "CPU",
        "settings_whisper_device_gpu": "GPU (CUDA)",
        "settings_default_export": "Default export format",
        "settings_restart_required": "Restart required for changes to take effect",

        # Whisper Models
        "model_tiny": "Tiny (39 MB) - Fastest, lowest accuracy",
        "model_base": "Base (74 MB) - Fast, low accuracy",
        "model_small": "Small (244 MB) - Balanced",
        "model_medium": "Medium (769 MB) - Good accuracy",
        "model_large": "Large (1550 MB) - Best accuracy, slowest",

        # Progress
        "progress_loading": "Loading...",
        "progress_extracting": "Extracting audio...",
        "progress_analyzing": "Analyzing audio...",
        "progress_generating_waveform": "Generating waveform...",
        "progress_transcribing": "Transcribing...",
        "progress_exporting": "Exporting...",
        "progress_downloading": "Downloading model...",

        # Status
        "status_ready": "Ready",
        "status_loaded": "Loaded: {0}",
        "status_analyzing": "Analyzing...",
        "status_found_cuts": "Found {0} silence regions",
        "status_exported": "Exported: {0}",
        "status_saved": "Saved: {0}",

        # Errors
        "error_ffmpeg_not_found": "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH.",
        "error_ffmpeg_install": "Install FFmpeg:\n• macOS: brew install ffmpeg\n• Windows: choco install ffmpeg\n• Ubuntu: sudo apt install ffmpeg",
        "error_file_not_found": "File not found: {0}",
        "error_invalid_file": "Invalid or corrupted file: {0}",
        "error_no_audio": "No audio track found in file",
        "error_analysis_failed": "Analysis failed: {0}",
        "error_export_failed": "Export failed: {0}",
        "error_model_download": "Failed to download model: {0}",

        # About
        "about_title": "About AutoCut",
        "about_text": "AutoCut v{0}\n\nAutomatic silence removal and NLE export tool.\n\nSupports:\n• Final Cut Pro (FCPXML)\n• Adobe Premiere Pro (XML)\n• DaVinci Resolve (EDL)\n\n© 2024 AutoCut",
    },

    "tr": {
        # App
        "app_name": "AutoCut",
        "app_description": "Otomatik Sessizlik Kaldırma Aracı",

        # Menu
        "menu_file": "&Dosya",
        "menu_edit": "Düzen&le",
        "menu_view": "&Görünüm",
        "menu_help": "&Yardım",
        "menu_open": "&Aç...",
        "menu_save": "Projeyi &Kaydet",
        "menu_save_as": "Projeyi &Farklı Kaydet...",
        "menu_export": "&Dışa Aktar...",
        "menu_settings": "&Ayarlar...",
        "menu_quit": "&Çıkış",
        "menu_undo": "&Geri Al",
        "menu_redo": "&İleri Al",
        "menu_zoom_in": "Yakınlaştır",
        "menu_zoom_out": "Uzaklaştır",
        "menu_zoom_fit": "Sığdır",
        "menu_about": "&Hakkında",

        # Toolbar
        "toolbar_open": "Aç",
        "toolbar_analyze": "Analiz Et",
        "toolbar_export": "Dışa Aktar",
        "toolbar_settings": "Ayarlar",

        # Panels
        "panel_media": "Medya",
        "panel_settings": "Tespit Ayarları",
        "panel_cuts": "Kesimler",
        "panel_transcript": "Transkript",
        "panel_statistics": "İstatistikler",

        # Media Panel
        "no_file_loaded": "Dosya yüklenmedi",
        "btn_import_video": "Video İçe Aktar...",
        "btn_import_audio": "Ses İçe Aktar...",

        # Settings Panel
        "preset": "Ön Ayar",
        "threshold": "Eşik Değeri",
        "min_duration": "Min Süre",
        "pre_padding": "Ön Boşluk",
        "post_padding": "Son Boşluk",
        "merge_gap": "Birleştirme Aralığı",
        "use_vad": "Ses Aktivite Tespiti Kullan",
        "breath_detection": "Nefes Tespiti",

        # Presets
        "preset_podcast": "Podcast",
        "preset_tutorial": "Eğitim Videosu",
        "preset_meeting": "Toplantı",
        "preset_noisy": "Gürültülü Ortam",
        "preset_aggressive": "Agresif",
        "preset_custom": "Özel",

        # Actions
        "btn_analyze": "Sesi Analiz Et",
        "btn_export": "Timeline'ı Dışa Aktar",
        "btn_transcribe": "Transkript Çıkar",
        "btn_cancel": "İptal",
        "btn_ok": "Tamam",
        "btn_apply": "Uygula",
        "btn_reset": "Sıfırla",
        "btn_toggle": "Aç/Kapat",
        "btn_delete": "Sil",

        # Timeline
        "timeline_zoom_in": "Yakınlaştır",
        "timeline_zoom_out": "Uzaklaştır",
        "timeline_fit": "Sığdır",

        # Statistics
        "stats_original": "Orijinal Süre",
        "stats_removed": "Kaldırılan",
        "stats_final": "Son Süre",
        "stats_cuts": "Toplam Kesim",
        "stats_saved": "Kazanılan Zaman",

        # Export Dialog
        "export_title": "Timeline'ı Dışa Aktar",
        "export_format": "Dışa Aktarma Formatı",
        "export_fcp": "Final Cut Pro (FCPXML)",
        "export_premiere": "Adobe Premiere Pro (XML)",
        "export_resolve": "DaVinci Resolve (EDL)",
        "export_fcp_hint": "Final Cut Pro'da Dosya → İçe Aktar → XML ile açın.\nOrijinal medya dosyası aynı konumda olmalıdır.",
        "export_premiere_hint": "Premiere Pro'da Dosya → İçe Aktar ile açın.\nMedia Browser'dan da içe aktarabilirsiniz.",
        "export_resolve_hint": "DaVinci Resolve'da Dosya → İçe Aktar → Timeline → AAF, EDL, XML İçe Aktar...\nÖnce medya dosyasını içe aktarmanız gerekebilir.",
        "export_success": "Dışa Aktarma Tamamlandı",
        "export_failed": "Dışa Aktarma Başarısız",

        # Dialogs
        "dialog_warning": "Uyarı",
        "dialog_error": "Hata",
        "dialog_info": "Bilgi",
        "dialog_confirm": "Onay",
        "dialog_unsaved": "Kaydedilmemiş Değişiklikler",
        "dialog_unsaved_msg": "Kaydedilmemiş değişiklikleriniz var. Kapatmadan önce kaydetmek ister misiniz?",

        # Settings Dialog
        "settings_title": "Ayarlar",
        "settings_general": "Genel",
        "settings_analysis": "Analiz",
        "settings_export": "Dışa Aktarma",
        "settings_transcription": "Transkripsiyon",
        "settings_appearance": "Görünüm",
        "settings_language": "Dil",
        "settings_theme": "Tema",
        "settings_theme_system": "Sistem",
        "settings_theme_light": "Açık",
        "settings_theme_dark": "Koyu",
        "settings_autosave": "Projeleri otomatik kaydet",
        "settings_autosave_interval": "Otomatik kaydetme aralığı (saniye)",
        "settings_proxy": "Büyük dosyalar için proxy oluştur",
        "settings_proxy_resolution": "Proxy çözünürlüğü",
        "settings_whisper_model": "Whisper Modeli",
        "settings_whisper_download": "Modeli İndir",
        "settings_whisper_device": "Cihaz",
        "settings_whisper_device_auto": "Otomatik (varsa GPU)",
        "settings_whisper_device_cpu": "CPU",
        "settings_whisper_device_gpu": "GPU (CUDA)",
        "settings_default_export": "Varsayılan dışa aktarma formatı",
        "settings_restart_required": "Değişikliklerin geçerli olması için yeniden başlatma gerekli",

        # Whisper Models
        "model_tiny": "Tiny (39 MB) - En hızlı, düşük doğruluk",
        "model_base": "Base (74 MB) - Hızlı, düşük doğruluk",
        "model_small": "Small (244 MB) - Dengeli",
        "model_medium": "Medium (769 MB) - İyi doğruluk",
        "model_large": "Large (1550 MB) - En iyi doğruluk, en yavaş",

        # Progress
        "progress_loading": "Yükleniyor...",
        "progress_extracting": "Ses çıkarılıyor...",
        "progress_analyzing": "Ses analiz ediliyor...",
        "progress_generating_waveform": "Dalga formu oluşturuluyor...",
        "progress_transcribing": "Transkript çıkarılıyor...",
        "progress_exporting": "Dışa aktarılıyor...",
        "progress_downloading": "Model indiriliyor...",

        # Status
        "status_ready": "Hazır",
        "status_loaded": "Yüklendi: {0}",
        "status_analyzing": "Analiz ediliyor...",
        "status_found_cuts": "{0} sessiz bölge bulundu",
        "status_exported": "Dışa aktarıldı: {0}",
        "status_saved": "Kaydedildi: {0}",

        # Errors
        "error_ffmpeg_not_found": "FFmpeg bulunamadı. Lütfen FFmpeg'i kurun ve PATH'e ekleyin.",
        "error_ffmpeg_install": "FFmpeg Kurulumu:\n• macOS: brew install ffmpeg\n• Windows: choco install ffmpeg\n• Ubuntu: sudo apt install ffmpeg",
        "error_file_not_found": "Dosya bulunamadı: {0}",
        "error_invalid_file": "Geçersiz veya bozuk dosya: {0}",
        "error_no_audio": "Dosyada ses kanalı bulunamadı",
        "error_analysis_failed": "Analiz başarısız: {0}",
        "error_export_failed": "Dışa aktarma başarısız: {0}",
        "error_model_download": "Model indirme başarısız: {0}",

        # About
        "about_title": "AutoCut Hakkında",
        "about_text": "AutoCut v{0}\n\nOtomatik sessizlik kaldırma ve NLE dışa aktarma aracı.\n\nDesteklenen formatlar:\n• Final Cut Pro (FCPXML)\n• Adobe Premiere Pro (XML)\n• DaVinci Resolve (EDL)\n\n© 2024 AutoCut",
    },
}


class Translator:
    """Çeviri yöneticisi."""

    _instance: Optional[Translator] = None
    _current_language: str = "en"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> Translator:
        """Singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def language(self) -> str:
        return self._current_language

    @language.setter
    def language(self, lang: str):
        if lang in SUPPORTED_LANGUAGES:
            self._current_language = lang

    def set_language(self, lang: str):
        """Dili ayarla."""
        self.language = lang

    def detect_system_language(self) -> str:
        """Sistem dilini tespit et."""
        try:
            sys_locale = locale.getdefaultlocale()[0]
            if sys_locale:
                lang_code = sys_locale.split("_")[0].lower()
                if lang_code in SUPPORTED_LANGUAGES:
                    return lang_code
        except Exception:
            pass
        return "en"

    def get(self, key: str, *args) -> str:
        """
        Çeviri al.

        Args:
            key: Çeviri anahtarı
            *args: Format argümanları

        Returns:
            Çevrilmiş metin
        """
        translations = TRANSLATIONS.get(self._current_language, TRANSLATIONS["en"])
        text = translations.get(key, TRANSLATIONS["en"].get(key, key))

        if args:
            try:
                return text.format(*args)
            except (IndexError, KeyError):
                return text

        return text

    def __call__(self, key: str, *args) -> str:
        """Kısayol: tr("key")"""
        return self.get(key, *args)


# Global translator instance
_translator = Translator.get_instance()


def tr(key: str, *args) -> str:
    """
    Çeviri fonksiyonu.

    Kullanım:
        from app.core.i18n import tr
        label.setText(tr("btn_analyze"))
        status.setText(tr("status_found_cuts", 5))
    """
    return _translator.get(key, *args)


def set_language(lang: str):
    """Dili ayarla."""
    _translator.set_language(lang)


def get_language() -> str:
    """Mevcut dili al."""
    return _translator.language


def get_supported_languages() -> dict[str, str]:
    """Desteklenen dilleri al."""
    return SUPPORTED_LANGUAGES.copy()


def detect_system_language() -> str:
    """Sistem dilini tespit et."""
    return _translator.detect_system_language()
