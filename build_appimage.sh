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
VERSION_FILE="VERSION"
DESKTOP_FILE="${APP_NAME}.desktop"
APPDIR="${APP_NAME}.AppDir"
DIST_DIR="dist"
BUILD_DIR="build"
TOOLS_DIR=".build-tools"
BUILD_VENV="${TOOLS_DIR}/python-venv"
BUILD_PYTHON="${BUILD_VENV}/bin/python"
APPIMAGETOOL_VERSION="1.9.1"
APPIMAGETOOL="${TOOLS_DIR}/appimagetool-x86_64.AppImage"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
APPIMAGE_RUNTIME_TAG="20251108"
APPIMAGE_RUNTIME="${TOOLS_DIR}/runtime-x86_64"
APPIMAGE_RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/${APPIMAGE_RUNTIME_TAG}/runtime-x86_64"
APPIMAGE_RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
OUTPUT_FILE="${DIST_DIR}/${APP_NAME}-x86_64.AppImage"

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

python_module_exists() {
  "$BUILD_PYTHON" - "$1" >/dev/null 2>&1 <<'PY'
import importlib.util
import sys

module = sys.argv[1]
sys.exit(0 if importlib.util.find_spec(module) else 1)
PY
}

ensure_python_package() {
  local module="$1"
  local package="$2"

  if python_module_exists "$module"; then
    return
  fi

  warn "Python module ${module} is not installed."
  log "Installing ${package} into build virtual environment..."
  "$BUILD_PYTHON" -m pip install --upgrade "$package"
}

ensure_build_venv() {
  if [[ -x "$BUILD_PYTHON" ]]; then
    return
  fi

  log "Creating build virtual environment: ${BUILD_VENV}"
  python3 -m venv "$BUILD_VENV" || fail "Could not create Python virtual environment. Install python-venv/python-virtualenv support for your distribution."
  "$BUILD_PYTHON" -m pip install --upgrade pip
}

cleanup_old_outputs() {
  log "Cleaning previous build artifacts..."
  rm -rf "$APPDIR" "$BUILD_DIR"
  rm -f "${APP_NAME}.spec"
  rm -f "$OUTPUT_FILE"
}

validate_project() {
  log "Validating project files..."

  [[ -f "$ENTRY_FILE" ]] || fail "Entry file not found: ${ENTRY_FILE}"
  [[ -f "$ICON_FILE" ]] || fail "Icon file not found: ${ICON_FILE}"

  if ! command_exists python3; then
    fail "python3 is not installed or not available in PATH."
  fi

  ensure_build_venv

  ensure_python_package "PyInstaller" "PyInstaller>=6.15,<7"
  ensure_python_package "PIL" "Pillow>=10,<13"
  ensure_python_package "tkinterdnd2" "tkinterdnd2>=0.4,<1"
}

build_binary() {
  log "Building ${APP_NAME} executable with PyInstaller..."

  local add_data_args=()
  if [[ -f "$VERSION_FILE" ]]; then
    add_data_args+=(--add-data "${VERSION_FILE}:.")
  fi

  "$BUILD_PYTHON" -m PyInstaller \
    --onefile \
    --windowed \
    --name "$APP_NAME" \
    --hidden-import tkinterdnd2 \
    --collect-all tkinterdnd2 \
    "${add_data_args[@]}" \
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

  log "Downloading pinned appimagetool ${APPIMAGETOOL_VERSION}..."

  local temporary="${APPIMAGETOOL}.download"
  rm -f "$temporary"
  if command_exists wget; then
    wget --https-only --secure-protocol=TLSv1_2 --timeout=30 --tries=3 -O "$temporary" "$APPIMAGETOOL_URL"
  elif command_exists curl; then
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 30 -o "$temporary" "$APPIMAGETOOL_URL"
  else
    fail "Neither wget nor curl is available. Please install one of them and try again."
  fi

  printf '%s  %s\n' "$APPIMAGETOOL_SHA256" "$temporary" | sha256sum -c - \
    || fail "appimagetool SHA-256 verification failed."
  mv -f "$temporary" "$APPIMAGETOOL"
  chmod 0755 "$APPIMAGETOOL"
}


download_appimage_runtime() {
  mkdir -p "$TOOLS_DIR"

  if [[ -f "$APPIMAGE_RUNTIME" ]]; then
    if printf '%s  %s
' "$APPIMAGE_RUNTIME_SHA256" "$APPIMAGE_RUNTIME" | sha256sum -c - >/dev/null 2>&1; then
      log "Using verified AppImage runtime: ${APPIMAGE_RUNTIME}"
      return
    fi
    warn "Cached AppImage runtime failed verification; downloading a fresh copy."
    rm -f "$APPIMAGE_RUNTIME"
  fi

  log "Downloading pinned AppImage runtime ${APPIMAGE_RUNTIME_TAG}..."
  local temporary="${APPIMAGE_RUNTIME}.download"
  rm -f "$temporary"
  if command_exists wget; then
    wget --https-only --secure-protocol=TLSv1_2 --timeout=30 --tries=3 -O "$temporary" "$APPIMAGE_RUNTIME_URL"
  elif command_exists curl; then
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 30 -o "$temporary" "$APPIMAGE_RUNTIME_URL"
  else
    fail "Neither wget nor curl is available. Please install one of them and try again."
  fi

  printf '%s  %s
' "$APPIMAGE_RUNTIME_SHA256" "$temporary" | sha256sum -c -     || fail "AppImage runtime SHA-256 verification failed."
  mv -f "$temporary" "$APPIMAGE_RUNTIME"
  chmod 0644 "$APPIMAGE_RUNTIME"
}

build_appimage() {
  log "Generating AppImage package..."

  mkdir -p "$DIST_DIR"
  rm -f "$OUTPUT_FILE"

  ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN="${APPIMAGE_EXTRACT_AND_RUN:-1}" \
    "$APPIMAGETOOL" --runtime-file "$APPIMAGE_RUNTIME" "$APPDIR" "$OUTPUT_FILE"

  [[ -f "$OUTPUT_FILE" ]] || fail "AppImage was not generated: ${OUTPUT_FILE}"
  chmod 0755 "$OUTPUT_FILE"

  success "AppImage build completed: ${OUTPUT_FILE}"
}

main() {
  log "Starting G-TMCE AppImage build..."
  validate_project
  cleanup_old_outputs
  build_binary
  create_appdir
  download_appimagetool
  download_appimage_runtime
  build_appimage
  success "Done. You can now run the AppImage by double-clicking it or from the terminal."
}

main "$@"
