"""Regression coverage for container-signature routing and extraction presets."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.gtmce import core


def fake_item(track_id: int, track_type: str, language: str) -> core.ExtractItem:
    return core.ExtractItem(
        key=f"track:{track_id}", kind="track", item_id=track_id,
        label=f"{track_type} {language}", output_name=f"{language}.raw",
        track_type=track_type, language=language,
    )


def test_content_magic_overrides_filename_extension(tmp_path):
    named_mkv = tmp_path / "actually_mp4.mkv"
    named_mkv.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20)
    assert core.detect_extract_container(named_mkv) == "mp4"
    assert not core.source_uses_mkvextract(named_mkv)
    assert core.extract_container_mismatch(named_mkv) == "MP4/MOV"

    named_mp4 = tmp_path / "actually_mkv.mp4"
    named_mp4.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 20)
    assert core.detect_extract_container(named_mp4) == "matroska"
    assert core.source_uses_mkvextract(named_mp4)
    assert core.extract_container_mismatch(named_mp4) == "Matroska/WebM"

    damaged_mkv = tmp_path / "damaged.mkv"
    damaged_mkv.write_bytes(b"random content")
    assert not core.source_uses_mkvextract(damaged_mkv)


def test_filtered_audio_and_subtitles_keep_video_metadata_and_und_manual():
    items = [
        fake_item(0, "video", "und"),
        fake_item(1, "audio", "tur"),
        fake_item(2, "audio", "eng"),
        fake_item(3, "audio", "und"),
        fake_item(4, "subtitles", "eng"),
        fake_item(5, "subtitles", "und"),
        core.ExtractItem(key="tags", kind="tags", item_id=None, label="tags", output_name="tags.xml"),
    ]
    core.apply_extract_language_selection(items, "tr", "en", audio_only=True, subtitle_only=True)
    assert [item.selected for item in items] == [True, True, False, False, True, False, True]
    # The `und` row is still editable/selectable by hand.
    items[3].selected = True
    assert items[3].selected

    core.apply_extract_language_selection(items, "tr, und", "", audio_only=True)
    assert items[3].selected
    assert items[4].selected  # No subtitle filtering when checkbox is off.


def test_enabled_filter_with_empty_priority_selects_none_of_its_type():
    items = [fake_item(0, "video", "und"), fake_item(1, "audio", "eng"), fake_item(2, "subtitles", "und")]
    core.apply_extract_language_selection(items, "", "tr", audio_only=True)
    assert [item.selected for item in items] == [True, False, True]


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="FFmpeg tools unavailable")
def test_renamed_mp4_tracks_use_real_ffprobe_stream_indexes(tmp_path, monkeypatch):
    mp4 = tmp_path / "sample.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=black:s=32x32:r=25", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000", "-t", "0.25",
        "-c:v", "mpeg4", "-c:a", "aac", "-y", str(mp4),
    ], check=True)
    renamed = tmp_path / "sample.mkv"
    mp4.rename(renamed)

    # mkvmerge's IDs are deliberately wrong to assert ffprobe index precedence.
    monkeypatch.setattr(core, "identify_mkv", lambda path: {
        "container": {"recognized": True, "properties": {}},
        "tracks": [{"id": 100, "type": "video", "codec": "mpeg4"}],
    })
    monkeypatch.setattr(core, "ffprobe_path", lambda auto_install=False: shutil.which("ffprobe"))
    monkeypatch.setattr(core, "ffmpeg_path", lambda: shutil.which("ffmpeg"))
    payload = core.identify_extract_source(renamed)
    assert [track["id"] for track in payload["tracks"]] == [0, 1]
    items = core.build_extract_items(payload, renamed)
    assert [item.track_type for item in items] == ["video", "audio"]
    args, command_key, _ = core.build_extract_command(renamed, tmp_path / "tracks", items)
    assert "mkvextract" not in str(args[0]).lower()
    assert command_key == "log_ffmpeg_extract_command"
    assert "0:0" in args and "0:1" in args
    # This must truly extract, not just build plausible command-line strings.
    subprocess.run(args, check=True, capture_output=True, text=True)
    assert any((tmp_path / "tracks").rglob("*.mkv"))
    assert any((tmp_path / "tracks").rglob("*.aac"))
