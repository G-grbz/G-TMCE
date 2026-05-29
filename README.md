# G-TMCE

G-TMCE is a Tkinter application for extracting and creating MKV files, available on Linux and Windows.

It generates a `tags.xml` using the TMDB API, enriches MKV files with titles and visuals, and ensures MKV files are always created with a consistent structure.

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

## Building from Source

### Windows EXE

```powershell
py -3 -m pip install --upgrade pillow pyinstaller
py -3 build_windows_exe.py
```

Output path:

```text
dist\G-TMCE.exe
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

# TMDB Integration

G-TMCE can automatically download:

* `cover.jpg`
* `small_cover.jpg`
* `l2a.jpg`
* `l2p.png`

It can also automatically generate:

```text
tags.xml
```

If `tags.xml` already exists, it is not overwritten.

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
* Matching audio tracks are moved to the top

## Default Subtitle Selection

If subtitle priority is empty:

* No subtitle track becomes default

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
~/.config/mkv-creator-ui/settings.json
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
