import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.gtmce.core import (
    INTRO_DETECTION_TOP_CANDIDATES,
    ChapterOptions,
    IntroDetectionCandidate,
    select_intro_detection_candidate,
    top_intro_candidates,
    write_auto_chapters_file,
)


class IntroDetectionSelectionTests(unittest.TestCase):
    def test_earliest_dialogue_survives_dense_later_subtitle_shortlist(self):
        candidates = [IntroDetectionCandidate(61.979, 68.7, "subtitle-dialogue")]
        candidates.extend(
            IntroDetectionCandidate(100.0 + index, 70.0 + index, "subtitle-dialogue")
            for index in range(INTRO_DETECTION_TOP_CANDIDATES)
        )

        shortlisted = top_intro_candidates(candidates)

        self.assertEqual(len(shortlisted), INTRO_DETECTION_TOP_CANDIDATES)
        self.assertIn(candidates[0], shortlisted)

    def test_early_black_to_dialogue_transition_beats_later_scene_pause(self):
        # The first sustained dialogue starts during the final seconds of a
        # title-to-picture black transition. A later pause has a higher raw
        # score, but it is already part of the film.
        candidates = [
            IntroDetectionCandidate(61.979, 68.7, "subtitle-dialogue"),
            IntroDetectionCandidate(67.359, 77.0, "blackdetect", 58.976),
            IntroDetectionCandidate(67.359, 34.0, "scenechange"),
            IntroDetectionCandidate(108.651, 96.3, "subtitle-dialogue"),
            IntroDetectionCandidate(108.666, 69.3, "silencedetect"),
            IntroDetectionCandidate(107.941, 39.0, "scenechange"),
        ]

        selected = select_intro_detection_candidate(candidates)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.seconds, 61.979)

    def test_dialogue_before_black_interval_does_not_anchor_that_cut(self):
        candidates = [
            IntroDetectionCandidate(61.979, 68.7, "subtitle-dialogue"),
            IntroDetectionCandidate(67.359, 77.0, "blackdetect", 63.0),
            IntroDetectionCandidate(108.651, 96.3, "subtitle-dialogue"),
            IntroDetectionCandidate(108.666, 69.3, "silencedetect"),
        ]

        selected = select_intro_detection_candidate(candidates)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.seconds, 108.666)

    def test_isolated_early_black_frame_does_not_replace_supported_boundary(self):
        candidates = [
            IntroDetectionCandidate(58.976, 80.0, "blackdetect"),
            IntroDetectionCandidate(108.651, 96.3, "subtitle-dialogue"),
            IntroDetectionCandidate(108.666, 69.3, "silencedetect"),
        ]

        selected = select_intro_detection_candidate(candidates)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.seconds, 108.666)


class AutoChapterTimingTests(unittest.TestCase):
    def make_options(self, start_number: str = "1") -> ChapterOptions:
        return ChapterOptions(
            enabled=True,
            detect_intro=True,
            interval_minutes="10",
            name="Scene",
            start_number=start_number,
            end_minutes="31",
        )

    def chapter_times(self, intro_seconds: float, start_number: str = "1") -> list[str]:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chapters.txt"
            write_auto_chapters_file(
                path,
                self.make_options(start_number),
                duration_seconds=31 * 60,
                intro_start_seconds=intro_seconds,
            )
            return [
                line.split("=", 1)[1]
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("CHAPTER") and "NAME=" not in line
            ]

    def test_detected_intro_keeps_later_chapters_on_ten_minute_grid(self):
        self.assertEqual(
            self.chapter_times(61.979),
            ["00:01:01.979", "00:10:00.000", "00:20:00.000", "00:30:00.000"],
        )

    def test_intro_exactly_on_grid_does_not_duplicate_chapter(self):
        self.assertEqual(
            self.chapter_times(600.0),
            ["00:10:00.000", "00:20:00.000", "00:30:00.000"],
        )

    def test_no_intro_preserves_start_number_based_grid(self):
        self.assertEqual(
            self.chapter_times(0.0, start_number="2"),
            ["00:20:00.000", "00:30:00.000"],
        )
