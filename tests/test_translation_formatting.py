from src.gtmce.transcription import (
    SubtitleCue,
    _split_long_translation_cue,
    _translation_text_wrapper,
    _restore_translation_wrapper,
)


def test_sdh_wrapper_round_trip():
    payload, prefix, suffix = _translation_text_wrapper("[door closes]")
    assert payload == "door closes"
    assert _restore_translation_wrapper("kapı kapanır", prefix, suffix) == "[kapı kapanır]"


def test_italic_wrapper_round_trip():
    payload, prefix, suffix = _translation_text_wrapper("<i>Hello there.</i>")
    assert payload == "Hello there."
    assert _restore_translation_wrapper("Merhaba.", prefix, suffix) == "<i>Merhaba.</i>"


def test_nested_italic_sdh_wrapper_round_trip():
    payload, prefix, suffix = _translation_text_wrapper("<i>[whispers]</i>")
    assert payload == "whispers"
    assert _restore_translation_wrapper("fısıldar", prefix, suffix) == "<i>[fısıldar]</i>"


def test_long_translation_is_split_into_readable_cues():
    cue = SubtitleCue(0.0, 8.0, "Bu oldukça uzun bir altyazı metnidir ve ekranda tek parça olarak gösterildiğinde okunması zor olacağı için uygun biçimde bölünmelidir.")
    result = _split_long_translation_cue(cue)
    assert len(result) >= 2
    assert result[0].start == 0.0
    assert result[-1].end == 8.0
    assert all(len(line) <= 84 for item in result for line in item.text.splitlines())


def test_long_italic_translation_keeps_balanced_wrapper_on_each_piece():
    from src.gtmce.transcription import SubtitleCue, _split_long_translation_cue
    text = "<i>" + ("very long translated dialogue " * 8).strip() + "</i>"
    pieces = _split_long_translation_cue(SubtitleCue(0.0, 8.0, text), max_chars=50)
    assert len(pieces) > 1
    assert all(piece.text.startswith("<i>") and piece.text.endswith("</i>") for piece in pieces)


def test_long_sdh_translation_keeps_brackets_on_each_piece():
    from src.gtmce.transcription import SubtitleCue, _split_long_translation_cue
    text = "[" + ("very long sound description " * 8).strip() + "]"
    pieces = _split_long_translation_cue(SubtitleCue(0.0, 8.0, text), max_chars=50)
    assert len(pieces) > 1
    assert all(piece.text.startswith("[") and piece.text.endswith("]") for piece in pieces)


def test_strict_parts_preserve_sdh_italic_and_ass_positioning():
    from src.gtmce.transcription import _strict_translation_parts
    text = r'{\an8}<i>[whispers]</i> Hello <b>world</b>.'
    literals = [v for k, v in _strict_translation_parts(text) if k == 'literal']
    assert literals == [r'{\an8}', '<i>', '[', ']', '</i>', '<b>', '</b>']


def test_strict_validator_rejects_timing_or_markup_changes():
    import pytest
    from src.gtmce.transcription import SubtitleCue, _validate_strict_subtitle_translation
    source = [SubtitleCue(1.0, 2.0, r'{\an8}<i>Hello</i>')]
    _validate_strict_subtitle_translation(source, [SubtitleCue(1.0, 2.0, r'{\an8}<i>Merhaba</i>')])
    with pytest.raises(Exception):
        _validate_strict_subtitle_translation(source, [SubtitleCue(1.1, 2.0, r'{\an8}<i>Merhaba</i>')])
    with pytest.raises(Exception):
        _validate_strict_subtitle_translation(source, [SubtitleCue(1.0, 2.0, '<i>Merhaba</i>')])


def test_strict_quality_flags_generic_echo_omission_expansion_and_speaker_loss():
    from src.gtmce.transcription import _strict_translation_quality_reason

    assert _strict_translation_quality_reason(
        "This sentence should definitely be translated.",
        "This sentence should definitely be translated.",
    ) is not None
    assert _strict_translation_quality_reason(
        "one two three four five six seven eight nine ten", "iki"
    ).startswith("probable-omission")
    assert _strict_translation_quality_reason(
        "one two three four five six", "bir iki üç dört beş altı yedi sekiz dokuz on onbir oniki onüç ondört onbeş"
    ) is not None
    assert _strict_translation_quality_reason(
        "- First speaker.\n- Second speaker.", "- Birinci konuşmacı. İkinci konuşmacı."
    ).startswith("speaker-count")


def test_srt_reader_preserves_authored_speaker_lines(tmp_path):
    from src.gtmce.transcription import read_srt

    path = tmp_path / "dialogue.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n- First speaker.\n- Second speaker.\n",
        encoding="utf-8",
    )
    cues = read_srt(path)
    assert len(cues) == 1
    assert cues[0].text == "- First speaker.\n- Second speaker."


def test_strict_payload_detaches_and_restores_speaker_marker(monkeypatch):
    import src.gtmce.transcription as tr

    monkeypatch.setattr(tr, "_decode_single_translation", lambda *a, **k: "Merhaba.")
    result = tr._translate_payload_strict(object(), object(), "- Hello.", "tr")
    assert result == "- Merhaba."


def test_strict_cue_translates_each_speaker_line_independently(monkeypatch):
    import src.gtmce.transcription as tr

    seen = []
    def fake_payload(_translator, _tokenizer, text, _target):
        seen.append(text)
        return text.replace("First", "Birinci").replace("Second", "İkinci")

    monkeypatch.setattr(tr, "_translate_payload_strict", fake_payload)
    result = tr._translate_existing_cue_text_strict(
        object(), object(), "- First speaker.\n- Second speaker.", "tr"
    )
    assert seen == ["- First speaker.", "- Second speaker."]
    assert "- Birinci speaker." in result
    assert "- İkinci speaker." in result
    assert result.count("\n") == 1


def test_strict_quality_flags_half_clause_loss_and_tighter_expansion():
    from src.gtmce.transcription import _strict_translation_quality_reason
    assert _strict_translation_quality_reason(
        "Hey hey hey whoa whoa whoa", "Hey hey hey"
    ) is not None
    assert _strict_translation_quality_reason(
        "Because I am not just Peter Parker", "Çünkü ben sadece Peter Parker değilim ben Peter Parker'ım"
    ) is not None


def test_context_translation_extracts_only_current_segment(monkeypatch):
    import src.gtmce.transcription as tr

    monkeypatch.setattr(
        tr,
        "_decode_single_translation",
        lambda *a, **k: "Önceki ||| Biraz ara ver. ||| Sonraki",
    )
    value = tr._strict_context_translation(
        object(), object(), "Take five.", "tr", "Previous.", "Next."
    )
    assert value == "Biraz ara ver."


def test_strict_translation_populates_cue_level_qa_report(monkeypatch):
    import src.gtmce.transcription as tr

    monkeypatch.setattr(tr, "_prepare_translation_model", lambda *a, **k: object())
    monkeypatch.setattr(tr, "_load_translation_runtime", lambda *a, **k: (object(), object()))

    def fake_translate(_translator, _tokenizer, text, _target, **kwargs):
        events = {"retry", "context"} if "First" in text else {"review"}
        return text.replace("First", "Birinci").replace("Second", "İkinci"), events

    monkeypatch.setattr(tr, "_translate_existing_cue_text_strict_with_qa", fake_translate)
    report = {}
    result = tr.translate_existing_subtitle_cues_with_ai(
        [tr.SubtitleCue(0, 1, "First line."), tr.SubtitleCue(1, 2, "Second line.")],
        "en", "tr", qa_report=report,
    )
    assert len(result) == 2
    assert report["total"] == 2
    assert report["retried"] == 1
    assert report["context_used"] == 1
    assert report["review"] == 1
    assert report["successful"] == 1


def test_strict_translation_uses_batched_first_pass(monkeypatch):
    import src.gtmce.transcription as tr

    class Tok:
        def encode(self, text, out_type=str):
            return text.split()
        def decode(self, tokens):
            return " ".join(tokens)

    class Hyp:
        def __init__(self, text):
            self.hypotheses = [[text]]

    class Translator:
        def __init__(self):
            self.calls = 0
            self.batch_sizes = []
        def translate_batch(self, batch, **kwargs):
            self.calls += 1
            self.batch_sizes.append(len(batch))
            return [Hyp("translated") for _ in batch]

    translator = Translator()
    tokenizer = Tok()
    monkeypatch.setattr(tr, "_prepare_translation_model", lambda *a, **k: object())
    monkeypatch.setattr(tr, "_load_translation_runtime", lambda *a, **k: (translator, tokenizer))
    monkeypatch.setattr(tr, "_strict_translation_quality_reason", lambda *a, **k: None)

    cues = [tr.SubtitleCue(float(i), float(i + 1), f"Source line {i}.") for i in range(10)]
    out = tr.translate_existing_subtitle_cues_with_ai(cues, "en", "tr")
    assert len(out) == len(cues)
    assert translator.calls == 2
    assert translator.batch_sizes == [4, 6]


def test_ai_translation_quality_profiles_have_expected_tradeoffs():
    import src.gtmce.transcription as tr
    fast = tr.AI_TRANSLATION_QUALITY_PROFILES["fast"]
    balanced = tr.AI_TRANSLATION_QUALITY_PROFILES["balanced"]
    maximum = tr.AI_TRANSLATION_QUALITY_PROFILES["maximum"]
    assert fast["batch_size"] > balanced["batch_size"] > maximum["batch_size"]
    assert fast["beam_size"] < balanced["beam_size"] < maximum["beam_size"]
    assert fast["retry_attempts"] < balanced["retry_attempts"] < maximum["retry_attempts"]
    assert maximum["context_mode"] == "short_or_fail"


def test_short_bilingual_duplication_is_rejected():
    import src.gtmce.transcription as tr
    assert tr._strict_translation_quality_reason("V-Max.", "V-Max. V-Maks.") is not None


def test_balanced_qa_rejects_repeated_paraphrase_output():
    import src.gtmce.transcription as tr
    assert tr._strict_translation_quality_reason(
        "I was thinking the same thing.",
        "Ben de aynı şeyi düşünüyordum. Aynı şeyi düşündüm.",
    ).startswith("probable-output-duplication")
    assert tr._strict_translation_quality_reason(
        "You chased me this whole time.",
        "Bütün bu süre boyunca beni kovaladın, beni kovaladın.",
    ).startswith("probable-output-duplication")
    assert tr._strict_translation_quality_reason(
        "Spider-Man has to do the hard thing.",
        "Örümcek Adam zor olanı yapmak zorundadır, zor olan şeyi yapmalıdır.",
    ).startswith("probable-output-duplication")


def test_balanced_qa_allows_legitimate_two_clause_translation():
    import src.gtmce.transcription as tr
    assert tr._strict_translation_quality_reason(
        "I came home, and then I called you.",
        "Eve geldim, sonra seni aradım.",
    ) is None
