import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

import mkv_creator_ui as ui
from src.gtmce import core


def save_track(folder, name, start, *, fps="", codec_delay=0):
    path = folder / name
    path.write_bytes(b"untouched raw track")
    core.extracted_track_timestamps_path(path).write_text(f"# timestamp format v2\n{start}\n{start + 32}\n")
    core.write_extracted_track_timing(folder, [core.ExtractItem(
        key=name, kind="track", item_id=0, label=name, output_name=name,
        track_type="video" if fps else "audio", source_fps=fps, codec_delay_ns=codec_delay,
    )])
    return path


@pytest.fixture
def app(monkeypatch, tmp_path, qapp):
    monkeypatch.setattr(ui, "load_saved_preferences", lambda: {"ui_language": "tr"})
    monkeypatch.setattr(ui.MkvCreatorApp, "save_preferences", lambda self: None)
    monkeypatch.setattr(ui.MkvCreatorApp, "sync_context_menu_on_startup", lambda self: None)
    monkeypatch.setattr(ui.MkvCreatorApp, "start_check_app_update", lambda self: None)
    monkeypatch.setattr(core, "third_party_tool_path", lambda tool, **kwargs: tool)
    monkeypatch.setattr(core, "detect_video_fps_from_media_path", lambda path: "25" if path.suffix == ".h264" else "")
    monkeypatch.setattr(ui, "audio_probe_defaults", lambda path: {
        "codec": "ac3", "bitrate": "192k", "sample_rate": "48000", "channel_layout": "stereo",
    })
    window = ui.MkvCreatorApp()
    window.folder_var.set(str(tmp_path))
    window.output_var.set(str(tmp_path / "output.mkv"))
    yield window
    window.close_mux_tracks_window()
    window.close_audio_adjust_window()
    window.close()
    window.deleteLater()
    qapp.processEvents()
    core.set_active_ui_language("en")


@pytest.fixture(scope="session")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


def mux_row(app, path):
    return app._mux_row_index(core.path_identity_key(path))


def test_mux_shows_original_pts_and_keeps_delay_extra_after_reorder(app, tmp_path):
    video = save_track(tmp_path, "und.25.h264", 80, fps="25")
    audio = save_track(tmp_path, "tur.ac3", 0, codec_delay=5333333)
    app.open_mux_tracks_window()
    table = app.mux_tracks_tree
    row = mux_row(app, audio)
    assert table.item(row, 6).text() == "00:00:00.000"
    assert table.item(row, 7).text() == "-80"
    assert "5.333333" in table.item(row, 6).toolTip()
    assert not table.item(row, 6).flags() & Qt.ItemIsEditable
    editor = table.cellWidget(row, 3).findChild(QLineEdit)
    assert editor.text() == ""
    editor.setText("125")
    editor.editingFinished.emit()
    app._rebuild_mux_table_from_models(core.path_identity_key(audio))
    row = mux_row(app, audio)
    assert table.cellWidget(row, 3).findChild(QLineEdit).text() == "125"
    assert table.item(row, 7).text() == "-80"
    assert table.item(mux_row(app, video), 6).text() == "00:00:00.080"
    app._mux_row_inclusion_changed(core.path_identity_key(video), False)
    assert table.item(row, 7).text() == "—"


def test_audio_adjust_shows_source_and_retains_reference_after_codec_change(app, tmp_path):
    save_track(tmp_path, "und.25.h264", 80, fps="25")
    audio = save_track(tmp_path, "tur.ac3", 0, codec_delay=5333333)
    app.open_audio_adjust_window()
    row = app.audio_adjust_rows[0]
    source_text = row["source_timing_label"].text()
    assert "00:00:00.000" in source_text and "-80" in source_text
    assert row["delta"].get() == ""
    row["delta"].set("+125")
    assert row["source_timing_label"].text() == source_text
    audio.rename(core.audio_adjust_backup_path(audio))
    output = tmp_path / "tur.eac3"
    output.write_bytes(b"edited audio")
    app.mark_audio_adjust_done(audio, output)
    assert row["source_timing_label"].text() == source_text
    assert core.read_extracted_track_timing(output) is None
    assert core.audio_adjust_source_timing(output)["first_timestamp_ms"] == Decimal(0)
    app.close_audio_adjust_window()
    app.open_audio_adjust_window()
    assert app.audio_adjust_rows[0]["source_timing_label"].text() == source_text


def test_unknown_or_stale_timing_is_never_displayed_as_zero(app, tmp_path):
    audio = save_track(tmp_path, "tur.ac3", 160)
    audio.write_bytes(b"edited media")
    assert core.read_extracted_track_timing(audio) is None
    app.open_mux_tracks_window()
    row = mux_row(app, audio)
    assert app.mux_tracks_tree.item(row, 6).text() == "—"
    assert app.mux_tracks_tree.item(row, 7).text() == "—"
    app.open_audio_adjust_window()
    label = app.audio_adjust_rows[0]["source_timing_label"]
    assert label.text().count("—") == 2
    assert "yeniden ayır" in label.toolTip()


def test_manual_tracks_and_language_switch_keep_source_fields(app, tmp_path):
    save_track(tmp_path, "und.25.h264", 80, fps="25")
    save_track(tmp_path, "tur.ac3", 0)
    app.open_mux_tracks_window()
    extra_folder = tmp_path / "extra"
    extra_folder.mkdir()
    audio = save_track(extra_folder, "eng.ac3", 120)
    app.add_mux_track_paths([audio])
    app._rebuild_mux_table_from_models()
    row = mux_row(app, audio)
    assert app.mux_tracks_tree.item(row, 6).text() == "00:00:00.120"
    assert app.mux_tracks_tree.item(row, 7).text() == "+40"
    app.open_audio_adjust_window()
    core.set_active_ui_language("en")
    app.refresh_localized_text()
    assert app.mux_tracks_tree.horizontalHeaderItem(6).text() == "Source start (PTS)"
    assert "Source PTS" in app.audio_adjust_rows[0]["source_timing_label"].text()
