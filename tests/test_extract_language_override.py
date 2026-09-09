from src.gtmce.core import ExtractItem, extract_item_output_language, rebuild_extract_output_names


def make_audio(language: str, override: str = "") -> ExtractItem:
    return ExtractItem(
        key="track:1",
        kind="track",
        item_id=1,
        label="audio",
        output_name=f"{language}.eac3",
        language=language,
        language_override=override,
        extension="eac3",
        track_type="audio",
    )


def test_extract_language_override_applies_to_known_language():
    item = make_audio("eng", "tr")
    assert extract_item_output_language(item) == "tr"
    rebuild_extract_output_names([item])
    assert item.output_name == "tr.eac3"


def test_extract_language_override_falls_back_to_original_when_blank():
    item = make_audio("eng", "")
    assert extract_item_output_language(item) == "eng"
    rebuild_extract_output_names([item])
    assert item.output_name == "eng.eac3"
