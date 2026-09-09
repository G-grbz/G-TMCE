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
APP_SOURCE_FILES = (
    ROOT / "mkv_creator_ui.py",
    *(ROOT / "src" / "gtmce" / name for name in ("core.py", "controller.py", "theme.py")),
)


class DesktopOpenWithTests(unittest.TestCase):
    def test_extract_default_directory_is_available_from_the_ui_instance(self) -> None:
        source = Path("/media/movie.mkv")
        controller = app.GTMCEControllerMixin()

        self.assertEqual(
            controller.default_extract_output_dir(source),
            Path("/media/movie_tracks"),
        )

    def test_extract_desktop_arguments_open_supported_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "movie with spaces.MKV"
            source.touch()

            self.assertEqual(
                app.initial_extract_source_from_argv(["g-tmce", "--extract", str(source)]),
                source,
            )
            self.assertEqual(
                app.initial_extract_source_from_argv(["g-tmce", f"--extract={source}"]),
                source,
            )
            self.assertEqual(
                app.initial_extract_source_from_argv(["g-tmce", source.as_uri()]),
                source,
            )

    def test_pending_desktop_extract_uses_dialog_first_flow(self) -> None:
        source = Path("/media/movie.mkv")

        class PendingExtract:
            def __init__(self) -> None:
                self.initial_extract_source = source
                self._initial_extract_started = False
                self.opened_source: Path | None = None

            def open_initial_extract_source(self, value: Path) -> None:
                self.opened_source = value

        pending = PendingExtract()
        app.MkvCreatorApp._open_pending_initial_extract(pending)

        self.assertTrue(pending._initial_extract_started)
        self.assertIsNone(pending.initial_extract_source)
        self.assertEqual(pending.opened_source, source)


class WindowsContextMenuLauncherTests(unittest.TestCase):
    def test_versioned_release_updates_one_stable_context_menu_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_release = root / "G-TMCE-v1.9.0-win-x64.exe"
            second_release = root / "G-TMCE-v2.0.0-win-x64.exe"
            first_release.write_bytes(b"version one")
            second_release.write_bytes(b"version two")
            local_app_data = root / "AppData" / "Local"

            stable_path = local_app_data / "G-TMCE" / "G-TMCE.exe"
            with (
                mock.patch.object(app._core, "windows_context_menu_launcher_path", return_value=stable_path),
                mock.patch.object(app.sys, "frozen", True, create=True),
                mock.patch.object(app.sys, "executable", str(first_release)),
            ):
                stable = app.sync_windows_context_menu_launcher()
                self.assertEqual(stable, stable_path)
                self.assertEqual(stable.read_bytes(), b"version one")
                self.assertEqual(
                    app.app_command_for_file_argument(),
                    f'"{stable}" "%1"',
                )

                app.sys.executable = str(second_release)
                self.assertEqual(app.sync_windows_context_menu_launcher(), stable)
                self.assertEqual(stable.read_bytes(), b"version two")
                self.assertEqual(
                    app.app_command_for_file_argument(),
                    f'"{stable}" "%1"',
                )

    def test_new_appimage_updates_one_stable_dolphin_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_release = root / "G-TMCE-v1.9.0-x86_64.AppImage"
            second_release = root / "G-TMCE-v2.0.0-x86_64.AppImage"
            first_release.write_bytes(b"version one")
            second_release.write_bytes(b"version two")
            first_release.chmod(0o755)
            second_release.chmod(0o755)
            logo = root / "logo.png"
            logo.write_bytes(b"icon data")
            data_home = root / "share"

            with (
                mock.patch.dict(
                    os.environ,
                    {"APPIMAGE": str(first_release), "XDG_DATA_HOME": str(data_home)},
                    clear=False,
                ),
                mock.patch.object(app._core, "refresh_linux_kde_service_menu_cache") as refresh_cache,
                mock.patch.object(app._core, "LOGO_PATH", logo),
            ):
                # Double-clicking an AppImage refreshes the application-menu
                # launcher independently of the optional Dolphin checkbox.
                self.assertEqual(app.install_linux_appimage_launcher(), [])
                stable = data_home / "g-tmce" / "G-TMCE.AppImage"
                self.assertEqual(stable.read_bytes(), b"version one")
                self.assertTrue(stable.stat().st_mode & stat.S_IXUSR)
                icon = data_home / "icons" / "hicolor" / "256x256" / "apps" / "g-tmce.png"
                self.assertEqual(icon.read_bytes(), b"icon data")
                app_launcher = data_home / "applications" / "g-tmce.desktop"
                self.assertIn(str(stable), app_launcher.read_text(encoding="utf-8"))
                self.assertTrue(app_launcher.stat().st_mode & stat.S_IXUSR)
                self.assertFalse(any(path.exists() for path in app.linux_kde_service_menu_paths()))
                refresh_cache.assert_called_once()

                os.environ["APPIMAGE"] = str(second_release)
                self.assertEqual(app.install_linux_appimage_launcher(), [])
                self.assertEqual(stable.read_bytes(), b"version two")
                # The search entry retains its stable target and needs no
                # desktop-cache rewrite just because the AppImage changed.
                refresh_cache.assert_called_once()

                self.assertEqual(app.install_linux_appimage_context_menu(), [])
                for service_menu in app.linux_kde_service_menu_paths():
                    self.assertIn(str(stable), service_menu.read_text(encoding="utf-8"))
                    self.assertTrue(service_menu.stat().st_mode & stat.S_IXUSR)
                self.assertEqual(refresh_cache.call_count, 2)

                self.assertEqual(app.uninstall_linux_appimage_context_menu(), [])
                # The checkbox controls only the Dolphin action. The stable
                # AppImage and search-menu entry remain for future upgrades.
                self.assertTrue(stable.exists())
                self.assertTrue(icon.exists())
                self.assertTrue(app_launcher.exists())
                self.assertFalse(any(path.exists() for path in app.linux_kde_service_menu_paths()))
                self.assertEqual(refresh_cache.call_count, 3)

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

    def test_capture_process_drains_large_stderr_without_pipe_deadlock(self) -> None:
        # Regression: the old poll-then-communicate loop could block forever on
        # Windows when FFmpeg filled stderr before exiting.
        payload_size = 512 * 1024
        process = app.run_cancellable_capture(
            [
                app.sys.executable,
                "-c",
                f"import sys; sys.stderr.write('x' * {payload_size}); sys.stdout.write('ok')",
            ],
        )
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stdout, "ok")
        self.assertEqual(len(process.stderr), payload_size)

    def test_ffmpeg_path_prefers_installed_binary_without_release_check(self) -> None:
        installed = r"C:\\Users\\Test\\AppData\\Roaming\\g-tmce\\3rdParty\\bin\\ffmpeg.exe"
        with mock.patch.object(app._core, "installed_third_party_tool_path", return_value=installed), mock.patch.object(
            app._core, "third_party_tool_path", side_effect=AssertionError("release check should not run")
        ):
            self.assertEqual(app.ffmpeg_path(), installed)

    def test_source_contains_no_shell_true(self) -> None:
        source = "\n".join(path.read_text(encoding="utf-8") for path in APP_SOURCE_FILES)
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
            '"src/**"',
            '"scripts/build_windows_exe.py"',
            '"assets/**"',
            '"requirements.txt"',
            '"requirements-build.txt"',
            '"VERSION"',
        ):
            self.assertIn(watched_path, workflow)
        self.assertNotIn("tags:\n", workflow)
        self.assertNotIn("gh release create", workflow)

    def test_windows_build_installs_shared_requirements(self) -> None:
        build_script = (ROOT / "scripts" / "build_windows_exe.py").read_text(encoding="utf-8")
        self.assertIn('root / "requirements-build.txt"', build_script)
        self.assertIn('"-r", str(requirements)', build_script)
        for duplicated_requirement in ("Pillow>=", "PySide6>=", "certifi>=", "PyInstaller>="):
            self.assertNotIn(duplicated_requirement, build_script)
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

    def test_appimage_build_installs_shared_requirements(self) -> None:
        script = (ROOT / "build_appimage.sh").read_text(encoding="utf-8")
        self.assertIn('pip install --upgrade -r requirements-build.txt', script)
        for duplicated_requirement in ("Pillow>=", "PySide6>=", "certifi>=", "PyInstaller>="):
            self.assertNotIn(duplicated_requirement, script)
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
        requirement_names = {
            line.split(";", 1)[0].strip().split("[", 1)[0].split("=", 1)[0].split("<", 1)[0].split(">", 1)[0].strip().lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))
        }
        self.assertIn("certifi", requirement_names)

    def test_build_requirements_include_runtime_requirements(self) -> None:
        requirements = (ROOT / "requirements-build.txt").read_text(encoding="utf-8").splitlines()
        normalized = {line.strip() for line in requirements if line.strip() and not line.lstrip().startswith("#")}
        self.assertIn("-r requirements.txt", normalized)


class WindowsReleaseEncodingTests(unittest.TestCase):
    def test_release_windows_build_uses_utf8_stdio(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        windows_block = workflow.split("\n  windows:\n", 1)[1].split("\n  linux:\n", 1)[0]
        self.assertIn('PYTHONUTF8: "1"', windows_block)
        self.assertIn('PYTHONIOENCODING: "utf-8"', windows_block)

    def test_windows_builder_ci_output_is_ascii_safe(self) -> None:
        source = (ROOT / "scripts" / "build_windows_exe.py").read_text(encoding="utf-8")
        self.assertNotIn("Hazır:", source)
        self.assertNotIn("Bulunamadı:", source)
        self.assertNotIn("çıktısı", source)


class QtUiMigrationTests(unittest.TestCase):
    def test_runtime_uses_pyside6_not_tkinter(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("PySide6>=", requirements)
        self.assertNotIn("tkinterdnd2", requirements.lower())
        source = "\n".join(path.read_text(encoding="utf-8") for path in APP_SOURCE_FILES)
        self.assertNotIn("import tkinter", source)
        self.assertNotIn("from tkinter", source)

    def test_dark_and_light_qt_themes_are_present(self) -> None:
        source = (ROOT / "src" / "gtmce" / "theme.py").read_text(encoding="utf-8")
        self.assertIn("DARK = ThemePalette", source)
        self.assertIn("LIGHT = ThemePalette", source)
        self.assertIn("QMainWindow", source)
        self.assertIn("QProgressBar", source)

    def test_split_runtime_modules_are_compiled_in_ci(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for name in ("mkv_creator_ui.py", "src", "scripts/build_windows_exe.py"):
            self.assertIn(name, workflow)


if __name__ == "__main__":
    unittest.main()
