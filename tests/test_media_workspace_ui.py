import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog

import mkv_creator_ui as ui
from src.gtmce import core


@pytest.fixture
def window(monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "load_saved_preferences", lambda: {"ui_language": "tr"})
    for method in ("save_preferences", "sync_context_menu_on_startup", "start_check_app_update"):
        monkeypatch.setattr(ui.MkvCreatorApp, method, lambda self: None)
    app = ui.MkvCreatorApp()
    monkeypatch.setattr(app, "show_info", lambda *args: None)
    yield app
    app.close()
    app.deleteLater()
    application.processEvents()
    core.set_active_ui_language("en")


def test_ai_source_chooser_lists_localized_subtitles(window, tmp_path, monkeypatch):
    core.ensure_media_workspace(tmp_path, "tr")
    audio = core.workspace_file_path(tmp_path, "eng.ac3")
    subtitle = core.workspace_file_path(tmp_path, "eng.srt")
    subtitle.write_text("test")
    seen = []

    def reject(dialog):
        combo = dialog.findChild(QComboBox)
        seen.extend(combo.itemData(index) for index in range(combo.count()))
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", reject)
    assert window.choose_existing_subtitle_for_ai({"path": audio, "language": "en"}) == Path("__cancel__")
    assert str(subtitle) in seen


def test_language_switch_updates_only_uncreated_default_destination(window, tmp_path):
    source = tmp_path / "Film.mkv"
    source.touch()
    window.extract_source_var.set(str(source))
    window.extract_output_dir_var.set(str(tmp_path / "Film_parçalar"))
    window.on_ui_language_selected("English")
    assert window.extract_output_dir_var.get() == str(tmp_path / "Film_tracks")
    (tmp_path / "Film_tracks").mkdir()
    window.on_ui_language_selected("Türkçe")
    assert window.extract_output_dir_var.get() == str(tmp_path / "Film_tracks")
    window.extract_output_dir_var.set(str(tmp_path / "My folder"))
    window.on_ui_language_selected("English")
    assert window.extract_output_dir_var.get() == str(tmp_path / "My folder")
