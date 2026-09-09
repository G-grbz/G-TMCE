# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import math
import mimetypes
import os
import platform
import queue
import re
import secrets
import shlex
import ssl
import stat
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import certifi
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None


def app_runtime_dir() -> Path:
    """Return a writable app folder."""
    if getattr(sys, "frozen", False):
        appimage_path = os.environ.get("APPIMAGE")
        if appimage_path:
            return Path(appimage_path).resolve().parent
        return Path(sys.executable).resolve().parent
    # Source modules live in src/gtmce/, while runtime assets and VERSION stay
    # at the project root. Frozen builds continue to use the executable folder.
    return Path(__file__).resolve().parents[2]


def bundled_resource_path(name: str) -> Path:
    """Prefer a file beside the EXE/script, fall back to PyInstaller bundle data."""
    for external in (APP_DIR / "assets" / name, APP_DIR / name):
        if external.exists():
            return external
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        for bundled in (Path(bundle_dir) / "assets" / name, Path(bundle_dir) / name):
            if bundled.exists():
                return bundled
    return APP_DIR / "assets" / name


APP_DIR = app_runtime_dir()
APP_NAME = "G-TMCE"
APP_ID = "g-tmce"
APP_REPOSITORY_URL = "https://github.com/G-grbz/G-TMCE"
APP_TAG_SIMPLE_TAGS = (
    ("G_TMCE", APP_NAME),
    ("G_TMCE_URL", APP_REPOSITORY_URL),
)
APP_RELEASE_API_URL = "https://api.github.com/repos/G-grbz/G-TMCE/releases/latest"
APP_LATEST_RELEASE_URL = f"{APP_REPOSITORY_URL}/releases/latest"
DEFAULT_APP_VERSION = "source"


def read_app_version() -> str:
    env_version = os.environ.get("G_TMCE_VERSION", "").strip()
    if env_version:
        return env_version
    try:
        version = bundled_resource_path("VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_APP_VERSION
    return version or DEFAULT_APP_VERSION


def xdg_data_dirs() -> list[Path]:
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    candidates = [
        Path(data_home).expanduser()
        if data_home
        else Path.home() / ".local" / "share"
    ]
    for raw_path in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(
        os.pathsep
    ):
        raw_path = raw_path.strip()
        if raw_path:
            candidates.append(Path(raw_path).expanduser())

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.fspath(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates


def installed_icon_paths() -> list[Path]:
    icon_names = (f"{APP_ID}.png", f"{APP_NAME}.png")
    icon_sizes = (
        "1024x1024",
        "512x512",
        "256x256",
        "128x128",
        "64x64",
        "48x48",
        "32x32",
        "24x24",
        "16x16",
    )
    candidates: list[Path] = []
    for data_dir in xdg_data_dirs():
        for size in icon_sizes:
            for icon_name in icon_names:
                candidates.append(data_dir / "icons" / "hicolor" / size / "apps" / icon_name)
        for icon_name in icon_names:
            candidates.append(data_dir / "pixmaps" / icon_name)
    return candidates


def app_logo_path() -> Path:
    bundled = bundled_resource_path("logo.png")
    if bundled.exists():
        return bundled
    for candidate in installed_icon_paths():
        if candidate.exists():
            return candidate
    return bundled


DEFAULT_TEMPLATE = bundled_resource_path("mkv.mtxcfg")
APP_VERSION = read_app_version()
LOGO_PATH = app_logo_path()
# Compact defaults; the Qt window chooses a screen-relative size at runtime.
MAIN_WINDOW_WIDTH = 1180
MAIN_WINDOW_HEIGHT = 620
MAIN_WINDOW_MIN_WIDTH = 900
MAIN_WINDOW_MIN_HEIGHT = 600


def app_config_dir() -> Path:
    """Return the per-user config directory without changing the Linux path layout."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "g-tmce"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "g-tmce"


SETTINGS_PATH = app_config_dir() / "settings.json"
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"
OPENSUBTITLES_API_BASE = "https://api.opensubtitles.com/api/v1"
OPENSUBTITLES_USER_AGENT = f"{APP_NAME} v{APP_VERSION}"
THIRD_PARTY_DIR = app_config_dir() / "3rdParty"
THIRD_PARTY_BIN_DIR = THIRD_PARTY_DIR / "bin"
THIRD_PARTY_DOWNLOADS_DIR = THIRD_PARTY_DIR / ".downloads"
THIRD_PARTY_MKVTOOLNIX_APPDIR = THIRD_PARTY_BIN_DIR / "mkvtoolnix"
THIRD_PARTY_MKVTOOLNIX_STAGING_DIR = THIRD_PARTY_DIR / ".mkvtoolnix-new"
THIRD_PARTY_STATE_PATH = THIRD_PARTY_DIR / "installed.json"
MKVTOOLNIX_APPIMAGE_INDEX_URL = "https://mkvtoolnix.download/appimage/"
MKVTOOLNIX_DOWNLOADS_URL = "https://mkvtoolnix.download/downloads.html"
FFMPEG_RELEASE_API_URL = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
THIRD_PARTY_USER_AGENT = f"{APP_NAME}/{APP_VERSION} Python/{sys.version_info.major}.{sys.version_info.minor}"
THIRD_PARTY_ALLOWED_HOSTS = frozenset({
    "api.github.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "mkvtoolnix.download",
})
OPENSUBTITLES_ALLOWED_HOST_SUFFIX = ".opensubtitles.com"
MAX_JSON_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_RESPONSE_BYTES = 25 * 1024 * 1024
MAX_SUBTITLE_RESPONSE_BYTES = 25 * 1024 * 1024
MAX_THIRD_PARTY_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024

UI_COLORS = {
    "window": "#eef1f7",
    "surface": "#ffffff",
    "surface_alt": "#f4f6fb",
    "surface_hover": "#eef0fd",
    "border": "#dfe3ed",
    "border_strong": "#c7cede",
    "text": "#161b2c",
    "muted": "#66708a",
    "accent": "#4f46e5",
    "accent_hover": "#4338ca",
    "accent_pressed": "#3730a3",
    "accent_soft": "#eeecfc",
    "disabled": "#b7bccb",
    "shadow": "#ccd2e2",
    "success": "#15803d",
    "success_soft": "#dcfce7",
    "danger": "#dc2626",
}

DEFAULT_UI_LANGUAGE = "en"
UI_LANGUAGE_NAMES = {"en": "English", "tr": "Türkçe"}
UI_LANGUAGE_BY_NAME = {name: code for code, name in UI_LANGUAGE_NAMES.items()}
ACTIVE_UI_LANGUAGE = DEFAULT_UI_LANGUAGE

UI_TEXT = {
    "en": {
        "status_ready": "Ready",
        "status_processing": "Processing...",
        "status_completed": "Completed.",
        "status_progress_percent": "Progress: {percent}%",
        "error_prefix": "Error: {message}",
        "error_video_fps_positive": "Video FPS must be greater than zero.",
        "error_video_fps_fraction_positive": "Video FPS fraction must be greater than zero.",
        "error_video_fps_format": "Enter Video FPS as 24, 23.976, or 24000/1001.",
        "error_required": "{label} is required.",
        "error_minutes_numeric": "{label} must be a numeric minute value.",
        "error_minutes_positive": "{label} must be greater than zero.",
        "error_chapter_start_integer": "Chapter start number must be a positive integer.",
        "error_chapter_start_positive": "Chapter start number must be greater than zero.",
        "error_config_not_found": "Config file not found: {path}",
        "error_config_json": "Config file is not valid JSON: {error}",
        "track_type_audio": "audio",
        "track_type_video": "video",
        "track_type_subtitle": "subtitle",
        "track_type_artwork": "artwork",
        "track_type_generic": "track",
        "error_unsupported_track_type": "Unsupported track type: {name}",
        "error_extra_subtitle_template_missing": "No subtitle template is available in the config for extra subtitles.",
        "error_auto_chapter_name_required": "Enter a chapter name for automatic chapters.",
        "field_chapter_interval": "Chapter interval",
        "field_chapter_end": "Chapter end",
        "error_auto_chapter_end_required": "Enter an end minute for automatic chapters, or use a track with a detectable duration.",
        "error_chapter_start_after_end": "Chapter start time is greater than the end minute.",
        "error_mkvmerge_missing": "mkvmerge is not available in 3rdParty.",
        "error_third_party_platform": "Automatic {name} download is not available for this platform: {platform} {arch}.",
        "error_third_party_latest_failed": "Could not check the latest {name} release: {reason}",
        "error_third_party_download_failed": "{name} could not be downloaded: {reason}",
        "error_third_party_install_failed": "{name} could not be prepared: {reason}",
        "error_third_party_missing": "{name} is not available in 3rdParty.",
        "error_mux_no_files": "No files were found to mux.",
        "error_tmdb_request_failed": "TMDB request failed ({code}): {message}",
        "error_tmdb_connection_failed": "Could not connect to TMDB: {reason}",
        "error_image_download_failed": "Image download failed: {reason}",
        "error_subtitle_api_required": "OpenSubtitles API key is required.",
        "error_subtitle_credentials_required": "OpenSubtitles username and password are required to download subtitles.",
        "error_subtitle_request_failed": "OpenSubtitles request failed ({code}): {message}",
        "error_subtitle_connection_failed": "Could not connect to OpenSubtitles: {reason}",
        "error_subtitle_no_results": "No subtitles were found.",
        "error_subtitle_no_selection": "Select at least one subtitle result.",
        "error_subtitle_all_selected_downloaded": "Selected subtitle results are already downloaded.",
        "error_subtitle_download_link_missing": "OpenSubtitles did not return a download link.",
        "error_subtitle_file_empty": "Downloaded subtitle file is empty.",
        "error_subtitle_missing_target": "Subtitle target folder is missing: {path}",
        "error_tmdb_svg_logo": "TMDB returned an SVG for {name}; no PNG logo was available.",
        "error_pillow_image_convert": "Pillow must be installed to convert images.",
        "error_pillow_small_cover": "Pillow must be installed to create small cover artwork.",
        "error_file_prepare_failed": "{name} could not be prepared: {error}",
        "log_file_not_found_skipped": "{name} was not found; skipped.",
        "log_file_prepare_skipped": "{name} could not be prepared; skipped: {error}",
        "log_file_exists_skipped": "{name} already exists; skipped.",
        "log_tags_exists": "tags.xml already exists; checked.",
        "log_tags_ready": "tags.xml is ready.",
        "log_tmdb_title": "TMDB title: {title}",
        "log_cover_ready": "cover.jpg is ready.",
        "log_small_cover_ready": "small_cover.jpg is ready.",
        "log_small_cover_skipped": "small_cover.jpg could not be prepared; skipped: {error}",
        "log_cover_land_ready": "cover_land.jpg is ready.",
        "log_small_cover_land_ready": "small_cover_land.jpg is ready.",
        "log_small_cover_land_skipped": "small_cover_land.jpg could not be prepared; skipped: {error}",
        "log_logo_ready": "logo.png is ready.",
        "error_folder_title_missing": "Could not derive a title from the folder name. Select the track folder manually.",
        "error_tmdb_no_result": "No TMDB result found for: {query}{year_text}",
        "error_tmdb_missing_id": "The TMDB result does not include an ID.",
        "error_mkv_source_not_found": "Source MKV not found: {source}",
        "error_mkv_read_failed": "MKV could not be read: {message}",
        "error_mkv_json_parse_failed": "Could not parse mkvmerge JSON output: {error}",
        "error_mkv_not_recognized": "Selected file was not recognized as an MKV.",
        "error_mkvextract_missing": "mkvextract is not available in 3rdParty.",
        "error_extract_none_selected": "No items are selected for extraction.",
        "label_ui_language": "Interface language",
        "app_tagline": "MKV muxing, metadata & subtitle toolkit",
        "tooltip_switch_to_light_theme": "Switch to light theme",
        "tooltip_switch_to_dark_theme": "Switch to dark theme",
        "section_create_mkv": "Create MKV",
        "path_template": "Template config (optional)",
        "path_track_folder": "Track folder",
        "path_output_mkv": "Output MKV",
        "label_output_name_extra": "Output name suffix",
        "option_output_name_year": "Year",
        "button_browse": "Browse",
        "button_show": "Show",
        "button_update_third_party": "Update Tools",
        "button_app_update_available": "Update Available",
        "label_image_language": "Artwork language",
        "label_tag_language": "Tag language",
        "label_tmdb_media_type": "TMDB type",
        "media_type_movie": "Movie",
        "media_type_tv": "TV",
        "button_find_id": "Find ID",
        "window_tmdb_search_title": "Search TMDB",
        "label_tmdb_search_query": "Movie / TV title",
        "button_tmdb_search": "Search",
        "label_tmdb_search_status_ready": "Enter a title to search movies and TV shows.",
        "label_tmdb_search_status_searching": "Searching TMDB...",
        "label_tmdb_search_status_no_results": "No movie or TV results were found.",
        "label_tmdb_search_status_results": "Found {count} movie / TV results.",
        "error_tmdb_search_query_empty": "Enter a movie or TV title.",
        "error_tmdb_search_no_selection": "Select a TMDB result.",
        "heading_tmdb_search_type": "Type",
        "heading_tmdb_search_title": "Title",
        "heading_tmdb_search_original_title": "Original title",
        "heading_tmdb_search_year": "Year",
        "heading_tmdb_search_id": "TMDB ID",
        "button_tmdb_use_selected": "Use Selected",
        "label_mkv_title": "MKV title",
        "label_default_tracks": "Default tracks",
        "label_audio_order": "Audio priority",
        "label_subtitle_order": "Subtitle priority",
        "option_include_extra_subtitles": "Include additional subtitles",
        "option_add_tracks_before_mux": "Add tracks before muxing",
        "option_download_before_mux": "Prepare artwork and tags before muxing",
        "option_enable_extract_context_menu": "Enable Extract right-click menu",
        "tooltip_context_menu_unavailable": "Available in the Windows EXE and Linux AppImage (KDE Dolphin).",
        "option_download_missing_mux_assets": "Fill missing artwork/tags from TMDB",
        "label_auto_chapters": "Automatic chapters",
        "option_create_if_missing": "Create if missing",
        "option_detect_intro_end": "Detect intro end",
        "label_chapter_name": "Name",
        "label_chapter_interval": "Interval (min)",
        "label_chapter_start": "Start #",
        "label_chapter_end": "End (min)",
        "button_scan_tracks": "Adjust Audio",
        "window_audio_adjust_title": "Audio Adjust",
        "window_mux_tracks_title": "Add Tracks",
        "audio_adjust_hint": "Duration (ms): Enter a value in milliseconds. Positive (+) values create a new audio file with the specified amount of silence added to the beginning while preserving the original codec and channel layout, effectively delaying the audio. Negative (-) values trim the specified amount from the beginning of the audio track, effectively advancing the audio. Leave blank or set to 0 if you only want to change codec or output settings.\n\nVolume: 1x preserves the original volume level. Values between 1.1x and 5x increase the audio volume. Higher values may introduce distortion/clipping and should be used with caution.",
        "mux_tracks_drop_hint": "Drag and drop files to add tracks, chapters, tags, or artwork",
        "button_add_tracks": "Add Files",
        "button_include_track": "Include",
        "button_remove_track": "Remove",
        "button_move_track_up": "Up",
        "button_move_track_down": "Down",
        "label_track_language": "Language",
        "label_track_delay": "Delay (ms)",
        "heading_audio_append": "Append",
        "heading_audio_file": "Audio file",
        "heading_track_type": "Type",
        "heading_audio_delta": "Delta (ms)",
        "heading_audio_codec": "Codec",
        "heading_audio_bitrate": "Bitrate",
        "heading_audio_rate": "Sample rate",
        "heading_audio_layout": "Layout",
        "heading_audio_volume": "Volume",
        "heading_audio_speed": "Audio FPS Sync",
        "button_apply_audio_adjust": "Apply",
        "error_ffmpeg_missing": "ffmpeg is not available in 3rdParty.",
        "error_audio_adjust_none": "Select at least one audio track and enter milliseconds or change codec/output settings.",
        "error_audio_adjust_numeric": "Milliseconds must be numeric, for example +1 or -967.",
        "error_audio_codec_unsupported": "Unsupported audio codec: {codec}",
        "error_ffmpeg_exit": "ffmpeg exited with error code: {code}",
        "log_audio_adjust_ready": "Audio adjustment ready: {name}",
        "log_audio_adjust_command": "Audio ffmpeg command:",
        "status_adjusting_audio": "Adjusting audio...",
        "button_download_assets": "Download Artwork/Tags",
        "button_download_subtitles": "Download Subtitles",
        "button_write_config": "Write Config",
        "button_create_mkv": "Create MKV",
        "button_cancel": "Cancel",
        "button_cancel_job": "Cancel Job",
        "button_show_log": "Show Log",
        "section_extract": "MKV Extract",
        "path_source_mkv": "Source MKV / folder",
        "path_extract_folder": "Extraction folder",
        "button_browse_file": "File",
        "button_browse_folder": "Folder",
        "button_extract_folder": "Extract Folder",
        "button_mux_extracted_folder": "Mux Extracted Folder",
        "dialog_template_title": "Select MKVToolNix config",
        "filetype_all": "All files",
        "filetype_video": "Video files",
        "filetype_matroska": "Matroska video",
        "dialog_config_error": "Config error",
        "dialog_track_folder_title": "Select track folder",
        "dialog_add_track_files_title": "Select tracks",
        "dialog_add_append_audio_title": "Select audio append files",
        "window_subtitle_download_title": "Download Subtitles",
        "label_subtitle_api_key": "OpenSubtitles API key",
        "label_subtitle_username": "Username",
        "label_subtitle_password": "Password",
        "label_subtitle_language": "Subtitle language",
        "label_subtitle_query": "Search",
        "label_subtitle_target": "Target",
        "label_subtitle_status_ready": "Ready.",
        "label_subtitle_status_no_results": "No subtitles found. You can search again.",
        "button_search_subtitles": "Search",
        "button_download_selected_subtitle": "Download Selected",
        "button_download_best_subtitles": "Download Best",
        "heading_subtitle_status": "Status",
        "heading_subtitle_target": "Target",
        "heading_subtitle_language": "Lang",
        "heading_subtitle_release": "Release",
        "heading_subtitle_fps": "FPS",
        "heading_subtitle_flags": "Flags",
        "heading_subtitle_downloads": "Downloads",
        "heading_subtitle_file": "File",
        "dialog_output_mkv_title": "Select output MKV",
        "dialog_source_mkv_title": "Select source MKV / folder",
        "dialog_extract_folder_title": "Select extraction folder",
        "dialog_missing_info": "Missing information",
        "dialog_overwrite_title": "Overwrite file?",
        "dialog_overwrite_message": "{name} already exists. Overwrite it?",
        "dialog_in_progress_title": "Operation in progress",
        "dialog_in_progress_message": "Wait for the current operation to finish before starting another one.",
        "dialog_error_title": "Error",
        "error_template_missing": "Template config not found: {path}",
        "error_track_folder_not_selected": "Track folder is not selected.",
        "error_track_folder_not_found": "Track folder not found: {path}",
        "error_track_file_not_found": "Track file not found: {path}",
        "error_track_delay_format": "Track delay must be an integer millisecond value, for example 1000 or -1000.",
        "error_append_audio_selected": "Select an audio track first.",
        "error_append_audio_type": "Append files must be audio files with the same extension as {name}.",
        "error_append_audio_self": "A track cannot be appended to itself.",
        "error_unsupported_mux_asset_name": "Unsupported metadata/artwork file: {name}. Use chapters.txt, tags.xml, cover.jpg, small_cover.jpg, cover_land.jpg, small_cover_land.jpg, or logo.png.",
        "log_output_default_used": "Output path was empty; using the default: {path}",
        "error_tmdb_media_type": "TMDB type must be Movie or TV.",
        "error_tmdb_api_empty": "TMDB API key is required.",
        "error_tmdb_artwork_api_required": "To use the artwork/tag creation feature, you must have a valid TMDB API key. If you do not have an API key, clear the checkbox.",
        "error_tmdb_id_empty": "TMDB ID is required.",
        "error_tmdb_id_numeric": "TMDB ID must be numeric.",
        "error_source_mkv_not_selected": "Source MKV is not selected.",
        "error_source_folder_not_selected": "Source folder is not selected.",
        "error_source_folder_not_found": "Source folder not found: {source}",
        "error_batch_no_video_files": "No video files were found in the source folder.",
        "error_episode_number_missing": "Could not read season/episode from the file name: {name}",
        "error_batch_tmdb_tv_required": "Folder batch with TMDB must use TV type.",
        "error_batch_extract_dir_missing": "Extracted track folder not found: {path}",
        "log_tracks_found": "Tracks found: {count}",
        "log_custom_tracks_ready": "Custom mux list ready: {count} items.",
        "log_manual_asset_ready": "{name} was copied to the track folder.",
        "log_extra_subtitle_suffix": " (additional subtitle)",
        "log_default_track_suffix": " | default",
        "log_optional_tracks_missing": "Missing optional items: {items}",
        "log_optional_tracks_clear": "No optional items are missing.",
        "status_scanning_tracks": "Scanning tracks...",
        "log_tmdb_id_auto_failed": "Automatic TMDB ID lookup failed: {error}",
        "log_output_from_artwork_language": "Output name set from artwork language: {name}",
        "log_title_from_tag_language": "MKV title set from tag language: {title}",
        "log_tmdb_id_found": "TMDB ID found: {tmdb_id} - {title}{year_text}",
        "status_finding_tmdb": "Finding TMDB ID...",
        "status_downloading_assets": "Downloading artwork and tags...",
        "status_searching_subtitles": "Searching subtitles...",
        "status_downloading_subtitles": "Downloading subtitles...",
        "subtitle_target_single": "{folder}",
        "subtitle_target_batch": "Batch TV folders: {count} episodes",
        "log_subtitle_results_found": "Subtitle results found: {count}",
        "log_subtitle_no_result_for_target": "No subtitle found for {target}.",
        "log_subtitle_downloaded": "Subtitle downloaded: {path}",
        "log_batch_subtitles_complete": "Folder subtitle download completed: {count} subtitles.",
        "value_subtitle_downloaded": "Downloaded",
        "value_subtitle_flag_hi": "SDH",
        "value_subtitle_flag_forced": "forced",
        "value_subtitle_flag_trusted": "trusted",
        "value_subtitle_flag_machine": "machine",
        "value_subtitle_flag_ai": "AI",
        "log_config_written": "Config written: {path}",
        "status_writing_config": "Writing config...",
        "error_output_exists_choose": "{name} already exists. Choose a different name or move the existing file.",
        "log_skipped_optional_tracks": "Skipped optional items: {items}",
        "log_mkvmerge_command": "mkvmerge command:",
        "error_mkvmerge_exit": "mkvmerge exited with error code: {code}",
        "error_output_delete_failed": "{name} could not be deleted: {error}",
        "log_mkvmerge_warnings": "mkvmerge completed with warnings.",
        "log_mkv_created": "MKV created: {path}",
        "log_batch_episode": "Batch episode {index}/{count}: {name}",
        "log_batch_extract_dir": "Episode tracks folder: {path}",
        "log_batch_final_folder": "Final season folder: {path}",
        "log_batch_moved": "Moved MKV: {path}",
        "log_batch_extract_complete": "Folder extraction completed: {count} episode folders.",
        "log_batch_assets_complete": "Folder artwork/tag refresh completed: {count} episode folders.",
        "log_batch_mux_complete": "Folder mux completed: {count} MKV files.",
        "status_creating_mkv": "Creating MKV...",
        "status_batch_extract_folder": "Extracting folder...",
        "status_batch_mux_folder": "Muxing extracted folder...",
        "log_detecting_chapter_end": "Detecting chapter end...",
        "log_detecting_intro_end": "Detecting intro end...",
        "status_cancelling": "Cancelling...",
        "log_operation_cancelled": "Operation cancelled.",
        "button_scan_mkv": "Scan MKV",
        "button_toggle_selection": "Toggle Selection",
        "button_select_all": "Select All",
        "button_clear_all": "Clear All",
        "button_extract_selected": "Extract Selected",
        "context_cut": "Cut",
        "context_copy": "Copy",
        "context_paste": "Paste",
        "context_delete": "Delete",
        "context_select_all": "Select All",
        "heading_selected": "Use",
        "heading_track": "Track",
        "heading_output_name": "Output name",
        "extract_und_language_hint": "Tracks with und language: enter a language code for output names, or leave empty to keep und.",
        "heading_extract_language": "Language",
        "value_yes": "Yes",
        "value_no": "No",
        "window_log_title": "{app} Operation Log",
        "log_video_fps_detected": "Video FPS detected: {fps}",
        "log_mkv_items_found": "MKV items found: {count}",
        "error_scan_extract_first": "Scan the MKV first to list available items.",
        "log_mkvextract_command": "mkvextract command:",
        "log_ffmpeg_extract_command": "ffmpeg extract command:",
        "error_mkvextract_exit": "mkvextract exited with error code: {code}",
        "error_ffmpeg_extract_exit": "ffmpeg exited with error code: {code}",
        "error_extract_non_matroska_metadata": "Attachments, chapters, and tags can only be extracted from Matroska/WebM files. Deselect them or use an MKV/WebM source.",
        "log_mkvextract_warnings": "mkvextract completed with warnings.",
        "log_tracks_extracted": "Tracks extracted: {path}",
        "log_folder_set_for_mux": "Track folder updated for muxing.",
        "status_scanning_mkv": "Scanning MKV...",
        "status_extracting_tracks": "Extracting tracks...",
        "status_updating_third_party": "Checking/downloading tools...",
        "log_app_update_available": "Application update available: {version}",
        "log_third_party_checking": "Checking {name}...",
        "log_third_party_current": "{name} is already current: {version}",
        "log_third_party_updated": "{name} updated: {version}",
        "log_third_party_existing_used": "{name} update check failed; using existing 3rdParty version: {version}",
        "log_third_party_complete": "3rdParty tools are ready.",
        "error_unexpected": "Unexpected error: {error}",
        "log_settings_save_failed": "Settings could not be saved: {error}",
        "extract_label_track": "Track {track_id} | {track_type} | {language} | {codec}",
        "extract_label_attachment": "Attachment {attachment_id} | {description}",
        "extract_label_chapters": "Chapters | simple txt",
        "extract_label_tags": "Tags | XML",
        "speed_factor_auto": "Auto (none)",
        "speed_factor_23976_24000": "23.976 → 24",
        "speed_factor_24000_23976": "24 → 23.976",
        "speed_factor_24000_25000": "24 → 25",
        "speed_factor_23976_25000": "23.976 → 25",
        "speed_factor_25000_23976": "25 → 23.976",
        "speed_factor_25000_24000": "25 → 24",
        "speed_factor_30000_23976": "30 → 23.976",
        "speed_factor_30000_24000": "30 → 24",
        "speed_factor_30000_25000": "30 → 25",
    },
    "tr": {
        "status_ready": "Hazır",
        "status_processing": "İşlem sürüyor...",
        "status_completed": "Tamamlandı.",
        "status_progress_percent": "İlerleme: {percent}%",
        "error_prefix": "Hata: {message}",
        "error_video_fps_positive": "Video FPS sıfırdan büyük olmalı.",
        "error_video_fps_fraction_positive": "Video FPS kesri sıfırdan büyük olmalı.",
        "error_video_fps_format": "Video FPS değeri 24, 23.976 veya 24000/1001 gibi olmalı.",
        "error_required": "{label} boş.",
        "error_minutes_numeric": "{label} dakika olarak sayısal girilmeli.",
        "error_minutes_positive": "{label} sıfırdan büyük olmalı.",
        "error_chapter_start_integer": "Chapter başlangıç numarası pozitif tam sayı olmalı.",
        "error_chapter_start_positive": "Chapter başlangıç numarası sıfırdan büyük olmalı.",
        "error_config_not_found": "Config bulunamadı: {path}",
        "error_config_json": "Config JSON olarak okunamadı: {error}",
        "track_type_audio": "ses",
        "track_type_video": "video",
        "track_type_subtitle": "altyazı",
        "track_type_artwork": "görsel",
        "track_type_generic": "parça",
        "error_unsupported_track_type": "Desteklenmeyen parça türü: {name}",
        "error_extra_subtitle_template_missing": "Ek altyazı için config içinde kopyalanacak altyazı şablonu yok.",
        "error_auto_chapter_name_required": "Otomatik chapter için chapter adı girilmeli.",
        "field_chapter_interval": "Chapter aralığı",
        "field_chapter_end": "Chapter bitiş",
        "error_auto_chapter_end_required": "Otomatik chapter için bitiş dakikası gir veya süre algılanabilen bir parça kullan.",
        "error_chapter_start_after_end": "Chapter başlangıç zamanı bitiş dakikasından büyük.",
        "error_mkvmerge_missing": "mkvmerge 3rdParty içinde kullanıma hazır değil.",
        "error_third_party_platform": "{name} otomatik indirme bu platformda yok: {platform} {arch}.",
        "error_third_party_latest_failed": "{name} güncel sürüm kontrolü yapılamadı: {reason}",
        "error_third_party_download_failed": "{name} indirilemedi: {reason}",
        "error_third_party_install_failed": "{name} hazırlanamadı: {reason}",
        "error_third_party_missing": "{name} 3rdParty içinde kullanıma hazır değil.",
        "error_mux_no_files": "Mux edilecek dosya bulunamadı.",
        "error_tmdb_request_failed": "TMDB isteği başarısız ({code}): {message}",
        "error_tmdb_connection_failed": "TMDB bağlantısı kurulamadı: {reason}",
        "error_image_download_failed": "Görsel indirilemedi: {reason}",
        "error_subtitle_api_required": "OpenSubtitles API key boş.",
        "error_subtitle_credentials_required": "Altyazı indirmek için OpenSubtitles kullanıcı adı ve şifre gerekli.",
        "error_subtitle_request_failed": "OpenSubtitles isteği başarısız ({code}): {message}",
        "error_subtitle_connection_failed": "OpenSubtitles bağlantısı kurulamadı: {reason}",
        "error_subtitle_no_results": "Altyazı sonucu bulunamadı.",
        "error_subtitle_no_selection": "En az bir altyazı sonucu seç.",
        "error_subtitle_all_selected_downloaded": "Seçilen altyazı sonuçları zaten indirildi.",
        "error_subtitle_download_link_missing": "OpenSubtitles indirme linki döndürmedi.",
        "error_subtitle_file_empty": "İndirilen altyazı dosyası boş.",
        "error_subtitle_missing_target": "Altyazı hedef klasörü yok: {path}",
        "error_tmdb_svg_logo": "{name} için TMDB SVG döndürdü; PNG logo bulunamadı.",
        "error_pillow_image_convert": "Görsel dönüştürme için Pillow kurulu olmalı.",
        "error_pillow_small_cover": "Küçük kapak görseli üretmek için Pillow kurulu olmalı.",
        "error_file_prepare_failed": "{name} hazırlanamadı: {error}",
        "log_file_not_found_skipped": "{name} bulunamadı, atlandı.",
        "log_file_prepare_skipped": "{name} hazırlanamadı, atlandı: {error}",
        "log_file_exists_skipped": "{name} zaten var, atlandı.",
        "log_tags_exists": "tags.xml zaten var, kontrol edildi.",
        "log_tags_ready": "tags.xml hazır.",
        "log_tmdb_title": "TMDB içerik: {title}",
        "log_cover_ready": "cover.jpg hazır.",
        "log_small_cover_ready": "small_cover.jpg hazır.",
        "log_small_cover_skipped": "small_cover.jpg hazırlanamadı, atlandı: {error}",
        "log_cover_land_ready": "cover_land.jpg hazır.",
        "log_small_cover_land_ready": "small_cover_land.jpg hazır.",
        "log_small_cover_land_skipped": "small_cover_land.jpg hazırlanamadı, atlandı: {error}",
        "log_logo_ready": "logo.png hazır.",
        "error_folder_title_missing": "Klasör adından başlık çıkarılamadı. Parça klasörünü seç.",
        "error_tmdb_no_result": "TMDB sonucu bulunamadı: {query}{year_text}",
        "error_tmdb_missing_id": "TMDB sonucu ID içermiyor.",
        "error_mkv_source_not_found": "Kaynak MKV bulunamadı: {source}",
        "error_mkv_read_failed": "MKV okunamadı: {message}",
        "error_mkv_json_parse_failed": "mkvmerge JSON çıktısı okunamadı: {error}",
        "error_mkv_not_recognized": "Seçilen dosya MKV olarak tanınmadı.",
        "error_mkvextract_missing": "mkvextract 3rdParty içinde kullanıma hazır değil.",
        "error_extract_none_selected": "Çıkarılacak parça seçilmedi.",
        "label_ui_language": "Arayüz dili",
        "app_tagline": "MKV birleştirme, metadata ve altyazı araç takımı",
        "tooltip_switch_to_light_theme": "Aydınlık temaya geç",
        "tooltip_switch_to_dark_theme": "Karanlık temaya geç",
        "section_create_mkv": "MKV Oluştur",
        "path_template": "Şablon config (opsiyonel)",
        "path_track_folder": "Parça klasörü",
        "path_output_mkv": "Çıktı MKV",
        "label_output_name_extra": "Çıktı adı eki",
        "option_output_name_year": "Yıl",
        "button_browse": "Seç",
        "button_show": "Göster",
        "button_update_third_party": "Araçları Güncelle",
        "button_app_update_available": "Güncelleme Mevcut",
        "label_image_language": "Görsel dili",
        "label_tag_language": "Tag dili",
        "label_tmdb_media_type": "TMDB türü",
        "media_type_movie": "Film",
        "media_type_tv": "Dizi",
        "button_find_id": "ID Bul",
        "window_tmdb_search_title": "TMDB'de Ara",
        "label_tmdb_search_query": "Film / dizi adı",
        "button_tmdb_search": "Ara",
        "label_tmdb_search_status_ready": "Film veya dizi adı girerek arama yap.",
        "label_tmdb_search_status_searching": "TMDB aranıyor...",
        "label_tmdb_search_status_no_results": "Film veya dizi sonucu bulunamadı.",
        "label_tmdb_search_status_results": "{count} film / dizi sonucu bulundu.",
        "error_tmdb_search_query_empty": "Film veya dizi adı gir.",
        "error_tmdb_search_no_selection": "Bir TMDB sonucu seç.",
        "heading_tmdb_search_type": "Tür",
        "heading_tmdb_search_title": "Başlık",
        "heading_tmdb_search_original_title": "Orijinal başlık",
        "heading_tmdb_search_year": "Yıl",
        "heading_tmdb_search_id": "TMDB ID",
        "button_tmdb_use_selected": "Seçileni Kullan",
        "label_mkv_title": "MKV başlığı",
        "label_default_tracks": "Varsayılan iz",
        "label_audio_order": "Ses sırası",
        "label_subtitle_order": "Altyazı sırası",
        "option_include_extra_subtitles": "Fazla altyazıları ekle",
        "option_add_tracks_before_mux": "MKV öncesi parça ekle",
        "option_download_before_mux": "MKV oluşturmadan önce görsel/tag hazırla",
        "option_enable_extract_context_menu": "Extract sağ tık menüsünü etkinleştir",
        "tooltip_context_menu_unavailable": "Windows EXE ve Linux AppImage (KDE Dolphin) için kullanılabilir.",
        "option_download_missing_mux_assets": "Eksik görsel/tag TMDB'den tamamla",
        "label_auto_chapters": "Otomatik chapter",
        "option_create_if_missing": "Yoksa oluştur",
        "option_detect_intro_end": "Intro bitişini algıla",
        "label_chapter_name": "Ad",
        "label_chapter_interval": "Aralık dk",
        "label_chapter_start": "Başlangıç",
        "label_chapter_end": "Bitiş dk",
        "button_scan_tracks": "Ses Ayarla",
        "window_audio_adjust_title": "Ses Ayarla",
        "window_mux_tracks_title": "Parça Ekle",
        "audio_adjust_hint": "Süre (ms): Milisaniye cinsinden girilir. Pozitif (+) değerler, seçilen ses parçasının kodek ve kanal yapısını koruyarak başına belirtilen süre kadar sessizlik eklenmiş yeni bir ses dosyası oluşturur. Negatif (-) değerler ise ses parçasının başından belirtilen süreyi keserek sesi öne alır. Yalnızca kodek veya çıktı ayarlarını değiştirecekseniz boş bırakabilir ya da 0 girebilirsiniz.\n\nSes: 1x orijinal ses düzeyidir. 1.1x ile 5x arasındaki değerler sesi yükseltir. Yüksek değerlerde ses bozulması (distortion/clipping) oluşabileceğinden dikkatli kullanılması önerilir.",
        "mux_tracks_drop_hint": "Parça, chapter, tag veya görsel eklemek için dosyaları sürükle & bırak",
        "button_add_tracks": "Dosya Ekle",
        "button_include_track": "Ekle",
        "button_remove_track": "Kaldır",
        "button_move_track_up": "Yukarı",
        "button_move_track_down": "Aşağı",
        "label_track_language": "Dil",
        "label_track_delay": "Delay (ms)",
        "heading_audio_append": "İlave",
        "heading_audio_file": "Ses dosyası",
        "heading_track_type": "Tür",
        "heading_audio_delta": "Süre (ms)",
        "heading_audio_codec": "Kodek",
        "heading_audio_bitrate": "Bitrate",
        "heading_audio_rate": "Sample rate",
        "heading_audio_layout": "Layout",
        "heading_audio_volume": "Ses",
        "heading_audio_speed": "FPS Eşitle",
        "button_apply_audio_adjust": "Uygula",
        "error_ffmpeg_missing": "ffmpeg 3rdParty içinde kullanıma hazır değil.",
        "error_audio_adjust_none": "En az bir ses parçası seç ve milisaniye gir ya da kodek/çıkış ayarını değiştir.",
        "error_audio_adjust_numeric": "Milisaniye sayısal olmalı, örnek +1 veya -967.",
        "error_audio_codec_unsupported": "Desteklenmeyen ses kodeki: {codec}",
        "error_ffmpeg_exit": "ffmpeg hata kodu ile bitti: {code}",
        "log_audio_adjust_ready": "Ses ayarı hazır: {name}",
        "log_audio_adjust_command": "Ses ffmpeg komutu:",
        "status_adjusting_audio": "Ses ayarlanıyor...",
        "button_download_assets": "Görsel/Tag İndir",
        "button_download_subtitles": "Altyazı İndir",
        "button_write_config": "Config Yaz",
        "button_create_mkv": "MKV Oluştur",
        "button_cancel": "İptal",
        "button_cancel_job": "İşi İptal Et",
        "button_show_log": "Günlüğü Göster",
        "section_extract": "MKV Extract",
        "path_source_mkv": "Kaynak MKV / klasör",
        "path_extract_folder": "Çıkarma klasörü",
        "button_browse_file": "Dosya",
        "button_browse_folder": "Klasör",
        "button_extract_folder": "Klasörü Çıkar",
        "button_mux_extracted_folder": "Çıkan Klasörleri Birleştir",
        "dialog_template_title": "MKVToolNix config seç",
        "filetype_all": "Tüm dosyalar",
        "filetype_video": "Video dosyaları",
        "filetype_matroska": "Matroska video",
        "dialog_config_error": "Config hatası",
        "dialog_track_folder_title": "Parça klasörü seç",
        "dialog_add_track_files_title": "Parça seç",
        "dialog_add_append_audio_title": "İlave ses dosyalarını seç",
        "window_subtitle_download_title": "Altyazı İndir",
        "label_subtitle_api_key": "OpenSubtitles API key",
        "label_subtitle_username": "Kullanıcı adı",
        "label_subtitle_password": "Şifre",
        "label_subtitle_language": "Altyazı dili",
        "label_subtitle_query": "Arama",
        "label_subtitle_target": "Hedef",
        "label_subtitle_status_ready": "Hazır.",
        "label_subtitle_status_no_results": "Altyazı sonucu bulunamadı. Yeniden arama yapabilirsin.",
        "button_search_subtitles": "Ara",
        "button_download_selected_subtitle": "Seçileni İndir",
        "button_download_best_subtitles": "En İyiyi İndir",
        "heading_subtitle_status": "Durum",
        "heading_subtitle_target": "Hedef",
        "heading_subtitle_language": "Dil",
        "heading_subtitle_release": "Release",
        "heading_subtitle_fps": "FPS",
        "heading_subtitle_flags": "Bayrak",
        "heading_subtitle_downloads": "İndirme",
        "heading_subtitle_file": "Dosya",
        "dialog_output_mkv_title": "Çıktı MKV seç",
        "dialog_source_mkv_title": "Kaynak MKV / klasör seç",
        "dialog_extract_folder_title": "Çıkarma klasörü seç",
        "dialog_missing_info": "Eksik bilgi",
        "dialog_overwrite_title": "Üzerine yazılsın mı?",
        "dialog_overwrite_message": "{name} zaten var. Üzerine yazılsın mı?",
        "dialog_in_progress_title": "İşlem sürüyor",
        "dialog_in_progress_message": "Mevcut işlem bitmeden yeni işlem başlatılamaz.",
        "dialog_error_title": "Hata",
        "error_template_missing": "Şablon config bulunamadı: {path}",
        "error_track_folder_not_selected": "Parça klasörü seçilmedi.",
        "error_track_folder_not_found": "Parça klasörü bulunamadı: {path}",
        "error_track_file_not_found": "Parça dosyası bulunamadı: {path}",
        "error_track_delay_format": "Parça delay değeri tam sayı milisaniye olmalı, örnek 1000 veya -1000.",
        "error_append_audio_selected": "Önce bir ses parçası seç.",
        "error_append_audio_type": "İlave dosyalar {name} ile aynı uzantıda ses dosyası olmalı.",
        "error_append_audio_self": "Bir parça kendisine ilave edilemez.",
        "error_unsupported_mux_asset_name": "Desteklenmeyen metadata/görsel dosyası: {name}. chapters.txt, tags.xml, cover.jpg, small_cover.jpg, cover_land.jpg, small_cover_land.jpg veya logo.png kullan.",
        "log_output_default_used": "Çıktı yolu boştu, varsayılan kullanılıyor: {path}",
        "error_tmdb_media_type": "TMDB türü Film veya Dizi olmalı.",
        "error_tmdb_api_empty": "TMDB API key boş.",
        "error_tmdb_artwork_api_required": "Görsel/tag oluşturma özelliğini kullanmak için geçerli bir TMDB API anahtarınız olmalıdır. API anahtarınız yoksa onay kutusunun işaretini kaldırın.",
        "error_tmdb_id_empty": "TMDB ID boş.",
        "error_tmdb_id_numeric": "TMDB ID sayısal olmalı.",
        "error_source_mkv_not_selected": "Kaynak MKV seçilmedi.",
        "error_source_folder_not_selected": "Kaynak klasör seçilmedi.",
        "error_source_folder_not_found": "Kaynak klasör bulunamadı: {source}",
        "error_batch_no_video_files": "Kaynak klasörde video dosyası bulunamadı.",
        "error_episode_number_missing": "Dosya adından sezon/bölüm okunamadı: {name}",
        "error_batch_tmdb_tv_required": "TMDB ile klasör toplu işleminde tür Dizi olmalı.",
        "error_batch_extract_dir_missing": "Çıkarılmış parça klasörü bulunamadı: {path}",
        "log_tracks_found": "Bulunan parça sayısı: {count}",
        "log_custom_tracks_ready": "Özel mux listesi hazır: {count} öğe.",
        "log_manual_asset_ready": "{name} parça klasörüne kopyalandı.",
        "log_extra_subtitle_suffix": " (ek altyazı)",
        "log_default_track_suffix": " | varsayılan",
        "log_optional_tracks_missing": "Eksik opsiyonel parçalar: {items}",
        "log_optional_tracks_clear": "Eksik opsiyonel parça yok.",
        "status_scanning_tracks": "Parçalar taranıyor...",
        "log_tmdb_id_auto_failed": "TMDB ID otomatik bulunamadı: {error}",
        "log_output_from_artwork_language": "Çıktı adı görsel dilinden ayarlandı: {name}",
        "log_title_from_tag_language": "MKV başlığı tag dilinden ayarlandı: {title}",
        "log_tmdb_id_found": "TMDB ID bulundu: {tmdb_id} - {title}{year_text}",
        "status_finding_tmdb": "TMDB ID aranıyor...",
        "status_downloading_assets": "Görsel/tag indiriliyor...",
        "status_searching_subtitles": "Altyazı aranıyor...",
        "status_downloading_subtitles": "Altyazı indiriliyor...",
        "subtitle_target_single": "{folder}",
        "subtitle_target_batch": "Toplu dizi klasörleri: {count} bölüm",
        "log_subtitle_results_found": "Altyazı sonucu bulundu: {count}",
        "log_subtitle_no_result_for_target": "{target} için altyazı bulunamadı.",
        "log_subtitle_downloaded": "Altyazı indirildi: {path}",
        "log_batch_subtitles_complete": "Klasör altyazı indirme tamamlandı: {count} altyazı.",
        "value_subtitle_downloaded": "İndi",
        "value_subtitle_flag_hi": "SDH",
        "value_subtitle_flag_forced": "forced",
        "value_subtitle_flag_trusted": "güvenilir",
        "value_subtitle_flag_machine": "makine",
        "value_subtitle_flag_ai": "AI",
        "log_config_written": "Config yazıldı: {path}",
        "status_writing_config": "Config yazılıyor...",
        "error_output_exists_choose": "{name} zaten var. Farklı ad ver veya mevcut dosyayı taşı.",
        "log_skipped_optional_tracks": "Atlanan opsiyonel parçalar: {items}",
        "log_mkvmerge_command": "mkvmerge komutu:",
        "error_mkvmerge_exit": "mkvmerge hata kodu ile bitti: {code}",
        "error_output_delete_failed": "{name} silinemedi: {error}",
        "log_mkvmerge_warnings": "mkvmerge uyarılarla tamamlandı.",
        "log_mkv_created": "MKV oluşturuldu: {path}",
        "log_batch_episode": "Toplu bölüm {index}/{count}: {name}",
        "log_batch_extract_dir": "Bölüm parça klasörü: {path}",
        "log_batch_final_folder": "Final sezon klasörü: {path}",
        "log_batch_moved": "MKV taşındı: {path}",
        "log_batch_extract_complete": "Klasör çıkarma tamamlandı: {count} bölüm klasörü.",
        "log_batch_assets_complete": "Klasör görsel/tag yenileme tamamlandı: {count} bölüm klasörü.",
        "log_batch_mux_complete": "Klasör birleştirme tamamlandı: {count} MKV.",
        "status_creating_mkv": "MKV oluşturuluyor...",
        "status_batch_extract_folder": "Klasör çıkarılıyor...",
        "status_batch_mux_folder": "Çıkan klasörler birleştiriliyor...",
        "log_detecting_chapter_end": "Chapter bitişi algılanıyor...",
        "log_detecting_intro_end": "Intro bitişi algılanıyor...",
        "status_cancelling": "İptal ediliyor...",
        "log_operation_cancelled": "İş iptal edildi.",
        "button_scan_mkv": "MKV Tara",
        "button_toggle_selection": "Seçimi Değiştir",
        "button_select_all": "Tümünü Seç",
        "button_clear_all": "Tümünü Bırak",
        "button_extract_selected": "Seçileni Çıkar",
        "context_cut": "Kes",
        "context_copy": "Kopyala",
        "context_paste": "Yapıştır",
        "context_delete": "Sil",
        "context_select_all": "Tümünü Seç",
        "heading_selected": "Al",
        "heading_track": "Parça",
        "heading_output_name": "Çıktı adı",
        "extract_und_language_hint": "Dili und olan parçalar: çıktı adı için dil kodu gir veya und kalması için boş bırak.",
        "heading_extract_language": "Dil",
        "value_yes": "Evet",
        "value_no": "Hayır",
        "window_log_title": "{app} İşlem Günlüğü",
        "log_video_fps_detected": "Video FPS algılandı: {fps}",
        "log_mkv_items_found": "MKV parça sayısı: {count}",
        "error_scan_extract_first": "Önce MKV Tara ile parçaları listele.",
        "log_mkvextract_command": "mkvextract komutu:",
        "log_ffmpeg_extract_command": "ffmpeg çıkarma komutu:",
        "error_mkvextract_exit": "mkvextract hata kodu ile bitti: {code}",
        "error_ffmpeg_extract_exit": "ffmpeg hata kodu ile bitti: {code}",
        "error_extract_non_matroska_metadata": "Ekler, chapter ve tag yalnızca Matroska/WebM dosyalarından çıkarılabilir. Bunları seçme veya MKV/WebM kaynak kullan.",
        "log_mkvextract_warnings": "mkvextract uyarılarla tamamlandı.",
        "log_tracks_extracted": "Parçalar çıkarıldı: {path}",
        "log_folder_set_for_mux": "Parça klasörü birleştirme için güncellendi.",
        "status_scanning_mkv": "MKV taranıyor...",
        "status_extracting_tracks": "Parçalar çıkarılıyor...",
        "status_updating_third_party": "Araçlar denetleniyor/indiriliyor...",
        "log_app_update_available": "Uygulama güncellemesi mevcut: {version}",
        "log_third_party_checking": "{name} denetleniyor...",
        "log_third_party_current": "{name} zaten güncel: {version}",
        "log_third_party_updated": "{name} güncellendi: {version}",
        "log_third_party_existing_used": "{name} güncelleme denetimi başarısız; mevcut 3rdParty sürümü kullanılıyor: {version}",
        "log_third_party_complete": "3rdParty araçları hazır.",
        "error_unexpected": "Beklenmeyen hata: {error}",
        "log_settings_save_failed": "Ayarlar kaydedilemedi: {error}",
        "extract_label_track": "İz {track_id} | {track_type} | {language} | {codec}",
        "extract_label_attachment": "Ek {attachment_id} | {description}",
        "extract_label_chapters": "Chapter | simple txt",
        "extract_label_tags": "Tag | XML",
        "speed_factor_auto": "Otomatik (yok)",
        "speed_factor_23976_24000": "23.976 → 24",
        "speed_factor_24000_23976": "24 → 23.976",
        "speed_factor_24000_25000": "24 → 25",
        "speed_factor_23976_25000": "23.976 → 25",
        "speed_factor_25000_23976": "25 → 23.976",
        "speed_factor_25000_24000": "25 → 24",
        "speed_factor_30000_23976": "30 → 23.976",
        "speed_factor_30000_24000": "30 → 24",
        "speed_factor_30000_25000": "30 → 25",
    },
}


def normalise_ui_language(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("tr") or raw == "türkçe":
        return "tr"
    return DEFAULT_UI_LANGUAGE


def set_active_ui_language(language: str | None) -> None:
    global ACTIVE_UI_LANGUAGE
    ACTIVE_UI_LANGUAGE = normalise_ui_language(language)


def ui_text(key: str, **values: Any) -> str:
    template = UI_TEXT.get(ACTIVE_UI_LANGUAGE, {}).get(key)
    if template is None:
        template = UI_TEXT[DEFAULT_UI_LANGUAGE].get(key, key)
    return template.format(**values) if values else template


TMDB_MEDIA_TYPES = ("movie", "tv")


def normalise_tmdb_media_type(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in TMDB_MEDIA_TYPES:
        return raw
    return "movie"

def native_file_dialog_available() -> str | None:
    """Return preferred native Linux file dialog command."""
    if os.name != "posix":
        return None

    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        + " "
        + os.environ.get("DESKTOP_SESSION", "")
    ).lower()

    if "kde" in desktop and shutil.which("kdialog"):
        return "kdialog"

    if shutil.which("zenity"):
        return "zenity"

    if shutil.which("kdialog"):
        return "kdialog"

    return None


def dialog_initial_dir(value: str | Path | None) -> str:
    path = Path(value).expanduser() if value else Path.home()
    if path.is_file():
        path = path.parent
    if not path.exists():
        path = Path.home()
    return str(path)


def system_gui_subprocess_env() -> dict[str, str]:
    """Return a host-safe environment for kdialog/zenity from frozen builds."""
    env = os.environ.copy()

    # PyInstaller prepends its extraction directory to LD_LIBRARY_PATH. System
    # GUI programs such as kdialog/zenity must use the host libraries instead
    # of the bundled copies, otherwise they can fail before showing a dialog.
    if os.name == "posix":
        original_ld_path = env.get("LD_LIBRARY_PATH_ORIG")
        if original_ld_path is not None:
            env["LD_LIBRARY_PATH"] = original_ld_path
        else:
            env.pop("LD_LIBRARY_PATH", None)
        env.pop("LD_PRELOAD", None)

    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "TMDB_API_KEY",
        "OPENSUBTITLES_API_KEY",
        "OPENSUBTITLES_USERNAME",
        "OPENSUBTITLES_PASSWORD",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        env.pop(key, None)

    return env


def run_dialog_command(args: list[str]) -> str | None:
    """Run a host file-dialog helper. None means failure; empty means cancel."""
    try:
        process = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=system_gui_subprocess_env(),
        )
    except OSError:
        return None

    if process.returncode == 0:
        return (process.stdout or "").strip()
    if process.returncode == 1:
        # kdialog and zenity both use 1 for a normal user cancellation.
        return ""

    # Any other status is an execution failure. Returning None lets callers
    # let the Qt UI fall back to QFileDialog instead of silently doing nothing.
    return None


def kdialog_filter_string(filetypes: tuple[tuple[str, str], ...]) -> str:
    """Return a filter string in the format expected by KDE/kdialog."""
    filters: list[str] = []
    for label, pattern in filetypes:
        clean_pattern = str(pattern or "*").strip() or "*"
        clean_label = str(label or clean_pattern).strip() or clean_pattern
        filters.append(f"{clean_pattern}|{clean_label}")
    return "\n".join(filters)


def native_open_file(
    title: str,
    initialdir: str | Path | None = None,
    filetypes: tuple[tuple[str, str], ...] = (),
) -> str | None:
    tool = native_file_dialog_available()
    if tool is None:
        return None

    initialdir_text = dialog_initial_dir(initialdir)

    if tool == "kdialog":
        args = ["kdialog", "--title", title, "--getopenfilename", initialdir_text]
        if filetypes:
            args.append(kdialog_filter_string(filetypes))
        return run_dialog_command(args)

    if tool == "zenity":
        args = ["zenity", "--file-selection", "--title", title, "--filename", initialdir_text + "/"]
        for label, pattern in filetypes:
            if pattern != "*":
                args.extend(["--file-filter", f"{label} | {pattern}"])
        return run_dialog_command(args)

    return ""


def native_open_files(
    title: str,
    initialdir: str | Path | None = None,
    filetypes: tuple[tuple[str, str], ...] = (),
) -> tuple[str, ...] | None:
    tool = native_file_dialog_available()
    if tool is None:
        return None

    initialdir_text = dialog_initial_dir(initialdir)

    if tool == "kdialog":
        args = [
            "kdialog",
            "--title",
            title,
            "--getopenfilename",
            initialdir_text,
        ]
        if filetypes:
            args.append(kdialog_filter_string(filetypes))
        args.extend(["--multiple", "--separate-output"])
        result = run_dialog_command(args)

    elif tool == "zenity":
        args = [
            "zenity",
            "--file-selection",
            "--multiple",
            "--separator=\n",
            "--title",
            title,
            "--filename",
            initialdir_text + "/",
        ]
        for label, pattern in filetypes:
            if pattern != "*":
                args.extend(["--file-filter", f"{label} | {pattern}"])
        result = run_dialog_command(args)

    else:
        return None

    if result is None:
        return None
    if not result:
        return ()
    return tuple(path for path in result.splitlines() if path)


def native_select_dir(title: str, initialdir: str | Path | None = None) -> str | None:
    tool = native_file_dialog_available()
    if tool is None:
        return None

    initialdir_text = dialog_initial_dir(initialdir)

    if tool == "kdialog":
        return run_dialog_command([
            "kdialog",
            "--title",
            title,
            "--getexistingdirectory",
            initialdir_text,
        ])

    if tool == "zenity":
        return run_dialog_command([
            "zenity",
            "--file-selection",
            "--directory",
            "--title",
            title,
            "--filename",
            initialdir_text + "/",
        ])

    return ""


def native_save_file(
    title: str,
    initialdir: str | Path | None = None,
    defaultextension: str = "",
    filetypes: tuple[tuple[str, str], ...] = (),
) -> str | None:
    tool = native_file_dialog_available()
    if tool is None:
        return None

    initialdir_text = dialog_initial_dir(initialdir)

    if tool == "kdialog":
        args = ["kdialog", "--title", title, "--getsavefilename", initialdir_text]
        if filetypes:
            args.append(kdialog_filter_string(filetypes))
        path = run_dialog_command(args)

    elif tool == "zenity":
        args = [
            "zenity",
            "--file-selection",
            "--save",
            "--confirm-overwrite",
            "--title",
            title,
            "--filename",
            initialdir_text + "/",
        ]
        for label, pattern in filetypes:
            if pattern != "*":
                args.extend(["--file-filter", f"{label} | {pattern}"])
        path = run_dialog_command(args)

    else:
        return None

    if path and defaultextension and not Path(path).suffix:
        path += defaultextension

    return path

SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sup", ".sub"}
VIDEO_EXTENSIONS = {
    ".h264",
    ".h265",
    ".hevc",
    ".avc",
    ".m1v",
    ".m2v",
    ".ivf",
}
VIDEO_CONTAINER_EXTENSIONS = {
    ".mkv",
    ".mk3d",
    ".mka",
    ".mks",
    ".webm",
    ".mp4",
    ".m4v",
    ".mov",
    ".qt",
    ".avi",
    ".wmv",
    ".asf",
    ".ts",
    ".m2ts",
    ".mts",
    ".m2t",
    ".mpg",
    ".mpeg",
    ".mpe",
    ".vob",
    ".flv",
    ".f4v",
    ".ogv",
    ".ogg",
    ".rm",
    ".rmvb",
    ".divx",
    ".xvid",
}
VIDEO_FILE_PATTERNS = " ".join(f"*{ext}" for ext in sorted(VIDEO_CONTAINER_EXTENSIONS))
MATROSKA_EXTRACT_EXTENSIONS = {".mkv", ".mk3d", ".mka", ".mks", ".webm"}
WINDOWS_CONTEXT_MENU_VERB = "G-TMCEExtract"
WINDOWS_CONTEXT_MENU_LABEL = "Open with G-TMCE Extract"
WINDOWS_CONTEXT_MENU_EXTENSIONS = tuple(sorted(VIDEO_CONTAINER_EXTENSIONS))
LINUX_CONTEXT_MENU_FILE_NAME = "g-tmce-extract.desktop"
AUDIO_EXTENSIONS = {
    ".aac",
    ".ac3",
    ".eac3",
    ".ec3",
    ".dts",
    ".dtshd",
    ".flac",
    ".m4a",
    ".mp2",
    ".mp3",
    ".ogg",
    ".opus",
    ".thd",
    ".truehd",
    ".wav",
}
AUDIO_FILE_PATTERNS = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
TRACK_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | SUBTITLE_EXTENSIONS
TRACK_FILE_PATTERNS = " ".join(f"*{ext}" for ext in sorted(TRACK_EXTENSIONS))
SUBTITLE_LANGUAGE_CHOICES = (
    "tr",
    "en",
    "de",
    "fr",
    "es",
    "it",
    "pt",
    "pt-br",
    "ru",
    "ar",
    "nl",
    "pl",
    "sv",
    "da",
    "no",
    "fi",
    "ja",
    "ko",
    "zh-cn",
    "zh-tw",
)
SUBTITLE_FILENAME_LANGUAGE_CODES = {
    "ar": "ara",
    "bg": "bul",
    "cs": "cze",
    "da": "dan",
    "de": "ger",
    "el": "gre",
    "en": "eng",
    "es": "spa",
    "fi": "fin",
    "fr": "fre",
    "he": "heb",
    "hi": "hin",
    "hr": "hrv",
    "hu": "hun",
    "it": "ita",
    "ja": "jpn",
    "ko": "kor",
    "nl": "dut",
    "no": "nor",
    "pl": "pol",
    "pt": "por",
    "pt-br": "por",
    "pt-pt": "por",
    "ro": "rum",
    "ru": "rus",
    "sk": "slo",
    "sv": "swe",
    "tr": "tur",
    "uk": "ukr",
    "zh": "chi",
    "zh-cn": "chi",
    "zh-tw": "chi",
}


def quote_windows_command_arg(value: Path | str) -> str:
    return '"' + str(value).replace('"', r'\"') + '"'


def windows_context_menu_launcher_path() -> Path | None:
    """Return the stable per-user EXE path used by Explorer context menus."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base_dir = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base_dir / APP_NAME / f"{APP_NAME}.exe"


def files_have_same_sha256(first: Path, second: Path) -> bool:
    """Compare executable contents without trusting a versioned filename."""
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        first_hash = hashlib.sha256()
        second_hash = hashlib.sha256()
        with first.open("rb") as first_file, second.open("rb") as second_file:
            while True:
                first_chunk = first_file.read(1024 * 1024)
                second_chunk = second_file.read(1024 * 1024)
                if first_chunk != second_chunk:
                    return False
                if not first_chunk:
                    break
                first_hash.update(first_chunk)
                second_hash.update(second_chunk)
        return first_hash.digest() == second_hash.digest()
    except OSError:
        return False


def sync_stable_launcher(source: Path, destination: Path) -> Path:
    """Atomically update a stable launcher without exposing a partial file."""
    source = source.resolve()
    try:
        if source == destination.resolve():
            return destination
    except OSError:
        pass

    if destination.is_file() and files_have_same_sha256(source, destination):
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
    try:
        shutil.copy2(source, temporary)
        # Explorer either sees the complete old launcher or the complete new
        # launcher; it can never see a partially copied EXE.
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination


def sync_windows_context_menu_launcher() -> Path | None:
    """Atomically update the stable launcher from a newly opened release EXE."""
    destination = windows_context_menu_launcher_path()
    if destination is None:
        return None
    return sync_stable_launcher(Path(sys.executable), destination)


def windows_context_menu_executable() -> Path:
    """Prefer the stable launcher, preserving a working fallback on I/O errors."""
    source = Path(sys.executable).resolve()
    destination = windows_context_menu_launcher_path()
    if destination is None:
        return source
    try:
        return sync_windows_context_menu_launcher() or source
    except OSError:
        # If the stable copy is currently running, Windows may temporarily lock
        # it. Keep the existing stable target rather than reverting registry
        # entries to an older versioned release filename.
        return destination if destination.is_file() else source


def app_command_for_file_argument(executable: Path | None = None) -> str:
    if getattr(sys, "frozen", False):
        target = executable or windows_context_menu_executable()
        return f'{quote_windows_command_arg(target)} "%1"'
    return (
        f"{quote_windows_command_arg(Path(sys.executable).resolve())} "
        f'{quote_windows_command_arg(Path(__file__).resolve())} "%1"'
    )


def windows_context_menu_icon_value(executable: Path | None = None) -> str:
    if getattr(sys, "frozen", False):
        target = executable or windows_context_menu_executable()
        return f"{quote_windows_command_arg(target)},0"
    if LOGO_PATH.exists():
        return quote_windows_command_arg(LOGO_PATH)
    return f"{quote_windows_command_arg(Path(sys.executable).resolve())},0"


def notify_windows_file_association_changed() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except (AttributeError, OSError):
        pass


def windows_context_menu_is_current(command: str, icon: str) -> bool:
    """Return whether every supported extension already points to the stable EXE."""
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False

    for extension in WINDOWS_CONTEXT_MENU_EXTENSIONS:
        menu_key_path = (
            fr"Software\Classes\SystemFileAssociations\{extension}"
            fr"\shell\{WINDOWS_CONTEXT_MENU_VERB}"
        )
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, menu_key_path) as menu_key:
                label, _ = winreg.QueryValueEx(menu_key, "MUIVerb")
                registered_icon, _ = winreg.QueryValueEx(menu_key, "Icon")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, menu_key_path + r"\command") as command_key:
                registered_command, _ = winreg.QueryValueEx(command_key, "")
        except OSError:
            return False
        if (
            label != WINDOWS_CONTEXT_MENU_LABEL
            or registered_icon != icon
            or registered_command != command
        ):
            return False
    return True


def install_windows_context_menu() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError as exc:
        return [str(exc)]

    executable = windows_context_menu_executable()
    command = app_command_for_file_argument(executable)
    icon = windows_context_menu_icon_value(executable)
    if windows_context_menu_is_current(command, icon):
        return []
    errors: list[str] = []
    for extension in WINDOWS_CONTEXT_MENU_EXTENSIONS:
        menu_key_path = (
            fr"Software\Classes\SystemFileAssociations\{extension}"
            fr"\shell\{WINDOWS_CONTEXT_MENU_VERB}"
        )
        command_key_path = menu_key_path + r"\command"
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                menu_key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as menu_key:
                winreg.SetValueEx(menu_key, "", 0, winreg.REG_SZ, WINDOWS_CONTEXT_MENU_LABEL)
                winreg.SetValueEx(menu_key, "MUIVerb", 0, winreg.REG_SZ, WINDOWS_CONTEXT_MENU_LABEL)
                winreg.SetValueEx(menu_key, "Icon", 0, winreg.REG_SZ, icon)
                winreg.SetValueEx(menu_key, "MultiSelectModel", 0, winreg.REG_SZ, "Single")
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                command_key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as command_key:
                winreg.SetValueEx(command_key, "", 0, winreg.REG_SZ, command)
        except OSError as exc:
            errors.append(f"{extension}: {exc}")

    if not errors:
        notify_windows_file_association_changed()
    return errors


def delete_windows_registry_tree(root: Any, key_path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    child_name = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_windows_registry_tree(root, key_path + "\\" + child_name)
        winreg.DeleteKey(root, key_path)
    except FileNotFoundError:
        return


def uninstall_windows_context_menu() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError as exc:
        return [str(exc)]

    errors: list[str] = []
    for extension in WINDOWS_CONTEXT_MENU_EXTENSIONS:
        menu_key_path = (
            fr"Software\Classes\SystemFileAssociations\{extension}"
            fr"\shell\{WINDOWS_CONTEXT_MENU_VERB}"
        )
        try:
            delete_windows_registry_tree(winreg.HKEY_CURRENT_USER, menu_key_path)
        except OSError as exc:
            errors.append(f"{extension}: {exc}")

    if not errors:
        notify_windows_file_association_changed()
    return errors


def current_appimage_path() -> Path | None:
    """Return the outer AppImage path when running from an AppImage."""
    raw_path = os.environ.get("APPIMAGE", "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    return path if path.is_file() else None


def linux_context_menu_launcher_path() -> Path | None:
    source = current_appimage_path()
    if os.name != "posix" or source is None:
        return None
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    base_dir = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base_dir / APP_ID / f"{APP_NAME}.AppImage"


def linux_kde_service_menu_paths() -> tuple[Path, ...]:
    launcher = linux_context_menu_launcher_path()
    if launcher is None:
        return ()
    data_home = launcher.parents[1]
    # A single definition avoids duplicate actions in installations which still
    # scan a legacy service-menu directory.  Plasma 6 uses KIO; Plasma 5 uses
    # kservices5.  Prefer the current KIO location when no cache builder is
    # discoverable (for example, before the first Plasma login).
    if shutil.which("kbuildsycoca6") is not None:
        directory = data_home / "kio" / "servicemenus"
    elif shutil.which("kbuildsycoca5") is not None:
        directory = data_home / "kservices5" / "ServiceMenus"
    else:
        directory = data_home / "kio" / "servicemenus"
    return (directory / LINUX_CONTEXT_MENU_FILE_NAME,)


def quote_desktop_exec_arg(value: Path | str) -> str:
    """Quote an Exec argument according to the desktop-entry syntax."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def linux_kde_service_menu_contents(launcher: Path) -> str:
    executable = quote_desktop_exec_arg(launcher)
    return f"""[Desktop Entry]
Type=Service
Name=G-TMCE Extract
Name[tr]=G-TMCE Extract
Comment=Extract tracks, subtitles, chapters and attachments from media files
Comment[tr]=Medya dosyalarından parça, altyazı, chapter ve ek çıkar
ServiceTypes=KonqPopupMenu/Plugin
X-KDE-ServiceTypes=KonqPopupMenu/Plugin
X-KDE-Priority=TopLevel
MimeType=application/octet-stream;video/*;
Icon=g-tmce
Actions=OpenGTMCEExtract;

[Desktop Action OpenGTMCEExtract]
Name=Open with G-TMCE Extract
Name[tr]=G-TMCE Extract ile Aç
Icon=g-tmce
Exec={executable} --extract %f
"""


def refresh_linux_kde_service_menu_cache() -> None:
    for command in ("kbuildsycoca6", "kbuildsycoca5"):
        executable = shutil.which(command)
        if executable is None:
            continue
        try:
            subprocess.run(
                [executable, "--noincremental"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=20,
                env=system_gui_subprocess_env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue


def install_linux_appimage_context_menu() -> list[str]:
    source = current_appimage_path()
    destination = linux_context_menu_launcher_path()
    paths = linux_kde_service_menu_paths()
    if source is None or destination is None or not paths:
        return ["Linux right-click integration is available only from an AppImage."]
    try:
        sync_stable_launcher(source, destination)
        service_menu = linux_kde_service_menu_contents(destination)
        menu_changed = False
        for path in paths:
            try:
                current = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                current = ""
            if current != service_menu:
                atomic_write_private_text(path, service_menu)
                menu_changed = True
        if menu_changed:
            refresh_linux_kde_service_menu_cache()
    except OSError as exc:
        return [str(exc)]
    return []


def uninstall_linux_appimage_context_menu() -> list[str]:
    errors: list[str] = []
    menu_removed = False
    for path in linux_kde_service_menu_paths():
        try:
            menu_removed = menu_removed or path.exists()
            path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    launcher = linux_context_menu_launcher_path()
    if launcher is not None:
        try:
            launcher.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{launcher}: {exc}")
    if not errors and menu_removed:
        refresh_linux_kde_service_menu_cache()
    return errors


def context_menu_integration_supported() -> bool:
    return os.name == "nt" or current_appimage_path() is not None


def install_context_menu_integration() -> list[str]:
    if os.name == "nt":
        return install_windows_context_menu()
    if current_appimage_path() is not None:
        return install_linux_appimage_context_menu()
    return ["Right-click integration is available in the Windows EXE and Linux AppImage."]


def uninstall_context_menu_integration() -> list[str]:
    if os.name == "nt":
        return uninstall_windows_context_menu()
    if current_appimage_path() is not None:
        return uninstall_linux_appimage_context_menu()
    return []


def set_context_menu_enabled_preference(enabled: bool) -> None:
    """Persist the opt-in state shared by the checkbox and Windows CLI."""
    preferences = load_saved_preferences()
    preferences["context_menu_enabled"] = "true" if enabled else "false"
    save_saved_preferences(preferences)


def write_cli_line(message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream)


def handle_windows_context_menu_cli(argv: list[str]) -> bool:
    options = {value.lower() for value in argv[1:] if value.startswith("--")}
    if "--install-context-menu" in options:
        errors = install_windows_context_menu()
        if errors:
            write_cli_line("Windows context menu could not be installed:", error=True)
            for error in errors:
                write_cli_line(f"- {error}", error=True)
        else:
            set_context_menu_enabled_preference(True)
            write_cli_line("Windows context menu installed.")
        return True
    if "--uninstall-context-menu" in options:
        errors = uninstall_windows_context_menu()
        if errors:
            write_cli_line("Windows context menu could not be removed:", error=True)
            for error in errors:
                write_cli_line(f"- {error}", error=True)
        else:
            set_context_menu_enabled_preference(False)
            write_cli_line("Windows context menu removed.")
        return True
    return False


def is_supported_extract_source_path(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_CONTAINER_EXTENSIONS


STANDARD_ATTACHMENT_NAMES = (
    "cover.jpg",
    "small_cover.jpg",
    "cover_land.jpg",
    "small_cover_land.jpg",
    "logo.png",
)
ARTWORK_TARGET_NAME_ALIASES = {
    "cover.jpg": "cover.jpg",
    "cover.jpeg": "cover.jpg",
    "small_cover.jpg": "small_cover.jpg",
    "small_cover.jpeg": "small_cover.jpg",
    "cover_land.jpg": "cover_land.jpg",
    "cover_land.jpeg": "cover_land.jpg",
    "small_cover_land.jpg": "small_cover_land.jpg",
    "small_cover_land.jpeg": "small_cover_land.jpg",
    "logo.png": "logo.png",
}
MUX_METADATA_FILE_PATTERNS = (
    "chapters.txt tags.xml "
    "cover.jpg cover.jpeg small_cover.jpg small_cover.jpeg "
    "cover_land.jpg cover_land.jpeg small_cover_land.jpg small_cover_land.jpeg logo.png"
)
MUX_ADD_FILE_PATTERNS = f"{TRACK_FILE_PATTERNS} {MUX_METADATA_FILE_PATTERNS}"
NORMAL_COVER_SMALLEST_SIDE = 600
SMALL_COVER_SMALLEST_SIDE = 120
TMDB_LOGO_CANVAS_SIZE = (800, 320)
TMDB_LOGO_CONTENT_SIZE = (760, 280)
TMDB_LOGO_MAX_BYTES = 512 * 1024
FONT_ATTACHMENT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2"}
MUX_UNKNOWN_LANGUAGE = "und"
DEFAULT_OUTPUT_NAME = "output.mkv"
INTRO_DETECTION_WINDOW_SECONDS = 4 * 60
INTRO_DETECTION_MIN_SECONDS = 35.0
INTRO_DETECTION_MAX_SECONDS = 4 * 60
INTRO_DETECTION_CLUSTER_SECONDS = 4.0
INTRO_DETECTION_MIN_CONFIDENCE = 88.0
INTRO_DETECTION_TOP_CANDIDATES = 12
RELEASE_STOP_TOKENS = {
    "2160p",
    "1080p",
    "720p",
    "576p",
    "480p",
    "web",
    "webdl",
    "web-dl",
    "webrip",
    "bluray",
    "bdrip",
    "brrip",
    "hdtv",
    "hdrip",
    "remux",
    "proper",
    "repack",
    "hdr",
    "dv",
    "ddp",
    "ddp5",
    "dts",
    "atmos",
    "x264",
    "x265",
    "h264",
    "h265",
    "hevc",
    "avc",
}
SUBTITLE_DESCRIPTOR_TOKENS = {
    "cc",
    "caption",
    "captions",
    "closed",
    "force",
    "forced",
    "forc",
    "hearing",
    "impaired",
    "sdh",
}
LANG_ALIASES = {
    "eng": "en",
    "en": "en",
    "english": "en",
    "tur": "tr",
    "tr": "tr",
    "turkish": "tr",
    "deu": "de",
    "ger": "de",
    "de": "de",
    "german": "de",
    "fre": "fr",
    "fra": "fr",
    "fr": "fr",
    "french": "fr",
    "spa": "es",
    "es": "es",
    "spanish": "es",
    "ita": "it",
    "it": "it",
    "italian": "it",
    "jpn": "ja",
    "ja": "ja",
    "japanese": "ja",
    "kor": "ko",
    "ko": "ko",
    "korean": "ko",
    "por": "pt",
    "pt": "pt",
    "portuguese": "pt",
    "rus": "ru",
    "ru": "ru",
    "russian": "ru",
    "zho": "zh",
    "chi": "zh",
    "zh": "zh",
    "chinese": "zh",
    "ara": "ar",
    "ar": "ar",
    "arabic": "ar",
    "hin": "hi",
    "hi": "hi",
    "hindi": "hi",
    "nld": "nl",
    "dut": "nl",
    "nl": "nl",
    "dutch": "nl",
    "pol": "pl",
    "pl": "pl",
    "polish": "pl",
    "swe": "sv",
    "sv": "sv",
    "swedish": "sv",
    "nor": "no",
    "no": "no",
    "norwegian": "no",
    "dan": "da",
    "da": "da",
    "danish": "da",
    "fin": "fi",
    "fi": "fi",
    "finnish": "fi",
    "ces": "cs",
    "cze": "cs",
    "cs": "cs",
    "czech": "cs",
    "slk": "sk",
    "slo": "sk",
    "sk": "sk",
    "slovak": "sk",
    "hun": "hu",
    "hu": "hu",
    "hungarian": "hu",
    "ron": "ro",
    "rum": "ro",
    "ro": "ro",
    "romanian": "ro",
    "bul": "bg",
    "bg": "bg",
    "bulgarian": "bg",
    "hrv": "hr",
    "hr": "hr",
    "croatian": "hr",
    "srp": "sr",
    "sr": "sr",
    "serbian": "sr",
    "ukr": "uk",
    "uk": "uk",
    "ukrainian": "uk",
    "ell": "el",
    "gre": "el",
    "el": "el",
    "greek": "el",
    "heb": "he",
    "he": "he",
    "hebrew": "he",
    "vie": "vi",
    "vi": "vi",
    "vietnamese": "vi",
    "tha": "th",
    "th": "th",
    "thai": "th",
    "ind": "id",
    "id": "id",
    "indonesian": "id",
    "msa": "ms",
    "may": "ms",
    "ms": "ms",
    "malay": "ms",
    "fas": "fa",
    "per": "fa",
    "fa": "fa",
    "persian": "fa",
    "farsi": "fa",
    "cat": "ca",
    "ca": "ca",
    "catalan": "ca",
    "lat": "la",
    "la": "la",
    "latin": "la",
    "lit": "lt",
    "lt": "lt",
    "lithuanian": "lt",
    "lav": "lv",
    "lv": "lv",
    "latvian": "lv",
    "est": "et",
    "et": "et",
    "estonian": "et",
    "slv": "sl",
    "sl": "sl",
    "slovenian": "sl",
    "bos": "bs",
    "bs": "bs",
    "bosnian": "bs",
    "mkd": "mk",
    "mk": "mk",
    "macedonian": "mk",
    "alb": "sq",
    "sqi": "sq",
    "sq": "sq",
    "albanian": "sq",
    "bel": "be",
    "be": "be",
    "belarusian": "be",
    "aze": "az",
    "az": "az",
    "azerbaijani": "az",
    "kaz": "kk",
    "kk": "kk",
    "kazakh": "kk",
    "uzb": "uz",
    "uz": "uz",
    "uzbek": "uz",
    "geo": "ka",
    "kat": "ka",
    "ka": "ka",
    "georgian": "ka",
    "arm": "hy",
    "hye": "hy",
    "hy": "hy",
    "armenian": "hy",
    "isl": "is",
    "is": "is",
    "icelandic": "is",
    "gle": "ga",
    "ga": "ga",
    "irish": "ga",
    "wel": "cy",
    "cym": "cy",
    "cy": "cy",
    "welsh": "cy",
    "mlt": "mt",
    "mt": "mt",
    "maltese": "mt",
    "afr": "af",
    "af": "af",
    "afrikaans": "af",
    "swa": "sw",
    "sw": "sw",
    "swahili": "sw",
    "amh": "am",
    "am": "am",
    "amharic": "am",
    "hau": "ha",
    "ha": "ha",
    "hausa": "ha",
    "yor": "yo",
    "yo": "yo",
    "yoruba": "yo",
    "ibo": "ig",
    "ig": "ig",
    "igbo": "ig",
    "zul": "zu",
    "zu": "zu",
    "zulu": "zu",
    "xho": "xh",
    "xh": "xh",
    "xhosa": "xh",
    "som": "so",
    "so": "so",
    "somali": "so",
    "ben": "bn",
    "bn": "bn",
    "bengali": "bn",
    "tam": "ta",
    "ta": "ta",
    "tamil": "ta",
    "tel": "te",
    "te": "te",
    "telugu": "te",
    "mar": "mr",
    "mr": "mr",
    "marathi": "mr",
    "guj": "gu",
    "gu": "gu",
    "gujarati": "gu",
    "pan": "pa",
    "pa": "pa",
    "punjabi": "pa",
    "mal": "ml",
    "ml": "ml",
    "malayalam": "ml",
    "kan": "kn",
    "kn": "kn",
    "kannada": "kn",
    "sin": "si",
    "si": "si",
    "sinhala": "si",
    "nep": "ne",
    "ne": "ne",
    "nepali": "ne",
    "khm": "km",
    "km": "km",
    "khmer": "km",
    "mya": "my",
    "bur": "my",
    "my": "my",
    "burmese": "my",
    "lao": "lo",
    "lo": "lo",
    "lao": "lo",
    "mon": "mn",
    "mn": "mn",
    "mongolian": "mn",
    "tib": "bo",
    "bod": "bo",
    "bo": "bo",
    "tibetan": "bo",
    "urd": "ur",
    "ur": "ur",
    "urdu": "ur",
    "pus": "ps",
    "ps": "ps",
    "pashto": "ps",
    "kur": "ku",
    "ku": "ku",
    "kurdish": "ku",
    "hat": "ht",
    "ht": "ht",
    "haitian": "ht",
    "haitiancreole": "ht",
    "epo": "eo",
    "eo": "eo",
    "esperanto": "eo",
    "jav": "jv",
    "jv": "jv",
    "javanese": "jv",
    "sun": "su",
    "su": "su",
    "sundanese": "su",
    "ceb": "ceb",
    "cebuano": "ceb",
    "tgl": "tl",
    "fil": "tl",
    "tl": "tl",
    "filipino": "tl",
    "tagalog": "tl",
    "mri": "mi",
    "mi": "mi",
    "maori": "mi",
    "haw": "haw",
    "hawaiian": "haw",
    "smo": "sm",
    "sm": "sm",
    "samoan": "sm",
    "fij": "fj",
    "fj": "fj",
    "fijian": "fj",
    "baq": "eu",
    "eu": "eu",
    "basque": "eu",
    "glg": "gl",
    "gl": "gl",
    "galician": "gl",
    "nob": "no",
    "nb": "no",
    "bokmal": "no",
    "norwegianbokmal": "no",
}

AUDIO_SPEED_FACTORS = {
    "auto": 1.0,
    "23976_24000": 24000 / 23976,
    "24000_23976": 23976 / 24000,
    "24000_25000": 25000 / 24000,
    "23976_25000": 25000 / 23976,
    "25000_23976": 23976 / 25000,
    "25000_24000": 24000 / 25000,
    "30000_23976": 23976 / 30000,
    "30000_24000": 24000 / 30000,
    "30000_25000": 25000 / 30000,
}

class UserVisibleError(RuntimeError):
    """An expected problem that should be shown without a traceback."""


class OpenSubtitlesRequestError(UserVisibleError):
    def __init__(self, code: int | str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(ui_text("error_subtitle_request_failed", code=code, message=message))


class OperationCancelled(UserVisibleError):
    """Raised when the user cancels the current background operation."""


@dataclass
class TrackItem:
    entry: dict[str, Any]
    path: Path
    template_index: int | None
    file_id: int = 0
    is_extra: bool = False
    append_paths: tuple[Path, ...] = ()

    @property
    def track(self) -> dict[str, Any]:
        return self.entry["tracks"]["0"]

    @property
    def object_id(self) -> int | None:
        value = self.track.get("objectID")
        return int(value) if isinstance(value, int) else None


@dataclass(frozen=True)
class AdditionalMuxTrack:
    path: Path
    language: str
    delay: str = ""
    append_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class AdditionalMuxAsset:
    path: Path
    kind: str
    target_name: str


@dataclass
class MuxTrackWindowRow:
    key: str
    path: Path
    kind: str
    language: str
    delay: str = ""
    delay_supported: bool = False
    append_paths: tuple[Path, ...] = ()
    append_overridden: bool = False
    asset_kind: str = ""
    target_name: str = ""
    manual: bool = False
    included: bool = True


@dataclass
class AppSettings:
    template_path: Path | None
    media_dir: Path
    output_path: Path
    output_name_extra: str
    output_name_year: bool
    api_key: str
    tmdb_id: str
    media_type: str
    image_language: str
    tag_language: str
    mkv_title: str
    video_fps: str
    audio_language_order: str
    subtitle_language_order: str
    include_extra_subtitles: bool
    download_before_mux: bool
    auto_chapters: bool
    auto_chapter_detect_intro: bool
    chapter_interval_minutes: str
    chapter_name: str
    chapter_start_number: str
    chapter_end_minutes: str


@dataclass(frozen=True)
class EpisodeRef:
    season: int
    episode: int


@dataclass(frozen=True)
class BatchEpisodeTask:
    source: Path
    extract_dir: Path
    episode_ref: EpisodeRef


@dataclass(frozen=True)
class SubtitleSearchTarget:
    media_dir: Path
    query: str
    output_stem: str
    media_type: str
    tmdb_id: str = ""
    imdb_id: str = ""
    year: str = ""
    episode_ref: EpisodeRef | None = None
    source_name: str = ""


@dataclass(frozen=True)
class SubtitleResult:
    key: str
    target_index: int
    subtitle_id: str
    file_id: int
    language: str
    release: str
    file_name: str
    fps: str
    downloads: int
    forced: bool
    hearing_impaired: bool
    from_trusted: bool
    machine_translated: bool
    ai_translated: bool
    url: str


@dataclass(frozen=True)
class SubtitleLookupMetadata:
    query: str = ""
    tmdb_id: str = ""
    imdb_id: str = ""
    year: str = ""


@dataclass
class ChapterOptions:
    enabled: bool
    detect_intro: bool
    interval_minutes: str
    name: str
    start_number: str
    end_minutes: str
    analysis_source: Path | None = None
    video_fps: str = ""


@dataclass(frozen=True)
class IntroDetectionCandidate:
    seconds: float
    score: float
    source: str


@dataclass
class ExtractItem:
    key: str
    kind: str
    item_id: int | None
    label: str
    output_name: str
    selected: bool = True
    language: str = ""
    language_override: str = ""
    extension: str = ""
    track_type: str = ""
    name_prefix_parts: tuple[str, ...] = ()
    name_suffix_parts: tuple[str, ...] = ()


@dataclass
class AudioAdjustTask:
    path: Path
    delta_seconds: float
    codec: str
    bitrate: str
    sample_rate: str
    channel_layout: str
    volume_multiplier: float = 1.0
    speed_factor: float = 1.0
    original_codec: str = ""
    original_bitrate: str = ""
    original_sample_rate: str = ""
    original_channel_layout: str = ""


SUPPORTED_AUDIO_ENCODERS = {"ac3", "eac3", "aac", "dts", "mp3", "wav", "ogg", "flac", "opus"}
FFMPEG_AUDIO_ENCODERS = {
    "ac3": "ac3",
    "eac3": "eac3",
    "aac": "aac",
    "dts": "dts",
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "ogg": "libvorbis",
    "flac": "flac",
    "opus": "libopus",
}
AUDIO_OUTPUT_SUFFIXES = {
    "ac3": ".ac3",
    "eac3": ".eac3",
    "aac": ".aac",
    "dts": ".dts",
    "mp3": ".mp3",
    "wav": ".wav",
    "ogg": ".ogg",
    "flac": ".flac",
    "opus": ".opus",
}

THIRD_PARTY_TOOL_GROUPS = {
    "mkvmerge": "mkvtoolnix",
    "mkvextract": "mkvtoolnix",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
}
THIRD_PARTY_GROUP_TOOLS = {
    "mkvtoolnix": ("mkvmerge", "mkvextract"),
    "ffmpeg": ("ffmpeg", "ffprobe"),
}
THIRD_PARTY_EXECUTABLE_NAMES = {
    "mkvmerge": "mkvmerge.exe" if os.name == "nt" else "mkvmerge",
    "mkvextract": "mkvextract.exe" if os.name == "nt" else "mkvextract",
    "ffmpeg": "ffmpeg.exe" if os.name == "nt" else "ffmpeg",
    "ffprobe": "ffprobe.exe" if os.name == "nt" else "ffprobe",
}
THIRD_PARTY_READY_GROUPS: set[str] = set()
THIRD_PARTY_LOCK = threading.Lock()


def platform_arch() -> str:
    return platform.machine().lower()


def platform_name() -> str:
    return platform.system().lower()


def version_key(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", value)]
    return tuple(parts + [0] * (4 - len(parts)))


def host_matches(hostname: str, allowed_hosts: set[str] | frozenset[str], allowed_suffixes: tuple[str, ...] = ()) -> bool:
    host = str(hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host in allowed_hosts:
        return True
    return any(host.endswith(suffix) and host != suffix.lstrip(".") for suffix in allowed_suffixes)


def validate_https_url(
    url: str,
    *,
    allowed_hosts: set[str] | frozenset[str],
    allowed_suffixes: tuple[str, ...] = (),
) -> str:
    value = str(url or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise ValueError("only HTTPS URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials in URLs are not allowed")
    if parsed.port not in (None, 443):
        raise ValueError("non-standard HTTPS ports are not allowed")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not host_matches(hostname, allowed_hosts, allowed_suffixes):
        raise ValueError(f"untrusted HTTPS host: {hostname or '<missing>'}")
    return value


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str] | frozenset[str], allowed_suffixes: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.allowed_suffixes = allowed_suffixes

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        validate_https_url(
            newurl,
            allowed_hosts=self.allowed_hosts,
            allowed_suffixes=self.allowed_suffixes,
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def trusted_ssl_context() -> ssl.SSLContext:
    """Return a portable TLS context backed by certifi's Mozilla CA bundle.

    PyInstaller-built AppImages can otherwise inherit the build machine's
    OpenSSL default CA path (for example Debian's /etc/ssl/certs layout),
    which may not exist on the user's distribution.  Using the bundled
    certifi store keeps certificate verification enabled while making HTTPS
    behavior consistent across source, Windows, and AppImage builds.
    """
    ca_bundle = Path(certifi.where()).resolve()
    if not ca_bundle.is_file():
        raise RuntimeError(f"trusted CA bundle is missing: {ca_bundle}")
    return ssl.create_default_context(cafile=os.fspath(ca_bundle))


def safe_urlopen(
    request: urllib.request.Request | str,
    *,
    timeout: int,
    allowed_hosts: set[str] | frozenset[str],
    allowed_suffixes: tuple[str, ...] = (),
) -> Any:
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    validate_https_url(url, allowed_hosts=allowed_hosts, allowed_suffixes=allowed_suffixes)
    opener = urllib.request.build_opener(
        SafeRedirectHandler(allowed_hosts, allowed_suffixes),
        urllib.request.HTTPSHandler(context=trusted_ssl_context()),
    )
    return opener.open(request, timeout=timeout)


def read_response_limited(response: Any, max_bytes: int) -> bytes:
    length_header = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if length_header:
        try:
            if int(length_header) > max_bytes:
                raise ValueError("response exceeds maximum allowed size")
        except ValueError as exc:
            if str(exc) == "response exceeds maximum allowed size":
                raise
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("response exceeds maximum allowed size")
        chunks.append(chunk)
    return b"".join(chunks)


def third_party_request(url: str, accept: str = "*/*") -> urllib.request.Request:
    validate_https_url(url, allowed_hosts=THIRD_PARTY_ALLOWED_HOSTS)
    return urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": THIRD_PARTY_USER_AGENT,
        },
    )


def open_third_party_request(request: urllib.request.Request, timeout: int) -> Any:
    return safe_urlopen(
        request,
        timeout=timeout,
        allowed_hosts=THIRD_PARTY_ALLOWED_HOSTS,
    )


def read_third_party_text(url: str) -> str:
    with open_third_party_request(third_party_request(url), 45) as response:
        return read_response_limited(response, MAX_JSON_RESPONSE_BYTES).decode("utf-8", errors="replace")


def read_third_party_json(url: str) -> dict[str, Any]:
    with open_third_party_request(
        third_party_request(url, "application/vnd.github+json"),
        45,
    ) as response:
        payload = read_response_limited(response, MAX_JSON_RESPONSE_BYTES).decode("utf-8", errors="replace")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("JSON response is not an object")
    return value


def app_version_numbers(value: str) -> tuple[int, ...] | None:
    match = re.search(r"\d+(?:[._-]\d+)*", str(value or ""))
    if not match:
        return None
    parts = tuple(int(part) for part in re.findall(r"\d+", match.group(0)))
    return parts or None


def padded_version_numbers(parts: tuple[int, ...]) -> tuple[int, ...]:
    size = max(4, len(parts))
    return parts + (0,) * (size - len(parts))


def app_version_is_newer(latest_version: str, current_version: str) -> bool | None:
    latest = app_version_numbers(latest_version)
    current = app_version_numbers(current_version)
    if latest is None or current is None:
        return None
    return padded_version_numbers(latest) > padded_version_numbers(current)


def parse_github_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def app_build_datetime() -> datetime | None:
    path = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def latest_app_release() -> dict[str, str]:
    release = read_third_party_json(APP_RELEASE_API_URL)
    version = str(release.get("tag_name") or "").strip()
    if not version:
        raise ValueError("release tag is missing")
    return {
        "version": version,
        "url": str(release.get("html_url") or APP_LATEST_RELEASE_URL),
        "published_at": str(release.get("published_at") or release.get("created_at") or ""),
    }


def app_release_is_newer(release: dict[str, str]) -> bool:
    version_result = app_version_is_newer(str(release.get("version") or ""), APP_VERSION)
    if version_result is not None:
        return version_result

    published_at = parse_github_datetime(str(release.get("published_at") or ""))
    built_at = app_build_datetime()
    if published_at is None or built_at is None:
        return False
    # Unversioned packaged builds are usually created before the GitHub release is published.
    return published_at > built_at + timedelta(hours=24)


def error_reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if reason:
        return str(reason)
    return str(exc) or exc.__class__.__name__


def third_party_platform_label() -> tuple[str, str]:
    return platform_name(), platform_arch()


def unsupported_third_party(name: str) -> UserVisibleError:
    system, arch = third_party_platform_label()
    return UserVisibleError(
        ui_text("error_third_party_platform", name=name, platform=system, arch=arch)
    )


def latest_mkvtoolnix_release() -> dict[str, str]:
    system = platform_name()
    arch = platform_arch()

    if system == "linux":
        if arch not in {"x86_64", "amd64"}:
            raise unsupported_third_party("MKVToolNix")

        try:
            html = read_third_party_text(MKVTOOLNIX_APPIMAGE_INDEX_URL)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise UserVisibleError(
                ui_text("error_third_party_latest_failed", name="MKVToolNix", reason=error_reason(exc))
            ) from exc

        releases: dict[str, str] = {}
        pattern = r"(MKVToolNix_GUI-([0-9]+(?:\.[0-9]+){1,2})-x86_64\.AppImage)(?!\.zsync)"
        for filename, version in re.findall(pattern, html):
            releases[version] = filename
        if not releases:
            raise UserVisibleError(
                ui_text(
                    "error_third_party_latest_failed",
                    name="MKVToolNix",
                    reason="no AppImage asset found",
                )
            )

        version = max(releases, key=version_key)
        filename = releases[version]
        return {
            "version": version,
            "asset_name": filename,
            "download_url": urllib.parse.urljoin(MKVTOOLNIX_APPIMAGE_INDEX_URL, filename),
        }

    if system == "windows":
        if arch not in {"x86_64", "amd64", "amd6464"}:
            raise unsupported_third_party("MKVToolNix")

        try:
            html = read_third_party_text(MKVTOOLNIX_DOWNLOADS_URL)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise UserVisibleError(
                ui_text("error_third_party_latest_failed", name="MKVToolNix", reason=error_reason(exc))
            ) from exc

        version_match = re.search(r"current version\s+v?([0-9]+(?:\.[0-9]+){1,2})", html, re.IGNORECASE)
        if not version_match:
            version_match = re.search(r"/windows/releases/([0-9]+(?:\.[0-9]+){1,2})/", html, re.IGNORECASE)
        if not version_match:
            raise UserVisibleError(
                ui_text(
                    "error_third_party_latest_failed",
                    name="MKVToolNix",
                    reason="no Windows release version found",
                )
            )

        version = version_match.group(1)
        filename = f"mkvtoolnix-64-bit-{version}.zip"
        return {
            "version": version,
            "asset_name": filename,
            "download_url": f"https://mkvtoolnix.download/windows/releases/{version}/{filename}",
        }

    raise unsupported_third_party("MKVToolNix")

def ffmpeg_asset_name() -> str:
    system = platform_name()
    arch = platform_arch()

    if system == "windows":
        if arch in {"x86_64", "amd64", "amd6464"}:
            return "ffmpeg-master-latest-win64-gpl.zip"
        raise unsupported_third_party("FFmpeg")

    if system == "linux":
        if arch in {"x86_64", "amd64"}:
            return "ffmpeg-master-latest-linux64-gpl.tar.xz"
        if arch in {"aarch64", "arm64"}:
            return "ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
        raise unsupported_third_party("FFmpeg")

    raise unsupported_third_party("FFmpeg")

def latest_ffmpeg_release() -> dict[str, str]:
    asset_name = ffmpeg_asset_name()
    try:
        release = read_third_party_json(FFMPEG_RELEASE_API_URL)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise UserVisibleError(
            ui_text("error_third_party_latest_failed", name="FFmpeg", reason=error_reason(exc))
        ) from exc

    assets = release.get("assets") or []
    if not isinstance(assets, list):
        assets = []
    asset = next(
        (
            item
            for item in assets
            if isinstance(item, dict) and item.get("name") == asset_name
        ),
        None,
    )
    if asset is None:
        raise UserVisibleError(
            ui_text(
                "error_third_party_latest_failed",
                name="FFmpeg",
                reason=f"{asset_name} asset not found",
            )
        )

    download_url = str(asset.get("browser_download_url") or "")
    if not download_url:
        raise UserVisibleError(
            ui_text(
                "error_third_party_latest_failed",
                name="FFmpeg",
                reason=f"{asset_name} download URL missing",
            )
        )
    version = str(
        asset.get("updated_at")
        or release.get("published_at")
        or release.get("tag_name")
        or asset_name
    )
    tag = str(release.get("tag_name") or "latest")
    return {
        "version": f"{tag}@{version}",
        "asset_name": asset_name,
        "download_url": download_url,
        "digest": str(asset.get("digest") or ""),
    }


def load_third_party_state() -> dict[str, Any]:
    try:
        payload = json.loads(THIRD_PARTY_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_third_party_state(state: dict[str, Any]) -> None:
    atomic_write_private_text(
        THIRD_PARTY_STATE_PATH,
        json.dumps(state, indent=2, sort_keys=True) + "\n",
    )


def assert_third_party_child(path: Path) -> None:
    root = THIRD_PARTY_DIR.resolve()
    target = path.resolve()
    if target == root or root not in target.parents:
        raise RuntimeError(f"Refusing to modify path outside 3rdParty: {path}")


def remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    assert_third_party_child(path)
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def make_fresh_directory(path: Path) -> None:
    remove_path(path)
    path.mkdir(parents=True, exist_ok=True)


def mark_executable(path: Path) -> None:
    if os.name == "nt":
        return
    path.chmod(path.stat().st_mode | 0o755)


def verify_sha256(path: Path, digest: str) -> None:
    if not digest.startswith("sha256:"):
        return
    expected = digest.removeprefix("sha256:").strip().lower()
    if not expected:
        return
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    actual = hasher.hexdigest()
    if actual != expected:
        raise ValueError(f"sha256 mismatch for {path.name}")


def download_third_party_file(name: str, url: str, filename: str, digest: str = "") -> Path:
    THIRD_PARTY_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    destination = THIRD_PARTY_DOWNLOADS_DIR / filename
    temporary = destination.with_name(f"{destination.name}.download")
    remove_path(temporary)
    try:
        with open_third_party_request(third_party_request(url), 300) as response:
            length_header = response.headers.get("Content-Length")
            if length_header and int(length_header) > MAX_THIRD_PARTY_DOWNLOAD_BYTES:
                raise ValueError("download exceeds maximum allowed size")
            total = 0
            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_THIRD_PARTY_DOWNLOAD_BYTES:
                        raise ValueError("download exceeds maximum allowed size")
                    handle.write(chunk)
        verify_sha256(temporary, digest)
        temporary.replace(destination)
        return destination
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        remove_path(temporary)
        raise UserVisibleError(
            ui_text("error_third_party_download_failed", name=name, reason=error_reason(exc))
        ) from exc


def install_third_party_tool(tool_name: str, source: Path) -> None:
    THIRD_PARTY_BIN_DIR.mkdir(parents=True, exist_ok=True)
    destination = THIRD_PARTY_BIN_DIR / THIRD_PARTY_EXECUTABLE_NAMES.get(tool_name, tool_name)
    temporary = destination.with_name(f".{tool_name}.new")
    remove_path(temporary)
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copy2(source, temporary)
    mark_executable(temporary)
    remove_path(destination)
    temporary.rename(destination)


def mkvtoolnix_appdir_ready() -> bool:
    return (
        (THIRD_PARTY_MKVTOOLNIX_APPDIR / "AppRun").is_file()
        and os.access(THIRD_PARTY_MKVTOOLNIX_APPDIR / "AppRun", os.X_OK)
        and all(
            (THIRD_PARTY_MKVTOOLNIX_APPDIR / "usr" / "bin" / tool_name).is_file()
            for tool_name in THIRD_PARTY_GROUP_TOOLS["mkvtoolnix"]
        )
    )


def install_mkvtoolnix_wrapper(tool_name: str) -> None:
    THIRD_PARTY_BIN_DIR.mkdir(parents=True, exist_ok=True)
    destination = THIRD_PARTY_BIN_DIR / tool_name
    temporary = destination.with_name(f".{tool_name}.new")
    content = (
        "#!/bin/sh\n"
        "SCRIPT_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd) || exit 127\n"
        "APPDIR=\"$SCRIPT_DIR/mkvtoolnix\"\n"
        "export APPDIR\n"
        "ARGV0=\"$0\"\n"
        "export ARGV0\n"
        "exec \"$APPDIR/AppRun\" \"$@\"\n"
    )
    remove_path(temporary)
    temporary.write_text(content, encoding="utf-8")
    mark_executable(temporary)
    remove_path(destination)
    temporary.rename(destination)


def install_mkvtoolnix_wrappers() -> None:
    for tool_name in THIRD_PARTY_GROUP_TOOLS["mkvtoolnix"]:
        install_mkvtoolnix_wrapper(tool_name)


def extract_mkvtoolnix_appimage(source: Path) -> None:
    source = source.resolve()
    if not os.access(source, os.X_OK):
        mark_executable(source)

    make_fresh_directory(THIRD_PARTY_MKVTOOLNIX_STAGING_DIR)
    try:
        process = subprocess.run(
            [str(source), "--appimage-extract"],
            cwd=str(THIRD_PARTY_MKVTOOLNIX_STAGING_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **subprocess_common_kwargs(),
            check=False,
        )

        stdout = process.stdout.strip()
        stderr = process.stderr.strip()

        if process.returncode != 0:
            message = stderr or stdout or str(process.returncode)
            raise RuntimeError(f"AppImage extract failed: {message}")

        extracted = THIRD_PARTY_MKVTOOLNIX_STAGING_DIR / "squashfs-root"

        if not extracted.exists():
            matches = list(THIRD_PARTY_MKVTOOLNIX_STAGING_DIR.rglob("squashfs-root"))
            if matches:
                extracted = matches[0]

        if not extracted.exists():
            raise RuntimeError(
                "AppImage extract completed but squashfs-root was not created. "
                f"stdout={stdout!r} stderr={stderr!r}"
            )

        if not (extracted / "AppRun").is_file():
            raise FileNotFoundError(extracted / "AppRun")

        for tool_name in THIRD_PARTY_GROUP_TOOLS["mkvtoolnix"]:
            tool = extracted / "usr" / "bin" / tool_name
            if not tool.is_file():
                raise FileNotFoundError(tool)

        THIRD_PARTY_BIN_DIR.mkdir(parents=True, exist_ok=True)

        remove_path(THIRD_PARTY_MKVTOOLNIX_APPDIR)
        extracted.rename(THIRD_PARTY_MKVTOOLNIX_APPDIR)

        mark_executable(THIRD_PARTY_MKVTOOLNIX_APPDIR / "AppRun")

        for tool_name in THIRD_PARTY_GROUP_TOOLS["mkvtoolnix"]:
            mark_executable(THIRD_PARTY_MKVTOOLNIX_APPDIR / "usr" / "bin" / tool_name)

        install_mkvtoolnix_wrappers()

    except Exception:
        remove_path(THIRD_PARTY_MKVTOOLNIX_STAGING_DIR)
        raise

    remove_path(THIRD_PARTY_MKVTOOLNIX_STAGING_DIR)

def migrate_legacy_third_party_links() -> None:
    if THIRD_PARTY_MKVTOOLNIX_APPDIR.is_file():
        extract_mkvtoolnix_appimage(THIRD_PARTY_MKVTOOLNIX_APPDIR)
        return

    if mkvtoolnix_appdir_ready():
        install_mkvtoolnix_wrappers()


def cleanup_third_party_workdirs() -> None:
    for path in (
        THIRD_PARTY_DOWNLOADS_DIR,
        THIRD_PARTY_MKVTOOLNIX_STAGING_DIR,
        THIRD_PARTY_DIR / ".ffmpeg-new",
        THIRD_PARTY_DIR / ".mkvtoolnix-win-new",
        THIRD_PARTY_DIR / "mkvtoolnix",
        THIRD_PARTY_DIR / "ffmpeg",
    ):
        remove_path(path)


def third_party_group_installed(group: str) -> bool:
    if platform_name() == "linux" and group == "mkvtoolnix" and not mkvtoolnix_appdir_ready():
        return False

    tool_paths = [
        THIRD_PARTY_BIN_DIR / THIRD_PARTY_EXECUTABLE_NAMES.get(tool, tool)
        for tool in THIRD_PARTY_GROUP_TOOLS[group]
    ]
    if not all(path.exists() for path in tool_paths):
        return False

    # Windows MKVToolNix is not portable if only the exe files are present.
    # The CLI tools can exist but silently fail before producing JSON when the
    # runtime DLLs beside them are missing. Treat that as not installed so the
    # whole tool folder is downloaded/copied again.
    if os.name == "nt" and group == "mkvtoolnix":
        if not any(THIRD_PARTY_BIN_DIR.glob("*.dll")):
            return False
        probe = THIRD_PARTY_BIN_DIR / THIRD_PARTY_EXECUTABLE_NAMES["mkvmerge"]
        try:
            process = subprocess.run(
                [str(probe), "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **subprocess_common_kwargs(),
                check=False,
                env=third_party_subprocess_env(),
            )
        except OSError:
            return False
        if process.returncode != 0 or not ((process.stdout or process.stderr or "").strip()):
            return False

    return True


def install_mkvtoolnix(latest: dict[str, str]) -> dict[str, str]:
    if platform_name() == "windows":
        return install_mkvtoolnix_windows_zip(latest)

    filename = latest["asset_name"]
    downloaded = download_third_party_file(
        "MKVToolNix",
        latest["download_url"],
        filename,
    )
    try:
        mark_executable(downloaded)
        extract_mkvtoolnix_appimage(downloaded)
        cleanup_third_party_workdirs()
        return {
            "version": latest["version"],
            "asset_name": filename,
            "download_url": latest["download_url"],
        }
    except (OSError, RuntimeError) as exc:
        remove_path(downloaded)
        cleanup_third_party_workdirs()
        raise UserVisibleError(
            ui_text("error_third_party_install_failed", name="MKVToolNix", reason=error_reason(exc))
        ) from exc


def safe_extract_tar(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    members = archive.getmembers()
    total_size = 0
    for member in members:
        if member.name.startswith(("/", "\\")):
            raise ValueError(f"unsafe archive member: {member.name}")
        member_path = (destination / member.name).resolve()
        if member_path != root and root not in member_path.parents:
            raise ValueError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"unsupported archive member type: {member.name}")
        total_size += max(0, int(member.size or 0))
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("archive exceeds maximum allowed uncompressed size")
    archive.extractall(destination, members=members)


def safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    total_size = 0
    for member in archive.infolist():
        if member.filename.startswith(("/", "\\")):
            raise ValueError(f"unsafe archive member: {member.filename}")
        member_path = (destination / member.filename).resolve()
        if member_path != root and root not in member_path.parents:
            raise ValueError(f"unsafe archive member: {member.filename}")
        mode = (member.external_attr >> 16) & 0xFFFF
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            raise ValueError(f"symlink archive member is not allowed: {member.filename}")
        total_size += max(0, int(member.file_size or 0))
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("archive exceeds maximum allowed uncompressed size")
    archive.extractall(destination)


def install_mkvtoolnix_windows_zip(latest: dict[str, str]) -> dict[str, str]:
    filename = latest["asset_name"]
    downloaded = download_third_party_file(
        "MKVToolNix",
        latest["download_url"],
        filename,
    )
    staging = THIRD_PARTY_DIR / ".mkvtoolnix-win-new"
    extract_root = staging / "extract"
    try:
        make_fresh_directory(staging)
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(downloaded) as archive:
            safe_extract_zip(archive, extract_root)

        candidates = list(extract_root.rglob("mkvmerge.exe"))
        if not candidates:
            raise FileNotFoundError("mkvmerge.exe")
        bin_root = candidates[0].parent

        # Windows MKVToolNix executables need nearby DLL/runtime files.
        # Copy only required executables + DLLs instead of the whole folder.
        THIRD_PARTY_BIN_DIR.mkdir(parents=True, exist_ok=True)

        required_files = {
            "mkvmerge.exe",
            "mkvextract.exe",
        }

        required_patterns = (
            "*.dll",
        )

        selected_files: list[Path] = []

        for source_file in bin_root.iterdir():
            if not source_file.is_file():
                continue

            lower_name = source_file.name.lower()

            if lower_name in required_files:
                selected_files.append(source_file)
                continue

            if any(source_file.match(pattern) for pattern in required_patterns):
                selected_files.append(source_file)

        for source_file in selected_files:
            destination = THIRD_PARTY_BIN_DIR / source_file.name
            temporary = destination.with_name(f".{source_file.name}.new")

            remove_path(temporary)
            shutil.copy2(source_file, temporary)

            remove_path(destination)
            temporary.rename(destination)

        for tool in ("mkvmerge", "mkvextract"):
            candidate = THIRD_PARTY_BIN_DIR / THIRD_PARTY_EXECUTABLE_NAMES[tool]
            if not candidate.exists():
                raise FileNotFoundError(candidate)

        cleanup_third_party_workdirs()
        return {
            "version": latest["version"],
            "asset_name": filename,
            "download_url": latest["download_url"],
        }
    except (OSError, RuntimeError, zipfile.BadZipFile, ValueError) as exc:
        remove_path(staging)
        remove_path(downloaded)
        cleanup_third_party_workdirs()
        raise UserVisibleError(
            ui_text("error_third_party_install_failed", name="MKVToolNix", reason=error_reason(exc))
        ) from exc


def install_ffmpeg(latest: dict[str, str]) -> dict[str, str]:
    filename = latest["asset_name"]
    downloaded = download_third_party_file(
        "FFmpeg",
        latest["download_url"],
        filename,
        latest.get("digest", ""),
    )
    staging = THIRD_PARTY_DIR / ".ffmpeg-new"
    extract_root = staging / "extract"
    try:
        make_fresh_directory(staging)
        extract_root.mkdir(parents=True, exist_ok=True)

        if filename.lower().endswith(".zip"):
            with zipfile.ZipFile(downloaded) as archive:
                safe_extract_zip(archive, extract_root)
        else:
            with tarfile.open(downloaded, "r:*") as archive:
                safe_extract_tar(archive, extract_root)

        roots = [path for path in extract_root.iterdir() if path.is_dir()]
        extracted_root = roots[0] if len(roots) == 1 else extract_root

        for tool in ("ffmpeg", "ffprobe"):
            executable = THIRD_PARTY_EXECUTABLE_NAMES[tool]
            candidate = extracted_root / "bin" / executable
            if not candidate.exists():
                matches = list(extracted_root.rglob(executable))
                candidate = matches[0] if matches else candidate
            if not candidate.exists():
                raise FileNotFoundError(candidate)
            mark_executable(candidate)

        for tool in ("ffmpeg", "ffprobe"):
            executable = THIRD_PARTY_EXECUTABLE_NAMES[tool]
            candidate = extracted_root / "bin" / executable
            if not candidate.exists():
                candidate = list(extracted_root.rglob(executable))[0]
            install_third_party_tool(tool, candidate)

        cleanup_third_party_workdirs()
        return {
            "version": latest["version"],
            "asset_name": filename,
            "download_url": latest["download_url"],
        }
    except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile, ValueError) as exc:
        remove_path(staging)
        remove_path(downloaded)
        cleanup_third_party_workdirs()
        raise UserVisibleError(
            ui_text("error_third_party_install_failed", name="FFmpeg", reason=error_reason(exc))
        ) from exc

def latest_third_party_release(group: str) -> dict[str, str]:
    if group == "mkvtoolnix":
        return latest_mkvtoolnix_release()
    if group == "ffmpeg":
        return latest_ffmpeg_release()
    raise KeyError(group)


def install_third_party_group(group: str, latest: dict[str, str]) -> dict[str, str]:
    if group == "mkvtoolnix":
        return install_mkvtoolnix(latest)
    if group == "ffmpeg":
        return install_ffmpeg(latest)
    raise KeyError(group)


def ensure_third_party_group(group: str, force_check: bool = False) -> dict[str, Any]:
    if group == "mkvtoolnix":
        try:
            migrate_legacy_third_party_links()
        except (OSError, RuntimeError):
            pass

    state = load_third_party_state()
    installed = state.get(group)
    installed_version = installed.get("version") if isinstance(installed, dict) else ""

    if (
        not force_check
        and group in THIRD_PARTY_READY_GROUPS
        and third_party_group_installed(group)
    ):
        migrate_legacy_third_party_links()
        cleanup_third_party_workdirs()
        return {
            "group": group,
            "version": installed_version,
            "changed": False,
            "checked": False,
            "existing_used": False,
        }

    try:
        latest = latest_third_party_release(group)
    except UserVisibleError:
        if third_party_group_installed(group):
            THIRD_PARTY_READY_GROUPS.add(group)
            migrate_legacy_third_party_links()
            cleanup_third_party_workdirs()
            return {
                "group": group,
                "version": installed_version,
                "changed": False,
                "checked": False,
                "existing_used": True,
            }
        raise

    if installed_version != latest["version"] or not third_party_group_installed(group):
        try:
            state[group] = install_third_party_group(group, latest)
            save_third_party_state(state)
        except UserVisibleError:
            if third_party_group_installed(group):
                THIRD_PARTY_READY_GROUPS.add(group)
                migrate_legacy_third_party_links()
                cleanup_third_party_workdirs()
                return {
                    "group": group,
                    "version": installed_version,
                    "changed": False,
                    "checked": True,
                    "existing_used": True,
                }
            raise

        THIRD_PARTY_READY_GROUPS.add(group)
        cleanup_third_party_workdirs()
        return {
            "group": group,
            "version": latest["version"],
            "changed": True,
            "checked": True,
            "existing_used": False,
        }

    THIRD_PARTY_READY_GROUPS.add(group)
    migrate_legacy_third_party_links()
    cleanup_third_party_workdirs()
    return {
        "group": group,
        "version": latest["version"],
        "changed": False,
        "checked": True,
        "existing_used": False,
    }

def installed_third_party_tool_path(tool_name: str) -> str | None:
    tool_path = THIRD_PARTY_BIN_DIR / THIRD_PARTY_EXECUTABLE_NAMES.get(tool_name, tool_name)
    if tool_path.exists():
        return str(tool_path)
    return None


def third_party_tool_path(
    tool_name: str,
    required: bool = True,
    auto_install: bool = True,
) -> str | None:
    if not auto_install:
        path = installed_third_party_tool_path(tool_name)
        if path:
            return path
        if not required:
            return None
        raise UserVisibleError(ui_text("error_third_party_missing", name=tool_name))

    group = THIRD_PARTY_TOOL_GROUPS[tool_name]
    try:
        with THIRD_PARTY_LOCK:
            ensure_third_party_group(group)
    except UserVisibleError:
        if required:
            raise
        return None

    tool_path = installed_third_party_tool_path(tool_name)
    if tool_path:
        return tool_path
    if required:
        raise UserVisibleError(ui_text("error_third_party_missing", name=tool_name))
    return None


def third_party_subprocess_executable(args: list[str]) -> str | None:
    if not args:
        return None
    # On Windows, passing both args[0] and subprocess.run(executable=...) can
    # make CreateProcess build a command line that starts but returns no stdout
    # for some CLI tools. The absolute path is already in args[0], so let
    # subprocess use it directly. Linux keeps the old helper behavior for
    # AppImage/wrapper compatibility.
    if os.name == "nt":
        return None
    tool_name = Path(str(args[0])).name.lower()
    if tool_name.endswith(".exe"):
        tool_name = tool_name[:-4]
    if tool_name not in THIRD_PARTY_TOOL_GROUPS:
        return None
    return installed_third_party_tool_path(tool_name)


def third_party_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = str(THIRD_PARTY_BIN_DIR) + os.pathsep + env.get("PATH", "")
    for key in (
        "APPIMAGE_EXTRACT_AND_RUN",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "TMDB_API_KEY",
        "OPENSUBTITLES_API_KEY",
        "OPENSUBTITLES_USERNAME",
        "OPENSUBTITLES_PASSWORD",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        env.pop(key, None)
    return env


def subprocess_text_kwargs() -> dict[str, Any]:
    """Use UTF-8 tolerant text decoding for tool output on every platform."""
    return {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }


def subprocess_window_kwargs() -> dict[str, Any]:
    """Prevent console windows from flashing when Windows GUI code runs CLI tools."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def subprocess_common_kwargs() -> dict[str, Any]:
    return {
        **subprocess_text_kwargs(),
        **subprocess_window_kwargs(),
    }


def terminate_process(process: subprocess.Popen[Any], timeout: float = 3.0) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
    except OSError:
        pass


def run_cancellable_capture(
    args: list[str],
    *,
    stdout: int | None = subprocess.PIPE,
    stderr: int | None = subprocess.PIPE,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    executable: str | None = None,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a capture subprocess without allowing PIPE backpressure to deadlock.

    FFmpeg writes most diagnostic/filter output to stderr.  Polling the child
    until it exits and only then calling ``communicate()`` can deadlock once a
    pipe fills (particularly on Windows, where pipe buffers are comparatively
    small). ``communicate(timeout=...)`` starts/drains the pipe readers while
    still giving us regular opportunities to honor cancellation.
    """
    process = subprocess.Popen(
        args,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        env=env,
        executable=executable,
        **subprocess_common_kwargs(),
    )
    if register_process is not None:
        register_process(process)
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                terminate_process(process)
                # Reap/drain whatever the child already produced so Windows
                # does not leave pipe reader handles behind in a frozen GUI app.
                try:
                    process.communicate(timeout=1.0)
                except (subprocess.TimeoutExpired, OSError):
                    pass
                raise OperationCancelled(ui_text("log_operation_cancelled"))
            try:
                stdout_value, stderr_value = process.communicate(timeout=0.15)
                break
            except subprocess.TimeoutExpired:
                continue
        return subprocess.CompletedProcess(
            args,
            process.returncode,
            stdout_value or "",
            stderr_value or "",
        )
    finally:
        if unregister_process is not None:
            unregister_process(process)


def title_from_details(details: dict[str, Any]) -> str:
    return str(
        details.get("title")
        or details.get("name")
        or details.get("original_title")
        or details.get("original_name")
        or ""
    )


def safe_filename_stem(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or "output"


def clean_output_name_extra(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned if cleaned.strip() else ""


def output_path_with_name_extra(output_path: Path, extra: str) -> Path:
    cleaned_extra = clean_output_name_extra(extra)
    if not cleaned_extra:
        return output_path

    suffix = output_path.suffix or ".mkv"
    stem = output_path.stem if output_path.suffix else output_path.name
    if not stem.endswith(cleaned_extra):
        stem = f"{stem}{cleaned_extra}"
    return output_path.with_name(f"{stem}{suffix}")


def output_path_without_name_extra(output_path: Path, extra: str) -> Path:
    cleaned_extra = clean_output_name_extra(extra)
    if not cleaned_extra:
        return output_path

    suffix = output_path.suffix
    stem = output_path.stem if suffix else output_path.name
    if not stem.endswith(cleaned_extra):
        return output_path
    stem = stem[: -len(cleaned_extra)] or "output"
    return output_path.with_name(f"{stem}{suffix}")


def release_year_from_text(value: str) -> str:
    match = re.search(r"(?:^|[ ._\-\[\(])((?:19|20)\d{2})(?:$|[ ._\-\]\)])", str(value or ""))
    return match.group(1) if match else ""


def local_release_year(media_dir: Path, output_path: Path | None = None, extra: str = "") -> str:
    candidates: list[str] = []
    if output_path is not None:
        base_output = output_path_without_name_extra(output_path, extra)
        candidates.append(base_output.stem if base_output.suffix else base_output.name)

    for directory in (media_dir, media_dir.parent):
        try:
            name = directory.name
        except Exception:
            name = ""
        if name:
            candidates.append(name)

    try:
        for path in media_dir.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() in VIDEO_CONTAINER_EXTENSIONS or path.suffix.lower() in VIDEO_EXTENSIONS:
                candidates.append(path.stem)
    except OSError:
        pass

    for candidate in candidates:
        year = release_year_from_text(candidate)
        if year:
            return year
    return ""


def output_path_with_year(output_path: Path, year: str, extra: str = "") -> Path:
    year = str(year or "").strip()
    if not re.fullmatch(r"(?:19|20)\d{2}", year):
        return output_path_with_name_extra(output_path, extra)

    base_output = output_path_without_name_extra(output_path, extra)
    suffix = base_output.suffix or ".mkv"
    stem = base_output.stem if base_output.suffix else base_output.name
    if not release_year_from_text(stem):
        stem = f"{stem.rstrip()} ({year})"
    base_output = base_output.with_name(f"{stem}{suffix}")
    return output_path_with_name_extra(base_output, extra)


def output_path_with_optional_year(
    output_path: Path,
    *,
    enabled: bool,
    media_type: str,
    media_dir: Path,
    extra: str,
    tmdb_year: str = "",
) -> Path:
    if not enabled or normalise_tmdb_media_type(media_type) != "movie":
        return output_path_with_name_extra(output_path, extra)
    year = local_release_year(media_dir, output_path, extra) or str(tmdb_year or "").strip()
    return output_path_with_year(output_path, year, extra)


def tmdb_output_path(media_dir: Path, title: str) -> Path:
    return media_dir / f"{safe_filename_stem(title)}.mkv"


def episode_code(ref: EpisodeRef) -> str:
    return f"S{ref.season:02d}E{ref.episode:02d}"


def tv_episode_output_title(
    series_title: str,
    episode_ref: EpisodeRef,
    episode_title: str = "",
) -> str:
    parts = [series_title.strip() or "TV", episode_code(episode_ref)]
    if episode_title.strip():
        parts.append(episode_title.strip())
    return " - ".join(parts)


def batch_episode_series_title(source_dir: Path, source: Path) -> str:
    title, _ = parse_release_name(source.stem)
    if title:
        return title
    title, _ = parse_release_name(source_dir.name)
    if title:
        return title
    return clean_release_title(source_dir.name or source.stem) or source.stem


def batch_episode_preview_title(source_dir: Path, task: BatchEpisodeTask) -> str:
    return tv_episode_output_title(
        batch_episode_series_title(source_dir, task.source),
        task.episode_ref,
    )


def batch_episode_output_path(source_dir: Path, task: BatchEpisodeTask) -> Path:
    return task.extract_dir / f"{safe_filename_stem(batch_episode_preview_title(source_dir, task))}.mkv"


def batch_mkv_title_for_episode(
    user_title: str,
    default_title: str,
    first_default_title: str,
    first_ref: EpisodeRef,
    current_ref: EpisodeRef,
) -> str:
    title = user_title.strip()
    if not title:
        return default_title
    if current_ref == first_ref:
        return title

    if first_default_title and title.startswith(first_default_title):
        return default_title + title[len(first_default_title):]

    first_code = episode_code(first_ref)
    current_code = episode_code(current_ref)
    return re.sub(re.escape(first_code), current_code, title, count=1, flags=re.IGNORECASE)


def localized_season_label(season: int, language: str) -> str:
    if normalise_language(language) == "tr":
        return f"Sezon {season}"
    return f"Season {season}"


def season_folder_name(
    series_title: str,
    season_name: str,
    season: int,
    language: str,
) -> str:
    title = series_title.strip() or "TV"
    name = season_name.strip() or localized_season_label(season, language)
    return safe_filename_stem(f"{title} - {name}")


def parse_episode_ref_from_text(value: str) -> EpisodeRef | None:
    text = value.lower()
    patterns = (
        r"(?:^|[^a-z0-9])s(\d{1,2})[ ._\-]*e(\d{1,3})(?:$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])(\d{1,2})x(\d{1,3})(?:$|[^a-z0-9])",
        (
            r"(?:season|sezon)[ ._\-]*(\d{1,2}).{0,30}?"
            r"(?:episode|ep|bolum|bölüm)[ ._\-]*(\d{1,3})"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            if season >= 0 and episode > 0:
                return EpisodeRef(season, episode)
    return None


def parse_season_number_from_text(value: str) -> int | None:
    text = value.lower()
    patterns = (
        r"(?:^|[^a-z0-9])s(\d{1,2})(?:$|[^a-z0-9])",
        r"(?:season|sezon)[ ._\-]*(\d{1,2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_episode_number_from_text(value: str) -> int | None:
    text = value.lower()
    patterns = (
        r"(?:^|[^a-z0-9])e(\d{1,3})(?:$|[^a-z0-9])",
        r"(?:episode|ep|bolum|bölüm)[ ._\-]*(\d{1,3})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            episode = int(match.group(1))
            if episode > 0:
                return episode
    return None


def episode_ref_from_path(path: Path, default_season: int | None = None) -> EpisodeRef | None:
    for candidate in (path.stem, path.name):
        parsed = parse_episode_ref_from_text(candidate)
        if parsed is not None:
            return parsed

    season = default_season
    if season is None:
        for parent in (path.parent, path.parent.parent):
            season = parse_season_number_from_text(parent.name)
            if season is not None:
                break

    episode = parse_episode_number_from_text(path.stem)
    if season is not None and episode is not None:
        return EpisodeRef(season, episode)

    return None


def episode_ref_from_settings(settings: AppSettings) -> EpisodeRef | None:
    if settings.media_type != "tv":
        return None
    for candidate in (settings.media_dir, settings.output_path):
        parsed = episode_ref_from_path(candidate)
        if parsed is not None:
            return parsed
    return None


def natural_path_sort_key(path: Path) -> list[Any]:
    parts: list[Any] = []
    for token in re.split(r"(\d+)", path.name.lower()):
        if token.isdigit():
            parts.append(int(token))
        elif token:
            parts.append(token)
    return parts


def path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def video_sources_in_folder(source_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_CONTAINER_EXTENSIONS
        ),
        key=natural_path_sort_key,
    )


def clean_release_title(value: str) -> str:
    cleaned = re.sub(r"[._+\-\[\]\(\)]+", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_release_name(name: str) -> tuple[str, str]:
    stem = name
    year_match = re.search(r"(?:^|[ ._\-\[\(])((?:19|20)\d{2})(?:$|[ ._\-\]\)])", stem)
    if year_match:
        title = clean_release_title(stem[: year_match.start()])
        return title, year_match.group(1)

    tokens = [token for token in re.split(r"[._\-\s]+", stem) if token]
    title_tokens: list[str] = []
    for token in tokens:
        normalised = re.sub(r"[^a-z0-9]+", "", token.lower())
        if normalised in RELEASE_STOP_TOKENS or re.fullmatch(r"s\d{1,2}e\d{1,2}", normalised):
            break
        title_tokens.append(token)
    return clean_release_title(" ".join(title_tokens)), ""


def strip_track_folder_suffix(name: str) -> str:
    return re.sub(r"(?i)(?:[._\-\s]+)?tracks?$", "", name).strip(" ._-")


def is_generic_track_folder_name(name: str) -> bool:
    return clean_release_title(name).lower() in {"track", "tracks"}


def release_output_name_candidates(media_dir: Path) -> list[str]:
    result: list[str] = []
    for raw in (media_dir.name, media_dir.parent.name):
        for candidate in (strip_track_folder_suffix(raw), raw):
            candidate = candidate.strip()
            if not candidate or is_generic_track_folder_name(candidate):
                continue
            if candidate not in result:
                result.append(candidate)
    return result


def release_output_title_from_folder(media_dir: Path) -> str:
    fallback = ""
    for candidate in release_output_name_candidates(media_dir):
        title, year = parse_release_name(candidate)
        if not title:
            continue
        output_title = f"{title} ({year})" if year else title
        if year:
            return output_title
        if not fallback:
            fallback = output_title
    return fallback


def default_output_name(config: dict[str, Any], media_dir: Path) -> str:
    template_name = template_output_name(config)
    if template_name.casefold() != DEFAULT_OUTPUT_NAME:
        return template_name

    release_title = release_output_title_from_folder(media_dir)
    if release_title:
        return f"{safe_filename_stem(release_title)}.mkv"
    return DEFAULT_OUTPUT_NAME


def default_output_path(config: dict[str, Any], media_dir: Path) -> Path:
    return media_dir / default_output_name(config, media_dir)


def release_name_candidates(settings: AppSettings) -> list[str]:
    candidates = [
        settings.media_dir.name,
        settings.output_path.parent.name,
        settings.output_path.stem,
    ]
    result: list[str] = []
    for candidate in candidates:
        raw = candidate.strip()
        for value in (strip_track_folder_suffix(raw), raw):
            value = value.strip()
            if value and value not in {".", "/"} and value not in result:
                result.append(value)
    return result


def normalise_title_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def result_title(result: dict[str, Any]) -> str:
    return str(
        result.get("title")
        or result.get("name")
        or result.get("original_title")
        or result.get("original_name")
        or ""
    )


def result_year(result: dict[str, Any]) -> str:
    date_value = str(result.get("release_date") or result.get("first_air_date") or "")
    return date_value[:4] if re.match(r"\d{4}", date_value) else ""


def result_original_title(result: dict[str, Any]) -> str:
    return str(
        result.get("original_title")
        or result.get("original_name")
        or result_title(result)
        or ""
    )


def score_tmdb_result(result: dict[str, Any], query: str, year: str) -> float:
    query_key = normalise_title_for_match(query)
    title_key = normalise_title_for_match(result_title(result))
    score = float(result.get("popularity") or 0)

    if title_key == query_key:
        score += 1000
    elif title_key.startswith(query_key) or query_key.startswith(title_key):
        score += 500
    elif query_key and query_key in title_key:
        score += 250

    found_year = result_year(result)
    if year and found_year == year:
        score += 300
    elif year and found_year:
        score -= min(abs(int(found_year) - int(year)) * 20, 200)

    return score


def normalize_video_fps(value: str) -> str:
    raw = value.strip().lower().removesuffix("fps").strip().replace(",", ".")
    if not raw:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        if float(raw) <= 0:
            raise UserVisibleError(ui_text("error_video_fps_positive"))
        if "." in raw:
            raw = raw.rstrip("0").rstrip(".")
        return f"{raw}fps"
    if re.fullmatch(r"\d+/\d+", raw):
        numerator, denominator = raw.split("/", 1)
        if int(numerator) <= 0 or int(denominator) <= 0:
            raise UserVisibleError(ui_text("error_video_fps_fraction_positive"))
        return f"{raw}fps"
    raise UserVisibleError(ui_text("error_video_fps_format"))


def parse_positive_minutes(value: str, label: str) -> float:
    raw = value.strip().replace(",", ".")
    if not raw:
        raise UserVisibleError(ui_text("error_required", label=label))
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        raise UserVisibleError(ui_text("error_minutes_numeric", label=label))
    minutes = float(raw)
    if minutes <= 0:
        raise UserVisibleError(ui_text("error_minutes_positive", label=label))
    return minutes


def parse_optional_positive_minutes(value: str, label: str) -> float | None:
    raw = value.strip()
    if not raw:
        return None
    return parse_positive_minutes(raw, label)


def parse_chapter_start_number(value: str) -> int:
    raw = value.strip() or "1"
    if not re.fullmatch(r"\d+", raw):
        raise UserVisibleError(ui_text("error_chapter_start_integer"))
    number = int(raw)
    if number <= 0:
        raise UserVisibleError(ui_text("error_chapter_start_positive"))
    return number


def numbered_entries(section: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    count = int(section.get("numberOfEntries", 0))
    return [(index, section[str(index)]) for index in range(count) if str(index) in section]


def basename_from_config_path(value: str) -> str:
    return Path(value).name


def load_template_config(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UserVisibleError(ui_text("error_config_not_found", path=path)) from exc
    except json.JSONDecodeError as exc:
        raise UserVisibleError(ui_text("error_config_json", error=exc)) from exc


def base_template_config() -> dict[str, Any]:
    return {
        "MKVToolNix GUI Settings": {"type": "MuxConfig", "version": 3},
        "global": {
            "chapterLanguage": "tr",
            "chapters": "chapters.txt",
            "destination": DEFAULT_OUTPUT_NAME,
            "destinationAuto": DEFAULT_OUTPUT_NAME,
            "globalTags": "",
            "title": "",
            "stopAfterVideoEnds": False,
        },
        "input": {
            "attachments": {"numberOfEntries": 0},
            "files": {"numberOfEntries": 0},
            "firstInputFileName": "",
            "trackOrder": [],
        },
    }


def load_or_create_template_config(
    template_path: Path | None,
    media_dir: Path,
) -> dict[str, Any]:
    if template_path is not None:
        return load_template_config(template_path)
    return create_auto_template_config(media_dir)


def atomic_write_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_saved_preferences() -> dict[str, str]:
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value is not None}


def save_saved_preferences(preferences: dict[str, str]) -> None:
    atomic_write_private_text(
        SETTINGS_PATH,
        json.dumps(preferences, ensure_ascii=False, indent=2) + "\n",
    )


def template_output_name(config: dict[str, Any]) -> str:
    destination = config.get("global", {}).get("destination") or DEFAULT_OUTPUT_NAME
    return Path(destination).name


def template_title(config: dict[str, Any]) -> str:
    return str(config.get("global", {}).get("title") or "")


def is_subtitle_entry(entry: dict[str, Any]) -> bool:
    track = entry.get("tracks", {}).get("0", {})
    if track.get("type") == 2:
        return True
    suffix = Path(str(entry.get("fileName", ""))).suffix.lower()
    return suffix in SUBTITLE_EXTENSIONS


def is_video_entry(entry: dict[str, Any]) -> bool:
    track = entry.get("tracks", {}).get("0", {})
    return track.get("type") == 1


def apply_video_fps_override(items: list[TrackItem], video_fps: str) -> None:
    default_duration = normalize_video_fps(video_fps)
    if not default_duration:
        return
    for item in items:
        if is_video_entry(item.entry):
            item.track["defaultDuration"] = default_duration


def track_type_value(item: TrackItem) -> int | None:
    try:
        return int(item.track.get("type"))
    except (TypeError, ValueError):
        return None


def track_language_value(item: TrackItem) -> str:
    value = str(item.track.get("language") or "").strip().lower()
    if "-" in value:
        value = value.split("-", 1)[0]
    return LANG_ALIASES.get(value, value)


def normalise_mux_language(language: str, fallback: str = MUX_UNKNOWN_LANGUAGE) -> str:
    value = str(language or "").strip().lower()
    if not value:
        return fallback
    if "-" in value:
        value = value.split("-", 1)[0]
    return LANG_ALIASES.get(value, value)


def normalise_mux_delay(delay: str) -> str:
    value = str(delay or "").strip()
    if not value:
        return ""
    if not re.fullmatch(r"[+-]?\d+", value):
        raise UserVisibleError(ui_text("error_track_delay_format"))
    return str(int(value))


def path_identity_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve()).lower()
    except OSError:
        return str(path.expanduser()).lower()


def track_type_label(item: TrackItem) -> str:
    return {
        0: ui_text("track_type_audio"),
        1: ui_text("track_type_video"),
        2: ui_text("track_type_subtitle"),
    }.get(track_type_value(item), ui_text("track_type_generic"))


def truthy_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "evet"}
    return bool(value)


def parse_language_order(value: str) -> list[str]:
    languages: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;|\s]+", value.strip().lower()):
        if not raw:
            continue
        language = raw.split("-", 1)[0]
        language = LANG_ALIASES.get(language, language)
        if language in seen:
            continue
        languages.append(language)
        seen.add(language)
    return languages


def is_forced_track_item(item: TrackItem) -> bool:
    return truthy_flag(item.track.get("forcedTrackFlag"))


def is_sdh_track_item(item: TrackItem) -> bool:
    if truthy_flag(item.track.get("hearingImpairedFlag")):
        return True
    name = str(item.track.get("name") or "").strip().lower()
    if re.search(r"\b(sdh|hi|cc|hearing impaired|closed captions?)\b", name):
        return True
    tokens = {token for token in re.split(r"[._\-\s]+", item.path.stem.lower()) if token}
    return bool(
        tokens
        & {
            "sdh",
            "hi",
            "cc",
            "hearing",
            "impaired",
            "closed",
            "caption",
            "captions",
        }
    )


def is_regular_subtitle_track_item(item: TrackItem) -> bool:
    if track_type_value(item) != 2 and media_kind_from_path(item.path) != "subtitle":
        return False
    return not is_forced_track_item(item) and not is_sdh_track_item(item)


def first_preferred_track_item(
    items: list[TrackItem],
    track_type: int,
) -> TrackItem | None:
    if not items:
        return None
    if track_type == 2:
        forced_items = [item for item in items if is_forced_track_item(item)]
        if forced_items:
            return forced_items[0]
    return items[0]


def select_default_track_item(
    ordered: list[TrackItem],
    track_type: int,
    language_order: list[str],
    *,
    fallback_to_first: bool,
    label: str,
) -> TrackItem | None:
    candidates = [item for item in ordered if track_type_value(item) == track_type]
    if not candidates:
        return None

    if not language_order:
        return candidates[0] if fallback_to_first else None

    for language in language_order:
        matches = [item for item in candidates if track_language_value(item) == language]
        if not matches:
            continue
        if track_type == 2:
            forced_matches = [item for item in matches if is_forced_track_item(item)]
            if forced_matches:
                return forced_matches[0]
        return matches[0]

    fallback_language_matches = [
        item for item in candidates if track_language_value(item) == MUX_UNKNOWN_LANGUAGE
    ]
    fallback_item = first_preferred_track_item(
        fallback_language_matches,
        track_type,
    )
    if fallback_item is not None:
        return fallback_item

    return candidates[0] if fallback_to_first else None


def select_default_subtitle_item(
    ordered: list[TrackItem],
    language_order: list[str],
    audio_language_order: list[str] | None = None,
) -> TrackItem | None:
    candidates = [item for item in ordered if track_type_value(item) == 2]
    if not candidates or not language_order:
        return None

    audio_language_order = list(audio_language_order or [])
    audio_languages = {
        track_language_value(item)
        for item in ordered
        if track_type_value(item) == 0
    }

    # Keep all existing forced/SDH behavior, but do not fall through to a
    # different regular subtitle language when the audio and subtitle priority
    # lists start with the same language and that subtitle language is absent.
    shared_primary_language = ""
    if (
        audio_language_order
        and language_order
        and audio_language_order[0] == language_order[0]
    ):
        shared_primary_language = language_order[0]

    shared_primary_subtitle_missing = bool(
        shared_primary_language
        and not any(
            track_language_value(item) == shared_primary_language
            for item in candidates
        )
    )

    for language in language_order:
        matches = [item for item in candidates if track_language_value(item) == language]
        if not matches:
            continue
        forced_matches = [item for item in matches if is_forced_track_item(item)]
        if forced_matches:
            return forced_matches[0]
        if shared_primary_subtitle_missing:
            continue
        if language in audio_languages:
            return None
        return matches[0]

    fallback_language_matches = [
        item for item in candidates if track_language_value(item) == MUX_UNKNOWN_LANGUAGE
    ]
    fallback_item = first_preferred_track_item(
        fallback_language_matches,
        2,
    )
    if fallback_item is None:
        return None
    if is_forced_track_item(fallback_item):
        return fallback_item
    if shared_primary_subtitle_missing:
        return None
    if track_language_value(fallback_item) in audio_languages:
        return None
    return fallback_item


def set_default_track_flags(
    items: list[TrackItem],
    track_type: int,
    selected: TrackItem | None,
) -> None:
    for item in items:
        if track_type_value(item) != track_type:
            continue
        item.track["defaultTrackFlag"] = item is selected
        item.track["defaultTrackFlagWasSet"] = True


def reorder_track_type_by_language(
    ordered: list[TrackItem],
    track_type: int,
    language_order: list[str],
    selected: TrackItem | None,
) -> list[TrackItem]:
    if not language_order and selected is None:
        return ordered

    ranked_languages = {language: index for index, language in enumerate(language_order)}
    indexed = list(enumerate(ordered))
    target_items = [
        (index, item)
        for index, item in indexed
        if track_type_value(item) == track_type
    ]
    if not target_items:
        return ordered

    def sort_key(pair: tuple[int, TrackItem]) -> tuple[int, int, int, int]:
        index, item = pair
        selected_rank = 0 if item is selected else 1
        language_rank = ranked_languages.get(track_language_value(item), len(ranked_languages))
        forced_rank = 0 if track_type == 2 and is_forced_track_item(item) else 1
        return (selected_rank, language_rank, forced_rank, index)

    sorted_targets = [item for _, item in sorted(target_items, key=sort_key)]
    replacements = iter(sorted_targets)
    return [
        next(replacements) if track_type_value(item) == track_type else item
        for item in ordered
    ]


def group_track_order_by_type(ordered: list[TrackItem]) -> list[TrackItem]:
    type_rank = {
        1: 0,  # video
        0: 1,  # audio
        2: 2,  # subtitle
    }
    return [
        item
        for _, item in sorted(
            enumerate(ordered),
            key=lambda pair: (type_rank.get(track_type_value(pair[1]), 3), pair[0]),
        )
    ]


def apply_default_track_preferences(
    config: dict[str, Any],
    items: list[TrackItem],
    audio_language_order: str,
    subtitle_language_order: str,
) -> list[TrackItem]:
    ordered = ordered_items(config, items)
    audio_order = parse_language_order(audio_language_order)
    subtitle_order = parse_language_order(subtitle_language_order)

    selected_audio = select_default_track_item(
        ordered,
        0,
        audio_order,
        fallback_to_first=True,
        label=ui_text("track_type_audio"),
    )
    selected_subtitle = select_default_subtitle_item(
        ordered,
        subtitle_order,
        audio_order,
    )

    set_default_track_flags(items, 0, selected_audio)
    set_default_track_flags(items, 2, selected_subtitle)

    ordered = reorder_track_type_by_language(ordered, 0, audio_order, selected_audio)
    ordered = reorder_track_type_by_language(ordered, 2, subtitle_order, selected_subtitle)
    return group_track_order_by_type(ordered)


def next_object_id(config: dict[str, Any]) -> int:
    max_id = 0
    files = config.get("input", {}).get("files", {})
    for _, entry in numbered_entries(files):
        for key in ("objectID",):
            value = entry.get(key)
            if isinstance(value, int):
                max_id = max(max_id, value)
        tracks = entry.get("tracks", {})
        for _, track in numbered_entries(tracks):
            value = track.get("objectID")
            if isinstance(value, int):
                max_id = max(max_id, value)
    return max_id + 1


def next_object_id_for_items(config: dict[str, Any], items: list[TrackItem]) -> int:
    max_id = next_object_id(config) - 1
    for item in items:
        for value in (item.entry.get("objectID"), item.track.get("objectID")):
            if isinstance(value, int):
                max_id = max(max_id, value)
    return max_id + 1


def infer_language_from_filename(path: Path, unknown_language: str = "und") -> str:
    tokens = [token for token in re.split(r"[._\-\s]+", path.stem.lower()) if token]
    for token in tokens:
        if token in SUBTITLE_DESCRIPTOR_TOKENS:
            continue
        if token == "und":
            return unknown_language
        if token in LANG_ALIASES:
            return LANG_ALIASES[token]
        if re.fullmatch(r"[a-z]{2}", token):
            return token
    return unknown_language


def media_kind_from_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in SUBTITLE_EXTENSIONS:
        return "subtitle"
    return None


def mux_asset_info_from_path(path: Path) -> tuple[str, str] | None:
    name = path.name.lower()
    if name == "chapters.txt":
        return "chapters", "chapters.txt"
    if name == "tags.xml":
        return "tags", "tags.xml"
    target_name = ARTWORK_TARGET_NAME_ALIASES.get(name)
    if target_name:
        return "artwork", target_name
    return None


def is_supported_mux_add_path(path: Path) -> bool:
    return media_kind_from_path(path) is not None or mux_asset_info_from_path(path) is not None


def is_media_track_path(path: Path) -> bool:
    return path.is_file() and media_kind_from_path(path) is not None


def discover_media_track_paths(media_dir: Path) -> list[Path]:
    return sorted(
        (path for path in media_dir.iterdir() if is_media_track_path(path)),
        key=lambda item: item.name.lower(),
    )


def append_part_number(path: Path) -> tuple[str, int] | None:
    match = re.fullmatch(r"(.+)\.([1-9]\d*)", path.stem)
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def discover_media_track_paths_with_appends(
    media_dir: Path,
) -> tuple[list[Path], dict[str, tuple[Path, ...]], set[str]]:
    paths = discover_media_track_paths(media_dir)
    by_name = {path.name.lower(): path for path in paths}
    grouped: dict[str, list[tuple[int, Path]]] = {}

    for path in paths:
        parsed = append_part_number(path)
        if parsed is None:
            continue
        base_stem, number = parsed
        base_name = f"{base_stem}{path.suffix}".lower()
        base_path = by_name.get(base_name)
        if base_path is None:
            continue
        if media_kind_from_path(base_path) != media_kind_from_path(path):
            continue
        if media_kind_from_path(path) == "subtitle":
            continue
        grouped.setdefault(base_path.name.lower(), []).append((number, path))

    append_paths_by_base: dict[str, tuple[Path, ...]] = {}
    append_names: set[str] = set()
    for base_name, parts in grouped.items():
        if not any(number == 1 for number, _ in parts):
            continue
        ordered_parts = tuple(
            path for _, path in sorted(parts, key=lambda item: (item[0], item[1].name.lower()))
        )
        append_paths_by_base[base_name] = ordered_parts
        append_names.update(path.name.lower() for path in ordered_parts)

    root_paths = [path for path in paths if path.name.lower() not in append_names]
    return root_paths, append_paths_by_base, append_names


def normalise_append_paths_for_track(base_path: Path, append_paths: tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
    base_kind = media_kind_from_path(base_path)
    if base_kind not in {"audio", "video"}:
        return ()

    base_suffix = base_path.suffix.lower()
    base_key = path_identity_key(base_path)
    result: list[Path] = []
    seen: set[str] = set()
    for raw_path in append_paths:
        path = Path(raw_path).expanduser()
        if path.exists():
            path = path.resolve()
        if not path.is_file():
            raise UserVisibleError(ui_text("error_track_file_not_found", path=path))
        key = path_identity_key(path)
        if key == base_key:
            raise UserVisibleError(ui_text("error_append_audio_self"))
        if key in seen:
            continue
        if media_kind_from_path(path) != base_kind or path.suffix.lower() != base_suffix:
            raise UserVisibleError(ui_text("error_append_audio_type", name=base_path.name))
        result.append(path)
        seen.add(key)
    return tuple(result)


def infer_video_fps_from_text(value: str) -> str:
    pattern = (
        r"(?:^|[._\-\s])"
        r"(24000/1001|30000/1001|60000/1001|23\.976|23\.98|24|25|29\.970|29\.97|30|50|59\.940|59\.94|60)"
        r"(?:$|[._\-\s])"
    )
    match = re.search(pattern, str(value or ""), flags=re.IGNORECASE)
    return match.group(1) if match else ""


def infer_video_fps_from_filename(path: Path) -> str:
    # Raw elementary streams such as und.25.h264 / und.24000-1001.h265 do not
    # always expose FPS through ffprobe/mkvmerge. Prefer explicit FPS tokens in
    # the actual raw video filename before falling back to metadata probing.
    if media_kind_from_path(path) != "video" and path.suffix.lower() not in VIDEO_CONTAINER_EXTENSIONS:
        return ""
    fps = infer_video_fps_from_text(path.stem)
    if fps:
        return fps
    # Some release folders keep the FPS only in the parent/title folder name.
    return infer_video_fps_from_text(path.parent.name)


def track_type_for_kind(kind: str) -> int:
    return {"audio": 0, "video": 1, "subtitle": 2}[kind]


def file_type_for_kind(kind: str) -> int:
    return {"audio": 2, "video": 4, "subtitle": 27}[kind]


def infer_subtitle_track_flags(
    path: Path, unknown_language: str = MUX_UNKNOWN_LANGUAGE,
) -> dict[str, Any]:
    tokens = {token for token in re.split(r"[._\-\s]+", path.stem.lower()) if token}
    forced = bool(tokens & {"forced", "force", "forc"})
    sdh = bool(tokens & {"sdh", "hi", "cc", "hearing"})
    name_parts = []
    if forced:
        name_parts.append("Forced")
    if sdh:
        name_parts.append("SDH")
    name = " ".join(name_parts)
    return {
        "language": infer_language_from_filename(path, unknown_language),
        "name": name,
        "nameWasPresent": bool(name),
        "defaultTrackFlag": False,
        "defaultTrackFlagWasSet": True,
        "forcedTrackFlag": 1 if forced else 0,
        "forcedTrackFlagWasSet": True,
        "hearingImpairedFlag": sdh,
        "hearingImpairedFlagWasSet": True,
        "originalFlag": False,
        "originalFlagWasSet": True,
    }


def apply_subtitle_name_from_filename(entry: dict[str, Any], path: Path) -> None:
    if not is_subtitle_entry(entry):
        return
    track = entry.get("tracks", {}).get("0", {})
    if track.get("name"):
        return
    inferred = infer_subtitle_track_flags(path)
    if inferred["name"]:
        track["name"] = inferred["name"]
        track["nameWasPresent"] = True


def apply_track_metadata_from_filename(entry: dict[str, Any], path: Path, unknown_language: str = MUX_UNKNOWN_LANGUAGE) -> None:
    kind = media_kind_from_path(path)
    if kind is None:
        return
    track = entry.setdefault("tracks", {}).setdefault("0", {})
    track["type"] = track_type_for_kind(kind)
    track["language"] = infer_language_from_filename(path, unknown_language)
    if kind == "video":
        fps = detect_video_fps_from_media_path(path)
        if fps:
            track["defaultDuration"] = normalize_video_fps(fps)
    if kind == "subtitle":
        track.update(infer_subtitle_track_flags(path, unknown_language))


def template_entries_for_kind(config: dict[str, Any], kind: str, suffix: str) -> list[dict[str, Any]]:
    files = config.get("input", {}).get("files", {})
    target_type = track_type_for_kind(kind)
    entries = []
    for _, entry in numbered_entries(files):
        track = entry.get("tracks", {}).get("0", {})
        if track.get("type") != target_type:
            continue
        entries.append(entry)

    same_extension = [
        entry
        for entry in entries
        if Path(str(entry.get("fileName", ""))).suffix.lower() == suffix
    ]
    return same_extension or entries


def make_minimal_track_entry(path: Path, object_id_seed: int, unknown_language: str = MUX_UNKNOWN_LANGUAGE) -> tuple[dict[str, Any], int]:
    kind = media_kind_from_path(path)
    if kind is None:
        raise UserVisibleError(ui_text("error_unsupported_track_type", name=path.name))

    track: dict[str, Any] = {
        "id": 0,
        "objectID": object_id_seed + 1,
        "type": track_type_for_kind(kind),
        "language": infer_language_from_filename(path, unknown_language),
        "muxThis": True,
        "trackEnabledFlag": 1,
        "trackEnabledFlagWasSet": True,
    }
    fps = detect_video_fps_from_media_path(path)
    if kind == "video" and fps:
        track["defaultDuration"] = normalize_video_fps(fps)
    if kind == "subtitle":
        track.update(infer_subtitle_track_flags(path, unknown_language))

    entry = {
        "additionalPart": False,
        "fileName": str(path),
        "objectID": object_id_seed,
        "tracks": {"0": track, "numberOfEntries": 1},
        "type": file_type_for_kind(kind),
    }
    return entry, object_id_seed + 2


def make_track_entry_from_path(
    config: dict[str, Any], path: Path, object_id_seed: int, unknown_language: str = MUX_UNKNOWN_LANGUAGE,
) -> tuple[dict[str, Any], int]:
    kind = media_kind_from_path(path)
    if kind is None:
        raise UserVisibleError(ui_text("error_unsupported_track_type", name=path.name))

    templates = template_entries_for_kind(config, kind, path.suffix.lower())
    if templates:
        entry = copy.deepcopy(templates[0])
        entry["fileName"] = str(path)
        entry["objectID"] = object_id_seed
        track = entry.setdefault("tracks", {}).setdefault("0", {})
        entry["tracks"]["numberOfEntries"] = 1
        track["id"] = int(track.get("id", 0) or 0)
        track["objectID"] = object_id_seed + 1
        track["type"] = track_type_for_kind(kind)
        track["language"] = infer_language_from_filename(path, unknown_language)
        track["muxThis"] = True
        if kind == "video":
            fps = detect_video_fps_from_media_path(path)
            if fps:
                track["defaultDuration"] = normalize_video_fps(fps)
        if kind == "subtitle":
            track.update(infer_subtitle_track_flags(path, unknown_language))
        return entry, object_id_seed + 2

    return make_minimal_track_entry(path, object_id_seed, unknown_language)


def discover_auto_attachment_paths(media_dir: Path) -> list[Path]:
    paths: list[Path] = []
    used: set[str] = set()

    for name in STANDARD_ATTACHMENT_NAMES:
        path = media_dir / name
        if path.exists() and path.is_file():
            paths.append(path)
            used.add(str(path.resolve()).lower())

    for path in sorted(media_dir.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file() or path.suffix.lower() not in FONT_ATTACHMENT_EXTENSIONS:
            continue
        key = str(path.resolve()).lower()
        if key in used:
            continue
        paths.append(path)
        used.add(key)

    return paths


def attachment_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    font_mimes = {
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".ttc": "font/collection",
        ".otc": "font/collection",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }
    return font_mimes.get(suffix) or guess_mime_type(path)


def create_auto_template_config(media_dir: Path) -> dict[str, Any]:
    config = base_template_config()
    entries: list[dict[str, Any]] = []
    seed = 1
    root_paths, _, _ = discover_media_track_paths_with_appends(media_dir)
    for path in root_paths:
        entry, seed = make_minimal_track_entry(path, seed)
        entries.append(entry)

    input_section = config["input"]
    input_section["files"] = rebuild_numbered_section(input_section["files"], entries)
    input_section["firstInputFileName"] = str(entries[0]["fileName"]) if entries else ""
    input_section["trackOrder"] = [
        entry["tracks"]["0"]["objectID"]
        for entry in entries
        if entry.get("tracks", {}).get("0", {}).get("objectID") is not None
    ]

    attachments = []
    for path in discover_auto_attachment_paths(media_dir):
        attachments.append(
            {
                "MIMEType": attachment_mime_type(path),
                "description": "",
                "fileName": str(path),
                "name": path.name,
                "style": 1,
            }
        )
    input_section["attachments"] = rebuild_numbered_section(
        input_section["attachments"],
        attachments,
    )
    return config


def make_extra_subtitle_entry(
    config: dict[str, Any],
    path: Path,
    object_id_seed: int,
) -> tuple[dict[str, Any], int]:
    files = config.get("input", {}).get("files", {})
    subtitle_templates = [entry for _, entry in numbered_entries(files) if is_subtitle_entry(entry)]
    if not subtitle_templates:
        raise UserVisibleError(ui_text("error_extra_subtitle_template_missing"))

    same_extension = [
        entry
        for entry in subtitle_templates
        if Path(str(entry.get("fileName", ""))).suffix.lower() == path.suffix.lower()
    ]
    entry = copy.deepcopy((same_extension or subtitle_templates)[0])
    entry["fileName"] = str(path)
    entry["objectID"] = object_id_seed

    track = entry["tracks"]["0"]
    track.update(infer_subtitle_track_flags(path))
    track["objectID"] = object_id_seed + 1
    return entry, object_id_seed + 2


def assign_track_file_ids(items: list[TrackItem]) -> None:
    file_id = 0
    for item in items:
        item.file_id = file_id
        file_id += 1 + len(item.append_paths)


def discover_track_items(
    config: dict[str, Any],
    media_dir: Path,
    include_extra_subtitles: bool,
    unknown_language: str = MUX_UNKNOWN_LANGUAGE,
) -> tuple[list[TrackItem], list[str], list[str]]:
    files = config.get("input", {}).get("files", {})
    root_paths, append_paths_by_base, append_names = discover_media_track_paths_with_appends(
        media_dir
    )

    items: list[TrackItem] = []
    missing_optional: list[str] = []
    missing_required: list[str] = []
    used_names: set[str] = set()

    for index, entry in numbered_entries(files):
        name = basename_from_config_path(str(entry.get("fileName", "")))
        if not name:
            continue
        candidate = media_dir / name
        if candidate.name.lower() in append_names:
            continue
        if candidate.exists():
            copied = copy.deepcopy(entry)
            copied["fileName"] = str(candidate)
            apply_track_metadata_from_filename(copied, candidate, unknown_language)
            apply_subtitle_name_from_filename(copied, candidate)
            append_paths = append_paths_by_base.get(candidate.name.lower(), ())
            items.append(
                TrackItem(copied, candidate, index, append_paths=append_paths)
            )
            used_names.add(candidate.name.lower())
            used_names.update(path.name.lower() for path in append_paths)
        else:
            missing_optional.append(name)

    seed = next_object_id(config)
    for path in root_paths:
        if path.name.lower() in used_names:
            continue
        if path.suffix.lower() in SUBTITLE_EXTENSIONS and not include_extra_subtitles:
            continue
        entry, seed = make_track_entry_from_path(config, path, seed, unknown_language)
        append_paths = append_paths_by_base.get(path.name.lower(), ())
        items.append(
            TrackItem(entry, path, None, is_extra=True, append_paths=append_paths)
        )
        used_names.add(path.name.lower())
        used_names.update(part.name.lower() for part in append_paths)

    assign_track_file_ids(items)

    return items, missing_optional, missing_required


def append_additional_mux_tracks(
    config: dict[str, Any],
    items: list[TrackItem],
    additional_tracks: list[AdditionalMuxTrack],
    unknown_language: str = MUX_UNKNOWN_LANGUAGE,
) -> None:
    seed = next_object_id_for_items(config, items)
    for additional in additional_tracks:
        path = additional.path.expanduser()
        if path.exists():
            path = path.resolve()
        if not path.is_file():
            raise UserVisibleError(ui_text("error_track_file_not_found", path=path))
        entry, seed = make_track_entry_from_path(config, path, seed, unknown_language)
        track = entry.setdefault("tracks", {}).setdefault("0", {})
        track["language"] = normalise_mux_language(additional.language, unknown_language)
        delay = normalise_mux_delay(additional.delay)
        if delay and track.get("type") in (0, 2):
            track["delay"] = delay
        elif "delay" in track:
            track.pop("delay", None)
        append_paths = normalise_append_paths_for_track(path, list(additional.append_paths))
        items.append(TrackItem(entry, path, None, is_extra=True, append_paths=append_paths))
    assign_track_file_ids(items)


def apply_mux_track_append_overrides(
    items: list[TrackItem],
    append_overrides: dict[str, tuple[Path, ...]],
) -> None:
    if not append_overrides:
        return
    for item in items:
        append_paths = append_overrides.get(path_identity_key(item.path))
        if append_paths is None:
            continue
        item.append_paths = normalise_append_paths_for_track(item.path, list(append_paths))


def remove_items_consumed_as_appends(items: list[TrackItem]) -> list[TrackItem]:
    """Drop files that are already consumed as append parts of another item.

    Manual append selection must behave like mkvmerge's ``base + append`` input:
    the append file participates in the base track chain and must not also be
    emitted as an independent track.
    """
    append_source_keys = {
        path_identity_key(append_path)
        for item in items
        for append_path in item.append_paths
    }
    if not append_source_keys:
        return items
    return [
        item for item in items
        if path_identity_key(item.path) not in append_source_keys
    ]


def apply_mux_track_language_overrides(
    items: list[TrackItem],
    language_overrides: dict[str, str],
    unknown_language: str = MUX_UNKNOWN_LANGUAGE,
) -> None:
    if not language_overrides:
        return
    for item in items:
        language = language_overrides.get(path_identity_key(item.path))
        if language is None:
            continue
        item.track["language"] = normalise_mux_language(language, unknown_language)


def apply_mux_track_delay_overrides(
    items: list[TrackItem],
    delay_overrides: dict[str, str],
) -> None:
    if not delay_overrides:
        return
    for item in items:
        delay = delay_overrides.get(path_identity_key(item.path))
        if delay is None:
            continue
        if track_type_value(item) not in (0, 2):
            item.track.pop("delay", None)
            continue
        normalised = normalise_mux_delay(delay)
        if normalised:
            item.track["delay"] = normalised
        else:
            item.track.pop("delay", None)


def apply_custom_track_order(
    ordered: list[TrackItem],
    track_order_keys: list[str],
) -> list[TrackItem]:
    if not track_order_keys:
        return ordered
    buckets: dict[str, list[TrackItem]] = {}
    for item in ordered:
        buckets.setdefault(path_identity_key(item.path), []).append(item)

    result: list[TrackItem] = []
    seen_ids: set[int] = set()
    for key in track_order_keys:
        bucket = buckets.get(key)
        if not bucket:
            continue
        item = bucket.pop(0)
        result.append(item)
        seen_ids.add(id(item))

    result.extend(item for item in ordered if id(item) not in seen_ids)
    return result


def prepare_mux_track_items(
    config: dict[str, Any],
    media_dir: Path,
    include_extra_subtitles: bool,
    unknown_language: str = MUX_UNKNOWN_LANGUAGE,
    additional_tracks: list[AdditionalMuxTrack] | None = None,
    language_overrides: dict[str, str] | None = None,
    delay_overrides: dict[str, str] | None = None,
    append_overrides: dict[str, tuple[Path, ...]] | None = None,
    excluded_track_keys: set[str] | None = None,
) -> tuple[list[TrackItem], list[str]]:
    items, missing_optional, _ = discover_track_items(
        config,
        media_dir,
        include_extra_subtitles,
        unknown_language,
    )
    append_additional_mux_tracks(
        config,
        items,
        list(additional_tracks or []),
        unknown_language,
    )
    apply_mux_track_append_overrides(items, dict(append_overrides or {}))
    excluded = set(excluded_track_keys or set())
    if excluded:
        items = [item for item in items if path_identity_key(item.path) not in excluded]
    # A manual append source is part of an *active* preceding track chain, not a
    # second standalone track. Apply user exclusions first so disabling the base
    # track does not accidentally hide a source that should become independent
    # again.
    items = remove_items_consumed_as_appends(items)
    apply_mux_track_language_overrides(
        items,
        dict(language_overrides or {}),
        unknown_language,
    )
    apply_mux_track_delay_overrides(
        items,
        dict(delay_overrides or {}),
    )
    assign_track_file_ids(items)
    return items, missing_optional


def ordered_items(config: dict[str, Any], items: list[TrackItem]) -> list[TrackItem]:
    order = config.get("input", {}).get("trackOrder") or []
    by_object_id = {item.object_id: item for item in items if item.object_id is not None}
    ordered: list[TrackItem] = []

    for object_id in order:
        item = by_object_id.pop(object_id, None)
        if item is not None:
            ordered.append(item)

    remaining_template_items = [
        item for item in items if not item.is_extra and item not in ordered
    ]
    extra_items = [item for item in items if item.is_extra]
    return ordered + remaining_template_items + extra_items


def bool_arg(value: Any) -> str:
    return "1" if truthy_flag(value) else "0"


def add_if_present(args: list[str], option: str, track_id: int, value: Any) -> None:
    if value in (None, ""):
        return
    args.extend([option, f"{track_id}:{value}"])


def append_source_options(args: list[str], item: TrackItem) -> None:
    track = item.track
    track_id = int(track.get("id", 0))

    add_if_present(args, "--language", track_id, track.get("language"))

    name = track.get("name")
    if name:
        args.extend(["--track-name", f"{track_id}:{name}"])

    flags = [
        ("--default-track-flag", "defaultTrackFlag"),
        ("--forced-display-flag", "forcedTrackFlag"),
        ("--track-enabled-flag", "trackEnabledFlag"),
        ("--hearing-impaired-flag", "hearingImpairedFlag"),
        ("--visual-impaired-flag", "visualImpairedFlag"),
        ("--text-descriptions-flag", "textDescriptionsFlag"),
        ("--original-flag", "originalFlag"),
        ("--commentary-flag", "commentaryFlag"),
    ]
    for option, key in flags:
        if key in track:
            args.extend([option, f"{track_id}:{bool_arg(track.get(key))}"])

    add_if_present(args, "--sub-charset", track_id, track.get("characterSet"))
    add_if_present(args, "--timestamps", track_id, track.get("timestamps"))
    add_if_present(args, "--default-duration", track_id, track.get("defaultDuration"))

    delay = str(track.get("delay") or "").strip()
    stretch_by = str(track.get("stretchBy") or "").strip()
    if delay:
        sync_value = delay if not stretch_by else f"{delay},{stretch_by}"
        args.extend(["--sync", f"{track_id}:{sync_value}"])

    args.append(str(item.path))
    for append_path in item.append_paths:
        args.extend(["+", str(append_path)])


def append_to_mappings(items: list[TrackItem]) -> list[str]:
    mappings: list[str] = []
    for item in items:
        previous_file_id = item.file_id
        for offset, _ in enumerate(item.append_paths, start=1):
            append_file_id = item.file_id + offset
            mappings.append(f"{append_file_id}:0:{previous_file_id}:0")
            previous_file_id = append_file_id
    return mappings


def required_attachments(config: dict[str, Any], media_dir: Path) -> list[dict[str, Any]]:
    attachments = config.get("input", {}).get("attachments", {})
    result: list[dict[str, Any]] = []
    for _, attachment in numbered_entries(attachments):
        name = str(attachment.get("name") or basename_from_config_path(str(attachment.get("fileName", ""))))
        file_name = basename_from_config_path(str(attachment.get("fileName", name)))
        path = media_dir / file_name
        result.append(
            {
                "path": path,
                "name": name,
                "mime": attachment.get("MIMEType") or attachment_mime_type(path),
                "description": attachment.get("description") or "",
            }
        )
    return result


def discover_attachments(
    config: dict[str, Any],
    media_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    result: list[dict[str, Any]] = []
    missing: list[str] = []
    used_names: set[str] = set()

    for attachment in required_attachments(config, media_dir):
        used_names.add(str(attachment["name"]).lower())
        if attachment["path"].exists():
            result.append(attachment)
        else:
            missing.append(attachment["path"].name)

    for path in discover_auto_attachment_paths(media_dir):
        attachment_name = path.name
        if attachment_name.lower() in used_names:
            continue
        result.append(
            {
                "path": path,
                "name": attachment_name,
                "mime": attachment_mime_type(path),
                "description": "",
            }
        )
        used_names.add(attachment_name.lower())

    return result, missing


def guess_mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def format_chapter_timestamp(total_seconds: float) -> str:
    milliseconds = int(round(total_seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def chapter_end_minutes_from_duration_seconds(duration_seconds: float) -> str:
    if duration_seconds <= 0:
        return ""
    return str(max(1, int(math.ceil(duration_seconds / 60))))


def duration_seconds_from_identify_payload(payload: dict[str, Any]) -> float:
    durations = [
        parse_duration_seconds(payload.get("container", {}).get("properties", {}).get("duration"))
    ]
    for track in payload.get("tracks", []):
        durations.append(parse_duration_seconds(track.get("properties", {}).get("duration")))
    return max(durations, default=0.0)


def detect_chapter_end_minutes_for_source(source: Path) -> str:
    return chapter_end_minutes_from_duration_seconds(
        duration_seconds_from_identify_payload(identify_mkv(source))
    )


def detect_ffprobe_duration_seconds(
    path: Path,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> float:
    ffprobe = ffprobe_path(auto_install=False)
    if not ffprobe:
        return 0.0
    args = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=duration",
        "-of",
        "json",
        str(path),
    ]
    process = run_cancellable_capture(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    if process.returncode != 0:
        return 0.0
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return 0.0

    def ffprobe_seconds(value: Any) -> float:
        try:
            duration = float(str(value or "").strip())
        except ValueError:
            return 0.0
        return duration if duration > 0 else 0.0

    durations = [ffprobe_seconds(payload.get("format", {}).get("duration"))]
    for stream in payload.get("streams", []):
        durations.append(ffprobe_seconds(stream.get("duration")))
    return max(durations, default=0.0)


def detect_item_duration_seconds(
    item: TrackItem,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> float:
    if media_kind_from_path(item.path) == "audio":
        duration = detect_ffprobe_duration_seconds(
            item.path,
            cancel_event=cancel_event,
            register_process=register_process,
            unregister_process=unregister_process,
        )
        if duration > 0:
            return duration

    mkvmerge = third_party_tool_path("mkvmerge", required=False)
    if not mkvmerge:
        return 0.0
    args = [mkvmerge, "--identification-format", "json", "--identify", str(item.path)]
    process = run_cancellable_capture(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    if process.returncode > 1:
        return 0.0
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return 0.0

    return duration_seconds_from_identify_payload(payload)


def duration_detection_priority(item: TrackItem) -> tuple[int, str]:
    kind = media_kind_from_path(item.path)
    if kind == "audio":
        return 0, item.path.name.lower()
    if kind == "video":
        return 1, item.path.name.lower()
    return 2, item.path.name.lower()


def detect_media_duration_seconds(
    items: list[TrackItem],
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> float:
    ordered = sorted(
        items,
        key=duration_detection_priority,
    )
    for item in ordered:
        duration = detect_item_duration_seconds(
            item,
            cancel_event=cancel_event,
            register_process=register_process,
            unregister_process=unregister_process,
        )
        if duration > 0:
            return duration
    return 0.0


def detect_chapter_end_minutes_for_media_dir(
    config: dict[str, Any],
    media_dir: Path,
    include_extra_subtitles: bool,
    tag_language: str = "",
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> str:
    unknown_language = normalise_language(tag_language) if tag_language else MUX_UNKNOWN_LANGUAGE
    items, _, _ = discover_track_items(
        config,
        media_dir,
        include_extra_subtitles,
        unknown_language,
    )
    return chapter_end_minutes_from_duration_seconds(
        detect_media_duration_seconds(
            items,
            cancel_event=cancel_event,
            register_process=register_process,
            unregister_process=unregister_process,
        )
    )


def intro_detection_limit_seconds(duration_seconds: float = 0.0) -> float:
    if duration_seconds <= 0:
        return float(INTRO_DETECTION_MAX_SECONDS)
    return max(
        INTRO_DETECTION_MIN_SECONDS,
        min(float(INTRO_DETECTION_MAX_SECONDS), duration_seconds - 30),
    )


def intro_candidate_is_valid(seconds: float, duration_seconds: float = 0.0) -> bool:
    if seconds < INTRO_DETECTION_MIN_SECONDS:
        return False
    if seconds > intro_detection_limit_seconds(duration_seconds):
        return False
    if duration_seconds > 0 and seconds >= duration_seconds - 30:
        return False
    return True


def intro_common_time_bonus(seconds: float) -> float:
    if 70 <= seconds <= 180:
        return 12.0
    if 45 <= seconds <= 260:
        return 7.0
    if seconds <= INTRO_DETECTION_MAX_SECONDS:
        return 3.0
    return 0.0


def top_intro_candidates(
    candidates: list[IntroDetectionCandidate],
    duration_seconds: float = 0.0,
) -> list[IntroDetectionCandidate]:
    valid = [
        candidate
        for candidate in candidates
        if intro_candidate_is_valid(candidate.seconds, duration_seconds)
    ]
    return sorted(valid, key=lambda candidate: candidate.score, reverse=True)[
        :INTRO_DETECTION_TOP_CANDIDATES
    ]


def parse_intro_timestamp_seconds(value: str) -> float | None:
    raw = value.strip().replace(",", ".")
    match = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)", raw)
    if match is None:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def parse_srt_vtt_events(text: str) -> list[tuple[float, float]]:
    events: list[tuple[float, float]] = []
    for line in text.splitlines():
        if "-->" not in line:
            continue
        start_raw, end_raw = line.split("-->", 1)
        start = parse_intro_timestamp_seconds(start_raw)
        end = parse_intro_timestamp_seconds(end_raw)
        if start is None:
            continue
        if end is None or end <= start:
            end = start + 2.0
        events.append((start, end))
    return events


def parse_ass_events(text: str) -> list[tuple[float, float]]:
    events: list[tuple[float, float]] = []
    format_fields: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("format:"):
            format_fields = [
                field.strip().lower()
                for field in line.split(":", 1)[1].split(",")
            ]
            continue
        if not lower.startswith("dialogue:"):
            continue

        payload = line.split(":", 1)[1].lstrip()
        if format_fields:
            parts = payload.split(",", max(0, len(format_fields) - 1))
            try:
                start_index = format_fields.index("start")
                end_index = format_fields.index("end")
            except ValueError:
                start_index, end_index = 1, 2
        else:
            parts = payload.split(",", 9)
            start_index, end_index = 1, 2

        if len(parts) <= max(start_index, end_index):
            continue
        start = parse_intro_timestamp_seconds(parts[start_index])
        end = parse_intro_timestamp_seconds(parts[end_index])
        if start is None:
            continue
        if end is None or end <= start:
            end = start + 2.0
        events.append((start, end))
    return events


def parse_subtitle_intro_events(path: Path) -> list[tuple[float, float]]:
    suffix = path.suffix.lower()
    if suffix not in {".srt", ".vtt", ".ass", ".ssa"}:
        return []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    if suffix in {".ass", ".ssa"}:
        return parse_ass_events(text)
    return parse_srt_vtt_events(text)


def merge_subtitle_events(
    events: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(events):
        if not merged or start > merged[-1][1] + 1.0:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))
    return merged


def subtitle_intro_candidates(
    item: TrackItem,
    duration_seconds: float = 0.0,
) -> list[IntroDetectionCandidate]:
    """Return post-intro dialogue hints, never a raw first-subtitle guess.

    A valid subtitle hint must begin a sustained run of cues and must either
    follow a real subtitle gap or represent a clear density increase. This
    prevents logos, translator notes, song lyrics, and cold-open dialogue from
    being treated as the end of the opening sequence.
    """
    events = [
        event
        for event in parse_subtitle_intro_events(item.path)
        if event[0] <= intro_detection_limit_seconds(duration_seconds) + 50
    ]
    if not events:
        return []

    forced_multiplier = 0.40 if is_forced_track_item(item) else 1.0
    merged = merge_subtitle_events(events)
    candidates: list[IntroDetectionCandidate] = []

    for index, current in enumerate(merged):
        current_start = current[0]
        if not intro_candidate_is_valid(current_start, duration_seconds):
            continue

        previous_end = merged[index - 1][1] if index > 0 else 0.0
        gap = max(0.0, current_start - previous_end)
        after_events = [
            event
            for event in merged
            if current_start <= event[0] < current_start + 55.0
        ]
        before_events = [
            event
            for event in merged
            if current_start - 55.0 <= event[0] < current_start
        ]
        after_count = len(after_events)
        before_count = len(before_events)
        after_coverage = sum(
            max(0.0, min(end, current_start + 55.0) - max(start, current_start))
            for start, end in after_events
        )

        # The first subtitle is not evidence by itself. It only becomes useful
        # when several subsequent cues prove that normal dialogue has started.
        sustained_dialogue = after_count >= 3 and after_coverage >= 5.0
        density_increase = after_count >= before_count + 2
        meaningful_gap = gap >= 18.0
        if not sustained_dialogue or not (meaningful_gap or density_increase):
            continue

        score = (
            34.0
            + min(gap, 90.0) * 0.28
            + min(after_count, 9) * 2.8
            + min(after_coverage, 24.0) * 0.55
            + max(0, after_count - before_count) * 1.8
            + intro_common_time_bonus(current_start)
        )
        source = "subtitle-gap" if gap >= 35.0 else "subtitle-dialogue"
        candidates.append(
            IntroDetectionCandidate(
                current_start,
                score * forced_multiplier,
                source,
            )
        )

    return top_intro_candidates(candidates, duration_seconds)


def intro_item_paths(
    items: list[TrackItem],
    *,
    track_type: int,
    media_kind: str,
    limit: int = 1,
) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for item in items:
        if track_type_value(item) != track_type and media_kind_from_path(item.path) != media_kind:
            continue
        key = path_identity_key(item.path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(item.path)
        if len(paths) >= limit:
            break
    return paths


def parse_ffmpeg_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def run_intro_ffmpeg_analysis(
    args: list[str],
    *,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> str:
    process = run_cancellable_capture(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    if process.returncode != 0:
        return ""
    return f"{process.stdout}\n{process.stderr}"


def intro_analysis_fps(video_fps: str) -> str:
    """Return an FFmpeg-compatible frame rate for raw elementary streams.

    Raw .h264/.h265 track files carry no container timing, so FFmpeg has to
    guess a frame rate on its own (commonly defaulting to 25fps) when it
    demuxes them. Every blackdetect/scenechange pts_time computed from that
    guess then drifts away from real playback time whenever the guess is
    wrong, which is why detected intro-end timestamps could land on the
    wrong second. Reuse normalize_video_fps() for validation, then strip its
    mkvmerge-style "fps" suffix since FFmpeg's -r wants a bare number or
    fraction (e.g. "23.976" or "24000/1001").
    """
    try:
        normalized = normalize_video_fps(video_fps)
    except UserVisibleError:
        return ""
    return normalized.removesuffix("fps")


def intro_ffmpeg_input_args(path: Path, video_fps: str = "") -> list[str]:
    """Build an FFmpeg input that also works for extracted raw video."""
    args = ["-fflags", "+genpts"]
    suffix = path.suffix.lower()
    is_raw_video = suffix in {".h264", ".avc", ".h265", ".hevc"}
    if suffix in {".h264", ".avc"}:
        args.extend(["-f", "h264"])
    elif suffix in {".h265", ".hevc"}:
        args.extend(["-f", "hevc"])
    if is_raw_video:
        fps = intro_analysis_fps(video_fps)
        if fps:
            # As an input option, -r tells FFmpeg to generate timestamps for
            # a constant frame rate instead of guessing one, giving accurate
            # pts_time for a stream that has no timing info of its own.
            args.extend(["-r", fps])
    args.extend(["-i", str(path)])
    return args


def blackdetect_intro_candidates(
    path: Path,
    duration_seconds: float = 0.0,
    *,
    video_fps: str = "",
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> list[IntroDetectionCandidate]:
    ffmpeg = ffmpeg_path()
    args = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-t",
        str(INTRO_DETECTION_WINDOW_SECONDS),
        *intro_ffmpeg_input_args(path, video_fps),
        "-map",
        "0:v:0?",
        "-an",
        "-sn",
        "-vf",
        "blackdetect=d=0.10:pic_th=0.98:pix_th=0.10",
        "-f",
        "null",
        "-",
    ]
    output = run_intro_ffmpeg_analysis(
        args,
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    candidates: list[IntroDetectionCandidate] = []
    for match in re.finditer(
        r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)\s+black_duration:(\d+(?:\.\d+)?)",
        output,
    ):
        black_start = parse_ffmpeg_float(match.group(1))
        black_end = parse_ffmpeg_float(match.group(2))
        black_duration = parse_ffmpeg_float(match.group(3))
        if black_start is None or black_end is None or black_duration is None:
            continue
        if black_start < 18.0 or black_duration < 0.10:
            continue
        if not intro_candidate_is_valid(black_end, duration_seconds):
            continue
        score = 46.0 + min(black_duration, 2.0) * 8.0 + intro_common_time_bonus(black_end)
        if black_duration >= 0.35:
            score += 8.0
        candidates.append(IntroDetectionCandidate(black_end, score, "blackdetect"))
    return top_intro_candidates(candidates, duration_seconds)


def scenechange_intro_candidates(
    path: Path,
    duration_seconds: float = 0.0,
    *,
    video_fps: str = "",
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> list[IntroDetectionCandidate]:
    """Find exact video cut timestamps that can refine another intro signal."""
    ffmpeg = ffmpeg_path()
    args = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-t",
        str(INTRO_DETECTION_WINDOW_SECONDS),
        *intro_ffmpeg_input_args(path, video_fps),
        "-map",
        "0:v:0?",
        "-an",
        "-sn",
        "-vf",
        "select='gt(scene,0.32)',showinfo",
        "-f",
        "null",
        "-",
    ]
    output = run_intro_ffmpeg_analysis(
        args,
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )

    candidates: list[IntroDetectionCandidate] = []
    seen_milliseconds: set[int] = set()
    for match in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", output):
        seconds = parse_ffmpeg_float(match.group(1))
        if seconds is None or not intro_candidate_is_valid(seconds, duration_seconds):
            continue
        key = int(round(seconds * 1000))
        if key in seen_milliseconds:
            continue
        seen_milliseconds.add(key)
        score = 27.0 + intro_common_time_bonus(seconds)
        candidates.append(IntroDetectionCandidate(seconds, score, "scenechange"))

    return candidates


def silencedetect_intro_candidates(
    path: Path,
    duration_seconds: float = 0.0,
    *,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> list[IntroDetectionCandidate]:
    ffmpeg = ffmpeg_path()
    args = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-t",
        str(INTRO_DETECTION_WINDOW_SECONDS),
        *intro_ffmpeg_input_args(path),
        "-map",
        "0:a:0?",
        "-vn",
        "-sn",
        "-dn",
        "-af",
        "silencedetect=noise=-35dB:d=0.45",
        "-f",
        "null",
        "-",
    ]
    output = run_intro_ffmpeg_analysis(
        args,
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    candidates: list[IntroDetectionCandidate] = []
    silence_start: float | None = None
    for line in output.splitlines():
        start_match = re.search(r"silence_start:\s*(\d+(?:\.\d+)?)", line)
        if start_match is not None:
            silence_start = parse_ffmpeg_float(start_match.group(1))
            continue
        end_match = re.search(
            r"silence_end:\s*(\d+(?:\.\d+)?)\s*\|\s*silence_duration:\s*(\d+(?:\.\d+)?)",
            line,
        )
        if end_match is None:
            continue
        silence_end = parse_ffmpeg_float(end_match.group(1))
        silence_duration = parse_ffmpeg_float(end_match.group(2))
        if silence_end is None or silence_duration is None:
            continue
        start = silence_start if silence_start is not None else silence_end - silence_duration
        if start < 18.0 or silence_duration < 0.45 or silence_duration > 12.0:
            continue
        if not intro_candidate_is_valid(silence_end, duration_seconds):
            continue
        score = 34.0 + min(silence_duration, 2.5) * 8.0 + intro_common_time_bonus(silence_end)
        if silence_duration >= 0.9:
            score += 7.0
        candidates.append(IntroDetectionCandidate(silence_end, score, "silencedetect"))
    return top_intro_candidates(candidates, duration_seconds)


def audio_rms_samples_for_intro(
    path: Path,
    *,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> list[tuple[float, float]]:
    ffmpeg = ffmpeg_path()
    args = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-t",
        str(INTRO_DETECTION_WINDOW_SECONDS),
        *intro_ffmpeg_input_args(path),
        "-map",
        "0:a:0?",
        "-vn",
        "-sn",
        "-dn",
        "-af",
        "aresample=8000,asetnsamples=n=8000:p=1,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f",
        "null",
        "-",
    ]
    output = run_intro_ffmpeg_analysis(
        args,
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    samples: list[tuple[float, float]] = []
    current_time: float | None = None
    for line in output.splitlines():
        time_match = re.search(r"pts_time:(\d+(?:\.\d+)?)", line)
        if time_match is not None:
            current_time = parse_ffmpeg_float(time_match.group(1))
            continue
        rms_match = re.search(
            r"lavfi\.astats\.Overall\.RMS_level=([-+]?(?:inf|\d+(?:\.\d+)?))",
            line,
            flags=re.IGNORECASE,
        )
        if rms_match is None or current_time is None:
            continue
        raw = rms_match.group(1).lower()
        rms = -90.0 if raw == "-inf" else parse_ffmpeg_float(raw)
        if rms is None:
            continue
        samples.append((current_time, max(-90.0, min(0.0, rms))))
    return samples


def mean_value(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def audio_energy_intro_candidates(
    path: Path,
    duration_seconds: float = 0.0,
    *,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> list[IntroDetectionCandidate]:
    samples = audio_rms_samples_for_intro(
        path,
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    if len(samples) < 80:
        return []

    candidates: list[IntroDetectionCandidate] = []
    limit = intro_detection_limit_seconds(duration_seconds)
    for seconds, _rms in samples:
        if seconds < INTRO_DETECTION_MIN_SECONDS or seconds > limit:
            continue
        before = [rms for time_value, rms in samples if seconds - 55 <= time_value < seconds - 5]
        after = [rms for time_value, rms in samples if seconds + 5 <= time_value < seconds + 55]
        if len(before) < 20 or len(after) < 20:
            continue
        before_mean = mean_value(before)
        after_mean = mean_value(after)
        before_active = sum(1 for value in before if value > -42.0) / len(before)
        after_active = sum(1 for value in after if value > -42.0) / len(after)
        drop = before_mean - after_mean
        active_drop = before_active - after_active
        if drop < 3.0 and active_drop < 0.18:
            continue
        score = (
            28.0
            + max(0.0, drop) * 3.2
            + max(0.0, active_drop) * 28.0
            + intro_common_time_bonus(seconds)
        )
        candidates.append(IntroDetectionCandidate(seconds, min(score, 58.0), "audio-energy"))

    return top_intro_candidates(candidates, duration_seconds)


def intro_candidate_group(candidate: IntroDetectionCandidate) -> str:
    if candidate.source.startswith("subtitle"):
        return "subtitle"
    if candidate.source in {"blackdetect", "scenechange"}:
        return "video"
    if candidate.source in {"silencedetect", "audio-energy"}:
        return "audio"
    return "other"


def intro_candidate_is_media_boundary(candidate: IntroDetectionCandidate) -> bool:
    return intro_candidate_group(candidate) in {"video", "audio"}


def intro_boundary_anchor(
    cluster: list[IntroDetectionCandidate],
) -> IntroDetectionCandidate:
    """Choose an actual cut/end timestamp rather than averaging clocks."""
    non_scene = [item for item in cluster if item.source != "scenechange"]
    center_items = non_scene or cluster
    center = sum(item.seconds * max(item.score, 1.0) for item in center_items) / sum(
        max(item.score, 1.0) for item in center_items
    )

    # blackdetect reports black_end and silencedetect reports silence_end; both
    # are already end boundaries. Prefer them over a scene cut at the *start*
    # of the transition, which would place the chapter slightly too early.
    priority = {
        "blackdetect": 0,
        "silencedetect": 1,
        "scenechange": 2,
        "subtitle-gap": 3,
        "subtitle-dialogue": 4,
        "audio-energy": 5,
    }
    return min(
        cluster,
        key=lambda item: (priority.get(item.source, 9), abs(item.seconds - center)),
    )


def select_intro_detection_candidate(
    candidates: list[IntroDetectionCandidate],
    duration_seconds: float = 0.0,
) -> IntroDetectionCandidate | None:
    valid = [
        candidate
        for candidate in candidates
        if intro_candidate_is_valid(candidate.seconds, duration_seconds)
    ]
    if not valid:
        return None

    clusters: list[list[IntroDetectionCandidate]] = []
    for candidate in sorted(valid, key=lambda item: item.seconds):
        placed = False
        for cluster in reversed(clusters):
            center = mean_value([item.seconds for item in cluster])
            if abs(candidate.seconds - center) <= INTRO_DETECTION_CLUSTER_SECONDS:
                cluster.append(candidate)
                placed = True
                break
            if candidate.seconds - center > INTRO_DETECTION_CLUSTER_SECONDS:
                break
        if not placed:
            clusters.append([candidate])

    scored: list[IntroDetectionCandidate] = []
    for cluster in clusters:
        group_best: dict[str, IntroDetectionCandidate] = {}
        for item in cluster:
            group = intro_candidate_group(item)
            current = group_best.get(group)
            if current is None or item.score > current.score:
                group_best[group] = item

        evidence_groups = {group for group in group_best if group != "other"}
        media_groups = evidence_groups & {"video", "audio"}

        # One black frame, one silence, or one RMS drop is not enough. A valid
        # boundary needs independent agreement from at least two evidence
        # groups, one of which must come from the media itself.
        if len(evidence_groups) < 2 or not media_groups:
            continue

        ordered = sorted(
            (item.score for group, item in group_best.items() if group != "other"),
            reverse=True,
        )
        score = ordered[0]
        if len(ordered) > 1:
            score += ordered[1] * 0.48
        if len(ordered) > 2:
            score += ordered[2] * 0.24
        score += (len(evidence_groups) - 1) * 8.0

        cluster_time = mean_value([item.seconds for item in cluster])
        if 45.0 <= cluster_time <= 180.0:
            score += 8.0
        elif cluster_time > 210.0:
            score -= 14.0

        anchor = intro_boundary_anchor(cluster)
        scored.append(
            IntroDetectionCandidate(
                anchor.seconds,
                score,
                "+".join(sorted({item.source for item in cluster})),
            )
        )

    if not scored:
        return None

    strongest = max(candidate.score for candidate in scored)
    threshold = max(INTRO_DETECTION_MIN_CONFIDENCE, strongest - 10.0)
    plausible = [candidate for candidate in scored if candidate.score >= threshold]
    if not plausible:
        return None

    # The intro end is normally the first strongly corroborated transition.
    # Choosing the earliest near-best cluster prevents a later commercial-like
    # silence or dark scene from replacing the real opening boundary.
    return min(plausible, key=lambda candidate: candidate.seconds)


def detect_intro_chapter_start_seconds(
    items: list[TrackItem],
    duration_seconds: float = 0.0,
    *,
    analysis_source: Path | None = None,
    video_fps: str = "",
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> float:
    candidates: list[IntroDetectionCandidate] = []

    # Subtitle timestamps are collected only as supporting hints.  Media
    # analysis is always performed, even when subtitles exist.
    for item in items:
        if track_type_value(item) == 2 or media_kind_from_path(item.path) == "subtitle":
            candidates.extend(subtitle_intro_candidates(item, duration_seconds))

    source = analysis_source if analysis_source is not None and analysis_source.is_file() else None
    if source is not None:
        # In batch mode this is the original MKV/MP4. It preserves exact
        # timestamps and avoids guessing from elementary .h264/.h265 streams.
        audio_paths = [source]
        video_paths = [source]
    else:
        audio_paths = intro_item_paths(items, track_type=0, media_kind="audio")
        video_paths = intro_item_paths(items, track_type=1, media_kind="video")

    try:
        for path in video_paths:
            candidates.extend(
                blackdetect_intro_candidates(
                    path,
                    duration_seconds,
                    video_fps=video_fps,
                    cancel_event=cancel_event,
                    register_process=register_process,
                    unregister_process=unregister_process,
                )
            )
        for path in audio_paths:
            candidates.extend(
                silencedetect_intro_candidates(
                    path,
                    duration_seconds,
                    cancel_event=cancel_event,
                    register_process=register_process,
                    unregister_process=unregister_process,
                )
            )
            candidates.extend(
                audio_energy_intro_candidates(
                    path,
                    duration_seconds,
                    cancel_event=cancel_event,
                    register_process=register_process,
                    unregister_process=unregister_process,
                )
            )

        # Scene cuts are numerous, so use them only when they are close to an
        # independently detected subtitle/audio/video signal.  This refines an
        # approximate energy transition to the exact video frame boundary.
        reference_candidates = [
            candidate
            for candidate in candidates
            if intro_candidate_is_media_boundary(candidate)
        ]
        for path in video_paths:
            for scene_candidate in scenechange_intro_candidates(
                path,
                duration_seconds,
                video_fps=video_fps,
                cancel_event=cancel_event,
                register_process=register_process,
                unregister_process=unregister_process,
            ):
                if any(
                    abs(scene_candidate.seconds - reference.seconds)
                    <= INTRO_DETECTION_CLUSTER_SECONDS
                    for reference in reference_candidates
                ):
                    candidates.append(scene_candidate)
    except OperationCancelled:
        raise
    except UserVisibleError:
        pass

    selected = select_intro_detection_candidate(candidates, duration_seconds)
    return selected.seconds if selected is not None else 0.0


def write_auto_chapters_file(
    path: Path,
    options: ChapterOptions,
    duration_seconds: float,
    intro_start_seconds: float = 0.0,
) -> Path:
    name = options.name.strip()
    if not name:
        raise UserVisibleError(ui_text("error_auto_chapter_name_required"))

    interval_minutes = parse_positive_minutes(
        options.interval_minutes,
        ui_text("field_chapter_interval"),
    )
    start_number = parse_chapter_start_number(options.start_number)
    end_minutes = parse_optional_positive_minutes(
        options.end_minutes,
        ui_text("field_chapter_end"),
    )
    if end_minutes is None:
        if duration_seconds <= 0:
            raise UserVisibleError(ui_text("error_auto_chapter_end_required"))
        end_minutes = duration_seconds / 60

    interval_seconds = interval_minutes * 60
    end_seconds = end_minutes * 60
    fallback_start_seconds = interval_seconds * start_number
    if intro_start_seconds > 0:
        # The start number controls the chapter label only.  The first generated
        # chapter must be placed exactly at the detected end of the intro.
        current_seconds = intro_start_seconds
    else:
        current_seconds = fallback_start_seconds

    if current_seconds > end_seconds and intro_start_seconds > 0:
        current_seconds = fallback_start_seconds
    if current_seconds > end_seconds:
        raise UserVisibleError(ui_text("error_chapter_start_after_end"))

    lines: list[str] = []
    chapter_number = start_number
    while current_seconds <= end_seconds + 1e-9:
        marker = f"CHAPTER{chapter_number:02d}"
        lines.append(f"{marker}={format_chapter_timestamp(current_seconds)}")
        lines.append(f"{marker}NAME= {name} {chapter_number}")
        chapter_number += 1
        current_seconds += interval_seconds

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def resolve_chapter_path(
    config: dict[str, Any],
    media_dir: Path,
    items: list[TrackItem],
    options: ChapterOptions | None,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> tuple[Path | None, list[str]]:
    global_config = config.get("global", {})
    chapters_name = basename_from_config_path(str(global_config.get("chapters", "chapters.txt")))
    if not chapters_name:
        chapters_name = "chapters.txt"

    chapters_path = media_dir / chapters_name
    if chapters_path.exists():
        return chapters_path, []

    if options is not None and options.enabled:
        # Bitiş dakikası elle girildiyse büyük video dosyasını mkvmerge --identify ile tarama.
        # Bu ilk mux öncesi uzun beklemeyi engeller.
        if str(options.end_minutes or "").strip():
            duration_seconds = 0.0
        else:
            duration_seconds = detect_media_duration_seconds(
                items,
                cancel_event=cancel_event,
                register_process=register_process,
                unregister_process=unregister_process,
            )

        intro_start_seconds = 0.0
        if options.detect_intro:
            intro_start_seconds = detect_intro_chapter_start_seconds(
                items,
                duration_seconds,
                analysis_source=options.analysis_source,
                video_fps=options.video_fps,
                cancel_event=cancel_event,
                register_process=register_process,
                unregister_process=unregister_process,
            )

        return write_auto_chapters_file(
            chapters_path,
            options,
            duration_seconds,
            intro_start_seconds,
        ), []

    return None, [chapters_name]


def resolve_global_tags_path(
    config: dict[str, Any],
    media_dir: Path,
) -> tuple[Path | None, list[str]]:
    global_config = config.get("global", {})
    configured_value = str(global_config.get("globalTags") or "").strip()
    configured = bool(configured_value)
    tags_name = basename_from_config_path(configured_value) if configured else "tags.xml"
    if not tags_name:
        tags_name = "tags.xml"

    tags_path = media_dir / tags_name
    if tags_path.exists():
        return tags_path, []

    return None, [tags_name] if configured else []


def build_mkvmerge_args(
    config: dict[str, Any],
    media_dir: Path,
    output_path: Path,
    title: str,
    include_extra_subtitles: bool,
    video_fps: str = "",
    chapter_options: ChapterOptions | None = None,
    audio_language_order: str = "",
    subtitle_language_order: str = "",
    tag_language: str = "",
    additional_tracks: list[AdditionalMuxTrack] | None = None,
    track_order_keys: list[str] | None = None,
    language_overrides: dict[str, str] | None = None,
    delay_overrides: dict[str, str] | None = None,
    append_overrides: dict[str, tuple[Path, ...]] | None = None,
    excluded_track_keys: set[str] | None = None,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> tuple[list[str], list[str]]:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled(ui_text("log_operation_cancelled"))
    _unknown_language = normalise_language(tag_language) if tag_language else MUX_UNKNOWN_LANGUAGE
    mkvmerge = third_party_tool_path("mkvmerge")
    if not mkvmerge:
        raise UserVisibleError(ui_text("error_mkvmerge_missing"))

    items, missing_optional = prepare_mux_track_items(
        config,
        media_dir,
        include_extra_subtitles,
        _unknown_language,
        additional_tracks,
        language_overrides,
        delay_overrides,
        append_overrides,
        excluded_track_keys,
    )
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled(ui_text("log_operation_cancelled"))
    if not items:
        raise UserVisibleError(ui_text("error_mux_no_files"))
    apply_video_fps_override(items, video_fps)
    ordered = apply_default_track_preferences(
        config,
        items,
        audio_language_order,
        subtitle_language_order,
    )
    ordered = apply_custom_track_order(ordered, list(track_order_keys or []))

    attachments, missing_attachments = discover_attachments(config, media_dir)
    missing_optional.extend(missing_attachments)
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled(ui_text("log_operation_cancelled"))

    args = [mkvmerge, "--output", str(output_path)]
    if title:
        args.extend(["--title", title])

    global_config = config.get("global", {})
    tags_path, missing_tags = resolve_global_tags_path(config, media_dir)
    if tags_path is not None:
        args.extend(["--global-tags", str(tags_path)])
    else:
        missing_optional.extend(missing_tags)

    chapters_path, missing_chapters = resolve_chapter_path(
        config,
        media_dir,
        items,
        chapter_options,
        cancel_event=cancel_event,
        register_process=register_process,
        unregister_process=unregister_process,
    )
    if chapters_path is not None:
        chapter_language = (
            normalise_language(tag_language)
            if tag_language
            else str(global_config.get("chapterLanguage") or "")
        )
        if chapter_language:
            args.extend(["--chapter-language", chapter_language])
        args.extend(["--chapters", str(chapters_path)])
    else:
        missing_optional.extend(missing_chapters)

    if global_config.get("stopAfterVideoEnds"):
        args.append("--stop-after-video-ends")

    if ordered:
        track_order = ",".join(f"{item.file_id}:0" for item in ordered)
        args.extend(["--track-order", track_order])

    append_mappings = append_to_mappings(items)
    if append_mappings:
        args.extend(["--append-to", ",".join(append_mappings)])

    for attachment in attachments:
        if attachment["description"]:
            args.extend(["--attachment-description", attachment["description"]])
        args.extend(["--attachment-mime-type", attachment["mime"]])
        args.extend(["--attachment-name", attachment["name"]])
        args.extend(["--attach-file", str(attachment["path"])])

    for item in items:
        append_source_options(args, item)

    return args, sorted(set(missing_optional))


def rebuild_numbered_section(
    original: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    rebuilt = {
        key: copy.deepcopy(value)
        for key, value in original.items()
        if not key.isdigit() and key != "numberOfEntries"
    }
    for index, entry in enumerate(entries):
        rebuilt[str(index)] = entry
    rebuilt["numberOfEntries"] = len(entries)
    return rebuilt


def write_generated_config(
    config: dict[str, Any],
    media_dir: Path,
    output_path: Path,
    title: str,
    include_extra_subtitles: bool,
    video_fps: str = "",
    chapter_options: ChapterOptions | None = None,
    audio_language_order: str = "",
    subtitle_language_order: str = "",
    tag_language: str = "",
    additional_tracks: list[AdditionalMuxTrack] | None = None,
    track_order_keys: list[str] | None = None,
    language_overrides: dict[str, str] | None = None,
    delay_overrides: dict[str, str] | None = None,
    append_overrides: dict[str, tuple[Path, ...]] | None = None,
    excluded_track_keys: set[str] | None = None,
) -> Path:
    _unknown_language = normalise_language(tag_language) if tag_language else MUX_UNKNOWN_LANGUAGE
    items, _ = prepare_mux_track_items(
        config,
        media_dir,
        include_extra_subtitles,
        _unknown_language,
        additional_tracks,
        language_overrides,
        delay_overrides,
        append_overrides,
        excluded_track_keys,
    )
    apply_video_fps_override(items, video_fps)
    ordered = apply_default_track_preferences(
        config,
        items,
        audio_language_order,
        subtitle_language_order,
    )
    ordered = apply_custom_track_order(ordered, list(track_order_keys or []))
    generated = copy.deepcopy(config)
    generated.setdefault("global", {})
    generated["global"]["destination"] = str(output_path)
    generated["global"]["destinationAuto"] = str(output_path)
    generated["global"]["title"] = title
    if tag_language:
        generated["global"]["chapterLanguage"] = normalise_language(tag_language)

    chapter_path, _ = resolve_chapter_path(
        config,
        media_dir,
        items,
        chapter_options,
    )
    generated["global"]["chapters"] = str(chapter_path) if chapter_path is not None else ""
    tags_path, _ = resolve_global_tags_path(config, media_dir)
    generated["global"]["globalTags"] = str(tags_path) if tags_path is not None else ""

    input_section = generated.setdefault("input", {})
    input_section["firstInputFileName"] = str(items[0].path) if items else ""
    input_section["files"] = rebuild_numbered_section(
        input_section.get("files", {}),
        [copy.deepcopy(item.entry) for item in items],
    )
    input_section["trackOrder"] = [
        item.object_id for item in ordered if item.object_id is not None
    ]

    attachments = []
    for attachment in discover_attachments(config, media_dir)[0]:
        attachments.append(
            {
                "MIMEType": attachment["mime"],
                "description": attachment["description"],
                "fileName": str(attachment["path"]),
                "name": attachment["name"],
                "style": 1,
            }
        )
    input_section["attachments"] = rebuild_numbered_section(
        input_section.get("attachments", {}),
        attachments,
    )

    generated_path = output_path.with_suffix(".generated.mtxcfg")
    generated_path.write_text(
        json.dumps(generated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return generated_path


class TMDBClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise ValueError("invalid TMDB API path")
        params = dict(params)
        params["api_key"] = self.api_key
        query = urllib.parse.urlencode(params)
        url = f"{TMDB_API_BASE}{path}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "g-tmce/1.0"},
        )
        try:
            with safe_urlopen(
                request,
                timeout=self.timeout,
                allowed_hosts=frozenset({"api.themoviedb.org"}),
            ) as response:
                return json.loads(read_response_limited(response, MAX_JSON_RESPONSE_BYTES).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
                message = payload.get("status_message") or body
            except json.JSONDecodeError:
                message = body or str(exc)
            raise UserVisibleError(
                ui_text("error_tmdb_request_failed", code=exc.code, message=message)
            ) from exc
        except urllib.error.URLError as exc:
            raise UserVisibleError(
                ui_text("error_tmdb_connection_failed", reason=exc.reason)
            ) from exc

    def search(self, media_type: str, query: str, year: str) -> list[dict[str, Any]]:
        path = f"/search/{media_type}"
        params = {
            "query": query,
            "include_adult": "false",
            "language": "en-US",
            "page": "1",
        }
        if year:
            if media_type == "movie":
                params["year"] = year
                params["primary_release_year"] = year
            else:
                params["first_air_date_year"] = year

        payload = self.get_json(path, params)
        results = payload.get("results") or []
        if results or not year:
            return results

        fallback_params = dict(params)
        fallback_params.pop("year", None)
        fallback_params.pop("primary_release_year", None)
        fallback_params.pop("first_air_date_year", None)
        return self.get_json(path, fallback_params).get("results") or []

    def search_multi(self, query: str, language: str) -> list[dict[str, Any]]:
        payload = self.get_json(
            "/search/multi",
            {
                "query": query,
                "include_adult": "false",
                "language": language,
                "page": "1",
            },
        )
        results: list[dict[str, Any]] = []
        for result in payload.get("results") or []:
            media_type = str(result.get("media_type") or "")
            if media_type not in TMDB_MEDIA_TYPES:
                continue
            if not result.get("id") or not result_title(result):
                continue
            results.append(result)
        return results

    def download_bytes(self, file_path: str) -> bytes:
        if not file_path.startswith("/") or file_path.startswith("//") or "://" in file_path:
            raise ValueError("invalid TMDB image path")
        url = f"{TMDB_IMAGE_BASE}{file_path}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "g-tmce/1.0"},
        )
        try:
            with safe_urlopen(
                request,
                timeout=self.timeout,
                allowed_hosts=frozenset({"image.tmdb.org"}),
            ) as response:
                return read_response_limited(response, MAX_IMAGE_RESPONSE_BYTES)
        except urllib.error.URLError as exc:
            raise UserVisibleError(
                ui_text("error_image_download_failed", reason=exc.reason)
            ) from exc


class OpenSubtitlesClient:
    def __init__(self, api_key: str, username: str = "", password: str = "", timeout: int = 30) -> None:
        self.api_key = api_key
        self.username = username
        self.password = password
        self.timeout = timeout

    def headers(self, token: str = "", *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Api-Key": self.api_key,
            "User-Agent": OPENSUBTITLES_USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def api_url(self, path: str, params: dict[str, str] | None = None, base_url: str = "") -> str:
        base = normalise_opensubtitles_base_url(base_url)
        query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value != ""})
        return f"{base}{path}" + (f"?{query}" if query else "")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        token: str = "",
        base_url: str = "",
    ) -> dict[str, Any]:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.api_url(path, params, base_url),
            data=data,
            headers=self.headers(token, json_body=payload is not None),
            method=method,
        )
        try:
            with safe_urlopen(
                request,
                timeout=self.timeout,
                allowed_hosts=frozenset({"opensubtitles.com"}),
                allowed_suffixes=(OPENSUBTITLES_ALLOWED_HOST_SUFFIX,),
            ) as response:
                value = json.loads(read_response_limited(response, MAX_JSON_RESPONSE_BYTES).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = opensubtitles_error_message(body) or str(exc)
            raise OpenSubtitlesRequestError(exc.code, message) from exc
        except urllib.error.URLError as exc:
            raise UserVisibleError(
                ui_text("error_subtitle_connection_failed", reason=exc.reason)
            ) from exc
        except json.JSONDecodeError as exc:
            raise UserVisibleError(
                ui_text("error_subtitle_request_failed", code="JSON", message=exc)
            ) from exc
        if not isinstance(value, dict):
            raise UserVisibleError(
                ui_text("error_subtitle_request_failed", code="JSON", message="response is not an object")
            )
        return value

    def login(self) -> tuple[str, str]:
        if not self.username.strip() or not self.password:
            raise UserVisibleError(ui_text("error_subtitle_credentials_required"))
        payload = self.request_json(
            "POST",
            "/login",
            payload={
                "username": self.username.strip(),
                "password": self.password,
            },
        )
        token = str(payload.get("token") or "").strip()
        base_url = str(payload.get("base_url") or "").strip()
        if not token:
            raise UserVisibleError(
                ui_text("error_subtitle_request_failed", code="login", message="token missing")
            )
        return token, base_url

    def search(
        self,
        target: SubtitleSearchTarget,
        target_index: int,
        language: str,
        query: str,
        *,
        limit: int,
    ) -> list[SubtitleResult]:
        query = query.strip()
        search_target = (
            replace(target, query=query, source_name=query, output_stem=query)
            if query
            else target
        )
        results: list[SubtitleResult] = []
        seen_file_ids: set[int] = set()
        request_succeeded = False
        not_enough_parameters_error: OpenSubtitlesRequestError | None = None
        for params in opensubtitles_search_param_variants(search_target, language, query):
            try:
                payload = self.request_json("GET", "/subtitles", params=params)
            except OpenSubtitlesRequestError as exc:
                if opensubtitles_error_is_not_enough_parameters(exc):
                    not_enough_parameters_error = exc
                    continue
                raise
            request_succeeded = True
            data = payload.get("data") or []
            if not isinstance(data, list):
                continue

            for item in data:
                if not isinstance(item, dict):
                    continue
                attributes = item.get("attributes") or {}
                if not isinstance(attributes, dict):
                    continue
                if not opensubtitles_result_matches_target(search_target, attributes):
                    continue
                files = attributes.get("files") or []
                if not isinstance(files, list):
                    continue
                for file_info in files:
                    if not isinstance(file_info, dict):
                        continue
                    try:
                        file_id = int(file_info.get("file_id"))
                    except (TypeError, ValueError):
                        continue
                    if file_id in seen_file_ids:
                        continue
                    seen_file_ids.add(file_id)
                    key = f"{target_index}:{attributes.get('subtitle_id') or item.get('id')}:{file_id}:{len(results)}"
                    results.append(
                        SubtitleResult(
                            key=key,
                            target_index=target_index,
                            subtitle_id=str(attributes.get("subtitle_id") or item.get("id") or ""),
                            file_id=file_id,
                            language=str(attributes.get("language") or language),
                            release=str(attributes.get("release") or ""),
                            file_name=str(file_info.get("file_name") or ""),
                            fps=opensubtitles_fps_text(attributes.get("fps")),
                            downloads=int(attributes.get("download_count") or attributes.get("new_download_count") or 0),
                            forced=opensubtitles_result_is_forced(attributes, file_info),
                            hearing_impaired=bool(attributes.get("hearing_impaired")),
                            from_trusted=bool(attributes.get("from_trusted")),
                            machine_translated=bool(attributes.get("machine_translated")),
                            ai_translated=bool(attributes.get("ai_translated")),
                            url=str(attributes.get("url") or ""),
                        )
                    )
                    if len(results) >= limit:
                        return results
        if not request_succeeded and not_enough_parameters_error is not None:
            raise not_enough_parameters_error
        return results

    def download_link(
        self,
        result: SubtitleResult,
        token: str,
        base_url: str,
        destination_name: str,
        out_fps: float | None,
    ) -> str:
        payload: dict[str, Any] = {
            "file_id": result.file_id,
            "sub_format": "srt",
            "file_name": destination_name,
        }
        in_fps = parse_fps_number(result.fps)
        if in_fps is not None and out_fps is not None:
            payload["in_fps"] = in_fps
            payload["out_fps"] = out_fps
        response = self.request_json(
            "POST",
            "/download",
            payload=payload,
            token=token,
            base_url=base_url,
        )
        link = str(response.get("link") or "").strip()
        if not link:
            raise UserVisibleError(ui_text("error_subtitle_download_link_missing"))
        return link

    def download_bytes(self, link: str) -> tuple[bytes, str]:
        validate_https_url(
            link,
            allowed_hosts=frozenset({"opensubtitles.com"}),
            allowed_suffixes=(OPENSUBTITLES_ALLOWED_HOST_SUFFIX,),
        )
        request = urllib.request.Request(
            link,
            headers={"User-Agent": OPENSUBTITLES_USER_AGENT},
        )
        try:
            with safe_urlopen(
                request,
                timeout=max(self.timeout, 60),
                allowed_hosts=frozenset({"opensubtitles.com"}),
                allowed_suffixes=(OPENSUBTITLES_ALLOWED_HOST_SUFFIX,),
            ) as response:
                return read_response_limited(response, MAX_SUBTITLE_RESPONSE_BYTES), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = opensubtitles_error_message(body) or str(exc)
            raise UserVisibleError(
                ui_text("error_subtitle_request_failed", code=exc.code, message=message)
            ) from exc
        except urllib.error.URLError as exc:
            raise UserVisibleError(
                ui_text("error_subtitle_connection_failed", reason=exc.reason)
            ) from exc


def normalise_opensubtitles_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        return OPENSUBTITLES_API_BASE
    if "://" not in value:
        value = f"https://{value}"
    parsed = urllib.parse.urlsplit(value)
    validate_https_url(
        value,
        allowed_hosts=frozenset({"opensubtitles.com"}),
        allowed_suffixes=(OPENSUBTITLES_ALLOWED_HOST_SUFFIX,),
    )
    if parsed.query or parsed.fragment:
        raise ValueError("OpenSubtitles base URL must not contain a query or fragment")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.rstrip("/")
    if path and path != "/api/v1":
        raise ValueError("unexpected OpenSubtitles API base path")
    return f"https://{hostname}/api/v1"


def opensubtitles_error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if isinstance(payload, dict):
        for key in ("message", "error"):
            value = payload.get(key)
            if value:
                return str(value)
        errors = payload.get("errors")
        if isinstance(errors, list):
            return "; ".join(str(error) for error in errors)
    return body.strip()


def opensubtitles_error_is_not_enough_parameters(error: OpenSubtitlesRequestError) -> bool:
    return str(error.code) == "400" and "not enough parameter" in error.message.lower()


def normalise_subtitle_language(language: str) -> str:
    raw = str(language or "").strip().lower()
    if raw in {"pt-br", "pt-pt", "zh-cn", "zh-tw"}:
        return raw
    return normalise_language(raw or "en")


def subtitle_filename_language_code(language: str) -> str:
    code = normalise_subtitle_language(language)
    return SUBTITLE_FILENAME_LANGUAGE_CODES.get(code, code)


def subtitle_descriptor_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(token for token in re.split(r"[._\-\s\[\]\(\)]+", value.lower()) if token)
    return tokens


def opensubtitles_result_is_forced(
    attributes: dict[str, Any],
    file_info: dict[str, Any],
) -> bool:
    if bool(attributes.get("foreign_parts_only")):
        return True
    tokens = subtitle_descriptor_tokens(
        str(attributes.get("release") or ""),
        str(file_info.get("file_name") or ""),
        str(attributes.get("comments") or ""),
    )
    return bool(tokens & {"forced", "force", "forc", "foreign", "foreignparts"})


def clean_numeric_id(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def opensubtitles_feature_details(attributes: dict[str, Any]) -> dict[str, Any]:
    feature = attributes.get("feature_details") or {}
    return feature if isinstance(feature, dict) else {}


def opensubtitles_feature_id_values(feature: dict[str, Any], *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        value = clean_numeric_id(feature.get(key))
        if value:
            values.add(value)
    return values


def opensubtitles_result_id_matches_target(
    target: SubtitleSearchTarget,
    feature: dict[str, Any],
) -> bool | None:
    target_tmdb = clean_numeric_id(target.tmdb_id)
    target_imdb = clean_numeric_id(target.imdb_id)

    if target.media_type == "tv" and target.episode_ref is not None:
        feature_tmdb_values = opensubtitles_feature_id_values(feature, "parent_tmdb_id")
        if not feature_tmdb_values:
            feature_tmdb_values = opensubtitles_feature_id_values(feature, "tmdb_id")
        feature_imdb_values = opensubtitles_feature_id_values(feature, "parent_imdb_id")
        if not feature_imdb_values:
            feature_imdb_values = opensubtitles_feature_id_values(feature, "imdb_id")
    else:
        feature_tmdb_values = opensubtitles_feature_id_values(feature, "tmdb_id")
        feature_imdb_values = opensubtitles_feature_id_values(feature, "imdb_id")

    if target_tmdb and feature_tmdb_values:
        return target_tmdb in feature_tmdb_values
    if target_imdb and feature_imdb_values:
        return target_imdb in feature_imdb_values

    if (target_tmdb or target_imdb) and (feature_tmdb_values or feature_imdb_values):
        return False
    return None


def opensubtitles_year_values(attributes: dict[str, Any], feature: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for value in (
        feature.get("year"),
        feature.get("movie_name"),
        feature.get("title"),
        feature.get("parent_title"),
        attributes.get("release"),
    ):
        values.update(re.findall(r"(?:19|20)\d{2}", str(value or "")))
    return values


def strip_year_text(value: str, year: str) -> str:
    if not year:
        return value
    return re.sub(rf"(?:^|[\s._\-\(\)\[\]]){re.escape(year)}(?:$|[\s._\-\(\)\[\]])", " ", value)


def opensubtitles_text_values(attributes: dict[str, Any], feature: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in (
        feature.get("movie_name"),
        feature.get("title"),
        feature.get("parent_title"),
        attributes.get("release"),
    ):
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return values


def opensubtitles_result_text_matches_target(
    target: SubtitleSearchTarget,
    attributes: dict[str, Any],
    feature: dict[str, Any],
) -> bool:
    target_values = [
        value
        for value in (target.query, target.source_name, target.output_stem)
        if str(value or "").strip()
    ]
    if not target_values:
        return True

    target_year = str(target.year or "").strip()
    if target_year:
        years = opensubtitles_year_values(attributes, feature)
        if years and target_year not in years:
            return False

    candidate_keys = [
        normalise_title_for_match(value)
        for value in opensubtitles_text_values(attributes, feature)
    ]
    candidate_keys = [value for value in candidate_keys if value]
    if not candidate_keys:
        return True

    for value in target_values:
        full_key = normalise_title_for_match(value)
        base_key = normalise_title_for_match(strip_year_text(value, target_year))
        keys = [key for key in (full_key, base_key) if key]
        for key in keys:
            for candidate in candidate_keys:
                if candidate == key or candidate.startswith(key) or key.startswith(candidate):
                    return True
                if target_year and key in candidate:
                    return True
    return False


def opensubtitles_result_matches_target(
    target: SubtitleSearchTarget,
    attributes: dict[str, Any],
) -> bool:
    feature = opensubtitles_feature_details(attributes)
    id_match = opensubtitles_result_id_matches_target(target, feature)
    if id_match is not None:
        return id_match
    return opensubtitles_result_text_matches_target(target, attributes, feature)


def opensubtitles_search_params(
    target: SubtitleSearchTarget,
    language: str,
    query: str,
) -> dict[str, str]:
    params = opensubtitles_base_search_params(language, target)
    query = query.strip()
    if query:
        params["query"] = query
    if target.media_type == "tv" and target.episode_ref is not None:
        params["season_number"] = str(target.episode_ref.season)
        params["episode_number"] = str(target.episode_ref.episode)
        if target.tmdb_id:
            params["parent_tmdb_id"] = target.tmdb_id
        if target.imdb_id:
            params["parent_imdb_id"] = clean_imdb_id_number(target.imdb_id)
    elif target.tmdb_id:
        params["tmdb_id"] = target.tmdb_id
    elif target.imdb_id:
        params["imdb_id"] = clean_imdb_id_number(target.imdb_id)
    return params


def clean_imdb_id_number(value: str) -> str:
    return str(value or "").strip().lower().removeprefix("tt")


def opensubtitles_episode_params(target: SubtitleSearchTarget) -> dict[str, str]:
    if target.media_type != "tv" or target.episode_ref is None:
        return {}
    return {
        "season_number": str(target.episode_ref.season),
        "episode_number": str(target.episode_ref.episode),
    }


def opensubtitles_id_params(target: SubtitleSearchTarget, *, prefer_imdb: bool = False) -> dict[str, str]:
    params: dict[str, str] = {}
    imdb_id = clean_imdb_id_number(target.imdb_id)
    if target.media_type == "tv" and target.episode_ref is not None:
        if prefer_imdb and imdb_id:
            params.update(opensubtitles_episode_params(target))
            params["parent_imdb_id"] = imdb_id
        elif target.tmdb_id:
            params.update(opensubtitles_episode_params(target))
            params["parent_tmdb_id"] = target.tmdb_id
        elif imdb_id:
            params.update(opensubtitles_episode_params(target))
            params["parent_imdb_id"] = imdb_id
        return params

    if prefer_imdb and imdb_id:
        params["imdb_id"] = imdb_id
    elif target.tmdb_id:
        params["tmdb_id"] = target.tmdb_id
    elif imdb_id:
        params["imdb_id"] = imdb_id
    return params


def opensubtitles_type_param(target: SubtitleSearchTarget | None) -> str:
    if target is None:
        return ""
    if target.media_type == "movie":
        return "movie"
    if target.media_type == "tv" and target.episode_ref is not None:
        return "episode"
    return ""


def opensubtitles_base_search_params(
    language: str,
    target: SubtitleSearchTarget | None = None,
) -> dict[str, str]:
    params = {
        "languages": normalise_subtitle_language(language),
        "order_by": "download_count",
        "order_direction": "desc",
        "per_page": "60",
    }
    type_param = opensubtitles_type_param(target)
    if type_param:
        params["type"] = type_param
    return params


def add_unique_search_params(
    variants: list[dict[str, str]],
    seen: set[tuple[tuple[str, str], ...]],
    params: dict[str, str],
) -> None:
    cleaned = {key: value for key, value in params.items() if str(value).strip()}
    key = tuple(sorted(cleaned.items()))
    if key in seen:
        return
    variants.append(cleaned)
    seen.add(key)


def opensubtitles_query_candidates(target: SubtitleSearchTarget, query: str) -> list[str]:
    explicit_query = re.sub(r"\s+", " ", str(query or "").strip())
    base_candidates: list[str] = []
    source_values = (explicit_query,) if explicit_query else (target.query, target.source_name, target.output_stem)
    for value in source_values:
        value = re.sub(r"\s+", " ", str(value or "").strip())
        if value and value not in base_candidates:
            base_candidates.append(value)

    candidates: list[str] = []
    if target.year:
        for value in base_candidates:
            if target.year not in value:
                with_year = f"{value} {target.year}"
                if with_year not in candidates:
                    candidates.append(with_year)
    for value in base_candidates:
        if value not in candidates:
            candidates.append(value)
    return candidates


def opensubtitles_search_param_variants(
    target: SubtitleSearchTarget,
    language: str,
    query: str,
) -> list[dict[str, str]]:
    base = opensubtitles_base_search_params(language, target)
    variants: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    queries = opensubtitles_query_candidates(target, query)
    episode_params = opensubtitles_episode_params(target)
    has_id_variants = False

    for id_params in (
        opensubtitles_id_params(target),
        opensubtitles_id_params(target, prefer_imdb=True),
    ):
          if not id_params:
              continue
          has_id_variants = True
          for candidate in queries[:2]:
              add_unique_search_params(variants, seen, {**base, **id_params, "query": candidate})
          add_unique_search_params(variants, seen, {**base, **id_params})

    query_limit = 2 if has_id_variants else len(queries)
    for candidate in queries[:query_limit]:
        if episode_params:
            add_unique_search_params(variants, seen, {**base, **episode_params, "query": candidate})
        add_unique_search_params(variants, seen, {**base, "query": candidate})
    return variants


def opensubtitles_fps_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return format_fps_value(number)


def parse_fps_number(value: str) -> float | None:
    raw = str(value or "").strip().lower().removesuffix("fps").strip().replace(",", ".")
    if not raw:
        return None
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        try:
            return float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def subtitle_target_label(target: SubtitleSearchTarget) -> str:
    if target.episode_ref is not None:
        return episode_code(target.episode_ref)
    return target.media_dir.name


def subtitle_flags(result: SubtitleResult) -> str:
    flags = []
    if result.forced:
        flags.append(ui_text("value_subtitle_flag_forced"))
    if result.hearing_impaired:
        flags.append(ui_text("value_subtitle_flag_hi"))
    if result.from_trusted:
        flags.append(ui_text("value_subtitle_flag_trusted"))
    if result.machine_translated:
        flags.append(ui_text("value_subtitle_flag_machine"))
    if result.ai_translated:
        flags.append(ui_text("value_subtitle_flag_ai"))
    return ", ".join(flags)


def subtitle_output_stem_for_dir(media_dir: Path, fallback: str) -> str:
    for path in discover_media_track_paths(media_dir):
        if media_kind_from_path(path) == "video":
            return safe_filename_stem(path.stem)
    return safe_filename_stem(fallback or media_dir.name or "subtitle")


def subtitle_query_from_settings(settings: AppSettings) -> str:
    return first_non_empty(
        settings.mkv_title,
        release_output_title_from_folder(settings.media_dir),
        settings.output_path.stem,
        settings.media_dir.name,
    )


def subtitle_lookup_metadata_from_tmdb(settings: AppSettings) -> SubtitleLookupMetadata:
    if not settings.api_key:
        return SubtitleLookupMetadata()
    tmdb_id = settings.tmdb_id.strip()
    if not tmdb_id.isdigit():
        tmdb_id, _title, _found_year, _query = find_tmdb_match_from_folder(settings)
    client = TMDBClient(settings.api_key)
    details = client.get_json(
        f"/{settings.media_type}/{tmdb_id}",
        {
            "language": "en-US",
            "append_to_response": "external_ids",
        },
    )
    return SubtitleLookupMetadata(
        query=first_non_empty(detail_original_title(details), title_from_details(details)),
        tmdb_id=tmdb_id,
        imdb_id=imdb_id_from_details(details),
        year=detail_release_date(details)[:4],
    )


def subtitle_target_from_settings(settings: AppSettings) -> SubtitleSearchTarget:
    query = subtitle_query_from_settings(settings)
    return SubtitleSearchTarget(
        media_dir=settings.media_dir,
        query=query,
        output_stem=subtitle_output_stem_for_dir(settings.media_dir, query),
        media_type=settings.media_type,
        tmdb_id=settings.tmdb_id if settings.tmdb_id.isdigit() else "",
        imdb_id="",
        year="",
        episode_ref=episode_ref_from_settings(settings),
        source_name=settings.media_dir.name,
    )


def batch_subtitle_targets(
    settings: AppSettings,
    source_dir: Path,
    tasks: list[BatchEpisodeTask],
) -> list[SubtitleSearchTarget]:
    targets: list[SubtitleSearchTarget] = []
    for task in tasks:
        query = task.source.stem
        fallback = batch_episode_preview_title(source_dir, task)
        targets.append(
            SubtitleSearchTarget(
                media_dir=task.extract_dir,
                query=query,
                output_stem=safe_filename_stem(task.source.stem or fallback),
                media_type="tv",
                tmdb_id=settings.tmdb_id if settings.tmdb_id.isdigit() else "",
                imdb_id="",
                year="",
                episode_ref=task.episode_ref,
                source_name=task.source.name,
            )
        )
    return targets


def subtitle_destination_path(
    target: SubtitleSearchTarget,
    result: SubtitleResult,
) -> Path:
    language = subtitle_filename_language_code(result.language)
    parts = []
    if result.forced:
        parts.append("forced")
    if result.hearing_impaired:
        parts.append("sdh")
    parts.append(language)
    stem = ".".join(part for part in parts if part)
    destination = target.media_dir / f"{stem}.srt"
    counter = 2
    while destination.exists():
        destination = target.media_dir / f"{stem}.{counter}.srt"
        counter += 1
    return destination


def extract_subtitle_payload(data: bytes, content_type: str) -> bytes:
    if not data:
        raise UserVisibleError(ui_text("error_subtitle_file_empty"))
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream) or "zip" in content_type.lower():
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            candidates = [
                name
                for name in archive.namelist()
                if Path(name).suffix.lower() in {".srt", ".ass", ".ssa", ".vtt", ".sub"}
            ]
            if not candidates:
                raise UserVisibleError(ui_text("error_subtitle_file_empty"))
            return archive.read(candidates[0])
    return data


def download_subtitle_result(
    client: OpenSubtitlesClient,
    result: SubtitleResult,
    target: SubtitleSearchTarget,
    token: str,
    base_url: str,
    out_fps: float | None,
) -> Path:
    if not target.media_dir.exists():
        raise UserVisibleError(ui_text("error_subtitle_missing_target", path=target.media_dir))
    destination = subtitle_destination_path(target, result)
    link = client.download_link(result, token, base_url, destination.name, out_fps)
    data, content_type = client.download_bytes(link)
    subtitle_bytes = extract_subtitle_payload(data, content_type)
    if not subtitle_bytes:
        raise UserVisibleError(ui_text("error_subtitle_file_empty"))
    destination.write_bytes(subtitle_bytes)
    return destination


def normalise_language(language: str) -> str:
    value = language.strip().lower() or "en"
    if "-" in value:
        value = value.split("-", 1)[0]
    return LANG_ALIASES.get(value, value)


def detail_language(language: str) -> str:
    code = normalise_language(language)
    defaults = {"en": "en-US", "tr": "tr-TR"}
    return defaults.get(code, f"{code}-{code.upper()}")


def image_score(image: dict[str, Any], preferred_language: str, prefer_null: bool = False) -> tuple[int, float, int, int]:
    image_language = image.get("iso_639_1")
    if image_language == preferred_language:
        language_score = 3
    elif image_language is None:
        language_score = 2 if prefer_null else 1
    else:
        language_score = 0
    area = int(image.get("width") or 0) * int(image.get("height") or 0)
    return (
        language_score,
        float(image.get("vote_average") or 0),
        int(image.get("vote_count") or 0),
        area,
    )


def choose_image(
    images: list[dict[str, Any]],
    preferred_language: str,
    *,
    prefer_png: bool = False,
    prefer_null: bool = False,
) -> dict[str, Any] | None:
    candidates = [image for image in images if image.get("file_path")]
    if prefer_png:
        png_candidates = [
            image for image in candidates if str(image.get("file_path", "")).lower().endswith(".png")
        ]
        if png_candidates:
            candidates = png_candidates
        else:
            raster_candidates = [
                image
                for image in candidates
                if not str(image.get("file_path", "")).lower().endswith(".svg")
            ]
            if raster_candidates:
                candidates = raster_candidates
            else:
                return None
    if not candidates:
        return None
    return max(candidates, key=lambda image: image_score(image, preferred_language, prefer_null))


def write_original_or_convert(data: bytes, file_path: str, destination: Path, image_format: str) -> None:
    suffix = Path(file_path).suffix.lower()
    if image_format == "JPEG" and suffix in {".jpg", ".jpeg"}:
        destination.write_bytes(data)
        return
    if image_format == "PNG" and suffix == ".png":
        destination.write_bytes(data)
        return
    if suffix == ".svg":
        raise UserVisibleError(
            ui_text("error_tmdb_svg_logo", name=destination.name)
        )
    if Image is None:
        raise UserVisibleError(ui_text("error_pillow_image_convert"))
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        if image_format == "JPEG":
            image = image.convert("RGB")
            image.save(destination, "JPEG", quality=95)
        else:
            image.save(destination, image_format)


def prepare_fixed_tmdb_logo(data: bytes, file_path: str, destination: Path) -> None:
    """Create a fixed-size, compact PNG logo while preserving transparency."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".svg":
        raise UserVisibleError(ui_text("error_tmdb_svg_logo", name=destination.name))
    if Image is None or ImageOps is None:
        raise UserVisibleError(ui_text("error_pillow_image_convert"))

    try:
        with Image.open(io.BytesIO(data)) as opened:
            logo = ImageOps.exif_transpose(opened).convert("RGBA")
    except (OSError, ValueError) as exc:
        raise UserVisibleError(str(exc)) from exc

    alpha = logo.getchannel("A")
    visible_bounds = alpha.getbbox()
    if visible_bounds is None:
        logo = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    else:
        logo = logo.crop(visible_bounds)

    max_width, max_height = TMDB_LOGO_CONTENT_SIZE
    width, height = logo.size
    scale = min(max_width / max(1, width), max_height / max(1, height))
    resized_size = (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )
    if resized_size != logo.size:
        logo = logo.resize(resized_size, Image.Resampling.LANCZOS)

    canvas_width, canvas_height = TMDB_LOGO_CANVAS_SIZE
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    offset = (
        (canvas_width - logo.width) // 2,
        (canvas_height - logo.height) // 2,
    )
    canvas.alpha_composite(logo, offset)

    candidates: list[bytes] = []

    rgba_buffer = io.BytesIO()
    canvas.save(
        rgba_buffer,
        "PNG",
        optimize=True,
        compress_level=9,
    )
    candidates.append(rgba_buffer.getvalue())

    if len(candidates[0]) > TMDB_LOGO_MAX_BYTES:
        quantize_method = getattr(getattr(Image, "Quantize", object()), "FASTOCTREE", 2)
        dither_none = getattr(getattr(Image, "Dither", object()), "NONE", 0)
        for colour_count in (256, 192, 128, 96, 64, 48, 32):
            paletted = canvas.quantize(
                colors=colour_count,
                method=quantize_method,
                dither=dither_none,
            )
            palette_buffer = io.BytesIO()
            paletted.save(
                palette_buffer,
                "PNG",
                optimize=True,
                compress_level=9,
            )
            encoded = palette_buffer.getvalue()
            candidates.append(encoded)
            if len(encoded) <= TMDB_LOGO_MAX_BYTES:
                break

    acceptable = [item for item in candidates if len(item) <= TMDB_LOGO_MAX_BYTES]
    output_bytes = acceptable[0] if acceptable else min(candidates, key=len)
    destination.write_bytes(output_bytes)


def resize_jpeg_cover_art(source: Path, destination: Path, smallest_side: int) -> None:
    if Image is None:
        raise UserVisibleError(ui_text("error_pillow_small_cover"))
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    scale = smallest_side / max(1, min(width, height))
    resized_size = (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )
    resized = image.resize(resized_size, Image.Resampling.LANCZOS)
    resized.save(destination, "JPEG", quality=95)


def make_small_cover(
    source: Path,
    destination: Path,
    smallest_side: int = SMALL_COVER_SMALLEST_SIDE,
) -> None:
    resize_jpeg_cover_art(source, destination, smallest_side)


def download_optional_tmdb_image(
    client: TMDBClient,
    image: dict[str, Any] | None,
    destination: Path,
    image_format: str,
    log: Callable[[str], None],
    ready_message: str | None,
    *,
    replace_existing: bool = False,
    fixed_tmdb_logo: bool = False,
) -> bool:
    if destination.exists() and not replace_existing:
        log(ui_text("log_file_exists_skipped", name=destination.name))
        return False
    if image is None:
        log(ui_text("log_file_not_found_skipped", name=destination.name))
        return False

    file_path = str(image["file_path"])
    try:
        image_bytes = client.download_bytes(file_path)
        if fixed_tmdb_logo:
            prepare_fixed_tmdb_logo(image_bytes, file_path, destination)
        else:
            write_original_or_convert(image_bytes, file_path, destination, image_format)
    except UserVisibleError as exc:
        log(ui_text("log_file_prepare_skipped", name=destination.name, error=exc))
        return False

    if ready_message:
        log(ready_message)
    return True


def detail_original_title(details: dict[str, Any]) -> str:
    return str(details.get("original_title") or details.get("original_name") or "")


def detail_release_date(details: dict[str, Any]) -> str:
    return str(details.get("release_date") or details.get("first_air_date") or "")


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def names_from_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    names: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def crew_names(details: dict[str, Any], jobs: set[str]) -> list[str]:
    credits = details.get("credits", {})
    if not isinstance(credits, dict):
        return []
    crew = credits.get("crew", [])
    if not isinstance(crew, list):
        return []

    names: list[str] = []
    for member in crew:
        if not isinstance(member, dict):
            continue
        job = str(member.get("job") or "").strip()
        name = str(member.get("name") or "").strip()
        if job in jobs and name and name not in names:
            names.append(name)
    return names


def imdb_id_from_details(details: dict[str, Any]) -> str:
    direct = str(details.get("imdb_id") or "").strip()
    if direct:
        return direct
    external_ids = details.get("external_ids", {})
    if isinstance(external_ids, dict):
        return str(external_ids.get("imdb_id") or "").strip()
    return ""


def tv_episode_title_from_details(details: dict[str, Any]) -> str:
    return str(details.get("name") or "").strip()


def tv_episode_air_date(details: dict[str, Any]) -> str:
    return str(details.get("air_date") or "").strip()


def tv_episode_crew_names(details: dict[str, Any], jobs: set[str]) -> list[str]:
    crew_values: list[Any] = []
    credits = details.get("credits")
    if isinstance(credits, dict) and isinstance(credits.get("crew"), list):
        crew_values.extend(credits["crew"])
    if isinstance(details.get("crew"), list):
        crew_values.extend(details["crew"])

    names: list[str] = []
    for member in crew_values:
        if not isinstance(member, dict):
            continue
        job = str(member.get("job") or "").strip()
        name = str(member.get("name") or "").strip()
        if job in jobs and name and name not in names:
            names.append(name)
    return names


def add_simple_tag(parent: ET.Element, name: str, value: Any, language: str) -> None:
    text = str(value or "").strip()
    if not text:
        return

    simple = ET.SubElement(parent, "Simple")
    ET.SubElement(simple, "Name").text = name
    ET.SubElement(simple, "String").text = text
    ET.SubElement(simple, "TagLanguage").text = language


def add_repeated_simple_tags(
    parent: ET.Element,
    name: str,
    values: list[str],
    language: str,
) -> None:
    for value in values:
        add_simple_tag(parent, name, value, language)


def simple_tag_child_text(simple: ET.Element, child_name: str) -> str:
    return str(simple.findtext(child_name) or "").strip()


def simple_tag_exists(root: ET.Element, name: str, value: str) -> bool:
    for simple in root.iter("Simple"):
        if (
            simple_tag_child_text(simple, "Name") == name
            and simple_tag_child_text(simple, "String") == value
        ):
            return True
    return False


def has_empty_targets(targets: ET.Element | None) -> bool:
    return targets is not None and not list(targets) and not str(targets.text or "").strip()


def find_or_create_global_tag(root: ET.Element) -> ET.Element:
    for tag in root.findall("Tag"):
        if has_empty_targets(tag.find("Targets")):
            return tag

    tag = ET.SubElement(root, "Tag")
    ET.SubElement(tag, "Targets")
    return tag


def ensure_app_credit_tags(root: ET.Element, language: str) -> bool:
    added = False
    target_tag: ET.Element | None = None
    for name, value in APP_TAG_SIMPLE_TAGS:
        if simple_tag_exists(root, name, value):
            continue
        if target_tag is None:
            target_tag = find_or_create_global_tag(root)
        add_simple_tag(target_tag, name, value, language)
        added = True
    return added


def ensure_app_credit_tags_file(path: Path, language: str) -> bool:
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "Tags":
        raise ValueError("root element is not Tags")
    if not ensure_app_credit_tags(root, language):
        return False

    ET.indent(root, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return True


def write_tmdb_tags_file(
    path: Path,
    details: dict[str, Any],
    media_type: str,
    tmdb_id: str,
    language: str,
) -> Path:
    root = ET.Element("Tags")
    tag = ET.SubElement(root, "Tag")
    ET.SubElement(tag, "Targets")

    title = title_from_details(details)
    original_title = detail_original_title(details)
    add_simple_tag(tag, "TITLE", title, language)
    if original_title and original_title != title:
        add_simple_tag(tag, "ORIGINAL_TITLE", original_title, language)
    add_simple_tag(tag, "SUBTITLE", details.get("tagline"), language)
    add_simple_tag(tag, "SUMMARY", details.get("overview"), language)
    add_simple_tag(tag, "DATE_RELEASED", detail_release_date(details), language)
    add_simple_tag(tag, "ORIGINAL_LANGUAGE", details.get("original_language"), language)
    add_repeated_simple_tags(tag, "GENRE", names_from_list(details.get("genres")), language)
    add_repeated_simple_tags(
        tag,
        "PRODUCTION_STUDIO",
        names_from_list(details.get("production_companies")),
        language,
    )

    if media_type == "movie":
        add_repeated_simple_tags(tag, "DIRECTOR", crew_names(details, {"Director"}), language)
        add_repeated_simple_tags(
            tag,
            "WRITTEN_BY",
            crew_names(details, {"Writer", "Screenplay", "Story"}),
            language,
        )
        add_simple_tag(tag, "DURATION", details.get("runtime"), language)
    else:
        add_repeated_simple_tags(tag, "CREATED_BY", names_from_list(details.get("created_by")), language)
        add_simple_tag(tag, "NUMBER_OF_SEASONS", details.get("number_of_seasons"), language)
        add_simple_tag(tag, "NUMBER_OF_EPISODES", details.get("number_of_episodes"), language)

    add_simple_tag(tag, "STATUS", details.get("status"), language)
    add_simple_tag(tag, "TMDB_ID", tmdb_id, language)
    add_simple_tag(tag, "URL", f"https://www.themoviedb.org/{media_type}/{tmdb_id}", language)
    add_simple_tag(tag, "IMDB", imdb_id_from_details(details), language)
    ensure_app_credit_tags(root, language)

    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def write_tmdb_episode_tags_file(
    path: Path,
    series_details: dict[str, Any],
    episode_details: dict[str, Any],
    tmdb_id: str,
    episode_ref: EpisodeRef,
    language: str,
) -> Path:
    root = ET.Element("Tags")
    tag = ET.SubElement(root, "Tag")
    ET.SubElement(tag, "Targets")

    series_title = title_from_details(series_details)
    series_original_title = detail_original_title(series_details)
    episode_title = tv_episode_title_from_details(episode_details)
    output_title = tv_episode_output_title(series_title, episode_ref, episode_title)
    summary = first_non_empty(episode_details.get("overview"), series_details.get("overview"))
    release_date = first_non_empty(tv_episode_air_date(episode_details), detail_release_date(series_details))
    directors = tv_episode_crew_names(episode_details, {"Director"})
    if not directors:
        directors = crew_names(series_details, {"Director"})
    writers = tv_episode_crew_names(
        episode_details,
        {"Writer", "Screenplay", "Story", "Teleplay"},
    )
    if not writers:
        writers = crew_names(series_details, {"Writer", "Screenplay", "Story", "Teleplay"})

    add_simple_tag(tag, "TITLE", output_title, language)
    add_simple_tag(tag, "SERIES_TITLE", series_title, language)
    if series_original_title and series_original_title != series_title:
        add_simple_tag(tag, "ORIGINAL_TITLE", series_original_title, language)
    add_simple_tag(tag, "EPISODE_TITLE", episode_title, language)
    add_simple_tag(tag, "SEASON_NUMBER", episode_ref.season, language)
    add_simple_tag(tag, "EPISODE_NUMBER", episode_ref.episode, language)
    add_simple_tag(tag, "PART_NUMBER", episode_ref.episode, language)
    add_simple_tag(tag, "SUBTITLE", series_details.get("tagline"), language)
    add_simple_tag(tag, "SUMMARY", summary, language)
    add_simple_tag(tag, "DATE_RELEASED", release_date, language)
    add_simple_tag(tag, "ORIGINAL_LANGUAGE", series_details.get("original_language"), language)
    add_repeated_simple_tags(tag, "GENRE", names_from_list(series_details.get("genres")), language)
    add_repeated_simple_tags(
        tag,
        "PRODUCTION_STUDIO",
        names_from_list(series_details.get("production_companies")),
        language,
    )
    add_repeated_simple_tags(tag, "CREATED_BY", names_from_list(series_details.get("created_by")), language)
    add_repeated_simple_tags(tag, "DIRECTOR", directors, language)
    add_repeated_simple_tags(tag, "WRITTEN_BY", writers, language)
    add_simple_tag(tag, "NUMBER_OF_SEASONS", series_details.get("number_of_seasons"), language)
    add_simple_tag(tag, "NUMBER_OF_EPISODES", series_details.get("number_of_episodes"), language)
    add_simple_tag(tag, "STATUS", series_details.get("status"), language)
    add_simple_tag(tag, "TMDB_ID", tmdb_id, language)
    add_simple_tag(
        tag,
        "URL",
        f"https://www.themoviedb.org/tv/{tmdb_id}/season/{episode_ref.season}/episode/{episode_ref.episode}",
        language,
    )
    add_simple_tag(
        tag,
        "IMDB",
        first_non_empty(imdb_id_from_details(episode_details), imdb_id_from_details(series_details)),
        language,
    )
    ensure_app_credit_tags(root, language)

    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def ensure_tmdb_tags_file(
    settings: AppSettings,
    client: TMDBClient,
    media_type: str,
    tmdb_id: str,
    language: str,
    log: Callable[[str], None],
    episode_ref: EpisodeRef | None = None,
    *,
    replace_existing: bool = False,
) -> None:
    tags_path = settings.media_dir / "tags.xml"
    if tags_path.exists() and not replace_existing:
        log(ui_text("log_tags_exists"))
        try:
            if ensure_app_credit_tags_file(tags_path, language):
                log(ui_text("log_tags_ready"))
        except (OSError, ValueError, ET.ParseError) as exc:
            log(ui_text("log_file_prepare_skipped", name=tags_path.name, error=exc))
        return

    details = client.get_json(
        f"/{media_type}/{tmdb_id}",
        {
            "language": detail_language(language),
            "append_to_response": "credits,external_ids",
        },
    )
    if media_type == "tv" and episode_ref is not None:
        episode_details = client.get_json(
            f"/tv/{tmdb_id}/season/{episode_ref.season}/episode/{episode_ref.episode}",
            {
                "language": detail_language(language),
                "append_to_response": "credits,external_ids",
            },
        )
        write_tmdb_episode_tags_file(
            tags_path,
            details,
            episode_details,
            tmdb_id,
            episode_ref,
            language,
        )
    else:
        write_tmdb_tags_file(tags_path, details, media_type, tmdb_id, language)
    log(ui_text("log_tags_ready"))


def download_tmdb_assets(
    settings: AppSettings,
    log: Callable[[str], None],
    episode_ref: EpisodeRef | None = None,
    *,
    replace_existing: bool = False,
) -> tuple[str, str]:
    client = TMDBClient(settings.api_key)
    language = normalise_language(settings.image_language)
    tag_language = normalise_language(settings.tag_language)
    media_type = settings.media_type
    tmdb_id = settings.tmdb_id
    if episode_ref is None:
        episode_ref = episode_ref_from_settings(settings)

    details = client.get_json(
        f"/{media_type}/{tmdb_id}",
        {"language": detail_language(language)},
    )
    images = client.get_json(
        f"/{media_type}/{tmdb_id}/images",
        {"include_image_language": f"{language},null"},
    )

    title = title_from_details(details)
    if title:
        log(ui_text("log_tmdb_title", title=title))

    poster = choose_image(images.get("posters", []), language)
    backdrop = choose_image(images.get("backdrops", []), language, prefer_null=True)
    logo = choose_image(images.get("logos", []), language, prefer_png=True)

    settings.media_dir.mkdir(parents=True, exist_ok=True)

    cover = settings.media_dir / "cover.jpg"
    cover_downloaded = download_optional_tmdb_image(
        client,
        poster,
        cover,
        "JPEG",
        log,
        None,
        replace_existing=replace_existing,
    )
    if cover_downloaded:
        try:
            resize_jpeg_cover_art(cover, cover, NORMAL_COVER_SMALLEST_SIDE)
            log(ui_text("log_cover_ready"))
        except UserVisibleError as exc:
            log(ui_text("log_file_prepare_skipped", name=cover.name, error=exc))
    small_cover = settings.media_dir / "small_cover.jpg"
    if cover.exists() and (replace_existing or not small_cover.exists()):
        try:
            make_small_cover(cover, small_cover)
            log(ui_text("log_small_cover_ready"))
        except UserVisibleError as exc:
            log(ui_text("log_small_cover_skipped", error=exc))

    cover_land = settings.media_dir / "cover_land.jpg"
    cover_land_downloaded = download_optional_tmdb_image(
        client,
        backdrop,
        cover_land,
        "JPEG",
        log,
        None,
        replace_existing=replace_existing,
    )
    if cover_land_downloaded:
        try:
            resize_jpeg_cover_art(cover_land, cover_land, NORMAL_COVER_SMALLEST_SIDE)
            log(ui_text("log_cover_land_ready"))
        except UserVisibleError as exc:
            log(ui_text("log_file_prepare_skipped", name=cover_land.name, error=exc))
    small_cover_land = settings.media_dir / "small_cover_land.jpg"
    if cover_land.exists() and (replace_existing or not small_cover_land.exists()):
        try:
            make_small_cover(cover_land, small_cover_land)
            log(ui_text("log_small_cover_land_ready"))
        except UserVisibleError as exc:
            log(ui_text("log_small_cover_land_skipped", error=exc))

    download_optional_tmdb_image(
        client,
        logo,
        settings.media_dir / "logo.png",
        "PNG",
        log,
        ui_text("log_logo_ready"),
        replace_existing=replace_existing,
        fixed_tmdb_logo=True,
    )

    ensure_tmdb_tags_file(
        settings,
        client,
        media_type,
        tmdb_id,
        tag_language,
        log,
        episode_ref=episode_ref if media_type == "tv" else None,
        replace_existing=replace_existing,
    )

    if media_type == "tv" and episode_ref is not None:
        episode_details = client.get_json(
            f"/tv/{tmdb_id}/season/{episode_ref.season}/episode/{episode_ref.episode}",
            {"language": detail_language(language)},
        )
        return (
            tv_episode_output_title(
                title,
                episode_ref,
                tv_episode_title_from_details(episode_details),
            ),
            result_year(details),
        )

    return title, result_year(details)


def find_tmdb_match_from_folder(
    settings: AppSettings,
) -> tuple[str, str, str, str]:
    query = ""
    year = ""
    source_name = ""
    for candidate in release_name_candidates(settings):
        query, year = parse_release_name(candidate)
        if query:
            source_name = candidate
            break
    if not query:
        raise UserVisibleError(ui_text("error_folder_title_missing"))

    client = TMDBClient(settings.api_key)
    results = client.search(settings.media_type, query, year)
    if not results:
        year_text = f" ({year})" if year else ""
        raise UserVisibleError(
            ui_text("error_tmdb_no_result", query=query, year_text=year_text)
        )

    best = max(results, key=lambda result: score_tmdb_result(result, query, year))
    tmdb_id = str(best.get("id") or "")
    title = result_title(best)
    found_year = result_year(best)
    if not tmdb_id:
        raise UserVisibleError(ui_text("error_tmdb_missing_id"))
    if source_name and normalise_title_for_match(source_name) != normalise_title_for_match(query):
        query = f"{query} [{source_name}]"
    return tmdb_id, title, found_year, query


def tmdb_title_for_language(settings: AppSettings, tmdb_id: str, language: str) -> str:
    client = TMDBClient(settings.api_key)
    details = client.get_json(
        f"/{settings.media_type}/{tmdb_id}",
        {"language": detail_language(normalise_language(language))},
    )
    return title_from_details(details)


def tmdb_output_title_for_language(
    settings: AppSettings,
    tmdb_id: str,
    language: str,
    episode_ref: EpisodeRef | None = None,
) -> str:
    series_title = tmdb_title_for_language(settings, tmdb_id, language)
    if settings.media_type != "tv":
        return series_title
    if episode_ref is None:
        episode_ref = episode_ref_from_settings(settings)
    if episode_ref is None:
        return series_title

    client = TMDBClient(settings.api_key)
    episode_details = client.get_json(
        f"/tv/{tmdb_id}/season/{episode_ref.season}/episode/{episode_ref.episode}",
        {"language": detail_language(normalise_language(language))},
    )
    return tv_episode_output_title(
        series_title,
        episode_ref,
        tv_episode_title_from_details(episode_details),
    )


def tmdb_season_folder_path(source_dir: Path, settings: AppSettings, season: int) -> Path:
    language = normalise_language(settings.image_language)
    if settings.download_before_mux and settings.media_type == "tv" and settings.api_key and settings.tmdb_id:
        client = TMDBClient(settings.api_key)
        series_details = client.get_json(
            f"/tv/{settings.tmdb_id}",
            {"language": detail_language(language)},
        )
        season_details = client.get_json(
            f"/tv/{settings.tmdb_id}/season/{season}",
            {"language": detail_language(language)},
        )
        folder_name = season_folder_name(
            title_from_details(series_details),
            str(season_details.get("name") or ""),
            season,
            language,
        )
    else:
        folder_name = season_folder_name(source_dir.name, "", season, language)
    return source_dir.parent / folder_name


def command_preview(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def ffmpeg_path() -> str:
    # Runtime media operations must start the already-installed executable
    # immediately.  Do not perform a network release check before every FFmpeg
    # invocation; on Windows that can make intro detection appear frozen before
    # ffmpeg.exe is even spawned.  Automatic installation is only the fallback
    # when the executable is genuinely missing.
    ffmpeg = installed_third_party_tool_path("ffmpeg")
    if ffmpeg:
        THIRD_PARTY_READY_GROUPS.add("ffmpeg")
        return ffmpeg
    ffmpeg = third_party_tool_path("ffmpeg")
    if not ffmpeg:
        raise UserVisibleError(ui_text("error_ffmpeg_missing"))
    return ffmpeg


def ffprobe_path(auto_install: bool = True) -> str | None:
    ffprobe = installed_third_party_tool_path("ffprobe")
    if ffprobe:
        THIRD_PARTY_READY_GROUPS.add("ffmpeg")
        return ffprobe
    return third_party_tool_path("ffprobe", required=False, auto_install=auto_install)


def parse_milliseconds_delta(value: str) -> float:
    raw = value.strip().replace(",", ".")
    if not raw:
        return 0.0
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        raise UserVisibleError(ui_text("error_audio_adjust_numeric"))
    return float(raw) / 1000


def dedupe_sidecar_path(path: Path, marker: str) -> Path:
    candidate = path.with_name(f"{path.name}.{marker}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{marker}{counter}")
        counter += 1
    return candidate


def numbered_append_path(path: Path) -> Path:
    candidate = path.with_name(f"{path.stem}.1{path.suffix}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.{counter}{path.suffix}")
        counter += 1
    return candidate


def channel_layout_from_channels(channels: int) -> str:
    return {
        1: "mono",
        2: "stereo",
        3: "2.1",
        4: "quad",
        5: "5.0",
        6: "5.1",
        7: "6.1",
        8: "7.1",
    }.get(channels, "stereo")


def codec_from_audio_track(path: Path, track: dict[str, Any] | None = None) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "ec3":
        return "eac3"
    if suffix in SUPPORTED_AUDIO_ENCODERS:
        return suffix
    codec_id = ""
    codec = ""
    if track:
        codec_id = str(track.get("codec_id") or "").upper()
        codec = str(track.get("codec") or "").lower()
    if "EAC3" in codec_id or "e-ac-3" in codec:
        return "eac3"
    if "AC3" in codec_id or "ac-3" in codec:
        return "ac3"
    if "DTS" in codec_id or "dts" in codec:
        return "dts"
    if "AAC" in codec_id or "aac" in codec:
        return "aac"
    if "FLAC" in codec_id or "flac" in codec:
        return "flac"
    if "VORBIS" in codec_id or "vorbis" in codec:
        return "ogg"
    if "OPUS" in codec_id or "opus" in codec:
        return "opus"
    if "L3" in codec_id or "mp3" in codec:
        return "mp3"
    if "PCM" in codec_id or "pcm" in codec:
        return "wav"
    return suffix or "eac3"


def normalise_audio_bitrate(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw or raw in {"n/a", "none"}:
        return ""
    if raw.endswith("bps"):
        raw = raw[:-3].strip()
    if raw.endswith("k"):
        return raw
    try:
        return f"{round(float(raw) / 1000)}k"
    except ValueError:
        return raw


def normalise_audio_rate(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw or raw in {"n/a", "none"}:
        return ""
    try:
        return str(int(float(raw)))
    except ValueError:
        return raw


def normalise_audio_layout(value: Any, channels: Any = None) -> str:
    raw = str(value or "").strip().lower()
    if raw and raw not in {"n/a", "none", "unknown"}:
        return raw
    try:
        return channel_layout_from_channels(int(channels))
    except (TypeError, ValueError):
        return ""


def audio_probe_defaults(path: Path) -> dict[str, str]:
    result = {
        "codec": codec_from_audio_track(path),
        "bitrate": "",
        "sample_rate": "",
        "channel_layout": "",
    }

    ffprobe = ffprobe_path(auto_install=False)
    if ffprobe:
        args = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,codec_tag_string,bit_rate,sample_rate,channels,channel_layout",
            "-of",
            "json",
            str(path),
        ]
        process = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **subprocess_common_kwargs(),
            check=False,
            env=third_party_subprocess_env(),
            executable=third_party_subprocess_executable(args),
        )
        if process.returncode == 0 and process.stdout.strip():
            try:
                payload = json.loads(process.stdout)
                streams = payload.get("streams") or []
            except json.JSONDecodeError:
                streams = []
            if streams:
                stream = streams[0]
                codec_name = str(stream.get("codec_name") or "").lower()
                codec_tag = str(stream.get("codec_tag_string") or "").lower()
                result["codec"] = codec_from_audio_track(
                    path,
                    {"codec": codec_name, "codec_id": codec_tag},
                )
                result["bitrate"] = normalise_audio_bitrate(stream.get("bit_rate"))
                result["sample_rate"] = normalise_audio_rate(stream.get("sample_rate"))
                result["channel_layout"] = normalise_audio_layout(
                    stream.get("channel_layout"),
                    stream.get("channels"),
                )
                return {
                    "codec": result["codec"] or codec_from_audio_track(path),
                    "bitrate": result["bitrate"] or "384k",
                    "sample_rate": result["sample_rate"] or "48000",
                    "channel_layout": result["channel_layout"] or "stereo",
                }

    if not third_party_tool_path("mkvmerge", required=False, auto_install=False):
        return {
            "codec": result["codec"] or "eac3",
            "bitrate": result["bitrate"] or "384k",
            "sample_rate": result["sample_rate"] or "48000",
            "channel_layout": result["channel_layout"] or "stereo",
        }

    try:
        payload = identify_mkv(path)
    except UserVisibleError:
        return {
            "codec": result["codec"] or "eac3",
            "bitrate": result["bitrate"] or "384k",
            "sample_rate": result["sample_rate"] or "48000",
            "channel_layout": result["channel_layout"] or "stereo",
        }
    for track in payload.get("tracks", []):
        if str(track.get("type") or "") != "audio":
            continue
        props = track.get("properties", {})
        result["codec"] = codec_from_audio_track(path, {**track, **props})
        result["sample_rate"] = normalise_audio_rate(
            props.get("audio_sampling_frequency") or props.get("sampling_frequency")
        )
        result["channel_layout"] = normalise_audio_layout(
            props.get("audio_channel_layout"),
            props.get("audio_channels") or props.get("channels"),
        )
        result["bitrate"] = normalise_audio_bitrate(
            props.get("audio_bits_per_second") or props.get("bit_rate") or props.get("bitrate")
        )
        break
    return {
        "codec": result["codec"] or "eac3",
        "bitrate": result["bitrate"] or "384k",
        "sample_rate": result["sample_rate"] or "48000",
        "channel_layout": result["channel_layout"] or "stereo",
    }


def normalise_audio_adjust_value(value: str) -> str:
    return str(value or "").strip().lower()


def normalise_audio_volume_multiplier(value: Any) -> float:
    try:
        volume = round(float(value), 1)
    except (TypeError, ValueError):
        return 1.0
    return float(min(5, max(1, volume)))


def audio_adjust_requires_reencode(task: AudioAdjustTask) -> bool:
    if normalise_audio_volume_multiplier(task.volume_multiplier) != 1:
        return True
    if abs(task.speed_factor - 1.0) > 0.0001:
        return True
    return any(
        normalise_audio_adjust_value(current) != normalise_audio_adjust_value(original)
        for current, original in (
            (task.codec, task.original_codec),
            (task.bitrate, task.original_bitrate),
            (task.sample_rate, task.original_sample_rate),
            (task.channel_layout, task.original_channel_layout),
        )
    )


def audio_adjust_has_work(task: AudioAdjustTask) -> bool:
    return task.delta_seconds != 0 or audio_adjust_requires_reencode(task)


def validate_audio_adjust_task(task: AudioAdjustTask) -> None:
    if task.codec not in SUPPORTED_AUDIO_ENCODERS:
        raise UserVisibleError(ui_text("error_audio_codec_unsupported", codec=task.codec))
    if not audio_adjust_has_work(task):
        raise UserVisibleError(ui_text("error_audio_adjust_none"))


def audio_bitrate_kbps(value: str) -> int | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kmg]?)", raw)
    if match is None:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return round(amount * 1000)
    if unit == "g":
        return round(amount * 1_000_000)
    if unit == "k":
        return round(amount)
    return round(amount / 1000)


def audio_encoder_bitrate(task: AudioAdjustTask) -> str:
    bitrate = task.bitrate.strip()
    if task.codec == "dts":
        kbps = audio_bitrate_kbps(bitrate)
        if kbps is None or kbps < 768:
            return "768k"
    return bitrate


def ffmpeg_audio_output_args(task: AudioAdjustTask) -> list[str]:
    encoder = FFMPEG_AUDIO_ENCODERS[task.codec]
    args = ["-c:a", encoder]
    if task.codec == "dts":
        args.extend(["-strict", "-2"])
    bitrate = audio_encoder_bitrate(task)
    if task.codec != "wav" and bitrate:
        args.extend(["-b:a", bitrate])
    if task.sample_rate.strip():
        args.extend(["-ar", task.sample_rate.strip()])
    if task.channel_layout.strip():
        args.extend(["-channel_layout", task.channel_layout.strip()])
    return args


def ffmpeg_audio_filter_args(task: AudioAdjustTask) -> list[str]:
    filters = []
    volume = normalise_audio_volume_multiplier(task.volume_multiplier)
    if volume != 1:
        filters.append(f"volume={volume:g}")
    if abs(task.speed_factor - 1.0) > 0.0001:
        speed = task.speed_factor
        if speed < 0.5:
            current = speed
            while current < 0.5:
                filters.append("atempo=0.5")
                current *= 2
            if current > 1.0:
                filters.append(f"atempo={current:.6f}")
            elif current < 0.9999:
                filters.append(f"atempo={current:.6f}")
        elif speed > 2.0:
            remaining = speed
            while remaining > 2.0:
                filters.append("atempo=2.0")
                remaining /= 2.0
            if remaining > 1.0001:
                filters.append(f"atempo={remaining:.6f}")
            elif remaining < 0.9999:
                filters.append(f"atempo={remaining:.6f}")
        else:
            filters.append(f"atempo={speed:.6f}")

    if not filters:
        return []
    return ["-filter:a", ",".join(filters)]


def run_logged_process(args: list[str], log: Callable[[str], None]) -> None:
    log(ui_text("log_audio_adjust_command"))
    log(command_preview(args))
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **subprocess_common_kwargs(),
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        log(line.rstrip())
    return_code = process.wait()
    if return_code != 0:
        raise UserVisibleError(ui_text("error_ffmpeg_exit", code=return_code))


def run_cancellable_logged_process(
    args: list[str],
    log: Callable[[str], None],
    *,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled(ui_text("log_operation_cancelled"))
    log(ui_text("log_audio_adjust_command"))
    log(command_preview(args))
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **subprocess_common_kwargs(),
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
        bufsize=1,
    )
    if register_process is not None:
        register_process(process)
    try:
        if cancel_event is not None and cancel_event.is_set():
            terminate_process(process)
            raise OperationCancelled(ui_text("log_operation_cancelled"))
        assert process.stdout is not None
        for line in process.stdout:
            if cancel_event is not None and cancel_event.is_set():
                terminate_process(process)
                break
            log(line.rstrip())
        if cancel_event is not None and cancel_event.is_set():
            terminate_process(process)
            raise OperationCancelled(ui_text("log_operation_cancelled"))
        return_code = process.wait()
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled(ui_text("log_operation_cancelled"))
    finally:
        if unregister_process is not None:
            unregister_process(process)

    if return_code != 0:
        raise UserVisibleError(ui_text("error_ffmpeg_exit", code=return_code))


def cleanup_failed_audio_adjust(
    original_path: Path,
    restore_path: Path | None,
    generated_paths: list[Path],
    log: Callable[[str], None],
) -> None:
    seen: set[Path] = set()
    for generated_path in generated_paths:
        if restore_path is not None and generated_path == restore_path:
            continue
        if generated_path in seen:
            continue
        seen.add(generated_path)
        if not generated_path.exists():
            continue
        try:
            generated_path.unlink()
        except OSError as exc:
            log(ui_text("error_output_delete_failed", name=generated_path.name, error=exc))

    if restore_path is None or not restore_path.exists():
        return
    if original_path.exists():
        try:
            original_path.unlink()
        except OSError as exc:
            log(ui_text("error_output_delete_failed", name=original_path.name, error=exc))
            return
    try:
        restore_path.rename(original_path)
    except OSError as exc:
        log(ui_text("error_file_prepare_failed", name=original_path.name, error=exc))


def run_audio_adjust_task(
    task: AudioAdjustTask,
    log: Callable[[str], None],
    *,
    cancel_event: threading.Event | None = None,
    register_process: Callable[[subprocess.Popen[Any]], None] | None = None,
    unregister_process: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> Path:
    validate_audio_adjust_task(task)
    ffmpeg = ffmpeg_path()
    output_suffix = AUDIO_OUTPUT_SUFFIXES.get(task.codec, task.path.suffix)
    target = task.path.with_suffix(output_suffix)
    needs_reencode = audio_adjust_requires_reencode(task)
    restore_path: Path | None = None
    generated_paths: list[Path] = []

    if target != task.path and target.exists():
        raise UserVisibleError(ui_text("error_output_exists_choose", name=target.name))

    try:
        if task.delta_seconds > 0:
            source_path = dedupe_sidecar_path(task.path, "source")
            task.path.rename(source_path)
            restore_path = source_path

            original_path = numbered_append_path(target)
            if needs_reencode:
                generated_paths.append(original_path)
                encode_original_args = [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(source_path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    *ffmpeg_audio_filter_args(task),
                    *ffmpeg_audio_output_args(task),
                    str(original_path),
                ]
                run_cancellable_logged_process(
                    encode_original_args,
                    log,
                    cancel_event=cancel_event,
                    register_process=register_process,
                    unregister_process=unregister_process,
                )
            else:
                source_path.rename(original_path)
                restore_path = original_path

            generated_paths.append(target)
            lavfi = f"anullsrc=channel_layout={task.channel_layout}:sample_rate={task.sample_rate}"
            silence_args = [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                lavfi,
                *ffmpeg_audio_output_args(task),
                "-t",
                f"{task.delta_seconds:.6f}".rstrip("0").rstrip("."),
                str(target),
            ]
            run_cancellable_logged_process(
                silence_args,
                log,
                cancel_event=cancel_event,
                register_process=register_process,
                unregister_process=unregister_process,
            )
        elif task.delta_seconds < 0:
            backup_path = dedupe_sidecar_path(task.path, "source")
            task.path.rename(backup_path)
            restore_path = backup_path
            generated_paths.append(target)
            trim_args = [
                ffmpeg,
                "-y",
                "-ss",
                f"{abs(task.delta_seconds):.6f}".rstrip("0").rstrip("."),
                "-i",
                str(backup_path),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
            ]
            if needs_reencode:
                trim_args.extend(ffmpeg_audio_filter_args(task))
                trim_args.extend(ffmpeg_audio_output_args(task))
            else:
                trim_args.extend(["-c:a", "copy"])
            trim_args.append(str(target))
            run_cancellable_logged_process(
                trim_args,
                log,
                cancel_event=cancel_event,
                register_process=register_process,
                unregister_process=unregister_process,
            )
        else:
            backup_path = dedupe_sidecar_path(task.path, "source")
            task.path.rename(backup_path)
            restore_path = backup_path
            generated_paths.append(target)
            encode_args = [
                ffmpeg,
                "-y",
                "-i",
                str(backup_path),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                *ffmpeg_audio_filter_args(task),
                *ffmpeg_audio_output_args(task),
                str(target),
            ]
            run_cancellable_logged_process(
                encode_args,
                log,
                cancel_event=cancel_event,
                register_process=register_process,
                unregister_process=unregister_process,
            )
    except Exception:
        cleanup_failed_audio_adjust(task.path, restore_path, generated_paths, log)
        raise

    log(ui_text("log_audio_adjust_ready", name=target.name))
    return target



def identify_mkv(source: Path) -> dict[str, Any]:
    mkvmerge = third_party_tool_path("mkvmerge")
    if not mkvmerge:
        raise UserVisibleError(ui_text("error_mkvmerge_missing"))
    if not source.exists() or not source.is_file():
        raise UserVisibleError(ui_text("error_mkv_source_not_found", source=source))

    command_variants = [
        [mkvmerge, "--identify", "--identification-format", "json", str(source)],
        [mkvmerge, "--identification-format", "json", "--identify", str(source)],
        [mkvmerge, "-J", str(source)],
    ]
    attempts: list[str] = []
    env = third_party_subprocess_env()
    cwd = str(Path(mkvmerge).parent) if os.name == "nt" else None

    def parse_payload(raw: str, command: str) -> dict[str, Any] | None:
        text_value = (raw or "").strip().lstrip("\ufeff")
        if not text_value:
            return None
        try:
            payload = json.loads(text_value)
        except json.JSONDecodeError as exc:
            attempts.append(f"json_error={exc}; command={command}; output_head={text_value[:160]!r}")
            return None
        if not payload.get("container", {}).get("recognized"):
            raise UserVisibleError(ui_text("error_mkv_not_recognized"))
        return payload

    for args in command_variants:
        process = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **subprocess_common_kwargs(),
            check=False,
            env=env,
            cwd=cwd,
            executable=third_party_subprocess_executable(args),
        )

        stdout = process.stdout or ""
        stderr = (process.stderr or "").strip()
        command = " ".join(shlex.quote(str(part)) for part in args)
        attempts.append(
            f"pipe: returncode={process.returncode}; stdout_len={len(stdout.strip())}; "
            f"stderr={stderr or '-'}; command={command}"
        )

        if process.returncode <= 1:
            payload = parse_payload(stdout, command)
            if payload is not None:
                return payload

    # Some Windows builds can return 0 but emit nothing when stdout is captured
    # through PIPE. Retry with normal cmd.exe redirection to a temporary file.
    if os.name == "nt":
        import tempfile

        for args in command_variants:
            with tempfile.TemporaryDirectory(prefix="gtmce-mkvmerge-") as tmpdir:
                out_path = Path(tmpdir) / "identify.json"
                err_path = Path(tmpdir) / "identify.err"
                command = subprocess.list2cmdline([str(part) for part in args])
                with out_path.open("w", encoding="utf-8", errors="replace") as stdout_handle, err_path.open(
                    "w", encoding="utf-8", errors="replace"
                ) as stderr_handle:
                    process = subprocess.run(
                        args,
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                        text=True,
                        check=False,
                        env=env,
                        cwd=cwd,
                        executable=third_party_subprocess_executable(args),
                        **subprocess_window_kwargs(),
                    )
                stdout_file = out_path.read_text(encoding="utf-8-sig", errors="replace") if out_path.exists() else ""
                stderr_file = err_path.read_text(encoding="utf-8-sig", errors="replace").strip() if err_path.exists() else ""
                attempts.append(
                    f"redirect: returncode={process.returncode}; file_len={len(stdout_file.strip())}; "
                    f"stderr={stderr_file or '-'}; command={command}"
                )
                if process.returncode <= 1:
                    payload = parse_payload(stdout_file, command)
                    if payload is not None:
                        return payload

    raise UserVisibleError(
        ui_text(
            "error_mkv_read_failed",
            message="mkvmerge produced no usable JSON output; " + " | ".join(attempts),
        )
    )

def clean_output_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or fallback


def dedupe_plain_filename(name: str, used_names: set[str]) -> str:
    path = Path(name)
    stem = clean_output_component(path.stem, "item")
    suffix = path.suffix
    candidate = f"{stem}{suffix}"
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}.{counter}{suffix}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def language_for_extract_output(track: dict[str, Any]) -> str:
    properties = track.get("properties", {})
    for key in ("language", "language_ietf"):
        value = str(properties.get(key) or "").strip().lower()
        if not value:
            continue
        if key == "language_ietf":
            value = value.split("-", 1)[0]
        value = re.sub(r"[^a-z0-9]+", "", value)
        return value or "und"
    return "und"


def normalise_extract_language_override(value: str) -> str:
    language = value.strip().lower()
    if not language:
        return ""
    language = re.split(r"[,;|\s_]+", language, maxsplit=1)[0]
    language = language.split("-", 1)[0]
    language = LANG_ALIASES.get(language, language)
    return re.sub(r"[^a-z0-9]+", "", language)


def extract_item_output_language(item: ExtractItem) -> str:
    # The Qt extractor lets the user override the language directly in the
    # table for every track, not only tracks originally tagged ``und``.
    override = normalise_extract_language_override(item.language_override)
    return override or item.language


def extract_item_name_parts(item: ExtractItem) -> list[str]:
    parts = list(item.name_prefix_parts)
    if item.language:
        parts.append(extract_item_output_language(item))
    parts.extend(item.name_suffix_parts)
    return parts


def rebuild_extract_output_names(items: list[ExtractItem]) -> None:
    counters: dict[tuple[str, str], int] = {}
    used_names: set[str] = set()
    for item in items:
        if item.kind == "track" and item.extension:
            item.output_name = make_numbered_track_name(
                extract_item_name_parts(item),
                item.extension,
                counters,
                used_names,
            )
        else:
            used_names.add(item.output_name.lower())


def track_output_extension(track: dict[str, Any]) -> str:
    properties = track.get("properties", {})
    codec_id = str(properties.get("codec_id") or "").upper()
    codec = str(track.get("codec") or "").lower()
    track_type = str(track.get("type") or "")

    if track_type == "video":
        if "AVC" in codec_id or "H.264" in codec_id or "H264" in codec_id or "h.264" in codec or "h264" in codec or "avc" in codec:
            return "h264"
        if "HEVC" in codec_id or "H.265" in codec_id or "H265" in codec_id or "h.265" in codec or "h265" in codec or "hevc" in codec:
            return "h265"
        if "AV1" in codec_id or "av1" in codec:
            return "ivf"
        if "VP9" in codec_id or "vp9" in codec:
            return "ivf"
        if "MPEG2" in codec_id or "MPEG-2" in codec_id or "mpeg-2" in codec or "mpeg2" in codec:
            return "m2v"
        return "video"

    if track_type == "audio":
        if "EAC3" in codec_id or "E-AC-3" in codec:
            return "eac3"
        if "AC3" in codec_id or "AC-3" in codec:
            return "ac3"
        if "DTS" in codec_id or "dts" in codec:
            return "dts"
        if "TRUEHD" in codec_id or "truehd" in codec:
            return "thd"
        if "AAC" in codec_id or "aac" in codec:
            return "aac"
        if "FLAC" in codec_id or "flac" in codec:
            return "flac"
        if "OPUS" in codec_id or "opus" in codec:
            return "opus"
        if "VORBIS" in codec_id or "vorbis" in codec:
            return "ogg"
        if "L3" in codec_id or "mp3" in codec:
            return "mp3"
        if "PCM" in codec_id or "pcm" in codec:
            return "wav"
        return "audio"

    if track_type == "subtitles":
        if "UTF8" in codec_id or "subrip" in codec or "srt" in codec:
            return "srt"
        if (
            "MOV_TEXT" in codec_id
            or "TX3G" in codec_id
            or "timed text" in codec
            or "mov_text" in codec
        ):
            return "srt"
        if "ASS" in codec_id or "ass" in codec:
            return "ass"
        if "SSA" in codec_id or "ssa" in codec:
            return "ssa"
        if "WEBVTT" in codec_id or "webvtt" in codec:
            return "vtt"
        if "PGS" in codec_id or "hdmv" in codec:
            return "sup"
        if "VOBSUB" in codec_id:
            return "sub"
        return "sub"

    return "bin"


def parse_duration_seconds(value: Any) -> float:
    if isinstance(value, (int, float)) and value > 0:
        return float(value) / 1_000_000_000
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        numeric = float(raw)
        return numeric / 1_000_000_000 if numeric > 1_000 else numeric
    match = re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", raw)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return 0.0


def format_fps_value(fps: float) -> str:
    common = [
        (24000 / 1001, "23.976"),
        (24, "24"),
        (25, "25"),
        (30000 / 1001, "29.970"),
        (30, "30"),
        (50, "50"),
        (60000 / 1001, "59.940"),
        (60, "60"),
    ]
    for expected, label in common:
        if abs(fps - expected) < 0.02:
            return label
    if abs(fps - round(fps)) < 0.01:
        return str(int(round(fps)))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def parse_fps_rate(value: Any) -> float:
    raw = str(value or "").strip().lower()
    if not raw or raw in {"0/0", "n/a", "none"}:
        return 0.0
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        fps = float(raw)
        return fps if fps > 0 else 0.0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", raw)
    if not match:
        return 0.0
    numerator, denominator = (float(part) for part in match.groups())
    if numerator <= 0 or denominator <= 0:
        return 0.0
    return numerator / denominator


def fps_from_rate(value: Any) -> str:
    fps = parse_fps_rate(value)
    return format_fps_value(fps) if fps > 0 else ""


def fps_from_track(track: dict[str, Any]) -> str:
    properties = track.get("properties", {})
    duration_seconds = parse_duration_seconds(properties.get("default_duration"))
    if duration_seconds > 0:
        return format_fps_value(1 / duration_seconds)
    for key in ("frame_rate", "frames_per_second", "fps", "video_frame_rate"):
        fps = fps_from_rate(properties.get(key) or track.get(key))
        if fps:
            return fps
    return ""


def ffprobe_video_fps_for_source(source: Path) -> tuple[dict[int, str], list[str]]:
    ffprobe = ffprobe_path(auto_install=False)
    if not ffprobe:
        return {}, []
    args = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v",
        "-show_entries",
        "stream=index,avg_frame_rate,r_frame_rate",
        "-of",
        "json",
        str(source),
    ]
    process = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **subprocess_common_kwargs(),
        check=False,
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
    )
    if process.returncode != 0 or not process.stdout.strip():
        return {}, []
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return {}, []

    by_stream_index: dict[int, str] = {}
    by_video_order: list[str] = []
    for stream in payload.get("streams", []):
        fps = fps_from_rate(stream.get("avg_frame_rate")) or fps_from_rate(
            stream.get("r_frame_rate")
        )
        if not fps:
            continue
        by_video_order.append(fps)
        try:
            stream_index = int(stream.get("index"))
        except (TypeError, ValueError):
            continue
        by_stream_index[stream_index] = fps
    return by_stream_index, by_video_order


def video_fps_from_track(
    track: dict[str, Any],
    track_id: int,
    video_index: int,
    ffprobe_fps_by_stream_index: dict[int, str],
    ffprobe_fps_by_video_order: list[str],
) -> str:
    fps = fps_from_track(track)
    if fps:
        return fps
    fps = ffprobe_fps_by_stream_index.get(track_id, "")
    if fps:
        return fps
    if video_index < len(ffprobe_fps_by_video_order):
        return ffprobe_fps_by_video_order[video_index]
    return ""


def first_video_fps_from_identify_payload(identify_payload: dict[str, Any], source: Path | None = None) -> str:
    ffprobe_fps_by_stream_index: dict[int, str] = {}
    ffprobe_fps_by_video_order: list[str] = []
    if source is not None:
        ffprobe_fps_by_stream_index, ffprobe_fps_by_video_order = ffprobe_video_fps_for_source(source)

    video_index = 0
    for track in identify_payload.get("tracks", []):
        if str(track.get("type") or "").lower() != "video":
            continue
        try:
            track_id = int(track.get("id"))
        except (TypeError, ValueError):
            track_id = video_index
        fps = video_fps_from_track(
            track,
            track_id,
            video_index,
            ffprobe_fps_by_stream_index,
            ffprobe_fps_by_video_order,
        )
        if fps:
            return fps
        video_index += 1
    return ""


def detect_video_fps_from_media_path(path: Path) -> str:
    if media_kind_from_path(path) != "video" and path.suffix.lower() not in VIDEO_CONTAINER_EXTENSIONS:
        return ""

    # Priority order:
    # 1) explicit FPS token in raw/video filename, e.g. und.25.h264
    # 2) real media metadata through ffprobe / mkvmerge identify
    # 3) fallback FPS token from parent/release title
    filename_fps = infer_video_fps_from_text(path.stem)
    if filename_fps:
        return filename_fps

    _ffprobe_by_stream, ffprobe_by_order = ffprobe_video_fps_for_source(path)
    if ffprobe_by_order:
        return ffprobe_by_order[0]

    if path.suffix.lower() in VIDEO_CONTAINER_EXTENSIONS:
        try:
            fps = first_video_fps_from_identify_payload(identify_mkv(path), path)
        except UserVisibleError:
            fps = ""
        if fps:
            return fps

    return infer_video_fps_from_text(path.parent.name)


def discover_video_fps_candidate_paths(media_dir: Path) -> list[Path]:
    """Return video/container files that can carry a reliable FPS value.

    Track folders can contain extracted elementary video streams such as .h264/.h265,
    but users also often point the app at a folder that still contains the original
    .mkv/.mp4 source.  ID lookup must therefore scan both groups instead of relying
    only on raw track extensions or release-name tokens.
    """
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            candidates.append(path)

    for path in discover_media_track_paths(media_dir):
        if media_kind_from_path(path) == "video":
            add(path)
    for path in video_sources_in_folder(media_dir):
        add(path)

    return sorted(candidates, key=natural_path_sort_key)


def detect_first_video_fps_from_media_dir(media_dir: Path) -> str:
    # First pass: extracted raw tracks commonly store FPS only in filenames
    # like und.25.h264. Read those tokens before any metadata probing.
    for track_path in discover_video_fps_candidate_paths(media_dir):
        if media_kind_from_path(track_path) == "video":
            fps = infer_video_fps_from_text(track_path.stem)
            if fps:
                return fps

    # Second pass: use actual media metadata when available.
    for track_path in discover_video_fps_candidate_paths(media_dir):
        fps = detect_video_fps_from_media_path(track_path)
        if fps:
            return fps

    # Final fallback: release/folder title. Do not reuse UI's previous FPS here.
    return infer_video_fps_from_text(media_dir.name)


def is_truthy_property(properties: dict[str, Any], *names: str) -> bool:
    for name in names:
        value = properties.get(name)
        if isinstance(value, bool):
            if value:
                return True
        elif str(value).strip().lower() in {"1", "true", "yes"}:
            return True
    return False


def is_forced_extract_track(track: dict[str, Any]) -> bool:
    properties = track.get("properties", {})
    name = str(properties.get("track_name") or track.get("name") or "").lower()
    return is_truthy_property(properties, "forced_track", "forced") or "forced" in name


def is_sdh_extract_track(track: dict[str, Any]) -> bool:
    properties = track.get("properties", {})
    name = str(properties.get("track_name") or track.get("name") or "").lower()
    return is_truthy_property(
        properties,
        "hearing_impaired",
        "hearing_impaired_flag",
    ) or bool(re.search(r"\b(sdh|hi|cc|hearing impaired)\b", name))


def make_numbered_track_name(
    parts: list[str],
    extension: str,
    counters: dict[tuple[str, str], int],
    used_names: set[str],
) -> str:
    base = ".".join(clean_output_component(part, "und") for part in parts if part)
    if not base:
        base = "track"
    key = (base.lower(), extension.lower())
    counters[key] = counters.get(key, 0) + 1
    if counters[key] == 1:
        candidate = f"{base}.{extension}"
    else:
        candidate = f"{base}.({counters[key]}).{extension}"

    while candidate.lower() in used_names:
        counters[key] += 1
        candidate = f"{base}.({counters[key]}).{extension}"
    used_names.add(candidate.lower())
    return candidate


def build_extract_items(identify_payload: dict[str, Any], source: Path | None = None) -> list[ExtractItem]:
    items: list[ExtractItem] = []
    counters: dict[tuple[str, str], int] = {}
    used_names: set[str] = set()
    use_mkvextract = source is None or source_uses_mkvextract(source)
    ffprobe_fps_by_stream_index: dict[int, str] = {}
    ffprobe_fps_by_video_order: list[str] = []
    if source is not None and not use_mkvextract:
        ffprobe_fps_by_stream_index, ffprobe_fps_by_video_order = ffprobe_video_fps_for_source(
            source
        )
    video_index = 0

    for track in identify_payload.get("tracks", []):
        track_id = int(track.get("id"))
        track_type = str(track.get("type") or "track")
        language = language_for_extract_output(track)
        extension = track_output_extension(track)
        prefix_parts: list[str] = []
        suffix_parts: list[str] = []
        if track_type == "subtitles":
            if is_forced_extract_track(track):
                prefix_parts.append("forced")
            if is_sdh_extract_track(track):
                prefix_parts.append("sdh")
        if track_type == "video":
            fps = video_fps_from_track(
                track,
                track_id,
                video_index,
                ffprobe_fps_by_stream_index,
                ffprobe_fps_by_video_order,
            )
            if fps:
                suffix_parts.append(fps)
            video_index += 1

        output_name = make_numbered_track_name(
            [*prefix_parts, language, *suffix_parts],
            extension,
            counters,
            used_names,
        )
        codec = str(track.get("codec") or "")
        label = ui_text(
            "extract_label_track",
            track_id=track_id,
            track_type=track_type,
            language=language,
            codec=codec,
        )
        items.append(
            ExtractItem(
                key=f"track:{track_id}",
                kind="track",
                item_id=track_id,
                label=label,
                output_name=output_name,
                language=language,
                extension=extension,
                track_type=track_type,
                name_prefix_parts=tuple(prefix_parts),
                name_suffix_parts=tuple(suffix_parts),
            )
        )

    if use_mkvextract:
        for attachment in identify_payload.get("attachments", []):
            attachment_id = int(attachment.get("id"))
            properties = attachment.get("properties", {})
            name = str(
                properties.get("file_name")
                or attachment.get("file_name")
                or attachment.get("name")
                or f"attachment.{attachment_id}.bin"
            )
            output_name = dedupe_plain_filename(name, used_names)
            content_type = str(properties.get("content_type") or attachment.get("content_type") or "")
            label = ui_text(
                "extract_label_attachment",
                attachment_id=attachment_id,
                description=content_type or output_name,
            )
            items.append(
                ExtractItem(
                    key=f"attachment:{attachment_id}",
                    kind="attachment",
                    item_id=attachment_id,
                    label=label,
                    output_name=output_name,
                )
            )

    if identify_payload.get("chapters"):
        output_name = dedupe_plain_filename("chapters.txt", used_names)
        items.append(
            ExtractItem(
                key="chapters",
                kind="chapters",
                item_id=None,
                label=ui_text("extract_label_chapters") if use_mkvextract else "Chapters | ffmetadata",
                output_name=output_name,
            )
        )

    if identify_payload.get("global_tags") or identify_payload.get("track_tags"):
        output_name = dedupe_plain_filename("tags.xml" if use_mkvextract else "metadata.txt", used_names)
        items.append(
            ExtractItem(
                key="tags",
                kind="tags",
                item_id=None,
                label=ui_text("extract_label_tags") if use_mkvextract else "Metadata | ffmetadata",
                output_name=output_name,
            )
        )

    return items


def first_video_fps_from_items(items: list[ExtractItem]) -> str:
    for item in items:
        if item.kind != "track":
            continue
        match = re.search(
            r"(?:^|\.)(\d{2,3}(?:\.\d+)?)(?:\.\(\d+\))?(?:\.[^.]+)$",
            item.output_name,
        )
        if match:
            return match.group(1)
    return ""


def build_mkvextract_args(
    source: Path,
    output_dir: Path,
    items: list[ExtractItem],
) -> list[str]:
    mkvextract = third_party_tool_path("mkvextract")
    if not mkvextract:
        raise UserVisibleError(ui_text("error_mkvextract_missing"))
    selected = [item for item in items if item.selected]
    if not selected:
        raise UserVisibleError(ui_text("error_extract_none_selected"))

    output_dir.mkdir(parents=True, exist_ok=True)
    args = [mkvextract, str(source)]

    track_items = [item for item in selected if item.kind == "track"]
    if track_items:
        args.append("tracks")
        args.extend(
            f"{item.item_id}:{output_dir / item.output_name}"
            for item in track_items
            if item.item_id is not None
        )

    attachment_items = [item for item in selected if item.kind == "attachment"]
    if attachment_items:
        args.append("attachments")
        args.extend(
            f"{item.item_id}:{output_dir / item.output_name}"
            for item in attachment_items
            if item.item_id is not None
        )

    for item in selected:
        if item.kind == "chapters":
            args.extend(["chapters", "--simple", str(output_dir / item.output_name)])
        elif item.kind == "tags":
            args.extend(["tags", str(output_dir / item.output_name)])

    return args


def source_uses_mkvextract(source: Path) -> bool:
    return source.suffix.lower() in MATROSKA_EXTRACT_EXTENSIONS


def ffmpeg_extract_extension(item: ExtractItem) -> str:
    """Return a real filename extension that ffmpeg can infer as an output format."""
    ext = item.extension.lower().lstrip(".")
    if ext and ext not in {"video", "audio", "track", "bin"}:
        return ext

    label = item.label.lower()
    output = item.output_name.lower()
    probe = f"{label} {output}"

    if ext == "video" or "| video |" in probe:
        if "avc" in probe or "h.264" in probe or "h264" in probe:
            return "h264"
        if "hevc" in probe or "h.265" in probe or "h265" in probe:
            return "h265"
        if "mpeg-2" in probe or "mpeg2" in probe:
            return "m2v"
        if "av1" in probe or "vp9" in probe:
            return "mkv"
        return "mkv"

    if ext == "audio" or "| audio |" in probe:
        if "aac" in probe:
            return "aac"
        if "e-ac-3" in probe or "eac3" in probe:
            return "eac3"
        if "ac-3" in probe or "ac3" in probe:
            return "ac3"
        if "dts" in probe:
            return "dts"
        if "flac" in probe:
            return "flac"
        if "opus" in probe:
            return "opus"
        if "mp3" in probe:
            return "mp3"
        if "pcm" in probe or "wav" in probe:
            return "wav"
        return "mka"

    return ext or "bin"


def ffmpeg_extract_output_path(output_dir: Path, item: ExtractItem, used_paths: set[str]) -> Path:
    extension = ffmpeg_extract_extension(item)
    original = Path(item.output_name)
    stem = original.stem or "track"

    if original.suffix.lower().lstrip(".") == extension:
        candidate = output_dir / original.name
    else:
        candidate = output_dir / f"{stem}.{extension}"

    counter = 2
    while str(candidate).lower() in used_paths:
        candidate = output_dir / f"{stem}.{counter}.{extension}"
        counter += 1
    used_paths.add(str(candidate).lower())
    return candidate


def ffmpeg_video_bsf_for_extension(extension: str) -> str:
    ext = extension.lower().lstrip(".")
    if ext == "h264":
        return "h264_mp4toannexb"
    if ext in {"h265", "hevc"}:
        return "hevc_mp4toannexb"
    return ""


def item_is_subtitle_track(item: ExtractItem) -> bool:
    if item.track_type == "subtitles":
        return True
    return "| subtitles |" in item.label.lower()


def ffmpeg_subtitle_encoder_for_extension(extension: str) -> str:
    ext = extension.lower().lstrip(".")
    return {
        "srt": "srt",
        "vtt": "webvtt",
        "ass": "ass",
    }.get(ext, "")


def build_ffmpeg_extract_args(
    source: Path,
    output_dir: Path,
    items: list[ExtractItem],
) -> list[str]:
    ffmpeg = ffmpeg_path()
    selected = [item for item in items if item.selected]
    if not selected:
        raise UserVisibleError(ui_text("error_extract_none_selected"))

    unsupported_items = [item for item in selected if item.kind not in {"track", "chapters", "tags"}]
    if unsupported_items:
        raise UserVisibleError(ui_text("error_extract_non_matroska_metadata"))

    output_dir.mkdir(parents=True, exist_ok=True)
    args = [ffmpeg, "-hide_banner", "-y", "-i", str(source)]

    used_paths: set[str] = set()
    for item in selected:
        if item.kind != "track" or item.item_id is None:
            continue
        output_path = ffmpeg_extract_output_path(output_dir, item, used_paths)
        output_extension = output_path.suffix.lower().lstrip(".")
        args.extend(["-map", f"0:{item.item_id}"])
        subtitle_encoder = (
            ffmpeg_subtitle_encoder_for_extension(output_extension)
            if item_is_subtitle_track(item)
            else ""
        )
        if subtitle_encoder:
            args.extend(["-c:s", subtitle_encoder])
        else:
            args.extend(["-c", "copy"])
            bsf = ffmpeg_video_bsf_for_extension(output_extension)
            if bsf:
                args.extend(["-bsf:v", bsf])
        args.append(str(output_path))

    for item in selected:
        if item.kind == "chapters":
            output_path = output_dir / item.output_name
            args.extend([
                "-map_metadata",
                "-1",
                "-map_chapters",
                "0",
                "-f",
                "ffmetadata",
                str(output_path),
            ])
        elif item.kind == "tags":
            output_path = output_dir / item.output_name
            args.extend([
                "-map_metadata",
                "0",
                "-map_chapters",
                "-1",
                "-f",
                "ffmetadata",
                str(output_path),
            ])

    return args


def build_extract_command(
    source: Path,
    output_dir: Path,
    items: list[ExtractItem],
) -> tuple[list[str], str, str]:
    if source_uses_mkvextract(source):
        return (
            build_mkvextract_args(source, output_dir, items),
            "log_mkvextract_command",
            "error_mkvextract_exit",
        )
    return (
        build_ffmpeg_extract_args(source, output_dir, items),
        "log_ffmpeg_extract_command",
        "error_ffmpeg_extract_exit",
    )
