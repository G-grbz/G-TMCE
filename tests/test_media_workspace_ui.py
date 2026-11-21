import os
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QComboBox, QDialog

import mkv_creator_ui as ui
from src.gtmce import controller, core


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


@pytest.fixture
def tmdb_assets(window, tmp_path, monkeypatch):
    with BytesIO() as image:
        Image.new("RGB", (24, 36)).save(image, format="JPEG")
        poster = image.getvalue()

    class FakeTmdbClient:
        fail_request = ""

        def __init__(self, api_key):
            pass

        def get_json(self, endpoint, params):
            if self.fail_request == "details" or (
                self.fail_request == "tags" and "append_to_response" in params
            ):
                raise core.UserVisibleError("TMDB request failed")
            if endpoint.endswith("/images"):
                return {"posters": [{"file_path": "/poster.jpg", "iso_639_1": "en"}]}
            return {"title": "Film", "release_date": "2020-01-01"}

        def download_bytes(self, file_path):
            return poster

    monkeypatch.setattr(core, "TMDBClient", FakeTmdbClient)
    errors = []
    monkeypatch.setattr(window, "show_error", lambda title, message: errors.append(message))
    window.folder_var.set(str(tmp_path))
    window.output_var.set(str(tmp_path / "Film.mkv"))
    window.api_key_var.set("test-key")
    window.tmdb_id_var.set("123")
    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (12, 16), "red").save(cover, format="JPEG")
    tags = tmp_path / "tags.xml"
    tags.write_text("<Tags><Tag><Targets /></Tag></Tags>", encoding="utf-8")
    return FakeTmdbClient, cover, tags, errors


def finish_operation(window):
    window.worker.join(timeout=10)
    assert not window.worker.is_alive()
    window._drain_log_queue()


@pytest.mark.parametrize("operation", ["start_download", "start_mux"])
def test_overwrite_is_consumed_once(window, tmdb_assets, monkeypatch, operation):
    _client, cover, tags, errors = tmdb_assets
    initial = (cover.read_bytes(), tags.read_bytes())
    checkbox = window.overwrite_tmdb_assets_check
    assert checkbox.text() == "Bir kez üzerine yaz"
    assert not checkbox.isChecked()
    window.on_ui_language_selected("English")
    assert checkbox.text() == "Overwrite once"

    def stop_before_mux(*args, **kwargs):
        raise core.UserVisibleError("Mux stopped after asset preparation")

    monkeypatch.setattr(controller, "build_mkvmerge_args", stop_before_mux)
    window.download_before_mux_var.set(operation == "start_mux")
    start = getattr(window, operation)

    start()
    finish_operation(window)
    assert (cover.read_bytes(), tags.read_bytes()) == initial
    checkbox.click()
    start()
    if operation == "start_mux":
        worker = window.worker
        worker.join(timeout=10)
        assert not worker.is_alive()
        window.mux_button.click()
        assert window.worker is worker
    finish_operation(window)
    assert not checkbox.isChecked()
    assert cover.read_bytes() != initial[0]
    assert tags.read_bytes() != initial[1]

    cover.write_bytes(initial[0])
    tags.write_bytes(initial[1])
    start()
    finish_operation(window)
    assert (cover.read_bytes(), tags.read_bytes()) == initial
    assert errors == (["Mux stopped after asset preparation"] * 3 if operation == "start_mux" else [])


def test_overwrite_survives_failure_before_writes_but_is_consumed_after_first_write(window, tmdb_assets):
    client, cover, tags, errors = tmdb_assets
    initial = (cover.read_bytes(), tags.read_bytes())
    window.overwrite_tmdb_assets_check.click()
    client.fail_request = "details"
    window.start_download()
    finish_operation(window)
    assert window.overwrite_tmdb_assets_check.isChecked()
    assert (cover.read_bytes(), tags.read_bytes()) == initial

    client.fail_request = "tags"
    window.start_download()
    finish_operation(window)
    assert not window.overwrite_tmdb_assets_check.isChecked()
    assert cover.read_bytes() != initial[0]
    assert tags.read_bytes() == initial[1]
    assert errors == ["TMDB request failed"] * 2
