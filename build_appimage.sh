#!/usr/bin/env bash
set -Eeuo pipefail

# -----------------------------------------------------------------------------
# G-TMCE AppImage Build Script
# -----------------------------------------------------------------------------
# This script builds a Linux AppImage package for G-TMCE.
#
# It performs the following steps:
#   1. Validates the project structure
#   2. Builds the application with PyInstaller
#   3. Creates a valid AppDir layout
#   4. Downloads appimagetool if needed
#   5. Generates the final AppImage package
#
# Usage:
#   chmod +x build_appimage.sh
#   ./build_appimage.sh
# -----------------------------------------------------------------------------

APP_NAME="G-TMCE"
ENTRY_FILE="mkv_creator_ui.py"
ICON_FILE="logo.png"
DESKTOP_FILE="${APP_NAME}.desktop"
APPDIR="${APP_NAME}.AppDir"
DIST_DIR="dist"
BUILD_DIR="build"
TOOLS_DIR=".build-tools"
APPIMAGETOOL="${TOOLS_DIR}/appimagetool-x86_64.AppImage"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/latest/download/appimagetool-x86_64.AppImage"
OUTPUT_PATTERN="${APP_NAME}-*.AppImage"

log() {
  printf '\033[1;34m[INFO]\033[0m %s\n' "$1"
}

success() {
  printf '\033[1;32m[SUCCESS]\033[0m %s\n' "$1"
}

warn() {
  printf '\033[1;33m[WARNING]\033[0m %s\n' "$1"
}

fail() {
  printf '\033[1;31m[ERROR]\033[0m %s\n' "$1" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

cleanup_old_outputs() {
  log "Cleaning previous build artifacts..."
  rm -rf "$APPDIR" "$BUILD_DIR"
  rm -f "${APP_NAME}.spec"
  rm -f $OUTPUT_PATTERN 2>/dev/null || true
  rm -f "${DIST_DIR}"/${OUTPUT_PATTERN} 2>/dev/null || true
}

validate_project() {
  log "Validating project files..."

  [[ -f "$ENTRY_FILE" ]] || fail "Entry file not found: ${ENTRY_FILE}"
  [[ -f "$ICON_FILE" ]] || fail "Icon file not found: ${ICON_FILE}"

  if ! command_exists python3; then
    fail "python3 is not installed or not available in PATH."
  fi

  if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    warn "PyInstaller is not installed for the current Python environment."
    log "Installing PyInstaller with pip..."
    python3 -m pip install --user pyinstaller
  fi
}

build_binary() {
  log "Building ${APP_NAME} executable with PyInstaller..."

  python3 -m PyInstaller \
    --onefile \
    --windowed \
    --name "$APP_NAME" \
    "$ENTRY_FILE"

  [[ -x "${DIST_DIR}/${APP_NAME}" ]] || fail "PyInstaller output was not created: ${DIST_DIR}/${APP_NAME}"
}

create_appdir() {
  log "Creating AppDir structure..."

  mkdir -p "${APPDIR}/usr/bin"
  mkdir -p "${APPDIR}/usr/share/applications"
  mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

  cp "${DIST_DIR}/${APP_NAME}" "${APPDIR}/usr/bin/${APP_NAME}"
  chmod +x "${APPDIR}/usr/bin/${APP_NAME}"

  cp "$ICON_FILE" "${APPDIR}/${APP_NAME}.png"
  cp "$ICON_FILE" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png"

  cat > "${APPDIR}/AppRun" <<APPRUN
#!/usr/bin/env sh
HERE="\$(dirname "\$(readlink -f "\$0")")"
exec "\$HERE/usr/bin/${APP_NAME}" "\$@"
APPRUN
  chmod +x "${APPDIR}/AppRun"

  cat > "${APPDIR}/${DESKTOP_FILE}" <<DESKTOP
[Desktop Entry]
Type=Application
Name=G-TMCE
Comment=Extract and create MKV files with TMDB metadata support
Exec=${APP_NAME}
Icon=${APP_NAME}
Categories=AudioVideo;Video;
Terminal=false
DESKTOP

  cp "${APPDIR}/${DESKTOP_FILE}" "${APPDIR}/usr/share/applications/${DESKTOP_FILE}"
}

download_appimagetool() {
  mkdir -p "$TOOLS_DIR"

  if [[ -x "$APPIMAGETOOL" ]]; then
    log "Using existing appimagetool: ${APPIMAGETOOL}"
    return
  fi

  log "Downloading appimagetool..."

  if command_exists wget; then
    wget -O "$APPIMAGETOOL" "$APPIMAGETOOL_URL"
  elif command_exists curl; then
    curl -L -o "$APPIMAGETOOL" "$APPIMAGETOOL_URL"
  else
    fail "Neither wget nor curl is available. Please install one of them and try again."
  fi

  chmod +x "$APPIMAGETOOL"
}

build_appimage() {
  log "Generating AppImage package..."

  mkdir -p "$DIST_DIR"

  ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR"

  local generated_file
  generated_file="$(ls -1 ${OUTPUT_PATTERN} 2>/dev/null | head -n 1 || true)"

  [[ -n "$generated_file" ]] || fail "AppImage was not generated."

  local final_file="${DIST_DIR}/${generated_file}"
  mv -f "$generated_file" "$final_file"
  chmod +x "$final_file"

  success "AppImage build completed: ${final_file}"
}

main() {
  log "Starting G-TMCE AppImage build..."
  validate_project
  cleanup_old_outputs
  build_binary
  create_appdir
  download_appimagetool
  build_appimage
  success "Done. You can now run the AppImage by double-clicking it or from the terminal."
}

main "$@"
