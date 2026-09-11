# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
import copy
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QLibraryInfo, QMimeData, QSignalBlocker, QSize, Qt, QTimer, QTranslator, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QDrag, QFont, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Re-export the engine API from the public entry module. Existing integrations
# and the security test-suite can keep importing ``mkv_creator_ui``.
from src.gtmce import core as _core
from src.gtmce.core import *  # noqa: F401,F403
from src.gtmce.controller import GTMCEControllerMixin


def load_saved_preferences() -> dict[str, str]:
    # Keep the public module-level SETTINGS_PATH override behavior used by the
    # existing tests/integrations even though the engine now lives in src/gtmce.
    _core.SETTINGS_PATH = SETTINGS_PATH
    return _core.load_saved_preferences()


def save_saved_preferences(values: dict[str, Any]) -> None:
    _core.SETTINGS_PATH = SETTINGS_PATH
    _core.save_saved_preferences(values)
from src.gtmce.theme import build_stylesheet, palette_for, theme_toggle_icon


class ValueVar:
    """Small Tk-like value holder used by the proven workflow logic.

    Keeping get()/set() means the media pipeline can remain unchanged while the
    presentation layer is native Qt. Widgets are bound to it with Qt signals.
    """

    def __init__(self, value: Any = "") -> None:
        self._value = value
        self._callbacks: list[Callable[..., Any]] = []
        self._listeners: list[Callable[[Any], Any]] = []

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        if value == self._value:
            return
        self._value = value
        for callback in list(self._listeners):
            try:
                callback(value)
            except RuntimeError:
                # Qt wrapper was deleted with its dialog; drop the stale binding.
                try:
                    self._listeners.remove(callback)
                except ValueError:
                    pass
        for callback in list(self._callbacks):
            try:
                callback("", "", "write")
            except TypeError:
                callback()
            except RuntimeError:
                try:
                    self._callbacks.remove(callback)
                except ValueError:
                    pass

    def trace_add(self, _mode: str, callback: Callable[..., Any]) -> str:
        self._callbacks.append(callback)
        return str(id(callback))

    def bind(self, callback: Callable[[Any], Any]) -> None:
        self._listeners.append(callback)
        callback(self._value)


class MuxTracksTable(QTableWidget):
    """QTableWidget with safe row/file drops for the mux dialog.

    Native QTableWidget ``InternalMove`` moves QTableWidgetItem objects but does
    not reliably move widgets installed with ``setCellWidget()``.  The mux
    table contains checkboxes, line edits and append controls, so letting Qt do
    the default move visually scrambles the row after a drop.  Intercept the
    drop and ask the owner to reorder the row models, then rebuild the table.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.row_move_callback: Callable[[int, int], Any] | None = None
        self.file_drop_callback: Callable[[list[Path]], Any] | None = None
        self._drag_source_row = -1

    INTERNAL_ROW_MIME = "application/x-gtmce-mux-row"

    def startDrag(self, _supported_actions: Any) -> None:
        """Start an internal row drag without giving QTableWidget a MoveAction.

        QAbstractItemView may delete source rows after a successful MoveAction.
        We only use the drag gesture to choose a destination; the owner reorders
        its row models and rebuilds the table.  A CopyAction therefore prevents
        Qt from removing the freshly rebuilt source row behind our back.
        """
        source = self.currentRow()
        if source < 0:
            return
        self._drag_source_row = source
        mime = QMimeData()
        mime.setData(self.INTERNAL_ROW_MIME, str(source).encode("ascii"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction, Qt.CopyAction)
        self._drag_source_row = -1

    def dragEnterEvent(self, event: Any) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
            return
        if mime is not None and mime.hasFormat(self.INTERNAL_ROW_MIME):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
            return
        if mime is not None and mime.hasFormat(self.INTERNAL_ROW_MIME):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event: Any) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            paths: list[Path] = []
            for url in mime.urls():
                local = str(url.toLocalFile() or "").strip()
                if local:
                    paths.append(Path(local))
            if paths and self.file_drop_callback is not None:
                self.file_drop_callback(paths)
                event.acceptProposedAction()
                return

        source = self._drag_source_row if self._drag_source_row >= 0 else self.currentRow()
        point = event.position().toPoint()
        index = self.indexAt(point)
        if index.isValid():
            target = index.row()
            # Drop in the lower half means insert after the hovered row.
            if point.y() > self.visualRect(index).center().y():
                target += 1
        else:
            target = self.rowCount()

        if source >= 0 and self.row_move_callback is not None:
            # Convert insertion position from pre-removal coordinates.
            if target > source:
                target -= 1
            self.row_move_callback(source, target)
            self._drag_source_row = -1
            # Internal row moves are model-only. Never return MoveAction to
            # QAbstractItemView or it may remove a row after our rebuild.
            if mime is not None and mime.hasFormat(self.INTERNAL_ROW_MIME):
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                event.acceptProposedAction()
            return

        # Never allow the default QTableWidget internal move for this table: it
        # can detach/misplace setCellWidget() editors.
        event.ignore()


class MkvCreatorApp(GTMCEControllerMixin, QMainWindow):
    """PySide6/Qt 6 user interface for the G-TMCE media engine."""

    def __init__(self, initial_extract_source: Path | None = None) -> None:
        QMainWindow.__init__(self)
        self.saved_preferences = load_saved_preferences()
        self.ui_language_var = ValueVar(
            normalise_ui_language(self.saved_preferences.get("ui_language", "en"))
        )
        self.ui_language_display_var = ValueVar(UI_LANGUAGE_NAMES[self.ui_language_var.get()])
        set_active_ui_language(self.ui_language_var.get())
        self.qt_translator = QTranslator(self)
        self.apply_qt_language()
        self.theme_mode = str(self.saved_preferences.get("theme", "dark")).lower()
        if self.theme_mode not in {"dark", "light"}:
            self.theme_mode = "dark"

        self.log_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.log_lines: list[str] = []
        self.worker: threading.Thread | None = None
        self.app_update_thread: threading.Thread | None = None
        self.app_update_url = APP_LATEST_RELEASE_URL
        self.current_operation: str | None = None
        self.cancel_event = threading.Event()
        self.active_processes: set[subprocess.Popen[Any]] = set()
        self.active_processes_lock = threading.Lock()
        self.last_mkv_dir = self.saved_preferences.get("last_mkv_dir", "")

        # Workflow state. The names intentionally match the original engine's
        # controller variables so all validated mux/extract logic is reusable.
        self.template_var = ValueVar("")
        self.folder_var = ValueVar("")
        self.output_var = ValueVar("")
        self.output_name_extra_var = ValueVar(self.saved_preferences.get("output_name_extra", ""))
        self.output_name_year_var = ValueVar(
            self.saved_preferences.get("output_name_year", "false") == "true"
        )
        self.current_output_name_extra = self.output_name_extra_var.get()
        self.extract_source_var = ValueVar("")
        self.extract_output_dir_var = ValueVar("")
        self.extract_items: dict[str, ExtractItem] = {}
        self.api_key_var = ValueVar(os.environ.get("TMDB_API_KEY", self.saved_preferences.get("api_key", "")))
        self.subtitle_api_key_var = ValueVar(
            os.environ.get("OPENSUBTITLES_API_KEY", self.saved_preferences.get("opensubtitles_api_key", ""))
        )
        self.subtitle_username_var = ValueVar(
            os.environ.get("OPENSUBTITLES_USERNAME", self.saved_preferences.get("opensubtitles_username", ""))
        )
        self.subtitle_password_var = ValueVar(
            os.environ.get("OPENSUBTITLES_PASSWORD", self.saved_preferences.get("opensubtitles_password", ""))
        )
        self.subtitle_language_var = ValueVar(self.saved_preferences.get("subtitle_download_language", ""))
        self.subtitle_query_var = ValueVar("")
        self.subtitle_status_var = ValueVar("")
        self.subtitle_show_password_var = ValueVar(False)
        self.tmdb_search_query_var = ValueVar("")
        self.tmdb_search_status_var = ValueVar("")
        self.tmdb_id_var = ValueVar("")
        self.media_type_var = ValueVar(normalise_tmdb_media_type(self.saved_preferences.get("media_type", "movie")))
        self.media_type_display_var = ValueVar("")
        self.language_var = ValueVar(self.saved_preferences.get("image_language", "en"))
        self.tag_language_var = ValueVar(
            self.saved_preferences.get("tag_language", self.saved_preferences.get("image_language", "en"))
        )
        self.title_var = ValueVar("")
        self.video_fps_var = ValueVar(self.saved_preferences.get("video_fps", ""))
        self.audio_language_order_var = ValueVar(self.saved_preferences.get("audio_language_order", ""))
        self.subtitle_language_order_var = ValueVar(self.saved_preferences.get("subtitle_language_order", ""))
        self.include_extra_subs_var = ValueVar(True)
        self.add_tracks_before_mux_var = ValueVar(False)
        self.download_before_mux_var = ValueVar(True)
        self.context_menu_enabled_var = ValueVar(
            self.saved_preferences.get("context_menu_enabled", "false") == "true"
        )
        self.mux_tracks_download_missing_assets_var = ValueVar(False)
        self.auto_chapters_var = ValueVar(self.saved_preferences.get("auto_chapters", "false") == "true")
        self.auto_chapter_detect_intro_var = ValueVar(
            self.saved_preferences.get("auto_chapter_detect_intro", "false") == "true"
        )
        self.chapter_interval_var = ValueVar(self.saved_preferences.get("chapter_interval_minutes", "10"))
        self.chapter_name_var = ValueVar(self.saved_preferences.get("chapter_name", ""))
        self.chapter_start_var = ValueVar(self.saved_preferences.get("chapter_start_number", "1"))
        self.chapter_end_var = ValueVar(self.saved_preferences.get("chapter_end_minutes", ""))
        self.auto_chapter_end_value = str(self.chapter_end_var.get()).strip()
        self.show_api_key_var = ValueVar(False)
        self.progress_var = ValueVar(0.0)
        self.progress_status_var = ValueVar(self.tr("status_ready"))
        self.batch_operation_current_var = ValueVar("")
        self.audio_adjust_current_var = ValueVar("")

        # Dialog/model state.
        self.extract_window: QDialog | None = None
        self.extract_tree: QTableWidget | None = None
        self.extract_progress_bar: QProgressBar | None = None
        self.extract_language_vars: dict[str, ValueVar] = {}
        self.extract_language_output_vars: dict[str, ValueVar] = {}
        self.audio_adjust_window: QDialog | None = None
        self.audio_adjust_apply_button: QPushButton | None = None
        self.audio_adjust_apply_all_button: QPushButton | None = None
        self.audio_adjust_progress_bar: QProgressBar | None = None
        self.audio_adjust_rows: list[dict[str, Any]] = []
        self.audio_adjust_rows_by_episode: dict[str, list[dict[str, Any]]] = {}
        self.audio_adjust_tabs: QTabWidget | None = None
        self.audio_adjust_groups: list[tuple[str, list[Any], str]] = []
        self.audio_adjust_batch_mode = False
        self.audio_adjust_presets_by_episode: dict[str, dict[str, dict[str, Any]]] = {}
        self.audio_adjust_skipped_unchanged_count = 0
        self.audio_adjust_episode_labels_by_dir: dict[str, str] = {}
        self.subtitle_window: QDialog | None = None
        self.subtitle_progress_bar: QProgressBar | None = None
        self.subtitle_results_tree: QTableWidget | None = None
        self.subtitle_results_tabs: QTabWidget | None = None
        self.subtitle_results_trees_by_target: dict[int, QTableWidget] = {}
        self.subtitle_search_button: QPushButton | None = None
        self.tmdb_search_window: QDialog | None = None
        self.tmdb_search_tree: QTableWidget | None = None
        self.tmdb_lookup_button: QPushButton | None = None
        self.tmdb_search_action_button: QPushButton | None = None
        self.tmdb_search_results: list[dict[str, Any]] = []
        self.subtitle_download_button: QPushButton | None = None
        self.subtitle_best_button: QPushButton | None = None
        self.subtitle_password_entry: QLineEdit | None = None
        self.subtitle_targets: list[SubtitleSearchTarget] = []
        self.subtitle_results: dict[str, SubtitleResult] = {}
        self.subtitle_downloaded_paths: dict[str, Path] = {}
        self.subtitle_session_key: tuple[str, ...] = ()
        self.subtitle_sessions: dict[tuple[str, ...], tuple[str, str, dict[str, SubtitleResult], dict[str, Path]]] = {}
        self.subtitle_batch_mode = False
        self.mux_tracks_window: QDialog | None = None
        self.mux_tracks_tree: QTableWidget | None = None
        self.mux_tracks_tabs: QTabWidget | None = None
        self.mux_tracks_rows_by_episode: dict[str, dict[str, MuxTrackWindowRow]] = {}
        self.mux_track_source_keys_by_episode: dict[str, set[str]] = {}
        self.mux_track_auto_excluded_append_keys_by_episode: dict[str, set[str]] = {}
        self.mux_batch_tasks: list[BatchEpisodeTask] = []
        self.mux_batch_settings: AppSettings | None = None
        self.batch_mux_track_customizations: dict[str, tuple[
            list[AdditionalMuxTrack], list[str], dict[str, str], dict[str, str],
            dict[str, tuple[Path, ...]], set[str], list[AdditionalMuxAsset], bool,
        ]] = {}
        self.mux_tracks_toggle_button: QPushButton | None = None
        self.mux_tracks_rows_by_iid: dict[str, MuxTrackWindowRow] = {}
        self.mux_tracks_selected_iid: str | None = None
        self.additional_mux_tracks: list[AdditionalMuxTrack] = []
        self.mux_track_order_keys: list[str] = []
        self.mux_track_language_overrides: dict[str, str] = {}
        self.mux_track_delay_overrides: dict[str, str] = {}
        self.mux_track_append_overrides: dict[str, tuple[Path, ...]] = {}
        self.mux_track_excluded_keys: set[str] = set()
        self.mux_track_source_keys: set[str] = set()
        # Rows disabled automatically because that file is consumed as an append
        # source by another track. Keeping this separate from user exclusions lets
        # us restore the checkbox when the append is removed.
        self.mux_track_auto_excluded_append_keys: set[str] = set()
        self.additional_mux_assets: list[AdditionalMuxAsset] = []
        self.mux_track_download_missing_assets = False
        self.log_window: QDialog | None = None
        self.log_window_text: QPlainTextEdit | None = None
        self.log_progress_bar: QProgressBar | None = None
        self.log_progress_label: QLabel | None = None

        # Main controls referenced by the workflow layer.
        self.scan_button: QPushButton | None = None
        self.find_tmdb_button: QPushButton | None = None
        self.download_button: QPushButton | None = None
        self.subtitle_button: QPushButton | None = None
        self.config_button: QPushButton | None = None
        self.mux_button: QPushButton | None = None
        self.extract_scan_button: QPushButton | None = None
        self.extract_toggle_button: QPushButton | None = None
        self.extract_all_button: QPushButton | None = None
        self.extract_button: QPushButton | None = None
        self.batch_extract_button: QPushButton | None = None
        self.batch_mux_button: QPushButton | None = None
        self.third_party_button: QPushButton | None = None
        self.app_update_button: QPushButton | None = None
        self.download_before_mux_checkbutton: QCheckBox | None = None
        self.context_menu_check: QCheckBox | None = None
        self.media_type_combobox: QComboBox | None = None
        self.progress_bar: QProgressBar | None = None

        self._localized: list[tuple[Any, str, str]] = []
        self._bound_widgets: list[Any] = []
        self._dialog_progress_labels: list[QLabel] = []
        self._progress_bars: list[QProgressBar] = []
        self._toast_widget: QFrame | None = None

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self._build_ui()
        self.apply_theme()
        self._resize_for_available_screen()
        self.refresh_tmdb_media_type_display()
        self.update_download_before_mux_state()

        self.api_key_var.trace_add("write", self.on_api_key_changed)
        self.output_name_extra_var.trace_add("write", self.on_output_name_extra_changed)
        self.extract_source_var.trace_add("write", self.on_extract_source_changed)
        self.update_extract_source_mode()

        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._drain_log_queue)
        self._queue_timer.start(100)
        QTimer.singleShot(0, self.sync_context_menu_on_startup)
        QTimer.singleShot(800, self.start_check_app_update)
        # Defer Open-With extraction until the top-level Qt window has actually
        # received its first show event.  A QTimer owned by the window is more
        # reliable on KDE/Wayland than a free-standing singleShot scheduled from
        # main(), and mirrors the proven Tkinter startup flow: build UI first,
        # then set the source with scan=True.
        self.initial_extract_source = initial_extract_source
        self._initial_extract_started = False
        self._initial_extract_timer = QTimer(self)
        self._initial_extract_timer.setSingleShot(True)
        self._initial_extract_timer.timeout.connect(self._open_pending_initial_extract)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        if (
            self.initial_extract_source is not None
            and not self._initial_extract_started
            and not self._initial_extract_timer.isActive()
        ):
            # Give the compositor one event-loop turn to map/activate the main
            # window before creating its window-modal Extract child.
            self._initial_extract_timer.start(75)

    def _open_pending_initial_extract(self) -> None:
        source = self.initial_extract_source
        if source is None or self._initial_extract_started:
            return
        self._initial_extract_started = True
        self.initial_extract_source = None
        # Keep the startup path on the same dialog-first flow as an explicit
        # Open-With action.  Calling set_extract_source(..., scan=True) here
        # starts the identify job before the dialog is reliably mapped; on
        # KDE/Wayland that can leave only the main window visible.
        self.open_initial_extract_source(source)

    # ------------------------------------------------------------------
    # Qt/value binding helpers
    # ------------------------------------------------------------------
    def tr(self, key: str, **values: Any) -> str:
        return ui_text(key, **values)

    def _bind_line(self, variable: ValueVar, widget: QLineEdit) -> QLineEdit:
        variable.bind(lambda value: self._set_line_text(widget, value))
        widget.textChanged.connect(variable.set)
        self._bound_widgets.append(widget)
        return widget

    @staticmethod
    def _set_line_text(widget: QLineEdit, value: Any) -> None:
        text = str(value if value is not None else "")
        if widget.text() == text:
            return
        blocker = QSignalBlocker(widget)
        widget.setText(text)
        del blocker

    def _bind_check(self, variable: ValueVar, widget: QCheckBox) -> QCheckBox:
        variable.bind(lambda value: self._set_check(widget, bool(value)))
        widget.toggled.connect(variable.set)
        self._bound_widgets.append(widget)
        return widget

    @staticmethod
    def _set_check(widget: QCheckBox, value: bool) -> None:
        if widget.isChecked() == value:
            return
        blocker = QSignalBlocker(widget)
        widget.setChecked(value)
        del blocker

    def _bind_combo_text(self, variable: ValueVar, widget: QComboBox) -> QComboBox:
        variable.bind(lambda value: self._set_combo_text(widget, str(value)))
        widget.currentTextChanged.connect(variable.set)
        self._bound_widgets.append(widget)
        return widget

    @staticmethod
    def _set_combo_text(widget: QComboBox, value: str) -> None:
        index = widget.findText(value)
        blocker = QSignalBlocker(widget)
        if index >= 0:
            widget.setCurrentIndex(index)
        elif widget.isEditable():
            widget.setEditText(value)
        del blocker

    def localize_widget(self, widget: Any, key: str, option: str = "text") -> Any:
        self._localized.append((widget, key, option))
        self._apply_localized_widget(widget, key, option)
        return widget

    def _apply_localized_widget(self, widget: Any, key: str, option: str) -> None:
        text = self.tr(key)
        if option == "placeholder" and hasattr(widget, "setPlaceholderText"):
            widget.setPlaceholderText(text)
        elif hasattr(widget, "setText"):
            widget.setText(text)
        elif hasattr(widget, "setTitle"):
            widget.setTitle(text)

    def refresh_localized_text(self) -> None:
        for widget, key, option in list(self._localized):
            try:
                self._apply_localized_widget(widget, key, option)
            except RuntimeError:
                pass
        self.refresh_tmdb_media_type_display()
        if self.subtitle_window is not None:
            self._refresh_subtitle_headers()
        if self.tmdb_search_window is not None:
            self._refresh_tmdb_headers()
        if self.extract_window is not None:
            self._refresh_extract_headers()
        if self.audio_adjust_window is not None:
            self._refresh_audio_headers()
        self.update_mux_track_toggle_button_text()
        self.update_audio_adjust_apply_button_text()
        self.update_extract_source_mode()

    def _resize_for_available_screen(self) -> None:
        """Choose a compact launch size without consuming most of the desktop.

        The create workflow remains visible at launch while the MKV Extract card
        stays below the scroll viewport.  Users can still freely resize the
        window; the form layouts stretch with the available width.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT)
            return
        available = screen.availableGeometry()
        target_width = min(
            MAIN_WINDOW_WIDTH,
            max(MAIN_WINDOW_MIN_WIDTH, int(available.width() * 0.78)),
        )
        target_height = min(
            MAIN_WINDOW_HEIGHT,
            max(MAIN_WINDOW_MIN_HEIGHT, int(available.height() * 0.72)),
        )
        self.resize(target_width, target_height)

    # ------------------------------------------------------------------
    # Theme and shared widgets
    # ------------------------------------------------------------------
    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyle("Fusion")
            app.setStyleSheet(build_stylesheet(self.theme_mode))
        if hasattr(self, "theme_button"):
            switch_to = "light" if self.theme_mode == "dark" else "dark"
            self.theme_button.setText("")
            self.theme_button.setIcon(theme_toggle_icon(self.theme_mode))
            self.theme_button.setIconSize(QSize(22, 22))
            tooltip_key = (
                "tooltip_switch_to_light_theme"
                if switch_to == "light"
                else "tooltip_switch_to_dark_theme"
            )
            tooltip = self.tr(tooltip_key)
            self.theme_button.setToolTip(tooltip)
            self.theme_button.setAccessibleName(tooltip)

    def toggle_theme(self) -> None:
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self.apply_theme()
        self.save_preferences()

    def sync_context_menu_on_startup(self) -> None:
        """Refresh the stable launcher only after the user has opted in once."""
        if not self.context_menu_enabled_var.get() or not context_menu_integration_supported():
            return
        errors = install_context_menu_integration()
        if errors:
            self.queue_log("\n".join(errors))

    def on_context_menu_toggled(self, enabled: bool) -> None:
        if not context_menu_integration_supported():
            if self.context_menu_check is not None:
                self._set_check(self.context_menu_check, False)
            self.context_menu_enabled_var.set(False)
            self.show_error(self.tr("dialog_error_title"), self.tr("tooltip_context_menu_unavailable"))
            return

        errors = (
            install_context_menu_integration()
            if enabled
            else uninstall_context_menu_integration()
        )
        if errors:
            if self.context_menu_check is not None:
                self._set_check(self.context_menu_check, not enabled)
            self.context_menu_enabled_var.set(not enabled)
            self.show_error(self.tr("dialog_error_title"), "\n".join(errors))
            return
        self.save_preferences()

    def _card(self, object_name: str = "Card") -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName(object_name)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        return frame, layout

    def _section_header(self, key: str) -> QWidget:
        row = QWidget()
        row.setObjectName("Header")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        marker = QLabel()
        marker.setObjectName("SectionMarker")
        marker.setFixedSize(4, 21)
        title = QLabel()
        title.setObjectName("SectionTitle")
        self.localize_widget(title, key)
        layout.addWidget(marker)
        layout.addWidget(title)
        layout.addStretch(1)
        return row

    def _field_label(self, key: str) -> QLabel:
        label = QLabel()
        label.setObjectName("FieldLabel")
        self.localize_widget(label, key)
        return label

    def _button(self, key: str, callback: Callable[[], Any], *, primary: bool = False, ghost: bool = False) -> QPushButton:
        button = QPushButton()
        if primary:
            button.setObjectName("PrimaryButton")
        elif ghost:
            button.setObjectName("GhostButton")
        self.localize_widget(button, key)
        button.clicked.connect(callback)
        return button

    def show_toast(self, message: str, *, success: bool = True) -> None:
        """Show a brief in-context confirmation without interrupting the modal."""
        parent = self.audio_adjust_window or self
        if self._toast_widget is not None:
            self._toast_widget.deleteLater()
        toast = QFrame(parent)
        toast.setObjectName("ToastSuccess" if success else "ToastError")
        toast.setFrameShape(QFrame.StyledPanel)
        row = QHBoxLayout(toast); row.setContentsMargins(12, 8, 12, 8)
        label = QLabel(message); label.setWordWrap(True); label.setMaximumWidth(460)
        row.addWidget(label)
        toast.adjustSize()
        toast.move(max(12, parent.width() - toast.width() - 20), max(12, parent.height() - toast.height() - 20))
        toast.show(); toast.raise_()
        self._toast_widget = toast
        QTimer.singleShot(4200, lambda current=toast: self._hide_toast(current))

    def _hide_toast(self, toast: QFrame) -> None:
        if self._toast_widget is toast:
            self._toast_widget = None
        toast.deleteLater()

    def _main_progress_block(self, parent_layout: QVBoxLayout) -> None:
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(float(self.progress_var.get())))
        self._progress_bars.append(self.progress_bar)
        self.progress_var.bind(lambda value: self._set_progress_value(self.progress_bar, value))
        parent_layout.addWidget(self.progress_bar)
        status = QLabel()
        status.setObjectName("StatusText")
        status.setWordWrap(False)
        self.progress_status_var.bind(lambda value: status.setText(str(value)))
        parent_layout.addWidget(status)
        current = QLabel()
        current.setObjectName("Muted")
        current.setWordWrap(True)
        self.batch_operation_current_var.bind(lambda value: current.setText(str(value)))
        parent_layout.addWidget(current)

    @staticmethod
    def _set_progress_value(bar: QProgressBar | None, value: Any) -> None:
        if bar is None:
            return
        try:
            numeric = int(float(value))
        except (TypeError, ValueError):
            numeric = 0
        if bar.minimum() == 0 and bar.maximum() == 0:
            bar.setRange(0, 100)
        bar.setValue(max(0, min(100, numeric)))

    def _dialog_progress_block(self, layout: QVBoxLayout) -> tuple[QProgressBar, QLabel]:
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(float(self.progress_var.get())))
        self._progress_bars.append(bar)
        self.progress_var.bind(lambda value, b=bar: self._set_progress_value(b, value))
        label = QLabel()
        label.setObjectName("StatusText")
        self.progress_status_var.bind(lambda value, l=label: l.setText(str(value)))
        layout.addWidget(bar)
        layout.addWidget(label)
        self._dialog_progress_labels.append(label)
        return bar, label

    # ------------------------------------------------------------------
    # Main window
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(9)

        # Header: intentionally mirrors the supplied reference image.
        header = QWidget()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(50, 50)
        logo.setScaledContents(True)
        if LOGO_PATH.exists():
            pix = QPixmap(str(LOGO_PATH))
            if not pix.isNull():
                logo.setPixmap(pix.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        h.addWidget(logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        name_row = QHBoxLayout()
        name_row.setSpacing(9)
        name = QLabel(APP_NAME)
        name.setObjectName("AppName")
        version = QLabel(self._display_version())
        version.setObjectName("Version")
        name_row.addWidget(name)
        name_row.addWidget(version)
        name_row.addStretch(1)
        title_box.addLayout(name_row)
        tagline = QLabel()
        tagline.setObjectName("Tagline")
        self.localize_widget(tagline, "app_tagline")
        title_box.addWidget(tagline)
        h.addLayout(title_box)
        h.addStretch(1)
        language_label = QLabel()
        language_label.setObjectName("FieldLabel")
        self.localize_widget(language_label, "label_ui_language")
        h.addWidget(language_label)
        self.ui_language_combo = QComboBox()
        self.ui_language_combo.addItems(list(UI_LANGUAGE_NAMES.values()))
        self.ui_language_combo.setFixedWidth(112)
        self.ui_language_combo.setCurrentText(UI_LANGUAGE_NAMES[self.ui_language_var.get()])
        self.ui_language_combo.currentTextChanged.connect(self.on_ui_language_selected)
        h.addWidget(self.ui_language_combo)
        self.context_menu_check = self._bind_check(self.context_menu_enabled_var, QCheckBox())
        self.localize_widget(self.context_menu_check, "option_enable_extract_context_menu")
        self.context_menu_check.toggled.connect(self.on_context_menu_toggled)
        if not context_menu_integration_supported():
            self.context_menu_check.setEnabled(False)
            self.context_menu_check.setToolTip(self.tr("tooltip_context_menu_unavailable"))
        h.addWidget(self.context_menu_check)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("ThemeButton")
        self.theme_button.setFixedSize(34, 34)
        self.theme_button.clicked.connect(self.toggle_theme)
        h.addWidget(self.theme_button)
        self.third_party_button = self._button("button_update_third_party", self.start_update_third_party, ghost=True)
        h.addWidget(self.third_party_button)
        self.app_update_button = self._button("button_app_update_available", self.open_app_update_release, ghost=True)
        self.app_update_button.hide()
        h.addWidget(self.app_update_button)
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName("MainScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 2, 6)
        content_layout.setSpacing(9)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        create_card, create_layout = self._card("Card")
        # The compact controls let the complete creation workflow fit in the
        # initial viewport. A modest minimum keeps MKV Extract just below the
        # fold without recreating the old oversized 720px card.
        create_card.setMinimumHeight(510)
        create_layout.addWidget(self._section_header("section_create_mkv"))
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 2)
        form.setColumnStretch(3, 2)
        form.setColumnStretch(5, 2)
        form.setColumnStretch(7, 2)
        create_layout.addLayout(form)

        row = 0
        self.template_entry = self._bind_line(self.template_var, QLineEdit())
        form.addWidget(self._field_label("path_template"), row, 0)
        form.addWidget(self.template_entry, row, 1, 1, 7)
        form.addWidget(self._button("button_browse", self.browse_template), row, 8)
        row += 1
        self.folder_entry = self._bind_line(self.folder_var, QLineEdit())
        form.addWidget(self._field_label("path_track_folder"), row, 0)
        form.addWidget(self.folder_entry, row, 1, 1, 7)
        form.addWidget(self._button("button_browse", self.browse_folder), row, 8)
        row += 1
        self.output_entry = self._bind_line(self.output_var, QLineEdit())
        form.addWidget(self._field_label("path_output_mkv"), row, 0)
        form.addWidget(self.output_entry, row, 1, 1, 7)
        form.addWidget(self._button("button_browse", self.browse_output), row, 8)
        row += 1

        form.addWidget(self._field_label("label_output_name_extra"), row, 0)
        self.year_check = self._bind_check(self.output_name_year_var, QCheckBox())
        self.localize_widget(self.year_check, "option_output_name_year")
        self.year_check.toggled.connect(lambda _v: self.on_output_name_year_changed())
        form.addWidget(self.year_check, row, 1)
        self.output_extra_entry = self._bind_line(self.output_name_extra_var, QLineEdit())
        form.addWidget(self.output_extra_entry, row, 2, 1, 2)
        form.addWidget(self._field_label("label_mkv_title"), row, 4)
        self.title_entry = self._bind_line(self.title_var, QLineEdit())
        form.addWidget(self.title_entry, row, 5, 1, 4)
        row += 1

        tmdb_api_label = QLabel("TMDB API key")
        tmdb_api_label.setObjectName("FieldLabel")
        form.addWidget(tmdb_api_label, row, 0)
        self.api_key_entry = self._bind_line(self.api_key_var, QLineEdit())
        self.api_key_entry.setEchoMode(QLineEdit.Password)
        form.addWidget(self.api_key_entry, row, 1, 1, 7)
        self.show_api_check = self._bind_check(self.show_api_key_var, QCheckBox())
        self.localize_widget(self.show_api_check, "button_show")
        self.show_api_check.toggled.connect(self.toggle_api_key_visibility)
        form.addWidget(self.show_api_check, row, 8)
        row += 1

        tmdb_label = QLabel("TMDB")
        tmdb_label.setObjectName("FieldLabel")
        form.addWidget(tmdb_label, row, 0)
        self.tmdb_id_entry = self._bind_line(self.tmdb_id_var, QLineEdit())
        self.tmdb_id_entry.setMaximumWidth(112)
        form.addWidget(self.tmdb_id_entry, row, 1)
        media_lbl = self._field_label("label_tmdb_media_type")
        form.addWidget(media_lbl, row, 2)
        self.media_type_combobox = QComboBox()
        self.media_type_combobox.setFixedWidth(100)
        self.media_type_combobox.currentTextChanged.connect(self.on_tmdb_media_type_selected)
        form.addWidget(self.media_type_combobox, row, 3)
        form.addWidget(self._field_label("label_image_language"), row, 4)
        self.language_entry = self._bind_line(self.language_var, QLineEdit())
        self.language_entry.setMaximumWidth(78)
        form.addWidget(self.language_entry, row, 5)
        form.addWidget(self._field_label("label_tag_language"), row, 6)
        self.tag_language_entry = self._bind_line(self.tag_language_var, QLineEdit())
        self.tag_language_entry.setMaximumWidth(78)
        form.addWidget(self.tag_language_entry, row, 7)
        self.find_tmdb_button = self._button("button_find_id", self.start_find_tmdb_id)
        form.addWidget(self.find_tmdb_button, row, 8)
        self.tmdb_lookup_button = QPushButton("⌕")
        self.tmdb_lookup_button.setFixedWidth(36)
        self.tmdb_lookup_button.setToolTip(self.tr("window_tmdb_search_title"))
        self.tmdb_lookup_button.clicked.connect(self.open_tmdb_search_window)
        form.addWidget(self.tmdb_lookup_button, row, 9)
        row += 1

        form.addWidget(self._field_label("label_default_tracks"), row, 0)
        audio_lbl = self._field_label("label_audio_order")
        form.addWidget(audio_lbl, row, 1)
        self.audio_order_entry = self._bind_line(self.audio_language_order_var, QLineEdit())
        form.addWidget(self.audio_order_entry, row, 2, 1, 2)
        sub_lbl = self._field_label("label_subtitle_order")
        form.addWidget(sub_lbl, row, 4)
        self.subtitle_order_entry = self._bind_line(self.subtitle_language_order_var, QLineEdit())
        form.addWidget(self.subtitle_order_entry, row, 5, 1, 2)
        fps_label = QLabel("Video FPS")
        fps_label.setObjectName("FieldLabel")
        form.addWidget(fps_label, row, 7)
        self.video_fps_combo = QComboBox()
        self.video_fps_combo.setEditable(True)
        self.video_fps_combo.addItems(["", "23.976", "24", "25", "29.97", "30", "50", "59.94", "60", "24000/1001"])
        self._bind_combo_text(self.video_fps_var, self.video_fps_combo)
        form.addWidget(self.video_fps_combo, row, 8, 1, 2)
        row += 1

        options = QHBoxLayout()
        options.setSpacing(12)
        self.include_extra_check = self._bind_check(self.include_extra_subs_var, QCheckBox())
        self.localize_widget(self.include_extra_check, "option_include_extra_subtitles")
        options.addWidget(self.include_extra_check)
        self.download_before_mux_checkbutton = self._bind_check(self.download_before_mux_var, QCheckBox())
        self.localize_widget(self.download_before_mux_checkbutton, "option_download_before_mux")
        self.download_before_mux_checkbutton.toggled.connect(lambda _v: self.update_download_before_mux_state())
        options.addWidget(self.download_before_mux_checkbutton)
        self.add_tracks_check = self._bind_check(self.add_tracks_before_mux_var, QCheckBox())
        self.localize_widget(self.add_tracks_check, "option_add_tracks_before_mux")
        options.addWidget(self.add_tracks_check)
        options.addStretch(1)
        form.addLayout(options, row, 1, 1, 9)
        row += 1

        form.addWidget(self._field_label("label_auto_chapters"), row, 0)
        self.auto_chapter_check = self._bind_check(self.auto_chapters_var, QCheckBox())
        self.localize_widget(self.auto_chapter_check, "option_create_if_missing")
        form.addWidget(self.auto_chapter_check, row, 1)
        form.addWidget(self._field_label("label_chapter_name"), row, 2)
        self.chapter_name_entry = self._bind_line(self.chapter_name_var, QLineEdit())
        form.addWidget(self.chapter_name_entry, row, 3, 1, 7)
        row += 1

        chapter_row = QHBoxLayout()
        chapter_row.setSpacing(6)
        interval_label = self._field_label("label_chapter_interval")
        chapter_row.addWidget(interval_label)
        interval_edit = self._bind_line(self.chapter_interval_var, QLineEdit())
        interval_edit.setFixedWidth(68)
        chapter_row.addWidget(interval_edit)
        chapter_row.addWidget(self._field_label("label_chapter_start"))
        start_edit = self._bind_line(self.chapter_start_var, QLineEdit())
        start_edit.setFixedWidth(62)
        chapter_row.addWidget(start_edit)
        chapter_row.addWidget(self._field_label("label_chapter_end"))
        end_edit = self._bind_line(self.chapter_end_var, QLineEdit())
        end_edit.setFixedWidth(72)
        chapter_row.addWidget(end_edit)
        intro_check = self._bind_check(self.auto_chapter_detect_intro_var, QCheckBox())
        self.localize_widget(intro_check, "option_detect_intro_end")
        chapter_row.addWidget(intro_check)
        chapter_row.addStretch(1)
        form.addLayout(chapter_row, row, 1, 1, 9)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.scan_button = self._button("button_scan_tracks", self.open_audio_adjust_window)
        action_row.addWidget(self.scan_button, 1)
        self.download_button = self._button("button_download_assets", self.start_download)
        action_row.addWidget(self.download_button, 1)
        self.subtitle_button = self._button("button_download_subtitles", self.open_subtitle_download_window)
        action_row.addWidget(self.subtitle_button, 1)
        self.config_button = self._button("button_write_config", self.start_write_config)
        action_row.addWidget(self.config_button, 1)
        self.mux_button = self._button("button_create_mkv", self._mux_button_clicked, primary=True)
        action_row.addWidget(self.mux_button, 1)
        log_btn = self._button("button_show_log", self.open_log_window)
        action_row.addWidget(log_btn, 1)
        create_layout.addLayout(action_row)
        self._main_progress_block(create_layout)
        content_layout.addWidget(create_card)

        extract_card, extract_layout = self._card("Card")
        extract_layout.addWidget(self._section_header("section_extract"))
        extract_form = QGridLayout()
        extract_form.setHorizontalSpacing(8)
        extract_form.setVerticalSpacing(6)
        extract_form.setColumnStretch(1, 1)
        extract_form.setColumnMinimumWidth(2, 78)
        extract_form.setColumnMinimumWidth(3, 150)
        extract_layout.addLayout(extract_form)
        extract_form.addWidget(self._field_label("path_source_mkv"), 0, 0)
        self.extract_source_entry = self._bind_line(self.extract_source_var, QLineEdit())
        extract_form.addWidget(self.extract_source_entry, 0, 1)
        extract_form.addWidget(self._button("button_browse_file", self.browse_extract_source), 0, 2)
        extract_form.addWidget(self._button("button_browse_folder", self.browse_extract_source_folder), 0, 3)
        extract_form.addWidget(self._field_label("path_existing_extract_folder"), 1, 0)
        self.extract_output_entry = self._bind_line(self.extract_output_dir_var, QLineEdit())
        extract_form.addWidget(self.extract_output_entry, 1, 1)
        extract_form.addWidget(self._button("button_browse", self.browse_extract_output_dir), 1, 2)
        extract_form.addWidget(self._button("button_load_existing_extract", self.load_existing_extracted_folder_action), 1, 3)
        batch_actions = QHBoxLayout()
        self.batch_extract_button = self._button("button_extract_folder", self.start_extract_source_action)
        self.batch_mux_button = self._button("button_mux_extracted_folder", self.start_batch_mux_folder, primary=True)
        batch_actions.addWidget(self.batch_extract_button, 1)
        batch_actions.addWidget(self.batch_mux_button, 1)
        extract_layout.addLayout(batch_actions)
        content_layout.addWidget(extract_card)
        content_layout.addStretch(1)

    def _display_version(self) -> str:
        version = str(APP_VERSION or "").strip()
        if not version or version == DEFAULT_APP_VERSION:
            return ""
        return version if version.lower().startswith("v") else f"v{version}"

    def _mux_button_clicked(self) -> None:
        if self.current_operation == "mux" and self.worker is not None and self.worker.is_alive():
            self.cancel_current_operation()
        else:
            self.start_mux()

    # ------------------------------------------------------------------
    # Localization / language
    # ------------------------------------------------------------------
    def tmdb_media_type_labels(self) -> dict[str, str]:
        return {"movie": self.tr("media_type_movie"), "tv": self.tr("media_type_tv")}

    def tmdb_media_type_display(self, value: str) -> str:
        return self.tmdb_media_type_labels().get(normalise_tmdb_media_type(value), self.tr("media_type_movie"))

    def tmdb_media_type_from_display(self, value: str) -> str:
        labels = self.tmdb_media_type_labels()
        for key, label in labels.items():
            if value == label:
                return key
        return normalise_tmdb_media_type(value) if str(value).strip().lower() in TMDB_MEDIA_TYPES else ""

    def refresh_tmdb_media_type_display(self) -> None:
        display = self.tmdb_media_type_display(self.media_type_var.get())
        self.media_type_display_var.set(display)
        if self.media_type_combobox is not None:
            blocker = QSignalBlocker(self.media_type_combobox)
            self.media_type_combobox.clear()
            self.media_type_combobox.addItems([self.tr("media_type_movie"), self.tr("media_type_tv")])
            self.media_type_combobox.setCurrentText(display)
            del blocker

    def on_tmdb_media_type_selected(self, value: str | None = None, *_args: Any) -> None:
        display = value if isinstance(value, str) else self.media_type_display_var.get()
        media_type = self.tmdb_media_type_from_display(display)
        if media_type:
            self.media_type_var.set(media_type)
            self.media_type_display_var.set(self.tmdb_media_type_display(media_type))

    def on_ui_language_selected(self, value: str | None = None, *_args: Any) -> None:
        display = value if isinstance(value, str) else self.ui_language_display_var.get()
        code = UI_LANGUAGE_BY_NAME.get(str(display), normalise_ui_language(str(display)))
        self.ui_language_var.set(code)
        self.ui_language_display_var.set(UI_LANGUAGE_NAMES[code])
        set_active_ui_language(code)
        self.apply_qt_language()
        self.progress_status_var.set(self.tr("status_ready"))
        self.refresh_localized_text()
        self.apply_theme()
        self.save_preferences()

    def apply_qt_language(self) -> None:
        """Translate Qt-owned controls such as native text-edit context menus."""
        app = QApplication.instance()
        if app is None:
            return
        app.removeTranslator(self.qt_translator)
        if self.ui_language_var.get() != "tr":
            return
        translations_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if self.qt_translator.load("qtbase_tr", translations_dir):
            app.installTranslator(self.qt_translator)

    # ------------------------------------------------------------------
    # Dialog helpers / files / preferences
    # ------------------------------------------------------------------
    def dialog_parent(self) -> QWidget:
        for dialog in (self.audio_adjust_window, self.subtitle_window, self.mux_tracks_window, self.extract_window, self.tmdb_search_window, self.log_window):
            if dialog is not None and dialog.isVisible():
                return dialog
        return self

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self.dialog_parent(), title, message)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self.dialog_parent(), title, message)

    def ask_yes_no(self, title: str, message: str) -> bool:
        result = QMessageBox.question(
            self.dialog_parent(), title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        return result == QMessageBox.Yes

    def save_preferences(self) -> None:
        try:
            save_saved_preferences(
                {
                    "ui_language": self.ui_language_var.get(),
                    "theme": self.theme_mode,
                    "api_key": self.api_key_var.get().strip(),
                    "opensubtitles_api_key": self.subtitle_api_key_var.get().strip(),
                    "opensubtitles_username": self.subtitle_username_var.get().strip(),
                    "opensubtitles_password": self.subtitle_password_var.get(),
                    "subtitle_download_language": self.subtitle_language_var.get().strip(),
                    "media_type": normalise_tmdb_media_type(self.media_type_var.get()),
                    "image_language": self.language_var.get().strip() or "en",
                    "tag_language": self.tag_language_var.get().strip() or self.language_var.get().strip() or "en",
                    "output_name_extra": self.output_name_extra_var.get(),
                    "output_name_year": "true" if self.output_name_year_var.get() else "false",
                    "context_menu_enabled": "true" if self.context_menu_enabled_var.get() else "false",
                    "video_fps": self.video_fps_var.get().strip(),
                    "audio_language_order": self.audio_language_order_var.get().strip(),
                    "subtitle_language_order": self.subtitle_language_order_var.get().strip(),
                    "auto_chapters": "true" if self.auto_chapters_var.get() else "false",
                    "auto_chapter_detect_intro": "true" if self.auto_chapter_detect_intro_var.get() else "false",
                    "chapter_interval_minutes": self.chapter_interval_var.get().strip(),
                    "chapter_name": self.chapter_name_var.get().strip(),
                    "chapter_start_number": self.chapter_start_var.get().strip(),
                    "chapter_end_minutes": self.chapter_end_var.get().strip(),
                    "last_mkv_dir": self.last_mkv_dir,
                }
            )
        except OSError as exc:
            self.queue_log(self.tr("log_settings_save_failed", error=exc))

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self.save_preferences()
        if self.worker is not None and self.worker.is_alive():
            self.cancel_current_operation()
        event.accept()

    def browse_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("dialog_template_title"), str(APP_DIR), "MKVToolNix config (*.mtxcfg);;All files (*)"
        )
        if path:
            self.template_var.set(path)

    def browse_folder(self) -> None:
        initial = self.existing_initial_dir(self.folder_var.get(), self.last_mkv_dir, APP_DIR)
        path = QFileDialog.getExistingDirectory(self, self.tr("dialog_track_folder_title"), initial)
        if path:
            self.folder_var.set(path)
            self.last_mkv_dir = path
            self._set_default_output()

    def browse_output(self) -> None:
        initial = self.output_var.get().strip()
        if not initial:
            folder = self.folder_var.get().strip()
            initial = str(Path(folder) / "output.mkv") if folder else str(APP_DIR / "output.mkv")
        path, _ = QFileDialog.getSaveFileName(self, self.tr("dialog_output_mkv_title"), initial, "Matroska video (*.mkv);;All files (*)")
        if path:
            if not Path(path).suffix:
                path += ".mkv"
            self.output_var.set(path)

    def on_extract_source_changed(self, *_args: Any) -> None:
        self.update_extract_source_mode()

    def update_extract_source_mode(self) -> None:
        """Keep the main Extract action aligned with the selected source type.

        A single media file must open/scan the detailed extraction dialog, while
        a directory uses the existing batch-folder workflow.  The previous Qt
        port always wired this button to the folder workflow, which made a valid
        MKV path fail with ``Source folder not found``.
        """
        if self.batch_extract_button is None or self.batch_mux_button is None:
            return

        raw = self.extract_source_var.get().strip()
        source = Path(raw).expanduser() if raw else None
        is_file = bool(source and source.exists() and source.is_file())
        is_dir = bool(source and source.exists() and source.is_dir())

        self.batch_extract_button.setText(
            self.tr("button_scan_mkv") if is_file else self.tr("button_extract_folder")
        )
        self.batch_extract_button.setEnabled(is_file or is_dir)
        # Folder muxing is a batch operation; for a single MKV the detailed
        # dialog owns extraction and the regular Create MKV flow handles muxing.
        self.batch_mux_button.setEnabled(is_dir)

    def start_extract_source_action(self) -> None:
        raw = self.extract_source_var.get().strip()
        if not raw:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_source_mkv_not_selected"),
            )
            return

        source = Path(raw).expanduser()
        if source.is_file():
            self.start_scan_extract()
            return
        if source.is_dir():
            self.start_batch_extract_folder()
            return

        # Preserve the most useful existing validation message for a path that
        # no longer exists or is otherwise invalid.
        self.show_error(
            self.tr("dialog_missing_info"),
            self.tr("error_mkv_source_not_found", source=source),
        )

    def load_existing_extracted_folder_action(self) -> None:
        try:
            self.load_existing_extracted_folder()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))

    def open_initial_extract_source(self, source: Path) -> None:
        """Open a file supplied by the desktop/Open-With integration in Extract.

        Create and raise the Extract dialog *before* starting the background
        identify job.  Some KDE/Wayland compositors otherwise keep a newly
        created child dialog behind the just-mapped main window during startup.
        """
        self.set_extract_source(source, scan=False)
        self.ensure_extract_window()
        if self.extract_window is not None:
            self.extract_window.show()
            self.extract_window.raise_()
            self.extract_window.activateWindow()
        QTimer.singleShot(50, self.start_scan_extract)

    def browse_extract_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("dialog_source_mkv_title"),
            self.extract_source_initial_dir(),
            "Video files (*.mkv *.mk3d *.mka *.webm *.mp4 *.m4v *.mov *.avi *.ts *.m2ts);;All files (*)",
        )
        if path:
            self.set_extract_source(Path(path), scan=True)

    def browse_extract_source_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr("dialog_source_mkv_title"), self.extract_source_initial_dir())
        if path:
            self.set_extract_source(Path(path), scan=False)

    def browse_extract_output_dir(self) -> None:
        initial = self.extract_output_dir_var.get().strip() or self.extract_source_initial_dir()
        path = QFileDialog.getExistingDirectory(self, self.tr("dialog_extract_folder_title"), initial)
        if path:
            self.extract_output_dir_var.set(path)

    def toggle_api_key_visibility(self, *_args: Any) -> None:
        self.api_key_entry.setEchoMode(QLineEdit.Normal if self.show_api_key_var.get() else QLineEdit.Password)

    def on_api_key_changed(self, *_args: Any) -> None:
        self.update_download_before_mux_state()

    def on_output_name_extra_changed(self, *_args: Any) -> None:
        output_raw = self.output_var.get().strip()
        if output_raw:
            output_path = Path(output_raw).expanduser()
            output_path = output_path_without_name_extra(
                output_path, self.current_output_name_extra
            )
            output_path = self.output_path_with_current_name_extra(output_path)
            self.output_var.set(str(output_path))
        self.current_output_name_extra = self.output_name_extra_var.get()

    def update_download_before_mux_state(self) -> None:
        if self.download_before_mux_checkbutton is None:
            return
        has_api_key = bool(self.api_key_var.get().strip())
        if not has_api_key:
            self.download_before_mux_var.set(False)
        self.download_before_mux_checkbutton.setEnabled(has_api_key)

    # ------------------------------------------------------------------
    # Add-tracks dialog
    # ------------------------------------------------------------------
    def open_mux_tracks_window(self, settings: AppSettings | None = None) -> None:
        try:
            settings = settings or self.collect_settings()
            rows = self.mux_track_window_rows(settings)
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return
        self.mux_batch_tasks = []
        self.close_mux_tracks_window()
        dialog = QDialog(self)
        dialog.setObjectName("DialogRoot")
        dialog.setWindowTitle(f"{APP_NAME} - {self.tr('window_mux_tracks_title')}")
        dialog.resize(1050, 560)
        self.mux_tracks_window = dialog
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        card, card_layout = self._card("DialogCard")
        layout.addWidget(card, 1)
        table = self._build_mux_tracks_table(rows)
        card_layout.addWidget(table, 1)
        controls = QHBoxLayout()
        add = self._button("button_add_tracks", self.add_mux_track_files)
        remove = self._button("button_remove_track", self.remove_selected_mux_track)
        up = self._button("button_move_track_up", lambda: self.move_selected_mux_track(-1))
        down = self._button("button_move_track_down", lambda: self.move_selected_mux_track(1))
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addWidget(up)
        controls.addWidget(down)
        controls.addStretch(1)
        self.mux_tracks_download_missing_assets_var.set(self.mux_track_download_missing_assets)
        fill = self._bind_check(self.mux_tracks_download_missing_assets_var, QCheckBox())
        self.localize_widget(fill, "option_download_missing_mux_assets")
        controls.addWidget(fill)
        card_layout.addLayout(controls)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._button("button_cancel", self.close_mux_tracks_window))
        actions.addWidget(self._button("button_create_mkv", self.confirm_mux_tracks_and_start_mux, primary=True))
        layout.addLayout(actions)
        dialog.finished.connect(lambda _r: self._clear_mux_dialog_refs())
        dialog.show()

    def _build_mux_tracks_table(self, rows: list[MuxTrackWindowRow]) -> MuxTracksTable:
        """Create one editable track table for the active episode."""
        table = MuxTracksTable(0, 6)
        table.setHorizontalHeaderLabels([
            self.tr("heading_selected"), self.tr("heading_track_type"), self.tr("label_track_language"),
            self.tr("label_track_delay"), self.tr("heading_audio_append"), self.tr("heading_audio_file"),
        ])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setDragDropMode(QAbstractItemView.InternalMove)
        table.setDefaultDropAction(Qt.MoveAction)
        table.setDragEnabled(True)
        table.setAcceptDrops(True)
        table.setDropIndicatorShown(True)
        table.row_move_callback = self._move_mux_track_row_to
        table.file_drop_callback = self._drop_mux_track_files
        table.verticalHeader().setDefaultSectionSize(40)
        table.verticalHeader().setMinimumSectionSize(40)
        table.setColumnWidth(4, 250)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.mux_tracks_tree = table
        self.mux_tracks_rows_by_iid = {}
        self.mux_track_source_keys = {row.key for row in rows if not row.manual}
        for index, row_model in enumerate(rows):
            key = row_model.key
            self.mux_tracks_rows_by_iid[key] = row_model
            table.insertRow(index)
            use = QCheckBox(); use.setChecked(row_model.included)
            use.toggled.connect(lambda checked, row_key=key: self._mux_row_inclusion_changed(row_key, checked))
            table.setCellWidget(index, 0, self._center_widget(use))
            table.setItem(index, 1, QTableWidgetItem(row_model.kind))
            lang = QLineEdit(row_model.language)
            lang.editingFinished.connect(lambda row_key=key, editor=lang: self._mux_row_language_changed(row_key, editor.text()))
            table.setCellWidget(index, 2, self._table_editor_host(lang))
            delay = QLineEdit(row_model.delay); delay.setEnabled(row_model.delay_supported)
            delay.editingFinished.connect(lambda row_key=key, editor=delay: self._mux_row_delay_changed(row_key, editor.text()))
            table.setCellWidget(index, 3, self._table_editor_host(delay))
            table.setCellWidget(index, 4, self._build_mux_append_cell(row_model))
            item = QTableWidgetItem(self._mux_base_file_label(row_model)); item.setData(Qt.UserRole, key)
            table.setItem(index, 5, item)
            self._style_mux_row(index, row_model.included)
        self._sync_mux_append_source_rows()
        return table

    def open_batch_mux_tracks_window(
        self,
        settings: AppSettings,
        source_dir: Path,
        tasks: list[BatchEpisodeTask],
    ) -> None:
        """Let batch users configure each extracted episode independently."""
        if not tasks:
            return
        self.close_mux_tracks_window()
        self.mux_batch_tasks = list(tasks)
        self.mux_batch_settings = copy.copy(settings)
        self.mux_tracks_rows_by_episode = {}
        self.mux_track_source_keys_by_episode = {}
        self.mux_track_auto_excluded_append_keys_by_episode = {}
        self.batch_mux_track_customizations = {}
        self.additional_mux_tracks = []
        self.additional_mux_assets = []
        self.mux_track_order_keys = []
        self.mux_track_language_overrides = {}
        self.mux_track_delay_overrides = {}
        self.mux_track_append_overrides = {}
        self.mux_track_excluded_keys = set()

        dialog = QDialog(self)
        dialog.setObjectName("DialogRoot")
        dialog.setWindowTitle(f"{APP_NAME} - {self.tr('window_mux_tracks_title')}")
        dialog.resize(1050, 610)
        self.mux_tracks_window = dialog
        layout = QVBoxLayout(dialog); layout.setContentsMargins(16, 16, 16, 16); layout.setSpacing(10)
        card, card_layout = self._card("DialogCard"); layout.addWidget(card, 1)
        tabs = QTabWidget(); self.mux_tracks_tabs = tabs; card_layout.addWidget(tabs, 1)

        for task in tasks:
            tab_label = f"{episode_code(task.episode_ref)} · {task.source.name}"
            tabs.addTab(QWidget(), tab_label)

        tabs.currentChanged.connect(self._activate_mux_batch_tab)
        self._activate_mux_batch_tab(0)
        controls = QHBoxLayout()
        controls.addWidget(self._button("button_add_tracks", self.add_mux_track_files))
        controls.addWidget(self._button("button_remove_track", self.remove_selected_mux_track))
        controls.addWidget(self._button("button_move_track_up", lambda: self.move_selected_mux_track(-1)))
        controls.addWidget(self._button("button_move_track_down", lambda: self.move_selected_mux_track(1)))
        controls.addStretch(1)
        self.mux_tracks_download_missing_assets_var.set(False)
        card_layout.addLayout(controls)
        actions = QHBoxLayout(); actions.addStretch(1)
        actions.addWidget(self._button("button_cancel", self.close_mux_tracks_window))
        actions.addWidget(self._button("button_create_mkv", self.confirm_mux_tracks_and_start_mux, primary=True))
        layout.addLayout(actions)
        dialog.finished.connect(lambda _r: self._clear_mux_dialog_refs())
        dialog.show()

    def _activate_mux_batch_tab(self, index: int) -> None:
        if index < 0 or index >= len(self.mux_batch_tasks) or self.mux_tracks_tabs is None:
            return
        task = self.mux_batch_tasks[index]
        key = str(task.extract_dir.resolve())
        page = self.mux_tracks_tabs.widget(index)
        if page is None:
            return
        table = page.findChild(MuxTracksTable)
        if table is None:
            if self.mux_batch_settings is None:
                return
            episode_settings = copy.copy(self.mux_batch_settings)
            episode_settings.media_dir = task.extract_dir
            rows = self.mux_track_window_rows(episode_settings)
            self.mux_track_auto_excluded_append_keys = set()
            table = self._build_mux_tracks_table(rows)
            page_layout = QVBoxLayout(page); page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.addWidget(table)
            self.mux_tracks_rows_by_episode[key] = self.mux_tracks_rows_by_iid
            self.mux_track_source_keys_by_episode[key] = self.mux_track_source_keys
            self.mux_track_auto_excluded_append_keys_by_episode[key] = self.mux_track_auto_excluded_append_keys
        self.mux_tracks_tree = table
        self.mux_tracks_rows_by_iid = self.mux_tracks_rows_by_episode.get(key, {})
        self.mux_track_source_keys = self.mux_track_source_keys_by_episode.get(key, set())
        self.mux_track_auto_excluded_append_keys = self.mux_track_auto_excluded_append_keys_by_episode.get(key, set())

    @staticmethod
    def _center_widget(widget: QWidget) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(widget)
        layout.addStretch(1)
        return host

    @staticmethod
    def _table_editor_host(widget: QWidget, *, horizontal: int = 2, vertical: int = 4) -> QWidget:
        """Give table editors breathing room without increasing the global control size."""
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(horizontal, vertical, horizontal, vertical)
        layout.setSpacing(0)
        layout.addWidget(widget)
        return host

    def _mux_base_file_label(self, row: MuxTrackWindowRow) -> str:
        if row.asset_kind:
            if row.target_name and row.target_name != row.path.name:
                return f"{row.path.name} -> {row.target_name}"
            return row.path.name
        return row.path.name

    @staticmethod
    def _mux_append_label(row: MuxTrackWindowRow) -> str:
        return " + ".join(path.name for path in row.append_paths)

    def _build_mux_append_cell(self, row: MuxTrackWindowRow) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(5)

        label = QLabel(self._mux_append_label(row))
        label.setObjectName("MuxAppendLabel")
        label.setToolTip("\n".join(str(path) for path in row.append_paths))
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(label, 1)

        add = QPushButton("+")
        add.setObjectName("CompactButton")
        add.setFixedSize(28, 28)
        add.setToolTip(self.tr("dialog_add_append_audio_title"))
        add.setEnabled(self.mux_track_append_supported(row))
        add.clicked.connect(lambda _=False, key=row.key: self._add_append_for_mux_key(key))
        layout.addWidget(add)

        remove = QPushButton("-")
        remove.setObjectName("CompactButton")
        remove.setFixedSize(28, 28)
        remove.setEnabled(bool(row.append_paths) and self.mux_track_append_supported(row))
        remove.clicked.connect(lambda _=False, key=row.key: self._remove_last_append_for_mux_key(key))
        layout.addWidget(remove)
        return host

    def _refresh_mux_append_cell(self, key: str) -> None:
        if self.mux_tracks_tree is None:
            return
        row_index = self._mux_row_index(key)
        model = self.mux_tracks_rows_by_iid.get(key)
        if row_index < 0 or model is None:
            return
        self.mux_tracks_tree.setCellWidget(row_index, 4, self._build_mux_append_cell(model))
        file_item = self.mux_tracks_tree.item(row_index, 5)
        if file_item is not None:
            file_item.setText(self._mux_base_file_label(model))
            file_item.setData(Qt.UserRole, model.key)

    def _mux_checkbox_for_row(self, row: int) -> QCheckBox | None:
        if self.mux_tracks_tree is None or row < 0:
            return None
        host = self.mux_tracks_tree.cellWidget(row, 0)
        return host.findChild(QCheckBox) if host is not None else None

    def _sync_mux_append_source_rows(self) -> None:
        """Keep append sources out of the MKV as independent tracks.

        A file used as an append part (for example ``sessiz.eac3`` appended to
        ``tur.eac3``) is automatically unchecked and locked while the owning
        base track is active. If the append is removed, a checkbox that we
        disabled automatically is restored to its previous active state.
        """
        if self.mux_tracks_tree is None:
            return

        active_append_keys: set[str] = set()
        for owner in self.mux_tracks_rows_by_iid.values():
            if owner.asset_kind or not owner.included:
                continue
            active_append_keys.update(path_identity_key(path) for path in owner.append_paths)

        for model in self.mux_tracks_rows_by_iid.values():
            if model.asset_kind:
                continue
            is_append_source = model.key in active_append_keys
            if is_append_source:
                if model.included:
                    model.included = False
                    self.mux_track_auto_excluded_append_keys.add(model.key)
            elif model.key in self.mux_track_auto_excluded_append_keys:
                model.included = True
                self.mux_track_auto_excluded_append_keys.discard(model.key)

            row_index = self._mux_row_index(model.key)
            if row_index < 0:
                continue
            checkbox = self._mux_checkbox_for_row(row_index)
            if checkbox is not None:
                blocker = QSignalBlocker(checkbox)
                checkbox.setChecked(model.included)
                del blocker
                checkbox.setEnabled(not is_append_source)
            self._style_mux_row(row_index, model.included)
            self._refresh_mux_append_cell(model.key)

    def _mux_row_index(self, key: str) -> int:
        if self.mux_tracks_tree is None:
            return -1
        for row in range(self.mux_tracks_tree.rowCount()):
            item = self.mux_tracks_tree.item(row, 5)
            model = self._mux_model_for_row(row)
            if model is not None and model.key == key:
                return row
        return -1

    def _mux_model_for_row(self, row: int) -> MuxTrackWindowRow | None:
        if self.mux_tracks_tree is None or row < 0:
            return None
        file_item = self.mux_tracks_tree.item(row, 5)
        if file_item is None:
            return None
        key = file_item.data(Qt.UserRole)
        if key is not None:
            model = self.mux_tracks_rows_by_iid.get(str(key))
            if model is not None:
                return model
        # Fallback for rows created by an older in-memory dialog.
        text = file_item.text()
        for model in self.mux_tracks_rows_by_iid.values():
            if self._mux_base_file_label(model) == text:
                return model
        return None

    def _mux_row_inclusion_changed(self, key: str, checked: bool) -> None:
        model = self.mux_tracks_rows_by_iid.get(key)
        if model is None:
            return
        model.included = checked
        self._sync_mux_append_source_rows()

    def _style_mux_row(self, row: int, active: bool) -> None:
        if self.mux_tracks_tree is None:
            return
        palette = palette_for(self.theme_mode)
        color = QColor(palette.text if active else palette.disabled)
        for col in (1, 5):
            item = self.mux_tracks_tree.item(row, col)
            if item is not None:
                item.setForeground(color)
                font = item.font()
                font.setStrikeOut(not active)
                item.setFont(font)

    def _mux_row_language_changed(self, key: str, value: str) -> None:
        model = self.mux_tracks_rows_by_iid.get(key)
        if model is not None:
            model.language = normalise_mux_language(value)

    def _mux_row_delay_changed(self, key: str, value: str) -> None:
        model = self.mux_tracks_rows_by_iid.get(key)
        if model is None:
            return
        value = value.strip()
        if value and not re.fullmatch(r"[+-]?\d+", value):
            self.show_error(self.tr("dialog_missing_info"), self.tr("error_track_delay_format"))
            return
        model.delay = value

    def _add_append_for_mux_key(self, key: str) -> None:
        model = self.mux_tracks_rows_by_iid.get(key)
        if model is None or not self.mux_track_append_supported(model):
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self.mux_tracks_window or self,
            self.tr("dialog_add_append_audio_title"),
            str(model.path.parent),
            "Audio files (*)",
        )
        if not paths:
            return
        try:
            model.append_paths = normalise_append_paths_for_track(
                model.path,
                [*model.append_paths, *(Path(path) for path in paths)],
            )
            model.append_overridden = True
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return
        self._refresh_mux_append_cell(key)
        self._sync_mux_append_source_rows()

    def _remove_last_append_for_mux_key(self, key: str) -> None:
        model = self.mux_tracks_rows_by_iid.get(key)
        if model is None or not model.append_paths:
            return
        model.append_paths = tuple(model.append_paths[:-1])
        model.append_overridden = True
        self._refresh_mux_append_cell(key)
        self._sync_mux_append_source_rows()

    def _drop_mux_track_files(self, paths: list[Path]) -> None:
        """Add files dropped from the desktop without letting Qt mutate rows."""
        self.add_mux_track_paths(paths)
        self._rebuild_mux_table_from_models()

    def _move_mux_track_row_to(self, source: int, target: int) -> None:
        """Reorder the persistent row models, then rebuild the table."""
        if self.mux_tracks_tree is None:
            return
        # Do not reconstruct the model order from QTableWidget while a drag is
        # active.  Qt can transiently detach visual rows/cell widgets during the
        # gesture.  The dict is the authoritative snapshot and preserves order.
        ordered = list(self.mux_tracks_rows_by_iid.values())
        if source < 0 or source >= len(ordered):
            return
        moved = ordered.pop(source)
        target = max(0, min(int(target), len(ordered)))
        ordered.insert(target, moved)
        self.mux_tracks_rows_by_iid = {model.key: model for model in ordered}
        self._rebuild_mux_table_from_models(selected_key=moved.key)

    def add_mux_track_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self.mux_tracks_window or self, self.tr("dialog_add_track_files_title"), self.folder_var.get() or str(APP_DIR), "Media / metadata files (*)")
        if paths:
            self.add_mux_track_paths([Path(path) for path in paths])
            self._rebuild_mux_table_from_models()

    def add_mux_track_paths(self, paths: list[Path]) -> None:
        # Reuse the model preparation rules from the original implementation but
        # append directly to the Qt row model.
        existing = {path_identity_key(row.path) for row in self.mux_tracks_rows_by_iid.values() if not row.asset_kind}
        for raw in paths:
            path = Path(raw).expanduser()
            if path.exists():
                path = path.resolve()
            if not path.is_file():
                continue
            asset_info = mux_asset_info_from_path(path)
            if asset_info:
                asset_kind, target_name = asset_info
                key = self.mux_window_row_key(path, asset_kind, target_name)
                if key in self.mux_tracks_rows_by_iid:
                    continue
                self.mux_tracks_rows_by_iid[key] = MuxTrackWindowRow(
                    key=key, path=path, kind=self.mux_asset_kind_label(asset_kind), language="",
                    asset_kind=asset_kind, target_name=target_name, manual=True, included=True,
                )
                continue
            kind = media_kind_from_path(path)
            if kind is None or path_identity_key(path) in existing:
                continue
            key = self.mux_window_row_key(path)
            self.mux_tracks_rows_by_iid[key] = MuxTrackWindowRow(
                key=key,
                path=path,
                kind=self.mux_track_kind_label(path),
                language=infer_language_from_filename(path, MUX_UNKNOWN_LANGUAGE),
                delay="",
                delay_supported=kind in {"audio", "subtitle"},
                manual=True,
                included=True,
            )
            existing.add(path_identity_key(path))

    def _rebuild_mux_table_from_models(self, selected_key: str | None = None) -> None:
        if self.mux_tracks_tree is None:
            return
        models = list(self.mux_tracks_rows_by_iid.values())
        self.mux_tracks_tree.setRowCount(0)
        self.mux_tracks_rows_by_iid = {}
        for idx, model in enumerate(models):
            self.mux_tracks_rows_by_iid[model.key] = model
            self.mux_tracks_tree.insertRow(idx)
            use = QCheckBox(); use.setChecked(model.included)
            use.toggled.connect(lambda checked, key=model.key: self._mux_row_inclusion_changed(key, checked))
            self.mux_tracks_tree.setCellWidget(idx, 0, self._center_widget(use))
            self.mux_tracks_tree.setItem(idx, 1, QTableWidgetItem(model.kind))
            lang = QLineEdit(model.language); lang.editingFinished.connect(lambda key=model.key, e=lang: self._mux_row_language_changed(key, e.text()))
            self.mux_tracks_tree.setCellWidget(idx, 2, self._table_editor_host(lang))
            delay = QLineEdit(model.delay); delay.setEnabled(model.delay_supported); delay.editingFinished.connect(lambda key=model.key, e=delay: self._mux_row_delay_changed(key, e.text()))
            self.mux_tracks_tree.setCellWidget(idx, 3, self._table_editor_host(delay))
            self.mux_tracks_tree.setCellWidget(idx, 4, self._build_mux_append_cell(model))
            file_item = QTableWidgetItem(self._mux_base_file_label(model))
            file_item.setData(Qt.UserRole, model.key)
            self.mux_tracks_tree.setItem(idx, 5, file_item)
            self._style_mux_row(idx, model.included)
        self._sync_mux_append_source_rows()
        if selected_key:
            selected_row = self._mux_row_index(selected_key)
            if selected_row >= 0:
                self.mux_tracks_tree.selectRow(selected_row)
                self.mux_tracks_tree.setCurrentCell(selected_row, 5)

    def remove_selected_mux_track(self) -> None:
        if self.mux_tracks_tree is None:
            return
        row = self.mux_tracks_tree.currentRow()
        model = self._mux_model_for_row(row)
        if model is None:
            return
        model.included = not model.included
        host = self.mux_tracks_tree.cellWidget(row, 0)
        if host is not None:
            check = host.findChild(QCheckBox)
            if check is not None:
                check.setChecked(model.included)
        self._style_mux_row(row, model.included)

    def move_selected_mux_track(self, direction: int) -> None:
        if self.mux_tracks_tree is None:
            return
        row = self.mux_tracks_tree.currentRow()
        target = row + int(direction)
        if row < 0 or target < 0 or target >= self.mux_tracks_tree.rowCount():
            return
        self._move_mux_track_row_to(row, target)

    def confirm_mux_tracks_and_start_mux(self) -> None:
        if self.mux_tracks_tree is None:
            return
        if self.mux_batch_tasks:
            for task in self.mux_batch_tasks:
                key = str(task.extract_dir.resolve())
                rows = list(self.mux_tracks_rows_by_episode.get(key, {}).values())
                active_rows = [row for row in rows if row.included]
                active_tracks = [row for row in active_rows if not row.asset_kind]
                active_assets = [row for row in active_rows if row.asset_kind]
                source_keys = self.mux_track_source_keys_by_episode.get(key, set())
                self.batch_mux_track_customizations[key] = (
                    [AdditionalMuxTrack(row.path, normalise_mux_language(row.language), row.delay, row.append_paths)
                     for row in active_tracks if row.manual],
                    [row.key for row in active_tracks],
                    {row.key: normalise_mux_language(row.language) for row in active_tracks},
                    {row.key: row.delay for row in active_tracks if row.delay_supported},
                    {row.key: row.append_paths for row in active_tracks if row.append_paths or row.append_overridden},
                    source_keys - {row.key for row in active_tracks},
                    [AdditionalMuxAsset(row.path, row.asset_kind, row.target_name)
                     for row in active_assets if row.manual],
                    bool(self.mux_tracks_download_missing_assets_var.get()),
                )
            self.close_mux_tracks_window()
            self.start_batch_mux_folder(skip_track_window=True)
            return
        download_missing_assets = bool(self.mux_tracks_download_missing_assets_var.get())
        try:
            settings = self.collect_settings(require_tmdb=download_missing_assets)
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return
        ordered_rows = [self._mux_model_for_row(i) for i in range(self.mux_tracks_tree.rowCount())]
        ordered_rows = [row for row in ordered_rows if row is not None]
        active_rows = [row for row in ordered_rows if row.included]
        active_track_rows = [row for row in active_rows if not row.asset_kind]
        active_asset_rows = [row for row in active_rows if row.asset_kind]
        self.additional_mux_tracks = [
            AdditionalMuxTrack(row.path, normalise_mux_language(row.language), row.delay, row.append_paths)
            for row in active_track_rows if row.manual
        ]
        self.additional_mux_assets = [
            AdditionalMuxAsset(row.path, row.asset_kind, row.target_name)
            for row in active_asset_rows if row.manual
        ]
        self.mux_track_download_missing_assets = download_missing_assets
        if not self.prepare_additional_mux_assets(settings):
            return
        self.mux_track_order_keys = [row.key for row in active_track_rows]
        self.mux_track_language_overrides = {row.key: normalise_mux_language(row.language) for row in active_track_rows}
        self.mux_track_delay_overrides = {row.key: row.delay for row in active_track_rows if row.delay_supported}
        self.mux_track_append_overrides = {row.key: row.append_paths for row in active_track_rows if row.append_paths or row.append_overridden}
        active_track_keys = {row.key for row in active_track_rows}
        self.mux_track_excluded_keys = self.mux_track_source_keys - active_track_keys
        self.queue_log(self.tr("log_custom_tracks_ready", count=len(active_rows)))
        self.close_mux_tracks_window()
        self.start_mux(skip_track_window=True)

    def close_mux_tracks_window(self) -> None:
        if self.mux_tracks_window is not None:
            self.mux_tracks_window.close()
        self._clear_mux_dialog_refs()

    def _clear_mux_dialog_refs(self) -> None:
        self.mux_tracks_window = None
        self.mux_tracks_tree = None
        self.mux_tracks_tabs = None
        self.mux_tracks_toggle_button = None
        self.mux_tracks_rows_by_episode = {}
        self.mux_track_source_keys_by_episode = {}
        self.mux_track_auto_excluded_append_keys_by_episode = {}
        self.mux_batch_tasks = []
        self.mux_batch_settings = None

    def update_mux_track_toggle_button_text(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Subtitle dialog
    # ------------------------------------------------------------------
    def open_subtitle_download_window(self) -> None:
        try:
            batch_settings = self.collect_batch_subtitle_download_settings()
            if batch_settings is None:
                settings = self.collect_settings()
                metadata = self.subtitle_lookup_metadata(settings)
                targets = [self.apply_subtitle_lookup_metadata(subtitle_target_from_settings(settings), metadata)]
                batch_mode = False
                target_text = self.tr("subtitle_target_single", folder=settings.media_dir)
                query = metadata.query or targets[0].query
            else:
                settings, source_dir, _extract_root, tasks = batch_settings
                metadata = self.subtitle_lookup_metadata(settings)
                targets = [self.apply_subtitle_lookup_metadata(t, metadata) for t in batch_subtitle_targets(settings, source_dir, tasks)]
                batch_mode = True
                target_text = self.tr("subtitle_target_batch", count=len(targets))
                query = metadata.query or (targets[0].query if targets else "")
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        self.close_subtitle_window()
        self.subtitle_targets = targets
        self.subtitle_batch_mode = batch_mode
        session_key = tuple(str(target.media_dir.resolve()) for target in targets)
        self.subtitle_session_key = session_key
        cached = self.subtitle_sessions.get(session_key)
        if cached is None:
            self.subtitle_results = {}
            self.subtitle_downloaded_paths = {}
            self.subtitle_language_var.set(self.default_subtitle_download_language())
            self.subtitle_query_var.set(query)
            self.subtitle_status_var.set(self.tr("label_subtitle_status_ready"))
        else:
            cached_query, cached_language, cached_results, cached_downloads = cached
            self.subtitle_results = dict(cached_results)
            self.subtitle_downloaded_paths = dict(cached_downloads)
            self.subtitle_query_var.set(cached_query)
            self.subtitle_language_var.set(cached_language)
            self.subtitle_status_var.set(self.tr("log_subtitle_results_found", count=len(self.subtitle_results)))

        dialog = QDialog(self)
        dialog.setObjectName("DialogRoot")
        dialog.setWindowTitle(f"{APP_NAME} - {self.tr('window_subtitle_download_title')}")
        dialog.resize(1120, 670)
        self.subtitle_window = dialog
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        card, card_layout = self._card("DialogCard")
        layout.addWidget(card, 1)
        form = QGridLayout(); form.setHorizontalSpacing(10); form.setVerticalSpacing(8); form.setColumnStretch(1, 1); form.setColumnStretch(3, 1)
        card_layout.addLayout(form)
        form.addWidget(self._field_label("label_subtitle_api_key"), 0, 0)
        api_edit = self._bind_line(self.subtitle_api_key_var, QLineEdit()); api_edit.setEchoMode(QLineEdit.Password)
        form.addWidget(api_edit, 0, 1, 1, 3)
        form.addWidget(self._field_label("label_subtitle_username"), 1, 0)
        user_edit = self._bind_line(self.subtitle_username_var, QLineEdit()); form.addWidget(user_edit, 1, 1)
        form.addWidget(self._field_label("label_subtitle_password"), 1, 2)
        self.subtitle_password_entry = self._bind_line(self.subtitle_password_var, QLineEdit()); self.subtitle_password_entry.setEchoMode(QLineEdit.Password)
        form.addWidget(self.subtitle_password_entry, 1, 3)
        show = self._bind_check(self.subtitle_show_password_var, QCheckBox()); self.localize_widget(show, "button_show"); show.toggled.connect(self.toggle_subtitle_password_visibility)
        form.addWidget(show, 1, 4)
        form.addWidget(self._field_label("label_subtitle_language"), 2, 0)
        lang = QComboBox(); lang.setEditable(True); lang.addItems(["tr","en","de","fr","es","it","pt","ru","ja","ko"]); self._bind_combo_text(self.subtitle_language_var, lang)
        form.addWidget(lang, 2, 1)
        form.addWidget(self._field_label("label_subtitle_query"), 2, 2)
        query_edit = self._bind_line(self.subtitle_query_var, QLineEdit()); form.addWidget(query_edit, 2, 3)
        self.subtitle_search_button = self._button("button_search_subtitles", self.start_subtitle_search); form.addWidget(self.subtitle_search_button, 2, 4)
        form.addWidget(self._field_label("label_subtitle_target"), 3, 0)
        target_label = QLabel(target_text); target_label.setObjectName("Muted"); target_label.setWordWrap(True); form.addWidget(target_label, 3, 1, 1, 4)
        status_label = QLabel(); status_label.setObjectName("StatusText"); self.subtitle_status_var.bind(lambda v: status_label.setText(str(v))); form.addWidget(status_label, 4, 1, 1, 4)

        self.subtitle_results_trees_by_target = {}
        if batch_mode:
            tabs = QTabWidget(); self.subtitle_results_tabs = tabs; card_layout.addWidget(tabs, 1)
            for index, target in enumerate(targets):
                table = self._new_subtitle_results_table()
                self.subtitle_results_trees_by_target[index] = table
                label = f"{episode_code(target.episode_ref)} · {target.source_name}" if target.episode_ref else target.output_stem
                tabs.addTab(table, label)
            self.subtitle_results_tree = self.subtitle_results_trees_by_target.get(0)
            tabs.currentChanged.connect(self._activate_subtitle_target_tab)
        else:
            table = self._new_subtitle_results_table()
            self.subtitle_results_tree = table; card_layout.addWidget(table, 1)
        bottom = QVBoxLayout(); self.subtitle_progress_bar, _ = self._dialog_progress_block(bottom); card_layout.addLayout(bottom)
        actions = QHBoxLayout()
        self.subtitle_best_button = self._button("button_download_best_subtitles", self.start_subtitle_download_best)
        self.subtitle_download_button = self._button("button_download_selected_subtitle", self.start_subtitle_download_selected, primary=True)
        actions.addWidget(self.subtitle_best_button, 1); actions.addWidget(self.subtitle_download_button, 1); actions.addWidget(self._button("button_close", self.close_subtitle_window), 1)
        card_layout.addLayout(actions)
        self.sync_progress_widget(self.subtitle_progress_bar)
        dialog.finished.connect(lambda _r: self._clear_subtitle_refs())
        if self.subtitle_results:
            self.set_subtitle_results(list(self.subtitle_results.values()))
        dialog.show()

    def remember_subtitle_session(self) -> None:
        if not self.subtitle_session_key:
            return
        self.subtitle_sessions[self.subtitle_session_key] = (
            self.subtitle_query_var.get().strip(),
            self.subtitle_language_var.get().strip(),
            dict(self.subtitle_results),
            dict(self.subtitle_downloaded_paths),
        )

    def _new_subtitle_results_table(self) -> QTableWidget:
        table = QTableWidget(0, 8)
        table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setAlternatingRowColors(True); table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.setHorizontalHeaderLabels([
            self.tr("heading_subtitle_status"), self.tr("heading_subtitle_target"), self.tr("heading_subtitle_language"),
            self.tr("heading_subtitle_release"), self.tr("heading_subtitle_fps"), self.tr("heading_subtitle_flags"),
            self.tr("heading_subtitle_downloads"), self.tr("heading_subtitle_file"),
        ])
        return table

    def _activate_subtitle_target_tab(self, index: int) -> None:
        table = self.subtitle_results_trees_by_target.get(index)
        if table is not None:
            self.subtitle_results_tree = table

    def _refresh_subtitle_headers(self) -> None:
        tables = list(self.subtitle_results_trees_by_target.values()) or [self.subtitle_results_tree]
        for table in tables:
            if table is not None:
                table.setHorizontalHeaderLabels([
                    self.tr("heading_subtitle_status"), self.tr("heading_subtitle_target"), self.tr("heading_subtitle_language"),
                    self.tr("heading_subtitle_release"), self.tr("heading_subtitle_fps"), self.tr("heading_subtitle_flags"),
                    self.tr("heading_subtitle_downloads"), self.tr("heading_subtitle_file"),
                ])

    def close_subtitle_window(self) -> None:
        if self.subtitle_window is not None:
            self.subtitle_window.close()
        self._clear_subtitle_refs()

    def _clear_subtitle_refs(self) -> None:
        if self.subtitle_progress_bar in self._progress_bars:
            self._progress_bars.remove(self.subtitle_progress_bar)
        self.subtitle_window = None; self.subtitle_results_tree = None; self.subtitle_results_tabs = None; self.subtitle_results_trees_by_target = {}; self.subtitle_progress_bar = None
        self.subtitle_search_button = None; self.subtitle_download_button = None; self.subtitle_best_button = None; self.subtitle_password_entry = None

    def toggle_subtitle_password_visibility(self, *_args: Any) -> None:
        if self.subtitle_password_entry is not None:
            self.subtitle_password_entry.setEchoMode(QLineEdit.Normal if self.subtitle_show_password_var.get() else QLineEdit.Password)

    def update_subtitle_search_button_text(self) -> None:
        if self.subtitle_search_button is None:
            return
        running = (
            self.current_operation == "subtitle_search"
            and self.worker is not None
            and self.worker.is_alive()
        )
        self.subtitle_search_button.setText(
            self.tr("button_cancel_job") if running else self.tr("button_search_subtitles")
        )
        self.subtitle_search_button.setEnabled(
            running or self.current_operation is None
        )

    def set_subtitle_results(self, results: list[SubtitleResult]) -> None:
        self.subtitle_results = {result.key: result for result in results}
        self.remember_subtitle_session()
        tables = self.subtitle_results_trees_by_target or {0: self.subtitle_results_tree}
        for table in tables.values():
            if table is not None:
                table.setRowCount(0)
        for result in results:
            table = tables.get(result.target_index)
            if table is None:
                continue
            row = table.rowCount(); table.insertRow(row)
            target = self.subtitle_targets[result.target_index] if result.target_index < len(self.subtitle_targets) else None
            target_text = target.output_stem if target else str(result.target_index + 1)
            flags: list[str] = []
            if result.hearing_impaired: flags.append(self.tr("value_subtitle_flag_hi"))
            if result.forced: flags.append(self.tr("value_subtitle_flag_forced"))
            if result.from_trusted: flags.append(self.tr("value_subtitle_flag_trusted"))
            if result.machine_translated: flags.append(self.tr("value_subtitle_flag_machine"))
            if result.ai_translated: flags.append(self.tr("value_subtitle_flag_ai"))
            values = [self.subtitle_download_status(result.key), target_text, result.language, result.release, result.fps, ", ".join(flags), str(result.downloads), result.file_name]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.UserRole, result.key); table.setItem(row, col, item)
        for table in tables.values():
            if table is not None and table.rowCount():
                table.selectRow(0)
        self.subtitle_status_var.set(self.tr("log_subtitle_results_found", count=len(results)))

    def selected_subtitle_results(self) -> list[SubtitleResult]:
        table = self.subtitle_results_tree
        if table is None:
            return []
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
        output: list[SubtitleResult] = []
        for row in rows:
            item = table.item(row, 0)
            if item is None: continue
            result = self.subtitle_results.get(str(item.data(Qt.UserRole)))
            if result is not None: output.append(result)
        return output

    def mark_subtitle_result_downloaded(self, result_key: str, destination: Path) -> None:
        self.subtitle_downloaded_paths[result_key] = destination
        self.remember_subtitle_session()
        tables = self.subtitle_results_trees_by_target.values() or [self.subtitle_results_tree]
        for table in tables:
            if table is None:
                continue
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and str(item.data(Qt.UserRole)) == result_key:
                    item.setText(self.tr("value_subtitle_downloaded"))
                    return

    # ------------------------------------------------------------------
    # Audio adjust dialog
    # ------------------------------------------------------------------
    def open_audio_adjust_window(self) -> None:
        try:
            settings = self.collect_settings()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc)); return

        groups: list[tuple[str, list[Any], str]] = []
        batch_audio_mode = False
        source_raw = self.extract_source_var.get().strip()
        source = Path(source_raw).expanduser() if source_raw else None
        if source is not None and source.is_dir():
            try:
                _batch_settings, _source_dir, _extract_root, batch_tasks = self.collect_batch_folder_settings(require_mux=False)
                for task in batch_tasks:
                    if not task.extract_dir.is_dir():
                        continue
                    config = load_or_create_template_config(settings.template_path, task.extract_dir)
                    items, _, _ = discover_track_items(config, task.extract_dir, settings.include_extra_subtitles)
                    audio_items = [item for item in items if track_type_value(item) == 0]
                    if audio_items:
                        groups.append((f"{episode_code(task.episode_ref)} · {task.source.name}", audio_items, str(task.extract_dir.resolve())))
                batch_audio_mode = bool(groups)
            except UserVisibleError:
                # A normal track folder remains a valid single-folder workflow.
                groups = []
        if not groups:
            try:
                config = load_or_create_template_config(settings.template_path, settings.media_dir)
                items, _, _ = discover_track_items(config, settings.media_dir, settings.include_extra_subtitles)
            except UserVisibleError as exc:
                self.show_error(self.tr("dialog_missing_info"), str(exc)); return
            audio_items = [item for item in items if track_type_value(item) == 0]
            if audio_items:
                groups.append((settings.media_dir.name, audio_items, str(settings.media_dir.resolve())))
        if not groups:
            self.show_info(self.tr("dialog_missing_info"), self.tr("error_audio_adjust_none")); return
        self.close_audio_adjust_window()
        dialog = QDialog(self); dialog.setObjectName("DialogRoot"); dialog.setWindowTitle(f"{APP_NAME} - {self.tr('window_audio_adjust_title')}"); dialog.resize(1180, 560)
        self.audio_adjust_window = dialog
        layout = QVBoxLayout(dialog); layout.setContentsMargins(16,16,16,16); layout.setSpacing(10)
        card, card_layout = self._card("DialogCard"); layout.addWidget(card, 1)
        self.audio_adjust_rows = []
        self.audio_adjust_rows_by_episode = {}
        self.audio_adjust_presets_by_episode = {}
        self.audio_adjust_episode_labels_by_dir = {key: label for label, _items, key in groups}
        self.audio_adjust_current_var.set("")
        self.audio_adjust_groups = groups
        self.audio_adjust_batch_mode = batch_audio_mode
        self._audio_heading_labels: list[tuple[QLabel,str]] = []
        if len(groups) == 1:
            label, audio_items, key = groups[0]
            page, rows = self._build_audio_adjust_page(audio_items)
            card_layout.addWidget(page, 1)
            self.audio_adjust_rows = rows
            self.audio_adjust_rows_by_episode[key] = rows
        else:
            tabs = QTabWidget(); self.audio_adjust_tabs = tabs; card_layout.addWidget(tabs, 1)
            for label, _audio_items, _key in groups:
                tabs.addTab(QWidget(), label)
            tabs.currentChanged.connect(self._activate_audio_adjust_tab)
            self._activate_audio_adjust_tab(0)
        hint=QLabel(self.tr("audio_adjust_hint")); hint.setObjectName("Muted"); hint.setWordWrap(True); card_layout.addWidget(hint)
        progress_layout=QVBoxLayout(); self.audio_adjust_progress_bar,_=self._dialog_progress_block(progress_layout)
        current_label = QLabel(); current_label.setObjectName("Muted"); current_label.setWordWrap(True)
        self.audio_adjust_current_var.bind(lambda value: current_label.setText(str(value)))
        progress_layout.addWidget(current_label)
        card_layout.addLayout(progress_layout)
        actions=QHBoxLayout(); actions.addStretch(1)
        self.audio_adjust_apply_all_button = self._button("button_apply_audio_to_all_episodes", self.apply_audio_settings_to_all_episodes)
        self.audio_adjust_apply_all_button.setVisible(batch_audio_mode)
        actions.addWidget(self.audio_adjust_apply_all_button)
        self.audio_adjust_apply_button=self._button("button_apply_audio_adjust", self.start_audio_adjust, primary=True); actions.addWidget(self.audio_adjust_apply_button); card_layout.addLayout(actions)
        self.update_audio_apply_all_button_state()
        self.sync_progress_widget(self.audio_adjust_progress_bar)
        dialog.finished.connect(lambda _r:self._clear_audio_refs()); dialog.show()

    def _build_audio_adjust_page(self, audio_items: list[Any]) -> tuple[QScrollArea, list[dict[str, Any]]]:
        scroll = QScrollArea(); scroll.setObjectName("DialogScroll"); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        rows_widget = QWidget(); grid = QGridLayout(rows_widget); grid.setContentsMargins(4,4,4,4); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(9)
        grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(rows_widget)
        headings = ["", "heading_audio_file", "heading_audio_delta", "heading_audio_speed", "heading_audio_codec", "heading_audio_bitrate", "heading_audio_rate", "heading_audio_layout", "heading_audio_volume"]
        for col,key in enumerate(headings):
            if not key: continue
            label = QLabel(); label.setObjectName("TableHeading"); self.localize_widget(label,key); grid.addWidget(label,0,col); self._audio_heading_labels.append((label,key))
        grid.setColumnStretch(1,1)
        rows: list[dict[str, Any]] = []
        codec_values = sorted(SUPPORTED_AUDIO_ENCODERS)
        speed_values = [("auto", self.tr("speed_factor_auto"))] + [(key,self.tr(f"speed_factor_{key}")) for key in AUDIO_SPEED_FACTORS if key != "auto"]
        for r,item in enumerate(audio_items, start=1):
            defaults = audio_probe_defaults(item.path)
            selected = ValueVar(False); delta = ValueVar(""); codec = ValueVar(defaults["codec"] if defaults["codec"] in SUPPORTED_AUDIO_ENCODERS else "eac3")
            bitrate=ValueVar(defaults["bitrate"]); rate=ValueVar(defaults["sample_rate"]); layout_var=ValueVar(defaults["channel_layout"]); volume=ValueVar(1.0); speed=ValueVar(speed_values[0][1])
            check=self._bind_check(selected,QCheckBox()); check.toggled.connect(self.update_audio_apply_all_button_state); grid.addWidget(check,r,0)
            name=QLabel(item.path.name); name.setObjectName("FieldLabel"); grid.addWidget(name,r,1)
            grid.addWidget(self._bind_line(delta,QLineEdit()),r,2)
            speed_combo=QComboBox(); speed_combo.addItems([label for _,label in speed_values]); self._bind_combo_text(speed,speed_combo); grid.addWidget(speed_combo,r,3)
            codec_combo=QComboBox(); codec_combo.setEditable(True); codec_combo.addItems(codec_values); self._bind_combo_text(codec,codec_combo); grid.addWidget(codec_combo,r,4)
            grid.addWidget(self._bind_line(bitrate,QLineEdit()),r,5); grid.addWidget(self._bind_line(rate,QLineEdit()),r,6); grid.addWidget(self._bind_line(layout_var,QLineEdit()),r,7)
            volume_host=QWidget(); vh=QHBoxLayout(volume_host); vh.setContentsMargins(0,0,0,0); slider=QSlider(Qt.Horizontal); slider.setRange(10,50); slider.setValue(10); value_label=QLabel("1.0x"); value_label.setMinimumWidth(42)
            slider.valueChanged.connect(lambda v,var=volume,lbl=value_label: (var.set(v/10.0), lbl.setText(f"{v/10.0:.1f}x")))
            vh.addWidget(slider,1); vh.addWidget(value_label); grid.addWidget(volume_host,r,8)
            rows.append({"path":item.path,"language":track_language_value(item) or "und","selected":selected,"delta":delta,"codec":codec,"bitrate":bitrate,"sample_rate":rate,"layout":layout_var,"volume":volume,"volume_slider":slider,"volume_label":value_label,"speed":speed,"speed_values":speed_values,"defaults":defaults,"name_label":name})
        # Keep all headings and audio rows anchored to the top of the scroll viewport.
        # Any spare vertical room belongs below the final row instead of being spread
        # between the header and editors.
        grid.setRowStretch(len(audio_items) + 1, 1)
        return scroll, rows

    def _activate_audio_adjust_tab(self, index: int) -> None:
        """Build a batch episode's heavy audio controls only when it is opened."""
        if self.audio_adjust_tabs is None or index < 0 or index >= len(self.audio_adjust_groups):
            return
        page = self.audio_adjust_tabs.widget(index)
        if page is None or page.property("audioAdjustPageBuilt"):
            return
        _label, audio_items, key = self.audio_adjust_groups[index]
        page_layout = QVBoxLayout(page); page_layout.setContentsMargins(0, 0, 0, 0)
        scroll, rows = self._build_audio_adjust_page(audio_items)
        page_layout.addWidget(scroll)
        page.setProperty("audioAdjustPageBuilt", True)
        self.audio_adjust_rows_by_episode[key] = rows
        self.audio_adjust_rows.extend(rows)
        for row in rows:
            preset = self.audio_adjust_presets_by_episode.get(key, {}).get(row["language"])
            if preset is not None:
                self._apply_audio_preset(row, preset)
        self.update_audio_apply_all_button_state()

    def _current_audio_adjust_rows(self) -> list[dict[str, Any]]:
        if self.audio_adjust_tabs is None:
            return self.audio_adjust_rows
        index = self.audio_adjust_tabs.currentIndex()
        if index < 0 or index >= len(self.audio_adjust_groups):
            return []
        return self.audio_adjust_rows_by_episode.get(self.audio_adjust_groups[index][2], [])

    @staticmethod
    def _audio_preset_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "delta": row["delta"].get(), "codec": row["codec"].get(),
            "bitrate": row["bitrate"].get(), "sample_rate": row["sample_rate"].get(),
            "layout": row["layout"].get(), "volume": row["volume"].get(),
            "speed": row["speed"].get(),
        }

    @staticmethod
    def _apply_audio_preset(row: dict[str, Any], preset: dict[str, Any]) -> None:
        for key in ("delta", "codec", "bitrate", "sample_rate", "layout", "speed"):
            row[key].set(preset[key])
        volume = float(preset["volume"])
        row["volume"].set(volume)
        slider = row.get("volume_slider")
        if isinstance(slider, QSlider):
            slider.setValue(round(volume * 10))
        row["selected"].set(True)

    def update_audio_apply_all_button_state(self, *_args: Any) -> None:
        if self.audio_adjust_apply_all_button is None:
            return
        selected = any(row["selected"].get() for row in self._current_audio_adjust_rows())
        available = self.audio_adjust_batch_mode and selected
        self.audio_adjust_apply_all_button.setVisible(available)
        self.audio_adjust_apply_all_button.setEnabled(available)

    def apply_audio_settings_to_all_episodes(self) -> None:
        source_rows = [row for row in self._current_audio_adjust_rows() if row["selected"].get()]
        if not source_rows:
            self.show_toast(self.tr("toast_audio_apply_all_error"), success=False)
            return
        presets = {row["language"]: self._audio_preset_from_row(row) for row in source_rows}
        matched_tracks = 0
        matched_episodes: set[str] = set()
        for _label, _audio_items, key in self.audio_adjust_groups:
            matches = [
                item for item in _audio_items
                if (track_language_value(item) or "und") in presets
            ]
            if matches:
                matched_tracks += len(matches)
                matched_episodes.add(key)
            episode_presets = self.audio_adjust_presets_by_episode.setdefault(key, {})
            episode_presets.update(presets)
            for row in self.audio_adjust_rows_by_episode.get(key, []):
                preset = presets.get(row["language"])
                if preset is not None:
                    self._apply_audio_preset(row, preset)
        self.update_audio_apply_all_button_state()
        if not matched_tracks:
            self.show_toast(self.tr("toast_audio_apply_all_error"), success=False)
            return
        self.show_toast(
            self.tr(
                "toast_audio_apply_all_success",
                episodes=len(matched_episodes),
                tracks=matched_tracks,
            ),
            success=True,
        )

    def _audio_adjust_task_from_preset(
        self,
        path: Path,
        defaults: dict[str, str],
        preset: dict[str, Any],
    ) -> AudioAdjustTask:
        speed_label = str(preset["speed"]).strip()
        speed_labels = {
            self.tr("speed_factor_auto"): "auto",
            **{self.tr(f"speed_factor_{key}"): key for key in AUDIO_SPEED_FACTORS if key != "auto"},
        }
        return AudioAdjustTask(
            path=path,
            delta_seconds=parse_milliseconds_delta(str(preset["delta"])),
            codec=str(preset["codec"]).strip().lower(),
            bitrate=str(preset["bitrate"]).strip(),
            sample_rate=str(preset["sample_rate"]).strip() or "48000",
            channel_layout=str(preset["layout"]).strip() or "stereo",
            volume_multiplier=normalise_audio_volume_multiplier(preset["volume"]),
            speed_factor=AUDIO_SPEED_FACTORS.get(speed_labels.get(speed_label, "auto"), 1.0),
            original_codec=defaults.get("codec", ""),
            original_bitrate=defaults.get("bitrate", ""),
            original_sample_rate=defaults.get("sample_rate", ""),
            original_channel_layout=defaults.get("channel_layout", ""),
        )

    def collect_audio_adjust_tasks(self) -> list[AudioAdjustTask]:
        tasks: list[AudioAdjustTask] = []
        for row in self.audio_adjust_rows:
            if not row["selected"].get():
                continue
            delta = parse_milliseconds_delta(row["delta"].get())
            codec = row["codec"].get().strip().lower()
            speed_label = row["speed"].get().strip()
            speed_label_to_key = {
                label: key
                for key, label in row.get(
                    "speed_values", [("auto", self.tr("speed_factor_auto"))]
                )
            }
            speed_key = speed_label_to_key.get(speed_label, "auto")
            speed = AUDIO_SPEED_FACTORS.get(speed_key, 1.0)
            tasks.append(
                AudioAdjustTask(
                    path=Path(row["path"]),
                    delta_seconds=delta,
                    codec=codec,
                    bitrate=row["bitrate"].get().strip(),
                    sample_rate=row["sample_rate"].get().strip() or "48000",
                    channel_layout=row["layout"].get().strip() or "stereo",
                    volume_multiplier=normalise_audio_volume_multiplier(row["volume"].get()),
                    speed_factor=speed,
                    original_codec=row["defaults"].get("codec", ""),
                    original_bitrate=row["defaults"].get("bitrate", ""),
                    original_sample_rate=row["defaults"].get("sample_rate", ""),
                    original_channel_layout=row["defaults"].get("channel_layout", ""),
                )
            )
        # Lazy tabs do not build their editors until opened.  Their presets
        # must nevertheless become real ffmpeg tasks when the user applies a
        # language-specific setting to every episode.
        if self.audio_adjust_batch_mode:
            loaded_episode_keys = set(self.audio_adjust_rows_by_episode)
            for _label, audio_items, episode_key in self.audio_adjust_groups:
                if episode_key in loaded_episode_keys:
                    continue
                presets = self.audio_adjust_presets_by_episode.get(episode_key, {})
                for item in audio_items:
                    preset = presets.get(track_language_value(item) or "und")
                    if preset is None:
                        continue
                    tasks.append(
                        self._audio_adjust_task_from_preset(
                            item.path,
                            audio_probe_defaults(item.path),
                            preset,
                        )
                    )
        if not tasks:
            raise UserVisibleError(self.tr("error_audio_adjust_none"))
        self.audio_adjust_skipped_unchanged_count = 0
        if self.audio_adjust_batch_mode:
            unchanged = [task for task in tasks if not audio_adjust_has_work(task)]
            tasks = [task for task in tasks if audio_adjust_has_work(task)]
            self.audio_adjust_skipped_unchanged_count = len(unchanged)
            if not tasks:
                return []
        for task in tasks:
            validate_audio_adjust_task(task)
        return tasks

    def start_audio_adjust(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if self.current_operation == "audio_adjust":
                self.cancel_current_operation()
            else:
                self.show_info(
                    self.tr("dialog_in_progress_title"),
                    self.tr("dialog_in_progress_message"),
                )
            return
        try:
            tasks = self.collect_audio_adjust_tasks()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return
        if not tasks and self.audio_adjust_batch_mode:
            self.queue_log(
                self.tr(
                    "log_audio_adjust_skipped_unchanged",
                    count=self.audio_adjust_skipped_unchanged_count,
                )
            )
            self.show_info(
                self.tr("dialog_missing_info"),
                self.tr("info_audio_adjust_no_changes"),
            )
            return
        if self.audio_adjust_skipped_unchanged_count:
            self.queue_log(
                self.tr(
                    "log_audio_adjust_skipped_unchanged",
                    count=self.audio_adjust_skipped_unchanged_count,
                )
            )
        self.update_audio_adjust_apply_button_text()

        def work() -> None:
            for index, task in enumerate(tasks, start=1):
                self.check_cancelled()
                episode_label = self.audio_adjust_episode_labels_by_dir.get(
                    str(task.path.parent.resolve()),
                    task.path.parent.name,
                )
                self.log_queue.put((
                    "set_audio_adjust_current",
                    f"{episode_label} · {task.path.name} ({index}/{len(tasks)})",
                ))
                output_path = run_audio_adjust_task(
                    task,
                    self.queue_log,
                    cancel_event=self.cancel_event,
                    register_process=self.register_active_process,
                    unregister_process=self.unregister_active_process,
                )
                self.log_queue.put(("audio_adjust_done", (task.path, output_path)))
            if not self.audio_adjust_batch_mode:
                self.log_queue.put(("close_audio_adjust", True))

        started = self.run_background(
            work, self.tr("status_adjusting_audio"), operation="audio_adjust"
        )
        if started:
            self.update_audio_adjust_apply_button_text()

    def _refresh_audio_headers(self) -> None:
        for label,key in getattr(self,"_audio_heading_labels",[]): label.setText(self.tr(key))

    def mark_audio_adjust_done(self, source: Path, output: Path) -> None:
        """Keep a batch dialog usable after one row has been regenerated."""
        for row in self.audio_adjust_rows:
            if Path(row["path"]) != source:
                continue
            row["path"] = output
            row["selected"].set(False)
            row["defaults"] = audio_probe_defaults(output)
            label = row.get("name_label")
            if isinstance(label, QLabel):
                label.setText(output.name)
            return

    def close_audio_adjust_window(self) -> None:
        if self.audio_adjust_window is not None: self.audio_adjust_window.close()
        self._clear_audio_refs()

    def _clear_audio_refs(self) -> None:
        if self.audio_adjust_progress_bar in self._progress_bars: self._progress_bars.remove(self.audio_adjust_progress_bar)
        self.audio_adjust_window=None; self.audio_adjust_apply_button=None; self.audio_adjust_apply_all_button=None; self.audio_adjust_progress_bar=None; self.audio_adjust_rows=[]; self.audio_adjust_rows_by_episode={}; self.audio_adjust_tabs=None; self.audio_adjust_groups=[]; self.audio_adjust_batch_mode=False; self.audio_adjust_presets_by_episode={}; self.audio_adjust_skipped_unchanged_count=0; self.audio_adjust_episode_labels_by_dir={}; self.audio_adjust_current_var.set(""); self._toast_widget=None

    def update_audio_adjust_apply_button_text(self) -> None:
        if self.audio_adjust_apply_button is None: return
        running = self.current_operation == "audio_adjust" and self.worker is not None and self.worker.is_alive()
        self.audio_adjust_apply_button.setText(self.tr("button_cancel" if running else "button_apply_audio_adjust"))
        self.audio_adjust_apply_button.setEnabled(True)

    # ------------------------------------------------------------------
    # TMDB search dialog
    # ------------------------------------------------------------------
    def open_tmdb_search_window(self) -> None:
        if not self.api_key_var.get().strip():
            self.show_error(self.tr("dialog_missing_info"), self.tr("error_tmdb_api_empty")); return
        self.close_tmdb_search_window()
        dialog=QDialog(self); dialog.setObjectName("DialogRoot"); dialog.setWindowTitle(f"{APP_NAME} - {self.tr('window_tmdb_search_title')}"); dialog.resize(900,560); self.tmdb_search_window=dialog
        layout=QVBoxLayout(dialog); layout.setContentsMargins(16,16,16,16); card,card_layout=self._card("DialogCard"); layout.addWidget(card,1)
        row=QHBoxLayout(); label=self._field_label("label_tmdb_search_query"); row.addWidget(label); query=self._bind_line(self.tmdb_search_query_var,QLineEdit()); row.addWidget(query,1); self.tmdb_search_action_button=self._button("button_tmdb_search",self.start_tmdb_name_search,primary=True); row.addWidget(self.tmdb_search_action_button); card_layout.addLayout(row)
        status=QLabel(); status.setObjectName("StatusText"); self.tmdb_search_status_var.bind(lambda v:status.setText(str(v))); card_layout.addWidget(status)
        table=QTableWidget(0,5); table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.SingleSelection); table.verticalHeader().setVisible(False); table.setAlternatingRowColors(True); table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); table.doubleClicked.connect(lambda _i:self.use_selected_tmdb_search_result())
        self.tmdb_search_tree=table; self._refresh_tmdb_headers(); card_layout.addWidget(table,1)
        actions=QHBoxLayout(); actions.addStretch(1); actions.addWidget(self._button("button_cancel",self.close_tmdb_search_window)); actions.addWidget(self._button("button_tmdb_use_selected",self.use_selected_tmdb_search_result,primary=True)); card_layout.addLayout(actions)
        self.tmdb_search_status_var.set(self.tr("label_tmdb_search_status_ready")); dialog.finished.connect(lambda _r:self._clear_tmdb_refs()); dialog.show(); query.setFocus()

    def _refresh_tmdb_headers(self) -> None:
        if self.tmdb_search_tree is not None:
            self.tmdb_search_tree.setHorizontalHeaderLabels([self.tr("heading_tmdb_search_type"),self.tr("heading_tmdb_search_title"),self.tr("heading_tmdb_search_original_title"),self.tr("heading_tmdb_search_year"),self.tr("heading_tmdb_search_id")])

    def close_tmdb_search_window(self) -> None:
        if self.tmdb_search_window is not None: self.tmdb_search_window.close()
        self._clear_tmdb_refs()

    def _clear_tmdb_refs(self) -> None:
        self.tmdb_search_window=None; self.tmdb_search_tree=None; self.tmdb_search_action_button=None; self.tmdb_search_results=[]

    def set_tmdb_search_results(self, results: list[dict[str, Any]]) -> None:
        self.tmdb_search_results=results
        table=self.tmdb_search_tree
        if table is None: return
        table.setRowCount(0)
        for index,result in enumerate(results):
            row=table.rowCount(); table.insertRow(row)
            media_type=str(result.get("media_type") or "")
            type_label=self.tr("media_type_movie") if media_type=="movie" else self.tr("media_type_tv") if media_type=="tv" else media_type
            title=str(result.get("title") or result.get("name") or ""); original=str(result.get("original_title") or result.get("original_name") or "")
            date=str(result.get("release_date") or result.get("first_air_date") or ""); year=date[:4] if len(date)>=4 else ""; tmdb_id=str(result.get("id") or "")
            for col,val in enumerate([type_label,title,original,year,tmdb_id]):
                item=QTableWidgetItem(val); item.setData(Qt.UserRole,index); table.setItem(row,col,item)
        if results: table.selectRow(0)

    def use_selected_tmdb_search_result(self) -> None:
        table = self.tmdb_search_tree
        if table is None:
            return
        row = table.currentRow()
        if row < 0 or row >= table.rowCount():
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_tmdb_search_no_selection"),
            )
            return

        item = table.item(row, 0)
        idx = (
            int(item.data(Qt.UserRole))
            if item is not None and item.data(Qt.UserRole) is not None
            else row
        )
        if idx < 0 or idx >= len(self.tmdb_search_results):
            return

        result = self.tmdb_search_results[idx]
        tmdb_id = str(result.get("id") or "").strip()
        media_type = normalise_tmdb_media_type(str(result.get("media_type") or "movie"))
        title = str(result.get("title") or result.get("name") or "").strip()
        date = str(result.get("release_date") or result.get("first_air_date") or "")
        found_year = date[:4] if len(date) >= 4 else ""
        if not tmdb_id:
            return

        # Manual selection must keep the exact chosen TMDB record.  The old Qt
        # port called start_find_tmdb_id(auto=True) here, which searched the
        # folder again and could replace/ignore the user's explicit selection.
        self.tmdb_id_var.set(tmdb_id)
        self.media_type_var.set(media_type)
        self.refresh_tmdb_media_type_display()
        if title:
            self.tmdb_search_query_var.set(title)

        try:
            settings = self.collect_settings()
        except UserVisibleError as exc:
            self.save_preferences()
            self.close_tmdb_search_window()
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        settings.tmdb_id = tmdb_id
        settings.media_type = media_type
        self.save_preferences()
        self.close_tmdb_search_window()

        # Refresh every field derived from the selected TMDB record, matching
        # the proven Tk UI behavior: FPS, output title/path (including the
        # selected result's release year) and MKV title.
        self.video_fps_var.set("")
        settings.video_fps = ""

        def work() -> None:
            fps = detect_first_video_fps_from_media_dir(settings.media_dir)
            self.log_queue.put(("set_video_fps", fps))
            if fps:
                settings.video_fps = fps
                self.queue_log(self.tr("log_video_fps_detected", fps=fps))

            episode_ref = episode_ref_from_settings(settings)
            image_title = tmdb_output_title_for_language(
                settings,
                tmdb_id,
                settings.image_language,
                episode_ref,
            )
            if image_title:
                base_output_path = tmdb_output_path(settings.media_dir, image_title)
                if (
                    settings.output_name_year
                    and normalise_tmdb_media_type(settings.media_type) == "movie"
                    and found_year
                ):
                    # This is an explicit manual match: the selected TMDB
                    # result's year must override any year parsed from the
                    # release folder/file name or from the previous output.
                    output_path = output_path_with_year(
                        base_output_path, found_year, settings.output_name_extra
                    )
                else:
                    output_path = output_path_with_optional_year(
                        base_output_path,
                        enabled=settings.output_name_year,
                        media_type=settings.media_type,
                        media_dir=settings.media_dir,
                        extra=settings.output_name_extra,
                        tmdb_year=found_year,
                    )
                self.log_queue.put(("set_output", str(output_path)))
                self.queue_log(
                    self.tr("log_output_from_artwork_language", name=output_path.name)
                )

            tag_title = tmdb_output_title_for_language(
                settings,
                tmdb_id,
                settings.tag_language,
                episode_ref,
            )
            if tag_title:
                self.log_queue.put(("set_title", tag_title))
                self.queue_log(self.tr("log_title_from_tag_language", title=tag_title))

            year_text = f" ({found_year})" if found_year else ""
            self.queue_log(
                self.tr(
                    "log_tmdb_id_found",
                    tmdb_id=tmdb_id,
                    title=image_title or tag_title or title,
                    year_text=year_text,
                )
            )

        self.run_background(work, self.tr("status_finding_tmdb"))

    # ------------------------------------------------------------------
    # Extract detail dialog
    # ------------------------------------------------------------------
    def ensure_extract_window(self) -> None:
        if self.extract_window is not None and self.extract_window.isVisible():
            self.extract_window.raise_(); self.extract_window.activateWindow(); return
        dialog=QDialog(self); dialog.setObjectName("DialogRoot"); dialog.setWindowTitle(f"{APP_NAME} - {self.tr('section_extract')}"); dialog.resize(1000,600); dialog.setWindowModality(Qt.WindowModal); self.extract_window=dialog
        layout=QVBoxLayout(dialog); layout.setContentsMargins(16,16,16,16); card,card_layout=self._card("DialogCard"); layout.addWidget(card,1)
        table=QTableWidget(0,4); table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.SingleSelection); table.verticalHeader().setVisible(False); table.setAlternatingRowColors(True); table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch); table.cellDoubleClicked.connect(self._extract_cell_double_clicked); table.itemChanged.connect(self._extract_table_item_changed); self.extract_tree=table; self._refresh_extract_headers(); card_layout.addWidget(table,1)
        prog=QVBoxLayout(); self.extract_progress_bar,_=self._dialog_progress_block(prog); card_layout.addLayout(prog)
        controls=QHBoxLayout(); self.extract_toggle_button=self._button("button_toggle_selection",self.toggle_selected_extract_items); self.extract_all_button=self._button("button_select_all",self.toggle_all_extract_items); self.extract_button=self._button("button_extract_selected",self.start_extract,primary=True); controls.addWidget(self.extract_toggle_button); controls.addWidget(self.extract_all_button); controls.addStretch(1); controls.addWidget(self.extract_button); card_layout.addLayout(controls)
        dialog.finished.connect(lambda _r:self._clear_extract_refs()); dialog.show(); dialog.raise_(); dialog.activateWindow(); self.populate_extract_tree(); self.populate_extract_language_inputs(); self.sync_progress_widget(self.extract_progress_bar)

    def _refresh_extract_headers(self) -> None:
        if self.extract_tree is not None: self.extract_tree.setHorizontalHeaderLabels([self.tr("heading_selected"),self.tr("heading_track"),self.tr("heading_extract_language"),self.tr("heading_output_name")])

    def close_extract_window(self) -> None:
        if self.extract_window is not None: self.extract_window.close()
        self._clear_extract_refs()

    def _clear_extract_refs(self) -> None:
        if self.extract_progress_bar in self._progress_bars: self._progress_bars.remove(self.extract_progress_bar)
        self.extract_window=None; self.extract_tree=None; self.extract_progress_bar=None; self.extract_toggle_button=None; self.extract_all_button=None; self.extract_button=None

    def set_extract_items(self, items: list[ExtractItem]) -> None:
        self.extract_items={item.key:item for item in items}; self.ensure_extract_window(); self.populate_extract_tree(); self.update_extract_all_button_text()

    def populate_extract_tree(self) -> None:
        table=self.extract_tree
        if table is None: return
        blocker=QSignalBlocker(table)
        table.setRowCount(0)
        for item in self.extract_items.values():
            row=table.rowCount(); table.insertRow(row)
            check=QCheckBox(); check.setChecked(item.selected); check.toggled.connect(lambda checked,key=item.key:self._extract_checked(key,checked)); table.setCellWidget(row,0,self._center_widget(check))

            track=QTableWidgetItem(item.label); track.setData(Qt.UserRole,item.key); track.setFlags(track.flags() & ~Qt.ItemFlag.ItemIsEditable); table.setItem(row,1,track)

            language=QTableWidgetItem(item.language_override or item.language)
            language.setData(Qt.UserRole,item.key)
            if item.kind != "track":
                language.setFlags(language.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row,2,language)

            output=QTableWidgetItem(item.output_name); output.setFlags(output.flags() & ~Qt.ItemFlag.ItemIsEditable); table.setItem(row,3,output)
            self._style_extract_row(row,item.selected)
        del blocker
        if table.rowCount(): table.selectRow(0)

    def _extract_checked(self,key:str,checked:bool)->None:
        item=self.extract_items.get(key)
        if item is None:return
        item.selected=checked
        if self.extract_tree is not None:
            for row in range(self.extract_tree.rowCount()):
                cell=self.extract_tree.item(row,1)
                if cell is not None and cell.data(Qt.UserRole)==key: self._style_extract_row(row,checked); break
        self.update_extract_all_button_text()

    def _style_extract_row(self,row:int,active:bool)->None:
        if self.extract_tree is None:return
        p=palette_for(self.theme_mode); color=QColor(p.text if active else p.disabled)
        for col in range(1,4):
            item=self.extract_tree.item(row,col)
            if item is not None:
                item.setForeground(color); font=item.font(); font.setStrikeOut(not active); item.setFont(font)

    def populate_extract_language_inputs(self) -> None:
        # Legacy Tkinter UI used a second editor below the table for ``und``
        # tracks.  In the Qt UI the Language column itself is the single source
        # of truth, so there is intentionally no extra editor block.
        self.extract_language_vars={}
        self.extract_language_output_vars={}

    def _extract_key_for_row(self, row: int) -> str:
        if self.extract_tree is None or row < 0 or row >= self.extract_tree.rowCount():
            return ""
        track_item=self.extract_tree.item(row,1)
        return str(track_item.data(Qt.UserRole) or "") if track_item is not None else ""

    def _extract_cell_double_clicked(self, row: int, column: int) -> None:
        table=self.extract_tree
        if table is None:
            return
        key=self._extract_key_for_row(row)
        item=self.extract_items.get(key)
        if item is None:
            return

        if column == 2 and item.kind == "track":
            # Only the Language column is editable. Programmatic editItem()
            # keeps the table globally read-only for every other column.
            language_item=table.item(row,2)
            if language_item is not None:
                table.editItem(language_item)
            return

        if column in (1,3):
            # Double-clicking Track or Output name is a quick enable/disable
            # gesture, not a text edit.  Do this in-place instead of rebuilding
            # the table: rebuilding resets the viewport and then selecting the
            # original row makes Qt scroll it to the bottom of the visible area.
            # Keeping the existing row widgets intact preserves the user's
            # scroll position so several consecutive rows can be toggled quickly.
            check_host = table.cellWidget(row, 0)
            check = check_host.findChild(QCheckBox) if check_host is not None else None
            if check is not None:
                check.setChecked(not check.isChecked())
            else:
                # Defensive fallback for a row without the expected checkbox.
                item.selected = not item.selected
                self._style_extract_row(row, item.selected)
                self.update_extract_all_button_text()
            return

    def _extract_table_item_changed(self, cell: QTableWidgetItem) -> None:
        table=self.extract_tree
        if table is None or cell.column() != 2:
            return
        row=cell.row()
        key=self._extract_key_for_row(row)
        item=self.extract_items.get(key)
        if item is None or item.kind != "track":
            return

        normalized=normalise_extract_language_override(cell.text())
        item.language_override=normalized
        rebuild_extract_output_names(list(self.extract_items.values()))

        # Normalize the visible language and immediately refresh every output
        # name because duplicate-language numbering may affect more than one row.
        blocker=QSignalBlocker(table)
        cell.setText(normalized or item.language)
        for table_row in range(table.rowCount()):
            row_key=self._extract_key_for_row(table_row)
            row_model=self.extract_items.get(row_key)
            if row_model is None:
                continue
            output_cell=table.item(table_row,3)
            if output_cell is not None:
                output_cell.setText(row_model.output_name)
        del blocker

    def _extract_language_changed(self,key:str,value:str)->None:
        # Kept for controller/API compatibility. All languages, not only ``und``,
        # may now be overridden directly from the table's Language column.
        item=self.extract_items.get(key)
        if item is None:return
        item.language_override=normalise_extract_language_override(value)
        rebuild_extract_output_names(list(self.extract_items.values()))
        if self.extract_tree is not None:
            blocker=QSignalBlocker(self.extract_tree)
            for row in range(self.extract_tree.rowCount()):
                if self._extract_key_for_row(row)==key:
                    self.extract_tree.item(row,2).setText(item.language_override or item.language)
                row_key=self._extract_key_for_row(row)
                row_model=self.extract_items.get(row_key)
                if row_model is not None and self.extract_tree.item(row,3) is not None:
                    self.extract_tree.item(row,3).setText(row_model.output_name)
            del blocker

    def refresh_extract_output_names(self) -> None:
        rebuild_extract_output_names(list(self.extract_items.values()))
        self.populate_extract_tree()

    def toggle_selected_extract_items(self) -> None:
        table=self.extract_tree
        if table is None:return
        row=table.currentRow()
        if row<0:return
        cell=table.item(row,1); key=str(cell.data(Qt.UserRole)) if cell is not None else ""; item=self.extract_items.get(key)
        if item is None:return
        check_host=table.cellWidget(row,0)
        check=check_host.findChild(QCheckBox) if check_host is not None else None
        if check is not None:
            check.setChecked(not check.isChecked())
        else:
            item.selected=not item.selected
            self._style_extract_row(row,item.selected)
            self.update_extract_all_button_text()

    def toggle_all_extract_items(self) -> None:
        if not self.extract_items:return
        target=not all(item.selected for item in self.extract_items.values())
        table=self.extract_tree
        for item in self.extract_items.values():
            item.selected=target
        if table is not None:
            # Update the existing row widgets in-place so Select All / Clear All
            # does not unexpectedly reset the user's current scroll position.
            for row in range(table.rowCount()):
                key=self._extract_key_for_row(row)
                row_item=self.extract_items.get(key)
                if row_item is None:
                    continue
                check_host=table.cellWidget(row,0)
                check=check_host.findChild(QCheckBox) if check_host is not None else None
                if check is not None:
                    blocker=QSignalBlocker(check)
                    check.setChecked(target)
                    del blocker
                self._style_extract_row(row,target)
        self.update_extract_all_button_text()

    def update_extract_all_button_text(self) -> None:
        if self.extract_all_button is None:return
        all_selected=bool(self.extract_items) and all(item.selected for item in self.extract_items.values()); self.extract_all_button.setText(self.tr("button_clear_all" if all_selected else "button_select_all"))

    def update_extract_tree_row(self, key: str) -> None:
        self.populate_extract_tree()

    # ------------------------------------------------------------------
    # Log dialog
    # ------------------------------------------------------------------
    @staticmethod
    def _split_log_progress(message: str) -> tuple[int | None, str]:
        """Extract standalone percentage updates from log text.

        mkvmerge/mkvextract can emit ``Progress: 1%``, ``Progress: 2%`` ... as
        separate lines. They are useful state, but poor log content. Keep the
        newest percentage for the horizontal bar and return only real log text.
        """
        percent: int | None = None
        kept: list[str] = []
        for line in str(message).splitlines() or [str(message)]:
            clean = line.strip()
            match = re.fullmatch(
                r"(?:(?:Progress|İlerleme)\s*:?\s*)?(\d{1,3})%",
                clean,
                flags=re.IGNORECASE,
            )
            if match:
                percent = max(0, min(100, int(match.group(1))))
            elif clean:
                kept.append(line)
        return percent, "\n".join(kept)

    def open_log_window(self) -> None:
        if self.log_window is not None and self.log_window.isVisible():
            self.log_window.raise_()
            self.log_window.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setObjectName("DialogRoot")
        dialog.setWindowTitle(self.tr("window_log_title", app=APP_NAME))
        dialog.resize(860, 500)
        self.log_window = dialog
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        progress_layout = QVBoxLayout()
        self.log_progress_bar, self.log_progress_label = self._dialog_progress_block(progress_layout)
        layout.addLayout(progress_layout)
        self.sync_progress_widget(self.log_progress_bar)

        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText("\n".join(self.log_lines))
        edit.verticalScrollBar().setValue(edit.verticalScrollBar().maximum())
        self.log_window_text = edit
        layout.addWidget(edit, 1)
        close = self._button("button_cancel", self.close_log_window)
        layout.addWidget(close, 0, Qt.AlignRight)
        dialog.finished.connect(lambda _r: self._clear_log_refs())
        dialog.show()

    def close_log_window(self) -> None:
        if self.log_window is not None:
            self.log_window.close()
        self._clear_log_refs()

    def _clear_log_refs(self) -> None:
        if self.log_progress_bar in self._progress_bars:
            self._progress_bars.remove(self.log_progress_bar)
        self.log_window = None
        self.log_window_text = None
        self.log_progress_bar = None
        self.log_progress_label = None

    def append_log(self, message: str) -> None:
        percent, visible_text = self._split_log_progress(message)
        if percent is not None:
            if self.log_progress_bar is not None:
                self.log_progress_bar.setRange(0, 100)
                self.log_progress_bar.setValue(percent)
            if self.log_progress_label is not None:
                self.log_progress_label.setText(self.tr("status_progress_percent", percent=percent))
        if not visible_text:
            return
        self.log_lines.append(visible_text)
        if self.log_window_text is not None:
            self.log_window_text.appendPlainText(visible_text)
            self.log_window_text.verticalScrollBar().setValue(
                self.log_window_text.verticalScrollBar().maximum()
            )

    def append_log_to_widget(self,widget:QPlainTextEdit,message:str)->None: widget.appendPlainText(message)

    # ------------------------------------------------------------------
    # Busy/progress and worker queue
    # ------------------------------------------------------------------
    def set_busy(self,busy:bool,status:str|None=None)->None:
        buttons=(self.scan_button,self.find_tmdb_button,self.tmdb_lookup_button,self.tmdb_search_action_button,self.download_button,self.subtitle_button,self.config_button,self.extract_scan_button,self.extract_toggle_button,self.extract_all_button,self.extract_button,self.batch_extract_button,self.batch_mux_button,self.third_party_button,self.subtitle_search_button,self.subtitle_download_button,self.subtitle_best_button)
        for button in buttons:
            if button is not None: button.setEnabled(not busy)
        self.update_subtitle_search_button_text()
        if self.mux_button is not None:
            if busy and self.current_operation=="mux": self.mux_button.setEnabled(True); self.mux_button.setText(self.tr("button_cancel_job"))
            else: self.mux_button.setEnabled(not busy); self.mux_button.setText(self.tr("button_create_mkv"))
        if busy:self.start_progress(status or self.tr("status_processing"))
        else:self.finish_progress()

    def progress_bars(self)->list[QProgressBar]: return [bar for bar in self._progress_bars if bar is not None]

    def sync_progress_widget(self, bar: QProgressBar | None) -> None:
        if bar is None:
            return
        try:
            value = max(0, min(100, int(float(self.progress_var.get()))))
        except (TypeError, ValueError):
            value = 0
        if self.worker is not None and self.worker.is_alive() and value <= 0:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(value)

    def start_progress(self,message:str)->None:
        self.progress_var.set(0);self.progress_status_var.set(self.short_status_message(message))
        for bar in self.progress_bars():bar.setRange(0,0)

    def finish_progress(self)->None:
        error_prefixes={texts["error_prefix"].split("{message}",1)[0] for texts in UI_TEXT.values()};has_error=any(str(self.progress_status_var.get()).startswith(prefix) for prefix in error_prefixes);target=0 if has_error else 100
        for bar in self.progress_bars():bar.setRange(0,100);bar.setValue(target)
        if has_error:self.progress_var.set(0);return
        self.progress_var.set(100)
        if str(self.progress_status_var.get()).endswith("..."):self.progress_status_var.set(self.tr("status_completed"))

    def set_progress_error(self,message:str)->None:
        for bar in self.progress_bars():bar.setRange(0,100);bar.setValue(0)
        self.progress_var.set(0);self.progress_status_var.set(self.short_status_message(self.tr("error_prefix",message=message)))

    def update_progress_from_log(self, message: str) -> None:
        clean = self.short_status_message(message)
        if not clean:
            return
        value, _visible_text = self._split_log_progress(clean)
        if value is None:
            match = re.search(
                r"(?:[İIiı]lerleme|Progress):?\s*(\d{1,3})%",
                clean,
                flags=re.IGNORECASE,
            )
            if match:
                value = min(100, max(0, int(match.group(1))))
        if value is not None:
            for bar in self.progress_bars():
                bar.setRange(0, 100)
                bar.setValue(value)
            self.progress_var.set(value)
            self.progress_status_var.set(self.tr("status_progress_percent", percent=value))
            return
        command_line = clean.startswith("/") and ("mkvmerge" in clean or "mkvextract" in clean)
        if not command_line:
            self.progress_status_var.set(clean)

    def _drain_log_queue(self)->None:
        while True:
            try:kind,value=self.log_queue.get_nowait()
            except queue.Empty:break
            if kind=="log":
                message=str(value);self.append_log(message);self.update_progress_from_log(message)
            elif kind=="error":
                message=str(value);self.append_log(self.tr("error_prefix",message=message));self.set_progress_error(message);self.show_error(self.tr("dialog_error_title"),message)
            elif kind=="busy":
                self.set_busy(bool(value));
                if not bool(value):self.update_audio_adjust_apply_button_text()
            elif kind=="app_update_available" and isinstance(value,dict):self.show_app_update_available(value)
            elif kind=="close_audio_adjust":self.close_audio_adjust_window()
            elif kind=="audio_adjust_done":
                try: source, output = value
                except (TypeError, ValueError): continue
                self.mark_audio_adjust_done(Path(str(source)), Path(str(output)))
            elif kind=="set_audio_adjust_current":self.audio_adjust_current_var.set(str(value))
            elif kind=="close_extract":self.close_extract_window()
            elif kind=="set_output":self.output_var.set(str(self.output_path_with_current_name_extra(Path(str(value)))))
            elif kind=="set_batch_operation_current":self.batch_operation_current_var.set(str(value))
            elif kind=="set_tmdb_id":self.tmdb_id_var.set(str(value))
            elif kind=="set_tmdb_search_results":self.set_tmdb_search_results(list(value))
            elif kind=="set_tmdb_search_status":self.tmdb_search_status_var.set(str(value))
            elif kind=="set_title":self.title_var.set(str(value))
            elif kind=="set_title_if_empty":
                if not self.title_var.get().strip():self.title_var.set(str(value))
            elif kind=="set_folder":self.folder_var.set(str(value));self._set_default_output()
            elif kind=="set_extract_dir":self.extract_output_dir_var.set(str(value))
            elif kind=="set_video_fps":self.video_fps_var.set(str(value))
            elif kind=="set_chapter_end_auto":
                current=self.chapter_end_var.get().strip()
                if not current or current==self.auto_chapter_end_value:self.chapter_end_var.set(str(value));self.auto_chapter_end_value=str(value)
            elif kind=="set_extract_items":self.set_extract_items(value)
            elif kind=="set_subtitle_results":self.set_subtitle_results(value)
            elif kind=="reset_subtitle_downloads":
                self.subtitle_downloaded_paths = {}
                self.remember_subtitle_session()
            elif kind=="set_subtitle_status":self.subtitle_status_var.set(str(value))
            elif kind=="mark_subtitle_downloaded":
                try:result_key,destination=value
                except (TypeError,ValueError):continue
                self.mark_subtitle_result_downloaded(str(result_key),Path(str(destination)))

    # ------------------------------------------------------------------
    # App update / platform integration
    # ------------------------------------------------------------------
    def show_app_update_available(self, release: dict[str, Any]) -> None:
        version = str(
            release.get("version") or release.get("tag_name") or release.get("name") or ""
        ).strip()
        url = str(release.get("url") or release.get("html_url") or APP_LATEST_RELEASE_URL)
        self.app_update_url = url
        if self.app_update_button is not None:
            self.app_update_button.setText(f"{self.tr('button_app_update_available')} · {version}" if version else self.tr("button_app_update_available")); self.app_update_button.show()
        if version:self.queue_log(self.tr("log_app_update_available",version=version))

    def open_app_update_release(self) -> None:
        QDesktopServices.openUrl(QUrl(self.app_update_url or APP_LATEST_RELEASE_URL))

    # Tk-only context menu hooks are intentionally unnecessary. Qt supplies
    # native undo/cut/copy/paste/select-all context menus for line edits.
    def install_text_context_menu(self) -> None: pass


def initial_extract_source_from_argv(argv: list[str]) -> Path | None:
    for value in argv[1:]:
        if not value:
            continue

        # The shipped .desktop entries use ``--extract %f``.  Support the
        # equivalent ``--extract=/path`` form too, while retaining direct file
        # arguments for the Windows context menu and existing integrations.
        if value == "--extract":
            continue
        if value.startswith("--extract="):
            value = value.partition("=")[2]
        elif value.startswith("-"):
            continue

        # Desktop environments normally expand %F to a local path, but some
        # launchers/Open-With integrations hand applications a file:// URL.
        # Accept both forms so right-click -> G-TMCE behaves identically.
        candidate = str(value).strip()
        if candidate.lower().startswith("file:"):
            local_file = QUrl(candidate).toLocalFile()
            if local_file:
                candidate = local_file
        path = Path(candidate).expanduser()
        if is_supported_extract_source_path(path):
            return path
    return None


def main(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv
    if handle_windows_context_menu_cli(argv):
        return
    # AppImage launches refresh their per-user desktop target. Package and
    # install.sh launches remove only the stale AppImage menu that would take
    # precedence over the system g-tmce service-menu entry.
    if current_appimage_path() is not None:
        install_linux_appimage_launcher()
    else:
        remove_stale_appimage_service_menu_for_system_install()
    initial_extract_source = initial_extract_source_from_argv(argv)
    qt_app = QApplication(argv)
    qt_app.setApplicationName(APP_NAME)
    qt_app.setOrganizationName("G-TMCE")
    window = MkvCreatorApp(initial_extract_source)
    window.show()
    raise SystemExit(qt_app.exec())


if __name__ == "__main__":
    main()
