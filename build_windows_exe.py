# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


APP_NAME = "G-TMCE"
ENTRY_FILE = "mkv_creator_ui.py"


def install_build_requirements(root: Path) -> None:
    requirements = root / "requirements-build.txt"
    if not requirements.exists():
        raise FileNotFoundError(f"Missing: {requirements}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--upgrade", "-r", str(requirements)],
        cwd=str(root),
    )


def create_windows_icon(root: Path) -> Path | None:
    logo = root / "logo.png"
    if not logo.exists():
        return None

    existing_icon = root / f"{APP_NAME}.ico"
    if existing_icon.exists():
        return existing_icon

    try:
        from PIL import Image
    except ImportError:
        return None

    icon = root / "build" / f"{APP_NAME}.ico"
    icon.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(logo) as source:
        source.convert("RGBA").save(
            icon,
            format="ICO",
            sizes=[
                (16, 16),
                (24, 24),
                (32, 32),
                (48, 48),
                (64, 64),
                (128, 128),
                (256, 256),
            ],
        )
    return icon


def main() -> int:
    root = Path(__file__).resolve().parent
    entry = root / ENTRY_FILE
    if not entry.exists():
        print(f"Missing: {entry}")
        return 1

    python = sys.executable
    install_build_requirements(root)

    hidden_imports = ["PIL", "PIL.Image", "PIL.ImageOps", "PIL.ImageTk", "tkinterdnd2", "certifi"]
    command = [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "tkinterdnd2",
        "--collect-data",
        "certifi",
    ]

    logo = root / "logo.png"
    if logo.exists():
        command += ["--add-data", f"{logo}{os.pathsep}."]

    icon = create_windows_icon(root)
    if icon is not None:
        command += ["--icon", str(icon)]

    template = root / "mkv.mtxcfg"
    if template.exists():
        command += ["--add-data", f"{template}{os.pathsep}."]

    version_file = root / "VERSION"
    if version_file.exists():
        command += ["--add-data", f"{version_file}{os.pathsep}."]

    for item in hidden_imports:
        command += ["--hidden-import", item]

    command.append(str(entry))
    subprocess.check_call(command, cwd=str(root))

    exe_name = f"{APP_NAME}.exe" if os.name == "nt" else APP_NAME
    built = root / "dist" / exe_name
    if built.exists():
        print(f"Built: {built}")
    else:
        print("Build completed but dist output was not found.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
