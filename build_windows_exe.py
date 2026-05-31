# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "G-TMCE"
ENTRY_FILE = "mkv_creator_ui.py"


def main() -> int:
    root = Path(__file__).resolve().parent
    entry = root / ENTRY_FILE
    if not entry.exists():
        print(f"Bulunamadı: {entry}")
        return 1

    python = sys.executable
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.check_call([python, "-m", "pip", "install", "--upgrade", "pyinstaller"])

    hidden_imports = ["PIL", "PIL.Image", "PIL.ImageOps", "PIL.ImageTk"]
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
    ]

    logo = root / "logo.png"
    if logo.exists():
        command += ["--add-data", f"{logo}{os.pathsep}."]
        # Windows icon dosyan varsa G-TMCE.ico olarak koyarsan otomatik kullanır.
        icon = root / "G-TMCE.ico"
        if icon.exists():
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
        print(f"Hazır: {built}")
    else:
        print("Build tamamlandı ama dist çıktısı bulunamadı.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
