from dataclasses import replace

from src.gtmce import core


def options(**changes):
    return replace(core.ChapterOptions(
        enabled=True, interval_minutes="10", name="Scene", start_number="1", end_minutes="31",
    ), **changes)


def chapter_times(path):
    return [
        line.split("=", 1)[1]
        for line in path.read_text().splitlines()
        if line.startswith("CHAPTER") and "NAME=" not in line
    ]


def test_chapters_follow_requested_interval(tmp_path):
    path = tmp_path / "chapters.txt"
    core.write_auto_chapters_file(path, options(), duration_seconds=0)
    assert chapter_times(path) == ["00:10:00.000", "00:20:00.000", "00:30:00.000"]
    assert "CHAPTER01NAME= Scene 1" in path.read_text()


def test_start_number_controls_first_time_and_numbering(tmp_path):
    path = tmp_path / "chapters.txt"
    core.write_auto_chapters_file(path, options(start_number="2"), duration_seconds=0)
    assert chapter_times(path) == ["00:20:00.000", "00:30:00.000"]
    assert "CHAPTER02NAME= Scene 2" in path.read_text()


def test_fractional_intervals_keep_exact_millisecond_boundaries(tmp_path):
    path = tmp_path / "chapters.txt"
    core.write_auto_chapters_file(path, options(interval_minutes="0.5", end_minutes="1.5"), duration_seconds=0)
    assert chapter_times(path) == ["00:00:30.000", "00:01:00.000", "00:01:30.000"]


def test_explicit_end_generates_chapters_without_media_analysis(monkeypatch, tmp_path):
    def unexpected_analysis(*args, **kwargs):
        raise AssertionError("An explicit end must not probe media")
    monkeypatch.setattr(core, "detect_media_duration_seconds", unexpected_analysis)
    path, missing = core.resolve_chapter_path({}, tmp_path, [], options())
    assert missing == []
    assert chapter_times(path) == ["00:10:00.000", "00:20:00.000", "00:30:00.000"]


def test_empty_end_uses_detected_media_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "detect_media_duration_seconds", lambda *args, **kwargs: 31 * 60)
    path, missing = core.resolve_chapter_path({}, tmp_path, [], options(end_minutes=""))
    assert missing == []
    assert chapter_times(path) == ["00:10:00.000", "00:20:00.000", "00:30:00.000"]


def test_existing_chapters_are_preserved_and_disabled_generation_creates_nothing(tmp_path):
    path = tmp_path / "chapters.txt"
    original = "CHAPTER01=00:00:00.000\nCHAPTER01NAME=Original chapter\n"
    path.write_text(original)
    resolved, missing = core.resolve_chapter_path({}, tmp_path, [], options())
    assert resolved == path and missing == []
    assert path.read_text() == original
    other = tmp_path / "empty"
    other.mkdir()
    resolved, missing = core.resolve_chapter_path({}, other, [], options(enabled=False))
    assert resolved is None and missing == ["chapters.txt"]
    assert not (other / "chapters.txt").exists()
