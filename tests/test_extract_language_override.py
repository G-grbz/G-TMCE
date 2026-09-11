from pathlib import Path
from unittest import mock

from src.gtmce import core
from src.gtmce.core import (
    AppSettings,
    ExtractItem,
    extract_item_output_language,
    normalise_title_for_match,
    rebuild_extract_output_names,
    score_tmdb_result,
    tmdb_search_query_variants,
)


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


def test_tmdb_search_variants_restore_turkish_punctuation_and_sequel_colon():
    query = "Köstebekgiller 2 Gölgenin Tılsımı"

    assert "Köstebekgiller 2: Gölge'nin Tılsımı" in tmdb_search_query_variants(query)
    assert normalise_title_for_match(query) == normalise_title_for_match(
        "Köstebekgiller 2: Gölge'nin Tılsımı"
    )


def test_tmdb_score_uses_original_title_when_result_is_translated():
    result = {
        "id": 1,
        "title": "A translated title",
        "original_title": "Köstebekgiller 2: Gölge'nin Tılsımı",
        "popularity": 1,
    }

    assert score_tmdb_result(result, "Köstebekgiller 2 Gölgenin Tılsımı", "") >= 1000


def test_automatic_tmdb_lookup_tries_official_title_variant():
    media_dir = Path("/tmp/Köstebekgiller 2 Gölgenin Tılsımı")
    settings = AppSettings(
        template_path=None,
        media_dir=media_dir,
        output_path=media_dir / "output.mkv",
        output_name_extra="",
        output_name_year=False,
        api_key="test-key",
        tmdb_id="",
        media_type="movie",
        image_language="tr",
        tag_language="tr",
        mkv_title="",
        video_fps="",
        audio_language_order="",
        subtitle_language_order="",
        include_extra_subtitles=False,
        download_before_mux=False,
        auto_chapters=False,
        auto_chapter_detect_intro=False,
        chapter_interval_minutes="",
        chapter_name="",
        chapter_start_number="",
        chapter_end_minutes="",
    )

    class FakeTMDBClient:
        calls: list[str] = []

        def __init__(self, _api_key: str) -> None:
            pass

        def search(
            self, _media_type: str, query: str, _year: str, language: str = "en-US"
        ) -> list[dict[str, object]]:
            self.calls.append(query)
            assert language == "tr-TR"
            if query == "Köstebekgiller 2: Gölge'nin Tılsımı":
                return [{"id": 123, "title": query, "popularity": 1}]
            return []

    with mock.patch.object(core, "TMDBClient", FakeTMDBClient):
        tmdb_id, title, _year, _query = core.find_tmdb_match_from_folder(settings)

    assert tmdb_id == "123"
    assert title == "Köstebekgiller 2: Gölge'nin Tılsımı"
    assert "Köstebekgiller 2: Gölge'nin Tılsımı" in FakeTMDBClient.calls
