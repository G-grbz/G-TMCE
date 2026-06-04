# G-TMCE

G-TMCE is a Tkinter application for extracting and creating MKV files, available on Linux and Windows.

It generates a `tags.xml` using the TMDB API, enriches MKV files with titles and visuals, and ensures MKV files are always created with a consistent structure.
<p align="center">
  <img src="https://github.com/user-attachments/assets/694c61ad-c62e-4067-b8a7-50ac4fa2b057" width="900">
</p>

---

# Features

## MKV Creation

* Automatic MKVToolNix config generation from track folders
* Optional TMDB artwork download
* Automatic `tags.xml` generation
* Automatic output title generation from TMDB metadata
* Automatic chapter generation
* Default audio/subtitle selection by language priority
* Subtitle forced/SDH detection
* Audio append support (`eng.ac3` + `eng.1.ac3` etc.)
* Automatic FPS detection and override support
* Generated `.generated.mtxcfg` audit file for every mux

## MKV Extraction

* Extract:
  * Video tracks
  * Audio tracks
  * Subtitle tracks
  * Attachments
  * Chapters
  * Tags

* Automatic output naming
* Forced/SDH subtitle naming
* FPS detection for extracted video tracks

## Audio Adjustment

* Delay or cut audio tracks
* Codec conversion
* Bitrate/sample-rate/channel-layout adjustment
* Volume boost
* FPS speed synchronization presets

---

# Requirements

## Runtime

* Linux
* Python 3.10+
* Tkinter
* Pillow

## Supported Architectures

### MKVToolNix AppImage

* Linux x86_64

### FFmpeg Builds

* Linux x86_64
* Linux aarch64

### Windows

* Windows x86_64 (via pre-built EXE or PyInstaller)

---

# Installation

## Arch Linux (AUR)

G-TMCE is available on the Arch User Repository as [`g-tmce`](https://aur.archlinux.org/packages/g-tmce).

Using an AUR helper:

```bash
yay -S g-tmce
```

or:

```bash
paru -S g-tmce
```

Manual AUR installation:

```bash
git clone https://aur.archlinux.org/g-tmce.git
cd g-tmce
makepkg -si
```

The AUR package installs the `g-tmce` launcher command, desktop menu entry, application icon, and Dolphin/KDE service menu integration.

Optional native file dialog helpers:

```bash
sudo pacman -S --needed kdialog zenity
```

---

## Clone Repository

```bash
git clone https://github.com/G-grbz/G-TMCE.git
cd G-TMCE
```

## Automatic Installation (Recommended)

```bash
chmod +x install.sh && sudo ./install.sh
```

The installer automatically:

* Installs required system dependencies
* Installs desktop launcher entries
* Installs application icons
* Installs Dolphin context menu integration
* Creates the `g-tmce` launcher command

Supported distributions:

* Debian / Ubuntu
* Fedora
* Arch Linux
* openSUSE

---

# Release

You can download a pre-built executable or AppImage from the [Releases](../../releases) page, or build one yourself using the instructions below.

> **Windows support has been added.** A pre-built `.exe` is available for download on the Releases page.
>
> **VirusTotal Note:** A few antivirus engines may occasionally flag G-TMCE as suspicious. The application uses FFmpeg and MKVToolNix, works directly with media files, and launches external processes as part of its normal operation. Because of this, some machine learning–based antivirus solutions may generate false positives.
>
> At the time of writing, the latest release is detected by 5 out of 71 security vendors on VirusTotal, while major vendors such as BitDefender, Kaspersky, ESET, Malwarebytes, Sophos, and Trend Micro report the file as clean.
>
> VirusTotal report:
> https://www.virustotal.com/gui/file/8093821caf8639574a6be6cfd91bb672d986ae5213c0dbc4f43389bd779b01fd/detection

## Building from Source

### Windows EXE

```powershell
py -3 -m pip install --upgrade pillow tkinterdnd2 pyinstaller
py -3 build_windows_exe.py
```

Output path:

```text
dist\G-TMCE.exe
```

Windows right-click integration:

* On first launch, the EXE registers a per-user Explorer context menu entry for supported media containers.
* The menu item is named `Open with G-TMCE Extract` and opens the selected file directly in the extraction window.
* No admin permission is required because the registry entries are written under `HKEY_CURRENT_USER`.
* If you move the portable EXE, launch it once from the new location so the context menu command path is refreshed.

Manual commands:

```powershell
dist\G-TMCE.exe --install-context-menu
dist\G-TMCE.exe --uninstall-context-menu
```

### AppImage

```bash
chmod +x build_appimage.sh
./build_appimage.sh
```

Output path:

```text
G-TMCE-x86_64.AppImage
```

---

# Launch

## From Terminal

```bash
g-tmce
```

or:

```bash
python3 mkv_creator_ui.py
```

---

# Third-Party Tool Management

G-TMCE does not depend on system-installed MKVToolNix or FFmpeg binaries.

On first use, the application automatically creates:

```text
3rdParty/
```

and downloads:

* MKVToolNix AppImage
* FFmpeg build

The following tools are prepared automatically:

* `mkvmerge`
* `mkvextract`
* `ffmpeg`
* `ffprobe`

## Automatic Updates

During application runtime:

* Latest versions are checked once per session
* New versions are downloaded before old versions are removed
* Old versions are cleaned automatically after successful installation

If there is no internet connection:

* Existing installed tools continue to work
* Operations fail only if no previous installation exists

Temporary downloads and extraction folders are automatically cleaned after installation/update.

Persistent files:

```text
3rdParty/bin/
3rdParty/installed.json
```

---

# Create MKV Workflow

1. Select the track folder
2. Enter your TMDB API key
3. Select:
   * Media type (`movie` or `tv`)
   * Artwork language
   * Tag language
4. Press `Find ID`
5. Optionally enter:
   * Video FPS
   * Default audio languages
   * Default subtitle languages
6. Press `Download Artwork/Tags`
7. Press `Create MKV`

---

# Extract MKV Workflow

1. Select source MKV
2. Track scan opens automatically
3. Optionally refresh with `Scan MKV`
4. Toggle unwanted items
5. Press `Extract Selected`

The extraction folder is automatically updated as the current track folder.

---

# Automatic Template Generation

Template config is optional.

If no config is provided, G-TMCE automatically generates a mux template using known track extensions such as:

```text
*.h264
*.h265
*.ac3
*.eac3
*.srt
```

---

# Track Folder Naming Rules

The selected track folder should contain one media track per file. Files extracted with G-TMCE are already named in the expected format.

Media track files must be placed directly inside the selected track folder. Font attachments can be inside subfolders.

Recommended naming style:

```text
<language>[.<flag>...][.<fps>].<extension>
```

Examples:

```text
und.23.976.h265
en.eac3
tr.ac3
forced.en.srt
sdh.tr.srt
tr.ass
```

## Supported Track Extensions

Video track files:

```text
.h264 .h265 .hevc .avc .m1v .m2v .ivf
```

Audio track files:

```text
.aac .ac3 .eac3 .ec3 .dts .dtshd .flac .m4a .mp2 .mp3 .ogg .opus .thd .truehd .wav
```

Subtitle track files:

```text
.srt .ass .ssa .vtt .sup .sub
```

## Language Tokens

G-TMCE reads the language from filename tokens separated by dots, underscores, hyphens, or spaces.

Use a clear two-letter language code whenever possible:

```text
en.eac3
tr.srt
ja.ass
```

Common aliases are also accepted:

```text
eng -> en
tur -> tr
jpn -> ja
deu / ger -> de
fre / fra -> fr
spa -> es
```

If the filename contains:

```text
und
```

the track is treated as unknown and inherits the selected tag language during muxing.

## Video FPS Tokens

Video FPS can be detected from the video filename when it appears as its own token:

```text
und.23.976.h265
und.24.h264
und.24000/1001.h265
```

If the Video FPS field in the UI is filled, that value overrides the filename-detected FPS.

## Forced and SDH Subtitles

Forced subtitles are detected from these tokens:

```text
forced
force
forc
```

Examples:

```text
forced.en.srt
en.forced.ass
```

Forced subtitle behavior:

* Track name becomes `Forced`
* Forced display flag is enabled

SDH / hearing-impaired subtitles are detected from these tokens:

```text
sdh
hi
cc
hearing
```

Examples:

```text
sdh.en.srt
tr.cc.ass
```

SDH subtitle behavior:

* Track name becomes `SDH`
* Hearing-impaired flag is enabled

If both forced and SDH tokens are present, the track name becomes:

```text
Forced SDH
```

## Audio Append Naming

Split audio files can be appended automatically.

The main file and numbered parts must share the same base name and extension:

```text
en.eac3
en.1.eac3
en.2.eac3
```

Rules:

* `.1` must exist for append detection to start
* `.2`, `.3`, etc. are appended in numeric order
* Append parts are not added as separate tracks
* Audio and video append is supported
* Subtitle append is not supported

In the **Add Tracks** window, audio rows also have a `+` control. Use it to append one or more audio files to the selected audio track without placing numbered files in the track folder manually.

## Additional Subtitle Files

When `Include additional subtitles` is enabled, subtitle files found in the track folder are added even if they were not listed in the original template.

When it is disabled, only subtitle entries already present in the template are used.

## Attachments, Artwork, and Fonts

These artwork files are attached automatically when they exist in the selected track folder:

```text
cover.jpg
small_cover.jpg
cover_land.jpg
small_cover_land.jpg
logo.png
```

Font files are attached automatically. They may be placed directly in the selected track folder or inside subfolders.

The **Add Tracks** window also accepts `chapters.txt`, `tags.xml`, and the artwork file names listed above. Added metadata/artwork files are copied into the selected track folder before muxing, so existing manual files are used instead of being generated or downloaded again. Enable `Fill missing artwork/tags from TMDB` in that window to try downloading any missing artwork and `tags.xml`.

Supported font extensions:

```text
.ttf .otf .ttc .otc .woff .woff2
```

Font attachment notes:

* Keep the original font files used by `.ass` / `.ssa` subtitles
* Avoid duplicate font filenames that differ only by letter case
* Attachment names are written using the file name
* If a custom template requires an attachment by name, the file must exist in the selected track folder

## Practical Folder Example

```text
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

Important:

* Use clear language tokens such as `en`, `tr`, `ja`, or `und`
* Put metadata words like `forced` and `sdh` in separate filename tokens
* Keep media track files at the top level of the selected track folder
* Keep append parts beside the main file
* Use extracted single-track files for predictable muxing

---

# TMDB Integration

G-TMCE can automatically download:

* `cover.jpg`
* `small_cover.jpg`
* `cover_land.jpg`
* `small_cover_land.jpg`
* `logo.png`

Cover artwork is normalized to Matroska cover-art sizes:

* `cover.jpg` and `cover_land.jpg`: 600 px on the smallest side
* `small_cover.jpg` and `small_cover_land.jpg`: 120 px on the smallest side

It can also automatically generate:

```text
tags.xml
```

If `tags.xml` already exists, it is not overwritten. Existing artwork files are also kept and skipped by the TMDB download step.

During muxing:

```text
--global-tags
```

is automatically applied.

---

# Output Naming

The final MKV filename is generated from the TMDB title using the selected artwork language.

Example:

```text
Artwork language: tr
TMDB title: Interstellar
Output: Yıldızlararası.mkv
```

`Find ID` also attempts to detect title/year from folder names:

```text
Project.Hail.Mary.2026.1080p...
```

becomes:

```text
Project Hail Mary
2026
```

---

# Language Handling

## Unknown Languages

Tracks without detectable language:

```text
und.*
```

automatically inherit the selected tag language during muxing.

Example:

```text
Tag language: en
und.* -> en
```

```text
Tag language: tr
und.* -> tr
```

This behavior is used as the fallback language mechanism for unknown tracks.

## Default Audio Selection

Language priority can be entered like:

```text
en,tr,jp
```

Behavior:

* First matching language becomes default
* Video tracks stay first
* Audio tracks are grouped together after video tracks
* Matching audio languages are moved to the top of the audio group

## Default Subtitle Selection

If subtitle priority is empty:

* No subtitle track becomes default

Subtitle tracks are grouped together after audio tracks. When subtitle priority is set, matching subtitle languages are moved to the top of the subtitle group.

Forced subtitles only become default if explicitly selected by language priority.

---

# Subtitle Handling

## Forced Subtitles

```text
forced.eng.srt
```

* Track name becomes `Forced`
* Forced display flag remains enabled

## SDH Subtitles

```text
sdh.eng.srt
```

are automatically recognized.

---

# Audio Append Support

If files like:

```text
eng.ac3
eng.1.ac3
eng.2.ac3
```

exist in the same folder:

* `.1`, `.2` files are appended to the main track
* They are not added as separate tracks

---

# Automatic Chapters

If `chapters.txt` does not exist and automatic chapters are enabled:

G-TMCE generates chapters using:

* Chapter name
* Interval
* Start number
* End minute

Example output:

```text
CHAPTER03=00:30:00.000
CHAPTER03NAME=ggrbz 3
```

Durations over 60 minutes are automatically written as:

```text
01:00:00.000
```

---

# Extraction Naming Rules

Second tracks with same language:

```text
eng.2.srt
tur.2.srt
```

Extracted video tracks include detected FPS:

```text
und.23.976.h264
```

---

# MKVMerge Behavior

If `mkvmerge` exits with code:

```text
1
```

the operation is still considered successful because MKVToolNix uses exit code `1` for warnings.

---

# Settings Storage

The following settings are saved automatically:

* TMDB API key
* Media type
* Artwork language
* Tag language
* Video FPS
* Chapter settings

Location:

```text
~/.config/g-tmce/settings.json
```

---

# Notes

* Missing optional tracks are skipped automatically
* Missing TMDB artwork does not stop muxing
* Existing artwork files are reused if already present
* Every mux operation writes a:

```text
*.generated.mtxcfg
```

file beside the output MKV for auditing/debugging purposes

---

# License

[LICENSE](LICENSE)
