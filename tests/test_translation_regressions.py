import re

import pytest

from src.gtmce import transcription as tr


@pytest.mark.parametrize("text,expected", [
    ("The only way to solve this\nwas to work together.", ["The only way to solve this was to work together."]),
    ("Uma frase longa\nem duas linhas.", ["Uma frase longa em duas linhas."]),
    ("这是同一句话\n只是换了行。", ["这是同一句话 只是换了行。"]),
    ("- First speaker\nfinishes here.\n- Second speaker.", ["- First speaker finishes here.", "- Second speaker."]),
])
def test_display_newlines_are_not_translation_boundaries(text, expected):
    assert tr._authored_translation_lines(text) == expected


def test_inline_styles_keep_separating_whitespace(monkeypatch):
    monkeypatch.setattr(tr, "_decode_single_translation", lambda *a, **k: "translated")
    result = tr._translate_existing_cue_text_strict(object(), object(), "Hello <b>world</b> today.", "de")
    assert result == "translated <b>translated</b> translated"


@pytest.mark.parametrize("source,output,expected", [
    ("We knew one another.", "Birbirimizi tanıyorduk, birbirimizi tanırdık.", "Birbirimizi tanıyorduk."),
    ("A problem was going to happen,", "Ama kötü bir şey olacaktı, kötü şeyler olacakdı.", "Ama kötü bir şey olacaktı."),
    ("Un message unique.", "Eine wichtige Nachricht. Eine wichtige Nachricht.", "Eine wichtige Nachricht."),
    ("A single statement.", "这是一条重要消息。这是一条重要消息。", "这是一条重要消息。"),
])
def test_alternative_duplicate_repair_is_language_agnostic(source, output, expected):
    assert tr._remove_translation_clause_duplicates(source, output) == expected


def test_genuine_source_repetition_is_not_removed():
    source = "Come on, come on, come on."
    output = "Hadi, hadi, hadi."
    assert tr._remove_translation_clause_duplicates(source, output) == output
    assert tr._strict_translation_quality_reason(source, output) is None


@pytest.mark.parametrize("source,output", [
    ("We used to know each other.", "Birbirimizi tanıyorduk."),
    ("Get out of the vehicle, please.", "Araçtan çıkın lütfen."),
    ("Please come home before it gets dark.", "请在天黑之前回家。"),
    ("请在天黑之前回家。", "Please come home before it gets dark."),
    ("请在天黑之前回家，因为今晚可能会下雨。", "Veuillez rentrer chez vous avant la tombée de la nuit, car il peut pleuvoir ce soir."),
])
def test_morphology_and_unspaced_scripts_are_not_omissions(source, output):
    assert tr._strict_translation_quality_reason(source, output) is None


def test_unfinished_sentence_groups_respect_styles_gaps_and_speakers():
    cues = [
        tr.SubtitleCue(1, 2, "<i>The only way</i>"),
        tr.SubtitleCue(2.001, 3, "<i>was to help.</i>"),
        tr.SubtitleCue(4, 5, "Another phrase,"),
        tr.SubtitleCue(9, 10, "after a long gap."),
        tr.SubtitleCue(10.001, 11, "<i>A different style,</i>"),
        tr.SubtitleCue(11.001, 12, "cannot be merged."),
        tr.SubtitleCue(13, 14, "- One person,\n- Another person."),
    ]
    assert tr._authored_sentence_groups(cues) == [[0, 1]]


@pytest.mark.parametrize("target", [
    "Eine längere Nachricht mit mehreren wichtigen Teilen.",
    "这是一条包含多个重要部分的较长消息。",
    "هذه رسالة أطول تحتوي على عدة أجزاء مهمة.",
])
def test_sentence_distribution_never_duplicates_or_drops_words(target):
    pieces = tr._distribute_authored_sentence(target, ["A first part,", "and the ending."])
    assert len(pieces) == 2
    assert re.sub(r"\s+", "", "".join(pieces)) == re.sub(r"\s+", "", target)


@pytest.mark.parametrize("payload", [
    "A deliberately long sentence containing many ordinary words and enough useful information to need several readable subtitle screens.",
    "这是一个很长的字幕句子，其中包含很多重要信息，需要分成多个易读的字幕画面，同时保留原始时间范围，不能重复也不能遗漏任何文字。",
    "هذه جملة ترجمة طويلة تحتوي على الكثير من المعلومات المهمة التي يجب تقسيمها إلى شاشات ترجمة مقروءة دون حذف أي جزء منها.",
])
def test_layout_splits_different_scripts_inside_original_interval(payload):
    text = r'{\an8}<i><b>[' + payload + ']</b></i>'
    cue = tr.SubtitleCue(10, 18, text)
    pieces = tr._layout_authored_translation_cue(cue)
    assert len(pieces) > 1
    assert pieces[0].start == cue.start
    assert pieces[-1].end == cue.end
    assert all(a.end == b.start for a, b in zip(pieces, pieces[1:]))
    for piece in pieces:
        assert piece.end > piece.start
        assert piece.text.startswith(r'{\an8}<i><b>[')
        assert piece.text.endswith(']</b></i>')
        visible = re.sub(r"<[^>]+>|\{[^}]*\}|[\[\]]", "", piece.text)
        assert len(visible.splitlines()) <= 2
        assert all(sum(tr._subtitle_character_width(c) for c in line) <= 42 for line in visible.splitlines())
    before = tr._subtitle_layout_units(cue.text)
    after = [unit for piece in pieces for unit in tr._subtitle_layout_units(piece.text)]
    assert [u for u in before if not u[0].isspace()] == [u for u in after if not u[0].isspace()]


def test_layout_preserves_inline_styles_and_speaker_boundaries():
    cue = tr.SubtitleCue(1, 10, "- This is <i>an italic passage with many words that must be reflowed</i> without losing its styling.\n- Another speaker answers.")
    pieces = tr._layout_authored_translation_cue(cue)
    before = tr._subtitle_layout_units(cue.text)
    after = [u for piece in pieces for u in tr._subtitle_layout_units(piece.text)]
    assert [u for u in before if not u[0].isspace()] == [u for u in after if not u[0].isspace()]


def test_file_translation_validates_then_splits_without_mutating_source(monkeypatch, tmp_path):
    source = tmp_path / "input.srt"
    tr.write_srt(source, [tr.SubtitleCue(1, 9, "<i>An authored sentence.</i>")])
    original = source.read_bytes()
    long_output = "<i>" + "A lengthy translated sentence with many necessary details and carefully preserved words. " * 2 + "</i>"
    monkeypatch.setattr(tr, "translate_existing_subtitle_cues_with_ai", lambda *a, **k: [tr.SubtitleCue(1, 9, long_output)])
    report = {}
    result = tr.translate_subtitle_with_ai(source, "fr", "de", output_path=tmp_path / "output.srt", qa_report=report)
    pieces = tr.read_srt(result)
    assert len(pieces) > 1
    assert pieces[0].start == 1
    assert pieces[-1].end == 9
    assert report["split_cues"] == 1
    assert report["output_cues"] == len(pieces)
    assert source.read_bytes() == original


def test_missing_sentence_rescue_translates_complete_sentences_not_display_lines(monkeypatch):
    seen = []
    def retry(_translator, _tokenizer, source, _target, **kwargs):
        seen.append(source)
        return {"We should leave!": "Wir sollten gehen!", "It is late!": "Es ist spät!"}[source]
    monkeypatch.setattr(tr, "_strict_retry_translation", retry)
    output = tr._strict_sentence_retry_translation(object(), object(), "We should leave! It is late!", "de")
    assert seen == ["We should leave!", "It is late!"]
    assert output == "Wir sollten gehen! Es ist spät!"


def test_unfinished_sentence_first_pass_is_batched(monkeypatch):
    from types import SimpleNamespace
    batch_sizes = []
    class Tokenizer:
        def encode(self, text, out_type=str):
            return text.split()
        def decode(self, tokens):
            return " ".join(tokens)
    class Translator:
        def translate_batch(self, payloads, **kwargs):
            batch_sizes.append(len(payloads))
            return [SimpleNamespace(hypotheses=[["Gemeinsam", "können", "wir", "helfen."]]) for _ in payloads]
    monkeypatch.setattr(tr, "_prepare_translation_model", lambda *a, **k: object())
    monkeypatch.setattr(tr, "_load_translation_runtime", lambda *a, **k: (Translator(), Tokenizer()))
    monkeypatch.setattr(tr, "_strict_translation_quality_reason", lambda *a, **k: None)
    cues = [tr.SubtitleCue(3 * i, 3 * i + 1, "We can work," if i % 2 == 0 else "and help together.") for i in range(6)]
    # Use genuine adjacent timings inside each pair, with a scene gap between pairs.
    cues = [tr.SubtitleCue(i // 2 * 5 + i % 2, i // 2 * 5 + i % 2 + 1, cue.text) for i, cue in enumerate(cues)]
    progress = []
    result = tr.translate_existing_subtitle_cues_with_ai(cues, "en", "de", progress=lambda n,t: progress.append(n))
    assert batch_sizes == [3]
    assert len(result) == len(cues)
    assert [(c.start, c.end) for c in result] == [(c.start, c.end) for c in cues]
    assert progress == list(range(1, 7))


def test_cancelled_layout_does_not_publish_output(monkeypatch, tmp_path):
    import threading
    from src.gtmce.core import OperationCancelled
    source = tmp_path / "input.srt"
    tr.write_srt(source, [tr.SubtitleCue(1, 9, "An authored sentence.")])
    cancel = threading.Event()
    def translation(*args, **kwargs):
        cancel.set()
        return [tr.SubtitleCue(1, 9, "Ein übersetzter Satz.")]
    monkeypatch.setattr(tr, "translate_existing_subtitle_cues_with_ai", translation)
    target = tmp_path / "output.srt"
    with pytest.raises(OperationCancelled):
        tr.translate_subtitle_with_ai(source, "en", "de", output_path=target, cancel_event=cancel)
    assert not target.exists()
