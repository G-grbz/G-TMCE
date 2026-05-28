# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import hashlib
import io
import json
import mimetypes
import os
import platform
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:
    Image = None
    ImageOps = None
    ImageTk = None


APP_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = APP_DIR / "mkv.mtxcfg"
APP_NAME = "G-TMCE"
LOGO_PATH = APP_DIR / "logo.png"
SETTINGS_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "mkv-creator-ui"
    / "settings.json"
)
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"
THIRD_PARTY_DIR = APP_DIR / "3rdParty"
THIRD_PARTY_BIN_DIR = THIRD_PARTY_DIR / "bin"
THIRD_PARTY_DOWNLOADS_DIR = THIRD_PARTY_DIR / ".downloads"
THIRD_PARTY_MKVTOOLNIX_APPDIR = THIRD_PARTY_BIN_DIR / "mkvtoolnix"
THIRD_PARTY_MKVTOOLNIX_STAGING_DIR = THIRD_PARTY_DIR / ".mkvtoolnix-new"
THIRD_PARTY_STATE_PATH = THIRD_PARTY_DIR / "installed.json"
MKVTOOLNIX_APPIMAGE_INDEX_URL = "https://mkvtoolnix.download/appimage/"
FFMPEG_RELEASE_API_URL = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
THIRD_PARTY_USER_AGENT = f"{APP_NAME}/1.0 Python/{sys.version_info.major}.{sys.version_info.minor}"

UI_COLORS = {
    "window": "#f4f7fb",
    "surface": "#ffffff",
    "surface_alt": "#eef3f9",
    "border": "#d8e0ec",
    "text": "#172033",
    "muted": "#5d6978",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_pressed": "#1e40af",
    "disabled": "#aeb8c6",
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
        "error_tmdb_svg_logo": "TMDB returned an SVG for {name}; no PNG logo was available.",
        "error_pillow_image_convert": "Pillow must be installed to convert images.",
        "error_pillow_small_cover": "Pillow must be installed to create small_cover.jpg.",
        "log_file_not_found_skipped": "{name} was not found; skipped.",
        "log_file_prepare_skipped": "{name} could not be prepared; skipped: {error}",
        "log_tags_exists": "tags.xml already exists; skipped.",
        "log_tags_ready": "tags.xml is ready.",
        "log_tmdb_title": "TMDB title: {title}",
        "log_cover_ready": "cover.jpg is ready.",
        "log_small_cover_ready": "small_cover.jpg is ready.",
        "log_small_cover_skipped": "small_cover.jpg could not be prepared; skipped: {error}",
        "log_l2a_ready": "l2a.jpg is ready.",
        "log_l2p_ready": "l2p.png is ready.",
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
        "section_create_mkv": "Create MKV",
        "path_template": "Template config (optional)",
        "path_track_folder": "Track folder",
        "path_output_mkv": "Output MKV",
        "button_browse": "Browse",
        "button_show": "Show",
        "button_update_third_party": "Update Tools",
        "label_image_language": "Artwork language",
        "label_tag_language": "Tag language",
        "button_find_id": "Find ID",
        "label_mkv_title": "MKV title",
        "label_default_tracks": "Default tracks",
        "label_audio_order": "Audio priority",
        "label_subtitle_order": "Subtitle priority",
        "option_include_extra_subtitles": "Include additional subtitles",
        "option_download_before_mux": "Prepare artwork and tags before muxing",
        "label_auto_chapters": "Automatic chapters",
        "option_create_if_missing": "Create if missing",
        "label_chapter_name": "Name",
        "label_chapter_interval": "Interval (min)",
        "label_chapter_start": "Start #",
        "label_chapter_end": "End (min)",
        "button_scan_tracks": "Adjust Audio",
        "window_audio_adjust_title": "Audio Adjust",
        "audio_adjust_hint": "Select audio tracks. A + value creates silence in the selected output codec and prepends it; a - value cuts that many seconds from the beginning. Leave duration empty or 0 to only change codec/output settings. Volume 1x keeps the original level; 2x-5x boosts it.",
        "heading_audio_file": "Audio file",
        "heading_audio_delta": "Delta (s)",
        "heading_audio_codec": "Codec",
        "heading_audio_bitrate": "Bitrate",
        "heading_audio_rate": "Sample rate",
        "heading_audio_layout": "Layout",
        "heading_audio_volume": "Volume",
        "heading_audio_speed": "Audio FPS Sync",
        "button_apply_audio_adjust": "Apply",
        "error_ffmpeg_missing": "ffmpeg is not available in 3rdParty.",
        "error_audio_adjust_none": "Select at least one audio track and enter a duration or change codec/output settings.",
        "error_audio_adjust_numeric": "Duration value must be numeric, for example +0.967 or -0.967.",
        "error_audio_codec_unsupported": "Unsupported audio codec: {codec}",
        "log_audio_adjust_ready": "Audio adjustment ready: {name}",
        "log_audio_adjust_command": "Audio ffmpeg command:",
        "status_adjusting_audio": "Adjusting audio...",
        "button_download_assets": "Download Artwork/Tags",
        "button_write_config": "Write Config",
        "button_create_mkv": "Create MKV",
        "button_show_log": "Show Log",
        "section_extract": "MKV Extract",
        "path_source_mkv": "Source MKV",
        "path_extract_folder": "Extraction folder",
        "dialog_template_title": "Select MKVToolNix config",
        "filetype_all": "All files",
        "filetype_matroska": "Matroska video",
        "dialog_config_error": "Config error",
        "dialog_track_folder_title": "Select track folder",
        "dialog_output_mkv_title": "Select output MKV",
        "dialog_source_mkv_title": "Select source MKV",
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
        "log_output_default_used": "Output path was empty; using the default: {path}",
        "error_tmdb_media_type": "TMDB type must be movie or tv.",
        "error_tmdb_api_empty": "TMDB API key is required.",
        "error_tmdb_id_empty": "TMDB ID is required.",
        "error_tmdb_id_numeric": "TMDB ID must be numeric.",
        "error_source_mkv_not_selected": "Source MKV is not selected.",
        "log_tracks_found": "Tracks found: {count}",
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
        "log_config_written": "Config written: {path}",
        "status_writing_config": "Writing config...",
        "error_output_exists_choose": "{name} already exists. Choose a different name or move the existing file.",
        "log_skipped_optional_tracks": "Skipped optional items: {items}",
        "log_mkvmerge_command": "mkvmerge command:",
        "error_mkvmerge_exit": "mkvmerge exited with error code: {code}",
        "log_mkvmerge_warnings": "mkvmerge completed with warnings.",
        "log_mkv_created": "MKV created: {path}",
        "status_creating_mkv": "Creating MKV...",
        "button_scan_mkv": "Scan MKV",
        "button_toggle_selection": "Toggle Selection",
        "button_select_all": "Select All",
        "button_clear_all": "Clear All",
        "button_extract_selected": "Extract Selected",
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
        "error_mkvextract_exit": "mkvextract exited with error code: {code}",
        "log_mkvextract_warnings": "mkvextract completed with warnings.",
        "log_tracks_extracted": "Tracks extracted: {path}",
        "log_folder_set_for_mux": "Track folder updated for muxing.",
        "status_scanning_mkv": "Scanning MKV...",
        "status_extracting_tracks": "Extracting tracks...",
        "status_updating_third_party": "Checking/downloading tools...",
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
        "error_tmdb_svg_logo": "{name} için TMDB SVG döndürdü; PNG logo bulunamadı.",
        "error_pillow_image_convert": "Görsel dönüştürme için Pillow kurulu olmalı.",
        "error_pillow_small_cover": "small_cover.jpg üretmek için Pillow kurulu olmalı.",
        "log_file_not_found_skipped": "{name} bulunamadı, atlandı.",
        "log_file_prepare_skipped": "{name} hazırlanamadı, atlandı: {error}",
        "log_tags_exists": "tags.xml zaten var, atlandı.",
        "log_tags_ready": "tags.xml hazır.",
        "log_tmdb_title": "TMDB içerik: {title}",
        "log_cover_ready": "cover.jpg hazır.",
        "log_small_cover_ready": "small_cover.jpg hazır.",
        "log_small_cover_skipped": "small_cover.jpg hazırlanamadı, atlandı: {error}",
        "log_l2a_ready": "l2a.jpg hazır.",
        "log_l2p_ready": "l2p.png hazır.",
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
        "section_create_mkv": "MKV Oluştur",
        "path_template": "Şablon config (opsiyonel)",
        "path_track_folder": "Parça klasörü",
        "path_output_mkv": "Çıktı MKV",
        "button_browse": "Seç",
        "button_show": "Göster",
        "button_update_third_party": "Araçları Güncelle",
        "label_image_language": "Görsel dili",
        "label_tag_language": "Tag dili",
        "button_find_id": "ID Bul",
        "label_mkv_title": "MKV başlığı",
        "label_default_tracks": "Varsayılan iz",
        "label_audio_order": "Ses sırası",
        "label_subtitle_order": "Altyazı sırası",
        "option_include_extra_subtitles": "Fazla altyazıları ekle",
        "option_download_before_mux": "MKV oluşturmadan önce görsel/tag hazırla",
        "label_auto_chapters": "Otomatik chapter",
        "option_create_if_missing": "Yoksa oluştur",
        "label_chapter_name": "Ad",
        "label_chapter_interval": "Aralık dk",
        "label_chapter_start": "Başlangıç",
        "label_chapter_end": "Bitiş dk",
        "button_scan_tracks": "Ses Ayarla",
        "window_audio_adjust_title": "Ses Ayarla",
        "audio_adjust_hint": "Ses parçalarını seç. + değer, girilen süre kadar seçili çıkış kodekinde sessizlik oluşturup parçanın başına ekler; - değer, seçili parçanın başından girilen süre kadar keser. Sadece kodek/çıkış ayarı değiştirmek için süreyi boş veya 0 bırak. Ses 1x orijinal seviyeyi korur; 2x-5x yükseltir.",
        "heading_audio_file": "Ses dosyası",
        "heading_audio_delta": "Süre (sn)",
        "heading_audio_codec": "Kodek",
        "heading_audio_bitrate": "Bitrate",
        "heading_audio_rate": "Sample rate",
        "heading_audio_layout": "Layout",
        "heading_audio_volume": "Ses",
        "heading_audio_speed": "FPS Eşitle",
        "button_apply_audio_adjust": "Uygula",
        "error_ffmpeg_missing": "ffmpeg 3rdParty içinde kullanıma hazır değil.",
        "error_audio_adjust_none": "En az bir ses parçası seç ve süre gir ya da kodek/çıkış ayarını değiştir.",
        "error_audio_adjust_numeric": "Süre sayısal olmalı, örnek +0.967 veya -0.967.",
        "error_audio_codec_unsupported": "Desteklenmeyen ses kodeki: {codec}",
        "log_audio_adjust_ready": "Ses ayarı hazır: {name}",
        "log_audio_adjust_command": "Ses ffmpeg komutu:",
        "status_adjusting_audio": "Ses ayarlanıyor...",
        "button_download_assets": "Görsel/Tag İndir",
        "button_write_config": "Config Yaz",
        "button_create_mkv": "MKV Oluştur",
        "button_show_log": "Günlüğü Göster",
        "section_extract": "MKV Extract",
        "path_source_mkv": "Kaynak MKV",
        "path_extract_folder": "Çıkarma klasörü",
        "dialog_template_title": "MKVToolNix config seç",
        "filetype_all": "Tüm dosyalar",
        "filetype_matroska": "Matroska video",
        "dialog_config_error": "Config hatası",
        "dialog_track_folder_title": "Parça klasörü seç",
        "dialog_output_mkv_title": "Çıktı MKV seç",
        "dialog_source_mkv_title": "Kaynak MKV seç",
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
        "log_output_default_used": "Çıktı yolu boştu, varsayılan kullanılıyor: {path}",
        "error_tmdb_media_type": "TMDB türü movie veya tv olmalı.",
        "error_tmdb_api_empty": "TMDB API key boş.",
        "error_tmdb_id_empty": "TMDB ID boş.",
        "error_tmdb_id_numeric": "TMDB ID sayısal olmalı.",
        "error_source_mkv_not_selected": "Kaynak MKV seçilmedi.",
        "log_tracks_found": "Bulunan parça sayısı: {count}",
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
        "log_config_written": "Config yazıldı: {path}",
        "status_writing_config": "Config yazılıyor...",
        "error_output_exists_choose": "{name} zaten var. Farklı ad ver veya mevcut dosyayı taşı.",
        "log_skipped_optional_tracks": "Atlanan opsiyonel parçalar: {items}",
        "log_mkvmerge_command": "mkvmerge komutu:",
        "error_mkvmerge_exit": "mkvmerge hata kodu ile bitti: {code}",
        "log_mkvmerge_warnings": "mkvmerge uyarılarla tamamlandı.",
        "log_mkv_created": "MKV oluşturuldu: {path}",
        "status_creating_mkv": "MKV oluşturuluyor...",
        "button_scan_mkv": "MKV Tara",
        "button_toggle_selection": "Seçimi Değiştir",
        "button_select_all": "Tümünü Seç",
        "button_clear_all": "Tümünü Bırak",
        "button_extract_selected": "Seçileni Çıkar",
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
        "error_mkvextract_exit": "mkvextract hata kodu ile bitti: {code}",
        "log_mkvextract_warnings": "mkvextract uyarılarla tamamlandı.",
        "log_tracks_extracted": "Parçalar çıkarıldı: {path}",
        "log_folder_set_for_mux": "Parça klasörü birleştirme için güncellendi.",
        "status_scanning_mkv": "MKV taranıyor...",
        "status_extracting_tracks": "Parçalar çıkarılıyor...",
        "status_updating_third_party": "Araçlar denetleniyor/indiriliyor...",
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
TRACK_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | SUBTITLE_EXTENSIONS
STANDARD_ATTACHMENT_NAMES = ("cover.jpg", "small_cover.jpg", "l2a.jpg", "l2p.png")
MUX_UNKNOWN_LANGUAGE = "und"
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


@dataclass
class AppSettings:
    template_path: Path | None
    media_dir: Path
    output_path: Path
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
    chapter_interval_minutes: str
    chapter_name: str
    chapter_start_number: str
    chapter_end_minutes: str


@dataclass
class ChapterOptions:
    enabled: bool
    interval_minutes: str
    name: str
    start_number: str
    end_minutes: str


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
    "mkvmerge": "mkvmerge",
    "mkvextract": "mkvextract",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
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


def third_party_request(url: str, accept: str = "*/*") -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": THIRD_PARTY_USER_AGENT,
        },
    )


def read_third_party_text(url: str) -> str:
    with urllib.request.urlopen(third_party_request(url), timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def read_third_party_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(
        third_party_request(url, "application/vnd.github+json"),
        timeout=45,
    ) as response:
        payload = response.read().decode("utf-8", errors="replace")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("JSON response is not an object")
    return value


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
    if platform_name() != "linux" or platform_arch() not in {"x86_64", "amd64"}:
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


def ffmpeg_asset_name() -> str:
    if platform_name() != "linux":
        raise unsupported_third_party("FFmpeg")
    arch = platform_arch()
    if arch in {"x86_64", "amd64"}:
        return "ffmpeg-master-latest-linux64-gpl.tar.xz"
    if arch in {"aarch64", "arm64"}:
        return "ffmpeg-master-latest-linuxarm64-gpl.tar.xz"
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
    THIRD_PARTY_DIR.mkdir(parents=True, exist_ok=True)
    temporary = THIRD_PARTY_STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(THIRD_PARTY_STATE_PATH)


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
        with urllib.request.urlopen(third_party_request(url), timeout=300) as response:
            with temporary.open("wb") as handle:
                shutil.copyfileobj(response, handle, 1024 * 1024)
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
    destination = THIRD_PARTY_BIN_DIR / tool_name
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
            text=True,
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
        THIRD_PARTY_DIR / "mkvtoolnix",
        THIRD_PARTY_DIR / "ffmpeg",
    ):
        remove_path(path)


def third_party_group_installed(group: str) -> bool:
    if group == "mkvtoolnix" and not mkvtoolnix_appdir_ready():
        return False
    return all(
        (THIRD_PARTY_BIN_DIR / tool).exists()
        and os.access(THIRD_PARTY_BIN_DIR / tool, os.X_OK)
        for tool in THIRD_PARTY_GROUP_TOOLS[group]
    )


def install_mkvtoolnix(latest: dict[str, str]) -> dict[str, str]:
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
    for member in archive.getmembers():
        member_path = (destination / member.name).resolve()
        if member_path != root and root not in member_path.parents:
            raise ValueError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk():
            link_path = (member_path.parent / member.linkname).resolve()
            if link_path != root and root not in link_path.parents:
                raise ValueError(f"unsafe archive link: {member.name}")
    archive.extractall(destination)


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
        with tarfile.open(downloaded, "r:*") as archive:
            safe_extract_tar(archive, extract_root)
        roots = [path for path in extract_root.iterdir() if path.is_dir()]
        extracted_root = roots[0] if len(roots) == 1 else extract_root
        for tool in ("ffmpeg", "ffprobe"):
            candidate = extracted_root / "bin" / tool
            if not candidate.exists():
                raise FileNotFoundError(candidate)
            mark_executable(candidate)

        for tool in ("ffmpeg", "ffprobe"):
            install_third_party_tool(tool, extracted_root / "bin" / tool)
        cleanup_third_party_workdirs()
        return {
            "version": latest["version"],
            "asset_name": filename,
            "download_url": latest["download_url"],
        }
    except (OSError, RuntimeError, tarfile.TarError, ValueError) as exc:
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
    if tool_path.exists() and os.access(tool_path, os.X_OK):
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
            executable_name = THIRD_PARTY_EXECUTABLE_NAMES.get(tool_name, tool_name)
            return tool_name if executable_name != tool_name else path
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
        executable_name = THIRD_PARTY_EXECUTABLE_NAMES.get(tool_name, tool_name)
        return tool_name if executable_name != tool_name else tool_path
    if required:
        raise UserVisibleError(ui_text("error_third_party_missing", name=tool_name))
    return None


def third_party_subprocess_executable(args: list[str]) -> str | None:
    if not args:
        return None
    tool_name = Path(str(args[0])).name
    if tool_name not in THIRD_PARTY_TOOL_GROUPS:
        return None
    return installed_third_party_tool_path(tool_name)


def third_party_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = str(THIRD_PARTY_BIN_DIR) + os.pathsep + env.get("PATH", "")
    env.pop("APPIMAGE_EXTRACT_AND_RUN", None)
    return env


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


def tmdb_output_path(media_dir: Path, title: str) -> Path:
    return media_dir / f"{safe_filename_stem(title)}.mkv"


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


def release_name_candidates(settings: AppSettings) -> list[str]:
    candidates = [
        settings.media_dir.name,
        settings.output_path.parent.name,
        settings.output_path.stem,
    ]
    result: list[str] = []
    for candidate in candidates:
        value = candidate.strip()
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
            "destination": "output.mkv",
            "destinationAuto": "output.mkv",
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
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(preferences, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        SETTINGS_PATH.chmod(0o600)
    except OSError:
        pass


def template_output_name(config: dict[str, Any]) -> str:
    destination = config.get("global", {}).get("destination") or "output.mkv"
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
) -> TrackItem | None:
    candidates = [item for item in ordered if track_type_value(item) == 2]
    if not candidates or not language_order:
        return None

    audio_languages = {
        track_language_value(item)
        for item in ordered
        if track_type_value(item) == 0
    }

    for language in language_order:
        matches = [item for item in candidates if track_language_value(item) == language]
        if not matches:
            continue
        forced_matches = [item for item in matches if is_forced_track_item(item)]
        if forced_matches:
            return forced_matches[0]
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
    selected_subtitle = select_default_subtitle_item(ordered, subtitle_order)

    set_default_track_flags(items, 0, selected_audio)
    set_default_track_flags(items, 2, selected_subtitle)

    ordered = reorder_track_type_by_language(ordered, 0, audio_order, selected_audio)
    ordered = reorder_track_type_by_language(ordered, 2, subtitle_order, selected_subtitle)
    return ordered


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


def infer_language_from_filename(path: Path, unknown_language: str = "und") -> str:
    tokens = [token for token in re.split(r"[._\-\s]+", path.stem.lower()) if token]
    for token in tokens:
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


def infer_video_fps_from_filename(path: Path) -> str:
    if media_kind_from_path(path) != "video":
        return ""
    pattern = (
        r"(?:^|[._\-\s])"
        r"(23\.976|23\.98|24|25|29\.970|29\.97|30|50|59\.940|59\.94|60|24000/1001|30000/1001|60000/1001)"
        r"(?:$|[._\-\s])"
    )
    match = re.search(pattern, path.stem)
    return match.group(1) if match else ""


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
        fps = infer_video_fps_from_filename(path)
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
    fps = infer_video_fps_from_filename(path)
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
            fps = infer_video_fps_from_filename(path)
            if fps:
                track["defaultDuration"] = normalize_video_fps(fps)
        if kind == "subtitle":
            track.update(infer_subtitle_track_flags(path, unknown_language))
        return entry, object_id_seed + 2

    return make_minimal_track_entry(path, object_id_seed, unknown_language)


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
    for name in STANDARD_ATTACHMENT_NAMES:
        path = media_dir / name
        if path.exists():
            attachments.append(
                {
                    "MIMEType": guess_mime_type(path),
                    "description": "",
                    "fileName": str(path),
                    "name": name,
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

    file_id = 0
    for item in items:
        item.file_id = file_id
        file_id += 1 + len(item.append_paths)

    return items, missing_optional, missing_required


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
                "mime": attachment.get("MIMEType") or guess_mime_type(path),
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

    for name in STANDARD_ATTACHMENT_NAMES:
        if name.lower() in used_names:
            continue
        path = media_dir / name
        if not path.exists():
            continue
        result.append(
            {
                "path": path,
                "name": name,
                "mime": guess_mime_type(path),
                "description": "",
            }
        )
        used_names.add(name.lower())

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


def detect_item_duration_seconds(item: TrackItem) -> float:
    mkvmerge = third_party_tool_path("mkvmerge", required=False)
    if not mkvmerge:
        return 0.0
    args = [mkvmerge, "--identification-format", "json", "--identify", str(item.path)]
    process = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
    )
    if process.returncode > 1:
        return 0.0
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return 0.0

    durations = [
        parse_duration_seconds(payload.get("container", {}).get("properties", {}).get("duration"))
    ]
    for track in payload.get("tracks", []):
        durations.append(parse_duration_seconds(track.get("properties", {}).get("duration")))
    return max(durations, default=0.0)


def detect_media_duration_seconds(items: list[TrackItem]) -> float:
    ordered = sorted(
        items,
        key=lambda item: 0 if is_video_entry(item.entry) else 1,
    )
    for item in ordered:
        duration = detect_item_duration_seconds(item)
        if duration > 0:
            return duration
    return 0.0


def write_auto_chapters_file(
    path: Path,
    options: ChapterOptions,
    duration_seconds: float,
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

    current_minutes = interval_minutes * start_number
    if current_minutes > end_minutes:
        raise UserVisibleError(ui_text("error_chapter_start_after_end"))

    lines: list[str] = []
    chapter_number = start_number
    while current_minutes <= end_minutes + 1e-9:
        marker = f"CHAPTER{chapter_number:02d}"
        lines.append(f"{marker}={format_chapter_timestamp(current_minutes * 60)}")
        lines.append(f"{marker}NAME= {name} {chapter_number}")
        chapter_number += 1
        current_minutes += interval_minutes

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def resolve_chapter_path(
    config: dict[str, Any],
    media_dir: Path,
    items: list[TrackItem],
    options: ChapterOptions | None,
) -> tuple[Path | None, list[str]]:
    global_config = config.get("global", {})
    chapters_name = basename_from_config_path(str(global_config.get("chapters", "chapters.txt")))
    if not chapters_name:
        chapters_name = "chapters.txt"

    chapters_path = media_dir / chapters_name
    if chapters_path.exists():
        return chapters_path, []

    if options is not None and options.enabled:
        duration_seconds = detect_media_duration_seconds(items)
        return write_auto_chapters_file(chapters_path, options, duration_seconds), []

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
) -> tuple[list[str], list[str]]:
    _unknown_language = normalise_language(tag_language) if tag_language else MUX_UNKNOWN_LANGUAGE
    mkvmerge = third_party_tool_path("mkvmerge")
    if not mkvmerge:
        raise UserVisibleError(ui_text("error_mkvmerge_missing"))

    items, missing_optional, _ = discover_track_items(
        config, media_dir, include_extra_subtitles, _unknown_language
    )
    if not items:
        raise UserVisibleError(ui_text("error_mux_no_files"))
    apply_video_fps_override(items, video_fps)
    ordered = apply_default_track_preferences(
        config,
        items,
        audio_language_order,
        subtitle_language_order,
    )

    attachments, missing_attachments = discover_attachments(config, media_dir)
    missing_optional.extend(missing_attachments)

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
) -> Path:
    _unknown_language = normalise_language(tag_language) if tag_language else MUX_UNKNOWN_LANGUAGE
    items, _, _ = discover_track_items(config, media_dir, include_extra_subtitles, _unknown_language)
    apply_video_fps_override(items, video_fps)
    ordered = apply_default_track_preferences(
        config,
        items,
        audio_language_order,
        subtitle_language_order,
    )
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
        params = dict(params)
        params["api_key"] = self.api_key
        query = urllib.parse.urlencode(params)
        url = f"{TMDB_API_BASE}{path}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "g-tmce/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
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

    def download_bytes(self, file_path: str) -> bytes:
        url = f"{TMDB_IMAGE_BASE}{file_path}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "g-tmce/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.URLError as exc:
            raise UserVisibleError(
                ui_text("error_image_download_failed", reason=exc.reason)
            ) from exc


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


def make_small_cover(source: Path, destination: Path) -> None:
    if Image is None:
        raise UserVisibleError(ui_text("error_pillow_small_cover"))
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        resized = image.resize((120, 180), Image.Resampling.LANCZOS)
        resized.save(destination, "JPEG", quality=95)


def download_optional_tmdb_image(
    client: TMDBClient,
    image: dict[str, Any] | None,
    destination: Path,
    image_format: str,
    log: Callable[[str], None],
    ready_message: str,
) -> bool:
    if image is None:
        log(ui_text("log_file_not_found_skipped", name=destination.name))
        return False

    file_path = str(image["file_path"])
    try:
        image_bytes = client.download_bytes(file_path)
        write_original_or_convert(image_bytes, file_path, destination, image_format)
    except UserVisibleError as exc:
        log(ui_text("log_file_prepare_skipped", name=destination.name, error=exc))
        return False

    log(ready_message)
    return True


def detail_original_title(details: dict[str, Any]) -> str:
    return str(details.get("original_title") or details.get("original_name") or "")


def detail_release_date(details: dict[str, Any]) -> str:
    return str(details.get("release_date") or details.get("first_air_date") or "")


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
) -> None:
    tags_path = settings.media_dir / "tags.xml"
    if tags_path.exists():
        log(ui_text("log_tags_exists"))
        return

    details = client.get_json(
        f"/{media_type}/{tmdb_id}",
        {
            "language": detail_language(language),
            "append_to_response": "credits,external_ids",
        },
    )
    write_tmdb_tags_file(tags_path, details, media_type, tmdb_id, language)
    log(ui_text("log_tags_ready"))


def download_tmdb_assets(
    settings: AppSettings,
    log: Callable[[str], None],
) -> str:
    client = TMDBClient(settings.api_key)
    language = normalise_language(settings.image_language)
    tag_language = normalise_language(settings.tag_language)
    media_type = settings.media_type
    tmdb_id = settings.tmdb_id

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
    if download_optional_tmdb_image(
        client,
        poster,
        cover,
        "JPEG",
        log,
        ui_text("log_cover_ready"),
    ):
        try:
            make_small_cover(cover, settings.media_dir / "small_cover.jpg")
            log(ui_text("log_small_cover_ready"))
        except UserVisibleError as exc:
            log(ui_text("log_small_cover_skipped", error=exc))

    download_optional_tmdb_image(
        client,
        backdrop,
        settings.media_dir / "l2a.jpg",
        "JPEG",
        log,
        ui_text("log_l2a_ready"),
    )

    download_optional_tmdb_image(
        client,
        logo,
        settings.media_dir / "l2p.png",
        "PNG",
        log,
        ui_text("log_l2p_ready"),
    )

    ensure_tmdb_tags_file(settings, client, media_type, tmdb_id, tag_language, log)

    return title


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
    if source_name:
        query = f"{query} [{source_name}]"
    return tmdb_id, title, found_year, query


def tmdb_title_for_language(settings: AppSettings, tmdb_id: str, language: str) -> str:
    client = TMDBClient(settings.api_key)
    details = client.get_json(
        f"/{settings.media_type}/{tmdb_id}",
        {"language": detail_language(normalise_language(language))},
    )
    return title_from_details(details)


def command_preview(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def ffmpeg_path() -> str:
    ffmpeg = third_party_tool_path("ffmpeg")
    if not ffmpeg:
        raise UserVisibleError(ui_text("error_ffmpeg_missing"))
    return ffmpeg


def ffprobe_path(auto_install: bool = True) -> str | None:
    return third_party_tool_path("ffprobe", required=False, auto_install=auto_install)


def parse_seconds_delta(value: str) -> float:
    raw = value.strip().replace(",", ".")
    if not raw:
        return 0.0
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        raise UserVisibleError(ui_text("error_audio_adjust_numeric"))
    return float(raw)


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
            text=True,
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


def ffmpeg_audio_output_args(task: AudioAdjustTask) -> list[str]:
    encoder = FFMPEG_AUDIO_ENCODERS[task.codec]
    args = ["-c:a", encoder]
    if task.codec != "wav" and task.bitrate.strip():
        args.extend(["-b:a", task.bitrate.strip()])
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
    process = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
    )
    if process.stdout.strip():
        for line in process.stdout.splitlines():
            log(line.rstrip())
    if process.returncode != 0:
        raise UserVisibleError(f"ffmpeg exited with error code: {process.returncode}")


def run_audio_adjust_task(task: AudioAdjustTask, log: Callable[[str], None]) -> Path:
    validate_audio_adjust_task(task)
    ffmpeg = ffmpeg_path()
    output_suffix = AUDIO_OUTPUT_SUFFIXES.get(task.codec, task.path.suffix)
    target = task.path.with_suffix(output_suffix)
    needs_reencode = audio_adjust_requires_reencode(task)

    if target != task.path and target.exists():
        raise UserVisibleError(ui_text("error_output_exists_choose", name=target.name))

    if task.delta_seconds > 0:
        source_path = dedupe_sidecar_path(task.path, "source")
        task.path.rename(source_path)

        original_path = numbered_append_path(target)
        if needs_reencode:
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
            run_logged_process(encode_original_args, log)
        else:
            source_path.rename(original_path)

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
        run_logged_process(silence_args, log)
    elif task.delta_seconds < 0:
        backup_path = dedupe_sidecar_path(task.path, "source")
        task.path.rename(backup_path)
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
        run_logged_process(trim_args, log)
    else:
        backup_path = dedupe_sidecar_path(task.path, "source")
        task.path.rename(backup_path)
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
        run_logged_process(encode_args, log)

    log(ui_text("log_audio_adjust_ready", name=target.name))
    return target



def identify_mkv(source: Path) -> dict[str, Any]:
    mkvmerge = third_party_tool_path("mkvmerge")
    if not mkvmerge:
        raise UserVisibleError(ui_text("error_mkvmerge_missing"))
    if not source.exists() or not source.is_file():
        raise UserVisibleError(ui_text("error_mkv_source_not_found", source=source))

    args = [mkvmerge, "--identification-format", "json", "--identify", str(source)]
    process = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=third_party_subprocess_env(),
        executable=third_party_subprocess_executable(args),
    )
    if process.returncode > 1:
        message = process.stderr.strip() or process.stdout.strip()
        raise UserVisibleError(
            ui_text("error_mkv_read_failed", message=message or process.returncode)
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise UserVisibleError(ui_text("error_mkv_json_parse_failed", error=exc)) from exc
    if not payload.get("container", {}).get("recognized"):
        raise UserVisibleError(ui_text("error_mkv_not_recognized"))
    return payload


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
    override = normalise_extract_language_override(item.language_override)
    return override if item.language == "und" and override else item.language


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
        if "AVC" in codec_id or "H.264" in codec or "H264" in codec:
            return "h264"
        if "HEVC" in codec_id or "H.265" in codec or "H265" in codec:
            return "h265"
        if "AV1" in codec_id or "av1" in codec:
            return "ivf"
        if "VP9" in codec_id or "vp9" in codec:
            return "ivf"
        if "MPEG2" in codec_id or "mpeg-2" in codec:
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


def fps_from_track(track: dict[str, Any]) -> str:
    properties = track.get("properties", {})
    duration_seconds = parse_duration_seconds(properties.get("default_duration"))
    if duration_seconds <= 0:
        return ""
    return format_fps_value(1 / duration_seconds)


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
        candidate = f"{base}.{counters[key]}.{extension}"

    while candidate.lower() in used_names:
        counters[key] += 1
        candidate = f"{base}.{counters[key]}.{extension}"
    used_names.add(candidate.lower())
    return candidate


def build_extract_items(identify_payload: dict[str, Any]) -> list[ExtractItem]:
    items: list[ExtractItem] = []
    counters: dict[tuple[str, str], int] = {}
    used_names: set[str] = set()

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
            fps = fps_from_track(track)
            if fps:
                suffix_parts.append(fps)

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
                name_prefix_parts=tuple(prefix_parts),
                name_suffix_parts=tuple(suffix_parts),
            )
        )

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
                label=ui_text("extract_label_chapters"),
                output_name=output_name,
            )
        )

    if identify_payload.get("global_tags") or identify_payload.get("track_tags"):
        output_name = dedupe_plain_filename("tags.xml", used_names)
        items.append(
            ExtractItem(
                key="tags",
                kind="tags",
                item_id=None,
                label=ui_text("extract_label_tags"),
                output_name=output_name,
            )
        )

    return items


def first_video_fps_from_items(items: list[ExtractItem]) -> str:
    for item in items:
        if item.kind != "track":
            continue
        match = re.search(r"(?:^|\.)(\d{2,3}(?:\.\d+)?)(?:\.[^.]+)$", item.output_name)
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


class MkvCreatorApp(tk.Tk):
    def __init__(self, initial_extract_source: Path | None = None) -> None:
        super().__init__(className=APP_NAME)
        self.saved_preferences = load_saved_preferences()
        self.ui_language_var = tk.StringVar(
            value=normalise_ui_language(self.saved_preferences.get("ui_language", "en"))
        )
        self.ui_language_display_var = tk.StringVar(
            value=UI_LANGUAGE_NAMES[self.ui_language_var.get()]
        )
        set_active_ui_language(self.ui_language_var.get())
        self.localized_widgets: list[tuple[tk.Widget, str, str]] = []
        self.localized_tree_headings: list[tuple[ttk.Treeview, str, str]] = []
        self.configure_ui_theme()
        self.title(APP_NAME)
        self.geometry("1200x820")
        self.minsize(1040, 700)

        self.log_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.log_lines: list[str] = []
        self.worker: threading.Thread | None = None
        self.last_mkv_dir = self.saved_preferences.get("last_mkv_dir", "")
        self.logo_source_image: Any = None
        self.logo_icon_image: Any = None
        self.logo_header_image: Any = None
        self.load_logo_images()

        self.template_var = tk.StringVar(value="")
        self.folder_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.extract_source_var = tk.StringVar()
        self.extract_output_dir_var = tk.StringVar()
        self.extract_items: dict[str, ExtractItem] = {}
        self.api_key_var = tk.StringVar(
            value=os.environ.get("TMDB_API_KEY", self.saved_preferences.get("api_key", ""))
        )
        self.tmdb_id_var = tk.StringVar()
        self.media_type_var = tk.StringVar(value=self.saved_preferences.get("media_type", "movie"))
        self.language_var = tk.StringVar(value=self.saved_preferences.get("image_language", "en"))
        self.tag_language_var = tk.StringVar(
            value=self.saved_preferences.get(
                "tag_language",
                self.saved_preferences.get("image_language", "en"),
            )
        )
        self.title_var = tk.StringVar()
        self.video_fps_var = tk.StringVar(value=self.saved_preferences.get("video_fps", ""))
        self.audio_language_order_var = tk.StringVar(
            value=self.saved_preferences.get("audio_language_order", "")
        )
        self.subtitle_language_order_var = tk.StringVar(
            value=self.saved_preferences.get("subtitle_language_order", "")
        )
        self.include_extra_subs_var = tk.BooleanVar(value=True)
        self.download_before_mux_var = tk.BooleanVar(value=True)
        self.auto_chapters_var = tk.BooleanVar(
            value=self.saved_preferences.get("auto_chapters", "false") == "true"
        )
        self.chapter_interval_var = tk.StringVar(
            value=self.saved_preferences.get("chapter_interval_minutes", "10")
        )
        self.chapter_name_var = tk.StringVar(
            value=self.saved_preferences.get("chapter_name", "")
        )
        self.chapter_start_var = tk.StringVar(
            value=self.saved_preferences.get("chapter_start_number", "1")
        )
        self.chapter_end_var = tk.StringVar(
            value=self.saved_preferences.get("chapter_end_minutes", "")
        )
        self.show_api_key_var = tk.BooleanVar(value=False)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_status_var = tk.StringVar(value=self.tr("status_ready"))
        self.extract_window: tk.Toplevel | None = None
        self.extract_tree: ttk.Treeview | None = None
        self.extract_language_frame: ttk.Frame | None = None
        self.extract_language_vars: dict[str, tk.StringVar] = {}
        self.extract_language_output_vars: dict[str, tk.StringVar] = {}
        self.audio_adjust_window: tk.Toplevel | None = None
        self.audio_adjust_apply_button: ttk.Button | None = None
        self.audio_adjust_rows: list[dict[str, Any]] = []
        self.extract_scan_button: ttk.Button | None = None
        self.extract_toggle_button: ttk.Button | None = None
        self.extract_all_button: ttk.Button | None = None
        self.extract_button: ttk.Button | None = None
        self.third_party_button: ttk.Button | None = None
        self.progress_bar: ttk.Progressbar | None = None
        self.log_window: tk.Toplevel | None = None
        self.log_window_text: ScrolledText | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._drain_log_queue)
        if initial_extract_source is not None:
            self.after(50, lambda: self.set_extract_source(initial_extract_source, scan=True))

    def load_logo_images(self) -> None:
        if not LOGO_PATH.exists():
            return
        try:
            if Image is not None and ImageOps is not None and ImageTk is not None:
                with Image.open(LOGO_PATH) as source:
                    image = source.convert("RGBA")
                    icon = ImageOps.contain(image, (256, 256))
                    header = ImageOps.contain(image, (96, 56))
                    self.logo_icon_image = ImageTk.PhotoImage(icon)
                    self.logo_header_image = ImageTk.PhotoImage(header)
            else:
                source = tk.PhotoImage(file=str(LOGO_PATH))
                self.logo_source_image = source
                icon_factor = max(1, (max(source.width(), source.height()) + 255) // 256)
                header_factor = max(
                    1,
                    max((source.width() + 95) // 96, (source.height() + 55) // 56),
                )
                self.logo_icon_image = source.subsample(icon_factor, icon_factor)
                self.logo_header_image = source.subsample(header_factor, header_factor)
            self.iconphoto(True, self.logo_icon_image)
        except (OSError, tk.TclError):
            self.logo_source_image = None
            self.logo_icon_image = None
            self.logo_header_image = None

    def tr(self, key: str, **values: Any) -> str:
        return ui_text(key, **values)

    def localize_widget(
        self,
        widget: tk.Widget,
        key: str,
        option: str = "text",
    ) -> tk.Widget:
        widget.configure(**{option: self.tr(key)})
        self.localized_widgets.append((widget, option, key))
        return widget

    def localize_tree_heading(
        self,
        tree: ttk.Treeview,
        column: str,
        key: str,
    ) -> None:
        tree.heading(column, text=self.tr(key))
        self.localized_tree_headings.append((tree, column, key))

    def make_section(
        self,
        parent: ttk.Frame,
        row: int,
        title_key: str,
        *,
        pady: tuple[int, int] = (0, 12),
    ) -> ttk.Frame:
        self.localize_widget(
            ttk.Label(parent, style="SectionTitle.TLabel"),
            title_key,
        ).grid(row=row, column=0, sticky="w", pady=(0, 6))
        section = ttk.Frame(parent, padding=(16, 12, 16, 16), style="Section.TFrame")
        section.grid(row=row + 1, column=0, sticky="ew", pady=pady)
        section.columnconfigure(1, weight=1)
        return section

    def on_ui_language_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.ui_language_display_var.get()
        language = UI_LANGUAGE_BY_NAME.get(selected, DEFAULT_UI_LANGUAGE)
        if language == self.ui_language_var.get():
            return
        self.ui_language_var.set(language)
        set_active_ui_language(language)
        self.refresh_localized_text()
        self.save_preferences()

    def refresh_localized_text(self) -> None:
        set_active_ui_language(self.ui_language_var.get())
        self.ui_language_display_var.set(UI_LANGUAGE_NAMES[self.ui_language_var.get()])

        for widget, option, key in list(self.localized_widgets):
            try:
                if not widget.winfo_exists():
                    continue
                widget.configure(**{option: self.tr(key)})
            except tk.TclError:
                continue

        for tree, column, key in list(self.localized_tree_headings):
            try:
                if tree.winfo_exists():
                    tree.heading(column, text=self.tr(key))
            except tk.TclError:
                continue

        if self.extract_window is not None and self.extract_window.winfo_exists():
            self.extract_window.title(f"{APP_NAME} Extract")
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.title(self.tr("window_log_title", app=APP_NAME))

        ready_values = {texts["status_ready"] for texts in UI_TEXT.values()}
        completed_values = {texts["status_completed"] for texts in UI_TEXT.values()}
        current_status = self.progress_status_var.get()
        if current_status in ready_values:
            self.progress_status_var.set(self.tr("status_ready"))
        elif current_status in completed_values:
            self.progress_status_var.set(self.tr("status_completed"))

        self.update_extract_all_button_text()
        if self.extract_tree is not None:
            for item in self.extract_items.values():
                self.update_extract_tree_row(item)

    def configure_ui_theme(self) -> None:
        self.configure(background=UI_COLORS["window"])
        self.option_add("*tearOff", False)

        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Noto Sans", size=10)
        text_font = tkfont.nametofont("TkTextFont")
        text_font.configure(family="Noto Sans", size=10)
        heading_font = tkfont.nametofont("TkHeadingFont")
        heading_font.configure(family="Noto Sans", size=11, weight="bold")
        fixed_font = tkfont.nametofont("TkFixedFont")
        fixed_font.configure(size=10)

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        colors = UI_COLORS
        style.configure(
            ".",
            background=colors["surface"],
            foreground=colors["text"],
            font=default_font,
        )
        style.configure("Root.TFrame", background=colors["window"])
        style.configure("Toolbar.TFrame", background=colors["window"])
        style.configure(
            "Section.TFrame",
            background=colors["surface"],
            bordercolor=colors["border"],
            darkcolor=colors["border"],
            lightcolor=colors["border"],
            borderwidth=1,
            relief="solid",
        )
        style.configure("TFrame", background=colors["surface"])
        style.configure(
            "TLabel",
            background=colors["surface"],
            foreground=colors["text"],
            padding=(0, 2),
        )
        style.configure(
            "Muted.TLabel",
            background=colors["surface"],
            foreground=colors["muted"],
        )
        style.configure(
            "Root.TLabel",
            background=colors["window"],
            foreground=colors["text"],
        )
        style.configure(
            "SectionTitle.TLabel",
            background=colors["window"],
            foreground=colors["text"],
            font=heading_font,
            padding=(0, 0),
        )
        style.configure(
            "AppName.TLabel",
            background=colors["window"],
            foreground=colors["text"],
            font=(default_font.cget("family"), 18, "bold"),
            padding=(0, 0),
        )
        style.configure(
            "TLabelframe",
            background=colors["surface"],
            bordercolor=colors["border"],
            darkcolor=colors["border"],
            lightcolor=colors["border"],
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=colors["window"],
            foreground=colors["text"],
            font=heading_font,
            padding=(8, 2),
        )
        style.configure(
            "TEntry",
            fieldbackground=colors["surface"],
            foreground=colors["text"],
            insertcolor=colors["text"],
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"],
            padding=(8, 6),
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", colors["accent"])],
            lightcolor=[("focus", colors["accent"])],
            darkcolor=[("focus", colors["accent"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=colors["surface"],
            foreground=colors["text"],
            arrowcolor=colors["muted"],
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"],
            padding=(8, 6),
        )
        style.map(
            "TCombobox",
            bordercolor=[("focus", colors["accent"])],
            fieldbackground=[("readonly", colors["surface"])],
            selectbackground=[("readonly", colors["surface"])],
            selectforeground=[("readonly", colors["text"])],
        )
        style.configure(
            "TCheckbutton",
            background=colors["surface"],
            foreground=colors["text"],
            indicatorcolor=colors["surface"],
            padding=(0, 4),
        )
        style.map(
            "TCheckbutton",
            background=[("active", colors["surface"])],
            foreground=[("disabled", colors["disabled"])],
        )
        style.configure(
            "TButton",
            background=colors["surface_alt"],
            foreground=colors["text"],
            borderwidth=0,
            focusthickness=1,
            focuscolor=colors["accent"],
            padding=(12, 8),
            relief="flat",
        )
        style.map(
            "TButton",
            background=[
                ("disabled", "#e4e9f0"),
                ("pressed", "#d5dfec"),
                ("active", "#dde6f2"),
            ],
            foreground=[("disabled", colors["disabled"])],
        )
        style.configure(
            "Accent.TButton",
            background=colors["accent"],
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=1,
            focuscolor=colors["accent_pressed"],
            padding=(12, 8),
            relief="flat",
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", "#9bb7f3"),
                ("pressed", colors["accent_pressed"]),
                ("active", colors["accent_hover"]),
            ],
            foreground=[("disabled", "#edf3ff"), ("active", "#ffffff")],
        )
        style.configure(
            "Treeview",
            background=colors["surface"],
            fieldbackground=colors["surface"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            rowheight=30,
        )
        style.map(
            "Treeview",
            background=[("selected", colors["accent"])],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Treeview.Heading",
            background=colors["surface_alt"],
            foreground=colors["text"],
            font=heading_font,
            padding=(8, 7),
            relief="flat",
        )

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        outer = ttk.Frame(self, padding=18, style="Root.TFrame")
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)

        header = ttk.Frame(outer, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)
        if self.logo_header_image is not None:
            ttk.Label(
                header,
                image=self.logo_header_image,
                style="Root.TLabel",
            ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(
            header,
            text=APP_NAME,
            style="AppName.TLabel",
        ).grid(row=0, column=1, sticky="w")
        self.localize_widget(
            ttk.Label(header, style="Root.TLabel"),
            "label_ui_language",
        ).grid(row=0, column=2, sticky="e", padx=(12, 6))
        language_select = ttk.Combobox(
            header,
            textvariable=self.ui_language_display_var,
            values=tuple(UI_LANGUAGE_NAMES.values()),
            width=11,
            state="readonly",
        )
        language_select.grid(row=0, column=3, sticky="e")
        language_select.bind("<<ComboboxSelected>>", self.on_ui_language_selected)
        self.third_party_button = ttk.Button(
            header,
            command=self.start_update_third_party,
        )
        self.localize_widget(self.third_party_button, "button_update_third_party")
        self.third_party_button.grid(row=0, column=4, sticky="e", padx=(8, 0))

        form = self.make_section(outer, 1, "section_create_mkv")

        row = 0
        self._path_row(form, row, "path_template", self.template_var, self.browse_template)
        row += 1
        self._path_row(form, row, "path_track_folder", self.folder_var, self.browse_folder)
        row += 1
        self._path_row(form, row, "path_output_mkv", self.output_var, self.browse_output)
        row += 1

        ttk.Label(form, text="TMDB API key").grid(row=row, column=0, sticky="w", pady=5)
        self.api_key_entry = ttk.Entry(form, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        self.localize_widget(
            ttk.Checkbutton(
                form,
                variable=self.show_api_key_var,
                command=self.toggle_api_key_visibility,
            ),
            "button_show",
        ).grid(row=row, column=2, sticky="w", pady=5)
        row += 1

        tmdb_row = ttk.Frame(form)
        tmdb_row.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        tmdb_row.columnconfigure(0, weight=1)
        ttk.Label(form, text="TMDB").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(tmdb_row, textvariable=self.tmdb_id_var).grid(row=0, column=0, sticky="ew")
        ttk.Combobox(
            tmdb_row,
            textvariable=self.media_type_var,
            values=("movie", "tv"),
            width=8,
            state="readonly",
        ).grid(row=0, column=1, padx=(8, 0))
        self.localize_widget(
            ttk.Label(tmdb_row),
            "label_image_language",
        ).grid(row=0, column=2, padx=(12, 4))
        ttk.Entry(tmdb_row, textvariable=self.language_var, width=7).grid(row=0, column=3)
        self.localize_widget(
            ttk.Label(tmdb_row),
            "label_tag_language",
        ).grid(row=0, column=4, padx=(12, 4))
        ttk.Entry(tmdb_row, textvariable=self.tag_language_var, width=7).grid(row=0, column=5)
        self.find_tmdb_button = ttk.Button(tmdb_row, command=self.start_find_tmdb_id)
        self.localize_widget(self.find_tmdb_button, "button_find_id")
        self.find_tmdb_button.grid(row=0, column=6, padx=(8, 0))
        row += 1

        self.localize_widget(
            ttk.Label(form),
            "label_mkv_title",
        ).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.title_var).grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        row += 1

        ttk.Label(form, text="Video FPS").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Combobox(
            form,
            textvariable=self.video_fps_var,
            values=("", "23.976", "24", "25", "29.970", "30", "50", "60", "24000/1001"),
        ).grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        row += 1

        default_track_row = ttk.Frame(form)
        default_track_row.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        default_track_row.columnconfigure(1, weight=1)
        default_track_row.columnconfigure(3, weight=1)
        self.localize_widget(
            ttk.Label(form),
            "label_default_tracks",
        ).grid(row=row, column=0, sticky="w", pady=5)
        self.localize_widget(
            ttk.Label(default_track_row),
            "label_audio_order",
        ).grid(row=0, column=0, sticky="w")
        ttk.Entry(default_track_row, textvariable=self.audio_language_order_var, width=16).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(6, 14),
        )
        self.localize_widget(
            ttk.Label(default_track_row),
            "label_subtitle_order",
        ).grid(row=0, column=2, sticky="w")
        ttk.Entry(default_track_row, textvariable=self.subtitle_language_order_var, width=16).grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(6, 0),
        )
        row += 1

        options = ttk.Frame(form)
        options.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        self.localize_widget(
            ttk.Checkbutton(
                options,
                variable=self.include_extra_subs_var,
            ),
            "option_include_extra_subtitles",
        ).grid(row=0, column=0, sticky="w")
        self.localize_widget(
            ttk.Checkbutton(
                options,
                variable=self.download_before_mux_var,
            ),
            "option_download_before_mux",
        ).grid(row=0, column=1, sticky="w", padx=(18, 0))
        row += 1

        chapter_row = ttk.Frame(form)
        chapter_row.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        chapter_row.columnconfigure(2, weight=1)
        self.localize_widget(
            ttk.Label(form),
            "label_auto_chapters",
        ).grid(row=row, column=0, sticky="w", pady=5)
        self.localize_widget(
            ttk.Checkbutton(
                chapter_row,
                variable=self.auto_chapters_var,
            ),
            "option_create_if_missing",
        ).grid(row=0, column=0, sticky="w")
        self.localize_widget(
            ttk.Label(chapter_row),
            "label_chapter_name",
        ).grid(row=0, column=1, padx=(12, 4))
        ttk.Entry(chapter_row, textvariable=self.chapter_name_var).grid(row=0, column=2, sticky="ew")
        self.localize_widget(
            ttk.Label(chapter_row),
            "label_chapter_interval",
        ).grid(row=0, column=3, padx=(12, 4))
        ttk.Entry(chapter_row, textvariable=self.chapter_interval_var, width=7).grid(row=0, column=4)
        self.localize_widget(
            ttk.Label(chapter_row),
            "label_chapter_start",
        ).grid(row=0, column=5, padx=(12, 4))
        ttk.Entry(chapter_row, textvariable=self.chapter_start_var, width=5).grid(row=0, column=6)
        self.localize_widget(
            ttk.Label(chapter_row),
            "label_chapter_end",
        ).grid(row=0, column=7, padx=(12, 4))
        ttk.Entry(chapter_row, textvariable=self.chapter_end_var, width=8).grid(row=0, column=8)

        actions = ttk.Frame(outer, style="Toolbar.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        for index in range(5):
            actions.columnconfigure(index, weight=1)

        self.scan_button = ttk.Button(actions, command=self.open_audio_adjust_window)
        self.localize_widget(self.scan_button, "button_scan_tracks")
        self.scan_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.download_button = ttk.Button(actions, command=self.start_download)
        self.localize_widget(self.download_button, "button_download_assets")
        self.download_button.grid(row=0, column=1, sticky="ew", padx=8)
        self.config_button = ttk.Button(actions, command=self.start_write_config)
        self.localize_widget(self.config_button, "button_write_config")
        self.config_button.grid(row=0, column=2, sticky="ew", padx=8)
        self.mux_button = ttk.Button(
            actions,
            command=self.start_mux,
            style="Accent.TButton",
        )
        self.localize_widget(self.mux_button, "button_create_mkv")
        self.mux_button.grid(row=0, column=3, sticky="ew", padx=8)
        self.localize_widget(
            ttk.Button(
                actions,
                command=self.open_log_window,
            ),
            "button_show_log",
        ).grid(row=0, column=4, sticky="ew", padx=(8, 0))

        self.progress_bar = ttk.Progressbar(
            actions,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.progress_bar.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        ttk.Label(
            actions,
            textvariable=self.progress_status_var,
            style="Root.TLabel",
            anchor="w",
        ).grid(row=2, column=0, columnspan=5, sticky="ew", pady=(4, 0))

        extract = self.make_section(outer, 4, "section_extract")

        self._path_row(extract, 0, "path_source_mkv", self.extract_source_var, self.browse_extract_source)
        self._path_row(
            extract,
            1,
            "path_extract_folder",
            self.extract_output_dir_var,
            self.browse_extract_output_dir,
        )

    def make_log_text(self, parent: tk.Widget, height: int) -> ScrolledText:
        return ScrolledText(
            parent,
            height=height,
            wrap="word",
            state="disabled",
            borderwidth=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI_COLORS["border"],
            highlightcolor=UI_COLORS["accent"],
            background=UI_COLORS["surface"],
            foreground=UI_COLORS["text"],
            insertbackground=UI_COLORS["text"],
            selectbackground=UI_COLORS["accent"],
            selectforeground="#ffffff",
            padx=10,
            pady=8,
            font=tkfont.nametofont("TkFixedFont"),
        )

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label_key: str,
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> None:
        self.localize_widget(ttk.Label(parent), label_key).grid(
            row=row,
            column=0,
            sticky="w",
            pady=5,
        )
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=5)
        self.localize_widget(
            ttk.Button(parent, command=command),
            "button_browse",
        ).grid(row=row, column=2, sticky="ew", pady=5)

    def toggle_api_key_visibility(self) -> None:
        self.api_key_entry.configure(show="" if self.show_api_key_var.get() else "*")

    def save_preferences(self) -> None:
        try:
            save_saved_preferences(
                {
                    "ui_language": self.ui_language_var.get(),
                    "api_key": self.api_key_var.get().strip(),
                    "media_type": self.media_type_var.get().strip() or "movie",
                    "image_language": self.language_var.get().strip() or "en",
                    "tag_language": self.tag_language_var.get().strip()
                    or self.language_var.get().strip()
                    or "en",
                    "video_fps": self.video_fps_var.get().strip(),
                    "audio_language_order": self.audio_language_order_var.get().strip(),
                    "subtitle_language_order": self.subtitle_language_order_var.get().strip(),
                    "auto_chapters": "true" if self.auto_chapters_var.get() else "false",
                    "chapter_interval_minutes": self.chapter_interval_var.get().strip(),
                    "chapter_name": self.chapter_name_var.get().strip(),
                    "chapter_start_number": self.chapter_start_var.get().strip(),
                    "chapter_end_minutes": self.chapter_end_var.get().strip(),
                    "last_mkv_dir": self.last_mkv_dir,
                }
            )
        except OSError as exc:
            self.queue_log(self.tr("log_settings_save_failed", error=exc))

    def on_close(self) -> None:
        self.save_preferences()
        self.destroy()

    def browse_template(self) -> None:
        path = filedialog.askopenfilename(
            title=self.tr("dialog_template_title"),
            initialdir=str(APP_DIR),
            filetypes=(
                ("MKVToolNix config", "*.mtxcfg"),
                (self.tr("filetype_all"), "*"),
            ),
        )
        if path:
            self.template_var.set(path)
            try:
                config = load_template_config(Path(path))
                if not self.title_var.get().strip():
                    self.title_var.set(template_title(config))
                self._set_default_output()
            except UserVisibleError as exc:
                messagebox.showerror(self.tr("dialog_config_error"), str(exc))

    def browse_folder(self) -> None:
        path = filedialog.askdirectory(title=self.tr("dialog_track_folder_title"))
        if path:
            self.folder_var.set(path)
            self._set_default_output()
            if self.api_key_var.get().strip() and not self.tmdb_id_var.get().strip():
                self.start_find_tmdb_id(auto=True)

    def browse_output(self) -> None:
        output_raw = self.output_var.get().strip()
        output_dir = Path(output_raw).expanduser().parent if output_raw else None
        initial_dir = self.existing_initial_dir(
            output_dir,
            self.folder_var.get().strip(),
            self.last_mkv_dir,
            APP_DIR,
        )
        path = filedialog.asksaveasfilename(
            title=self.tr("dialog_output_mkv_title"),
            initialdir=initial_dir,
            defaultextension=".mkv",
            filetypes=(
                (self.tr("filetype_matroska"), "*.mkv"),
                (self.tr("filetype_all"), "*"),
            ),
        )
        if path:
            self.output_var.set(path)
            self.remember_mkv_dir(Path(path))

    def browse_extract_source(self) -> None:
        path = filedialog.askopenfilename(
            title=self.tr("dialog_source_mkv_title"),
            initialdir=self.extract_source_initial_dir(),
            filetypes=(
                (self.tr("filetype_matroska"), "*.mkv"),
                (self.tr("filetype_all"), "*"),
            ),
        )
        if not path:
            return
        self.set_extract_source(Path(path), scan=True)

    def browse_extract_output_dir(self) -> None:
        initial_dir = self.extract_output_dir_var.get().strip()
        if not initial_dir:
            source_raw = self.extract_source_var.get().strip()
            initial_dir = str(Path(source_raw).expanduser().parent) if source_raw else str(APP_DIR)
        path = filedialog.askdirectory(
            title=self.tr("dialog_extract_folder_title"),
            initialdir=initial_dir,
        )
        if path:
            self.extract_output_dir_var.set(path)

    def existing_initial_dir(self, *candidates: str | Path | None) -> str:
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.is_file():
                path = path.parent
            if path.exists() and path.is_dir():
                return str(path)
        return str(APP_DIR)

    def extract_source_initial_dir(self) -> str:
        source_raw = self.extract_source_var.get().strip()
        source_dir = Path(source_raw).expanduser().parent if source_raw else None
        return self.existing_initial_dir(
            self.last_mkv_dir,
            source_dir,
            self.folder_var.get().strip(),
            APP_DIR,
        )

    def remember_mkv_dir(self, path: Path) -> None:
        directory = path if path.is_dir() else path.parent
        self.last_mkv_dir = str(directory.expanduser())
        self.save_preferences()

    def set_extract_source(self, source: Path, *, scan: bool) -> None:
        source = source.expanduser()
        self.extract_source_var.set(str(source))
        if not self.extract_output_dir_var.get().strip():
            self.extract_output_dir_var.set(str(source.parent / f"{source.stem}_tracks"))
        self.remember_mkv_dir(source)
        if scan:
            self.start_scan_extract()

    def _set_default_output(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder or self.output_var.get().strip():
            return
        template_raw = self.template_var.get().strip()
        try:
            if template_raw:
                config = load_template_config(Path(template_raw).expanduser())
                name = template_output_name(config)
            else:
                name = "output.mkv"
        except UserVisibleError:
            name = "output.mkv"
        self.output_var.set(str(Path(folder).expanduser() / name))

    def collect_settings(self, *, require_tmdb: bool = False) -> AppSettings:
        template_raw = self.template_var.get().strip()
        template_path = Path(template_raw).expanduser() if template_raw else None
        folder_raw = self.folder_var.get().strip()
        media_dir = Path(folder_raw).expanduser()
        output_raw = self.output_var.get().strip()
        api_key = self.api_key_var.get().strip()
        tmdb_id = self.tmdb_id_var.get().strip()
        media_type = self.media_type_var.get().strip() or "movie"
        image_language = self.language_var.get().strip() or "en"
        tag_language = self.tag_language_var.get().strip() or image_language
        mkv_title = self.title_var.get().strip()
        video_fps = self.video_fps_var.get().strip()
        audio_language_order = self.audio_language_order_var.get().strip()
        subtitle_language_order = self.subtitle_language_order_var.get().strip()
        auto_chapters = self.auto_chapters_var.get()
        chapter_interval_minutes = self.chapter_interval_var.get().strip()
        chapter_name = self.chapter_name_var.get().strip()
        chapter_start_number = self.chapter_start_var.get().strip()
        chapter_end_minutes = self.chapter_end_var.get().strip()

        if template_path is not None and not template_path.exists():
            raise UserVisibleError(ui_text("error_template_missing", path=template_path))
        if not folder_raw or folder_raw == ".":
            raise UserVisibleError(ui_text("error_track_folder_not_selected"))
        if not media_dir.exists() or not media_dir.is_dir():
            raise UserVisibleError(ui_text("error_track_folder_not_found", path=media_dir))
        if output_raw:
            output_path = Path(output_raw).expanduser()
        else:
            config = load_or_create_template_config(template_path, media_dir)
            output_path = media_dir / template_output_name(config)
            self.log_queue.put(
                ("log", self.tr("log_output_default_used", path=output_path))
            )
            self.output_var.set(str(output_path))
        if media_type not in {"movie", "tv"}:
            raise UserVisibleError(ui_text("error_tmdb_media_type"))
        normalize_video_fps(video_fps)
        if require_tmdb:
            if not api_key:
                raise UserVisibleError(ui_text("error_tmdb_api_empty"))
            if not tmdb_id:
                raise UserVisibleError(ui_text("error_tmdb_id_empty"))
            if not tmdb_id.isdigit():
                raise UserVisibleError(ui_text("error_tmdb_id_numeric"))

        return AppSettings(
            template_path=template_path,
            media_dir=media_dir,
            output_path=output_path,
            api_key=api_key,
            tmdb_id=tmdb_id,
            media_type=media_type,
            image_language=image_language,
            tag_language=tag_language,
            mkv_title=mkv_title,
            video_fps=video_fps,
            audio_language_order=audio_language_order,
            subtitle_language_order=subtitle_language_order,
            include_extra_subtitles=self.include_extra_subs_var.get(),
            download_before_mux=self.download_before_mux_var.get(),
            auto_chapters=auto_chapters,
            chapter_interval_minutes=chapter_interval_minutes,
            chapter_name=chapter_name,
            chapter_start_number=chapter_start_number,
            chapter_end_minutes=chapter_end_minutes,
        )

    def chapter_options_from_settings(self, settings: AppSettings) -> ChapterOptions:
        return ChapterOptions(
            enabled=settings.auto_chapters,
            interval_minutes=settings.chapter_interval_minutes,
            name=settings.chapter_name,
            start_number=settings.chapter_start_number,
            end_minutes=settings.chapter_end_minutes,
        )

    def collect_extract_settings(self) -> tuple[Path, Path]:
        source_raw = self.extract_source_var.get().strip()
        if not source_raw:
            raise UserVisibleError(ui_text("error_source_mkv_not_selected"))
        source = Path(source_raw).expanduser()
        if not source.exists() or not source.is_file():
            raise UserVisibleError(ui_text("error_mkv_source_not_found", source=source))
        source = source.resolve()

        output_raw = self.extract_output_dir_var.get().strip()
        output_dir = Path(output_raw).expanduser() if output_raw else source.parent / f"{source.stem}_tracks"
        output_dir = output_dir.resolve()
        self.extract_output_dir_var.set(str(output_dir))
        return source, output_dir

    def open_audio_adjust_window(self) -> None:
        try:
            settings = self.collect_settings()
            config = load_or_create_template_config(settings.template_path, settings.media_dir)
            items, _, _ = discover_track_items(
                config,
                settings.media_dir,
                settings.include_extra_subtitles,
            )
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        audio_items = [item for item in items if track_type_value(item) == 0]
        if not audio_items:
            messagebox.showinfo(self.tr("dialog_missing_info"), self.tr("error_audio_adjust_none"))
            return

        if self.audio_adjust_window is not None:
            try:
                if self.audio_adjust_window.winfo_exists():
                    self.audio_adjust_window.destroy()
            except tk.TclError:
                pass

        window = tk.Toplevel(self)
        self.audio_adjust_window = window
        window.title(f"{APP_NAME} - {self.tr('window_audio_adjust_title')}")
        window.geometry("1220x420")
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        hint_label = self.localize_widget(
            ttk.Label(window, style="Root.TLabel", wraplength=1180, justify="left"),
            "audio_adjust_hint",
        )
        hint_label.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=14,
            pady=(12, 8),
        )

        container = ttk.Frame(window, padding=(14, 0, 14, 10))
        container.grid(row=1, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        canvas = tk.Canvas(container, highlightthickness=0, background=UI_COLORS["surface"])
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        rows_frame = ttk.Frame(canvas, style="Section.TFrame")
        rows_frame.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        container.rowconfigure(0, weight=1)

        headings = [
            ("", 0, 4),
            ("heading_audio_file", 1, 20),
            ("heading_audio_delta", 2, 10),
            ("heading_audio_speed", 3, 16),
            ("heading_audio_codec", 4, 10),
            ("heading_audio_bitrate", 5, 10),
            ("heading_audio_rate", 6, 12),
            ("heading_audio_layout", 7, 10),
            ("heading_audio_volume", 8, 16),
        ]
        for key, column, width in headings:
            if key:
                self.localize_widget(ttk.Label(rows_frame, style="SectionTitle.TLabel"), key).grid(
                    row=0,
                    column=column,
                    sticky="w",
                    padx=4,
                    pady=(8, 6),
                )
            rows_frame.columnconfigure(column, weight=1 if column == 1 else 0, minsize=width * 8)

        self.audio_adjust_rows = []
        codec_values = tuple(sorted(SUPPORTED_AUDIO_ENCODERS))
        speed_values = [("auto", self.tr("speed_factor_auto"))] + [
            (key, self.tr(f"speed_factor_{key}")) for key in AUDIO_SPEED_FACTORS if key != "auto"
        ]
        speed_label_to_key = {label: key for key, label in speed_values}
        speed_key_to_label = {key: label for key, label in speed_values}
        def update_volume_label(value: Any, variable: tk.DoubleVar, label_var: tk.StringVar) -> None:
            level = normalise_audio_volume_multiplier(value)
            if abs(normalise_audio_volume_multiplier(variable.get()) - level) > 0.001:
                variable.set(level)
            label_var.set(f"{level:.1f}x")

        for row_index, item in enumerate(audio_items, start=1):
            defaults = audio_probe_defaults(item.path)
            selected_var = tk.BooleanVar(value=False)
            delta_var = tk.StringVar(value="")
            codec_var = tk.StringVar(value=defaults["codec"] if defaults["codec"] in SUPPORTED_AUDIO_ENCODERS else "eac3")
            bitrate_var = tk.StringVar(value=defaults["bitrate"])
            sample_rate_var = tk.StringVar(value=defaults["sample_rate"])
            layout_var = tk.StringVar(value=defaults["channel_layout"])
            volume_var = tk.DoubleVar(value=1.0)
            volume_label_var = tk.StringVar(value="1.0x")
            speed_var = tk.StringVar(value=speed_key_to_label["auto"])

            ttk.Checkbutton(rows_frame, variable=selected_var).grid(row=row_index, column=0, padx=4, pady=4)
            ttk.Label(rows_frame, text=item.path.name).grid(row=row_index, column=1, sticky="w", padx=4, pady=4)
            ttk.Entry(rows_frame, textvariable=delta_var, width=10).grid(row=row_index, column=2, sticky="ew", padx=4, pady=4)
            ttk.Combobox(
                rows_frame,
                textvariable=speed_var,
                values=[label for _key, label in speed_values],
                width=12,
                state="readonly",
            ).grid(row=row_index, column=3, sticky="ew", padx=4, pady=4)
            ttk.Combobox(rows_frame, textvariable=codec_var, values=codec_values, width=9).grid(row=row_index, column=4, sticky="ew", padx=4, pady=4)
            ttk.Entry(rows_frame, textvariable=bitrate_var, width=10).grid(row=row_index, column=5, sticky="ew", padx=4, pady=4)
            ttk.Entry(rows_frame, textvariable=sample_rate_var, width=10).grid(row=row_index, column=6, sticky="ew", padx=4, pady=4)
            ttk.Entry(rows_frame, textvariable=layout_var, width=10).grid(row=row_index, column=7, sticky="ew", padx=4, pady=4)
            volume_frame = ttk.Frame(rows_frame)
            volume_frame.columnconfigure(0, weight=1)
            ttk.Scale(
                volume_frame,
                from_=1,
                to=5,
                orient="horizontal",
                variable=volume_var,
                command=lambda value, var=volume_var, label=volume_label_var: update_volume_label(value, var, label),
            ).grid(row=0, column=0, sticky="ew")
            ttk.Label(volume_frame, textvariable=volume_label_var, width=4).grid(row=0, column=1, padx=(6, 0))
            volume_frame.grid(row=row_index, column=8, sticky="ew", padx=4, pady=4)

            self.audio_adjust_rows.append(
                {
                    "path": item.path,
                    "selected": selected_var,
                    "delta": delta_var,
                    "codec": codec_var,
                    "bitrate": bitrate_var,
                    "sample_rate": sample_rate_var,
                    "layout": layout_var,
                    "volume": volume_var,
                    "speed": speed_var,
                    "defaults": defaults,
                }
            )

        actions = ttk.Frame(window, padding=(14, 0, 14, 14))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        apply_button = ttk.Button(
            actions,
            command=self.start_audio_adjust,
            style="Accent.TButton",
        )
        self.audio_adjust_apply_button = apply_button
        self.localize_widget(apply_button, "button_apply_audio_adjust")
        apply_button.grid(row=0, column=1, sticky="e")

    def close_audio_adjust_window(self) -> None:
        if self.audio_adjust_window is None:
            return
        try:
            if self.audio_adjust_window.winfo_exists():
                self.audio_adjust_window.destroy()
        except tk.TclError:
            pass
        finally:
            self.audio_adjust_window = None
            self.audio_adjust_apply_button = None
            self.audio_adjust_rows = []

    def collect_audio_adjust_tasks(self) -> list[AudioAdjustTask]:
        tasks: list[AudioAdjustTask] = []
        for row in self.audio_adjust_rows:
            if not row["selected"].get():
                continue
            delta = parse_seconds_delta(row["delta"].get())
            codec = row["codec"].get().strip().lower()
            speed_label = row["speed"].get().strip()
            speed_key = speed_label_to_key.get(speed_label, "auto")
            speed = AUDIO_SPEED_FACTORS.get(speed_key, 1.0)
            tasks.append(
                AudioAdjustTask(
                    path=Path(row["path"]),
                    delta_seconds=delta,
                    codec=codec,
                    bitrate=row["bitrate"].get().strip(),
                    sample_rate=row["sample_rate"].get().strip() or "48000",
                    channel_layout=row["layout"].get().strip() or "stereo",
                    volume_multiplier=normalise_audio_volume_multiplier(row["volume"].get()),
                    speed_factor=speed,
                    original_codec=row["defaults"].get("codec", ""),
                    original_bitrate=row["defaults"].get("bitrate", ""),
                    original_sample_rate=row["defaults"].get("sample_rate", ""),
                    original_channel_layout=row["defaults"].get("channel_layout", ""),
                )
            )
        if not tasks:
            raise UserVisibleError(self.tr("error_audio_adjust_none"))
        for task in tasks:
            validate_audio_adjust_task(task)
        return tasks

    def start_audio_adjust(self) -> None:
        try:
            tasks = self.collect_audio_adjust_tasks()
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        if self.audio_adjust_apply_button is not None:
            self.audio_adjust_apply_button.configure(state="disabled")

        def work() -> None:
            for task in tasks:
                run_audio_adjust_task(task, self.queue_log)
            self.log_queue.put(("close_audio_adjust", True))

        started = self.run_background(work, self.tr("status_adjusting_audio"))
        if not started and self.audio_adjust_apply_button is not None:
            self.audio_adjust_apply_button.configure(state="normal")

    def start_update_third_party(self) -> None:
        groups = (
            ("mkvtoolnix", "MKVToolNix"),
            ("ffmpeg", "FFmpeg"),
        )

        def work() -> None:
            for group, name in groups:
                self.queue_log(self.tr("log_third_party_checking", name=name))
                result = ensure_third_party_group(group, force_check=True)
                version = str(result.get("version") or "installed")
                if result.get("existing_used"):
                    self.queue_log(
                        self.tr(
                            "log_third_party_existing_used",
                            name=name,
                            version=version,
                        )
                    )
                elif result.get("changed"):
                    self.queue_log(
                        self.tr("log_third_party_updated", name=name, version=version)
                    )
                else:
                    self.queue_log(
                        self.tr("log_third_party_current", name=name, version=version)
                    )
            self.queue_log(self.tr("log_third_party_complete"))

        self.run_background(work, self.tr("status_updating_third_party"))

    def start_scan(self) -> None:
        try:
            settings = self.collect_settings()
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        def work() -> None:
            config = load_or_create_template_config(settings.template_path, settings.media_dir)
            items, missing_optional, _ = discover_track_items(
                config,
                settings.media_dir,
                settings.include_extra_subtitles,
            )
            ordered = apply_default_track_preferences(
                config,
                items,
                settings.audio_language_order,
                settings.subtitle_language_order,
            )
            self.queue_log(self.tr("log_tracks_found", count=len(items)))
            for item in ordered:
                suffix = self.tr("log_extra_subtitle_suffix") if item.is_extra else ""
                language = track_language_value(item) or "und"
                default = (
                    self.tr("log_default_track_suffix")
                    if truthy_flag(item.track.get("defaultTrackFlag"))
                    else ""
                )
                forced = " | forced" if is_forced_track_item(item) else ""
                appended = "".join(f" + {path.name}" for path in item.append_paths)
                self.queue_log(
                    f"  {track_type_label(item)} | {language} | {item.path.name}{appended}{suffix}{default}{forced}"
                )
            if missing_optional:
                self.queue_log(
                    self.tr(
                        "log_optional_tracks_missing",
                        items=", ".join(sorted(set(missing_optional))),
                    )
                )
            else:
                self.queue_log(self.tr("log_optional_tracks_clear"))

        self.run_background(work, self.tr("status_scanning_tracks"))

    def start_find_tmdb_id(self, auto: bool = False) -> None:
        try:
            settings = self.collect_settings()
            if not settings.api_key:
                if not auto:
                    raise UserVisibleError(ui_text("error_tmdb_api_empty"))
                return
            self.save_preferences()
        except UserVisibleError as exc:
            if not auto:
                messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        def work() -> None:
            try:
                tmdb_id, title, found_year, query = find_tmdb_match_from_folder(settings)
            except UserVisibleError as exc:
                if auto:
                    self.queue_log(self.tr("log_tmdb_id_auto_failed", error=exc))
                    return
                raise
            self.log_queue.put(("set_tmdb_id", tmdb_id))
            image_title = tmdb_title_for_language(settings, tmdb_id, settings.image_language)
            if image_title:
                output_path = tmdb_output_path(settings.media_dir, image_title)
                self.log_queue.put(("set_output", str(output_path)))
                self.queue_log(
                    self.tr("log_output_from_artwork_language", name=output_path.name)
                )
            tag_title = tmdb_title_for_language(settings, tmdb_id, settings.tag_language)
            if tag_title and (not auto or not settings.mkv_title):
                self.log_queue.put(("set_title", tag_title))
                self.queue_log(self.tr("log_title_from_tag_language", title=tag_title))
            year_text = f" ({found_year})" if found_year else ""
            title_text = image_title or title or query
            self.queue_log(
                self.tr(
                    "log_tmdb_id_found",
                    tmdb_id=tmdb_id,
                    title=title_text,
                    year_text=year_text,
                )
            )

        self.run_background(work, self.tr("status_finding_tmdb"))

    def start_download(self) -> None:
        try:
            settings = self.collect_settings(require_tmdb=True)
            self.save_preferences()
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        def work() -> None:
            title = download_tmdb_assets(settings, self.queue_log)
            if title:
                output_path = tmdb_output_path(settings.media_dir, title)
                self.log_queue.put(("set_output", str(output_path)))
                self.queue_log(
                    self.tr("log_output_from_artwork_language", name=output_path.name)
                )

        self.run_background(work, self.tr("status_downloading_assets"))

    def start_write_config(self) -> None:
        try:
            settings = self.collect_settings()
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        def work() -> None:
            config = load_or_create_template_config(settings.template_path, settings.media_dir)
            settings.output_path.parent.mkdir(parents=True, exist_ok=True)
            generated = write_generated_config(
                config,
                settings.media_dir,
                settings.output_path,
                settings.mkv_title,
                settings.include_extra_subtitles,
                settings.video_fps,
                self.chapter_options_from_settings(settings),
                settings.audio_language_order,
                settings.subtitle_language_order,
                settings.tag_language,
            )
            self.queue_log(self.tr("log_config_written", path=generated))

        self.run_background(work, self.tr("status_writing_config"))

    def start_mux(self) -> None:
        try:
            settings = self.collect_settings(require_tmdb=self.download_before_mux_var.get())
            self.save_preferences()
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        if settings.output_path.exists():
            overwrite = messagebox.askyesno(
                self.tr("dialog_overwrite_title"),
                self.tr("dialog_overwrite_message", name=settings.output_path.name),
            )
            if not overwrite:
                return

        def work() -> None:
            config = load_or_create_template_config(settings.template_path, settings.media_dir)
            settings.output_path.parent.mkdir(parents=True, exist_ok=True)

            if settings.download_before_mux:
                title = download_tmdb_assets(settings, self.queue_log)
                if title:
                    settings.output_path = tmdb_output_path(settings.media_dir, title)
                    settings.output_path.parent.mkdir(parents=True, exist_ok=True)
                    self.log_queue.put(("set_output", str(settings.output_path)))
                    self.queue_log(
                        self.tr(
                            "log_output_from_artwork_language",
                            name=settings.output_path.name,
                        )
                    )
                    if settings.output_path.exists():
                        raise UserVisibleError(
                            ui_text(
                                "error_output_exists_choose",
                                name=settings.output_path.name,
                            )
                        )

            args, missing_optional = build_mkvmerge_args(
                config,
                settings.media_dir,
                settings.output_path,
                settings.mkv_title,
                settings.include_extra_subtitles,
                settings.video_fps,
                self.chapter_options_from_settings(settings),
                settings.audio_language_order,
                settings.subtitle_language_order,
                settings.tag_language,
            )
            generated = write_generated_config(
                config,
                settings.media_dir,
                settings.output_path,
                settings.mkv_title,
                settings.include_extra_subtitles,
                settings.video_fps,
                self.chapter_options_from_settings(settings),
                settings.audio_language_order,
                settings.subtitle_language_order,
                settings.tag_language,
            )
            self.queue_log(self.tr("log_config_written", path=generated))
            if missing_optional:
                self.queue_log(
                    self.tr(
                        "log_skipped_optional_tracks",
                        items=", ".join(missing_optional),
                    )
                )
            self.queue_log(self.tr("log_mkvmerge_command"))
            self.queue_log(command_preview(args))

            process = subprocess.Popen(
                args,
                cwd=str(settings.media_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=third_party_subprocess_env(),
                executable=third_party_subprocess_executable(args),
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.queue_log(line.rstrip())
            return_code = process.wait()
            if return_code > 1:
                raise UserVisibleError(ui_text("error_mkvmerge_exit", code=return_code))
            if return_code == 1:
                self.queue_log(self.tr("log_mkvmerge_warnings"))
            self.queue_log(self.tr("log_mkv_created", path=settings.output_path))

        self.run_background(work, self.tr("status_creating_mkv"))

    def close_extract_window(self) -> None:
        if self.extract_window is not None:
            self.extract_window.destroy()
        self.extract_window = None
        self.extract_tree = None
        self.extract_language_frame = None
        self.extract_language_vars = {}
        self.extract_language_output_vars = {}
        self.extract_scan_button = None
        self.extract_toggle_button = None
        self.extract_all_button = None
        self.extract_button = None

    def ensure_extract_window(self) -> None:
        if self.extract_window is not None and self.extract_window.winfo_exists():
            self.extract_window.lift()
            return

        window = tk.Toplevel(self)
        window.configure(background=UI_COLORS["window"])
        window.title(f"{APP_NAME} Extract")
        if self.logo_icon_image is not None:
            window.iconphoto(True, self.logo_icon_image)
        window.geometry("960x620")
        window.minsize(760, 480)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        window.protocol("WM_DELETE_WINDOW", self.close_extract_window)
        self.extract_window = window

        actions = ttk.Frame(window, padding=(18, 18, 18, 10), style="Root.TFrame")
        actions.grid(row=0, column=0, sticky="ew")
        for index in range(4):
            actions.columnconfigure(index, weight=1)

        self.extract_scan_button = ttk.Button(
            actions,
            command=self.start_scan_extract,
        )
        self.localize_widget(self.extract_scan_button, "button_scan_mkv")
        self.extract_scan_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.extract_toggle_button = ttk.Button(
            actions,
            command=self.toggle_selected_extract_items,
        )
        self.localize_widget(self.extract_toggle_button, "button_toggle_selection")
        self.extract_toggle_button.grid(row=0, column=1, sticky="ew", padx=8)
        self.extract_all_button = ttk.Button(
            actions,
            command=self.toggle_all_extract_items,
        )
        self.localize_widget(self.extract_all_button, "button_select_all")
        self.extract_all_button.grid(row=0, column=2, sticky="ew", padx=8)
        self.extract_button = ttk.Button(
            actions,
            command=self.start_extract,
            style="Accent.TButton",
        )
        self.localize_widget(self.extract_button, "button_extract_selected")
        self.extract_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        frame = ttk.Frame(window, padding=(18, 0, 18, 18), style="Root.TFrame")
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            frame,
            columns=("selected", "kind", "output"),
            show="headings",
            height=16,
        )
        self.localize_tree_heading(tree, "selected", "heading_selected")
        self.localize_tree_heading(tree, "kind", "heading_track")
        self.localize_tree_heading(tree, "output", "heading_output_name")
        tree.column("selected", width=55, minwidth=55, stretch=False, anchor="center")
        tree.column("kind", width=560, minwidth=260, stretch=True)
        tree.column("output", width=280, minwidth=180, stretch=False)
        tree.grid(row=0, column=0, sticky="nsew")
        tree.bind("<Double-1>", self.toggle_extract_item_event)
        tree.bind("<space>", self.toggle_extract_item_event)

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self.extract_tree = tree

        language_frame = ttk.Frame(frame, padding=(0, 10, 0, 0), style="Root.TFrame")
        language_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.extract_language_frame = language_frame

        if self.extract_items:
            self.populate_extract_tree()
            self.populate_extract_language_inputs()

    def populate_extract_tree(self) -> None:
        if self.extract_tree is None:
            return
        for row_id in self.extract_tree.get_children():
            self.extract_tree.delete(row_id)
        for item in self.extract_items.values():
            self.extract_tree.insert(
                "",
                "end",
                iid=item.key,
                values=(
                    self.tr("value_yes") if item.selected else self.tr("value_no"),
                    item.label,
                    item.output_name,
                ),
            )
        self.update_extract_all_button_text()

    def extract_items_with_unknown_language(self) -> list[ExtractItem]:
        return [
            item
            for item in self.extract_items.values()
            if item.kind == "track" and item.language == "und"
        ]

    def on_extract_language_changed(self, item_key: str, variable: tk.StringVar) -> None:
        item = self.extract_items.get(item_key)
        if item is None:
            return
        item.language_override = variable.get()
        self.refresh_extract_output_names()

    def populate_extract_language_inputs(self) -> None:
        if self.extract_language_frame is None:
            return
        for child in self.extract_language_frame.winfo_children():
            child.destroy()

        unknown_items = self.extract_items_with_unknown_language()
        if not unknown_items:
            self.extract_language_frame.grid_remove()
            self.extract_language_vars = {}
            self.extract_language_output_vars = {}
            return

        self.extract_language_frame.grid()
        self.extract_language_frame.columnconfigure(0, weight=1)
        self.localize_widget(
            ttk.Label(
                self.extract_language_frame,
                style="Root.TLabel",
                wraplength=860,
                justify="left",
            ),
            "extract_und_language_hint",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.localize_widget(
            ttk.Label(self.extract_language_frame, style="SectionTitle.TLabel"),
            "heading_extract_language",
        ).grid(row=0, column=2, sticky="w", padx=(8, 0), pady=(0, 6))

        self.extract_language_vars = {}
        self.extract_language_output_vars = {}
        for row_index, item in enumerate(unknown_items, start=1):
            ttk.Label(
                self.extract_language_frame,
                text=item.label,
                style="Root.TLabel",
            ).grid(row=row_index, column=0, sticky="w", pady=2)
            output_variable = tk.StringVar(value=item.output_name)
            self.extract_language_output_vars[item.key] = output_variable
            ttk.Label(
                self.extract_language_frame,
                textvariable=output_variable,
                style="Root.TLabel",
            ).grid(row=row_index, column=1, sticky="w", padx=(8, 0), pady=2)
            variable = tk.StringVar(value=item.language_override)
            self.extract_language_vars[item.key] = variable
            variable.trace_add(
                "write",
                lambda _name, _index, _mode, key=item.key, var=variable: self.on_extract_language_changed(key, var),
            )
            ttk.Entry(
                self.extract_language_frame,
                textvariable=variable,
                width=8,
            ).grid(row=row_index, column=2, sticky="w", padx=(8, 0), pady=2)

    def refresh_extract_output_names(self) -> None:
        items = list(self.extract_items.values())
        rebuild_extract_output_names(items)
        for item in items:
            self.update_extract_tree_row(item)
            output_variable = self.extract_language_output_vars.get(item.key)
            if output_variable is not None:
                output_variable.set(item.output_name)

    def set_extract_items(self, items: list[ExtractItem]) -> None:
        self.extract_items = {item.key: item for item in items}
        self.extract_language_vars = {}
        self.extract_language_output_vars = {}
        self.ensure_extract_window()
        self.populate_extract_tree()
        self.populate_extract_language_inputs()

    def update_extract_all_button_text(self) -> None:
        if self.extract_all_button is None:
            return
        all_selected = bool(self.extract_items) and all(
            item.selected for item in self.extract_items.values()
        )
        self.extract_all_button.configure(
            text=self.tr("button_clear_all") if all_selected else self.tr("button_select_all")
        )

    def update_extract_tree_row(self, item: ExtractItem) -> None:
        if self.extract_tree is not None and self.extract_tree.exists(item.key):
            self.extract_tree.item(
                item.key,
                values=(
                    self.tr("value_yes") if item.selected else self.tr("value_no"),
                    item.label,
                    item.output_name,
                ),
            )

    def toggle_extract_item_event(self, event: tk.Event) -> str:
        if self.extract_tree is None:
            return "break"
        row_id = self.extract_tree.focus()
        if row_id:
            item = self.extract_items.get(row_id)
            if item is not None:
                item.selected = not item.selected
                self.update_extract_tree_row(item)
                self.update_extract_all_button_text()
        return "break"

    def toggle_selected_extract_items(self) -> None:
        if self.extract_tree is None:
            return
        rows = self.extract_tree.selection() or (self.extract_tree.focus(),)
        for row_id in rows:
            item = self.extract_items.get(row_id)
            if item is None:
                continue
            item.selected = not item.selected
            self.update_extract_tree_row(item)
        self.update_extract_all_button_text()

    def toggle_all_extract_items(self) -> None:
        select_all = not (
            self.extract_items
            and all(item.selected for item in self.extract_items.values())
        )
        for item in self.extract_items.values():
            item.selected = select_all
            self.update_extract_tree_row(item)
        self.update_extract_all_button_text()

    def close_log_window(self) -> None:
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.destroy()
        self.log_window = None
        self.log_window_text = None

    def open_log_window(self) -> None:
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            self.log_window.focus_set()
            return

        window = tk.Toplevel(self)
        window.configure(background=UI_COLORS["window"])
        window.title(self.tr("window_log_title", app=APP_NAME))
        if self.logo_icon_image is not None:
            window.iconphoto(True, self.logo_icon_image)
        window.geometry("980x700")
        window.minsize(720, 480)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        window.protocol("WM_DELETE_WINDOW", self.close_log_window)

        frame = ttk.Frame(window, padding=18, style="Root.TFrame")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        text = self.make_log_text(frame, height=28)
        text.grid(row=0, column=0, sticky="nsew")
        if self.log_lines:
            text.configure(state="normal")
            text.insert("end", "\n".join(self.log_lines) + "\n")
            text.see("end")
            text.configure(state="disabled")

        self.log_window = window
        self.log_window_text = text

    def start_scan_extract(self) -> None:
        try:
            source, output_dir = self.collect_extract_settings()
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return
        self.ensure_extract_window()

        def work() -> None:
            payload = identify_mkv(source)
            items = build_extract_items(payload)
            self.log_queue.put(("set_extract_items", items))
            self.log_queue.put(("set_extract_dir", str(output_dir)))
            fps = first_video_fps_from_items(items)
            if fps:
                self.log_queue.put(("set_video_fps", fps))
                self.queue_log(self.tr("log_video_fps_detected", fps=fps))
            self.queue_log(self.tr("log_mkv_items_found", count=len(items)))
            for item in items:
                self.queue_log(f"  {item.label} -> {item.output_name}")

        self.run_background(work, self.tr("status_scanning_mkv"))

    def start_extract(self) -> None:
        try:
            source, output_dir = self.collect_extract_settings()
        except UserVisibleError as exc:
            messagebox.showerror(self.tr("dialog_missing_info"), str(exc))
            return

        if not self.extract_items:
            messagebox.showerror(
                self.tr("dialog_missing_info"),
                self.tr("error_scan_extract_first"),
            )
            return

        for item_key, variable in self.extract_language_vars.items():
            item = self.extract_items.get(item_key)
            if item is not None:
                item.language_override = variable.get()
        self.refresh_extract_output_names()

        items = [copy.deepcopy(item) for item in self.extract_items.values() if item.selected]
        if not items:
            messagebox.showerror(
                self.tr("dialog_missing_info"),
                self.tr("error_extract_none_selected"),
            )
            return

        def work() -> None:
            args = build_mkvextract_args(source, output_dir, items)
            self.queue_log(self.tr("log_mkvextract_command"))
            self.queue_log(command_preview(args))
            process = subprocess.Popen(
                args,
                cwd=str(output_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=third_party_subprocess_env(),
                executable=third_party_subprocess_executable(args),
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.queue_log(line.rstrip())
            return_code = process.wait()
            if return_code > 1:
                raise UserVisibleError(ui_text("error_mkvextract_exit", code=return_code))
            if return_code == 1:
                self.queue_log(self.tr("log_mkvextract_warnings"))

            fps = first_video_fps_from_items(items)
            if fps:
                self.log_queue.put(("set_video_fps", fps))
            self.log_queue.put(("set_folder", str(output_dir)))
            self.queue_log(self.tr("log_tracks_extracted", path=output_dir))
            self.queue_log(self.tr("log_folder_set_for_mux"))
            self.log_queue.put(("close_extract", True))

        self.run_background(work, self.tr("status_extracting_tracks"))

    def run_background(self, work: Callable[[], Any], status: str | None = None) -> bool:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(
                self.tr("dialog_in_progress_title"),
                self.tr("dialog_in_progress_message"),
            )
            return False

        self.set_busy(True, status or self.tr("status_processing"))

        def wrapped() -> None:
            try:
                work()
            except UserVisibleError as exc:
                self.queue_error(str(exc))
            except Exception as exc:
                self.queue_error(ui_text("error_unexpected", error=exc))
            finally:
                self.log_queue.put(("busy", False))

        self.worker = threading.Thread(target=wrapped, daemon=True)
        self.worker.start()
        return True

    def set_busy(self, busy: bool, status: str | None = None) -> None:
        state = "disabled" if busy else "normal"
        buttons = (
            self.scan_button,
            self.find_tmdb_button,
            self.download_button,
            self.config_button,
            self.mux_button,
            self.extract_scan_button,
            self.extract_toggle_button,
            self.extract_all_button,
            self.extract_button,
            self.third_party_button,
        )
        for button in buttons:
            if button is not None:
                button.configure(state=state)
        if busy:
            self.start_progress(status or self.tr("status_processing"))
        else:
            self.finish_progress()

    def short_status_message(self, message: str) -> str:
        value = re.sub(r"\s+", " ", message).strip()
        if len(value) > 150:
            return value[:147].rstrip() + "..."
        return value

    def start_progress(self, message: str) -> None:
        self.progress_var.set(0)
        self.progress_status_var.set(self.short_status_message(message))
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="indeterminate")
            self.progress_bar.start(12)

    def finish_progress(self) -> None:
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
        error_prefixes = {
            texts["error_prefix"].split("{message}", 1)[0]
            for texts in UI_TEXT.values()
        }
        if any(self.progress_status_var.get().startswith(prefix) for prefix in error_prefixes):
            return
        self.progress_var.set(100)
        if self.progress_status_var.get().endswith("..."):
            self.progress_status_var.set(self.tr("status_completed"))

    def set_progress_error(self, message: str) -> None:
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
        self.progress_var.set(0)
        self.progress_status_var.set(
            self.short_status_message(self.tr("error_prefix", message=message))
        )

    def update_progress_from_log(self, message: str) -> None:
        clean_message = self.short_status_message(message)
        if not clean_message:
            return

        percent_match = re.search(r"(?:[İI]lerleme|Progress):\s*(\d{1,3})%", clean_message)
        if percent_match:
            value = min(100, max(0, int(percent_match.group(1))))
            if self.progress_bar is not None:
                self.progress_bar.stop()
                self.progress_bar.configure(mode="determinate")
            self.progress_var.set(value)
            self.progress_status_var.set(clean_message)
            return

        command_line = clean_message.startswith("/") and (
            "mkvmerge" in clean_message or "mkvextract" in clean_message
        )
        if not command_line:
            self.progress_status_var.set(clean_message)

    def queue_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def queue_error(self, message: str) -> None:
        self.log_queue.put(("error", message))

    def _drain_log_queue(self) -> None:
        while True:
            try:
                kind, value = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                message = str(value)
                self.append_log(message)
                self.update_progress_from_log(message)
            elif kind == "error":
                message = str(value)
                self.append_log(self.tr("error_prefix", message=message))
                self.set_progress_error(message)
                messagebox.showerror(self.tr("dialog_error_title"), message)
            elif kind == "busy":
                self.set_busy(bool(value))
                if not bool(value) and self.audio_adjust_apply_button is not None:
                    try:
                        if self.audio_adjust_window is not None and self.audio_adjust_window.winfo_exists():
                            self.audio_adjust_apply_button.configure(state="normal")
                    except tk.TclError:
                        pass
            elif kind == "close_audio_adjust":
                self.close_audio_adjust_window()
            elif kind == "close_extract":
                self.close_extract_window()
            elif kind == "set_output":
                self.output_var.set(str(value))
            elif kind == "set_tmdb_id":
                self.tmdb_id_var.set(str(value))
            elif kind == "set_title":
                self.title_var.set(str(value))
            elif kind == "set_folder":
                self.folder_var.set(str(value))
                self._set_default_output()
            elif kind == "set_extract_dir":
                self.extract_output_dir_var.set(str(value))
            elif kind == "set_video_fps":
                self.video_fps_var.set(str(value))
            elif kind == "set_extract_items":
                self.set_extract_items(value)
        self.after(100, self._drain_log_queue)

    def append_log(self, message: str) -> None:
        self.log_lines.append(message)
        if self.log_window_text is not None:
            try:
                if self.log_window_text.winfo_exists():
                    self.append_log_to_widget(self.log_window_text, message)
            except tk.TclError:
                self.log_window_text = None

    def append_log_to_widget(self, widget: ScrolledText, message: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", message + "\n")
        widget.see("end")
        widget.configure(state="disabled")


def initial_extract_source_from_argv(argv: list[str]) -> Path | None:
    for value in argv[1:]:
        if not value or value.startswith("-"):
            continue
        path = Path(value).expanduser()
        if path.suffix.lower() == ".mkv" or path.is_file():
            return path
    return None


def main(argv: list[str] | None = None) -> None:
    app = MkvCreatorApp(initial_extract_source_from_argv(argv or sys.argv))
    app.mainloop()


if __name__ == "__main__":
    main()
