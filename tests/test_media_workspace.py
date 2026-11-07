import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.gtmce import core, transcription, workspace


@pytest.mark.parametrize("language,names", [
    ("en", "metadata"),
    ("tr", "üstveri"),
])
def test_new_workspace_is_flat_and_language_switch_does_not_rename(tmp_path, monkeypatch, language, names):
    root = tmp_path / "Film_tracks"
    core.prepare_extraction_workspace(root, language)
    assert core.workspace_layout(root)["version"] == 2
    for kind in ("video", "audio", "subtitle", "artwork"):
        assert core.workspace_directory(root, kind) == root
    assert core.workspace_directory(root, "metadata") == root / names
    assert {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")} == {names}
    monkeypatch.setattr(core, "ACTIVE_UI_LANGUAGE", "en" if language == "tr" else "tr")
    core.prepare_extraction_workspace(root)
    assert core.workspace_layout(root)["language"] == language
    assert core.workspace_directory(root, "audio") == root


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


def test_templates_resolve_tracks_artwork_and_metadata_in_flat_layout(tmp_path, monkeypatch):
    core.ensure_media_workspace(tmp_path, "tr")
    audio = core.workspace_file_path(tmp_path, "tur.ac3")
    audio.write_bytes(b"audio")
    cover = core.workspace_file_path(tmp_path, "cover.jpg", "artwork")
    cover.write_bytes(b"cover")
    tags = core.workspace_file_path(tmp_path, "tags.xml", "metadata")
    tags.write_text("<Tags />")
    chapters = core.workspace_file_path(tmp_path, "chapters.txt", "metadata")
    chapters.write_text("CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 1\n")
    assert all(p.parent == tmp_path for p in (audio, cover, tags, chapters))
    assert core.workspace_file_path(tmp_path, "metadata.txt", "metadata").parent == tmp_path / "üstveri"
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


def test_subtitles_created_from_audio_or_translation_use_workspace_root(tmp_path):
    core.ensure_media_workspace(tmp_path, "tr")
    audio = core.workspace_file_path(tmp_path, "eng.ac3")
    assert transcription.generated_subtitle_path(audio, "en") == tmp_path / "eng.generated.srt"
    assert transcription.generated_translation_path(audio, "tr") == tmp_path / "eng.tr.generated.srt"


def test_timing_and_audio_restore_keep_working_with_hidden_sidecars(tmp_path):
    core.ensure_media_workspace(tmp_path, "tr")
    audio = core.workspace_file_path(tmp_path, "tur.ac3")
    original = b"original audio"
    audio.write_bytes(original)
    timestamps = core.extracted_track_timestamps_path(audio)
    timestamps.parent.mkdir(parents=True, exist_ok=True)
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



@pytest.mark.parametrize("language,backup_folder", [("tr", "yedekler"), ("en", "backups")])
@pytest.mark.parametrize("delay_seconds", [0, 3])
def test_codec_change_keeps_original_and_delay_source_outside_editable_root(
    tmp_path, monkeypatch, language, backup_folder, delay_seconds,
):
    # A changed audio format must only expose the editable replacement at the
    # workspace root; the pristine source and temporary mux append are backups.
    root = tmp_path / "Show.S01E01_parçalar"
    core.prepare_extraction_workspace(root, language)
    original = root / "tur.ac3"
    original.write_bytes(b"original AC3")
    commands = []

    def fake_ffmpeg(args, _log, **_kwargs):
        commands.append(args)
        Path(args[-1]).write_bytes(b"new AAC")

    monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(core, "run_cancellable_logged_process", fake_ffmpeg)

    task = core.AudioAdjustTask(
        path=original, delta_seconds=delay_seconds, codec="aac",
        bitrate="128k", sample_rate="48000", channel_layout="stereo",
        original_codec="ac3", original_bitrate="192k",
        original_sample_rate="48000", original_channel_layout="stereo",
    )
    converted = core.run_audio_adjust_task(task, lambda _line: None)
    backups = root / ".gtmce" / backup_folder / ("ses" if language == "tr" else "audio")
    retained = backups / "tur.source.ac3"

    assert converted == root / "tur.aac"
    assert retained.read_bytes() == b"original AC3"
    assert not original.exists()
    assert {p.name for p in root.iterdir() if p.is_file()} == {"tur.aac"}
    assert core.discover_media_track_paths(root) == [converted]
    assert core.find_audio_adjust_source_backup(converted) == retained
    assert len(commands) == (2 if delay_seconds else 1)
    if delay_seconds:
        append = backups / "tur.delay-source.aac"
        assert append.is_file()
        assert core.read_audio_adjust_delay_append_path(converted) == append
    else:
        append = None
        assert core.read_audio_adjust_delay_append_path(converted) is None

    restored = core.restore_audio_adjust_original(converted)
    assert restored == original
    assert restored.read_bytes() == b"original AC3"
    assert not converted.exists() and not retained.exists()
    if append is not None:
        assert not append.exists()
    assert core.discover_media_track_paths(root) == [original]


def test_batch_episode_audio_conversion_keeps_separate_original_backups(tmp_path, monkeypatch):
    root = tmp_path / "Series_parçalar"
    core.prepare_extraction_workspace(root, "tr", mode="batch")
    monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        core, "run_cancellable_logged_process",
        lambda args, _log, **_kwargs: Path(args[-1]).write_bytes(b"converted"),
    )
    for episode in (1, 2):
        folder = core.batch_episode_directory(root, f"Series.S01E{episode:02}", "tr", for_new=True)
        core.prepare_extraction_workspace(folder, "tr")
        source = folder / "tur.ac3"
        source.write_bytes(f"episode {episode}".encode())
        converted = core.run_audio_adjust_task(
            core.AudioAdjustTask(
                path=source, delta_seconds=0, codec="aac", bitrate="128k",
                sample_rate="48000", channel_layout="stereo", original_codec="ac3",
                original_bitrate="192k", original_sample_rate="48000",
                original_channel_layout="stereo",
            ),
            lambda _line: None,
        )
        assert converted == folder / "tur.aac"
        assert (folder / ".gtmce" / "yedekler" / "ses" / "tur.source.ac3").read_bytes() == f"episode {episode}".encode()
        assert {p.name for p in folder.iterdir() if p.is_file()} == {"tur.aac"}

def test_new_batch_paths_match_the_saved_language(tmp_path, monkeypatch):
    root = tmp_path / "Series_parçalar"
    planned = core.batch_episode_directory(root, "Series S01E01", "tr", for_new=True)
    core.prepare_extraction_workspace(root, "tr", mode="batch")
    assert planned == root / "bölümler" / "Series S01E01_parçalar"
    core.prepare_extraction_workspace(planned, "tr")
    assert core.workspace_layout(root)["version"] == 2
    assert core.workspace_file_path(planned, "tur.ac3") == planned / "tur.ac3"
    assert core.workspace_file_path(planned, "tags.xml", "metadata") == planned / "tags.xml"
    assert core.workspace_file_path(planned, "metadata.txt", "metadata") == planned / "üstveri" / "metadata.txt"
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


def test_legacy_v1_workspace_remains_readable_and_is_not_migrated(tmp_path):
    root = tmp_path / "legacy"
    core.ensure_media_workspace(root, "tr")
    manifest = workspace.layout_path(root)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["version"] = 1
    manifest.write_text(json.dumps(data), encoding="utf-8")
    core.ensure_media_workspace(root, "en")
    assert core.workspace_layout(root)["version"] == 1
    audio = root / "ses" / "tur.ac3"
    audio.write_bytes(b"original")
    assert core.discover_media_track_paths(root) == [audio]
    assert core.workspace_file_path(root, "tags.xml", "metadata") == root / "üstveri" / "tags.xml"
    assert core.workspace_file_path(root, "cover.jpg", "artwork") == root / "görseller" / "cover.jpg"


def test_flat_extract_paths_and_attachment_manifest_do_not_attach_tracks(tmp_path):
    root = tmp_path / "Film_parçalar"
    core.prepare_extraction_workspace(root, "tr")
    definitions = [
        ("track", "video", "und.23.976.h265", root),
        ("track", "audio", "tur.ac3", root),
        ("track", "subtitles", "eng.srt", root),
        ("attachment", "", "cover.jpg", root),
        ("attachment", "", "font.ttf", root / "üstveri"),
        ("attachment", "", "readme.txt", root / "üstveri"),
        ("chapters", "", "chapters.txt", root),
        ("tags", "", "tags.xml", root),
    ]
    items = []
    for index, (kind, track_type, name, expected_parent) in enumerate(definitions, 1):
        item = core.ExtractItem(f"{kind}:{index}", kind, index, name, name, track_type=track_type)
        path = core.extracted_item_output_path(root, item)
        assert path.parent == expected_parent
        path.write_bytes(b"asset")
        items.append(item)
    technical = root / "üstveri" / "metadata.txt"
    technical.write_text("Technical metadata", encoding="utf-8")
    core.record_extracted_attachments(root, items)
    assert [p.name for p in core.discover_media_track_paths(root)] == [
        "eng.srt", "tur.ac3", "und.23.976.h265",
    ]
    attachments = {p.name for p in core.discover_auto_attachment_paths(root)}
    assert attachments == {"cover.jpg", "font.ttf", "readme.txt"}
    assert "metadata.txt" not in attachments
    assert "tags.xml" not in attachments
    assert "chapters.txt" not in attachments
    assert core.workspace_output_directory(root) == root


def test_flat_batch_episode_extract_commands_use_distinct_roots(tmp_path, monkeypatch):
    root = tmp_path / "Show_parçalar"
    core.prepare_extraction_workspace(root, "tr", mode="batch")
    monkeypatch.setattr(core, "third_party_tool_path", lambda tool, **kwargs: "/usr/bin/mkvextract")
    episodes = []
    for episode in (1, 2):
        folder = core.batch_episode_directory(root, f"Show.S01E{episode:02}", for_new=True)
        core.prepare_extraction_workspace(folder, "tr")
        items = [
            core.ExtractItem("track:0", "track", 0, "video", "und.25.h264", track_type="video"),
            core.ExtractItem("track:1", "track", 1, "audio", "eng.ac3", track_type="audio"),
            core.ExtractItem("tags", "tags", None, "tags", "tags.xml"),
        ]
        args = core.build_mkvextract_args(tmp_path / f"Show.S01E{episode:02}.mkv", folder, items)
        assert str(folder / "und.25.h264") in " ".join(args)
        assert str(folder / "eng.ac3") in " ".join(args)
        assert str(folder / "tags.xml") in args
        assert core.workspace_output_directory(folder) == root / "çıktı"
        episodes.append(folder)
    assert core.discover_episode_workspace_dirs(root) == episodes


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
    assert sorted(path.name for path in folder.iterdir() if path.is_file()) == sorted(
        ["Film.mkv", *(item.output_name for item in items if item.selected and
                       core.extracted_item_output_path(folder, item).parent == folder)]
    )


@pytest.mark.parametrize("key", ["language", "mode"])
def test_unhashable_layout_fields_are_reported_cleanly(tmp_path, key):
    core.ensure_media_workspace(tmp_path, "en")
    data = json.loads(workspace.layout_path(tmp_path).read_text())
    data[key] = []
    workspace.layout_path(tmp_path).write_text(json.dumps(data))
    with pytest.raises(core.UserVisibleError):
        core.workspace_layout(tmp_path)
