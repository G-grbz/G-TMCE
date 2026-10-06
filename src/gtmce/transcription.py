# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from difflib import SequenceMatcher
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .core import (
    LANG_ALIASES,
    OperationCancelled,
    UserVisibleError,
    app_config_dir,
    ffmpeg_path,
    subprocess_common_kwargs,
    third_party_subprocess_env,
    third_party_subprocess_executable,
    ui_text,
)


DEFAULT_ASR_MODEL = "large-v3"
ASR_RUNTIME_STATE_VERSION = 1

# Per-job subtitle creation profiles used by the UI.  The labels stay in the
# presentation layer; these stable keys let callers choose speed/accuracy for
# each source without changing a global preference.
ASR_QUALITY_PROFILES: dict[str, dict[str, Any]] = {
    "fast": {"model": "turbo", "beam_size": 3, "patience": 1.0, "repetition_penalty": 1.05, "no_repeat_ngram_size": 3},
    "medium": {"model": "medium", "beam_size": 5, "patience": 1.0, "repetition_penalty": 1.06, "no_repeat_ngram_size": 3},
    "slow": {"model": "large-v3", "beam_size": 5, "patience": 1.0, "repetition_penalty": 1.07, "no_repeat_ngram_size": 3},
    # Same acoustic model, but a wider/more patient beam search. Keep the
    # extra search effort bounded: very large beams can cause severe RAM/VRAM
    # pressure on long-form transcription and may trigger the Linux OOM killer.
    # This is intentionally exposed as large-v3+ in the UI rather than
    # pretending that Whisper ships a separate xlarge checkpoint.
    "slower": {"model": "large-v3", "beam_size": 8, "patience": 1.5, "repetition_penalty": 1.08, "no_repeat_ngram_size": 3},
}

# Shared AI subtitle translation profiles.  Both the standalone subtitle
# workflow and Audio Adjust use these same stable keys and the same engine.
AI_TRANSLATION_QUALITY_PROFILES: dict[str, dict[str, Any]] = {
    # Throughput first: large first-pass batches, a small beam and only one
    # conservative retry when QA rejects a span.
    "fast": {
        "batch_size": 32, "beam_size": 2, "repetition_penalty": 1.12,
        "no_repeat_ngram_size": 3, "length_factor": 1.70, "length_extra": 6,
        "retry_attempts": 1, "context_mode": "fail",
    },
    # Default: keeps the fast batch-first architecture but gives suspicious
    # spans a broader retry search.
    "balanced": {
        "batch_size": 24, "beam_size": 3, "repetition_penalty": 1.10,
        "no_repeat_ngram_size": 3, "length_factor": 1.75, "length_extra": 6,
        "retry_attempts": 2, "context_mode": "fail",
    },
    # Accuracy first: smaller batches, wider beam and neighbour-context
    # candidate generation for short dialogue even when the first pass looks
    # structurally valid.  This is intentionally slower.
    "maximum": {
        "batch_size": 12, "beam_size": 4, "repetition_penalty": 1.10,
        "no_repeat_ngram_size": 3, "length_factor": 2.00, "length_extra": 8,
        "retry_attempts": 3, "context_mode": "short_or_fail",
    },
}

def _normalise_translation_quality_profile(value: str | None) -> str:
    key = str(value or "balanced").strip().lower()
    aliases = {"medium": "balanced", "max": "maximum", "quality": "maximum"}
    key = aliases.get(key, key)
    return key if key in AI_TRANSLATION_QUALITY_PROFILES else "balanced"

def _asr_hotwords(_language: str) -> str | None:
    """Return only explicitly user-supplied ASR hotwords.

    Do not ship language-wide lexical hints. In real film dialogue, biasing a
    whole inflection family (for example Turkish ``abi/ağabey`` forms) can make
    Whisper repeat those words even where the acoustics do not support them.
    The environment override remains available for advanced, source-specific
    terminology without imposing a global bias on normal users.
    """
    extra = os.environ.get("GTMCE_ASR_HOTWORDS", "").strip()
    return extra or None


def _normalise_channel_layout_name(channel_layout: str | None) -> str:
    return re.sub(r"\s+", "", str(channel_layout or "").strip().lower())


def _dialogue_mix_filter(channel_layout: str | None) -> str | None:
    """Return an FFmpeg dialogue-focused downmix for center-channel layouts.

    Stereo/mono and layouts without a declared front-center channel are left to
    faster-whisper's normal decoder. For common cinema layouts, favour FC while
    retaining a little FL/FR so deliberately panned dialogue is not lost.
    """
    layout = _normalise_channel_layout_name(channel_layout)
    if not layout:
        return None
    center_layout_prefixes = (
        "3.0", "3.1", "4.0", "4.1",
        "5.0", "5.1", "6.0", "6.1",
        "7.0", "7.1",
    )
    if not layout.startswith(center_layout_prefixes):
        return None
    return "pan=mono|c0=0.80*FC+0.10*FL+0.10*FR"


def _prepare_asr_audio_input(
    audio_path: Path,
    channel_layout: str | None,
    *,
    cancel_event: Any | None,
    logger: Callable[[str], None],
) -> tuple[Path, Path | None]:
    """Prepare a temporary dialogue-focused mono source when appropriate.

    Returns ``(input_path, temporary_path)``. If preprocessing is unavailable or
    fails, ASR safely falls back to the original source.
    """
    layout = _normalise_channel_layout_name(channel_layout)
    mix_filter = _dialogue_mix_filter(layout)
    if mix_filter is None:
        if layout:
            logger(f"G-TMCE ASR audio: layout={layout}; using standard decoder downmix")
        else:
            logger("G-TMCE ASR audio: layout unknown; using standard decoder downmix")
        return audio_path, None

    fd, temp_name = tempfile.mkstemp(prefix="gtmce-asr-dialogue-", suffix=".wav")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        ffmpeg = ffmpeg_path()
        args = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio_path),
            "-map",
            "0:a:0",
            "-af",
            mix_filter,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(temp_path),
        ]
        logger(
            f"G-TMCE ASR audio: layout={layout}; preparing dialogue-focused mono "
            "(FC 80% + FL 10% + FR 10%)"
        )
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=third_party_subprocess_env(),
            executable=third_party_subprocess_executable(args),
            **subprocess_common_kwargs(),
        )
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
                raise OperationCancelled()
            time.sleep(0.1)
        _stdout, stderr = process.communicate()
        if process.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size < 44:
            detail = (stderr or "").strip()
            if detail:
                detail = detail.splitlines()[-1][:240]
                logger(f"G-TMCE ASR audio: dialogue downmix failed; using original audio ({detail})")
            else:
                logger("G-TMCE ASR audio: dialogue downmix failed; using original audio")
            temp_path.unlink(missing_ok=True)
            return audio_path, None
        logger("G-TMCE ASR audio: dialogue-focused mono ready")
        return temp_path, temp_path
    except OperationCancelled:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        logger(f"G-TMCE ASR audio: dialogue downmix unavailable; using original audio ({exc})")
        return audio_path, None


LOCAL_CONTEXT_BLOCK_SECONDS = 120.0
# Boundaries are moved onto nearby VAD-confirmed silence, so only a small
# safety overlap is needed. The previous 3 s hard-boundary overlap could
# decode the same sentence twice when Whisper shifted cue timestamps.
LOCAL_CONTEXT_OVERLAP_SECONDS = 1.0
LOCAL_CONTEXT_BOUNDARY_SEARCH_SECONDS = 12.0
LOCAL_CONTEXT_MIN_SILENCE_SECONDS = 0.55


def _wav_is_pcm_16k_mono(path: Path) -> bool:
    """Return True when *path* is already the PCM format used by ASR blocks."""
    try:
        with wave.open(str(path), "rb") as source:
            return (
                source.getnchannels() == 1
                and source.getsampwidth() == 2
                and source.getframerate() == 16000
                and source.getcomptype() == "NONE"
            )
    except (OSError, wave.Error, EOFError):
        return False


def _prepare_local_context_audio_input(
    audio_path: Path,
    *,
    cancel_event: Any | None,
    logger: Callable[[str], None],
) -> tuple[Path, Path | None]:
    """Ensure local-context decoding reads a seekable 16 kHz mono PCM WAV.

    Blocked transcription intentionally resets Whisper's text prompt between
    blocks.  A small on-disk PCM working file lets us read one block at a time
    without decoding the entire film into RAM, which is important for large-v3
    on memory-constrained Linux systems.
    """
    if _wav_is_pcm_16k_mono(audio_path):
        return audio_path, None

    fd, temp_name = tempfile.mkstemp(prefix="gtmce-asr-context-", suffix=".wav")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        ffmpeg = ffmpeg_path()
        args = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio_path),
            "-map",
            "0:a:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(temp_path),
        ]
        logger("G-TMCE ASR: preparing 16 kHz mono working audio for local-context blocks...")
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=third_party_subprocess_env(),
            executable=third_party_subprocess_executable(args),
            **subprocess_common_kwargs(),
        )
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
                raise OperationCancelled()
            time.sleep(0.1)
        _stdout, stderr = process.communicate()
        if process.returncode != 0 or not _wav_is_pcm_16k_mono(temp_path):
            detail = (stderr or "").strip()
            if detail:
                detail = detail.splitlines()[-1][:240]
            raise RuntimeError(detail or "could not prepare PCM working audio")
        logger("G-TMCE ASR: local-context working audio ready")
        return temp_path, temp_path
    except OperationCancelled:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _local_context_ranges(
    duration: float,
    *,
    block_seconds: float = LOCAL_CONTEXT_BLOCK_SECONDS,
    overlap_seconds: float = LOCAL_CONTEXT_OVERLAP_SECONDS,
) -> list[tuple[float, float, float, float]]:
    """Return ``(start, end, keep_start, keep_end)`` ranges for local context.

    Adjacent decode blocks overlap so words near a hard boundary are heard in
    full by at least one block.  The keep-range splits that overlap at its
    midpoint, preventing duplicate cues while preserving continuous coverage.
    """
    duration = max(0.0, float(duration))
    block_seconds = max(30.0, float(block_seconds))
    overlap_seconds = max(0.0, min(float(overlap_seconds), block_seconds / 4.0))
    if duration <= 0.0:
        return []
    if duration <= block_seconds:
        return [(0.0, duration, 0.0, duration)]

    step = block_seconds - overlap_seconds
    starts: list[float] = []
    start = 0.0
    while start < duration:
        starts.append(start)
        if start + block_seconds >= duration:
            break
        start += step

    ranges: list[tuple[float, float, float, float]] = []
    half_overlap = overlap_seconds / 2.0
    for index, start in enumerate(starts):
        end = min(duration, start + block_seconds)
        keep_start = start if index == 0 else min(end, start + half_overlap)
        keep_end = end if index == len(starts) - 1 else max(keep_start, end - half_overlap)
        ranges.append((start, end, keep_start, keep_end))
    return ranges


def _choose_vad_silence_boundary(
    target: float,
    window_start: float,
    window_end: float,
    speech_ranges: Iterable[tuple[float, float]],
    *,
    min_silence_seconds: float = LOCAL_CONTEXT_MIN_SILENCE_SECONDS,
) -> float:
    """Move a nominal block boundary onto nearby VAD-confirmed silence."""
    window_start = float(window_start)
    window_end = max(window_start, float(window_end))
    target = min(window_end, max(window_start, float(target)))
    min_silence_seconds = max(0.1, float(min_silence_seconds))

    merged: list[tuple[float, float]] = []
    for start, end in sorted((float(a), float(b)) for a, b in speech_ranges):
        start = max(window_start, start)
        end = min(window_end, end)
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + 0.02:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    gaps: list[tuple[float, float]] = []
    cursor = window_start
    for start, end in merged:
        if start - cursor >= min_silence_seconds:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if window_end - cursor >= min_silence_seconds:
        gaps.append((cursor, window_end))
    if not gaps:
        return target

    best_point = target
    best_score: tuple[float, float] | None = None
    for gap_start, gap_end in gaps:
        gap_length = gap_end - gap_start
        margin = min(0.20, gap_length / 4.0)
        safe_start = gap_start + margin
        safe_end = gap_end - margin
        if safe_end < safe_start:
            safe_start = safe_end = (gap_start + gap_end) / 2.0
        point = min(safe_end, max(safe_start, target))
        score = (abs(point - target), -gap_length)
        if best_score is None or score < best_score:
            best_score = score
            best_point = point
    return best_point


def _vad_aligned_context_boundaries(
    source: wave.Wave_read,
    duration: float,
    *,
    block_seconds: float = LOCAL_CONTEXT_BLOCK_SECONDS,
    search_seconds: float = LOCAL_CONTEXT_BOUNDARY_SEARCH_SECONDS,
    cancel_event: Any | None = None,
    logger: Callable[[str], None] | None = None,
) -> list[float]:
    """Find ~2 minute boundaries near real VAD silence without loading the film."""
    duration = max(0.0, float(duration))
    block_seconds = max(30.0, float(block_seconds))
    search_seconds = max(2.0, min(float(search_seconds), block_seconds / 3.0))
    if duration <= block_seconds:
        return []

    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps  # type: ignore
    except Exception:
        return [
            point
            for point in (block_seconds * index for index in range(1, int(duration // block_seconds) + 1))
            if 30.0 <= point <= duration - 30.0
        ]

    sampling_rate = int(source.getframerate())
    boundaries: list[float] = []
    previous = 0.0
    target = block_seconds
    shifted = 0
    max_shift = 0.0
    while target < duration - 30.0:
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled()
        window_start = max(previous + 45.0, target - search_seconds)
        window_end = min(duration - 30.0, target + search_seconds)
        if window_end <= window_start:
            boundary = target
        else:
            clip = _read_pcm_wav_range(source, window_start, window_end)
            speech_ranges: list[tuple[float, float]] = []
            if getattr(clip, "size", 0) > 0:
                chunks = get_speech_timestamps(
                    clip,
                    VadOptions(
                        threshold=0.30,
                        min_speech_duration_ms=120,
                        min_silence_duration_ms=500,
                        speech_pad_ms=120,
                    ),
                )
                for chunk in chunks:
                    start = window_start + float(chunk["start"]) / sampling_rate
                    end = window_start + float(chunk["end"]) / sampling_rate
                    speech_ranges.append((start, end))
            boundary = _choose_vad_silence_boundary(
                target,
                window_start,
                window_end,
                speech_ranges,
            )
        boundary = min(target + search_seconds, max(target - search_seconds, boundary))
        boundary = max(previous + 45.0, boundary)
        if duration - boundary < 30.0:
            break
        shift = abs(boundary - target)
        if shift >= 0.05:
            shifted += 1
            max_shift = max(max_shift, shift)
        boundaries.append(boundary)
        previous = boundary
        target = boundary + block_seconds

    if logger is not None and boundaries:
        logger(
            "G-TMCE ASR: VAD-aligned "
            f"{shifted}/{len(boundaries)} context boundary(s) to nearby silence "
            f"(max shift {max_shift:.1f}s)"
        )
    return boundaries


def _local_context_ranges_from_boundaries(
    duration: float,
    boundaries: Iterable[float],
    *,
    overlap_seconds: float = LOCAL_CONTEXT_OVERLAP_SECONDS,
) -> list[tuple[float, float, float, float]]:
    """Build decode/ownership ranges around silence-aligned core boundaries."""
    duration = max(0.0, float(duration))
    if duration <= 0.0:
        return []
    cleaned = sorted({
        min(duration, max(0.0, float(point)))
        for point in boundaries
        if 0.0 < float(point) < duration
    })
    cores = [0.0, *cleaned, duration]
    overlap_seconds = max(0.0, float(overlap_seconds))
    half = overlap_seconds / 2.0
    ranges: list[tuple[float, float, float, float]] = []
    for index in range(len(cores) - 1):
        keep_start = cores[index]
        keep_end = cores[index + 1]
        decode_start = keep_start if index == 0 else max(0.0, keep_start - half)
        decode_end = keep_end if index == len(cores) - 2 else min(duration, keep_end + half)
        ranges.append((decode_start, decode_end, keep_start, keep_end))
    return ranges


def _normalise_cue_compare_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9çğıöşü]+", " ", text).strip()


def _deduplicate_boundary_cues(
    cues: Iterable[SubtitleCue],
    boundaries: Iterable[float],
    *,
    boundary_margin: float = 4.0,
    logger: Callable[[str], None] | None = None,
) -> list[SubtitleCue]:
    """Remove near-identical overlapping cues created around block boundaries."""
    boundary_points = [float(point) for point in boundaries]
    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    result: list[SubtitleCue] = []
    removed = 0
    for cue in ordered:
        duplicate_index: int | None = None
        cue_mid = (cue.start + cue.end) / 2.0
        near_boundary = any(abs(cue_mid - point) <= boundary_margin for point in boundary_points)
        if near_boundary:
            cue_norm = _normalise_cue_compare_text(cue.text)
            for index in range(len(result) - 1, -1, -1):
                existing = result[index]
                if existing.end < cue.start - 0.25:
                    break
                existing_mid = (existing.start + existing.end) / 2.0
                if not any(abs(existing_mid - point) <= boundary_margin for point in boundary_points):
                    continue
                overlap = min(cue.end, existing.end) - max(cue.start, existing.start)
                shorter = min(cue.end - cue.start, existing.end - existing.start)
                if overlap <= 0.0 or shorter <= 0.0 or overlap / shorter < 0.30:
                    continue
                existing_norm = _normalise_cue_compare_text(existing.text)
                if not cue_norm or not existing_norm:
                    continue
                if min(len(cue_norm), len(existing_norm)) < 12:
                    similar = cue_norm == existing_norm
                else:
                    similar = SequenceMatcher(None, cue_norm, existing_norm).ratio() >= 0.72
                if similar:
                    duplicate_index = index
                    break
        if duplicate_index is None:
            result.append(cue)
            continue
        existing = result[duplicate_index]
        existing_score = (len(_normalise_cue_compare_text(existing.text)), existing.end - existing.start)
        cue_score = (len(_normalise_cue_compare_text(cue.text)), cue.end - cue.start)
        if cue_score > existing_score:
            result[duplicate_index] = cue
        removed += 1
    if logger is not None and removed:
        logger(f"G-TMCE ASR: removed {removed} duplicate cue(s) near context boundaries")
    return sorted(result, key=lambda cue: (cue.start, cue.end))


def _read_pcm_wav_range(source: wave.Wave_read, start: float, end: float) -> Any:
    """Read one mono PCM WAV range as the float32 array faster-whisper expects."""
    import numpy as np

    sampling_rate = source.getframerate()
    start_frame = max(0, int(round(start * sampling_rate)))
    end_frame = min(source.getnframes(), int(round(end * sampling_rate)))
    source.setpos(start_frame)
    raw = source.readframes(max(0, end_frame - start_frame))
    if not raw:
        return np.empty((0,), dtype=np.float32)
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    audio *= 1.0 / 32768.0
    return audio

# Multilingual, local translation model. MADLAD-400 uses a <2xx> target
# language prefix and does not require a source-language-specific checkpoint.
# The CT2 INT8 conversion keeps runtime memory reasonable while preserving a
# single model for all UI target languages. The upstream model is Apache-2.0.
DEFAULT_TRANSLATION_MODEL = "Nextcloud-AI/madlad400-3b-mt-ct2-int8"
TRANSLATION_MODEL_DOWNLOAD_BYTES = 2_980_000_000
TRANSLATION_MODEL_FILES = (
    "config.json",
    "model.bin",
    "shared_vocabulary.json",
    "spiece.model",
    "sentencepiece.model",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "generation_config.json",
)

# Stable target-language menu. MADLAD supports substantially more languages,
# but this curated set covers the languages G-TMCE is most likely to encounter
# while keeping the picker useful instead of overwhelming. Adding another
# MADLAD <2xx> language later only requires extending this table.
TRANSLATION_TARGET_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("tr", "Türkçe"),
    ("en", "English"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("pt", "Português"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    # Keep picker labels in a Latin script. Some Linux Qt builds emit a very
    # large amount of ``qt.text.font.db: OpenType support missing`` noise when
    # the combo box previews many writing systems at once. The target codes are
    # unchanged; these are display labels only.
    ("ru", "Rusça"),
    ("uk", "Ukraynaca"),
    ("ar", "Arapça"),
    ("fa", "Farsça"),
    ("he", "İbranice"),
    ("zh", "Çince"),
    ("ja", "Japonca"),
    ("ko", "Korece"),
    ("hi", "Hintçe"),
    ("bn", "Bengalce"),
    ("ur", "Urduca"),
    ("el", "Yunanca"),
    ("cs", "Čeština"),
    ("sk", "Slovenčina"),
    ("hu", "Magyar"),
    ("ro", "Română"),
    ("bg", "Български"),
    ("sr", "Srpski"),
    ("hr", "Hrvatski"),
    ("bs", "Bosanski"),
    ("sl", "Slovenščina"),
    ("mk", "Македонски"),
    ("sq", "Shqip"),
    ("sv", "Svenska"),
    ("no", "Norsk"),
    ("da", "Dansk"),
    ("fi", "Suomi"),
    ("is", "Íslenska"),
    ("et", "Eesti"),
    ("lv", "Latviešu"),
    ("lt", "Lietuvių"),
    ("id", "Bahasa Indonesia"),
    ("ms", "Bahasa Melayu"),
    ("vi", "Tiếng Việt"),
    ("th", "ไทย"),
    ("tl", "Filipino"),
    ("sw", "Kiswahili"),
    ("az", "Azərbaycanca"),
    ("hy", "Ermenice"),
    ("ka", "Gürcüce"),
    ("kk", "Kazakça"),
    ("uz", "O‘zbekcha"),
    ("mn", "Moğolca"),
    ("ta", "Tamilce"),
    ("te", "Teluguca"),
    ("mr", "Marathice"),
    ("gu", "Guceratça"),
    ("pa", "Pencapça"),
    ("ne", "Nepalce"),
    ("my", "Birmanca"),
    ("ca", "Català"),
    ("eu", "Euskara"),
    ("gl", "Galego"),
    ("cy", "Cymraeg"),
)
TRANSLATION_TARGET_CODES = {code for code, _name in TRANSLATION_TARGET_LANGUAGES}

# Approximate on-disk model payload sizes used only for first-download progress.
# The turbo CT2 model is ~1.62 GB on Hugging Face.
MODEL_DOWNLOAD_BYTES = {
    "turbo": 1_625_000_000,
    "large-v3-turbo": 1_625_000_000,
    "medium": 1_500_000_000,
    # Keep this approximate: it is used only for a friendly first-download log.
    "large-v3": 3_100_000_000,
}


SUPPORTED_ASR_LANGUAGES = {
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "zh", "yue",
}


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class _TranslationUnit:
    """Text translated with shared context while preserving source cue timing."""

    cues: tuple[SubtitleCue, ...]
    text: str

    @property
    def start(self) -> float:
        return self.cues[0].start

    @property
    def end(self) -> float:
        return self.cues[-1].end


def normalise_asr_language(language: str) -> str:
    value = str(language or "").strip().lower()
    if "-" in value:
        value = value.split("-", 1)[0]
    value = LANG_ALIASES.get(value, value)
    if not value or value == "und":
        raise UserVisibleError(ui_text("error_asr_language_unknown"))
    if value not in SUPPORTED_ASR_LANGUAGES:
        raise UserVisibleError(ui_text("error_asr_language_unsupported", language=language))
    return value


def generated_subtitle_path(audio_path: Path, language: str) -> Path:
    """Return a non-destructive subtitle name next to the audio track.

    G-TMCE understands language tokens in filenames.  Keeping ``.<lang>.`` in
    the generated name lets normal track discovery classify the subtitle
    without modifying the template configuration.
    """
    audio_path = Path(audio_path)
    language = normalise_asr_language(language)
    stem = audio_path.stem
    tokens = [token for token in re.split(r"[._\-\s()]+", stem.lower()) if token]
    token_languages = {LANG_ALIASES.get(token, token) for token in tokens}
    if language in token_languages:
        return audio_path.with_name(f"{stem}.generated.srt")
    return audio_path.with_name(f"{stem}.{language}.generated.srt")


def generated_translation_path(audio_path: Path, target_language: str = "tr") -> Path:
    """Return the translated subtitle path without replacing the source-language SRT."""
    return generated_subtitle_path(audio_path, target_language)


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _translation_text_wrapper(text: str) -> tuple[str, str, str]:
    """Detach common subtitle presentation wrappers before machine translation.

    Translators are not reliable custodians of markup.  For the common cases
    produced by extracted subtitles -- SDH cues such as ``[door closes]`` and
    fully italic dialogue such as ``<i>Hello</i>`` -- translate only the visible
    payload and restore the wrapper afterwards.  Nested combinations are handled
    iteratively, e.g. ``<i>[whispers]</i>``.
    """
    payload = _clean_text(text)
    prefix = ""
    suffix = ""
    while payload:
        italic = re.fullmatch(r"(?is)<i>(.*?)</i>", payload)
        if italic is not None:
            prefix += "<i>"
            suffix = "</i>" + suffix
            payload = _clean_text(italic.group(1))
            continue
        sdh = re.fullmatch(r"(?s)\[(.*?)\]", payload)
        if sdh is not None:
            prefix += "["
            suffix = "]" + suffix
            payload = _clean_text(sdh.group(1))
            continue
        break
    return payload, prefix, suffix


def _restore_translation_wrapper(text: str, prefix: str, suffix: str) -> str:
    clean = _clean_text(text)
    return f"{prefix}{clean}{suffix}" if clean else ""


def _has_translation_wrapper(text: str) -> bool:
    payload, prefix, suffix = _translation_text_wrapper(text)
    return bool(payload and (prefix or suffix))


def _normalise_hallucination_text(text: str) -> str:
    """Normalise ASR text for conservative hallucination checks.

    This deliberately removes punctuation but keeps words.  We only use the
    result to recognise subtitle-credit boilerplate and obvious fragments; it
    is never written back to the subtitle.
    """
    value = _clean_text(text).casefold().replace("ı", "i")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _hallucination_reason(cue: SubtitleCue) -> str | None:
    """Return a reason when a cue is very likely Whisper boilerplate/noise.

    The checks are intentionally conservative.  Ordinary dialogue is retained
    even when it contains words such as "altyazı" or "teşekkür"; removal
    requires a credit-shaped phrase, an unreadably short multi-word cue, or an
    impossible reading speed on a very short cue.
    """
    text = _clean_text(cue.text)
    if not text:
        return "empty"
    duration = max(0.0, float(cue.end) - float(cue.start))
    normalised = _normalise_hallucination_text(text)
    tokens = normalised.split()

    # Classic Whisper subtitle-credit hallucinations.  Examples seen in the
    # supplied film include "Altyazı M.K.", "Altyazı M" and a detached ".K.".
    if tokens and tokens[0] in {"altyazi", "subtitle", "subtitles", "caption", "captions"}:
        tail = tokens[1:]
        if not tail:
            return "subtitle-credit"
        if len(tail) <= 4 and all(len(token) == 1 for token in tail):
            return "subtitle-credit"
        if tail and tail[0] in {"by", "ceviri", "translation", "translated", "sync", "synced"}:
            return "subtitle-credit"
        if "amara" in tail and "community" in tail:
            return "subtitle-credit"

    if tokens and tokens[0] in {"ceviri", "translation", "translated"}:
        tail = tokens[1:]
        if tail and (tail[0] == "by" or (len(tail) <= 4 and all(len(token) == 1 for token in tail))):
            return "subtitle-credit"

    # Punctuation-wrapped isolated letter fragments such as ".K." that appear
    # when a credit hallucination is split by word timestamps.
    if duration <= 1.25 and len(normalised) == 1:
        punctuation = sum(1 for char in text if not char.isalnum() and not char.isspace())
        if punctuation >= 2:
            return "orphan-fragment"

    compact_chars = len(re.sub(r"\s+", "", text))
    word_count = len(tokens)

    # Multi-word speech cannot realistically occupy only a few video frames.
    # Keep tiny interjections ("Ah!", "Ha?") but reject substantial text.
    if duration < 0.18 and word_count >= 2 and compact_chars >= 8:
        return "impossible-duration"

    # Generic creator/outro boilerplate is a common silence/music hallucination,
    # but the same sentence could exist in real dialogue.  Only reject it when
    # Whisper also squeezed it into an implausibly short cue.
    outro_phrases = {
        "izlediginiz icin tesekkur ederim",
        "izlediginiz icin tesekkurler",
        "thank you for watching",
        "thanks for watching",
        "merci d avoir regarde",
        "danke furs zuschauen",
        "gracias por ver",
    }
    if normalised in outro_phrases:
        # Whisper frequently emits these stock creator/outro phrases over the
        # opening silence/music of films.  The supplied Turkish sample produced
        # exactly "İzlediğiniz için teşekkür ederim." at 00:00:02 even though
        # no dialogue exists there.  Keep the old impossible-speed guard for
        # arbitrary positions, and additionally reject an exact stock phrase
        # near the beginning of the programme.
        if 0.0 <= float(cue.start) < 8.0 and duration < 4.0:
            return "outro-boilerplate"
        if duration > 0 and duration < 1.50:
            chars_per_second = compact_chars / duration
            if chars_per_second > 24.0:
                return "outro-boilerplate"

    # Reserve the generic speed rejection for truly extreme cases.  This keeps
    # fast arguments/dialogue while still rejecting text that cannot possibly
    # fit its word timestamps.
    if duration > 0 and duration < 0.75 and word_count >= 5:
        chars_per_second = compact_chars / duration
        if chars_per_second > 55.0:
            return "impossible-reading-speed"

    return None


def _filter_hallucinated_cues(
    cues: Iterable[SubtitleCue],
    *,
    logger: Callable[[str], None] | None = None,
    stage: str = "final",
) -> list[SubtitleCue]:
    """Remove high-confidence ASR hallucinations while preserving dialogue."""
    kept: list[SubtitleCue] = []
    counts: dict[str, int] = {}
    for cue in cues:
        reason = _hallucination_reason(cue)
        if reason is None:
            kept.append(cue)
            continue
        counts[reason] = counts.get(reason, 0) + 1

    if logger is not None and counts:
        total = sum(counts.values())
        detail = ", ".join(f"{reason}={count}" for reason, count in sorted(counts.items()))
        logger(f"G-TMCE ASR: hallucination cleanup ({stage}) removed {total} cue(s): {detail}")
    return kept


def _filter_repetition_loops(
    cues: Iterable[SubtitleCue],
    *,
    logger: Callable[[str], None] | None = None,
    stage: str = "final",
) -> list[SubtitleCue]:
    """Remove high-confidence long-form Whisper repetition loops.

    Long recordings can make Whisper latch onto a short sentence and emit it
    again for unrelated audio.  We only flag a region when the *same*
    multi-word phrase appears at least six times with no more than 30 seconds
    between occurrences and the cluster spans at least eight seconds.  The
    whole contaminated interval is removed so the existing gap-rescue pass can
    decode that audio again independently without previous-text conditioning.
    """
    cue_list = list(cues)
    if len(cue_list) < 6:
        return cue_list

    occurrences: dict[str, list[tuple[int, SubtitleCue]]] = {}
    for index, cue in enumerate(cue_list):
        normalised = _normalise_hallucination_text(cue.text)
        tokens = normalised.split()
        token_count = len(tokens)
        if not (1 <= token_count <= 10) or len(normalised) > 100:
            continue
        # Single-word loops need a higher bar because real dialogue can repeat
        # short interjections. Ignore tiny words such as "ha"/"ne" entirely.
        if token_count == 1 and len(normalised) < 5:
            continue
        occurrences.setdefault(normalised, []).append((index, cue))

    bad_windows: list[tuple[float, float, str, int]] = []
    for phrase, items in occurrences.items():
        cluster: list[tuple[int, SubtitleCue]] = []
        required_count = 8 if len(phrase.split()) == 1 else 6
        required_span = 10.0 if len(phrase.split()) == 1 else 8.0
        for item in items:
            cue = item[1]
            if not cluster or cue.start - cluster[-1][1].start <= 30.0:
                cluster.append(item)
            else:
                if len(cluster) >= required_count:
                    start = cluster[0][1].start
                    end = cluster[-1][1].end
                    if end - start >= required_span:
                        bad_windows.append((start, end, phrase, len(cluster)))
                cluster = [item]
        if len(cluster) >= required_count:
            start = cluster[0][1].start
            end = cluster[-1][1].end
            if end - start >= required_span:
                bad_windows.append((start, end, phrase, len(cluster)))

    if not bad_windows:
        return cue_list

    # Merge overlapping contaminated windows before filtering.
    merged: list[tuple[float, float]] = []
    for start, end, _phrase, _count in sorted(bad_windows):
        start = max(0.0, start - 0.35)
        end += 0.35
        if merged and start <= merged[-1][1] + 0.5:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    kept = [
        cue for cue in cue_list
        if not any(cue.start < end and cue.end > start for start, end in merged)
    ]
    if logger is not None:
        removed = len(cue_list) - len(kept)
        examples = ", ".join(
            f"'{phrase[:36]}' x{count}" for _s, _e, phrase, count in bad_windows[:3]
        )
        logger(
            f"G-TMCE ASR: repetition-loop cleanup ({stage}) removed {removed} cue(s) "
            f"across {len(merged)} region(s) ({examples})"
        )
    return kept


def _wrap_subtitle_text(text: str, width: int = 42) -> str:
    clean = _clean_text(text)
    if not clean:
        return ""
    lines = textwrap.wrap(
        clean,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(lines) <= 2:
        return "\n".join(lines)
    # Cue construction normally keeps text below two lines.  This fallback
    # preserves all text if a model returns an unusually long single token.
    midpoint = max(1, len(clean) // 2)
    split_at = clean.rfind(" ", 0, midpoint + 1)
    if split_at <= 0:
        split_at = clean.find(" ", midpoint)
    if split_at <= 0:
        return clean
    return clean[:split_at].strip() + "\n" + clean[split_at:].strip()


def _word_value(word: Any, key: str, default: Any = None) -> Any:
    if isinstance(word, dict):
        return word.get(key, default)
    return getattr(word, key, default)


def _cues_from_words(words: Iterable[Any]) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    current: list[Any] = []
    max_chars = 84
    max_duration = 6.0

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = _clean_text("".join(str(_word_value(word, "word", "")) for word in current))
        starts = [float(_word_value(word, "start")) for word in current if _word_value(word, "start") is not None]
        ends = [float(_word_value(word, "end")) for word in current if _word_value(word, "end") is not None]
        if text and starts and ends:
            cues.append(SubtitleCue(min(starts), max(ends), _wrap_subtitle_text(text)))
        current = []

    for word in words:
        text = str(_word_value(word, "word", ""))
        start = _word_value(word, "start")
        end = _word_value(word, "end")
        if not text.strip() or start is None or end is None:
            continue
        candidate = current + [word]
        candidate_text = _clean_text("".join(str(_word_value(item, "word", "")) for item in candidate))
        first_start = float(_word_value(candidate[0], "start"))
        duration = float(end) - first_start
        previous_text = str(_word_value(current[-1], "word", "")) if current else ""
        sentence_break = bool(current and re.search(r"[.!?…][\"'”’)]?$", previous_text.strip()))
        if current and (
            len(candidate_text) > max_chars
            or duration > max_duration
            or (sentence_break and len(_clean_text("".join(str(_word_value(item, "word", "")) for item in current))) >= 24)
        ):
            flush()
        current.append(word)
    flush()
    return cues


def cues_from_segments(segments: Iterable[Any]) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    for segment in segments:
        words = getattr(segment, "words", None)
        if words:
            word_cues = _cues_from_words(words)
            if word_cues:
                cues.extend(word_cues)
                continue
        text = _clean_text(getattr(segment, "text", ""))
        start = getattr(segment, "start", None)
        end = getattr(segment, "end", None)
        if text and start is not None and end is not None:
            cues.append(SubtitleCue(float(start), float(end), _wrap_subtitle_text(text)))
    return cues



def _suspicious_gaps(cues: Iterable[SubtitleCue], duration: float, minimum_gap: float = 30.0) -> list[tuple[float, float]]:
    """Return long uncovered regions worth a second, more sensitive VAD scan.

    Long stretches without subtitles can be perfectly valid in a film, so this
    function only marks candidates.  The rescue pass still requires Silero VAD
    to detect speech-like audio before Whisper is asked to decode anything.
    """
    ordered = sorted((cue for cue in cues if cue.end > cue.start), key=lambda cue: cue.start)
    if duration <= 0:
        return []
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for cue in ordered:
        start = max(0.0, float(cue.start))
        if start - cursor >= minimum_gap:
            gaps.append((cursor, start))
        cursor = max(cursor, float(cue.end))
    if duration - cursor >= minimum_gap:
        gaps.append((cursor, duration))
    return gaps


def _merge_cues(primary: Iterable[SubtitleCue], rescued: Iterable[SubtitleCue]) -> list[SubtitleCue]:
    """Merge a rescue pass without duplicating already-covered dialogue."""
    merged = list(primary)
    for cue in rescued:
        if not cue.text.strip() or cue.end <= cue.start:
            continue
        # Ignore a rescue cue when it substantially overlaps an existing cue.
        duplicate = False
        for existing in merged:
            overlap = min(cue.end, existing.end) - max(cue.start, existing.start)
            if overlap > 0 and overlap >= min(cue.end - cue.start, existing.end - existing.start) * 0.45:
                duplicate = True
                break
        if not duplicate:
            merged.append(cue)
    merged.sort(key=lambda cue: (cue.start, cue.end))
    return merged


def _group_speech_windows(
    speech_chunks: Iterable[dict[str, int]],
    sampling_rate: int,
    gap_ranges: Iterable[tuple[float, float]],
    *,
    join_gap: float = 0.8,
    max_window: float = 28.0,
) -> list[tuple[float, float]]:
    """Turn relaxed-VAD speech chunks inside suspicious gaps into short windows."""
    ranges = list(gap_ranges)
    candidates: list[tuple[float, float]] = []
    for chunk in speech_chunks:
        start = float(chunk["start"]) / sampling_rate
        end = float(chunk["end"]) / sampling_rate
        if end <= start:
            continue
        if not any(start < gap_end and end > gap_start for gap_start, gap_end in ranges):
            continue
        candidates.append((start, end))

    windows: list[tuple[float, float]] = []
    for start, end in sorted(candidates):
        if not windows:
            windows.append((start, end))
            continue
        prev_start, prev_end = windows[-1]
        if start - prev_end <= join_gap and end - prev_start <= max_window:
            windows[-1] = (prev_start, max(prev_end, end))
        else:
            windows.append((start, end))
    return windows

def write_srt(path: Path, cues: Iterable[SubtitleCue]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for index, cue in enumerate(cues, start=1):
        if not cue.text.strip() or cue.end <= cue.start:
            continue
        parts.append(
            f"{index}\n{srt_timestamp(cue.start)} --> {srt_timestamp(cue.end)}\n{cue.text.strip()}\n"
        )
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(parts), encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return path


def asr_model_cache_dir() -> Path:
    override = os.environ.get("GTMCE_ASR_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "G-TMCE" / "models"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "G-TMCE" / "models"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "G-TMCE" / "models"


def asr_runtime_state_path() -> Path:
    override = os.environ.get("GTMCE_ASR_RUNTIME_STATE", "").strip()
    if override:
        return Path(override).expanduser()
    return app_config_dir() / "asr-runtime.json"


def _read_asr_runtime_state() -> dict[str, Any]:
    path = asr_runtime_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict) or data.get("version") != ASR_RUNTIME_STATE_VERSION:
        return {}
    return data


def _write_asr_runtime_state(data: dict[str, Any]) -> None:
    path = asr_runtime_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["version"] = ASR_RUNTIME_STATE_VERSION
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _saved_runtime() -> tuple[str, str] | None:
    state = _read_asr_runtime_state()
    runtime = state.get("runtime")
    if not isinstance(runtime, dict):
        return None
    device = str(runtime.get("device", "")).strip().lower()
    compute_type = str(runtime.get("compute_type", "")).strip().lower()
    if device not in {"cuda", "cpu"} or not compute_type:
        return None
    return device, compute_type


def _remember_runtime(device: str, compute_type: str) -> None:
    state = _read_asr_runtime_state()
    state["runtime"] = {
        "device": str(device).strip().lower(),
        "compute_type": str(compute_type).strip().lower(),
    }
    _write_asr_runtime_state(state)


def _saved_model_snapshot(model_name: str) -> Path | None:
    state = _read_asr_runtime_state()
    models = state.get("models")
    if not isinstance(models, dict):
        return None
    raw = models.get(model_name)
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def _remember_model_snapshot(model_name: str, path: Path) -> None:
    state = _read_asr_runtime_state()
    models = state.get("models")
    if not isinstance(models, dict):
        models = {}
    models[str(model_name)] = str(Path(path).expanduser().resolve())
    state["models"] = models
    _write_asr_runtime_state(state)


def _best_cuda_compute_type() -> str | None:
    """Return a compute type that CTranslate2 says is efficient on GPU 0.

    Do not assume every CUDA-capable NVIDIA GPU has efficient FP16. Older
    architectures (for example some Pascal cards) can expose CUDA while
    CTranslate2 correctly rejects float16. Prefer full FP16 when available,
    then GPU quantized modes, and finally float32.
    """
    try:
        import ctranslate2  # type: ignore

        if int(ctranslate2.get_cuda_device_count()) <= 0:
            return None
        supported = set(ctranslate2.get_supported_compute_types("cuda", 0))
    except Exception:
        return None

    for compute_type in ("float16", "int8_float16", "int8_float32", "int8", "float32"):
        if compute_type in supported:
            return compute_type
    return None


def _runtime_device(logger: Callable[[str], None] | None = None) -> tuple[str, str, bool]:
    requested = os.environ.get("GTMCE_ASR_DEVICE", "auto").strip().lower() or "auto"
    requested_compute = os.environ.get("GTMCE_ASR_COMPUTE_TYPE", "").strip().lower()

    # Explicit environment overrides always win and are not replaced by the
    # persisted auto-detected runtime.
    if requested != "auto" or requested_compute:
        if requested == "cpu":
            return "cpu", requested_compute or "int8", False
        cuda_compute = _best_cuda_compute_type()
        if requested == "cuda":
            return "cuda", requested_compute or cuda_compute or "auto", False
        if cuda_compute:
            return "cuda", requested_compute or cuda_compute, False
        return "cpu", requested_compute or "int8", False

    saved = _saved_runtime()
    if saved is not None:
        if logger is not None:
            logger(f"G-TMCE ASR: using saved runtime {saved[0]}/{saved[1]}")
        return saved[0], saved[1], True

    cuda_compute = _best_cuda_compute_type()
    if cuda_compute:
        return "cuda", cuda_compute, False
    return "cpu", "int8", False


def _format_bytes(value: int) -> str:
    value = max(0, int(value))
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024.0
    return f"{value} B"


def _parse_linux_meminfo(text: str) -> dict[str, int]:
    """Parse /proc/meminfo into byte values without requiring psutil."""
    values: dict[str, int] = {}
    for raw_line in str(text or "").splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        try:
            amount = int(parts[0])
        except ValueError:
            continue
        # Linux reports these fields in KiB. Keep a defensive fallback for any
        # future/unit-less fields so the logger can never break transcription.
        multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
        values[key.strip()] = amount * multiplier
    return values


def _linux_memory_snapshot() -> dict[str, int] | None:
    try:
        meminfo = _parse_linux_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None
    total = int(meminfo.get("MemTotal", 0))
    available = int(meminfo.get("MemAvailable", meminfo.get("MemFree", 0)))
    if total <= 0:
        return None
    swap_total = int(meminfo.get("SwapTotal", 0))
    swap_free = int(meminfo.get("SwapFree", 0))
    return {
        "total": total,
        "available": max(0, available),
        "used": max(0, total - available),
        "swap_total": max(0, swap_total),
        "swap_used": max(0, swap_total - swap_free),
    }


def _process_rss_bytes() -> int | None:
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = re.search(r"^VmRSS:\s+(\d+)\s+kB\s*$", status, flags=re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1)) * 1024


def _nvidia_resource_snapshot() -> dict[str, Any] | None:
    """Best-effort NVIDIA status via nvidia-smi; never a runtime dependency."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
                "-i",
                "0",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        fields = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
        if len(fields) < 4:
            return None
        name = fields[0]
        used_mib = float(fields[1])
        total_mib = float(fields[2])
        util = float(fields[3])
        process_mib: float | None = None
        process_result = subprocess.run(
            [
                executable,
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if process_result.returncode == 0:
            current_pid = os.getpid()
            for line in process_result.stdout.splitlines():
                parts = [part.strip() for part in line.split(",")]
                if len(parts) < 2:
                    continue
                try:
                    if int(parts[0]) == current_pid:
                        process_mib = float(parts[1])
                        break
                except ValueError:
                    continue
        return {
            "name": name,
            "used": int(used_mib * 1024 * 1024),
            "total": int(total_mib * 1024 * 1024),
            "util": util,
            "process_used": None if process_mib is None else int(process_mib * 1024 * 1024),
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _asr_resource_log_lines(
    device: str,
    compute_type: str,
    *,
    large_profile: bool = False,
) -> list[str]:
    """Return concise RAM/VRAM status lines plus non-fatal pressure warnings."""
    lines: list[str] = []
    memory = _linux_memory_snapshot()
    rss = _process_rss_bytes()
    if memory is not None:
        process_part = f"process={_format_bytes(rss)} | " if rss is not None else ""
        lines.append(
            "G-TMCE ASR resources: RAM "
            f"{process_part}system={_format_bytes(memory['used'])}/{_format_bytes(memory['total'])} "
            f"| available={_format_bytes(memory['available'])} "
            f"| swap={_format_bytes(memory['swap_used'])}/{_format_bytes(memory['swap_total'])}"
        )
        available = memory["available"]
        if available < int(1.5 * 1024**3):
            lines.append(
                "G-TMCE ASR WARNING: available RAM is critical "
                f"({_format_bytes(available)}); Linux may invoke the OOM killer."
            )
        elif available < 3 * 1024**3:
            lines.append(
                "G-TMCE ASR WARNING: available RAM is low "
                f"({_format_bytes(available)}); monitor memory pressure."
            )
        if large_profile and memory["swap_total"] == 0:
            lines.append(
                "G-TMCE ASR WARNING: swap is disabled; large-v3/large-v3+ has less "
                "protection against sudden RAM spikes."
            )

    if device == "cuda":
        gpu = _nvidia_resource_snapshot()
        if gpu is not None:
            process_gpu = (
                f" | process VRAM={_format_bytes(gpu['process_used'])}"
                if gpu.get("process_used") is not None
                else ""
            )
            lines.append(
                "G-TMCE ASR GPU: "
                f"{gpu['name']} | CUDA/{compute_type} | "
                f"VRAM={_format_bytes(gpu['used'])}/{_format_bytes(gpu['total'])}"
                f"{process_gpu} | util={gpu['util']:.0f}%"
            )
            free_vram = max(0, int(gpu["total"]) - int(gpu["used"]))
            if gpu["total"] and free_vram < max(512 * 1024**2, int(gpu["total"] * 0.08)):
                lines.append(
                    "G-TMCE ASR WARNING: GPU memory headroom is low "
                    f"({_format_bytes(free_vram)} free); CUDA OOM is possible."
                )
        else:
            lines.append(
                f"G-TMCE ASR GPU: CUDA/{compute_type} active; nvidia-smi telemetry unavailable."
            )
    else:
        lines.append(f"G-TMCE ASR device: CPU/{compute_type}")
    return lines


def _directory_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _prepare_local_model(
    model_name: str,
    logger: Callable[[str], None],
    cancel_event: Any | None,
) -> Path:
    source = Path(model_name).expanduser()
    if source.is_dir():
        return source

    saved_snapshot = _saved_model_snapshot(model_name)
    if saved_snapshot is not None:
        logger(f"G-TMCE ASR: using saved model snapshot: {saved_snapshot}")
        return saved_snapshot

    try:
        from faster_whisper import download_model  # type: ignore
    except ImportError as exc:
        raise UserVisibleError(ui_text("error_asr_dependency_missing")) from exc

    cache_dir = asr_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Reuse the exact Hugging Face cache layout created by earlier G-TMCE
    # versions. This is important when a first turbo download was already
    # partially or fully completed before upgrading the app.
    try:
        cached = Path(
            download_model(
                model_name,
                local_files_only=True,
                cache_dir=str(cache_dir),
            )
        )
        if cached.is_dir():
            _remember_model_snapshot(model_name, cached)
            logger(f"G-TMCE ASR: model cache ready: {cached}")
            return cached
    except Exception:
        pass

    expected = MODEL_DOWNLOAD_BYTES.get(model_name.lower())
    initial_size = _directory_size(cache_dir)
    if expected:
        logger(
            "G-TMCE ASR: model is not fully cached; downloading/resuming "
            f"~{_format_bytes(expected)} into {cache_dir}"
        )
    else:
        logger(f"G-TMCE ASR: model is not fully cached; downloading/resuming into {cache_dir}")

    stop = threading.Event()

    def monitor() -> None:
        last_size = -1
        last_time = 0.0
        while not stop.wait(1.5):
            size = _directory_size(cache_dir)
            now = time.monotonic()
            if size == last_size and now - last_time < 10.0:
                continue
            if last_size >= 0 and abs(size - last_size) < 8 * 1024 * 1024 and now - last_time < 10.0:
                continue
            growth = max(0, size - initial_size)
            if growth > 0:
                logger(
                    "G-TMCE ASR model download: "
                    f"+{_format_bytes(growth)} this run; cache={_format_bytes(size)}"
                )
            else:
                logger(
                    "G-TMCE ASR: model download is active; "
                    f"cache={_format_bytes(size)} (waiting for network/cache write)"
                )
            last_size = size
            last_time = now

    thread = threading.Thread(target=monitor, name="gtmce-asr-model-progress", daemon=True)
    thread.start()
    try:
        # faster-whisper intentionally disables Hugging Face's tqdm display.
        # We keep its native cache path (so existing/partial downloads resume)
        # and report cache activity through the G-TMCE log instead.
        downloaded = download_model(model_name, cache_dir=str(cache_dir))
    finally:
        stop.set()
        thread.join(timeout=2.0)

    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled()
    model_path = Path(downloaded)
    _remember_model_snapshot(model_name, model_path)
    logger(f"G-TMCE ASR: model download/cache ready: {model_path}")
    return model_path

def _load_whisper_model(
    model_name: str,
    device: str,
    compute_type: str,
    *,
    logger: Callable[[str], None],
    cancel_event: Any | None,
) -> Any:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise UserVisibleError(ui_text("error_asr_dependency_missing")) from exc

    model_path = _prepare_local_model(model_name, logger, cancel_event)
    logger(f"G-TMCE ASR: loading model on {device}/{compute_type}...")
    model = WhisperModel(
        str(model_path),
        device=device,
        compute_type=compute_type,
    )
    logger("G-TMCE ASR: model loaded; transcription starting...")
    return model


def translation_model_cache_dir() -> Path:
    override = os.environ.get("GTMCE_TRANSLATION_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return asr_model_cache_dir() / "translation"


def translation_language_name(language: str) -> str:
    code = str(language or "").strip().lower()
    for item_code, name in TRANSLATION_TARGET_LANGUAGES:
        if item_code == code:
            return name
    return code


def _prepare_translation_model(
    model_name: str,
    logger: Callable[[str], None],
    cancel_event: Any | None,
) -> Path:
    source = Path(model_name).expanduser()
    if source.is_dir():
        return source

    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:
        raise UserVisibleError(ui_text("error_translation_dependency_missing")) from exc

    cache_dir = translation_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    allow_patterns = list(TRANSLATION_MODEL_FILES)

    try:
        cached = Path(
            snapshot_download(
                repo_id=model_name,
                cache_dir=str(cache_dir),
                allow_patterns=allow_patterns,
                local_files_only=True,
            )
        )
        if cached.is_dir():
            logger(f"G-TMCE AI Translation: model cache ready: {cached}")
            return cached
    except Exception:
        pass

    logger(
        "G-TMCE AI Translation: model is not cached; downloading/resuming "
        f"~{_format_bytes(TRANSLATION_MODEL_DOWNLOAD_BYTES)} into {cache_dir}"
    )

    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled()

    initial_size = _directory_size(cache_dir)
    stop = threading.Event()

    def monitor() -> None:
        last_size = -1
        while not stop.wait(1.5):
            size = _directory_size(cache_dir)
            if size == last_size:
                continue
            growth = max(0, size - initial_size)
            if growth > 0:
                logger(
                    "G-TMCE AI Translation model download: "
                    f"+{_format_bytes(growth)} this run; cache={_format_bytes(size)}"
                )
            last_size = size

    thread = threading.Thread(
        target=monitor,
        name="gtmce-translation-model-progress",
        daemon=True,
    )
    thread.start()
    try:
        downloaded = snapshot_download(
            repo_id=model_name,
            cache_dir=str(cache_dir),
            allow_patterns=allow_patterns,
        )
    finally:
        stop.set()
        thread.join(timeout=2.0)
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled()
    model_path = Path(downloaded)
    logger(f"G-TMCE AI Translation: model download/cache ready: {model_path}")
    return model_path


def _load_translation_runtime(
    model_path: Path,
    logger: Callable[[str], None],
) -> tuple[Any, Any]:
    try:
        import ctranslate2  # type: ignore
        import sentencepiece as sentencepiece  # type: ignore
    except ImportError as exc:
        raise UserVisibleError(ui_text("error_translation_dependency_missing")) from exc

    sentencepiece_model = next(
        (
            candidate
            for candidate in (
                model_path / "spiece.model",
                model_path / "sentencepiece.model",
            )
            if candidate.is_file()
        ),
        None,
    )
    if sentencepiece_model is None or not (model_path / "model.bin").is_file():
        raise UserVisibleError(ui_text("error_translation_model_invalid", path=model_path))

    tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(sentencepiece_model))

    cuda_compute = _best_cuda_compute_type()
    device = "cuda" if cuda_compute else "cpu"
    # The downloaded model is already INT8. Let CTranslate2 use its native
    # representation instead of requesting a conflicting runtime conversion.
    compute_type = "default" if device == "cuda" else "int8"
    try:
        logger(f"G-TMCE AI Translation: loading multilingual model on {device}/{compute_type}...")
        translator = ctranslate2.Translator(
            str(model_path),
            device=device,
            compute_type=compute_type,
        )
    except Exception as exc:
        if device != "cuda":
            raise UserVisibleError(ui_text("error_translation_failed", error=exc)) from exc
        logger(f"G-TMCE AI Translation: CUDA load failed; retrying on CPU/int8 ({exc})")
        try:
            translator = ctranslate2.Translator(
                str(model_path),
                device="cpu",
                compute_type="int8",
            )
        except Exception as cpu_exc:
            raise UserVisibleError(ui_text("error_translation_failed", error=cpu_exc)) from cpu_exc

    return translator, tokenizer


def _cue_finishes_sentence(text: str) -> bool:
    value = _clean_text(text)
    if not value:
        return True
    # Quotes/brackets after punctuation still count as sentence termination.
    return bool(re.search(r"[.!?…][\"'’”»)\]]*$", value))


def _translation_units(cues: Iterable[SubtitleCue]) -> list[_TranslationUnit]:
    """Build context-aware translation units without collapsing SRT timing.

    Whisper often splits one sentence across adjacent cues. Joining those
    fragments gives the translator enough context for idioms and continuations,
    but the joined text must *not* become one giant subtitle cue. Each unit
    therefore remembers its original cues; translated text is redistributed
    back onto those timings after decoding.
    """
    cue_list = [cue for cue in cues if cue.text.strip() and cue.end > cue.start]
    if not cue_list:
        return []

    units: list[_TranslationUnit] = []
    current_cues = [cue_list[0]]
    parts = [_clean_text(cue_list[0].text)]
    end = cue_list[0].end

    for cue in cue_list[1:]:
        text = _clean_text(cue.text)
        gap = max(0.0, cue.start - end)
        combined_length = len(" ".join(parts)) + 1 + len(text)
        should_merge = (
            not _has_translation_wrapper(parts[-1])
            and not _has_translation_wrapper(text)
            and not _cue_finishes_sentence(parts[-1])
            and gap <= 1.25
            and len(parts) < 4
            and combined_length <= 320
        )
        if should_merge:
            current_cues.append(cue)
            parts.append(text)
            end = cue.end
            continue
        units.append(_TranslationUnit(tuple(current_cues), _clean_text(" ".join(parts))))
        current_cues = [cue]
        parts = [text]
        end = cue.end

    units.append(_TranslationUnit(tuple(current_cues), _clean_text(" ".join(parts))))
    return units


def _split_long_translation_cue(cue: SubtitleCue, max_chars: int = 84) -> list[SubtitleCue]:
    """Keep translated subtitle blocks to roughly two 42-character lines.

    Whole-cue SDH/italic wrappers are detached before wrapping and restored on
    *each* generated cue.  This prevents long ``<i>...</i>`` or ``[...]``
    subtitles from producing unbalanced formatting when split.
    """
    text = _clean_text(cue.text)
    if not text:
        return []
    payload, wrapper_prefix, wrapper_suffix = _translation_text_wrapper(text)
    split_text = payload if (wrapper_prefix or wrapper_suffix) else text
    if len(split_text) <= max_chars:
        restored = _restore_translation_wrapper(split_text, wrapper_prefix, wrapper_suffix)
        return [SubtitleCue(cue.start, cue.end, _wrap_subtitle_text(restored))]

    chunks = textwrap.wrap(
        split_text,
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(chunks) <= 1 or cue.end <= cue.start:
        return [SubtitleCue(cue.start, cue.end, _wrap_subtitle_text(text))]

    duration = cue.end - cue.start
    weights = [max(1, len(chunk)) for chunk in chunks]
    total_weight = sum(weights)
    result: list[SubtitleCue] = []
    elapsed_weight = 0
    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        start = cue.start + duration * elapsed_weight / total_weight
        elapsed_weight += weight
        end = cue.end if index == len(chunks) - 1 else cue.start + duration * elapsed_weight / total_weight
        restored = _restore_translation_wrapper(chunk, wrapper_prefix, wrapper_suffix)
        result.append(SubtitleCue(start, end, _wrap_subtitle_text(restored)))
    return result


def _split_translation_across_source_cues(
    source_cues: tuple[SubtitleCue, ...],
    translated_text: str,
) -> list[SubtitleCue]:
    """Redistribute one contextual translation over the original cue timings.

    The translator may see several adjacent source cues as one sentence, but
    viewers still need short, readable subtitle blocks. We split at nearby
    punctuation where possible and otherwise use source word proportions. This
    preserves the source cue count/timestamps instead of turning four 4-second
    cues into one 18-second paragraph.
    """
    text = _clean_text(translated_text)
    if not source_cues or not text:
        return []
    if len(source_cues) == 1:
        cue = source_cues[0]
        return _split_long_translation_cue(SubtitleCue(cue.start, cue.end, text))

    words = text.split()
    cue_count = len(source_cues)
    if len(words) < cue_count:
        # Extremely compressed output cannot be split into non-empty blocks
        # safely. Keep it on the full unit rather than inventing/duplicating
        # translated words. This should be rare and is still preferable to a
        # decoder loop.
        return [
            SubtitleCue(source_cues[0].start, source_cues[-1].end, _wrap_subtitle_text(text))
        ]

    source_weights = [max(1, len(_translation_word_tokens(cue.text))) for cue in source_cues]
    total_weight = sum(source_weights)
    boundaries: list[int] = []
    previous = 0
    cumulative_weight = 0

    for index, weight in enumerate(source_weights[:-1]):
        cumulative_weight += weight
        remaining_cues = cue_count - index - 1
        ideal = round(len(words) * cumulative_weight / total_weight)
        low = previous + 1
        high = len(words) - remaining_cues
        ideal = min(high, max(low, ideal))

        # Prefer a natural punctuation boundary close to the proportional cut.
        candidates = range(max(low, ideal - 4), min(high, ideal + 4) + 1)
        best = ideal
        best_score = float("inf")
        for boundary in candidates:
            token = words[boundary - 1]
            punctuation_bonus = 0.0
            if re.search(r"[.!?…][\"'’”»)]*$", token):
                punctuation_bonus = 2.5
            elif re.search(r"[,;:][\"'’”»)]*$", token):
                punctuation_bonus = 1.0
            score = abs(boundary - ideal) - punctuation_bonus
            if score < best_score:
                best = boundary
                best_score = score
        boundaries.append(best)
        previous = best

    pieces: list[str] = []
    start = 0
    for boundary in boundaries + [len(words)]:
        pieces.append(_clean_text(" ".join(words[start:boundary])))
        start = boundary

    redistributed: list[SubtitleCue] = []
    for cue, piece in zip(source_cues, pieces):
        if not piece:
            continue
        redistributed.extend(
            _split_long_translation_cue(SubtitleCue(cue.start, cue.end, piece))
        )
    return redistributed


def _translation_word_tokens(text: str) -> list[str]:
    """Return case-folded word tokens for translation sanity checks."""
    return [
        token.casefold()
        for token in re.findall(r"[^\W_]+(?:['’][^\W_]+)?", _clean_text(text), flags=re.UNICODE)
    ]


def _longest_same_token_run(tokens: list[str]) -> int:
    if not tokens:
        return 0
    longest = 1
    current = 1
    for previous, token in zip(tokens, tokens[1:]):
        if token == previous:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def _sentence_break_count(text: str) -> int:
    """Count likely sentence endings without treating every dot as a boundary."""
    value = _clean_text(text)
    if not value:
        return 0
    return len(re.findall(r"(?:[!?…]+|\.(?=\s|$))", value))


def _normalised_translation_text(text: str) -> str:
    """Normalise text for conservative source==target fallback detection."""
    return " ".join(_translation_word_tokens(text))


_TINY_ENGLISH_ASR_FRAGMENT_TOKENS = {
    # Function-word fragments this short are almost always incomplete Whisper
    # debris rather than useful standalone dialogue.  Dropping them is safer
    # than letting MT invent a full sentence from e.g. ``The`` or ``He``.
    "a", "an", "and", "but", "he", "it", "of", "or", "she",
    "the", "there's", "there're", "to",
}


def _is_unreliable_tiny_translation_fragment(
    text: str, duration: float, source_language: str
) -> bool:
    """Return True for tiny incomplete English ASR function-word fragments."""
    if normalise_asr_language(source_language) != "en" or duration > 0.9:
        return False
    tokens = _translation_word_tokens(text)
    return len(tokens) == 1 and tokens[0] in _TINY_ENGLISH_ASR_FRAGMENT_TOKENS


_ENGLISH_SINGLE_WORD_ECHOES = {
    # Common dialogue/function words that may be capitalised only because they
    # start a subtitle.  A title-cased unknown word is otherwise treated as a
    # possible proper noun and may legitimately survive translation.
    "ah", "also", "and", "are", "do", "done", "fine", "go", "good",
    "he", "hello", "her", "here", "hey", "hi", "him", "hmm", "huh",
    "i", "it", "me", "my", "no", "not", "now", "oh", "okay", "ok",
    "right", "she", "so", "sorry", "sure", "thanks", "that", "the",
    "them", "then", "there", "they", "this", "uh", "um", "us", "we",
    "well", "what", "why", "yeah", "yep", "yes", "nope", "you", "your",
}


# Target-language agnostic rescue paraphrases for very short English dialogue.
# MADLAD occasionally treats terse conversational lines as labels and copies
# them unchanged.  Rephrasing the *English source* gives the same multilingual
# model a semantically explicit sentence to translate while keeping the target
# language fully user-selectable.  This is deliberately not a Turkish lookup
# table: every value is still translated by MADLAD into the selected target.
_ENGLISH_DIALOGUE_RESCUE_PARAPHRASES: dict[str, tuple[str, ...]] = {
    "yeah": ("Yes.", "That is correct."),
    "yep": ("Yes.", "That is correct."),
    "nope": ("No.", "That is not correct."),
    "okay": ("All right.", "I understand."),
    "ok": ("All right.", "I understand."),
    "thanks": ("Thank you.", "I am grateful."),
    "sorry": ("I am sorry.", "I apologize."),
    "i know": ("I understand.", "I am aware of that."),
    "i mean that's late": (
        "What I mean is that it is late.",
        "I mean that the time is late.",
    ),
}


def _english_dialogue_rescue_variants(source: str) -> list[str]:
    """Return explicit English paraphrases for stubborn short dialogue echoes."""
    key = _normalised_translation_text(source)
    return list(_ENGLISH_DIALOGUE_RESCUE_PARAPHRASES.get(key, ()))


def _translation_untranslated_reason(source: str, output: str) -> str | None:
    """Detect model fallbacks that simply echo the source language.

    Proper nouns can legitimately survive translation.  Everything else that
    comes back byte-for-byte as the source is suspicious, including short
    dialogue such as ``Yeah``, ``I know`` and sentence-initial pronouns.  This
    deliberately remains target-language agnostic; the small English word set
    only distinguishes common dialogue words from one-word proper names when
    the *source* happens to be English.
    """
    source_norm = _normalised_translation_text(source)
    output_norm = _normalised_translation_text(output)
    if not source_norm or source_norm != output_norm:
        return None

    source_tokens = _translation_word_tokens(source)
    raw_words = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", _clean_text(source), flags=re.UNICODE)
    if len(source_tokens) >= 3:
        return "source-echo"
    if len(source_tokens) == 2:
        # Only a two-token proper name such as ``New Mexico`` is allowed to
        # remain unchanged.  ``My daughter`` and ``I know`` must be retried.
        if len(raw_words) == 2 and all(word[:1].isupper() for word in raw_words):
            return None
        return "source-echo-short"
    if len(source_tokens) == 1 and raw_words:
        word = raw_words[0]
        token = source_tokens[0]
        if word[:1].islower() or token in _ENGLISH_SINGLE_WORD_ECHOES:
            return "source-echo-single"
    return None


def _translation_invalid_reason(source: str, output: str) -> str | None:
    return (
        _translation_degeneration_reason(source, output)
        or _translation_untranslated_reason(source, output)
    )


def _translation_degeneration_reason(source: str, output: str) -> str | None:
    """Detect decoder loops without rejecting legitimate repeated dialogue.

    MADLAD occasionally gets stuck on a token when the ASR source is a tiny
    fragment (for example ``The`` -> ``The The The...``) or when a sentence
    ends on a filler.  Compare the generated repetition with the source so
    real dialogue such as ``go, go, go`` remains valid.
    """
    source_tokens = _translation_word_tokens(source)
    output_tokens = _translation_word_tokens(output)
    if not output_tokens:
        return "empty"

    source_count = max(1, len(source_tokens))
    output_count = len(output_tokens)
    comparable_words = not (_uses_unspaced_translation_script(source) or _uses_unspaced_translation_script(output))
    source_run = _longest_same_token_run(source_tokens)
    output_run = _longest_same_token_run(output_tokens)

    # Short inputs sometimes become duplicated answers (for example
    # ``I don't know.`` -> ``Bilmiyorum, bilmiyorum.``). A two-token run is
    # suspicious only when the source itself did not repeat that token.
    repeated_source_clauses = _has_adjacent_translation_duplicate(source)
    if output_run >= 2 and source_run < 2 and output_count <= 8 and not repeated_source_clauses:
        return f"short-token-repeat:{output_run}"

    # Tiny ASR fragments are especially prone to semantic hallucinations that
    # are not token loops (for example ``The`` becoming a whole unrelated
    # sentence). Reject implausible expansion before it reaches the subtitle.
    if comparable_words and source_count == 1 and output_count >= 5:
        return f"tiny-input-expansion:{source_count}->{output_count}"
    if comparable_words and source_count == 2 and output_count > 8:
        return f"tiny-input-expansion:{source_count}->{output_count}"
    if comparable_words and source_count <= 4 and output_count > source_count * 4 + 4:
        return f"short-input-expansion:{source_count}->{output_count}"

    # Beam decoding can occasionally emit two alternative translations one
    # after another. For subtitle work that is both semantically dangerous and
    # far too verbose. Retry when one source sentence unexpectedly expands to
    # multiple target sentences with additional material.
    source_sentences = _sentence_break_count(source)
    output_sentences = _sentence_break_count(output)
    if (
        source_sentences <= 1
        and output_sentences >= 2
        and comparable_words and output_count >= source_count + 3
    ):
        return f"sentence-expansion:{source_sentences}->{output_sentences}"

    # The supplied sample exposed runs such as one source token becoming 7-36
    # copies in the translation. Keep genuine source repetition by allowing a
    # little headroom over the longest run already present in the source.
    if output_run >= 4 and output_run > source_run + 2 and not repeated_source_clauses:
        return f"token-loop:{output_run}"

    # A subtitle translation should not explode to many times the source size.
    # Use a generous limit because some language pairs naturally expand.
    if comparable_words and output_count > max(24, source_count * 4 + 10):
        return f"length-explosion:{source_count}->{output_count}"

    # Low lexical diversity is another signature of a loop even when
    # punctuation or a short preamble interrupts the repeated token run.
    if output_count >= 12:
        unique_ratio = len(set(output_tokens)) / output_count
        if comparable_words and unique_ratio < 0.22 and output_count > source_count * 2:
            return f"low-diversity:{unique_ratio:.2f}"

    return None


def _decode_translation_result(
    result: Any, tokenizer: Any, target_language: str, *, max_length: int | None = None,
) -> str:
    hypothesis = list(result.hypotheses[0]) if result.hypotheses else []
    # A length-limited hypothesis can end in the middle of a SentencePiece
    # word. It is not a finished translation, even if its text passes QA.
    # Ask CT2 to retain EOS, and never send these fragments to layout/fallback.
    if max_length is not None and len(hypothesis) >= max_length and "</s>" not in hypothesis:
        return ""
    hypothesis = [
        token for token in hypothesis
        if token not in {"</s>", "<pad>", f"<2{target_language}>"}
    ]
    return _clean_text(tokenizer.decode(hypothesis)) if hypothesis else ""


def _encode_translation_source(tokenizer: Any, text: str, target_language: str) -> list[str]:
    """Build a complete MADLAD/T5 input, not an unfinished text prefix.

    Plain SentencePiece does not add the T5 EOS that Hugging Face tokenizers
    normally append. The converted CT2 model also has add_source_eos=false.
    Missing EOS makes the translator invent continuations of the source.
    """
    tokens = list(tokenizer.encode(f"<2{target_language}> {_clean_text(text)}", out_type=str))
    if not tokens or tokens[-1] != "</s>":
        tokens.append("</s>")
    return tokens


@dataclass
class _RankedTranslationResult:
    hypotheses: list[list[str]]


class _FaithfulSubtitleTranslator:
    """Re-rank a bounded set of translations by source reconstruction score.

    Uses teacher-forced scoring with the same loaded multilingual model, not
    another model or language-specific negation/idiom dictionaries. Scores
    compare the identical source tokens for every candidate. They are a
    preference signal, not a guarantee of semantic equivalence.
    """
    def __init__(self, translator: Any, tokenizer: Any, source_language: str, cancel_event: Any = None, pause_event: Any = None):
        self.translator = translator
        self.tokenizer = tokenizer
        self.source_language = source_language
        self.cancel_event = cancel_event
        self.pause_event = pause_event
        self.reconstruction_scores: dict[tuple[str, str], float] = {}
        self.translation_scores: dict[tuple[str, str], float] = {}

    def _checkpoint(self) -> None:
        while self.pause_event is not None and self.pause_event.is_set():
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise OperationCancelled()
            time.sleep(0.12)
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise OperationCancelled()

    def reconstruction_score(self, source: str, candidate: str) -> float:
        key = (_clean_text(source), _clean_text(candidate))
        if key not in self.reconstruction_scores:
            self._checkpoint()
            target = list(self.tokenizer.encode(key[0], out_type=str))
            if not target or target[-1] != "</s>":
                target.append("</s>")
            result = self.translator.score_batch(
                [_encode_translation_source(self.tokenizer, key[1], self.source_language)], [target],
            )[0]
            self._checkpoint()
            self.reconstruction_scores[key] = sum(result.log_probs) / max(1, len(result.log_probs))
        return self.reconstruction_scores[key]

    def candidate_score(self, source: str, candidate: str, target_language: str) -> float:
        """Compare source fidelity AND target fluency on the same full input."""
        key = (_clean_text(source), _clean_text(candidate))
        if key not in self.translation_scores:
            self._checkpoint()
            target = list(self.tokenizer.encode(key[1], out_type=str))
            if not target or target[-1] != "</s>":
                target.append("</s>")
            result = self.translator.score_batch(
                [_encode_translation_source(self.tokenizer, key[0], target_language)], [target],
            )[0]
            self._checkpoint()
            self.translation_scores[key] = sum(result.log_probs) / max(1, len(result.log_probs))
        return self.translation_scores[key] + self.reconstruction_score(source, candidate)

    def translate_batch(self, source_tokens: list[list[str]], **kwargs: Any) -> list[Any]:
        self._checkpoint()
        # At least two candidates are needed to resolve a close wrong/correct
        # choice. Bound search/scoring even for Maximum to avoid VRAM spikes.
        kwargs["beam_size"] = max(2, int(kwargs.get("beam_size", 2)))
        kwargs["num_hypotheses"] = min(4, kwargs["beam_size"])
        kwargs["return_scores"] = True
        kwargs["return_end_token"] = True
        results = self.translator.translate_batch(source_tokens, **kwargs)
        expanded: set[int] = set()
        # Very similar endings can carry opposite meanings or different
        # modalities. A small beam can prune the faithful form entirely.
        # Widen only these ambiguous items, individually, keeping memory
        # bounded instead of running a large beam for the whole subtitle.
        if kwargs["beam_size"] < 8:
            for index, result in enumerate(results):
                alternatives = [_translation_word_tokens(self.tokenizer.decode(h)) for h in result.hypotheses]
                if len(alternatives) < 2 or min(map(len, alternatives)) < 4:
                    continue
                prefix = 0
                for words in zip(*alternatives):
                    if len(set(words)) != 1:
                        break
                    prefix += 1
                endings = {tuple(words[prefix:]) for words in alternatives}
                if prefix >= min(map(len, alternatives)) - 2 and len(endings) > 1:
                    self._checkpoint()
                    wider = dict(kwargs, beam_size=8, num_hypotheses=4)
                    results[index] = self.translator.translate_batch([source_tokens[index]], **wider)[0]
                    expanded.add(index)
        reverse_sources: list[list[str]] = []
        reverse_targets: list[list[str]] = []
        refs: list[tuple[int, int, float]] = []
        limit = kwargs.get("max_decoding_length")
        for index, (tokens, result) in enumerate(zip(source_tokens, results)):
            original = [token for token in tokens if not re.fullmatch(r"<2[^>]+>", token)]
            source = self.tokenizer.decode([t for t in original if t != "</s>"])
            for alternative, hypothesis in enumerate(result.hypotheses):
                candidate = _decode_translation_result(_RankedTranslationResult([hypothesis]), self.tokenizer, "", max_length=limit)
                if not candidate or _strict_translation_quality_reason(source, candidate) is not None:
                    continue
                reverse_sources.append(_encode_translation_source(self.tokenizer, candidate, self.source_language))
                target = list(self.tokenizer.encode(source, out_type=str))
                if not target or target[-1] != "</s>":
                    target.append("</s>")
                reverse_targets.append(target)
                refs.append((index, alternative, float(result.scores[alternative])))
        if not refs:
            return results
        self._checkpoint()
        scores = self.translator.score_batch(reverse_sources, reverse_targets, max_batch_size=8)
        choices: dict[int, tuple[float, int]] = {}
        for position, ((index, alternative, forward), reverse) in enumerate(zip(refs, scores)):
            if not reverse.log_probs:
                continue
            reverse_score = sum(reverse.log_probs) / len(reverse.log_probs)
            source = self.tokenizer.decode([t for t in reverse_targets[position] if t != "</s>"])
            candidate = _decode_translation_result(
                _RankedTranslationResult([results[index].hypotheses[alternative]]), self.tokenizer, "",
            )
            self.reconstruction_scores[(_clean_text(source), _clean_text(candidate))] = reverse_score
            self.translation_scores[(_clean_text(source), _clean_text(candidate))] = forward
            score = forward + reverse_score
            if index not in choices or score > choices[index][0]:
                choices[index] = (score, alternative)
        self._checkpoint()
        ranked = [_RankedTranslationResult([result.hypotheses[choices[index][1]]]) if index in choices else result
                  for index, result in enumerate(results)]
        # A short low-confidence fragment may require a wider search even if
        # its alternatives do not share a prefix. Retry one item at a time,
        # never recurse from an already-wide decode or widen long paragraphs.
        if kwargs["beam_size"] < 8:
            for index, result in enumerate(ranked):
                original = [t for t in source_tokens[index] if t != "</s>" and not re.fullmatch(r"<2[^>]+>", t)]
                source = self.tokenizer.decode(original)
                candidate = _decode_translation_result(result, self.tokenizer, "", max_length=limit)
                if (index not in expanded and index in choices and candidate and len(source_tokens[index]) <= 48
                        and self.reconstruction_scores.get((_clean_text(source), _clean_text(candidate)), 0) < -2.5):
                    ranked[index] = self.translate_batch([source_tokens[index]], **dict(kwargs, beam_size=8, num_hypotheses=4))[0]
        return ranked


def _decode_single_translation(
    translator: Any,
    tokenizer: Any,
    text: str,
    target_language: str,
    *,
    beam_size: int,
    repetition_penalty: float,
    no_repeat_ngram_size: int,
    length_factor: float = 3.0,
    length_extra: int = 8,
) -> str:
    tokens = _encode_translation_source(tokenizer, text, target_language)
    max_length = min(512, max(12, int(len(tokens) * length_factor) + length_extra))
    result = translator.translate_batch(
        [tokens],
        beam_size=beam_size,
        repetition_penalty=repetition_penalty,
        no_repeat_ngram_size=no_repeat_ngram_size,
        max_decoding_length=max_length,
        return_end_token=True,
    )[0]
    return _decode_translation_result(result, tokenizer, target_language, max_length=max_length)


def _decode_translation_batch(
    translator: Any,
    tokenizer: Any,
    texts: list[str],
    target_language: str,
    *,
    beam_size: int = 2,
    repetition_penalty: float = 1.10,
    no_repeat_ngram_size: int = 3,
    length_factor: float = 1.75,
    length_extra: int = 6,
) -> list[str]:
    """Decode many independent subtitle spans in one CTranslate2 call.

    A single max decoding length is required by CTranslate2, so size batches
    conservatively and derive the limit from the longest member.  Structural
    subtitle markup never reaches this helper.
    """
    if not texts:
        return []
    encoded = [
        _encode_translation_source(tokenizer, text, target_language)
        for text in texts
    ]
    longest = max((len(tokens) for tokens in encoded), default=1)
    max_length = min(512, max(12, int(longest * length_factor) + length_extra))
    results = translator.translate_batch(
        encoded,
        beam_size=beam_size,
        repetition_penalty=repetition_penalty,
        no_repeat_ngram_size=no_repeat_ngram_size,
        max_decoding_length=max_length,
        return_end_token=True,
    )
    return [_decode_translation_result(result, tokenizer, target_language, max_length=max_length) for result in results]


def _safe_retry_translation(
    translator: Any,
    tokenizer: Any,
    cue: SubtitleCue,
    target_language: str,
) -> str:
    """Retry a suspicious translation with two conservative decode profiles."""
    source = _clean_text(cue.text)
    attempts = (
        # Greedy decoding is effective against beam-search loops.
        dict(beam_size=1, repetition_penalty=1.22, no_repeat_ngram_size=2, length_factor=2.6, length_extra=8),
        # A small beam can rescue legitimate phrases that greedy leaves in the
        # source language while still keeping repetition tightly bounded.
        dict(beam_size=2, repetition_penalty=1.14, no_repeat_ngram_size=3, length_factor=3.0, length_extra=10),
    )
    best = ""
    for settings in attempts:
        candidate = _decode_single_translation(
            translator, tokenizer, source, target_language, **settings
        )
        if candidate and _translation_invalid_reason(source, candidate) is None:
            return candidate
        if candidate and not best:
            best = candidate
    return best


def _sentence_case_translation_source(text: str) -> str:
    """Return a conservative sentence-cased variant for fragment rescue."""
    value = _clean_text(text)
    for index, char in enumerate(value):
        if char.isalpha():
            return value[:index] + char.upper() + value[index + 1:]
    return value


def _rescue_source_echo_translation(
    translator: Any,
    tokenizer: Any,
    source: str,
    target_language: str,
) -> str:
    """Try alternate source shapes when MADLAD echoes the input unchanged.

    Short ASR fragments can be treated as labels/noise by multilingual MT
    models.  Sentence casing, explicit punctuation, and finally translating
    short chunks independently often recover a real translation without a
    second model or cloud API.
    """
    source = _clean_text(source)
    if not source:
        return ""

    variants: list[str] = []
    # First try semantically explicit rewrites for terse English dialogue that
    # multilingual MT models are prone to echo unchanged.  Proper names never
    # enter this table, so Chloe/Ellie/Sullivan remain untouched.
    for variant in _english_dialogue_rescue_variants(source):
        if variant and variant not in variants:
            variants.append(variant)

    sentence_case = _sentence_case_translation_source(source)
    for variant in (sentence_case, sentence_case.rstrip(".!?…") + "."):
        if variant and variant not in variants:
            variants.append(variant)

    profiles = (
        dict(beam_size=4, repetition_penalty=1.08, no_repeat_ngram_size=3, length_factor=3.0, length_extra=10),
        dict(beam_size=1, repetition_penalty=1.18, no_repeat_ngram_size=2, length_factor=2.8, length_extra=8),
    )
    for variant in variants:
        for settings in profiles:
            candidate = _decode_single_translation(
                translator, tokenizer, variant, target_language, **settings
            )
            if candidate and _translation_invalid_reason(source, candidate) is None:
                return candidate

    # Longer echoed sentences are easier to rescue as compact clauses.  Keep
    # chunks large enough for morphology/context but small enough that one bad
    # span cannot make the model echo the entire sentence.
    words = source.split()
    if len(words) >= 6:
        chunks: list[str] = []
        current: list[str] = []
        for word in words:
            current.append(word)
            if len(current) >= 8 or re.search(r"[,;:!?…]$", word):
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))

        translated_chunks: list[str] = []
        if len(chunks) >= 2:
            for chunk in chunks:
                chunk_variant = _sentence_case_translation_source(chunk)
                if not re.search(r"[.!?…]$", chunk_variant):
                    chunk_variant += "."
                candidate = _decode_single_translation(
                    translator,
                    tokenizer,
                    chunk_variant,
                    target_language,
                    beam_size=2,
                    repetition_penalty=1.12,
                    no_repeat_ngram_size=3,
                    length_factor=3.0,
                    length_extra=8,
                )
                if not candidate or _translation_invalid_reason(chunk, candidate) is not None:
                    translated_chunks = []
                    break
                translated_chunks.append(candidate)
            if translated_chunks:
                candidate = _clean_text(" ".join(translated_chunks))
                if _translation_invalid_reason(source, candidate) is None:
                    return candidate

    return ""


def _rescue_translation_with_neighbor(
    translator: Any,
    tokenizer: Any,
    units: list[_TranslationUnit],
    unit_index: int,
    target_language: str,
) -> str:
    """Use one neighbouring source unit as MT context for stubborn echoes.

    The separator lets us extract only the current unit after translation.
    This is a last local rescue path for inputs such as ``human traffickers``
    or short dialogue words that MADLAD may otherwise copy unchanged.
    """
    unit = units[unit_index]
    candidates: list[tuple[str, bool]] = []
    if unit_index + 1 < len(units):
        candidates.append((units[unit_index + 1].text, True))
    if unit_index > 0:
        candidates.append((units[unit_index - 1].text, False))

    separator = " ||| "
    split_pattern = re.compile(r"\s*\|\s*\|\s*\|\s*")
    for neighbour_text, current_first in candidates:
        neighbour_text = _clean_text(neighbour_text)
        if not neighbour_text:
            continue
        combined = (
            f"{_clean_text(unit.text)}{separator}{neighbour_text}"
            if current_first
            else f"{neighbour_text}{separator}{_clean_text(unit.text)}"
        )
        translated = _decode_single_translation(
            translator,
            tokenizer,
            combined,
            target_language,
            beam_size=3,
            repetition_penalty=1.10,
            no_repeat_ngram_size=3,
            length_factor=3.2,
            length_extra=12,
        )
        parts = [part.strip() for part in split_pattern.split(translated, maxsplit=1)]
        if len(parts) != 2:
            continue
        rescued = parts[0] if current_first else parts[1]
        if rescued and _translation_invalid_reason(unit.text, rescued) is None:
            return rescued
    return ""


def _rebalance_translation_timings(
    cues: Iterable[SubtitleCue],
    *,
    target_cps: float = 20.0,
    hard_cps: float = 40.0,
    max_duration: float = 4.5,
    safety_gap: float = 0.04,
) -> list[SubtitleCue]:
    """Use nearby silent gaps to make unreadably short translated cues readable.

    Translation can turn a 0.2-second ASR fragment into a much longer target
    phrase.  We never reorder cues or overlap the next subtitle; we only borrow
    otherwise-unused time immediately before/after the cue. Dense dialogue is
    left untouched rather than drifting away from speech.
    """
    items = list(cues)
    if len(items) < 1:
        return []
    result: list[SubtitleCue] = []
    for index, cue in enumerate(items):
        text = _clean_text(cue.text)
        duration = max(0.001, cue.end - cue.start)
        visible_chars = len(text.replace("\n", " ").strip())
        if visible_chars <= 0 or visible_chars / duration <= hard_cps:
            result.append(cue)
            continue

        desired = min(max_duration, max(duration, visible_chars / target_cps))
        start = cue.start
        end = cue.end

        # Prefer extending into silence after the cue.
        next_start = items[index + 1].start if index + 1 < len(items) else None
        if next_start is None:
            end = max(end, start + desired)
        else:
            latest_end = max(end, next_start - safety_gap)
            end = min(start + desired, latest_end)

        # If that is not enough, use an existing gap before the cue as well.
        if end - start + 1e-6 < desired and result:
            previous_end = result[-1].end
            earliest_start = max(previous_end + safety_gap, cue.start - 0.5, 0.0)
            if earliest_start < cue.start - safety_gap:
                start = max(earliest_start, end - desired)

        result.append(SubtitleCue(start, end, cue.text))
    return result


def translate_cues_with_ai(
    cues: Iterable[SubtitleCue],
    source_language: str,
    target_language: str,
    *,
    model_name: str | None = None,
    cancel_event: Any | None = None,
    pause_event: Any | None = None,
    progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[SubtitleCue]:
    """Translate subtitle text locally with one multilingual CT2 AI model."""
    source_language = normalise_asr_language(source_language)
    target_language = normalise_asr_language(target_language)
    if target_language not in TRANSLATION_TARGET_CODES:
        raise UserVisibleError(
            ui_text("error_translation_target_unsupported", language=target_language)
        )
    if target_language == source_language:
        raise UserVisibleError(
            ui_text("error_translation_same_language", language=target_language)
        )

    logger = log or (lambda _message: None)

    def wait_if_paused() -> None:
        while pause_event is not None and pause_event.is_set():
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelled()
            time.sleep(0.12)

    wait_if_paused()
    model_name = (
        model_name
        or os.environ.get("GTMCE_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL)
    ).strip() or DEFAULT_TRANSLATION_MODEL

    raw_units = _translation_units(cues)
    cue_list: list[_TranslationUnit] = []
    for unit in raw_units:
        duration = max(0.0, unit.end - unit.start)
        if (
            len(unit.cues) == 1
            and _is_unreliable_tiny_translation_fragment(
                unit.text, duration, source_language
            )
        ):
            logger(
                "G-TMCE AI Translation: dropping incomplete tiny ASR fragment at "
                f"{srt_timestamp(unit.start)}: {unit.text!r}"
            )
            continue
        cue_list.append(unit)
    if not cue_list:
        return []
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled()

    model_path = _prepare_translation_model(model_name, logger, cancel_event)
    translator, tokenizer = _load_translation_runtime(model_path, logger)
    translated: list[SubtitleCue] = []
    batch_size = 16
    total = len(cue_list)
    target_name = translation_language_name(target_language)
    logger(
        f"G-TMCE AI Translation: translating {total} unit(s) "
        f"from {source_language} to {target_name} ({target_language})..."
    )

    try:
        for offset in range(0, total, batch_size):
            wait_if_paused()
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelled()
            batch = cue_list[offset: offset + batch_size]
            prepared_batch = [_translation_text_wrapper(unit.text) for unit in batch]
            source_tokens = [
                _encode_translation_source(tokenizer, payload, target_language)
                for payload, _prefix, _suffix in prepared_batch
            ]
            longest_input = max((len(tokens) for tokens in source_tokens), default=1)
            # MADLAD can otherwise spend hundreds of decoding steps repeating
            # one token when Whisper produced a tiny/incomplete fragment.
            batch_max_length = min(160, max(24, longest_input * 3 + 12))
            results = translator.translate_batch(
                source_tokens,
                beam_size=4,
                repetition_penalty=1.08,
                no_repeat_ngram_size=3,
                max_decoding_length=batch_max_length,
                return_end_token=True,
            )
            for batch_index, (unit, result) in enumerate(zip(batch, results)):
                unit_index = offset + batch_index
                source_payload, wrapper_prefix, wrapper_suffix = prepared_batch[batch_index]
                text = _decode_translation_result(result, tokenizer, target_language, max_length=batch_max_length)
                reason = _translation_invalid_reason(source_payload, text)
                if reason is not None:
                    logger(
                        "G-TMCE AI Translation: suspicious decoder output at "
                        f"{srt_timestamp(unit.start)} ({reason}); retrying safely"
                    )
                    retry = _safe_retry_translation(
                        translator,
                        tokenizer,
                        SubtitleCue(unit.start, unit.end, source_payload),
                        target_language,
                    )
                    retry_reason = _translation_invalid_reason(source_payload, retry)
                    if retry and retry_reason is None:
                        text = retry
                    else:
                        rescue = _rescue_source_echo_translation(
                            translator, tokenizer, source_payload, target_language
                        )
                        rescue_reason = _translation_invalid_reason(source_payload, rescue)
                        if rescue and rescue_reason is None:
                            logger(
                                "G-TMCE AI Translation: recovered stubborn output with "
                                f"source reshaping at {srt_timestamp(unit.start)}"
                            )
                            text = rescue
                        else:
                            context_rescue = (
                                ""
                                if wrapper_prefix or wrapper_suffix
                                else _rescue_translation_with_neighbor(
                                    translator, tokenizer, cue_list, unit_index, target_language
                                )
                            )
                            context_reason = _translation_invalid_reason(
                                source_payload, context_rescue
                            )
                            if context_rescue and context_reason is None:
                                logger(
                                    "G-TMCE AI Translation: recovered stubborn output with "
                                    f"neighbour context at {srt_timestamp(unit.start)}"
                                )
                                text = context_rescue
                            else:
                                # A decoder loop is still safer to expose as the
                                # source than to write hundreds of bogus tokens.
                                # Source echoes, however, have exhausted three
                                # translation strategies before reaching here.
                                logger(
                                    "G-TMCE AI Translation: all local rescue paths failed at "
                                    f"{srt_timestamp(unit.start)} "
                                    f"({context_reason or rescue_reason or retry_reason or 'empty'}); "
                                    "preserving source as last-resort safety fallback"
                                )
                                text = source_payload
                if not text:
                    logger(
                        "G-TMCE AI Translation: empty model output after rescue; preserving source unit at "
                        f"{srt_timestamp(unit.start)}"
                    )
                    text = source_payload
                text = _restore_translation_wrapper(text, wrapper_prefix, wrapper_suffix)
                pieces = _split_translation_across_source_cues(unit.cues, text)
                if len(unit.cues) > 1 and len(pieces) < len(unit.cues):
                    logger(
                        "G-TMCE AI Translation: contextual output is too compressed to "
                        f"redistribute at {srt_timestamp(unit.start)}; translating source cues individually"
                    )
                    pieces = []
                    for source_cue in unit.cues:
                        individual = _safe_retry_translation(
                            translator, tokenizer, source_cue, target_language
                        )
                        individual_reason = _translation_invalid_reason(
                            source_cue.text, individual
                        )
                        if not individual or individual_reason is not None:
                            rescued_individual = _rescue_source_echo_translation(
                                translator, tokenizer, source_cue.text, target_language
                            )
                            rescued_reason = _translation_invalid_reason(
                                source_cue.text, rescued_individual
                            )
                            if rescued_individual and rescued_reason is None:
                                individual = rescued_individual
                            else:
                                individual = _clean_text(source_cue.text)
                        pieces.extend(
                            _split_long_translation_cue(
                                SubtitleCue(source_cue.start, source_cue.end, individual)
                            )
                        )
                translated.extend(pieces)
            completed = min(offset + len(batch), total)
            if progress is not None:
                progress(completed, total)
            logger(
                "G-TMCE AI Translation: "
                f"{completed}/{total} unit(s) complete"
            )
    except OperationCancelled:
        raise
    except UserVisibleError:
        raise
    except Exception as exc:
        raise UserVisibleError(ui_text("error_translation_failed", error=exc)) from exc

    return _rebalance_translation_timings(translated)


def _parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(value)
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def read_srt(path: Path) -> list[SubtitleCue]:
    """Read normal SRT cues for local AI translation."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        if not lines:
            continue
        timing_index = 1 if len(lines) > 1 and re.fullmatch(r"\d+", lines[0].strip()) else 0
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            continue
        left, right = (part.strip() for part in lines[timing_index].split("-->", 1))
        try:
            start = _parse_srt_timestamp(left.split()[0])
            end = _parse_srt_timestamp(right.split()[0])
        except (ValueError, IndexError):
            continue
        cue_text = "\n".join(line.strip() for line in lines[timing_index + 1:] if line.strip()).strip()
        if cue_text and end > start:
            cues.append(SubtitleCue(start, end, cue_text))
    return cues


def _parse_vtt_timestamp(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(value)
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def read_vtt(path: Path) -> list[SubtitleCue]:
    """Read WebVTT cues while keeping inline HTML-like subtitle markup."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    cues: list[SubtitleCue] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.upper() == "WEBVTT":
            index += 1
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue
        timing = line
        if "-->" not in timing and index + 1 < len(lines) and "-->" in lines[index + 1]:
            index += 1
            timing = lines[index].strip()
        if "-->" not in timing:
            index += 1
            continue
        left, right = (part.strip() for part in timing.split("-->", 1))
        try:
            start = _parse_vtt_timestamp(left.split()[0])
            end = _parse_vtt_timestamp(right.split()[0])
        except (ValueError, IndexError):
            index += 1
            continue
        index += 1
        payload: list[str] = []
        while index < len(lines) and lines[index].strip():
            payload.append(lines[index].strip())
            index += 1
        cue_text = "\n".join(line.strip() for line in payload if line.strip()).strip()
        if cue_text and end > start:
            cues.append(SubtitleCue(start, end, cue_text))
    return cues


def _ass_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[.](\d{1,2})", value.strip())
    if not match:
        raise ValueError(value)
    hours, minutes, seconds, centis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + centis / (10 if centis < 10 else 100)


def _ass_text_to_srt_markup(text: str) -> str:
    value = str(text or "").replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
    value = re.sub(r"\{[^}]*\\i1[^}]*\}", "<i>", value, flags=re.IGNORECASE)
    value = re.sub(r"\{[^}]*\\i0[^}]*\}", "</i>", value, flags=re.IGNORECASE)
    value = re.sub(r"\{[^}]*\}", "", value)
    # Keep tags balanced for the common whole/partial italic cases.
    if value.count("<i>") > value.count("</i>"):
        value += "</i>" * (value.count("<i>") - value.count("</i>"))
    return "\n".join(_clean_text(line) for line in value.splitlines() if _clean_text(line))


def read_ass_ssa(path: Path) -> list[SubtitleCue]:
    """Read ASS/SSA Events dialogue and convert portable styling to SRT markup."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    in_events = False
    fields: list[str] = []
    cues: list[SubtitleCue] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_events = line.casefold() == "[events]"
            continue
        if not in_events:
            continue
        if line.casefold().startswith("format:"):
            fields = [item.strip().casefold() for item in line.split(":", 1)[1].split(",")]
            continue
        if not line.casefold().startswith("dialogue:"):
            continue
        payload = line.split(":", 1)[1].lstrip()
        if not fields:
            # Standard ASS field order fallback.
            fields = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
        parts = payload.split(",", len(fields) - 1)
        if len(parts) < len(fields):
            continue
        row = dict(zip(fields, parts))
        try:
            start = _ass_timestamp(row.get("start", ""))
            end = _ass_timestamp(row.get("end", ""))
        except ValueError:
            continue
        cue_text = _ass_text_to_srt_markup(row.get("text", ""))
        if cue_text and end > start:
            cues.append(SubtitleCue(start, end, cue_text))
    return cues


def read_subtitle_for_translation(path: Path) -> list[SubtitleCue]:
    path = Path(path)
    suffix = path.suffix.casefold()
    if suffix == ".srt":
        return read_srt(path)
    if suffix == ".vtt":
        return read_vtt(path)
    if suffix in {".ass", ".ssa"}:
        return read_ass_ssa(path)
    raise UserVisibleError(f"Unsupported subtitle format: {path.suffix or path.name}")




def _strict_translation_parts(text: str) -> list[tuple[str, str]]:
    """Split subtitle text into translatable and literal formatting parts.

    Existing subtitle files are authored/timed assets, not ASR output.  Their
    cue structure and presentation markup therefore must never be rewritten by
    the MT model.  HTML-like tags and ASS override blocks are emitted verbatim;
    SDH brackets are structural delimiters while their visible payload remains
    translatable.
    """
    value = str(text or "")
    token_re = re.compile(r"(<[^>]+>|\{[^{}]*\\[^{}]*\}|\[[^\[\]]*\])")
    parts: list[tuple[str, str]] = []
    cursor = 0
    for match in token_re.finditer(value):
        if match.start() > cursor:
            parts.append(("text", value[cursor:match.start()]))
        token = match.group(0)
        if token.startswith("[") and token.endswith("]"):
            parts.append(("literal", "["))
            if token[1:-1]:
                parts.append(("text", token[1:-1]))
            parts.append(("literal", "]"))
        else:
            parts.append(("literal", token))
        cursor = match.end()
    if cursor < len(value):
        parts.append(("text", value[cursor:]))
    return parts



def _translation_clauses(value: str) -> list[str]:
    # Ignore trailing punctuation and display wrapping: neither is a clause.
    return [part.strip() for part in re.split(r"[.!?;…。,，；！？]+", value) if part.strip()]


def _near_duplicate_translation_clauses(left: str, right: str) -> bool:
    """Compare alternative renderings without language-specific dictionaries."""
    lt = _translation_word_tokens(left)
    rt = _translation_word_tokens(right)
    if not lt or not rt:
        return False
    normal_left = " ".join(lt)
    normal_right = " ".join(rt)
    if SequenceMatcher(None, normal_left, normal_right).ratio() >= 0.78:
        return True
    remaining = list(rt)
    matches = 0
    for token in lt:
        for index, other in enumerate(remaining):
            if token == other or (
                min(len(token), len(other)) >= 3
                and token[:3] == other[:3]
                and SequenceMatcher(None, token, other).ratio() >= 0.58
            ):
                matches += 1
                remaining.pop(index)
                break
    return matches >= 2 and matches / min(len(lt), len(rt)) >= 0.66


def _has_adjacent_translation_duplicate(value: str) -> bool:
    clauses = _translation_clauses(value)
    return any(_near_duplicate_translation_clauses(a, b) for a, b in zip(clauses, clauses[1:]))


def _remove_translation_clause_duplicates(source: str, output: str) -> str:
    """Last-resort repair of demonstrable doubled alternatives, not dialogue.

    Only remove adjacent near-duplicates when the source has fewer clauses and
    does not repeat itself. No movie phrases, target words or translations are
    substituted here. Normal QA still runs on the repaired candidate.
    """
    if _has_adjacent_translation_duplicate(source):
        return output
    # Check complete sentences first. Commas inside a second alternative
    # must not disguise the repeated sentence as several unrelated clauses.
    sentence_spans = _translation_sentence_spans(output)
    if len(_translation_sentence_spans(source)) == 1 and len(sentence_spans) > 1:
        first = sentence_spans[0]
        if all(_near_duplicate_translation_clauses(first, other) for other in sentence_spans[1:]):
            output = first
    source_count = len(_translation_clauses(source))
    spans = list(re.finditer(r"[^.!?;…。,，；！？]+[.!?;…。,，；！？]*", output))
    if len(spans) <= source_count:
        return output
    kept: list[str] = []
    removed = 0
    for span in spans:
        current = span.group().strip()
        if kept and len(spans) - removed > source_count and _near_duplicate_translation_clauses(kept[-1], current):
            # The last duplicate often carries the sentence-ending punctuation.
            # Preserve that ending on the original rendering.
            ending = re.search(r"[.!?…。！？]+$", current)
            if ending:
                kept[-1] = re.sub(r"[.!?…。,;，；！？]+$", "", kept[-1]) + ending.group()
            removed += 1
        else:
            kept.append(current)
    prefix = output[:spans[0].start()] if spans else ""
    return prefix + " ".join(kept) if removed else output


def _translation_sentence_spans(value: str) -> list[str]:
    # MT sometimes omits the space after a full stop. Ignore decimals and
    # single-letter initials rather than treating every dot as a sentence.
    boundaries = []
    for match in re.finditer(r"[.!?…。！？]+[\"'’”»)]*", value):
        end = match.end()
        if end == len(value):
            continue
        if not re.search(r"[^\W\d_]", value[:match.start()], flags=re.UNICODE):
            continue
        if value[end].isdigit():
            continue
        if match.group() == "." and re.search(r"(?:^|[^\w])\w$", value[:match.start()]):
            continue
        boundaries.append(end)
    pieces = []
    start = 0
    for end in boundaries + [len(value)]:
        piece = value[start:end].strip()
        if piece:
            pieces.append(piece)
        start = end
    return pieces


def _uses_unspaced_translation_script(value: str) -> bool:
    return bool(re.search(r"[\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u3040-\u30ff\u3400-\u9fff]", value))


def _strict_translation_quality_reason(source: str, output: str) -> str | None:
    """Conservative language-agnostic QA for authored subtitle translation.

    The check deliberately relies on structure and relative size instead of a
    source/target-language word list.  That keeps the same safety policy for
    every supported language pair.
    """
    base = _translation_invalid_reason(source, output)
    if base is not None:
        return base

    src = _clean_text(source)
    dst = _clean_text(output)
    if not src or not dst:
        return "empty"

    src_words = _translation_word_tokens(src)
    dst_words = _translation_word_tokens(dst)
    sw = len(src_words)
    dw = len(dst_words)
    comparable_words = not (_uses_unspaced_translation_script(src) or _uses_unspaced_translation_script(dst))
    src_chars = len(re.sub(r"[\W_]", "", src, flags=re.UNICODE))
    dst_chars = len(re.sub(r"[\W_]", "", dst, flags=re.UNICODE))

    # Exact source echoes are suspicious for real dialogue of useful length,
    # regardless of which language is the source.  Very short names/labels are
    # exempt because they often should survive translation unchanged.
    if _normalised_translation_text(src) == _normalised_translation_text(dst):
        if sw >= 3 or len(src) >= 18 or re.search(r"[.!?…]$", src):
            return "source-echo-generic"

    # Catch dropped clauses / hallucinated elaborations.  Limits are generous
    # enough for naturally expanding language pairs but strict enough to catch
    # the failures seen in authored subtitle translation.
    # Agglutinative languages can express several source words in one target
    # word. A low word count alone is not evidence of missing dialogue.
    if comparable_words and sw >= 4 and dw <= max(1, int(sw * 0.55)) and dst_chars < src_chars * 0.55:
        return f"probable-omission:{sw}->{dw}"
    if comparable_words and sw >= 5 and dw > max(sw + 4, int(sw * 1.60)):
        return f"probable-expansion:{sw}->{dw}"
    # Tiny labels/names are where MT models most often emit both the source and
    # a transliterated/translated duplicate (for example "V-Max. V-Maks.").
    # Allow one extra word, but reject a doubled short span.
    if comparable_words and 1 <= sw <= 3 and dw >= max(sw + 2, sw * 2):
        return f"probable-short-duplication:{sw}->{dw}"

    # Catch duplicated/paraphrased output fragments inside a single translated
    # span. MT decoders sometimes emit two near-equivalent Turkish renderings
    # for one source clause (for example "... düşünüyordum. Aynı şeyi düşündüm"
    # or "... zorundadır, ... yapmalıdır"). Compare adjacent output clauses
    # conservatively and only reject them when the source does not contain a
    # matching amount of clause structure. This stays language-pair agnostic.
    src_clause_count = len(_translation_clauses(src))
    dst_clause_count = len(_translation_clauses(dst))
    if (
        dst_clause_count > src_clause_count
        and _has_adjacent_translation_duplicate(dst)
        and not _has_adjacent_translation_duplicate(src)
    ):
        return f"probable-output-duplication:{src_clause_count}->{dst_clause_count}"
    if comparable_words and sw >= 4 and dst_clause_count > src_clause_count and dw >= sw + 3:
        return f"probable-clause-expansion:{src_clause_count}->{dst_clause_count}"
    if comparable_words and sw >= 4 and dst_clause_count >= src_clause_count + 2 and dst_chars > src_chars * 1.5:
        return f"probable-clause-expansion:{src_clause_count}->{dst_clause_count}"

    # Named entities should normally survive translation, but the model must
    # not invent extra repetitions of them.  This catches outputs such as
    # "... Peter Parker ... Peter Parker" when the source mentions the name
    # once, without assuming any specific source or target language.
    proper_tokens = re.findall(r"(?<![.!?]\s)\b[A-ZÀ-ÖØ-Þ][\w’'-]{2,}\b", src, flags=re.UNICODE)
    for token in set(proper_tokens):
        src_count = len(re.findall(rf"\b{re.escape(token)}\b", src, flags=re.IGNORECASE | re.UNICODE))
        dst_count = len(re.findall(rf"\b{re.escape(token)}\b", dst, flags=re.IGNORECASE | re.UNICODE))
        if src_count >= 1 and dst_count > src_count:
            return f"proper-name-duplication:{token}:{src_count}->{dst_count}"

    # Losing a whole clause is a common subtitle-MT failure even when the raw
    # word ratio still looks plausible (for example "Hey ... Whoa ..." ->
    # only "Hey ...").  Clause punctuation is language-agnostic enough to
    # use as a conservative coverage signal.
    src_clauses = len(re.findall(r"[,;:!?…]+", src))
    dst_clauses = len(re.findall(r"[,;:!?…]+", dst))
    if sw >= 5 and src_clauses >= 2 and dst_clauses == 0:
        return f"probable-clause-loss:{src_clauses}->{dst_clauses}"

    # Character ratios help for languages where whitespace token counts are not
    # meaningful (CJK is the important case).  Ignore punctuation and spaces.
    src_chars = len(re.sub(r"[\W_]", "", src, flags=re.UNICODE))
    dst_chars = len(re.sub(r"[\W_]", "", dst, flags=re.UNICODE))
    if src_chars >= 16:
        cross_script = _uses_unspaced_translation_script(src) != _uses_unspaced_translation_script(dst)
        # A Han character can carry the information of several Latin letters.
        # Raw character ratios are not interchangeable between writing systems.
        minimum_ratio = 0.10 if cross_script else 0.24
        maximum_ratio = 6.0 if cross_script else 3.4
        if dst_chars < max(3, int(src_chars * minimum_ratio)):
            return f"probable-char-omission:{src_chars}->{dst_chars}"
        if dst_chars > max(src_chars + 28, int(src_chars * maximum_ratio)):
            return f"probable-char-expansion:{src_chars}->{dst_chars}"

    # A translation must not silently delete one side of a two-speaker cue.
    # Lines are translated independently, but this guards direct helper use too.
    src_speakers = len(re.findall(r"(?m)^\s*[-–—]\s*\S", str(source or "")))
    dst_speakers = len(re.findall(r"(?m)^\s*[-–—]\s*\S", str(output or "")))
    if src_speakers and src_speakers != dst_speakers:
        return f"speaker-count:{src_speakers}->{dst_speakers}"

    return None


def _strict_candidate_penalty(source: str, output: str) -> float:
    """Rank suspicious candidates when no decode passes the hard QA gate."""
    if not output:
        return 1_000_000.0
    reason = _strict_translation_quality_reason(source, output)
    src_words = max(1, len(_translation_word_tokens(source)))
    dst_words = max(1, len(_translation_word_tokens(output)))
    src_chars = max(1, len(re.sub(r"[\W_]", "", source, flags=re.UNICODE)))
    dst_chars = max(1, len(re.sub(r"[\W_]", "", output, flags=re.UNICODE)))
    word_weight = 0.0 if _uses_unspaced_translation_script(source) or _uses_unspaced_translation_script(output) else 12.0
    penalty = abs(dst_words / src_words - 1.0) * word_weight + abs(dst_chars / src_chars - 1.0) * 4.0
    if reason:
        penalty += 25.0
        if reason.startswith("source-echo"):
            penalty += 18.0
        elif "omission" in reason or "clause-loss" in reason:
            penalty += 14.0
        elif "expansion" in reason:
            penalty += 12.0
    return penalty


def _strip_authored_markup_for_context(text: str) -> str:
    """Return only visible text for neighbouring-cue translation context."""
    visible = "".join(value for kind, value in _strict_translation_parts(text) if kind == "text")
    visible = re.sub(r"(?m)^\s*[-–—]\s*", "", visible)
    return _clean_text(visible)


def _strict_context_translation(
    translator: Any,
    tokenizer: Any,
    source: str,
    target_language: str,
    previous_context: str = "",
    next_context: str = "",
) -> str:
    """Translate the current span together with neighbours, returning only it.

    MADLAD is a translation model rather than an instruction-following chat
    model.  Stable separators are therefore more reliable than natural-language
    prompts for supplying context without letting context leak into the result.
    """
    current = _clean_text(source)
    previous = _clean_text(previous_context)
    following = _clean_text(next_context)
    if not current or not (previous or following):
        return ""

    sep = " ||| "
    segments: list[str] = []
    current_index = 0
    if previous:
        segments.append(previous)
        current_index += 1
    segments.append(current)
    if following:
        segments.append(following)
    combined = sep.join(segments)
    translated = _decode_single_translation(
        translator,
        tokenizer,
        combined,
        target_language,
        beam_size=3,
        repetition_penalty=1.12,
        no_repeat_ngram_size=3,
        length_factor=2.15,
        length_extra=10,
    )
    parts = [part.strip() for part in re.split(r"\s*\|\s*\|\s*\|\s*", translated)]
    if len(parts) != len(segments):
        return ""
    candidate = _clean_text(parts[current_index])
    return candidate if candidate else ""


def _strict_retry_translation(
    translator: Any,
    tokenizer: Any,
    source: str,
    target_language: str,
    *,
    retry_attempts: int = 2,
) -> str:
    """Retry authored text with conservative decodes and return best candidate."""
    source = _clean_text(source)
    attempts = (
        # Do not prohibit recurring subword ngrams on rescue decodes: normal
        # inflection and legitimate repeated words also share SentencePieces.
        # Give cross-script translations room to finish, then check coverage.
        dict(beam_size=1, repetition_penalty=1.20, no_repeat_ngram_size=0, length_factor=3.0, length_extra=12),
        dict(beam_size=2, repetition_penalty=1.14, no_repeat_ngram_size=0, length_factor=3.0, length_extra=12),
        dict(beam_size=4, repetition_penalty=1.10, no_repeat_ngram_size=0, length_factor=3.5, length_extra=12),
    )
    best = ""
    best_penalty = 10**9
    for settings in attempts[:max(1, min(len(attempts), int(retry_attempts)))]:
        candidate = _decode_single_translation(
            translator, tokenizer, source, target_language, **settings
        )
        if not candidate:
            continue
        reason = _strict_translation_quality_reason(source, candidate)
        if reason is None:
            return candidate
        # Keep the least size-distorted fallback in case every decoder profile
        # is suspicious.  It is only used after all retries are exhausted.
        penalty = _strict_candidate_penalty(source, candidate)
        if penalty < best_penalty:
            best = candidate
            best_penalty = penalty
    return best


def _strict_sentence_retry_translation(
    translator: Any, tokenizer: Any, source: str, target_language: str,
) -> str:
    """Rescue omitted complete sentences without any language/phrase rewrites."""
    parts = [p.strip() for p in re.split(r"(?<=[!?…。！？])\s+|(?<=\.)\s+(?=[\w\"'“‘])", source) if p.strip()]
    if not 2 <= len(parts) <= 4:
        return ""
    translated: list[str] = []
    for part in parts:
        candidate = _strict_retry_translation(
            translator, tokenizer, part, target_language, retry_attempts=2,
        )
        if not candidate or _strict_translation_quality_reason(part, candidate) is not None:
            return ""
        translated.append(candidate)
    result = " ".join(translated)
    return result if _strict_translation_quality_reason(source, result) is None else ""


def _translate_payload_strict(
    translator: Any,
    tokenizer: Any,
    source: str,
    target_language: str,
    *,
    previous_context: str = "",
    next_context: str = "",
    qa_events: set[str] | None = None,
    initial_candidate: str | None = None,
    quality_profile: str = "balanced",
) -> str:
    """Translate one visible subtitle span with QA, context and retry."""
    raw = str(source or "")
    leading = raw[: len(raw) - len(raw.lstrip())]
    trailing = raw[len(raw.rstrip()):] if raw.rstrip() != raw else ""
    body = raw.strip()

    speaker_prefix = ""
    speaker_match = re.match(r"^([-–—]\s*)", body)
    if speaker_match:
        speaker_prefix = speaker_match.group(1)
        body = body[speaker_match.end():].lstrip()

    payload = _clean_text(body)
    if not payload:
        return raw
    if not re.search(r"[^\W\d_]", payload, flags=re.UNICODE):
        return raw

    profile_key = _normalise_translation_quality_profile(quality_profile)
    profile = AI_TRANSLATION_QUALITY_PROFILES[profile_key]
    candidates: list[str] = []
    initial = _clean_text(initial_candidate or "")
    if not initial:
        initial = _decode_single_translation(
            translator, tokenizer, payload, target_language,
            beam_size=int(profile["beam_size"]),
            repetition_penalty=float(profile["repetition_penalty"]),
            no_repeat_ngram_size=int(profile["no_repeat_ngram_size"]),
            length_factor=float(profile["length_factor"]),
            length_extra=int(profile["length_extra"]),
        )
    if initial:
        candidates.append(initial)

    initial_reason = _strict_translation_quality_reason(payload, initial)
    short_dialogue = len(_translation_word_tokens(payload)) <= 9
    fidelity = getattr(translator, "reconstruction_score", None)
    uncertain = callable(fidelity) and initial and fidelity(payload, initial) < -2.5
    # Structural QA alone cannot detect changed polarity or a wrong sense.
    # Short dialogue can use neighbours, but candidates must compete against
    # the original source instead of automatically accepting the last decode.
    use_context = initial_reason is not None or uncertain or (
        profile.get("context_mode") == "short_or_fail" and short_dialogue
    )
    if use_context and (previous_context or next_context):
        contextual = _strict_context_translation(
            translator, tokenizer, payload, target_language,
            previous_context=previous_context, next_context=next_context,
        )
        if contextual and contextual not in candidates:
            candidates.append(contextual)
            if qa_events is not None:
                qa_events.add("context")

    valid = [c for c in candidates if _strict_translation_quality_reason(payload, c) is None]
    if uncertain and not _cue_finishes_sentence(payload):
        # An authored fragment can be mistaken for a different sense. A
        # punctuation-only decode variant gives it a complete-input boundary;
        # it never supplies a replacement phrase or a target-language word.
        variant = _decode_single_translation(
            translator, tokenizer, payload.rstrip(",;:") + ".", target_language,
            beam_size=4, repetition_penalty=1.0, no_repeat_ngram_size=0,
            length_factor=3.0, length_extra=12,
        )
        if variant and _strict_translation_quality_reason(payload, variant) is None:
            valid.append(variant)
            if qa_events is not None:
                qa_events.add("retry")
    if valid and callable(fidelity):
        rank = getattr(translator, "candidate_score", None)
        candidate = max(valid, key=lambda c: rank(payload, c, target_language) if callable(rank) else fidelity(payload, c))
    elif len(candidates) > 1 and _strict_translation_quality_reason(payload, candidates[-1]) is None:
        candidate = candidates[-1]
    elif valid:
        candidate = min(valid, key=lambda c: _strict_candidate_penalty(payload, c))
    else:
        candidate = ""

    if not candidate:
        if qa_events is not None:
            qa_events.add("retry")
        retry = _strict_retry_translation(
            translator, tokenizer, payload, target_language,
            retry_attempts=int(profile.get("retry_attempts", 2)),
        )
        if retry:
            candidates.append(retry)
            if _strict_translation_quality_reason(payload, retry) is None:
                candidate = retry

    if not candidate:
        rescue = _strict_sentence_retry_translation(translator, tokenizer, payload, target_language)
        if rescue:
            candidates.append(rescue)
            if _strict_translation_quality_reason(payload, rescue) is None:
                candidate = rescue

    if not candidate and (previous_context or next_context):
        rescue_context = _strict_context_translation(
            translator, tokenizer, payload, target_language,
            previous_context=previous_context, next_context=next_context,
        )
        if rescue_context:
            candidates.append(rescue_context)
            if _strict_translation_quality_reason(payload, rescue_context) is None:
                candidate = rescue_context
                if qa_events is not None:
                    qa_events.add("context")

    if not candidate:
        # Retry first; only if decoding cannot resolve an obvious duplicated
        # alternative do we consider a conservative structural repair.
        repaired = [_remove_translation_clause_duplicates(payload, c) for c in candidates]
        repaired = [c for c in repaired if _strict_translation_quality_reason(payload, c) is None]
        if repaired:
            candidate = min(repaired, key=lambda c: _strict_candidate_penalty(payload, c))
            if qa_events is not None:
                qa_events.add("deduplicated")

    if not candidate:
        # Do not silently replace a suspicious translation with the source.  Keep
        # the least-risk candidate and explicitly mark this cue for review.
        usable = [c for c in candidates if c]
        candidate = min(usable, key=lambda c: _strict_candidate_penalty(payload, c)) if usable else payload
        if qa_events is not None:
            qa_events.add("review")

    candidate = _clean_text(candidate)
    if callable(fidelity) and len(_translation_word_tokens(payload)) >= 3 and fidelity(payload, candidate) < -2.5:
        if qa_events is not None:
            qa_events.add("review")
            qa_events.add("low_fidelity")
    # The model sometimes adds a dialogue dash even when translating only
    # the text after the authored dash. Speaker markers belong to the source
    # layout; restoring its single prefix must not produce "- - Yes".
    candidate = re.sub(r"^[-–—]\s+", "", candidate)
    if not _uses_unspaced_translation_script(candidate):
        # Repair missing spaces at genuine sentence boundaries, but leave
        # initials, decimals and unspaced writing systems untouched.
        candidate = " ".join(_translation_sentence_spans(candidate))
    return f"{leading}{speaker_prefix}{candidate}{trailing}"


def _authored_translation_lines(value: str) -> list[str]:
    """Join visual wrapping, retaining only explicit speaker boundaries.

    A newline in an authored subtitle is usually typesetting, not the end of a
    sentence. Sending each half to MT independently invents endings and loses
    meaning. An explicit dialogue dash still starts a separate speaker span.
    """
    groups: list[str] = []
    for line in str(value).splitlines():
        content = line.strip()
        if not content:
            continue
        if groups and not re.match(r"^[-–—]\s*\S", content):
            groups[-1] += " " + content
        else:
            groups.append(content)
    if groups:
        # Spaces around inline style/SDH boundaries still separate words.
        if value[:1].isspace():
            leading = value[:len(value) - len(value.lstrip())]
            groups[0] = ("\n" if "\n" in leading else " ") + groups[0]
        if value[-1:].isspace():
            trailing = value[len(value.rstrip()):]
            groups[-1] += "\n" if "\n" in trailing else " "
    return groups or [value]


def _authored_translation_segments(value: str) -> list[str]:
    """Keep each completed sentence, including short repeated commands.

    Translating several sentences at once can omit the final short ones even
    when the overall output looks plausible. This also preserves intentional
    repetitions without asking a repetition-penalized decoder to recreate them.
    """
    segments: list[str] = []
    for line in _authored_translation_lines(value):
        leading = line[:len(line) - len(line.lstrip())]
        trailing = line[len(line.rstrip()):]
        pieces: list[str] = []
        for piece in _translation_sentence_spans(line.strip()):
            if pieces and re.search(r"(?:\.{2,}|…)[\"'’”»)]*$", pieces[-1]):
                pieces[-1] += " " + piece
            else:
                pieces.append(piece)
        # A comma-separated repeated command is authored repetition too.
        # Sending the whole run to MT often contracts five repetitions into
        # two or three. Only split an exact repeated utterance, never ordinary
        # lists or clauses which merely share a few words.
        repeated: list[str] = []
        for piece in pieces:
            clauses = [m.group().strip() for m in re.finditer(r"[^,，،、]+[,，،、]?", piece) if m.group().strip()]
            keys = [_normalised_translation_text(c) for c in clauses]
            if len(keys) >= 2 and keys[0] and len(set(keys)) == 1:
                repeated.extend(clauses)
            else:
                repeated.append(piece)
        pieces = repeated
        if pieces:
            pieces[0] = leading + pieces[0]
            pieces[-1] += trailing
            segments.extend(pieces)
    return segments or [value]


def _translate_existing_cue_text_strict_with_qa(
    translator: Any,
    tokenizer: Any,
    text: str,
    target_language: str,
    *,
    previous_context: str = "",
    next_context: str = "",
    initial_candidates: list[str] | None = None,
    quality_profile: str = "balanced",
) -> tuple[str, set[str]]:
    """Translate one authored cue and return its QA events."""
    parts = _strict_translation_parts(text)
    initial_iter = iter(initial_candidates or [])
    translated: list[str] = []
    qa_events: set[str] = set()
    has_literal_markup = any(kind == "literal" for kind, _value in parts)
    for kind, value in parts:
        if kind == "literal":
            translated.append(value)
        else:
            line_parts = _authored_translation_segments(value)
            single_speaker = len(_authored_translation_lines(value)) == 1
            previous_utterance = ""
            previous_translation = ""
            for line_index, content in enumerate(line_parts):
                if line_index:
                    translated.append("\n")
                initial_candidate = next(initial_iter, None)
                # Adjacent identical utterances from one speaker should not
                # become unrelated synonyms solely because their punctuation
                # or neighbour context differs. Reuse words, not punctuation
                # or the previous utterance's speaker dash. Never cross styles
                # or explicit speaker boundaries.
                body = re.sub(r"^[-–—]\s*", "", content.strip())
                utterance = re.sub(r"[,，،、.!?。！？]+$", "", body).strip().casefold()
                if (single_speaker and utterance and utterance == previous_utterance
                        and re.search(r"[,，،、.!?。！？]+$", previous_translation.strip())):
                    words = re.sub(r"^[-–—]\s*", "", previous_translation.strip())
                    words = re.sub(r"[,，،、.!?。！？]+$", "", words).rstrip()
                    ending = re.search(r"[,，،、.!?。！？]+$", body)
                    prefix = re.match(r"^([-–—]\s*)", content.strip())
                    leading = content[:len(content) - len(content.lstrip())]
                    trailing = content[len(content.rstrip()):]
                    translated.append(leading + (prefix.group(1) if prefix else "") + words
                                      + (ending.group() if ending else "") + trailing)
                    continue
                try:
                    translated_piece = _translate_payload_strict(
                        translator, tokenizer, content, target_language,
                        previous_context=line_parts[line_index - 1] if single_speaker and line_index > 0 else previous_context,
                        next_context=line_parts[line_index + 1] if single_speaker and line_index + 1 < len(line_parts) else next_context,
                        qa_events=qa_events,
                        initial_candidate=initial_candidate,
                        quality_profile=quality_profile,
                    )
                except TypeError as exc:
                    # Preserve compatibility with integrations/tests that replace
                    # the legacy four-argument helper with a simple callable.
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    translated_piece = _translate_payload_strict(
                        translator, tokenizer, content, target_language
                    )
                translated.append(translated_piece)
                previous_utterance = utterance
                previous_translation = translated_piece
    result = "".join(translated).strip()
    if result and not has_literal_markup:
        if "\n" in result:
            result = "\n".join(_wrap_subtitle_text(line) for line in result.splitlines())
        else:
            result = _wrap_subtitle_text(result)
    return result, qa_events


def _translate_existing_cue_text_strict(
    translator: Any,
    tokenizer: Any,
    text: str,
    target_language: str,
) -> str:
    result, _events = _translate_existing_cue_text_strict_with_qa(
        translator, tokenizer, text, target_language
    )
    return result


def _strict_cue_payloads(text: str) -> list[str]:
    """Return payloads in the exact order consumed by strict cue translation."""
    payloads: list[str] = []
    for kind, value in _strict_translation_parts(text):
        if kind != "text":
            continue
        for content in _authored_translation_segments(value):
            body = content.strip()
            speaker_match = re.match(r"^([-–—]\s*)", body)
            if speaker_match:
                body = body[speaker_match.end():].lstrip()
            payload = _clean_text(body)
            if payload and re.search(r"[^\W\d_]", payload, flags=re.UNICODE):
                payloads.append(payload)
            else:
                payloads.append("")
    return payloads


def _authored_sentence_payload(text: str) -> tuple[str, str, str] | None:
    """Detach whole-cue styles for safe sentence context across timed cues.

    Inline styling, SDH descriptions and multi-speaker cues stay on the
    span-preserving path. Never merge different presentation/positioning.
    """
    parts = _strict_translation_parts(text)
    indices = [i for i, (kind, value) in enumerate(parts) if kind == "text" and value.strip()]
    if len(indices) != 1 or any(value in {"[", "]"} for kind, value in parts if kind == "literal"):
        return None
    index = indices[0]
    value = parts[index][1]
    if len(_authored_translation_segments(value)) != 1 or re.match(r"^\s*[-–—]", value):
        return None
    prefix = "".join(v for _kind, v in parts[:index])
    suffix = "".join(v for _kind, v in parts[index + 1:])
    return _clean_text(value), prefix, suffix


def _authored_sentence_groups(items: list[SubtitleCue]) -> list[list[int]]:
    """Group only nearby continuations of an unfinished source sentence."""
    groups: list[list[int]] = []
    index = 0
    while index < len(items):
        current = _authored_sentence_payload(items[index].text)
        group = [index]
        length = len(current[0]) if current else 0
        while current and index + 1 < len(items) and len(group) < 4:
            following = _authored_sentence_payload(items[index + 1].text)
            gap = items[index + 1].start - items[index].end
            if (not following or _cue_finishes_sentence(current[0])
                    or current[1:] != following[1:] or not 0 <= gap <= 1.25
                    or length + 1 + len(following[0]) > 320):
                break
            index += 1
            group.append(index)
            length += 1 + len(following[0])
            current = following
        if len(group) > 1:
            groups.append(group)
        index += 1
    return groups


def _distribute_authored_sentence(text: str, sources: list[str]) -> list[str]:
    """Allocate contextual MT text to original windows without word duplication."""
    text = _clean_text(text)
    # Whitespace boundaries for spaced scripts; character boundaries for
    # scripts where words are not separated. Never assume target word counts.
    if _uses_unspaced_translation_script(text):
        boundaries = list(range(1, len(text)))
    else:
        boundaries = [match.start() for match in re.finditer(r"\s+", text)]
    if len(boundaries) < len(sources) - 1:
        return []
    weights = [max(1, len(_clean_text(source))) for source in sources]
    total = sum(weights)
    offset = 0
    cumulative = 0
    pieces: list[str] = []
    for index, weight in enumerate(weights[:-1]):
        cumulative += weight
        ideal = len(text) * cumulative / total
        available = [boundary for boundary in boundaries if boundary > offset]
        remaining = len(sources) - index - 2
        if remaining:
            available = available[:-remaining]
        if not available:
            return []
        boundary = min(available, key=lambda b: abs(b - ideal) - (1.5 if text[b - 1] in ",;.!?…。，；！？" else 0))
        pieces.append(text[offset:boundary].strip())
        offset = boundary
    pieces.append(text[offset:].strip())
    return pieces if all(pieces) else []


def translate_existing_subtitle_cues_with_ai(
    cues: Iterable[SubtitleCue],
    source_language: str,
    target_language: str,
    *,
    model_name: str | None = None,
    cancel_event: Any | None = None,
    pause_event: Any | None = None,
    progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
    qa_report: dict[str, Any] | None = None,
    quality_profile: str = "balanced",
) -> list[SubtitleCue]:
    """Translate an authored subtitle with cue count/timestamps hard-locked.

    This path is language-pair agnostic. Unfinished sentences can share MT
    context, but their text is distributed back to the original cue windows.
    The model cannot rewrite subtitle formatting. Readability splitting is a
    separate deterministic pass after source-structure validation.
    """
    source_language = normalise_asr_language(source_language)
    target_language = normalise_asr_language(target_language)
    if target_language not in TRANSLATION_TARGET_CODES:
        raise UserVisibleError(
            ui_text("error_translation_target_unsupported", language=target_language)
        )
    if target_language == source_language:
        raise UserVisibleError(
            ui_text("error_translation_same_language", language=target_language)
        )
    items = [cue for cue in cues if cue.text.strip() and cue.end > cue.start]
    if not items:
        return []

    logger = log or (lambda _message: None)
    profile_key = _normalise_translation_quality_profile(quality_profile)
    profile = AI_TRANSLATION_QUALITY_PROFILES[profile_key]

    def wait_if_paused() -> None:
        while pause_event is not None and pause_event.is_set():
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelled()
            time.sleep(0.12)

    model_name = (
        model_name or os.environ.get("GTMCE_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL)
    ).strip() or DEFAULT_TRANSLATION_MODEL
    model_path = _prepare_translation_model(model_name, logger, cancel_event)
    translator, tokenizer = _load_translation_runtime(model_path, logger)
    if source_language in TRANSLATION_TARGET_CODES and callable(getattr(translator, "score_batch", None)):
        translator = _FaithfulSubtitleTranslator(translator, tokenizer, source_language, cancel_event, pause_event)
        logger("G-TMCE AI Translation: source-reconstruction ranking enabled (same local model, bounded alternatives)")
    total = len(items)
    logger(
        "G-TMCE AI Translation: strict authored-subtitle mode; "
        f"{total} cue(s), {source_language}->{target_language}; timings/markup locked; "
        f"quality={profile_key}"
    )
    output: list[SubtitleCue] = []
    retried_cues = 0
    context_cues = 0
    review_items: list[dict[str, Any]] = []
    contextual_by_cue: dict[int, tuple[str, set[str]]] = {}
    sentence_groups = _authored_sentence_groups(items)
    group_payloads = [
        " ".join(_authored_sentence_payload(items[i].text)[0] for i in group)
        for group in sentence_groups
    ]
    env_batch = os.environ.get("GTMCE_TRANSLATION_BATCH_SIZE", "").strip()
    batch_size = max(4, min(64, int(env_batch or profile["batch_size"])))
    can_batch = callable(getattr(tokenizer, "encode", None)) and callable(getattr(translator, "translate_batch", None))
    initial_groups = ["" for _ in sentence_groups]
    group_by_first_cue = {group[0]: i for i, group in enumerate(sentence_groups)}
    grouped_indices = {i for group in sentence_groups for i in group}
    group_end_by_cue = {i: group[-1] + 1 for group in sentence_groups for i in group}
    if sentence_groups:
        logger(f"G-TMCE AI Translation: {len(sentence_groups)} unfinished sentence group(s) share translation context; original cue windows retained")

    # Prepare metadata only. Decode and finish QA for a small chronological
    # window before advancing, rather than translating the entire file while
    # progress remains at zero. Sentence groups must never cross a window.
    per_cue_payloads = [_strict_cue_payloads(cue.text) for cue in items]
    initial_by_cue: list[list[str]] = [["" for _ in payloads] for payloads in per_cue_payloads]
    prepared_until = 0
    if can_batch:
        logger(f"G-TMCE AI Translation: incremental translation + QA (up to {batch_size} spans/batch)")
    else:
        logger("G-TMCE AI Translation: batch first pass unavailable; using compatibility path")

    for index, cue in enumerate(items, start=1):
        wait_if_paused()
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled()
        if index - 1 >= prepared_until:
            window_start = index - 1
            # A small warm-up window gets real completed-cue progress out
            # quickly; later windows retain useful batching throughput.
            window_size = min(batch_size, 4 if window_start == 0 else 8)
            window_end = min(total, window_start + window_size)
            window_end = max(window_end, group_end_by_cue.get(window_end - 1, window_end))
            logger(f"G-TMCE AI Translation: translating/checking cues {index}-{window_end}/{total}")
            if can_batch:
                refs: list[tuple[str, int, int, str]] = []
                for cue_idx in range(window_start, window_end):
                    if cue_idx in group_by_first_cue:
                        group_index = group_by_first_cue[cue_idx]
                        refs.append(("group", group_index, 0, group_payloads[group_index]))
                    elif cue_idx not in grouped_indices:
                        refs.extend(("cue", cue_idx, payload_idx, payload)
                                    for payload_idx, payload in enumerate(per_cue_payloads[cue_idx]) if payload)
                for offset in range(0, len(refs), batch_size):
                    wait_if_paused()
                    if cancel_event is not None and cancel_event.is_set():
                        raise OperationCancelled()
                    chunk = refs[offset:offset + batch_size]
                    decoded = _decode_translation_batch(
                        translator, tokenizer, [entry[3] for entry in chunk], target_language,
                        beam_size=int(profile["beam_size"]),
                        repetition_penalty=float(profile["repetition_penalty"]),
                        no_repeat_ngram_size=int(profile["no_repeat_ngram_size"]),
                        length_factor=float(profile["length_factor"]),
                        length_extra=int(profile["length_extra"]),
                    )
                    wait_if_paused()
                    if cancel_event is not None and cancel_event.is_set():
                        raise OperationCancelled()
                    for (kind, ref_index, payload_idx, _payload), candidate in zip(chunk, decoded):
                        if kind == "group":
                            initial_groups[ref_index] = candidate
                        else:
                            initial_by_cue[ref_index][payload_idx] = candidate
            prepared_until = window_end
        previous_context = _strip_authored_markup_for_context(items[index - 2].text) if index > 1 and 0 <= cue.start - items[index - 2].end <= 2.0 else ""
        next_context = _strip_authored_markup_for_context(items[index].text) if index < total and 0 <= items[index].start - cue.end <= 2.0 else ""
        if index - 1 in group_by_first_cue:
            group_index = group_by_first_cue[index - 1]
            group = sentence_groups[group_index]
            events: set[str] = {"sentence_context"}
            translated_sentence = _translate_payload_strict(
                translator, tokenizer, group_payloads[group_index], target_language,
                qa_events=events, quality_profile=profile_key,
                initial_candidate=initial_groups[group_index],
            )
            payloads = [_authored_sentence_payload(items[i].text) for i in group]
            pieces = _distribute_authored_sentence(translated_sentence, [p[0] for p in payloads])
            if pieces:
                for i, piece, (_source, prefix, suffix) in zip(group, pieces, payloads):
                    contextual_by_cue[i] = (prefix + piece + suffix, set(events))
        if index - 1 in contextual_by_cue:
            translated_text, events = contextual_by_cue[index - 1]
        else:
            try:
                translated_text, events = _translate_existing_cue_text_strict_with_qa(
                    translator, tokenizer, cue.text, target_language,
                    previous_context=previous_context, next_context=next_context,
                    initial_candidates=initial_by_cue[index - 1],
                    quality_profile=profile_key,
                )
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise
                translated_text, events = _translate_existing_cue_text_strict_with_qa(
                    translator, tokenizer, cue.text, target_language,
                    previous_context=previous_context, next_context=next_context,
                )
        if not translated_text:
            translated_text = cue.text
            events.add("review")
        if "retry" in events:
            retried_cues += 1
        if "context" in events or "sentence_context" in events:
            context_cues += 1
        if "review" in events:
            review_items.append({
                "cue": index,
                "start": cue.start,
                "end": cue.end,
                "source": cue.text,
                "output": translated_text,
                "reasons": sorted(events),
            })
        output.append(SubtitleCue(cue.start, cue.end, translated_text))
        if progress is not None:
            progress(index, total)

    summary = {
        "total": total,
        "successful": total - len(review_items),
        "retried": retried_cues,
        "context_used": context_cues,
        "review": len(review_items),
        "review_items": review_items,
        "quality_profile": profile_key,
        "sentence_groups": len(sentence_groups),
    }
    if qa_report is not None:
        qa_report.clear()
        qa_report.update(summary)
    logger(
        "G-TMCE AI Translation QA: "
        f"{total} cue / {summary['successful']} passed / {retried_cues} retried / "
        f"{len(review_items)} review required / {context_cues} context-assisted"
    )
    for item in review_items[:20]:
        logger(f"QA review cue {item['cue']} ({', '.join(item['reasons'])}): {item['source']!r} -> {item['output']!r}")
    return output


def _validate_strict_subtitle_translation(
    source: list[SubtitleCue], translated: list[SubtitleCue]
) -> None:
    """Refuse to finalise a translated file if source structure changed."""
    if len(source) != len(translated):
        raise UserVisibleError(
            f"AI subtitle validation failed: cue count changed ({len(source)} -> {len(translated)})."
        )
    for index, (before, after) in enumerate(zip(source, translated), start=1):
        if before.start != after.start or before.end != after.end:
            raise UserVisibleError(
                f"AI subtitle validation failed: timestamp changed at cue {index}."
            )
        source_literals = [v for k, v in _strict_translation_parts(before.text) if k == "literal"]
        target_literals = [v for k, v in _strict_translation_parts(after.text) if k == "literal"]
        if source_literals != target_literals:
            raise UserVisibleError(
                f"AI subtitle validation failed: formatting changed at cue {index}."
            )


def _subtitle_layout_units(text: str) -> list[tuple[str, tuple[str, ...], str]]:
    """Visible characters with their original presentation state.

    Reopening active styles on a split cue keeps inline/nested HTML, SDH and
    positioning separate from MT. Wrapping uses visible display width rather
    than counting markup as dialogue.
    """
    units: list[tuple[str, tuple[str, ...], str]] = []
    stack: list[str] = []
    overrides = ""
    for kind, value in _strict_translation_parts(text):
        if kind == "text":
            units.extend((char, tuple(stack), overrides) for char in value)
        elif value.startswith("{"):
            overrides += value
        elif value == "[":
            stack.append(value)
        elif value == "]":
            if not stack or stack[-1] != "[":
                raise ValueError("Unbalanced SDH wrapper")
            stack.pop()
        elif re.fullmatch(r"</\w+\s*>", value):
            name = re.match(r"</(\w+)", value).group(1).casefold()
            if not stack or not re.match(rf"<{re.escape(name)}(?:\s|>)", stack[-1], re.I):
                raise ValueError("Unbalanced subtitle style")
            stack.pop()
        elif re.fullmatch(r"<\w+(?:\s[^>]*)?>", value) and not value.endswith("/>"):
            if value.casefold() == "<br>":
                units.append(("\n", tuple(stack), overrides))
            else:
                stack.append(value)
        else:
            raise ValueError("Unsupported subtitle layout token")
    if stack:
        raise ValueError("Unclosed subtitle style")

    normalised: list[tuple[str, tuple[str, ...], str]] = []
    cursor = 0
    while cursor < len(units):
        char, styles, positioning = units[cursor]
        if not char.isspace():
            normalised.append(units[cursor])
            cursor += 1
            continue
        end = cursor + 1
        while end < len(units) and units[end][0].isspace():
            end += 1
        if normalised and end < len(units):
            # Explicit speaker lines are semantic. All other line breaks are
            # typesetting and will be recomputed for the target language.
            speaker = any(u[0] == "\n" for u in units[cursor:end]) and units[end][0] in "-–—"
            normalised.append(("\n" if speaker else " ", styles, positioning))
        cursor = end
    return normalised


def _subtitle_character_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def _render_subtitle_layout_units(units: list[tuple[str, tuple[str, ...], str]]) -> str:
    output: list[str] = []
    active: tuple[str, ...] = ()
    positioning = ""

    def close_style(style: str) -> str:
        return "]" if style == "[" else "</" + re.match(r"<(\w+)", style).group(1) + ">"

    for char, styles, overrides in units:
        common = 0
        while common < min(len(active), len(styles)) and active[common] == styles[common]:
            common += 1
        output.extend(close_style(style) for style in reversed(active[common:]))
        if overrides != positioning:
            output.append(overrides)
            positioning = overrides
        output.extend(styles[common:])
        output.append(char)
        active = styles
    output.extend(close_style(style) for style in reversed(active))
    return "".join(output)


def _subtitle_layout_boundaries(units: list[tuple[str, tuple[str, ...], str]]) -> list[int]:
    """Prefer whole words; allow glyph boundaries for unspaced scripts only."""
    return [i for i in range(1, len(units)) if (
        units[i][0].isspace()
        or (not unicodedata.combining(units[i][0])
            and not unicodedata.category(units[i][0]).startswith("P")
            and (_uses_unspaced_translation_script(units[i - 1][0])
                 or _uses_unspaced_translation_script(units[i][0])))
    )] + [len(units)]


def _wrap_subtitle_layout_units(
    units: list[tuple[str, tuple[str, ...], str]], width: int,
) -> list[list[tuple[str, tuple[str, ...], str]]]:
    boundaries = set(_subtitle_layout_boundaries(units))
    lines: list[list[tuple[str, tuple[str, ...], str]]] = []
    cursor = 0
    while cursor < len(units):
        while cursor < len(units) and units[cursor][0].isspace():
            cursor += 1
        if cursor == len(units):
            break
        end = cursor
        columns = 0
        break_at = 0
        while end < len(units) and units[end][0] != "\n":
            char_width = _subtitle_character_width(units[end][0])
            if columns + char_width > width:
                break
            columns += char_width
            end += 1
            if end in boundaries:
                break_at = end
        if end < len(units) and units[end][0] != "\n" and break_at > cursor:
            end = break_at
        end = max(cursor + 1, end)
        line = units[cursor:end]
        while line and line[-1][0].isspace():
            line.pop()
        lines.append(line)
        cursor = end
    return lines


def _balanced_subtitle_layout_groups(
    units: list[tuple[str, tuple[str, ...], str]], width: int,
) -> list[list[list[tuple[str, tuple[str, ...], str]]]]:
    """Balance screens before allocating time; do not strand one-word tails."""
    lines = _wrap_subtitle_layout_units(units, width)
    count = (len(lines) + 1) // 2
    if count <= 1:
        return [lines] if lines else []
    boundaries = [0] + _subtitle_layout_boundaries(units)
    columns = [0]
    for char, _styles, _positioning in units:
        columns.append(columns[-1] + _subtitle_character_width(char))
    ideal = columns[-1] / count
    # A short subtitle normally has only a few dozen word boundaries. Dynamic
    # programming finds the least uneven partition subject to two-line/width
    # limits, without moving anything outside its authored timing window.
    states: dict[int, tuple[float, list[Any]]] = {0: (0.0, [])}
    for screen in range(count):
        following: dict[int, tuple[float, list[Any]]] = {}
        for start, (cost, groups) in states.items():
            for end in boundaries:
                if end <= start or (screen == count - 1 and end != len(units)):
                    continue
                if columns[end] - columns[start] > width * 2 + 2:
                    break
                wrapped = _wrap_subtitle_layout_units(units[start:end], width)
                if not wrapped or len(wrapped) > 2:
                    continue
                weight = sum(_subtitle_character_width(u[0]) for line in wrapped for u in line)
                new_cost = cost + (weight - ideal) ** 2
                if end not in following or new_cost < following[end][0]:
                    following[end] = (new_cost, groups + [wrapped])
        states = following
    best = states.get(len(units))
    return best[1] if best else [lines[i:i + 2] for i in range(0, len(lines), 2)]


def _layout_authored_translation_cue(cue: SubtitleCue, width: int = 42) -> list[SubtitleCue]:
    """Reflow/split into at most two lines, only inside the authored interval.

    Translation is validated against source markup/timestamps *before* this
    deterministic presentation pass. It never borrows a neighbouring cue's
    time, removes dialogue or relies on a particular writing system.
    """
    try:
        units = _subtitle_layout_units(cue.text)
    except ValueError:
        # Unsupported/malformed authored styling is safer left intact than
        # silently discarded. The caller reports remaining readability issues.
        return [cue]
    if not units or cue.end <= cue.start:
        return [cue]
    groups = _balanced_subtitle_layout_groups(units, width)
    weights = [sum(_subtitle_character_width(u[0]) for line in group for u in line) for group in groups]
    total = max(1, sum(weights))
    result: list[SubtitleCue] = []
    elapsed = 0
    for index, (group, weight) in enumerate(zip(groups, weights)):
        start = cue.start + (cue.end - cue.start) * elapsed / total
        elapsed += weight
        end = cue.end if index == len(groups) - 1 else cue.start + (cue.end - cue.start) * elapsed / total
        combined = list(group[0])
        for line in group[1:]:
            combined.append(("\n", combined[-1][1], combined[-1][2]))
            combined.extend(line)
        result.append(SubtitleCue(start, end, _render_subtitle_layout_units(combined)))
    return result or [cue]


def translate_subtitle_with_ai(
    source_path: Path,
    source_language: str,
    target_language: str,
    *,
    output_path: Path,
    model_name: str | None = None,
    cancel_event: Any | None = None,
    pause_event: Any | None = None,
    progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
    qa_report: dict[str, Any] | None = None,
    quality_profile: str = "balanced",
) -> Path:
    cues = read_subtitle_for_translation(source_path)
    if not cues:
        raise UserVisibleError(ui_text("error_translation_no_output"))
    translated = translate_existing_subtitle_cues_with_ai(
        cues,
        source_language,
        target_language,
        model_name=model_name,
        cancel_event=cancel_event,
        pause_event=pause_event,
        progress=progress,
        log=log,
        qa_report=qa_report,
        quality_profile=quality_profile,
    )
    if not translated:
        raise UserVisibleError(ui_text("error_translation_no_output"))
    _validate_strict_subtitle_translation(cues, translated)
    formatted: list[SubtitleCue] = []
    split_count = 0
    readability_review = 0
    readability_items: list[dict[str, Any]] = []
    for cue in translated:
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled()
        pieces = _layout_authored_translation_cue(cue)
        split_count += int(len(pieces) > 1)
        formatted.extend(pieces)
        for piece in pieces:
            visible = _strip_authored_markup_for_context(piece.text)
            cps = len(visible) / max(0.001, piece.end - piece.start)
            lines = "".join(v for k, v in _strict_translation_parts(piece.text) if k == "text").splitlines()
            overflow = len(lines) > 2 or any(sum(_subtitle_character_width(c) for c in line) > 42 for line in lines)
            if cps > 25 or overflow:
                readability_review += 1
                readability_items.append({"start": piece.start, "end": piece.end,
                                          "characters_per_second": round(cps, 1),
                                          "layout_overflow": overflow})
    if qa_report is not None:
        qa_report.update(output_cues=len(formatted), split_cues=split_count,
                         readability_review=readability_review,
                         readability_items=readability_items)
    if log is not None:
        log(f"G-TMCE AI Translation layout: {split_count} source cue(s) split within their timestamps; "
            f"{readability_review} cue(s) still need readability/timing review (25 characters/second, two 42-column lines).")
        for item in readability_items[:20]:
            log(f"QA readability: {srt_timestamp(item['start'])} --> {srt_timestamp(item['end'])}; "
                f"{item['characters_per_second']} characters/second; layout overflow={item['layout_overflow']}")
    return write_srt(output_path, formatted)


def translate_srt_with_ai(
    source_path: Path,
    source_language: str,
    target_language: str,
    *,
    output_path: Path,
    model_name: str | None = None,
    cancel_event: Any | None = None,
    pause_event: Any | None = None,
    progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
    quality_profile: str = "balanced",
) -> Path:
    return translate_subtitle_with_ai(
        source_path, source_language, target_language, output_path=output_path,
        model_name=model_name, cancel_event=cancel_event, pause_event=pause_event,
        progress=progress, log=log, quality_profile=quality_profile,
    )



def transcribe_audio_to_srt(
    audio_path: Path,
    language: str,
    *,
    output_path: Path | None = None,
    model_name: str | None = None,
    quality_profile: str | None = None,
    channel_layout: str | None = None,
    translate_to: str | None = None,
    cancel_event: Any | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    audio_path = Path(audio_path).expanduser()
    if not audio_path.is_file():
        raise UserVisibleError(ui_text("error_asr_audio_missing", path=audio_path))
    language = normalise_asr_language(language)
    translation_target = normalise_asr_language(translate_to) if translate_to else None
    if translation_target is not None and translation_target not in TRANSLATION_TARGET_CODES:
        raise UserVisibleError(
            ui_text("error_translation_target_unsupported", language=translation_target)
        )
    if translation_target is not None and translation_target == language:
        raise UserVisibleError(
            ui_text("error_translation_same_language", language=translation_target)
        )
    output_path = (
        Path(output_path)
        if output_path is not None
        else (
            generated_translation_path(audio_path, translation_target)
            if translation_target is not None
            else generated_subtitle_path(audio_path, language)
        )
    )
    profile_key = str(quality_profile or "").strip().lower()
    profile = ASR_QUALITY_PROFILES.get(profile_key) if profile_key else None
    if quality_profile is not None and profile is None:
        raise ValueError(f"Unknown ASR quality profile: {quality_profile}")
    if model_name is None and profile is not None:
        model_name = str(profile["model"])
    model_name = (model_name or os.environ.get("GTMCE_ASR_MODEL", DEFAULT_ASR_MODEL)).strip() or DEFAULT_ASR_MODEL
    beam_size = int(profile.get("beam_size", 5)) if profile is not None else 5
    patience = float(profile.get("patience", 1.0)) if profile is not None else 1.0
    repetition_penalty = float(profile.get("repetition_penalty", 1.06)) if profile is not None else 1.06
    no_repeat_ngram_size = int(profile.get("no_repeat_ngram_size", 3)) if profile is not None else 3
    hotwords = _asr_hotwords(language)
    logger = log or (lambda _message: None)
    asr_audio_path, temporary_asr_audio = _prepare_asr_audio_input(
        audio_path,
        channel_layout,
        cancel_event=cancel_event,
        logger=logger,
    )
    context_audio_path, temporary_context_audio = _prepare_local_context_audio_input(
        asr_audio_path,
        cancel_event=cancel_event,
        logger=logger,
    )

    def cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    def run(device: str, compute_type: str, *, remember_runtime: bool) -> list[SubtitleCue]:
        if cancelled():
            raise OperationCancelled()
        profile_log = f", profile={profile_key}" if profile_key else ""
        large_profile = model_name == "large-v3" or profile_key in {"slow", "slower"}
        last_resource_percent = -10
        emitted_static_resource_warnings: set[str] = set()

        def log_resources() -> None:
            for resource_line in _asr_resource_log_lines(
                device,
                compute_type,
                large_profile=large_profile,
            ):
                # Static configuration warnings (most notably disabled swap)
                # should be useful, not repeated at every progress checkpoint.
                if "swap is disabled" in resource_line:
                    if resource_line in emitted_static_resource_warnings:
                        continue
                    emitted_static_resource_warnings.add(resource_line)
                logger(resource_line)

        logger(f"G-TMCE ASR: model={model_name}{profile_log}, language={language}, device={device}, compute={compute_type}")
        if hotwords:
            logger("G-TMCE ASR: applying custom recognition hotwords")
        logger("G-TMCE ASR: preparing model...")
        model = _load_whisper_model(
            model_name,
            device,
            compute_type,
            logger=logger,
            cancel_event=cancel_event,
        )
        if remember_runtime:
            _remember_runtime(device, compute_type)
            logger(f"G-TMCE ASR: saved working runtime {device}/{compute_type}")
        if cancelled():
            raise OperationCancelled()
        log_resources()

        # Preserve short-range linguistic context without allowing a prompt to
        # survive for the entire film.  Each ~2 minute block gets its own
        # previous-text history; the prompt is reset at the next block.  A small
        # audio overlap protects words that straddle a block boundary, while the
        # keep-range below prevents duplicate subtitle cues.
        with wave.open(str(context_audio_path), "rb") as pcm_source:
            sampling_rate = int(pcm_source.getframerate())
            duration = float(pcm_source.getnframes()) / sampling_rate
            context_boundaries = _vad_aligned_context_boundaries(
                pcm_source,
                duration,
                cancel_event=cancel_event,
                logger=logger,
            )
            context_ranges = _local_context_ranges_from_boundaries(
                duration,
                context_boundaries,
            )
            logger(
                "G-TMCE ASR: local context enabled: "
                f"~{LOCAL_CONTEXT_BLOCK_SECONDS:.0f}s blocks aligned to VAD silence, "
                f"{LOCAL_CONTEXT_OVERLAP_SECONDS:.0f}s safety overlap; prompt resets between blocks"
            )
            collected_cues: list[SubtitleCue] = []
            duration_after_vad = 0.0
            last_percent = -1
            total_blocks = len(context_ranges)
            for block_index, (block_start, block_end, keep_start, keep_end) in enumerate(
                context_ranges, start=1
            ):
                if cancelled():
                    raise OperationCancelled()
                clip = _read_pcm_wav_range(pcm_source, block_start, block_end)
                if getattr(clip, "size", 0) <= 0:
                    continue
                segments, info = model.transcribe(
                    clip,
                    language=language,
                    task="transcribe",
                    beam_size=beam_size,
                    patience=patience,
                    temperature=0.0,
                    word_timestamps=True,
                    vad_filter=True,
                    vad_parameters={
                        "threshold": 0.30,
                        "min_speech_duration_ms": 120,
                        "min_silence_duration_ms": 700,
                        "speech_pad_ms": 350,
                    },
                    # Context is useful for Turkish inflection and sentence
                    # continuity inside a scene, but never crosses a block.
                    condition_on_previous_text=True,
                    repetition_penalty=repetition_penalty,
                    no_repeat_ngram_size=no_repeat_ngram_size,
                    max_new_tokens=128,
                    hotwords=hotwords,
                    hallucination_silence_threshold=2.0,
                )
                duration_after_vad += float(getattr(info, "duration_after_vad", 0.0) or 0.0)
                local_segments: list[Any] = []
                for segment in segments:
                    if cancelled():
                        raise OperationCancelled()
                    local_segments.append(segment)
                    global_end = block_start + float(getattr(segment, "end", 0.0) or 0.0)
                    if duration > 0:
                        percent = max(1, min(89, int(global_end / duration * 89)))
                        if percent > last_percent:
                            logger(f"Progress: {percent}%")
                            last_percent = percent
                        if percent >= last_resource_percent + 10:
                            log_resources()
                            last_resource_percent = (percent // 10) * 10

                # Keep only the half-overlap owned by this block.  Midpoint
                # ownership is stable even when Whisper shifts cue boundaries a
                # little between the two overlapping decodes.
                for cue in cues_from_segments(local_segments):
                    shifted = SubtitleCue(
                        cue.start + block_start,
                        cue.end + block_start,
                        cue.text,
                    )
                    midpoint = (shifted.start + shifted.end) / 2.0
                    if keep_start <= midpoint <= keep_end:
                        collected_cues.append(shifted)
                logger(
                    f"G-TMCE ASR: local-context block {block_index}/{total_blocks} "
                    f"complete ({block_start:.0f}-{block_end:.0f}s)"
                )

        if duration > 0 and duration_after_vad > 0:
            # Neighbouring blocks overlap by a few seconds, so their VAD totals
            # can double-count speech in the overlap. Clamp the display value
            # to the programme duration; this is diagnostic only.
            displayed_vad_duration = min(duration, duration_after_vad)
            logger(
                "G-TMCE ASR: VAD kept "
                f"{displayed_vad_duration:.1f}s / {duration:.1f}s of audio across local-context blocks"
            )
            log_resources()

        collected_cues = _deduplicate_boundary_cues(
            collected_cues,
            context_boundaries,
            logger=logger,
        )
        primary = _filter_hallucinated_cues(
            collected_cues,
            logger=logger,
            stage="primary",
        )
        primary = _filter_repetition_loops(primary, logger=logger, stage="primary")
        # 30 s was too coarse for films: the verified betting-shop scene in
        # our real test sample loses ~20 s of dialogue. Sensitive VAD is still
        # the gate, so scanning 8 s+ subtitle holes does not blindly transcribe
        # every quiet pause.
        gaps = _suspicious_gaps(primary, duration, minimum_gap=8.0)
        if not gaps or cancelled():
            return primary

        log_resources()
        logger(
            f"G-TMCE ASR: checking {len(gaps)} suspicious subtitle gap(s) with sensitive speech detection..."
        )
        try:
            from faster_whisper.audio import decode_audio  # type: ignore
            from faster_whisper.vad import VadOptions, get_speech_timestamps  # type: ignore

            sampling_rate = int(getattr(model.feature_extractor, "sampling_rate", 16000) or 16000)
            audio = decode_audio(str(context_audio_path), sampling_rate=sampling_rate)
            if cancelled():
                raise OperationCancelled()
            speech_chunks = get_speech_timestamps(
                audio,
                VadOptions(
                    threshold=0.18,
                    min_speech_duration_ms=100,
                    min_silence_duration_ms=550,
                    speech_pad_ms=400,
                ),
            )
            windows = _group_speech_windows(speech_chunks, sampling_rate, gaps)
            if not windows:
                logger("G-TMCE ASR: gap rescue found no additional speech-like regions.")
                return primary

            rescued: list[SubtitleCue] = []
            total_windows = len(windows)
            for index, (window_start, window_end) in enumerate(windows, start=1):
                if cancelled():
                    raise OperationCancelled()
                start_sample = max(0, int(window_start * sampling_rate))
                end_sample = min(len(audio), int(window_end * sampling_rate))
                if end_sample <= start_sample:
                    continue
                clip = audio[start_sample:end_sample]
                rescue_segments, _rescue_info = model.transcribe(
                    clip,
                    language=language,
                    task="transcribe",
                    beam_size=beam_size,
                    patience=patience,
                    temperature=0.0,
                    word_timestamps=True,
                    vad_filter=False,
                    # Rescue windows are independent clips, so carrying text
                    # from an unrelated gap would be harmful here.
                    condition_on_previous_text=False,
                    repetition_penalty=repetition_penalty,
                    no_repeat_ngram_size=no_repeat_ngram_size,
                    max_new_tokens=128,
                    hotwords=hotwords,
                    hallucination_silence_threshold=1.5,
                    no_speech_threshold=0.45,
                )
                local_segments: list[Any] = []
                for segment in rescue_segments:
                    if cancelled():
                        raise OperationCancelled()
                    local_segments.append(segment)
                for cue in cues_from_segments(local_segments):
                    rescued.append(
                        SubtitleCue(
                            cue.start + window_start,
                            cue.end + window_start,
                            cue.text,
                        )
                    )
                progress = 90 + min(9, int(index / total_windows * 9))
                logger(f"Progress: {progress}%")

            rescued = _filter_hallucinated_cues(
                rescued,
                logger=logger,
                stage="gap-rescue",
            )
            rescued = _filter_repetition_loops(rescued, logger=logger, stage="gap-rescue")
            merged = _merge_cues(primary, rescued)
            merged = _filter_hallucinated_cues(merged, logger=logger, stage="merged")
            merged = _filter_repetition_loops(merged, logger=logger, stage="merged")
            added = max(0, len(merged) - len(primary))
            logger(f"G-TMCE ASR: gap rescue added {added} subtitle cue(s) after cleanup.")
            return merged
        except OperationCancelled:
            raise
        except Exception as rescue_exc:
            # Gap recovery is a quality enhancement. Never throw away the
            # successful primary transcription if the optional pass fails.
            logger(f"G-TMCE ASR: gap rescue skipped ({rescue_exc})")
            return primary

    try:
        device, compute_type, used_saved_runtime = _runtime_device(logger)
        try:
            cues = run(device, compute_type, remember_runtime=not used_saved_runtime)
        except OperationCancelled:
            raise
        except Exception as exc:
            if device != "cuda":
                raise UserVisibleError(ui_text("error_asr_failed", error=exc)) from exc
            if used_saved_runtime:
                logger(
                    "G-TMCE ASR: saved CUDA runtime failed; rediscovering runtime "
                    f"({exc})"
                )
                # Remove only the stale runtime choice; keep known model snapshots.
                state = _read_asr_runtime_state()
                state.pop("runtime", None)
                _write_asr_runtime_state(state)
                rediscovered_device, rediscovered_compute, _ = _runtime_device(logger)
                if (rediscovered_device, rediscovered_compute) != (device, compute_type):
                    try:
                        cues = run(
                            rediscovered_device,
                            rediscovered_compute,
                            remember_runtime=True,
                        )
                    except OperationCancelled:
                        raise
                    except Exception as rediscovery_exc:
                        if rediscovered_device != "cuda":
                            raise UserVisibleError(
                                ui_text("error_asr_failed", error=rediscovery_exc)
                            ) from rediscovery_exc
                        logger(
                            "G-TMCE ASR: rediscovered CUDA runtime failed, "
                            f"retrying on CPU/int8 ({rediscovery_exc})"
                        )
                        cues = run("cpu", "int8", remember_runtime=False)
                else:
                    logger(f"G-TMCE ASR: CUDA failed, retrying on CPU/int8 ({exc})")
                    cues = run("cpu", "int8", remember_runtime=False)
            else:
                logger(f"G-TMCE ASR: CUDA failed, retrying on CPU/int8 ({exc})")
                try:
                    cues = run("cpu", "int8", remember_runtime=False)
                except OperationCancelled:
                    raise
                except Exception as cpu_exc:
                    raise UserVisibleError(ui_text("error_asr_failed", error=cpu_exc)) from cpu_exc

        if cancelled():
            raise OperationCancelled()
        cues = _filter_hallucinated_cues(cues, logger=logger, stage="final")
        if not cues:
            raise UserVisibleError(ui_text("error_asr_no_speech"))
        if translation_target is not None:
            cues = translate_cues_with_ai(
                cues,
                language,
                translation_target,
                cancel_event=cancel_event,
                log=logger,
            )
            if not cues:
                raise UserVisibleError(ui_text("error_translation_no_output"))
        write_srt(output_path, cues)
        logger("Progress: 100%")
        return output_path

    finally:
        if temporary_context_audio is not None:
            temporary_context_audio.unlink(missing_ok=True)
        if temporary_asr_audio is not None:
            temporary_asr_audio.unlink(missing_ok=True)
