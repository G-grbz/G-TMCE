from pathlib import Path

from src.gtmce import core


def audio_task(path: Path, delta_seconds: float) -> core.AudioAdjustTask:
    return core.AudioAdjustTask(
        path=path,
        delta_seconds=delta_seconds,
        codec="ac3",
        bitrate="192k",
        sample_rate="48000",
        channel_layout="stereo",
        original_codec="ac3",
        original_bitrate="192k",
        original_sample_rate="48000",
        original_channel_layout="stereo",
    )


def test_positive_adjust_uses_one_output_and_reuses_original_backup(tmp_path, monkeypatch):
    track = tmp_path / "tur.ac3"
    track.write_bytes(b"original audio")
    commands: list[list[str]] = []

    def fake_run(args, _log, **_kwargs):
        commands.append(args)
        Path(args[-1]).write_bytes(b"generated audio")

    monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(core, "run_cancellable_logged_process", fake_run)

    output = core.run_audio_adjust_task(audio_task(track, 5), lambda _message: None)

    backup = tmp_path / "tur.source.ac3"
    assert output == track
    assert backup.read_bytes() == b"original audio"
    assert track.read_bytes() == b"generated audio"
    assert not (tmp_path / "tur.1.ac3").exists()
    assert "-filter_complex" not in commands[0]
    assert commands[0][commands[0].index("-f") + 1] == "lavfi"
    assert core.read_audio_adjust_delay_append_path(track) == backup

    roots, append_paths, _append_names = core.discover_media_track_paths_with_appends(tmp_path)
    assert roots == [track]
    assert append_paths[track.name.lower()] == (backup,)

    core.run_audio_adjust_task(audio_task(track, 4), lambda _message: None)

    assert backup.read_bytes() == b"original audio"
    assert track.read_bytes() == b"generated audio"
    assert len(commands) == 2


def test_restore_original_discards_generated_version(tmp_path):
    track = tmp_path / "tur.ac3"
    backup = tmp_path / "tur.source.ac3"
    backup.write_bytes(b"original audio")
    track.write_bytes(b"generated audio")

    restored = core.restore_audio_adjust_original(track)

    assert restored == track
    assert track.read_bytes() == b"original audio"
    assert not backup.exists()


def test_restore_original_accepts_legacy_source_sidecar(tmp_path):
    track = tmp_path / "tur.ac3"
    legacy_backup = tmp_path / "tur.ac3.source"
    old_append = tmp_path / "tur.1.ac3"
    legacy_backup.write_bytes(b"original audio")
    track.write_bytes(b"generated audio")
    old_append.write_bytes(b"old generated append")

    restored = core.restore_audio_adjust_original(track)

    assert restored == track
    assert track.read_bytes() == b"original audio"
    assert not legacy_backup.exists()
    assert not old_append.exists()


def test_retained_audio_backup_is_not_discovered_as_a_mux_track(tmp_path):
    generated = tmp_path / "tur.ac3"
    backup = tmp_path / "tur.source.ac3"
    generated.write_bytes(b"generated audio")
    backup.write_bytes(b"original audio")

    assert core.discover_media_track_paths(tmp_path) == [generated]


def test_managed_delay_keeps_manual_numbered_audio_appends_in_order(tmp_path):
    base = tmp_path / "tur.ac3"
    source = tmp_path / "tur.source.ac3"
    append_one = tmp_path / "tur.1.ac3"
    append_two = tmp_path / "tur.2.ac3"
    for path in (base, source, append_one, append_two):
        path.write_bytes(path.name.encode())
    core.write_audio_adjust_delay_manifest(base, source, 9)

    roots, append_paths, _append_names = core.discover_media_track_paths_with_appends(tmp_path)

    assert roots == [base]
    assert append_paths[base.name.lower()] == (source, append_one, append_two)
