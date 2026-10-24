"""Persistent, localized media workspace paths (no GUI or media dependencies)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


FOLDER_NAMES = {
    "en": {"video": "video", "audio": "audio", "subtitle": "subtitles",
           "artwork": "artwork", "metadata": "metadata", "output": "output",
           "episodes": "episodes", "backups": "backups"},
    "tr": {"video": "video", "audio": "ses", "subtitle": "altyazılar",
           "artwork": "görseller", "metadata": "üstveri", "output": "çıktı",
           "episodes": "bölümler", "backups": "yedekler"},
}


def layout_path(root: Path) -> Path:
    return root / ".gtmce" / "layout.json"


def contained_path(root: Path, relative: str | Path) -> Path:
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in {"..", "."} for p in relative.parts):
        raise ValueError(f"Unsafe workspace path: {relative}")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Workspace path escapes its directory: {path}")
    return path


def read_layout(root: Path) -> dict[str, Any] | None:
    manifest = layout_path(root)
    if not manifest.exists():
        return None
    contained_path(root, ".gtmce/layout.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("language"), str) or data["language"] not in FOLDER_NAMES
            or not isinstance(data.get("mode"), str) or data["mode"] not in {"single", "batch"}
            or data.get("folders") != FOLDER_NAMES[data["language"]]):
        raise ValueError(f"Invalid workspace layout: {manifest}")
    for key, name in data["folders"].items():
        _directory_path(root, Path(".gtmce") / name if key == "backups" else name)
    return data


def _directory_path(root: Path, relative: str | Path) -> Path:
    path = contained_path(root, relative)
    if path.exists() and not path.is_dir():
        raise ValueError(f"Workspace directory is occupied by a file: {path}")
    return path


def directory(root: Path, kind: str, *, create: bool = False) -> Path:
    data = read_layout(root)
    if data is None:
        return root
    relative = ".gtmce" if kind == "control" else data["folders"][kind]
    if kind == "backups":
        relative = Path(".gtmce") / relative
    path = contained_path(root, relative)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_layout(root: Path, language: str, *, mode: str = "single") -> dict[str, Any]:
    existing = read_layout(root)
    if existing is not None:
        if existing["mode"] != mode:
            raise ValueError(f"Workspace mode mismatch: {root}")
        return existing
    if mode not in {"single", "batch"}:
        raise ValueError(mode)
    language = "tr" if language == "tr" else "en"
    names = dict(FOLDER_NAMES[language])
    for key, name in names.items():
        _directory_path(root, Path(".gtmce") / name if key == "backups" else name)
    contained_path(root, ".gtmce/layout.json")
    root.mkdir(parents=True, exist_ok=True)
    control = root / ".gtmce"
    control.mkdir(exist_ok=True)
    manifest = layout_path(root)
    temporary = control / ".layout.json.tmp"
    data = {"version": 1, "language": language, "mode": mode, "folders": names}
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    temporary.replace(manifest)
    return data


def root_for_path(path: Path) -> Path | None:
    # Tracks, technical sidecars and backup tracks have at most three levels
    # below the workspace. Do not scan arbitrary ancestors or episode trees.
    for ancestor in list(path.parents)[:4]:
        if read_layout(ancestor) is not None:
            return ancestor
    return None


def control_path(path: Path, suffix: str) -> Path:
    root = root_for_path(path)
    if root is None:
        return path.with_name(path.name + suffix)
    relative_parent = path.parent.relative_to(root)
    return contained_path(root, Path(".gtmce") / relative_parent / (path.name + suffix))


def backup_path(path: Path, name: str) -> Path:
    root = root_for_path(path)
    if root is None:
        return path.with_name(name)
    # Every original belongs to an audio track, including an older backup
    # passed to the legacy-upgrade path.
    audio_name = read_layout(root)["folders"]["audio"]
    return contained_path(root, directory(root, "backups").relative_to(root) / audio_name / name)


def original_audio_path(backup: Path, name: str) -> Path:
    root = root_for_path(backup)
    return contained_path(root, directory(root, "audio").relative_to(root) / name) if root is not None else backup.with_name(name)


def output_directory(root: Path) -> Path:
    data = read_layout(root)
    if data is not None and data["mode"] == "batch":
        return directory(root, "output")
    parent = root.parent.parent
    parent_layout = read_layout(parent)
    if (parent_layout is not None and parent_layout["mode"] == "batch"
            and root.parent == directory(parent, "episodes")):
        return directory(parent, "output")
    return root


def episode_directories(root: Path) -> list[Path]:
    data = read_layout(root)
    parent = directory(root, "episodes") if data is not None and data["mode"] == "batch" else root
    if not parent.is_dir():
        return []
    return sorted((path for path in parent.iterdir() if path.is_dir()
                   and (re.search(r"(?:_tracks|_parçalar)(?:_\d+)?$", path.name, re.I)
                        or (data is not None and data["mode"] == "batch" and read_layout(path) is not None))),
                  key=lambda path: path.name.casefold())
