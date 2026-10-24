import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

import mkv_creator_ui as ui
from src.gtmce import core


@pytest.fixture
def batch(monkeypatch, tmp_path):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "load_saved_preferences", lambda: {"ui_language": "tr"})
    for method in ("save_preferences", "sync_context_menu_on_startup", "start_check_app_update"):
        monkeypatch.setattr(ui.MkvCreatorApp, method, lambda self: None)
    monkeypatch.setattr(core, "third_party_tool_path", lambda tool, **kwargs: tool)
    monkeypatch.setattr(core, "detect_video_fps_from_media_path", lambda path: "25" if path.suffix == ".h264" else "")
    app = ui.MkvCreatorApp()
    errors = []
    monkeypatch.setattr(app, "show_error", lambda title, message: errors.append(message))
    source = tmp_path / "Series S01"
    source.mkdir()
    root = tmp_path / "Series S01_parçalar"
    core.ensure_media_workspace(root, "tr", mode="batch")
    paths = []
    for number in range(1, 5):
        original = source / f"Series S01E{number:02d}.mkv"
        original.touch()
        episode = core.batch_episode_directory(root, original.stem, "tr")
        core.ensure_media_workspace(episode, "tr")
        tracks = {}
        for name in ("und.25.h264", "tur.ac3", "eng.ac3", "tur.srt"):
            track = core.workspace_file_path(episode, name)
            track.write_bytes(b"test track")
            tracks[name] = track
        paths.append(tracks)
    app.extract_source_var.set(str(source))
    app.extract_output_dir_var.set(str(root))
    app.folder_var.set(str(paths[0]["tur.ac3"].parent.parent))
    app.media_type_var.set("tv")
    app.media_type_display_var.set(app.tmdb_media_type_display("tv"))
    app.add_tracks_before_mux_var.set(True)
    app.download_before_mux_var.set(False)
    app.include_extra_subs_var.set(True)
    yield SimpleNamespace(app=app, paths=paths, source=source, root=root, errors=errors, tmp=tmp_path)
    app.close_mux_tracks_window()
    app.close()
    app.deleteLater()
    application.processEvents()
    core.set_active_ui_language("en")


def editor(app, path, column):
    index = app._mux_row_index(core.path_identity_key(path))
    return app.mux_tracks_tree.cellWidget(index, column).findChild(QLineEdit)


def test_main_mux_button_opens_lazy_episode_tabs(batch):
    app = batch.app
    app.start_mux()
    assert not batch.errors
    assert app.mux_tracks_tabs.count() == 4
    assert "S01E01" in app.mux_tracks_tabs.tabText(0)
    assert "S01E04" in app.mux_tracks_tabs.tabText(3)
    assert len(app.mux_tracks_window.findChildren(ui.MuxTracksTable)) == 1
    app.mux_tracks_tabs.setCurrentIndex(2)
    assert len(app.mux_tracks_window.findChildren(ui.MuxTracksTable)) == 2
    assert {row.path for row in app.mux_tracks_rows_by_iid.values()} == set(batch.paths[2].values())
    app.toggle_theme()
    assert not batch.errors


def test_pending_delay_added_tracks_and_order_survive_switches_and_rebuilds(batch):
    app = batch.app
    app.open_mux_tracks_window()
    extra = batch.tmp / "deu.srt"
    extra.write_text("subtitle")
    editor(app, batch.paths[0]["tur.ac3"], 3).setText("+125")
    app.add_mux_track_paths([extra])
    app._rebuild_mux_table_from_models()
    editor(app, extra, 3).setText("-250")
    editor(app, extra, 2).setText("fra")
    app._move_mux_track_row_to(app._mux_row_index(core.path_identity_key(extra)), 0)
    original_order = list(app.mux_tracks_rows_by_iid)
    app.mux_tracks_tabs.setCurrentIndex(1)
    assert core.path_identity_key(extra) not in app.mux_tracks_rows_by_iid
    app.add_mux_track_paths([extra])
    app._rebuild_mux_table_from_models()
    editor(app, extra, 3).setText("900")
    app.mux_tracks_tabs.setCurrentIndex(0)
    assert list(app.mux_tracks_rows_by_iid) == original_order
    assert editor(app, batch.paths[0]["tur.ac3"], 3).text() == "+125"
    assert editor(app, extra, 3).text() == "-250"
    assert editor(app, extra, 2).text() == "fr"
    app.mux_tracks_tabs.setCurrentIndex(1)
    assert editor(app, extra, 3).text() == "900"


def test_confirmation_keeps_episode_customizations_isolated_and_unvisited_defaults(batch, monkeypatch):
    app = batch.app
    app.start_mux()
    extra = batch.tmp / "spa.srt"
    extra.write_text("subtitle")
    app.add_mux_track_paths([extra])
    app._rebuild_mux_table_from_models()
    editor(app, extra, 3).setText("75")
    editor(app, batch.paths[0]["tur.ac3"], 3).setText("100")
    app._mux_row_inclusion_changed(core.path_identity_key(batch.paths[0]["eng.ac3"]), False)
    app.mux_tracks_tabs.setCurrentIndex(1)
    editor(app, batch.paths[1]["tur.ac3"], 3).setText("-200")
    started = []
    monkeypatch.setattr(app, "start_batch_mux_folder", lambda **kwargs: started.append(kwargs))
    app.confirm_mux_tracks_and_start_mux()
    assert started == [{"skip_track_window": True}]
    first = app.batch_mux_track_customizations_for(batch.paths[0]["tur.ac3"].parent.parent)
    second = app.batch_mux_track_customizations_for(batch.paths[1]["tur.ac3"].parent.parent)
    third = app.batch_mux_track_customizations_for(batch.paths[2]["tur.ac3"].parent.parent)
    assert first[0][0].path == extra and first[0][0].delay == "75"
    assert first[3][core.path_identity_key(batch.paths[0]["tur.ac3"])] == "100"
    assert core.path_identity_key(batch.paths[0]["eng.ac3"]) in first[5]
    assert second[0] == []
    assert second[3][core.path_identity_key(batch.paths[1]["tur.ac3"])] == "-200"
    assert third == ([], [], {}, {}, {}, set(), [], False)
    # The mux worker consumes each episode's paths and overrides independently.
    for index, choices in enumerate((first, second, third)):
        folder = batch.paths[index]["tur.ac3"].parent.parent
        config = core.create_auto_template_config(folder)
        args, _ = core.build_mkvmerge_args(
            config, folder, folder / "output.mkv", "", True,
            additional_tracks=choices[0], track_order_keys=choices[1], language_overrides=choices[2],
            delay_overrides=choices[3], append_overrides=choices[4], excluded_track_keys=choices[5],
        )
        assert str(batch.paths[index]["tur.ac3"]) in args
        assert (str(extra) in args) == (index == 0)
        assert (str(batch.paths[index]["eng.ac3"]) in args) == (index != 0)
        assert all(str(path) not in args for other in batch.paths[:index] + batch.paths[index + 1:] for path in other.values())


def test_append_source_locking_is_per_episode(batch):
    app = batch.app
    app.start_mux()
    owner = app.mux_tracks_rows_by_iid[core.path_identity_key(batch.paths[0]["tur.ac3"])]
    owner.append_paths = (batch.paths[0]["eng.ac3"],)
    owner.append_overridden = True
    app._sync_mux_append_source_rows()
    assert not app.mux_tracks_rows_by_iid[core.path_identity_key(batch.paths[0]["eng.ac3"])].included
    app.mux_tracks_tabs.setCurrentIndex(1)
    assert app.mux_tracks_rows_by_iid[core.path_identity_key(batch.paths[1]["eng.ac3"])].included
    app.mux_tracks_tabs.setCurrentIndex(0)
    app._remove_last_append_for_mux_key(owner.key)
    assert app.mux_tracks_rows_by_iid[core.path_identity_key(batch.paths[0]["eng.ac3"])].included


def test_inactive_editor_signals_cannot_change_same_external_track_in_another_episode(batch):
    app = batch.app
    app.start_mux()
    extra = batch.tmp / "deu.srt"
    extra.touch()
    app.add_mux_track_paths([extra])
    app._rebuild_mux_table_from_models()
    previous_editor = editor(app, extra, 3)
    app.mux_tracks_tabs.setCurrentIndex(1)
    app.add_mux_track_paths([extra])
    app._rebuild_mux_table_from_models()
    editor(app, extra, 3).setText("200")
    previous_editor.setText("100")
    previous_editor.editingFinished.emit()
    assert app.mux_tracks_rows_by_iid[core.path_identity_key(extra)].delay != "100"
    app.mux_tracks_tabs.setCurrentIndex(0)
    assert editor(app, extra, 3).text() == "100"
    app.mux_tracks_tabs.setCurrentIndex(1)
    assert editor(app, extra, 3).text() == "200"


def test_invalid_delay_stops_confirmation_with_episode_identification(batch, monkeypatch):
    app = batch.app
    app.start_mux()
    app.mux_tracks_tabs.setCurrentIndex(1)
    editor(app, batch.paths[1]["tur.ac3"], 3).setText("not a number")
    started = []
    monkeypatch.setattr(app, "start_batch_mux_folder", lambda **kwargs: started.append(kwargs))
    app.confirm_mux_tracks_and_start_mux()
    assert not started
    assert "S01E02" in batch.errors[-1]
    assert app.mux_tracks_window is not None


def test_same_batch_reopens_saved_episode_choices_without_single_file_leaks(batch, monkeypatch):
    app = batch.app
    app.start_mux()
    editor(app, batch.paths[0]["tur.ac3"], 3).setText("125")
    monkeypatch.setattr(app, "start_batch_mux_folder", lambda **kwargs: None)
    app.confirm_mux_tracks_and_start_mux()
    unrelated = batch.tmp / "unrelated.srt"
    unrelated.touch()
    app.additional_mux_tracks = [core.AdditionalMuxTrack(unrelated, "en", "1000")]
    app.open_mux_tracks_window()
    assert editor(app, batch.paths[0]["tur.ac3"], 3).text() == "125"
    assert core.path_identity_key(unrelated) not in app.mux_tracks_rows_by_iid
    app.mux_tracks_tabs.setCurrentIndex(1)
    assert core.path_identity_key(unrelated) not in app.mux_tracks_rows_by_iid
    assert app.additional_mux_tracks[0].path == unrelated


def test_add_file_picker_starts_in_active_episode(batch, monkeypatch):
    app = batch.app
    app.start_mux()
    app.mux_tracks_tabs.setCurrentIndex(2)
    seen = []
    monkeypatch.setattr(ui.QFileDialog, "getOpenFileNames", lambda *args: (seen.append(args[2]) or [], ""))
    app.add_mux_track_files()
    assert seen == [str(batch.paths[2]["tur.ac3"].parent.parent)]


def test_unrelated_single_track_folder_does_not_route_to_batch(batch):
    app = batch.app
    single = batch.tmp / "Movie_tracks"
    single.mkdir()
    (single / "tur.ac3").touch()
    app.folder_var.set(str(single))
    assert not app.batch_workspace_selected()
    app.open_mux_tracks_window()
    assert app.mux_tracks_tabs is None
    assert [row.path for row in app.mux_tracks_rows_by_iid.values()] == [single / "tur.ac3"]
