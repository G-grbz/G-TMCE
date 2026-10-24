import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gtmce import core
from src.gtmce.controller import GTMCEControllerMixin


@pytest.fixture
def mux_tools(monkeypatch):
    monkeypatch.setattr(core, "third_party_tool_path", lambda tool, **kwargs: tool)
    monkeypatch.setattr(core, "detect_video_fps_from_media_path", lambda path: "25" if path.suffix == ".h264" else "")


def saved_track(folder, name="tur.ac3", *, delay=0, fps=""):
    path = folder / name
    path.write_bytes(b"untouched raw media")
    core.extracted_track_timestamps_path(path).write_text("# timestamp format v2\n0\n32\n64\n")
    item = core.ExtractItem(
        key="track:0", kind="track", item_id=0, label="track", output_name=name,
        track_type="video" if fps else "audio", codec_delay_ns=delay, source_fps=fps,
    )
    core.write_extracted_track_timing(folder, [item])
    return path


def test_extract_saves_timestamps_for_selected_audio_video_only(tmp_path, mux_tools):
    payload = {"tracks": [
        {"id": 0, "type": "video", "codec": "H.264", "properties": {"default_duration": 40000000}},
        {"id": 1, "type": "audio", "codec": "AC-3", "properties": {"language": "tur", "codec_id": "A_AC3", "codec_delay": 5333333}},
        {"id": 2, "type": "subtitles", "codec": "SubRip", "properties": {"language": "tur"}},
        {"id": 3, "type": "audio", "codec": "AC-3", "properties": {"language": "tur", "codec_id": "A_AC3"}},
    ]}
    items = core.build_extract_items(payload)
    items[1].language_override = "en"
    items[3].selected = False
    core.rebuild_extract_output_names(items)
    args = core.build_mkvextract_args(tmp_path / "source.mkv", tmp_path, items)
    timing_args = args[args.index("timestamps_v2") + 1:]
    assert timing_args == [
        f"0:{tmp_path / 'und.25.h264.timestamps.txt'}",
        f"1:{tmp_path / 'en.ac3.timestamps.txt'}",
    ]
    assert items[1].codec_delay_ns == 5333333
    assert items[0].source_fps == "25"


def test_auto_fps_keeps_source_timing_and_user_delay_is_added(tmp_path, mux_tools):
    video = saved_track(tmp_path, "und.25.h264", fps="25")
    audio = saved_track(tmp_path, delay=5333333)
    config = core.create_auto_template_config(tmp_path)
    args, _ = core.build_mkvmerge_args(
        config, tmp_path, tmp_path / "out.mkv", "", False, video_fps="25.0",
        delay_overrides={core.path_identity_key(audio): "100"},
    )
    assert "--disable-lacing" in args
    assert "--default-duration" not in args
    items, _ = core.prepare_mux_track_items(config, tmp_path, False, delay_overrides={core.path_identity_key(audio): "100"})
    maps = {item.path.name: Path(item.track["timestamps"]).read_text().splitlines() for item in items}
    assert maps[video.name][1:] == ["5", "37", "69"]
    assert maps[audio.name][1:] == ["100", "132", "164"]
    assert "--sync" not in args  # Adjustments are already in the timestamp files.


def test_explicit_different_fps_retains_manual_override(tmp_path, mux_tools):
    saved_track(tmp_path, "und.25.h264", fps="25")
    config = core.create_auto_template_config(tmp_path)
    args, _ = core.build_mkvmerge_args(config, tmp_path, tmp_path / "out.mkv", "", False, video_fps="24")
    assert "--timestamps" not in args
    assert args[args.index("--default-duration") + 1] == "0:24fps"


@pytest.mark.parametrize("change", ["media", "timestamps", "manifest", "append"])
def test_modified_tracks_and_appends_do_not_reuse_stale_timing(tmp_path, mux_tools, change):
    path = saved_track(tmp_path)
    config = core.create_auto_template_config(tmp_path)
    if change == "media":
        path.write_bytes(b"re-encoded media with different frames")
    elif change == "timestamps":
        core.extracted_track_timestamps_path(path).write_text("# timestamp format v2\n1000\n1032\n")
    elif change == "manifest":
        core.extracted_track_timing_manifest_path(path).write_text("[]")
    else:
        (tmp_path / "tur.1.ac3").write_bytes(b"appended track")
    args, _ = core.build_mkvmerge_args(config, tmp_path, tmp_path / "out.mkv", "", False)
    assert "--timestamps" not in args


def test_generated_template_keeps_timing_without_double_codec_delay(tmp_path, mux_tools):
    saved_track(tmp_path, "und.25.h264", fps="25")
    audio = saved_track(tmp_path, delay=5333333)
    config = core.create_auto_template_config(tmp_path)
    generated = core.write_generated_config(config, tmp_path, tmp_path / "out.mkv", "", False)
    loaded = core.load_template_config(generated)
    entry = next(entry for _, entry in core.numbered_entries(loaded["input"]["files"]) if Path(entry["fileName"]).name == audio.name)
    track = entry["tracks"]["0"]
    assert track["timestamps"] == str(core.extracted_track_timestamps_path(audio))
    assert not track.get("delay")
    args, _ = core.build_mkvmerge_args(loaded, tmp_path, tmp_path / "again.mkv", "", False)
    assert "--sync" not in args
    video_item = next(item for item in core.prepare_mux_track_items(loaded, tmp_path, False)[0] if item.path.suffix == ".h264")
    assert Path(video_item.track["timestamps"]).read_text().splitlines()[1] == "5"
    audio.write_bytes(b"edited media")
    args, _ = core.build_mkvmerge_args(loaded, tmp_path, tmp_path / "again.mkv", "", False)
    assert args.count("--timestamps") == 1  # Only the untouched video.
    assert "--sync" not in args


def test_legacy_track_folder_still_uses_detected_fps(tmp_path, mux_tools):
    (tmp_path / "und.25.h264").write_bytes(b"legacy raw video")
    config = core.create_auto_template_config(tmp_path)
    args, _ = core.build_mkvmerge_args(config, tmp_path, tmp_path / "out.mkv", "", False)
    assert "--timestamps" not in args
    assert "0:25fps" in args


def test_preview_displays_user_delay_without_adding_origin_bias_again(tmp_path, mux_tools):
    saved_track(tmp_path, "eng.aac", delay=21000000)
    saved_track(tmp_path, "tur.ac3", delay=5333333)
    (tmp_path / "tur.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    controller = GTMCEControllerMixin()
    controller.additional_mux_tracks = []
    controller.additional_mux_assets = []
    controller.mux_track_language_overrides = {}
    controller.mux_track_delay_overrides = {}
    controller.mux_track_append_overrides = {}
    controller.mux_track_order_keys = []
    controller.mux_track_excluded_keys = set()
    settings = SimpleNamespace(template_path=None, media_dir=tmp_path, include_extra_subtitles=True,
        tag_language="en", video_fps="", audio_language_order="", subtitle_language_order="")
    rows = controller.mux_track_window_rows(settings)
    assert all(row.delay == "" for row in rows)
    # Confirming the preview supplies all visible delays as overrides. Repeated
    # previews must not accumulate the hidden correction on AC-3/subtitles.
    controller.mux_track_delay_overrides = {row.key: row.delay for row in rows if row.delay_supported}
    assert all(row.delay == "" for row in controller.mux_track_window_rows(settings))


def test_user_stretch_is_applied_to_the_source_timestamp_map(tmp_path, mux_tools):
    saved_track(tmp_path)
    config = core.create_auto_template_config(tmp_path)
    config["input"]["files"]["0"]["tracks"]["0"]["stretchBy"] = "3/2"
    items, _ = core.prepare_mux_track_items(config, tmp_path, False)
    assert Path(items[0].track["timestamps"]).read_text().splitlines()[1:] == ["0.0", "48.0", "96.0"]


def test_explicit_template_timestamp_file_is_not_replaced(tmp_path, mux_tools):
    saved_track(tmp_path, "eng.aac", delay=21000000)
    audio = saved_track(tmp_path, delay=5333333)
    custom = tmp_path / "manual.timestamps.txt"
    custom.write_text("# timestamp format v2\n100\n132\n164\n")
    config = core.create_auto_template_config(tmp_path)
    entry = next(entry for _, entry in core.numbered_entries(config["input"]["files"]) if Path(entry["fileName"]).name == audio.name)
    entry["tracks"]["0"]["timestamps"] = str(custom)
    entry["tracks"]["0"]["delay"] = "15"
    items, _ = core.prepare_mux_track_items(config, tmp_path, False)
    track = next(item.track for item in items if item.path == audio)
    assert track["timestamps"] == str(custom)
    assert track["delay"] == "15"
    assert "gtmceSourceTiming" not in track


def run(*args):
    proc = subprocess.run([str(arg) for arg in args], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def probe_packets(path):
    return json.loads(run(
        "ffprobe", "-v", "error", "-show_packets", "-show_data_hash", "sha256",
        "-show_entries", "packet=stream_index,pts_time,data_hash", "-of", "json", path,
    ))["packets"]


@pytest.mark.skipif(any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "mkvmerge", "mkvextract")), reason="Media tools not installed")
def test_real_extract_mux_preserves_gaps_duplicate_timestamps_and_av_offset(tmp_path, mux_tools):
    seed = tmp_path / "seed.mkv"
    run("ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "ac3", "-b:a", "192k", seed)
    packets = probe_packets(seed)
    video_count = sum(p["stream_index"] == 0 for p in packets)
    audio_count = sum(p["stream_index"] == 1 for p in packets)
    video_times = tmp_path / "video.txt"
    audio_times = tmp_path / "audio.txt"
    video_times.write_text("# timestamp format v2\n" + "\n".join(str(80 + 40*i + (160 if i >= 20 else 0) + (120 if i >= 50 else 0)) for i in range(video_count + 1)))
    audio_times.write_text("# timestamp format v2\n" + "\n".join(str(32*i - 32*(i//10)) for i in range(audio_count + 1)))
    source = tmp_path / "source.mkv"
    run("mkvmerge", "--output", source, "--disable-lacing", "--timestamps", f"0:{video_times}", "--timestamps", f"1:{audio_times}", seed)
    payload = json.loads(run("mkvmerge", "-J", source))
    items = core.build_extract_items(payload, source)
    folder = tmp_path / "source_tracks"
    run(*core.build_mkvextract_args(source, folder, items))
    core.write_extracted_track_timing(folder, items)
    config = core.create_auto_template_config(folder)
    output = tmp_path / "rebuilt.mkv"
    args, _ = core.build_mkvmerge_args(config, folder, output, "", False, video_fps="25")
    run(*args)
    original, rebuilt = probe_packets(source), probe_packets(output)
    # Track order may change on muxing; compare each track independently.
    original_video = [p for p in original if p["stream_index"] == 0]
    original_audio = [p for p in original if p["stream_index"] == 1]
    rebuilt_video = [p for p in rebuilt if p["stream_index"] == 0]
    rebuilt_audio = [p for p in rebuilt if p["stream_index"] == 1]
    assert len(original_video) == len(rebuilt_video)
    assert len(original_audio) == len(rebuilt_audio)
    deltas = [round(float(v["pts_time"]) - float(u["pts_time"]), 3) for x,y in [(original_video,rebuilt_video),(original_audio,rebuilt_audio)] for u,v in zip(x,y)]
    # Raw formats lose CodecDelay; muxing can normalize the common origin,
    # but every A/V packet must retain its relative source time.
    assert max(deltas) - min(deltas) <= 0.001
    assert [p["data_hash"] for p in original_audio] == [p["data_hash"] for p in rebuilt_audio]
    # A manual audio delay must adjust the external map, because mkvmerge's
    # --sync is overridden by external timestamps.
    output_delayed = tmp_path / "delayed.mkv"
    audio_path = next(folder / item.output_name for item in items if item.track_type == "audio")
    args, _ = core.build_mkvmerge_args(config, folder, output_delayed, "", False, video_fps="25",
        delay_overrides={core.path_identity_key(audio_path): "125"})
    run(*args)
    delayed = probe_packets(output_delayed)
    delayed_audio = [p for p in delayed if p["stream_index"] == 1]
    delayed_video = [p for p in delayed if p["stream_index"] == 0]
    assert len(delayed_audio) == len(rebuilt_audio)
    assert all(round(float(v["pts_time"]) - float(u["pts_time"]), 3) == .125 for u,v in zip(rebuilt_audio,delayed_audio))
    assert [p["pts_time"] for p in delayed_video] == [p["pts_time"] for p in rebuilt_video]
