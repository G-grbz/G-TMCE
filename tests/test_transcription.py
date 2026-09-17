from pathlib import Path

from src.gtmce.transcription import (
    SubtitleCue,
    _best_cuda_compute_type,
    _group_speech_windows,
    _merge_cues,
    _suspicious_gaps,
    generated_subtitle_path,
    normalise_asr_language,
    srt_timestamp,
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
