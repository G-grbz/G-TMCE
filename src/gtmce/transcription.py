# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import sys
import textwrap
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .core import (
    LANG_ALIASES,
    OperationCancelled,
    UserVisibleError,
    app_config_dir,
    ui_text,
)


DEFAULT_ASR_MODEL = "turbo"
ASR_RUNTIME_STATE_VERSION = 1
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
    if duration > 0 and duration < 1.50 and normalised in outro_phrases:
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
            not _cue_finishes_sentence(parts[-1])
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
    """Keep translated subtitle blocks to roughly two 42-character lines."""
    text = _clean_text(cue.text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [SubtitleCue(cue.start, cue.end, _wrap_subtitle_text(text))]

    chunks = textwrap.wrap(
        text,
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
        result.append(SubtitleCue(start, end, _wrap_subtitle_text(chunk)))
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
    source_run = _longest_same_token_run(source_tokens)
    output_run = _longest_same_token_run(output_tokens)

    # Short inputs sometimes become duplicated answers (for example
    # ``I don't know.`` -> ``Bilmiyorum, bilmiyorum.``). A two-token run is
    # suspicious only when the source itself did not repeat that token.
    if output_run >= 2 and source_run < 2 and output_count <= 8:
        return f"short-token-repeat:{output_run}"

    # Tiny ASR fragments are especially prone to semantic hallucinations that
    # are not token loops (for example ``The`` becoming a whole unrelated
    # sentence). Reject implausible expansion before it reaches the subtitle.
    if source_count == 1 and output_count >= 5:
        return f"tiny-input-expansion:{source_count}->{output_count}"
    if source_count == 2 and output_count > 8:
        return f"tiny-input-expansion:{source_count}->{output_count}"
    if source_count <= 4 and output_count > source_count * 4 + 4:
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
        and output_count >= source_count + 3
    ):
        return f"sentence-expansion:{source_sentences}->{output_sentences}"

    # The supplied sample exposed runs such as one source token becoming 7-36
    # copies in the translation. Keep genuine source repetition by allowing a
    # little headroom over the longest run already present in the source.
    if output_run >= 4 and output_run > source_run + 2:
        return f"token-loop:{output_run}"

    # A subtitle translation should not explode to many times the source size.
    # Use a generous limit because some language pairs naturally expand.
    if output_count > max(24, source_count * 4 + 10):
        return f"length-explosion:{source_count}->{output_count}"

    # Low lexical diversity is another signature of a loop even when
    # punctuation or a short preamble interrupts the repeated token run.
    if output_count >= 12:
        unique_ratio = len(set(output_tokens)) / output_count
        if unique_ratio < 0.22 and output_count > source_count * 2:
            return f"low-diversity:{unique_ratio:.2f}"

    return None


def _decode_translation_result(result: Any, tokenizer: Any, target_language: str) -> str:
    hypothesis = list(result.hypotheses[0]) if result.hypotheses else []
    hypothesis = [
        token for token in hypothesis
        if token not in {"</s>", "<pad>", f"<2{target_language}>"}
    ]
    return _clean_text(tokenizer.decode(hypothesis)) if hypothesis else ""


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
    tokens = tokenizer.encode(
        f"<2{target_language}> {_clean_text(text)}",
        out_type=str,
    )
    max_length = min(112, max(12, int(len(tokens) * length_factor) + length_extra))
    result = translator.translate_batch(
        [tokens],
        beam_size=beam_size,
        repetition_penalty=repetition_penalty,
        no_repeat_ngram_size=no_repeat_ngram_size,
        max_decoding_length=max_length,
    )[0]
    return _decode_translation_result(result, tokenizer, target_language)


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
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelled()
            batch = cue_list[offset: offset + batch_size]
            source_tokens = [
                tokenizer.encode(
                    f"<2{target_language}> {_clean_text(unit.text)}",
                    out_type=str,
                )
                for unit in batch
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
            )
            for batch_index, (unit, result) in enumerate(zip(batch, results)):
                unit_index = offset + batch_index
                text = _decode_translation_result(result, tokenizer, target_language)
                reason = _translation_invalid_reason(unit.text, text)
                if reason is not None:
                    logger(
                        "G-TMCE AI Translation: suspicious decoder output at "
                        f"{srt_timestamp(unit.start)} ({reason}); retrying safely"
                    )
                    retry = _safe_retry_translation(
                        translator,
                        tokenizer,
                        SubtitleCue(unit.start, unit.end, unit.text),
                        target_language,
                    )
                    retry_reason = _translation_invalid_reason(unit.text, retry)
                    if retry and retry_reason is None:
                        text = retry
                    else:
                        rescue = _rescue_source_echo_translation(
                            translator, tokenizer, unit.text, target_language
                        )
                        rescue_reason = _translation_invalid_reason(unit.text, rescue)
                        if rescue and rescue_reason is None:
                            logger(
                                "G-TMCE AI Translation: recovered stubborn output with "
                                f"source reshaping at {srt_timestamp(unit.start)}"
                            )
                            text = rescue
                        else:
                            context_rescue = _rescue_translation_with_neighbor(
                                translator, tokenizer, cue_list, unit_index, target_language
                            )
                            context_reason = _translation_invalid_reason(
                                unit.text, context_rescue
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
                                text = _clean_text(unit.text)
                if not text:
                    logger(
                        "G-TMCE AI Translation: empty model output after rescue; preserving source unit at "
                        f"{srt_timestamp(unit.start)}"
                    )
                    text = _clean_text(unit.text)
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
            logger(
                "G-TMCE AI Translation: "
                f"{min(offset + len(batch), total)}/{total} unit(s) complete"
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
        cue_text = _clean_text(" ".join(lines[timing_index + 1:]))
        if cue_text and end > start:
            cues.append(SubtitleCue(start, end, cue_text))
    return cues


def translate_srt_with_ai(
    source_path: Path,
    source_language: str,
    target_language: str,
    *,
    output_path: Path,
    model_name: str | None = None,
    cancel_event: Any | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    cues = read_srt(source_path)
    if not cues:
        raise UserVisibleError(ui_text("error_translation_no_output"))
    translated = translate_cues_with_ai(
        cues,
        source_language,
        target_language,
        model_name=model_name,
        cancel_event=cancel_event,
        log=log,
    )
    if not translated:
        raise UserVisibleError(ui_text("error_translation_no_output"))
    return write_srt(output_path, translated)



def transcribe_audio_to_srt(
    audio_path: Path,
    language: str,
    *,
    output_path: Path | None = None,
    model_name: str | None = None,
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
    model_name = (model_name or os.environ.get("GTMCE_ASR_MODEL", DEFAULT_ASR_MODEL)).strip() or DEFAULT_ASR_MODEL
    logger = log or (lambda _message: None)

    def cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    def run(device: str, compute_type: str, *, remember_runtime: bool) -> list[SubtitleCue]:
        if cancelled():
            raise OperationCancelled()
        logger(f"G-TMCE ASR: model={model_name}, language={language}, device={device}, compute={compute_type}")
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

        # Film mixes often keep dialogue lower than music/effects.  A slightly
        # more sensitive VAD catches quiet/centre-channel speech that the stock
        # threshold can discard, while still avoiding full-film silence decode.
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            task="transcribe",
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={
                "threshold": 0.30,
                "min_speech_duration_ms": 120,
                "min_silence_duration_ms": 700,
                "speech_pad_ms": 350,
            },
            # The faster-whisper documentation notes that disabling previous
            # text conditioning reduces repetition loops and timestamp drift.
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
        )
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        duration_after_vad = float(getattr(info, "duration_after_vad", 0.0) or 0.0)
        if duration > 0 and duration_after_vad > 0:
            logger(
                "G-TMCE ASR: VAD kept "
                f"{duration_after_vad:.1f}s / {duration:.1f}s of audio for the primary pass"
            )
        collected: list[Any] = []
        last_percent = -1
        for segment in segments:
            if cancelled():
                raise OperationCancelled()
            collected.append(segment)
            if duration > 0:
                # Reserve the final 10% for the optional dialogue-gap rescue pass.
                percent = max(1, min(89, int(float(getattr(segment, "end", 0.0)) / duration * 89)))
                if percent != last_percent:
                    logger(f"Progress: {percent}%")
                    last_percent = percent

        primary = _filter_hallucinated_cues(
            cues_from_segments(collected),
            logger=logger,
            stage="primary",
        )
        # 30 s was too coarse for films: the verified betting-shop scene in
        # our real test sample loses ~20 s of dialogue. Sensitive VAD is still
        # the gate, so scanning 8 s+ subtitle holes does not blindly transcribe
        # every quiet pause.
        gaps = _suspicious_gaps(primary, duration, minimum_gap=8.0)
        if not gaps or cancelled():
            return primary

        logger(
            f"G-TMCE ASR: checking {len(gaps)} suspicious subtitle gap(s) with sensitive speech detection..."
        )
        try:
            from faster_whisper.audio import decode_audio  # type: ignore
            from faster_whisper.vad import VadOptions, get_speech_timestamps  # type: ignore

            sampling_rate = int(getattr(model.feature_extractor, "sampling_rate", 16000) or 16000)
            audio = decode_audio(str(audio_path), sampling_rate=sampling_rate)
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
                    beam_size=5,
                    word_timestamps=True,
                    vad_filter=False,
                    condition_on_previous_text=False,
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
            merged = _merge_cues(primary, rescued)
            merged = _filter_hallucinated_cues(merged, logger=logger, stage="merged")
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
