from pathlib import Path

from src.gtmce.core import (
    TrackItem,
    append_source_options,
    infer_language_from_filename,
    infer_subtitle_track_flags,
    make_minimal_track_entry,
)
from src.gtmce.transcription import (
    SubtitleCue,
    _best_cuda_compute_type,
    _group_speech_windows,
    _merge_cues,
    _suspicious_gaps,
    generated_subtitle_path,
    generated_translation_path,
    normalise_asr_language,
    read_srt,
    srt_timestamp,
    translate_cues_with_ai,
    translate_srt_with_ai,
    write_srt,
)


def test_language_aliases_match_track_languages():
    assert normalise_asr_language("tur") == "tr"
    assert normalise_asr_language("eng") == "en"
    assert normalise_asr_language("deu") == "de"
    assert normalise_asr_language("fre") == "fr"


def test_generated_subtitle_keeps_existing_language_token():
    assert generated_subtitle_path(Path("tr.ac3"), "tr") == Path("tr.generated.srt")
    assert generated_subtitle_path(Path("eng.(2).eac3"), "en") == Path("eng.(2).generated.srt")


def test_generated_subtitle_adds_language_when_filename_has_none():
    assert generated_subtitle_path(Path("commentary.flac"), "fr") == Path("commentary.fr.generated.srt")


def test_generated_translation_uses_selected_target_language():
    assert generated_translation_path(Path("eng.ac3"), "tr") == Path("eng.tr.generated.srt")
    assert generated_translation_path(Path("eng.ac3"), "de") == Path("eng.de.generated.srt")


def test_generated_audio_subtitles_receive_a_localized_track_name():
    english = infer_subtitle_track_flags(Path("eng.generated.srt"))
    turkish = infer_subtitle_track_flags(Path("tur.generated.srt"))

    assert english["language"] == "en"
    assert english["name"] == "Generated from Audio"
    assert turkish["language"] == "tr"
    assert turkish["name"] == "Sesten Oluşturuldu"


def test_ai_generated_subtitle_uses_target_language_and_track_name():
    turkish = infer_subtitle_track_flags(Path("eng.tr.generated.srt"))
    english = infer_subtitle_track_flags(Path("tur.en.generated.srt"))

    assert infer_language_from_filename(Path("eng.tr.generated.srt")) == "tr"
    assert turkish["language"] == "tr"
    assert turkish["name"] == "AI ile Çevrildi"
    assert english["language"] == "en"
    assert english["name"] == "AI Translated"


def test_ai_generated_subtitle_passes_target_language_and_name_to_mkvmerge():
    path = Path("eng.tr.generated.srt")
    entry, _ = make_minimal_track_entry(path, 1)
    args: list[str] = []

    append_source_options(args, TrackItem(entry, path, None))

    assert "0:tr" in args
    assert "0:AI ile Çevrildi" in args


def test_srt_timestamp_rounding():
    assert srt_timestamp(0) == "00:00:00,000"
    assert srt_timestamp(61.234) == "00:01:01,234"


def test_write_srt(tmp_path):
    target = tmp_path / "tr.generated.srt"
    write_srt(target, [SubtitleCue(1.0, 2.5, "Merhaba dünya")])
    assert target.read_text(encoding="utf-8") == (
        "1\n00:00:01,000 --> 00:00:02,500\nMerhaba dünya\n"
    )


def test_best_cuda_compute_type_prefers_float16(monkeypatch):
    import sys
    from types import SimpleNamespace

    fake = SimpleNamespace(
        get_cuda_device_count=lambda: 1,
        get_supported_compute_types=lambda device, index=0: {"float32", "int8_float16", "float16"},
    )
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    assert _best_cuda_compute_type() == "float16"


def test_best_cuda_compute_type_uses_int8_float32_when_fp16_is_not_supported(monkeypatch):
    import sys
    from types import SimpleNamespace

    fake = SimpleNamespace(
        get_cuda_device_count=lambda: 1,
        get_supported_compute_types=lambda device, index=0: {"float32", "int8_float32"},
    )
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    assert _best_cuda_compute_type() == "int8_float32"


def test_suspicious_gaps_include_large_internal_holes():
    cues = [SubtitleCue(17.0, 21.0, "a"), SubtitleCue(722.0, 724.0, "b")]
    assert _suspicious_gaps(cues, 800.0, minimum_gap=30.0) == [
        (21.0, 722.0),
        (724.0, 800.0),
    ]


def test_group_speech_windows_only_uses_chunks_inside_gap_ranges():
    chunks = [
        {"start": 10_000, "end": 20_000},
        {"start": 40_000, "end": 50_000},
        {"start": 51_000, "end": 60_000},
    ]
    windows = _group_speech_windows(
        chunks,
        1000,
        [(35.0, 70.0)],
        join_gap=2.0,
        max_window=30.0,
    )
    assert windows == [(40.0, 60.0)]


def test_merge_cues_adds_rescue_without_duplicate_overlap():
    primary = [SubtitleCue(10.0, 12.0, "bir"), SubtitleCue(20.0, 22.0, "iki")]
    rescued = [
        SubtitleCue(10.2, 11.8, "duplicate"),
        SubtitleCue(15.0, 16.0, "rescued"),
    ]
    merged = _merge_cues(primary, rescued)
    assert [(cue.start, cue.text) for cue in merged] == [
        (10.0, "bir"),
        (15.0, "rescued"),
        (20.0, "iki"),
    ]


def test_asr_runtime_and_model_snapshot_are_persisted(tmp_path, monkeypatch):
    import src.gtmce.transcription as transcription

    state_path = tmp_path / "asr-runtime.json"
    monkeypatch.setenv("GTMCE_ASR_RUNTIME_STATE", str(state_path))
    monkeypatch.delenv("GTMCE_ASR_DEVICE", raising=False)
    monkeypatch.delenv("GTMCE_ASR_COMPUTE_TYPE", raising=False)

    snapshot = tmp_path / "model-snapshot"
    snapshot.mkdir()
    transcription._remember_runtime("cuda", "int8_float32")
    transcription._remember_model_snapshot("turbo", snapshot)

    messages = []
    assert transcription._runtime_device(messages.append) == ("cuda", "int8_float32", True)
    assert transcription._saved_model_snapshot("turbo") == snapshot.resolve()
    assert any("using saved runtime cuda/int8_float32" in message for message in messages)


def test_missing_saved_model_snapshot_is_ignored(tmp_path, monkeypatch):
    import src.gtmce.transcription as transcription

    state_path = tmp_path / "asr-runtime.json"
    monkeypatch.setenv("GTMCE_ASR_RUNTIME_STATE", str(state_path))
    transcription._write_asr_runtime_state({
        "models": {"turbo": str(tmp_path / "missing-snapshot")},
    })

    assert transcription._saved_model_snapshot("turbo") is None


def test_explicit_runtime_override_beats_saved_runtime(tmp_path, monkeypatch):
    import src.gtmce.transcription as transcription

    state_path = tmp_path / "asr-runtime.json"
    monkeypatch.setenv("GTMCE_ASR_RUNTIME_STATE", str(state_path))
    transcription._remember_runtime("cuda", "int8_float32")
    monkeypatch.setenv("GTMCE_ASR_DEVICE", "cpu")
    monkeypatch.setenv("GTMCE_ASR_COMPUTE_TYPE", "int8")

    assert transcription._runtime_device() == ("cpu", "int8", False)


def test_hallucination_cleanup_removes_subtitle_credit_variants():
    from src.gtmce.transcription import _filter_hallucinated_cues

    cues = [
        SubtitleCue(18.992, 20.612, "Altyazı M.K."),
        SubtitleCue(5776.530, 5778.270, "Altyazı M"),
        SubtitleCue(5786.110, 5787.090, ".K."),
        SubtitleCue(10.0, 11.0, "Gerçek konuşma."),
    ]
    assert _filter_hallucinated_cues(cues) == [SubtitleCue(10.0, 11.0, "Gerçek konuşma.")]


def test_hallucination_cleanup_removes_impossible_timing_but_keeps_real_thanks():
    from src.gtmce.transcription import _filter_hallucinated_cues

    cues = [
        SubtitleCue(0.0, 0.78, "İzlediğiniz için teşekkür ederim."),
        SubtitleCue(10.0, 10.04, "Teşekkür ederim."),
        SubtitleCue(20.0, 21.5, "Tamam, çok teşekkür ediyorum."),
        SubtitleCue(30.0, 30.2, "Ah!"),
    ]
    assert _filter_hallucinated_cues(cues) == [
        SubtitleCue(20.0, 21.5, "Tamam, çok teşekkür ediyorum."),
        SubtitleCue(30.0, 30.2, "Ah!"),
    ]


def test_hallucination_cleanup_keeps_normal_subtitle_word_in_dialogue():
    from src.gtmce.transcription import _filter_hallucinated_cues

    cue = SubtitleCue(5.0, 7.0, "Bu altyazı neden burada?")
    assert _filter_hallucinated_cues([cue]) == [cue]


def test_hallucination_cleanup_keeps_single_word_even_with_tiny_word_timestamp():
    from src.gtmce.transcription import _filter_hallucinated_cues

    cue = SubtitleCue(10.0, 10.16, "Buyurun.")
    assert _filter_hallucinated_cues([cue]) == [cue]


def test_hallucination_cleanup_keeps_fast_but_plausible_dialogue():
    from src.gtmce.transcription import _filter_hallucinated_cues

    cue = SubtitleCue(34 * 60 + 7.07, 34 * 60 + 8.15, "Hayır, hayır, devam etmeyin, yeteri kadarsız.")
    assert _filter_hallucinated_cues([cue]) == [cue]


def test_sensitive_gap_rescue_can_target_twenty_second_hole():
    cues = [SubtitleCue(0.0, 10.0, "önce"), SubtitleCue(30.5, 32.0, "sonra")]
    assert _suspicious_gaps(cues, 40.0, minimum_gap=8.0)[0] == (10.0, 30.5)


def test_multilingual_ai_translation_preserves_timestamps(monkeypatch, tmp_path):
    import src.gtmce.transcription as transcription
    from types import SimpleNamespace

    class FakeTokenizer:
        def encode(self, text, out_type=str):
            assert out_type is str
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class FakeTranslator:
        def translate_batch(self, source_tokens, **_kwargs):
            assert source_tokens == [["<2tr>", "We", "must", "go.", "</s>"]]
            return [SimpleNamespace(hypotheses=[["Gitmeliyiz.", "</s>"]])]

    monkeypatch.setattr(
        transcription,
        "_prepare_translation_model",
        lambda *_args, **_kwargs: tmp_path,
    )
    monkeypatch.setattr(
        transcription,
        "_load_translation_runtime",
        lambda *_args, **_kwargs: (FakeTranslator(), FakeTokenizer()),
    )

    result = translate_cues_with_ai(
        [SubtitleCue(1.25, 2.75, "We must go.")],
        "en",
        "tr",
    )
    assert result == [SubtitleCue(1.25, 2.75, "Gitmeliyiz.")]


def test_ai_translation_merges_split_sentence_fragments(monkeypatch, tmp_path):
    import src.gtmce.transcription as transcription
    from types import SimpleNamespace

    class FakeTokenizer:
        def encode(self, text, out_type=str):
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class FakeTranslator:
        def translate_batch(self, source_tokens, **_kwargs):
            assert source_tokens == [[
                "<2tr>", "Caring", "for", "a", "child", "no", "one", "tells", "you", "jack", "shit.", "</s>"
            ]]
            return [SimpleNamespace(hypotheses=[["Bir", "çocuğa", "bakmayı", "kimse", "sana", "öğretmiyor."]])]

    monkeypatch.setattr(transcription, "_prepare_translation_model", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        transcription,
        "_load_translation_runtime",
        lambda *_args, **_kwargs: (FakeTranslator(), FakeTokenizer()),
    )

    result = translate_cues_with_ai(
        [
            SubtitleCue(1.0, 2.0, "Caring for a child no one tells you"),
            SubtitleCue(2.1, 2.8, "jack shit."),
        ],
        "en",
        "tr",
    )
    assert len(result) == 2
    assert [(cue.start, cue.end) for cue in result] == [(1.0, 2.0), (2.1, 2.8)]
    assert " ".join(cue.text.replace("\n", " ") for cue in result) == (
        "Bir çocuğa bakmayı kimse sana öğretmiyor."
    )



def test_context_translation_keeps_original_cue_count_and_short_blocks(monkeypatch, tmp_path):
    import src.gtmce.transcription as transcription
    from types import SimpleNamespace

    class FakeTokenizer:
        def encode(self, text, out_type=str):
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    translated = (
        "Sonra taşındıktan sonra onları gördüğünüz geri kalan zamanı eve yaptığınız "
        "ziyaretleri birlikte geçirdiğiniz tatilleri hayatınızın geri kalanı boyunca "
        "onlarla paylaştığınız değerli anları topladığınızda eğer onları bir yıl daha "
        "görürseniz şanslısınız ve bu kadar."
    )

    class FakeTranslator:
        def translate_batch(self, source_tokens, **_kwargs):
            assert len(source_tokens) == 1
            return [SimpleNamespace(hypotheses=[translated.split() + ["</s>"]])]

    monkeypatch.setattr(transcription, "_prepare_translation_model", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        transcription,
        "_load_translation_runtime",
        lambda *_args, **_kwargs: (FakeTranslator(), FakeTokenizer()),
    )

    source = [
        SubtitleCue(349.390, 353.950, "Then after they move out, when you add up all the remaining time you see them,"),
        SubtitleCue(353.950, 359.860, "the visits home the vacations together precious snatch moments"),
        SubtitleCue(359.860, 362.200, "you share with them for the rest"),
        SubtitleCue(362.200, 368.070, "of your life you're lucky if you see them for one more year that's it"),
    ]
    result = translate_cues_with_ai(source, "en", "tr")

    assert len(result) >= 4
    assert result[0].start == 349.390
    assert result[-1].end == 368.070
    assert " ".join(cue.text.replace("\n", " ") for cue in result) == translated
    assert max(len(cue.text.replace("\n", " ")) for cue in result) <= 84

def test_read_srt_and_translate_existing_text(monkeypatch, tmp_path):
    import src.gtmce.transcription as transcription

    source = tmp_path / "eng.generated.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello there.\n",
        encoding="utf-8",
    )
    target = tmp_path / "eng.de.generated.srt"
    assert read_srt(source) == [SubtitleCue(1.0, 2.0, "Hello there.")]

    monkeypatch.setattr(
        transcription,
        "translate_existing_subtitle_cues_with_ai",
        lambda cues, source_language, target_language, **_kwargs: [
            SubtitleCue(cue.start, cue.end, "Hallo.") for cue in cues
        ],
    )
    result = translate_srt_with_ai(
        source,
        "en",
        "de",
        output_path=target,
    )
    assert result == target
    assert "Hallo." in target.read_text(encoding="utf-8")



def test_translation_degeneration_detects_runaway_but_keeps_real_repetition():
    from src.gtmce.transcription import _translation_degeneration_reason

    assert _translation_degeneration_reason("The", "The The The The The The The") is not None
    assert _translation_degeneration_reason("possibility it", "olasılık " * 36) is not None
    assert _translation_degeneration_reason(
        "Go, go, go, go, go, go, go.",
        "Hadi, hadi, hadi, hadi, hadi, hadi, hadi, hadi.",
    ) is None


def test_ai_translation_retries_decoder_loop_with_strict_settings(monkeypatch, tmp_path):
    import src.gtmce.transcription as transcription
    from types import SimpleNamespace

    class FakeTokenizer:
        def encode(self, text, out_type=str):
            assert out_type is str
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class FakeTranslator:
        def __init__(self):
            self.calls = []

        def translate_batch(self, source_tokens, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("beam_size") == 1:
                return [SimpleNamespace(hypotheses=[["Bu", "</s>"]])]
            return [SimpleNamespace(hypotheses=[["The"] * 7 + [["</s>"]][0]])]

    translator = FakeTranslator()
    monkeypatch.setattr(transcription, "_prepare_translation_model", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        transcription,
        "_load_translation_runtime",
        lambda *_args, **_kwargs: (translator, FakeTokenizer()),
    )

    result = translate_cues_with_ai(
        [SubtitleCue(1.0, 2.0, "The")],
        "en",
        "tr",
    )
    assert result == [SubtitleCue(1.0, 2.0, "Bu")]
    assert translator.calls[0]["repetition_penalty"] > 1
    assert translator.calls[0]["no_repeat_ngram_size"] == 3
    assert translator.calls[1]["beam_size"] == 1
    assert translator.calls[1]["no_repeat_ngram_size"] == 2


def test_translation_degeneration_detects_duplicate_alternative_sentence():
    from src.gtmce.transcription import _translation_degeneration_reason

    source = "They say on average, a child spends the first 18 years with their parents."
    output = (
        "Ortalama olarak, bir çocuğun ilk 18 yılını ebeveynleriyle geçirdiğini söylüyorlar. "
        "Çocuklar ilk 20 yılını anne ve babalarıyla geçirirler."
    )
    assert _translation_degeneration_reason(source, output) is not None
    assert _translation_degeneration_reason("No, no.", "Hayır, hayır.") is None


def test_long_translation_cue_is_split_for_readability():
    from src.gtmce.transcription import _split_long_translation_cue

    text = (
        "Bu çok uzun bir altyazı cümlesidir ve ekranda tek parça olarak gösterildiğinde "
        "izleyicinin sahneyi takip etmesini zorlaştırdığı için iki satırlık okunabilir "
        "altyazı bloklarına ayrılması gerekir."
    )
    result = _split_long_translation_cue(SubtitleCue(10.0, 18.0, text))
    assert len(result) >= 2
    assert result[0].start == 10.0
    assert result[-1].end == 18.0
    assert max(len(cue.text.replace("\n", " ")) for cue in result) <= 84
    assert " ".join(cue.text.replace("\n", " ") for cue in result) == text


def test_translation_degeneration_rejects_tiny_input_hallucination():
    from src.gtmce.transcription import _translation_degeneration_reason

    assert _translation_degeneration_reason(
        "The",
        "1960'lı yılların ortalarında The New Yorker dergisinde yayınlanan",
    ) == "tiny-input-expansion:1->8"


def test_translation_invalid_reason_retries_source_echo():
    from src.gtmce.transcription import _translation_invalid_reason

    assert _translation_invalid_reason(
        "Use of lethal force is authorized.",
        "Use of lethal force is authorized.",
    ) == "source-echo"
    assert _translation_invalid_reason("human traffickers.", "human traffickers.") == "source-echo-short"
    assert _translation_invalid_reason("My daughter.", "My daughter.") == "source-echo-short"
    assert _translation_invalid_reason("Yeah.", "Yeah.") == "source-echo-single"
    assert _translation_invalid_reason("Yep.", "Yep.") == "source-echo-single"
    assert _translation_invalid_reason("Nope.", "Nope.") == "source-echo-single"
    assert _translation_invalid_reason("I mean, that's late.", "I mean, that's late.") == "source-echo"
    assert _translation_invalid_reason("do", "do") == "source-echo-single"
    # Proper names may legitimately remain unchanged.
    assert _translation_invalid_reason("New Mexico", "New Mexico") is None
    assert _translation_invalid_reason("Chloe", "Chloe") is None


def test_rebalance_translation_timings_uses_following_silence_for_unreadable_cue():
    from src.gtmce.transcription import _rebalance_translation_timings

    cues = [
        SubtitleCue(
            158.670,
            158.870,
            "1960'lı yılların ortalarında, The New Yorker dergisinde yayınlanan",
        ),
        SubtitleCue(168.790, 172.410, "Sonraki altyazı."),
    ]
    result = _rebalance_translation_timings(cues)
    assert result[0].start == 158.670
    assert result[0].end > 161.0
    assert result[0].end < result[1].start
    assert result[1] == cues[1]


def test_rebalance_translation_timings_does_not_move_normal_fast_dialogue():
    from src.gtmce.transcription import _rebalance_translation_timings

    cue = SubtitleCue(1.0, 2.0, "Bir çocuğa bakmayı kimse")
    assert _rebalance_translation_timings([cue]) == [cue]


def test_source_echo_rescue_uses_sentence_case_variant():
    from src.gtmce.transcription import _rescue_source_echo_translation
    from types import SimpleNamespace

    class FakeTokenizer:
        def encode(self, text, out_type=str):
            assert out_type is str
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class FakeTranslator:
        def translate_batch(self, source_tokens, **_kwargs):
            text = " ".join(source_tokens[0])
            if "Human traffickers" in text:
                return [SimpleNamespace(hypotheses=[["İnsan", "kaçakçıları", "</s>"]])]
            return [SimpleNamespace(hypotheses=[["human", "traffickers", "</s>"]])]

    result = _rescue_source_echo_translation(
        FakeTranslator(), FakeTokenizer(), "human traffickers.", "tr"
    )
    assert result == "İnsan kaçakçıları"


def test_source_echo_rescue_can_use_neighbor_separator():
    from src.gtmce.transcription import _TranslationUnit, _rescue_translation_with_neighbor
    from types import SimpleNamespace

    class FakeTokenizer:
        def encode(self, text, out_type=str):
            assert out_type is str
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class FakeTranslator:
        def translate_batch(self, source_tokens, **_kwargs):
            return [SimpleNamespace(hypotheses=[[
                "İnsan", "kaçakçıları.", "|||", "Orta", "Doğu'ya", "askerler.", "</s>"
            ]])]

    units = [
        _TranslationUnit((SubtitleCue(1.0, 2.0, "human traffickers."),), "human traffickers."),
        _TranslationUnit((SubtitleCue(3.0, 4.0, "Troops to the Middle East."),), "Troops to the Middle East."),
    ]
    result = _rescue_translation_with_neighbor(
        FakeTranslator(), FakeTokenizer(), units, 0, "tr"
    )
    assert result == "İnsan kaçakçıları."


def test_english_dialogue_rescue_variants_cover_short_phrases_without_names():
    from src.gtmce.transcription import _english_dialogue_rescue_variants

    assert _english_dialogue_rescue_variants("Yeah.")[0] == "Yes."
    assert _english_dialogue_rescue_variants("Yep!")[0] == "Yes."
    assert _english_dialogue_rescue_variants("Nope.")[0] == "No."
    assert _english_dialogue_rescue_variants("I know.")[0] == "I understand."
    assert _english_dialogue_rescue_variants("Okay.")[0] == "All right."
    assert _english_dialogue_rescue_variants("Thanks!")[0] == "Thank you."
    assert _english_dialogue_rescue_variants("Sorry.")[0] == "I am sorry."
    assert _english_dialogue_rescue_variants("I mean, that's late.")[0] == "What I mean is that it is late."
    assert _english_dialogue_rescue_variants("Chloe") == []
    assert _english_dialogue_rescue_variants("Ellie") == []
    assert _english_dialogue_rescue_variants("Sullivan") == []


def test_source_echo_rescue_prefers_explicit_short_dialogue_paraphrase():
    from src.gtmce.transcription import _rescue_source_echo_translation
    from types import SimpleNamespace

    class FakeTokenizer:
        def encode(self, text, out_type=str):
            assert out_type is str
            return text.split()

        def decode(self, tokens):
            return " ".join(tokens)

    class FakeTranslator:
        def translate_batch(self, source_tokens, **_kwargs):
            text = " ".join(source_tokens[0])
            if "Yes." in text:
                return [SimpleNamespace(hypotheses=[["Evet.", "</s>"]])]
            return [SimpleNamespace(hypotheses=[["Yeah.", "</s>"]])]

    result = _rescue_source_echo_translation(
        FakeTranslator(), FakeTokenizer(), "Yeah.", "tr"
    )
    assert result == "Evet."


def test_translation_degeneration_rejects_six_word_hallucination_from_the():
    from src.gtmce.transcription import _translation_degeneration_reason

    assert _translation_degeneration_reason(
        "The", "The, 1980'de yayınlanan bir Amerikan animasyon"
    ) == "tiny-input-expansion:1->6"


def test_ai_translation_drops_tiny_incomplete_english_function_word(monkeypatch, tmp_path):
    import src.gtmce.transcription as transcription

    class NeverCalledTranslator:
        def translate_batch(self, *_args, **_kwargs):
            raise AssertionError("tiny ASR fragment should be dropped before translation")

    class DummyTokenizer:
        pass

    monkeypatch.setattr(transcription, "_prepare_translation_model", lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(
        transcription,
        "_load_translation_runtime",
        lambda *_args, **_kwargs: (NeverCalledTranslator(), DummyTokenizer()),
    )

    result = transcription.translate_cues_with_ai(
        [transcription.SubtitleCue(158.670, 158.870, "The")],
        "en",
        "tr",
    )
    assert result == []


def test_default_asr_model_prefers_accuracy_for_subtitle_creation():
    from src.gtmce.transcription import DEFAULT_ASR_MODEL

    assert DEFAULT_ASR_MODEL == "large-v3"


def test_hallucination_cleanup_removes_stock_intro_boilerplate_from_sample():
    from src.gtmce.transcription import _filter_hallucinated_cues

    cues = [
        SubtitleCue(2.14, 3.98, "İzlediğiniz için teşekkür ederim."),
        SubtitleCue(17.92, 19.74, "Abi, ben diyeceğim seni öldürecek."),
    ]
    assert _filter_hallucinated_cues(cues) == [cues[1]]


def test_asr_has_no_builtin_turkish_hotword_bias(monkeypatch):
    from src.gtmce.transcription import _asr_hotwords

    monkeypatch.delenv("GTMCE_ASR_HOTWORDS", raising=False)
    assert _asr_hotwords("tr") is None


def test_asr_custom_hotwords_remain_opt_in(monkeypatch):
    from src.gtmce.transcription import _asr_hotwords

    monkeypatch.setenv("GTMCE_ASR_HOTWORDS", "özel terim")
    assert _asr_hotwords("tr") == "özel terim"


def test_dialogue_mix_uses_center_channel_for_surround_layouts():
    from src.gtmce.transcription import _dialogue_mix_filter

    for layout in ("5.1", "5.1(side)", "7.1", "3.0"):
        mix = _dialogue_mix_filter(layout)
        assert mix is not None
        assert "FC" in mix
        assert "FL" in mix
        assert "FR" in mix


def test_dialogue_mix_leaves_stereo_and_centerless_layouts_unchanged():
    from src.gtmce.transcription import _dialogue_mix_filter

    for layout in ("mono", "stereo", "2.1", "quad", ""):
        assert _dialogue_mix_filter(layout) is None


def test_large_v3_plus_uses_heavier_decode_than_large_v3():
    from src.gtmce.transcription import ASR_QUALITY_PROFILES

    regular = ASR_QUALITY_PROFILES["slow"]
    plus = ASR_QUALITY_PROFILES["slower"]
    assert regular["model"] == plus["model"] == "large-v3"
    assert plus["beam_size"] > regular["beam_size"]
    assert plus["beam_size"] <= 8
    assert plus["patience"] > regular["patience"]
    assert plus["patience"] <= 1.5


def test_repetition_loop_cleanup_removes_multiword_prompt_lock_region():
    from src.gtmce.transcription import _filter_repetition_loops

    cues = [SubtitleCue(0.0, 1.0, "Gerçek cümle.")]
    for i in range(8):
        start = 2.0 + i * 2.0
        cues.append(SubtitleCue(start, start + 1.0, "Ne yapar?"))
    cues.append(SubtitleCue(19.0, 20.0, "Sonraki gerçek cümle."))

    cleaned = _filter_repetition_loops(cues)
    assert [cue.text for cue in cleaned] == ["Gerçek cümle.", "Sonraki gerçek cümle."]


def test_repetition_loop_cleanup_catches_long_single_word_lock_but_keeps_short_repetition():
    from src.gtmce.transcription import _filter_repetition_loops

    short = [SubtitleCue(i * 1.5, i * 1.5 + 0.5, "Kimsin?") for i in range(4)]
    assert _filter_repetition_loops(short) == short

    long = [SubtitleCue(i * 1.5, i * 1.5 + 0.5, "Kimsin?") for i in range(10)]
    assert _filter_repetition_loops(long) == []


def test_local_context_ranges_overlap_without_output_gaps():
    from src.gtmce.transcription import _local_context_ranges

    ranges = _local_context_ranges(250.0, block_seconds=120.0, overlap_seconds=3.0)
    assert ranges == [
        (0.0, 120.0, 0.0, 118.5),
        (117.0, 237.0, 118.5, 235.5),
        (234.0, 250.0, 235.5, 250.0),
    ]
    # Decode windows overlap, but ownership windows are continuous.
    assert ranges[0][1] > ranges[1][0]
    assert ranges[1][1] > ranges[2][0]
    assert ranges[0][3] == ranges[1][2]
    assert ranges[1][3] == ranges[2][2]


def test_local_context_ranges_keep_short_audio_in_one_block():
    from src.gtmce.transcription import _local_context_ranges

    assert _local_context_ranges(75.0) == [(0.0, 75.0, 0.0, 75.0)]


def test_vad_boundary_prefers_nearby_real_silence():
    from src.gtmce.transcription import _choose_vad_silence_boundary

    # Nominal 120 s falls inside speech; nearest useful silence is 121.4-123.0.
    boundary = _choose_vad_silence_boundary(
        120.0,
        108.0,
        132.0,
        [(108.0, 121.4), (123.0, 132.0)],
        min_silence_seconds=0.55,
    )
    assert 121.5 <= boundary <= 122.9


def test_vad_boundary_keeps_target_when_target_is_already_silent():
    from src.gtmce.transcription import _choose_vad_silence_boundary

    boundary = _choose_vad_silence_boundary(
        120.0,
        108.0,
        132.0,
        [(108.0, 118.5), (121.0, 132.0)],
    )
    assert boundary == 120.0


def test_context_ranges_use_silence_boundaries_with_small_overlap():
    from src.gtmce.transcription import _local_context_ranges_from_boundaries

    ranges = _local_context_ranges_from_boundaries(
        250.0,
        [121.8, 239.2],
        overlap_seconds=1.0,
    )
    assert ranges == [
        (0.0, 122.3, 0.0, 121.8),
        (121.3, 239.7, 121.8, 239.2),
        (238.7, 250.0, 239.2, 250.0),
    ]
    assert ranges[0][3] == ranges[1][2]
    assert ranges[1][3] == ranges[2][2]


def test_boundary_duplicate_cleanup_catches_shifted_whisper_sentence():
    from src.gtmce.transcription import _deduplicate_boundary_cues

    cues = [
        SubtitleCue(116.08, 120.40, "Senin ağabeyin var ya, senin ağabin gelsin beni öldürsün."),
        SubtitleCue(117.00, 121.10, "Senin abin var ya, senin abin gelsin beni öldürsün."),
        SubtitleCue(124.00, 125.00, "Başka bir cümle."),
    ]
    cleaned = _deduplicate_boundary_cues(cues, [120.0])
    assert len(cleaned) == 2
    assert any("öldürsün" in cue.text for cue in cleaned)
    assert any(cue.text == "Başka bir cümle." for cue in cleaned)


def test_standalone_ai_subtitle_track_names_and_language():
    for name, language, title in (
        ("tur(ai).srt", "tr", "AI ile Çevrildi"),
        ("tur(ai-2).srt", "tr", "AI ile Çevrildi"),
        ("fre(ai-3).srt", "fr", "AI Translated"),
    ):
        path = Path(name)
        flags = infer_subtitle_track_flags(path)
        assert flags["language"] == language
        assert flags["name"] == title
        entry, _ = make_minimal_track_entry(path, 1)
        args = []
        append_source_options(args, TrackItem(entry, path, None))
        assert f"0:{language}" in args
        assert f"0:{title}" in args
