<p align="center">
  <img src="https://github.com/user-attachments/assets/438cb661-dbe0-4201-955e-1dab84e62668" alt="logo" width="200" style="background: transparent; display: inline-block;" />
</p>

Create professional MKV remuxes with TMDB metadata, artwork, chapters, language handling, and MKVToolNix automation — without manually building `mkvmerge` commands.

G-TMCE is a cross-platform GUI application for creating, extracting, and managing MKV files on Linux and Windows.

It combines MKVToolNix, FFmpeg, and TMDB into a single workflow and automatically handles tasks that are normally performed manually:

* 🎬 MKV remuxing and extraction
* 🏷️ Automatic TMDB metadata (`tags.xml`) generation
* 🖼️ Automatic poster, backdrop, and logo downloads
* 🌐 Audio and subtitle language management
* 📖 Automatic chapter generation
* 🎯 Forced and SDH subtitle detection
* 🔊 Audio synchronization between different frame rates (23.976 ↔ 24 ↔ 25 FPS)
* 📦 Consistent MKV structure and output naming

Perfect for media archivists, remux creators, home media server users, and anyone who regularly works with MKVToolNix.

<p align="center">
  <a href="https://github.com/user-attachments/assets/ab4245a7-1770-4fec-b54c-768d4a8f4357">
    <img src="https://github.com/user-attachments/assets/694c61ad-c62e-4067-b8a7-50ac4fa2b057" width="900">
  </a>
</p>

<p align="center">
  <b>▶ Click the image above to watch the demo</b>
</p>

---

## Why G-TMCE?

Creating a properly tagged MKV often requires multiple tools and many manual steps:

1. Search TMDB
2. Download artwork
3. Create `tags.xml`
4. Configure tracks
5. Set default audio/subtitle flags
6. Handle forced or SDH subtitles
7. Create chapters
8. Build the final `mkvmerge` command

G-TMCE automates the entire process and keeps every MKV organized using predictable naming rules and metadata handling.

---

## 📚 Documentation

| 🚀 Setup | 🎬 MKV Tools | 🏷️ Metadata & Rules | ⚙️ Advanced |
|----------|-------------|---------------------|-------------|
| [✨ Features](#features) | [🎞️ Create MKV Workflow](#create-mkv-workflow) | [📂 Track Folder Naming Rules](#track-folder-naming-rules) | [🛠️ Automatic Template Generation](#automatic-template-generation) |
| [📋 Requirements](#requirements) | [📤 Extract MKV Workflow](#extract-mkv-workflow) | [🎭 TMDB Integration](#tmdb-integration) | [📖 Automatic Chapters](#automatic-chapters) |
| [📦 Installation](#installation) | | [🏷️ Output Naming](#output-naming) | [🌐 Language Handling](#language-handling) |
| [⬇️ Releases & Downloads](#releases--downloads) | | [📁 Extraction Naming Rules](#extraction-naming-rules) | [⚙️ Settings](#settings) |
| [▶️ Launch](#launch) | | | [📝 Notes](#notes) |
| [🧰 Third-Party Tool Management](#third-party-tool-management) | | | [📄 License](#license) |

---

## Features

### 🎬 MKV Creation

- Automatic MKVToolNix config generation
- TMDB metadata and artwork integration
- Automatic `tags.xml` generation
- Automatic output naming from TMDB titles
- Automatic chapter generation
- Language-aware audio and subtitle ordering
- Default audio/subtitle selection rules
- Forced and SDH subtitle detection
- Audio and video append support
- Automatic FPS detection
- Generated `.generated.mtxcfg` audit file for every mux

### 📤 MKV Extraction

- Video, audio, subtitle, attachment, chapter, and tag extraction
- Automatic track naming
- Forced/SDH subtitle naming
- FPS-aware video extraction
- Extraction output ready for re-muxing

### 🔊 Audio Processing

- Delay adjustment
- Audio trimming/cutting
- Codec conversion
- Bitrate and sample-rate conversion
- Channel-layout conversion
- Volume boost

### 🎯 FPS Synchronization

- PAL speedup presets
- NTSC ↔ PAL audio synchronization
- 23.976 ↔ 24 ↔ 25 FPS conversion workflows
- Audio speed correction for remux projects

---

## Requirements

**Runtime:**
- Linux
- Python 3.10+
- Tkinter
- Pillow

**Supported Architectures:**

| Component | Supported |
|---|---|
| MKVToolNix AppImage | Linux x86_64 |
| FFmpeg | Linux x86_64, Linux aarch64 |
| Windows EXE | Windows x86_64 |

---

## Installation

### Arch Linux (AUR)

G-TMCE is available on the Arch User Repository as [`g-tmce`](https://aur.archlinux.org/packages/g-tmce).

```bash
# Using yay
yay -S g-tmce

# Using paru
paru -S g-tmce

# Manual
git clone https://aur.archlinux.org/g-tmce.git
cd g-tmce
makepkg -si
```

The AUR package installs the `g-tmce` launcher command, desktop menu entry, application icon, and Dolphin/KDE service menu integration.

Optional native file dialog helpers:

```bash
sudo pacman -S --needed kdialog zenity
```

### Clone Repository

```bash
git clone https://github.com/G-grbz/G-TMCE.git
cd G-TMCE
```

### Automatic Installation

```bash
chmod +x install.sh && sudo ./install.sh
```

The installer automatically installs required system dependencies, desktop launcher entries, application icons, Dolphin context menu integration, and creates the `g-tmce` launcher command.

Supported distributions: Debian / Ubuntu, Fedora, Arch Linux, openSUSE

---

## Releases & Downloads

Pre-built executables and AppImages are available on the [Releases](../../releases) page.

> **Windows support has been added.** A pre-built `.exe` is available for download on the Releases page.
>
> **VirusTotal Note:** A few antivirus engines may occasionally flag G-TMCE as suspicious. The application uses FFmpeg and MKVToolNix, works directly with media files, and launches external processes as part of its normal operation. Because of this, some machine learning–based antivirus solutions may generate false positives.
>
> At the time of writing, the latest release is detected by 5 out of 71 security vendors on VirusTotal, while major vendors such as BitDefender, Kaspersky, ESET, Malwarebytes, Sophos, and Trend Micro report the file as clean.
>
> [VirusTotal Report](https://www.virustotal.com/gui/file/8093821caf8639574a6be6cfd91bb672d986ae5213c0dbc4f43389bd779b01fd/detection)

### Building from Source

**Windows EXE:**

```powershell
py -3 -m pip install --upgrade pillow tkinterdnd2 pyinstaller
py -3 build_windows_exe.py
```

Output: `dist\G-TMCE.exe`

On first launch, the EXE registers a per-user Explorer context menu entry for supported media containers. The menu item is named `Open with G-TMCE Extract`. No admin permission is required as registry entries are written under `HKEY_CURRENT_USER`. If you move the portable EXE, launch it once from the new location to refresh the context menu command path.

```powershell
dist\G-TMCE.exe --install-context-menu
dist\G-TMCE.exe --uninstall-context-menu
```

**AppImage:**

```bash
chmod +x build_appimage.sh
./build_appimage.sh
```

Output: `G-TMCE-x86_64.AppImage`

---

## Launch

```bash
# As a command
g-tmce

# Directly
python3 mkv_creator_ui.py
```

---

## Third-Party Tool Management

G-TMCE does not depend on system-installed MKVToolNix or FFmpeg binaries. On first use, the application automatically creates the `3rdParty/` directory and downloads:

- MKVToolNix AppImage → `mkvmerge`, `mkvextract`
- FFmpeg build → `ffmpeg`, `ffprobe`

**Automatic Updates:** Latest versions are checked once per session. New versions are downloaded before old versions are removed; old versions are cleaned automatically after successful installation.

If there is no internet connection, existing installed tools continue to work. Operations fail only if no previous installation exists.

Persistent files:
```
3rdParty/bin/
3rdParty/installed.json
```

---

## Create MKV Workflow

1. Select the track folder
2. Enter your TMDB API key
3. Select media type (`movie` or `tv`), artwork language, and tag language
4. Press `Find ID`
5. Optionally enter video FPS, default audio languages, and default subtitle languages
6. Press `Download Artwork/Tags`
7. Press `Create MKV`

---

## Extract MKV Workflow

1. Select the source MKV
2. Track scan opens automatically
3. Optionally refresh with `Scan MKV`
4. Toggle off unwanted items
5. Press `Extract Selected`

The extraction folder is automatically set as the current track folder.

---

## Track Folder Naming Rules

The selected track folder should contain one media track per file. Files extracted with G-TMCE are already named in the expected format.

Media track files must be placed directly inside the selected track folder. Font attachments can be inside subfolders.

Recommended naming style:

```
<language>[.<flag>...][.<fps>].<extension>
```

Examples:

```
und.23.976.h265
en.eac3
tr.ac3
forced.en.srt
sdh.tr.srt
tr.ass
```

### Supported Track Extensions

| Type | Extensions |
|---|---|
| Video | `.h264` `.h265` `.hevc` `.avc` `.m1v` `.m2v` `.ivf` |
| Audio | `.aac` `.ac3` `.eac3` `.ec3` `.dts` `.dtshd` `.flac` `.m4a` `.mp2` `.mp3` `.ogg` `.opus` `.thd` `.truehd` `.wav` |
| Subtitle | `.srt` `.ass` `.ssa` `.vtt` `.sup` `.sub` |

### Language Tokens

G-TMCE reads the language from filename tokens separated by dots, underscores, hyphens, or spaces. Use a clear two-letter language code whenever possible:

```
en.eac3   tr.srt   ja.ass
```

Common aliases are also accepted:

| Alias | Language |
|---|---|
| `eng` | `en` |
| `tur` | `tr` |
| `jpn` | `ja` |
| `deu` / `ger` | `de` |
| `fre` / `fra` | `fr` |
| `spa` | `es` |

If the filename contains `und`, the track is treated as unknown and inherits the selected tag language during muxing.

### Video FPS Tokens

Video FPS can be detected from the video filename when it appears as its own token:

```
und.23.976.h265
und.24.h264
und.24000/1001.h265
```

If the Video FPS field in the UI is filled, that value overrides the filename-detected FPS.

### Forced and SDH Subtitles

**Forced subtitles** are detected from these tokens: `forced`, `force`, `forc`

```
forced.en.srt   en.forced.ass
```

- Track name becomes `Forced`
- Forced display flag is enabled

**SDH / hearing-impaired subtitles** are detected from these tokens: `sdh`, `hi`, `cc`, `hearing`

```
sdh.en.srt   tr.cc.ass
```

- Track name becomes `SDH`
- Hearing-impaired flag is enabled

If both tokens are present, the track name becomes `Forced SDH`.

### Audio Append

Split audio files can be appended automatically. The main file and numbered parts must share the same base name and extension:

```
en.eac3
en.1.eac3
en.2.eac3
```

- `.1` must exist for append detection to start
- `.2`, `.3`, etc. are appended in numeric order
- Append parts are not added as separate tracks
- Audio and video append is supported; subtitle append is not

In the **Add Tracks** window, audio rows have a `+` control to append one or more audio files to the selected track without manually placing numbered files in the folder.

### Attachments, Artwork, and Fonts

The following artwork files are attached automatically when present in the selected track folder:

```
cover.jpg         small_cover.jpg
cover_land.jpg    small_cover_land.jpg
logo.png
```

Cover artwork is normalized to Matroska cover-art sizes:
- `cover.jpg` and `cover_land.jpg`: 600 px on the smallest side
- `small_cover.jpg` and `small_cover_land.jpg`: 120 px on the smallest side

Font files are attached automatically and may be placed directly in the track folder or inside subfolders.

Supported font extensions: `.ttf` `.otf` `.ttc` `.otc` `.woff` `.woff2`

Font attachment notes:
- Keep the original font files used by `.ass` / `.ssa` subtitles
- Avoid duplicate font filenames that differ only by letter case
- Attachment names are written using the file name

### Example Folder Structure

```
Movie.Name.2025_tracks/
  und.23.976.h265
  en.eac3
  tr.ac3
  forced.en.srt
  tr.ass
  cover.jpg
  small_cover.jpg
  cover_land.jpg
  small_cover_land.jpg
  logo.png
  fonts/
    Arial.ttf
    SomeSubtitleFont.otf
```

Key points:
- Use clear language tokens such as `en`, `tr`, `ja`, or `und`
- Put metadata words like `forced` and `sdh` in separate filename tokens
- Keep media track files at the top level of the track folder
- Keep append parts beside the main file
- Use extracted single-track files for predictable muxing

---

## TMDB Integration

G-TMCE can automatically download:

```
cover.jpg   small_cover.jpg   cover_land.jpg   small_cover_land.jpg   logo.png
```

It can also automatically generate `tags.xml`.

If `tags.xml` already exists it is not overwritten, but missing G-TMCE app tags are added. Existing artwork files are also kept and skipped by the TMDB download step. During muxing, `--global-tags` is automatically applied.

---

## Output Naming

The final MKV filename is generated from the TMDB title using the selected artwork language.

Example:
```
Artwork language: tr
TMDB title:       Interstellar
Output:           Yıldızlararası.mkv
```

`Find ID` also attempts to detect title and year from folder names:

```
Project.Hail.Mary.2026.1080p...  →  Project Hail Mary (2026)
```

---

## Language Handling

Tracks without a detectable language (`und.*`) automatically inherit the selected tag language during muxing.

### Default Audio Selection

Language priority can be entered as:

```
en,tr,jp
```

- The first matching language becomes default
- Video tracks stay first
- Audio tracks are grouped together after video tracks
- Matching audio languages are moved to the top of the audio group

### Default Subtitle Selection

If subtitle priority is empty, no subtitle track becomes default.

Subtitle tracks are grouped after audio tracks. When subtitle priority is set, matching languages are moved to the top of the subtitle group. Forced subtitles only become default if explicitly selected by language priority.

---

## Automatic Template Generation

Template config is optional. If no config is provided, G-TMCE automatically generates a mux template using known track extensions such as:

```
*.h264   *.h265   *.ac3   *.eac3   *.srt
```

---

## Automatic Chapters

If `chapters.txt` does not exist and automatic chapters are enabled, G-TMCE generates chapters using: chapter name, interval, start number, and end minute. When intro-end detection is enabled, the first automatic chapter is aligned to the detected intro end when the signal is reliable; otherwise the normal interval-based start is used.

Example output:

```
CHAPTER03=00:30:00.000
CHAPTER03NAME=ggrbz 3
```

Durations over 60 minutes are automatically written as:

```
01:00:00.000
```

---

## Extraction Naming Rules

Second extracted tracks with the same language are numbered with parentheses so they stay separate from append parts:

```
eng.(2).srt
tur.(2).srt
```

Append parts still use plain numeric suffixes, such as `eng.1.eac3` and `eng.2.eac3`, and are appended to `eng.eac3`.

Extracted video tracks include the detected FPS:

```
und.23.976.h264
```

If `mkvmerge` exits with code `1`, the operation is still considered successful because MKVToolNix uses exit code `1` for warnings.

---

## Settings

The following settings are saved automatically:

- TMDB API key
- Media type
- Artwork language
- Tag language
- Video FPS
- Chapter settings

Location: `~/.config/g-tmce/settings.json`

---

## Notes

- Missing optional tracks are skipped automatically
- Missing TMDB artwork does not stop muxing
- Existing artwork files are reused if already present
- Every mux operation writes a `*.generated.mtxcfg` file beside the output MKV for auditing and debugging

---

## License

[LICENSE](LICENSE)
