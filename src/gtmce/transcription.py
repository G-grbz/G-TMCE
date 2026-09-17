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




def transcribe_audio_to_srt(
    audio_path: Path,
    language: str,
    *,
    output_path: Path | None = None,
    model_name: str | None = None,
    cancel_event: Any | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    audio_path = Path(audio_path).expanduser()
    if not audio_path.is_file():
        raise UserVisibleError(ui_text("error_asr_audio_missing", path=audio_path))
    language = normalise_asr_language(language)
    output_path = Path(output_path) if output_path is not None else generated_subtitle_path(audio_path, language)
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
    write_srt(output_path, cues)
    logger("Progress: 100%")
    return output_path
