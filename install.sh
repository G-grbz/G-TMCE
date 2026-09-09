#!/usr/bin/env bash
set -euo pipefail

APP_ID="g-tmce"
APP_NAME="G-TMCE"
SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/G-TMCE"
BIN_LINK="/usr/local/bin/g-tmce"
VENDOR_DIR="$INSTALL_DIR/vendor"

APP_DESKTOP_DIR="/usr/share/applications"
PIXMAP_DIR="/usr/share/pixmaps"

KDE_SERVICE_DIRS=(
  "/usr/share/kio/servicemenus"
  "/usr/share/kservices5/ServiceMenus"
  "/usr/share/kservices6/ServiceMenus"
)

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Administrator privileges are required."
    echo "Run: sudo ./install.sh"
    exit 1
  fi
}

detect_distro() {
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="${ID:-unknown}"
    DISTRO_LIKE="${ID_LIKE:-}"
  else
    DISTRO_ID="unknown"
    DISTRO_LIKE=""
  fi
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

is_debian_like() {
  [[ "$DISTRO_ID" =~ ^(debian|ubuntu|linuxmint|pop|elementary|zorin)$ ]] || [[ "$DISTRO_LIKE" == *"debian"* ]]
}

is_fedora_like() {
  [[ "$DISTRO_ID" =~ ^(fedora|rhel|centos|rocky|almalinux|nobara)$ ]] || [[ "$DISTRO_LIKE" == *"fedora"* ]] || [[ "$DISTRO_LIKE" == *"rhel"* ]]
}

is_arch_like() {
  [[ "$DISTRO_ID" =~ ^(arch|manjaro|endeavouros|garuda)$ ]] || [[ "$DISTRO_LIKE" == *"arch"* ]]
}

is_opensuse_like() {
  [[ "$DISTRO_ID" =~ ^(opensuse.*|suse|sles)$ ]] || [[ "$DISTRO_LIKE" == *"suse"* ]]
}

check_python_module() {
  python3 - "$1" >/dev/null 2>&1 <<'PY'
import importlib.util
import sys

module = sys.argv[1]
sys.exit(0 if importlib.util.find_spec(module) else 1)
PY
}

check_dependencies() {
  echo "[0/6] Checking required system dependencies..."

  detect_distro
  local missing_packages=()
  local packages=()

  if is_debian_like; then
    packages=(
      "python3" "python3-pip"
      "libxcb-cursor0" "libxkbcommon-x11-0" "libegl1" "libgl1"
      "desktop-file-utils" "hicolor-icon-theme" "xdg-utils"
    )
    for package in "${packages[@]}"; do
      if dpkg -s "$package" >/dev/null 2>&1; then
        echo "Dependency already installed: $package"
      else
        missing_packages+=("$package")
      fi
    done
    if ((${#missing_packages[@]} > 0)); then
      apt-get update
      apt-get install -y "${missing_packages[@]}"
    fi
  elif is_fedora_like; then
    packages=(
      "python3" "python3-pip"
      "xcb-util-cursor" "libxkbcommon-x11" "mesa-libEGL" "mesa-libGL"
      "desktop-file-utils" "hicolor-icon-theme" "xdg-utils"
    )
    for package in "${packages[@]}"; do
      rpm -q "$package" >/dev/null 2>&1 || missing_packages+=("$package")
    done
    ((${#missing_packages[@]} == 0)) || dnf install -y "${missing_packages[@]}"
  elif is_arch_like; then
    packages=(
      "python" "python-pip"
      "xcb-util-cursor" "libxkbcommon-x11" "libglvnd"
      "desktop-file-utils" "hicolor-icon-theme" "xdg-utils"
    )
    for package in "${packages[@]}"; do
      pacman -Q "$package" >/dev/null 2>&1 || missing_packages+=("$package")
    done
    ((${#missing_packages[@]} == 0)) || pacman -S --needed --noconfirm "${missing_packages[@]}"
  elif is_opensuse_like; then
    packages=(
      "python3" "python3-pip"
      "libxcb-cursor0" "libxkbcommon-x11-0" "libEGL1" "libGL1"
      "desktop-file-utils" "hicolor-icon-theme" "xdg-utils"
    )
    for package in "${packages[@]}"; do
      rpm -q "$package" >/dev/null 2>&1 || missing_packages+=("$package")
    done
    ((${#missing_packages[@]} == 0)) || zypper --non-interactive install "${missing_packages[@]}"
  else
    echo "Unsupported or unknown Linux distribution: ${DISTRO_ID}"
    echo "Install Python 3, pip, Qt/XCB runtime libraries, desktop-file-utils, hicolor-icon-theme and xdg-utils manually."
    exit 1
  fi

  has_command python3 || { echo "Error: python3 is not available."; exit 1; }
  python3 -m pip --version >/dev/null 2>&1 || { echo "Error: pip for Python 3 is not available."; exit 1; }
}

install_vendor_python_package() {
  local module="$1"
  local package="$2"

  if PYTHONPATH="$VENDOR_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$module" >/dev/null 2>&1 <<'PY'
import importlib.util
import sys

module = sys.argv[1]
sys.exit(0 if importlib.util.find_spec(module) else 1)
PY
  then
    echo "Python module already available: $module"
    return
  fi

  echo "Installing Python package into app vendor directory: $package"
  PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 \
    python3 -m pip install --upgrade --target "$VENDOR_DIR" "$package"
}

install_application() {
  echo "[1/6] Installing application files..."

  rm -rf "$INSTALL_DIR"

  mkdir -p "$INSTALL_DIR"
  cp -a "$SRC_DIR/." "$INSTALL_DIR/"

  mkdir -p "$VENDOR_DIR"
  echo "Installing Python runtime requirements into app vendor directory..."
  PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 \
    python3 -m pip install --upgrade --target "$VENDOR_DIR" -r "$INSTALL_DIR/requirements.txt"

  mkdir -p "$INSTALL_DIR/3rdParty/bin"
  mkdir -p "$INSTALL_DIR/3rdParty/.downloads"
  mkdir -p "$INSTALL_DIR/3rdParty/.mkvtoolnix-new"

  find "$INSTALL_DIR" -type d -exec chmod 755 {} \;
  find "$INSTALL_DIR" -type f -exec chmod 644 {} \;

  chmod +x "$INSTALL_DIR/mkv_creator_ui.py" 2>/dev/null || true
  find "$INSTALL_DIR/3rdParty/bin" -type f -exec chmod +x {} \; 2>/dev/null || true

  if [[ -n "${SUDO_USER:-}" ]]; then
    chown -R "$SUDO_USER":"$SUDO_USER" "$INSTALL_DIR/3rdParty"
  fi

  chmod -R 755 "$INSTALL_DIR/3rdParty"
}

install_launcher() {
  echo "[2/6] Installing command launcher..."

cat > "$BIN_LINK" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
export PYTHONPATH="$INSTALL_DIR:$VENDOR_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 "$INSTALL_DIR/mkv_creator_ui.py" "\$@"
EOF

  chmod +x "$BIN_LINK"
}

install_icon() {
  echo "[3/6] Installing application icon..."

  if [[ ! -f "$INSTALL_DIR/assets/logo.png" ]]; then
    echo "Warning: logo.png was not found. Skipping icon installation."
    return
  fi

  for size in 16 24 32 48 64 128 256 512 1024; do
    icon_dir="/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$icon_dir"
    cp "$INSTALL_DIR/assets/logo.png" "$icon_dir/${APP_ID}.png"
    chmod 644 "$icon_dir/${APP_ID}.png"
  done

  mkdir -p "$PIXMAP_DIR"
  cp "$INSTALL_DIR/assets/logo.png" "$PIXMAP_DIR/${APP_ID}.png"
  chmod 644 "$PIXMAP_DIR/${APP_ID}.png"
}

install_desktop_entry() {
  echo "[4/6] Installing desktop application entry..."

  mkdir -p "$APP_DESKTOP_DIR"

  cat > "$APP_DESKTOP_DIR/${APP_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0

Name=G-TMCE
Name[tr]=G-TMCE

GenericName=MKV Creator and Extractor
GenericName[tr]=MKV Oluşturma ve Parça Çıkarma Aracı

Comment=Create MKV files with TMDB metadata and extract tracks, subtitles, chapters, and attachments
Comment[tr]=TMDB verileriyle MKV oluşturur; parça, altyazı, chapter ve ekleri çıkarır

Exec=${BIN_LINK} --extract %f
Icon=${APP_ID}
Path=${INSTALL_DIR}

StartupWMClass=G-TMCE
Terminal=false
StartupNotify=true

MimeType=application/octet-stream;video/*;

Patterns=\
*.mkv;\
*.mk3d;\
*.mka;\
*.mks;\
*.webm;\
*.mp4;\
*.m4v;\
*.mov;\
*.avi;\
*.wmv;\
*.mpg;\
*.mpeg;\
*.ts;\
*.m2ts;\
*.mts

Categories=AudioVideo;Video;Utility;

Keywords=G-TMCE;mkv;matroska;tmdb;metadata;extract;tracks;subtitles;chapters;attachments;
Keywords[tr]=G-TMCE;mkv;matroska;tmdb;metadata;çıkar;parça;altyazı;chapter;ekler;
EOF

  chmod 644 "$APP_DESKTOP_DIR/${APP_ID}.desktop"
}

install_dolphin_service_menu() {
  echo "[5/6] Installing Dolphin service menu..."

  for dir in "${KDE_SERVICE_DIRS[@]}"; do
    mkdir -p "$dir"

    cat > "$dir/${APP_ID}-extract.desktop" <<EOF
[Desktop Entry]
Type=Service

Name=G-TMCE Extract
Name[tr]=G-TMCE Extract

Comment=Extract tracks, subtitles, chapters, and attachments from MKV files
Comment[tr]=MKV dosyalarından parça, altyazı, chapter ve ekleri çıkarır

MimeType=application/octet-stream;video/*;

Patterns=\
*.mkv;\
*.mk3d;\
*.mka;\
*.mks;\
*.webm;\
*.mp4;\
*.m4v;\
*.mov;\
*.avi;\
*.wmv;\
*.mpg;\
*.mpeg;\
*.ts;\
*.m2ts;\
*.mts

ServiceTypes=KonqPopupMenu/Plugin
X-KDE-ServiceTypes=KonqPopupMenu/Plugin
X-KDE-Priority=TopLevel

Icon=${APP_ID}

Actions=openWithGTMCEExtract;

[Desktop Action openWithGTMCEExtract]
Name=Open with G-TMCE Extract
Name[tr]=G-TMCE Extract ile Aç

Icon=${APP_ID}
Exec=${BIN_LINK} --extract %f
EOF

    chmod 644 "$dir/${APP_ID}-extract.desktop"
  done
}

update_caches() {
  echo "[6/6] Updating desktop integration caches..."

  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DESKTOP_DIR" || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -q /usr/share/icons/hicolor || true
  command -v xdg-icon-resource >/dev/null 2>&1 && xdg-icon-resource forceupdate || true

  # KDE's service/application cache is per-user.  Running the installer with
  # sudo and rebuilding only root's ksycoca can leave Dolphin using a stale
  # Open-With/ServiceMenu Exec line.  Refresh the invoking desktop user's cache
  # as well as root's so the new --extract %f handler is effective immediately.
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    user_home="$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6 || true)"
    if [[ -n "$user_home" ]]; then
      if command -v kbuildsycoca6 >/dev/null 2>&1; then
        sudo -u "$SUDO_USER" env HOME="$user_home" kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
      fi
      if command -v kbuildsycoca5 >/dev/null 2>&1; then
        sudo -u "$SUDO_USER" env HOME="$user_home" kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
      fi
    fi
  fi

  command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
  command -v kbuildsycoca5 >/dev/null 2>&1 && kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
}

uninstall_application() {
  require_root

  echo "[1/3] Removing G-TMCE files..."

  rm -rf "$INSTALL_DIR"
  rm -f "$BIN_LINK"
  rm -f "$APP_DESKTOP_DIR/${APP_ID}.desktop"
  rm -f "$PIXMAP_DIR/${APP_ID}.png"

  for size in 16 24 32 48 64 128 256 512 1024; do
    rm -f "/usr/share/icons/hicolor/${size}x${size}/apps/${APP_ID}.png"
  done

  for dir in "${KDE_SERVICE_DIRS[@]}"; do
    rm -f "$dir/${APP_ID}-extract.desktop"
  done

  echo "[2/3] Updating desktop integration caches..."
  update_caches

  echo "[3/3] Done."
  echo
  echo "G-TMCE was uninstalled successfully."
  echo
  echo "User config was kept:"
  echo "- ~/.config/g-tmce"
  echo
  echo "To remove user config too, run:"
  echo "rm -rf ~/.config/g-tmce"
}

main() {
  require_root
  check_dependencies
  install_application
  install_launcher
  install_icon
  install_desktop_entry
  install_dolphin_service_menu
  update_caches

  echo
  echo "Installation completed successfully."
  echo "Application menu entry: G-TMCE"
  echo "Command-line launcher: g-tmce"
  echo
  echo "If the application icon or Dolphin context menu does not appear immediately:"
  echo "1. Remove the old pinned launcher from the panel or dock."
  echo "2. Close all Dolphin windows."
  echo "3. Run: kbuildsycoca6 --noincremental || kbuildsycoca5 --noincremental"
  echo "4. Open G-TMCE from the application menu and pin it again."
}

case "${1:-install}" in
  install)
    main
    ;;
  uninstall|remove)
    uninstall_application
    ;;
  *)
    echo "Usage:"
    echo "  sudo ./install.sh"
    echo "  sudo ./install.sh install"
    echo "  sudo ./install.sh uninstall"
    exit 1
    ;;
esac
