import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeDatabase

from src.gtmce import core


ROOT = Path(__file__).resolve().parents[1]


def mime_types(contents):
    return re.search(r"^MimeType=(.*)$", contents, re.MULTILINE)[1].rstrip(";").split(";")


def accepts(mime_name, declared):
    mime = QMimeDatabase().mimeTypeForName(mime_name)
    return any(
        mime.name().startswith(pattern[:-1]) if pattern.endswith("/*")
        else mime.inherits(pattern)
        for pattern in declared
    )


@pytest.mark.parametrize("mime_name", [
    "video/x-matroska", "video/mp4", "video/quicktime", "video/x-msvideo",
    "video/mp2t", "audio/x-matroska", "audio/ogg", "application/ogg",
    "application/vnd.ms-asf", "application/vnd.rn-realmedia",
])
def test_extract_menu_keeps_supported_media_mime_types(mime_name):
    declared = mime_types(core.linux_kde_service_menu_contents(Path("/tmp/G-TMCE.AppImage")))
    assert accepts(mime_name, declared)


@pytest.mark.parametrize("mime_name", [
    "application/octet-stream", "application/x-executable", "application/x-iso9660-appimage",
    "application/pdf", "application/zip", "application/json", "text/csv", "image/png",
])
def test_extract_menu_does_not_match_unrelated_files_through_mime_inheritance(mime_name):
    declared = mime_types(core.linux_kde_service_menu_contents(Path("/tmp/G-TMCE.AppImage")))
    assert not accepts(mime_name, declared)
    # The previous entry matched all regular files via this inherited parent.
    mime = QMimeDatabase().mimeTypeForName(mime_name)
    if mime.isValid():
        assert mime.inherits("application/octet-stream")


@pytest.mark.skipif(shutil.which("bash") is None, reason="Linux installer requires bash")
def test_installer_writes_same_restricted_menu_and_application_types(tmp_path):
    script = (ROOT / "install.sh").read_text()
    functions = "\n".join(
        re.search(rf"^{name}\(\) \{{\n.*?^\}}", script, re.MULTILINE | re.DOTALL)[0]
        for name in ("install_desktop_entry", "install_dolphin_service_menu")
    )
    commands = functions + '\nAPP_ID=g-tmce\nBIN_LINK=/usr/local/bin/g-tmce\nINSTALL_DIR=/opt/G-TMCE\nAPP_DESKTOP_DIR="$1/apps"\nKDE_SERVICE_DIRS=("$1/kio" "$1/kservices5" "$1/kservices6")\ninstall_desktop_entry\ninstall_dolphin_service_menu\n'
    subprocess.run(["bash", "-c", commands, "test-installer", str(tmp_path)], check=True, capture_output=True, text=True)
    expected_menu = mime_types(core.linux_kde_service_menu_contents(Path("/tmp/G-TMCE.AppImage")))
    assert mime_types((ROOT / "mkv-creator-ui-extract.desktop").read_text()) == expected_menu
    for directory in ("kio", "kservices5", "kservices6"):
        contents = (tmp_path / directory / "g-tmce-extract.desktop").read_text()
        assert mime_types(contents) == expected_menu
        assert "Patterns=" not in contents
    expected_app = mime_types((ROOT / "G-TMCE.desktop").read_text())
    assert mime_types((tmp_path / "apps" / "g-tmce.desktop").read_text()) == expected_app
    assert not accepts("application/x-executable", expected_app)
    assert not accepts("text/csv", expected_app)


def test_system_install_still_recognizes_old_generated_appimage_menu(monkeypatch, tmp_path):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(core, "APP_DIR", Path("/opt/G-TMCE"))
    monkeypatch.setattr(core, "refresh_linux_kde_service_menu_cache", lambda: None)
    menu = tmp_path / "kio" / "servicemenus" / "g-tmce-extract.desktop"
    menu.parent.mkdir(parents=True)
    current = core.linux_kde_service_menu_contents(tmp_path / "g-tmce" / "G-TMCE.AppImage")
    previous = re.sub(r"^MimeType=.*$", "MimeType=application/octet-stream;video/*;", current, flags=re.MULTILINE)
    menu.write_text(previous)
    assert core.remove_stale_appimage_service_menu_for_system_install() == []
    assert not menu.exists()
    menu.write_text(previous + "# customized menu\n")
    assert core.remove_stale_appimage_service_menu_for_system_install() == []
    assert menu.exists()
