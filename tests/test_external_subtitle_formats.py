from pathlib import Path

from src.gtmce.transcription import read_ass_ssa, read_subtitle_for_translation, read_vtt


def test_read_vtt_keeps_italic_and_sdh(tmp_path: Path):
    path = tmp_path / "sample.vtt"
    path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<i>[whispers]</i> Hello world\n", encoding="utf-8")
    cues = read_vtt(path)
    assert len(cues) == 1
    assert cues[0].text == "<i>[whispers]</i> Hello world"


def test_read_ass_converts_italic_override_to_srt_markup(tmp_path: Path):
    path = tmp_path / "sample.ass"
    path.write_text(
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\i1}[whispers]{\\i0} Hello\\Nworld\n",
        encoding="utf-8",
    )
    cues = read_ass_ssa(path)
    assert len(cues) == 1
    assert cues[0].text == "<i>[whispers]</i> Hello\nworld"


def test_generic_reader_accepts_ssa(tmp_path: Path):
    path = tmp_path / "sample.ssa"
    path.write_text(
        "[Events]\n"
        "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: Marked=0,0:00:01.00,0:00:02.00,Default,,0,0,0,,[door closes]\n",
        encoding="utf-8",
    )
    cues = read_subtitle_for_translation(path)
    assert len(cues) == 1
    assert cues[0].text == "[door closes]"
