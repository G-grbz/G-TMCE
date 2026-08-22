from __future__ import annotations

import io
import json
import os
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import mkv_creator_ui as app


ROOT = Path(__file__).resolve().parents[1]


class UrlSecurityTests(unittest.TestCase):
    def test_opensubtitles_base_url_accepts_official_hosts(self) -> None:
        self.assertEqual(
            app.normalise_opensubtitles_base_url("api.opensubtitles.com"),
            "https://api.opensubtitles.com/api/v1",
        )
        self.assertEqual(
            app.normalise_opensubtitles_base_url("https://vip-api.opensubtitles.com/api/v1"),
            "https://vip-api.opensubtitles.com/api/v1",
        )

    def test_opensubtitles_base_url_rejects_ssrf_targets(self) -> None:
        bad = (
            "http://api.opensubtitles.com",
            "https://127.0.0.1",
            "https://localhost",
            "https://evilopensubtitles.com",
            "https://api.opensubtitles.com.evil.example",
            "https://user:pass@api.opensubtitles.com",
            "https://api.opensubtitles.com:8443",
            "https://api.opensubtitles.com/not-api",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.normalise_opensubtitles_base_url(value)

    def test_generic_https_validator_rejects_untrusted_hosts(self) -> None:
        allowed = frozenset({"example.com"})
        self.assertEqual(
            app.validate_https_url("https://example.com/file", allowed_hosts=allowed),
            "https://example.com/file",
        )
        for value in ("http://example.com", "https://evil.example", "https://user@example.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.validate_https_url(value, allowed_hosts=allowed)


class ArchiveSecurityTests(unittest.TestCase):
    def test_zip_traversal_is_rejected(self) -> None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../escape.txt", "no")
        stream.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(stream) as archive, self.assertRaises(ValueError):
                app.safe_extract_zip(archive, Path(tmp))

    def test_zip_symlink_is_rejected(self) -> None:
        stream = io.BytesIO()
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(info, "target")
        stream.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(stream) as archive, self.assertRaises(ValueError):
                app.safe_extract_zip(archive, Path(tmp))

    def test_tar_symlink_is_rejected(self) -> None:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "target"
            archive.addfile(info)
        stream.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(fileobj=stream, mode="r") as archive, self.assertRaises(ValueError):
                app.safe_extract_tar(archive, Path(tmp))


class ProcessSecurityTests(unittest.TestCase):
    def test_sensitive_environment_is_not_forwarded_to_media_tools(self) -> None:
        secrets = {
            "TMDB_API_KEY": "secret",
            "OPENSUBTITLES_API_KEY": "secret",
            "OPENSUBTITLES_USERNAME": "secret",
            "OPENSUBTITLES_PASSWORD": "secret",
            "GH_TOKEN": "secret",
            "GITHUB_TOKEN": "secret",
            "LD_PRELOAD": "/tmp/evil.so",
            "PYTHONPATH": "/tmp/evil",
        }
        with mock.patch.dict(os.environ, secrets, clear=False):
            env = app.third_party_subprocess_env()
        for key in secrets:
            self.assertNotIn(key, env)

    def test_source_contains_no_shell_true(self) -> None:
        source = (ROOT / "mkv_creator_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("shell = True", source)


class StorageSecurityTests(unittest.TestCase):
    def test_preferences_are_written_atomically_with_private_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = app.SETTINGS_PATH
            app.SETTINGS_PATH = Path(tmp) / "settings.json"
            try:
                app.save_saved_preferences({"api_key": "value"})
                self.assertEqual(app.load_saved_preferences()["api_key"], "value")
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(app.SETTINGS_PATH.stat().st_mode), 0o600)
                leftovers = list(Path(tmp).glob(".settings.json.*.tmp"))
                self.assertEqual(leftovers, [])
            finally:
                app.SETTINGS_PATH = original


class ReleaseSecurityTests(unittest.TestCase):
    def test_version_is_release_tag_format(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^v\d+\.\d+\.\d+$")

    def test_release_workflow_has_verified_artifacts(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        for required in (
            "actions/attest@v4",
            "sha256sum",
            "git archive",
            "G-TMCE-$env:VERSION-win-x64.exe",
            "G-TMCE-${VERSION}-x86_64.AppImage",
            "needs: [verify, windows, linux]",
        ):
            self.assertIn(required, workflow)

    def test_codeql_uses_security_extended(self) -> None:
        workflow = (ROOT / ".github/workflows/codeql.yml").read_text(encoding="utf-8")
        self.assertIn("security-extended", workflow)
        self.assertIn("github/codeql-action/init@v4", workflow)

    def test_appimagetool_is_pinned_and_verified(self) -> None:
        script = (ROOT / "build_appimage.sh").read_text(encoding="utf-8")
        self.assertIn("APPIMAGETOOL_VERSION=\"1.9.1\"", script)
        self.assertIn("APPIMAGETOOL_SHA256=", script)
        self.assertIn("APPIMAGE_RUNTIME_TAG=\"20251108\"", script)
        self.assertIn("APPIMAGE_RUNTIME_SHA256=", script)
        self.assertIn("--runtime-file", script)
        self.assertIn("sha256sum -c", script)
        self.assertNotIn("releases/latest/download", script)

    def test_windows_smoke_build_runs_manually_and_on_relevant_main_pushes(self) -> None:
        workflow = (ROOT / ".github/workflows/build-windows-exe.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("push:", workflow)
        self.assertIn("- main", workflow)
        for watched_path in (
            '"mkv_creator_ui.py"',
            '"build_windows_exe.py"',
            '"requirements.txt"',
            '"requirements-build.txt"',
            '"VERSION"',
        ):
            self.assertIn(watched_path, workflow)
        self.assertNotIn("tags:\n", workflow)
        self.assertNotIn("gh release create", workflow)

    def test_windows_build_fallback_dependencies_match_pinned_minimums(self) -> None:
        build_script = (ROOT / "build_windows_exe.py").read_text(encoding="utf-8")
        for requirement in (
            "PyInstaller>=6.22.2,<7",
            "Pillow>=12.3.0,<13",
            "tkinterdnd2>=0.6.2,<1",
            "certifi>=2024.8.30,<2027",
        ):
            self.assertIn(requirement, build_script)
        self.assertIn('"--collect-data",', build_script)
        self.assertIn('"certifi",', build_script)


class LinuxFileDialogTests(unittest.TestCase):
    def test_system_gui_environment_restores_host_library_path(self) -> None:
        values = {
            "LD_LIBRARY_PATH": "/tmp/_MEI-frozen",
            "LD_LIBRARY_PATH_ORIG": "/usr/local/lib:/usr/lib",
            "LD_PRELOAD": "/tmp/injected.so",
            "TMDB_API_KEY": "secret",
        }
        with mock.patch.dict(os.environ, values, clear=False):
            env = app.system_gui_subprocess_env()
        if os.name == "posix":
            self.assertEqual(env.get("LD_LIBRARY_PATH"), "/usr/local/lib:/usr/lib")
            self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("TMDB_API_KEY", env)

    def test_native_dialog_execution_failure_falls_back(self) -> None:
        failed = mock.Mock(returncode=127, stdout="")
        with mock.patch.object(app.subprocess, "run", return_value=failed):
            self.assertIsNone(app.run_dialog_command(["kdialog", "--getopenfilename"]))

    def test_native_dialog_cancel_does_not_open_second_dialog(self) -> None:
        cancelled = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(app.subprocess, "run", return_value=cancelled):
            self.assertEqual(app.run_dialog_command(["kdialog", "--getopenfilename"]), "")

    def test_appimage_build_dependencies_match_current_minimums(self) -> None:
        script = (ROOT / "build_appimage.sh").read_text(encoding="utf-8")
        for requirement in (
            "PyInstaller>=6.22.2,<7",
            "Pillow>=12.3.0,<13",
            "tkinterdnd2>=0.6.2,<1",
            "certifi>=2024.8.30,<2027",
        ):
            self.assertIn(requirement, script)
        self.assertIn("--collect-data certifi", script)


class TlsCertificateTests(unittest.TestCase):
    def test_tls_context_uses_bundled_certifi_ca_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ca_file = Path(tmp) / "cacert.pem"
            ca_file.write_text("test-ca", encoding="utf-8")
            sentinel = object()
            with mock.patch.object(app.certifi, "where", return_value=str(ca_file)), mock.patch.object(
                app.ssl, "create_default_context", return_value=sentinel
            ) as create_context:
                self.assertIs(app.trusted_ssl_context(), sentinel)
            create_context.assert_called_once_with(cafile=str(ca_file.resolve()))

    def test_tls_context_fails_closed_when_ca_store_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.pem"
            with mock.patch.object(app.certifi, "where", return_value=str(missing)):
                with self.assertRaises(RuntimeError):
                    app.trusted_ssl_context()

    def test_runtime_requirements_include_certifi(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("certifi>=2024.8.30,<2027", requirements)


class WindowsReleaseEncodingTests(unittest.TestCase):
    def test_release_windows_build_uses_utf8_stdio(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        windows_block = workflow.split("\n  windows:\n", 1)[1].split("\n  linux:\n", 1)[0]
        self.assertIn('PYTHONUTF8: "1"', windows_block)
        self.assertIn('PYTHONIOENCODING: "utf-8"', windows_block)

    def test_windows_builder_ci_output_is_ascii_safe(self) -> None:
        source = (ROOT / "build_windows_exe.py").read_text(encoding="utf-8")
        self.assertNotIn("Hazır:", source)
        self.assertNotIn("Bulunamadı:", source)
        self.assertNotIn("çıktısı", source)


if __name__ == "__main__":
    unittest.main()
