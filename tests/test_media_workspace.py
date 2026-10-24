import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.gtmce import core, transcription, workspace


@pytest.mark.parametrize("language,names", [
    ("en", ("audio", "subtitles", "artwork", "metadata")),
    ("tr", ("ses", "altyazılar", "görseller", "üstveri")),
])
def test_new_workspace_is_localized_and_language_switch_does_not_rename(tmp_path, monkeypatch, language, names):
    root = tmp_path / "Film_tracks"
    core.prepare_extraction_workspace(root, language)
    for kind, name in zip(("audio", "subtitle", "artwork", "metadata"), names):
        assert core.workspace_directory(root, kind).name == name
        assert (root / name).is_dir()
    monkeypatch.setattr(core, "ACTIVE_UI_LANGUAGE", "en" if language == "tr" else "tr")
    core.prepare_extraction_workspace(root)
    assert core.workspace_layout(root)["language"] == language
    assert core.workspace_directory(root, "audio").name == names[0]


def test_flat_existing_workspace_is_not_automatically_moved(tmp_path):
    (tmp_path / "tur.ac3").write_bytes(b"audio")
    core.prepare_extraction_workspace(tmp_path, "tr")
    assert core.workspace_layout(tmp_path) is None
    assert core.discover_media_track_paths(tmp_path) == [tmp_path / "tur.ac3"]


@pytest.mark.parametrize("language", ["en", "tr"])
def test_final_mkv_is_not_a_track_and_numbered_audio_appends_still_work(tmp_path, language):
    core.ensure_media_workspace(tmp_path, language)
    audio = core.workspace_directory(tmp_path, "audio")
    for name in ("tur.ac3", "tur.1.ac3", "tur.2.ac3"):
        (audio / name).write_bytes(b"audio")
    (tmp_path / "Film.mkv").write_bytes(b"finished")
    roots, appended, names = core.discover_media_track_paths_with_appends(tmp_path)
    assert roots == [audio / "tur.ac3"]
    assert appended["tur.ac3"] == (audio / "tur.1.ac3", audio / "tur.2.ac3")
    assert names == {"tur.1.ac3", "tur.2.ac3"}


def test_templates_resolve_tracks_artwork_and_metadata_in_localized_folders(tmp_path, monkeypatch):
    core.ensure_media_workspace(tmp_path, "tr")
    audio = core.workspace_file_path(tmp_path, "tur.ac3")
    audio.write_bytes(b"audio")
    cover = core.workspace_file_path(tmp_path, "cover.jpg", "artwork")
    cover.write_bytes(b"cover")
    tags = core.workspace_file_path(tmp_path, "tags.xml", "metadata")
    tags.write_text("<Tags />")
    chapters = core.workspace_file_path(tmp_path, "chapters.txt", "metadata")
    chapters.write_text("CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 1\n")
    config = core.base_template_config()
    entry, _ = core.make_minimal_track_entry(audio, 1)
    entry["fileName"] = "/old/computer/tur.ac3"
    config["input"]["files"] = {"0": entry, "numberOfEntries": 1}
    items, _, missing = core.discover_track_items(config, tmp_path, True)
    assert missing == [] and [item.path for item in items] == [audio]
    assert core.resolve_global_tags_path(config, tmp_path)[0] == tags
    assert core.resolve_chapter_path(config, tmp_path, items, None)[0] == chapters
    assert cover in core.discover_auto_attachment_paths(tmp_path)
    output = tmp_path / "Film.mkv"
    generated = core.write_generated_config(config, tmp_path, output, "Film", True)
    assert generated == tmp_path / ".gtmce" / "Film.generated.mtxcfg"


def test_subtitles_created_from_audio_or_translation_use_subtitle_folder(tmp_path):
    core.ensure_media_workspace(tmp_path, "tr")
    audio = core.workspace_file_path(tmp_path, "eng.ac3")
    assert transcription.generated_subtitle_path(audio, "en") == tmp_path / "altyazılar" / "eng.generated.srt"
    assert transcription.generated_translation_path(audio, "tr") == tmp_path / "altyazılar" / "eng.tr.generated.srt"


def test_timing_and_audio_restore_keep_working_with_hidden_sidecars(tmp_path):
    core.ensure_media_workspace(tmp_path, "tr")
    audio = core.workspace_file_path(tmp_path, "tur.ac3")
    original = b"original audio"
    audio.write_bytes(original)
    timestamps = core.extracted_track_timestamps_path(audio)
    timestamps.parent.mkdir(parents=True)
    timestamps.write_text("# timestamp format v2\n100.000\n120.000\n")
    item = core.ExtractItem("track:1", "track", 1, "audio", "tur.ac3", track_type="audio")
    core.write_extracted_track_timing(tmp_path, [item])
    assert core.read_extracted_track_timing(audio)["first_timestamp_ms"] == 100
    backup, created = core.prepare_audio_adjust_source(audio)
    assert created and backup == tmp_path / ".gtmce" / "yedekler" / "ses" / "tur.source.ac3"
    audio.write_bytes(b"silence")
    core.write_audio_adjust_delay_manifest(audio, backup, 9)
    assert core.read_audio_adjust_delay_append_path(audio) == backup
    assert core.audio_adjust_source_timing(audio)["first_timestamp_ms"] == 100
    assert core.discover_media_track_paths(tmp_path) == [audio]
    assert core.restore_audio_adjust_original(audio) == audio
    assert audio.read_bytes() == original
    assert core.read_audio_adjust_delay_append_path(audio) is None


def test_new_batch_paths_match_the_saved_language(tmp_path, monkeypatch):
    root = tmp_path / "Series_parçalar"
    planned = core.batch_episode_directory(root, "Series S01E01", "tr", for_new=True)
    core.prepare_extraction_workspace(root, "tr", mode="batch")
    assert planned == root / "bölümler" / "Series S01E01_parçalar"
    core.prepare_extraction_workspace(planned, "tr")
    monkeypatch.setattr(core, "ACTIVE_UI_LANGUAGE", "en")
    assert core.batch_episode_directory(root, "Series S01E01") == planned
    assert core.discover_episode_workspace_dirs(root) == [planned]
    assert core.workspace_output_directory(planned) == root / "çıktı"


@pytest.mark.parametrize("bad", ["../outside", "/outside"])
def test_corrupted_or_escaping_layout_is_rejected(tmp_path, bad):
    core.ensure_media_workspace(tmp_path, "en")
    data = json.loads(workspace.layout_path(tmp_path).read_text())
    data["folders"]["audio"] = bad
    workspace.layout_path(tmp_path).write_text(json.dumps(data))
    with pytest.raises(core.UserVisibleError):
        core.discover_media_track_paths(tmp_path)


def test_symlinked_destination_cannot_write_outside_workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "audio").symlink_to(outside, target_is_directory=True)
    with pytest.raises(core.UserVisibleError):
        core.ensure_media_workspace(root, "en")
    assert not list(outside.iterdir())


@pytest.mark.parametrize("language", ["en", "tr"])
@pytest.mark.skipif(any(shutil.which(tool) is None for tool in ("ffmpeg", "mkvmerge", "mkvextract")),
                    reason="Media tools not installed")
def test_real_localized_extract_and_mux(tmp_path, monkeypatch, language):
    monkeypatch.setattr(core, "third_party_tool_path", lambda tool, **kwargs: shutil.which(tool))
    monkeypatch.setattr(core, "detect_video_fps_from_media_path", lambda path: "25" if path.suffix == ".h264" else "")

    def run(args):
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    subtitle = tmp_path / "eng.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:00,800\nA test subtitle.\n", encoding="utf-8")
    source = tmp_path / "source.mkv"
    run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=size=160x90:rate=25:duration=1",
         "-f", "lavfi", "-i", "sine=sample_rate=48000:duration=1", "-i", str(subtitle),
         "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "ac3", "-b:a", "192k", "-c:s", "srt", "-metadata:s:a:0", "language=tur",
         "-metadata:s:s:0", "language=eng", str(source)])
    chapters = tmp_path / "chapters.txt"
    chapters.write_text("CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 1\n", encoding="utf-8")
    tags = tmp_path / "tags.xml"
    tags.write_text("<Tags><Tag><Targets/><Simple><Name>TITLE</Name><String>Film</String></Simple></Tag></Tags>", encoding="utf-8")
    decorated = tmp_path / "decorated.mkv"
    logo = Path(__file__).resolve().parents[1] / "assets" / "logo.png"
    run(["mkvmerge", "--output", str(decorated), "--chapters", str(chapters), "--global-tags", str(tags),
         "--attachment-mime-type", "image/png", "--attachment-name", "logo.png", "--attach-file", str(logo), str(source)])
    source = decorated
    folder = tmp_path / ("Film" + core.extraction_folder_suffix(language))
    core.prepare_extraction_workspace(folder, language)
    items = core.build_extract_items(core.identify_mkv(source), source)
    run(core.build_mkvextract_args(source, folder, items))
    core.write_extracted_track_timing(folder, items)
    for item in items:
        if not item.selected:
            continue
        path = core.extracted_item_output_path(folder, item)
        assert path.is_file()
        if item.track_type in {"video", "audio"}:
            assert core.read_extracted_track_timing(path) is not None
            assert core.extracted_track_timestamps_path(path).is_relative_to(folder / ".gtmce")
    config = core.create_auto_template_config(folder)
    output = core.workspace_output_directory(folder) / "Film.mkv"
    args, _ = core.build_mkvmerge_args(config, folder, output, "Film", True, video_fps="25")
    run(args)
    core.write_generated_config(config, folder, output, "Film", True)
    rebuilt = core.identify_mkv(output)
    assert sorted(track["type"] for track in rebuilt["tracks"]) == ["audio", "subtitles", "video"]
    assert rebuilt["chapters"] and rebuilt["global_tags"]
    assert any(attachment["file_name"] == "logo.png" for attachment in rebuilt["attachments"])
    assert output not in core.discover_media_track_paths(folder)
    assert sorted(path.name for path in folder.iterdir() if path.is_file()) == ["Film.mkv"]


@pytest.mark.parametrize("key", ["language", "mode"])
def test_unhashable_layout_fields_are_reported_cleanly(tmp_path, key):
    core.ensure_media_workspace(tmp_path, "en")
    data = json.loads(workspace.layout_path(tmp_path).read_text())
    data[key] = []
    workspace.layout_path(tmp_path).write_text(json.dumps(data))
    with pytest.raises(core.UserVisibleError):
        core.workspace_layout(tmp_path)
