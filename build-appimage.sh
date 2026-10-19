#!/bin/bash
# =============================================================================
# build-appimage.sh — Empaqueta OpenArgentOS USB Studio como AppImage
#
# Uso:  ./build-appimage.sh
#
# AppImage "thin": usa GTK4 / libadwaita / Python del sistema.
# =============================================================================
set -euo pipefail

APP_NAME="OpenArgentOS-USB-Studio"
APP_BIN="openargentos-usb-studio"
APP_ID="org.openargentos.usbstudio"
VERSION="1.1.1"
ARCH="$(uname -m)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PY="${SCRIPT_DIR}/openargentos-usb-studio.py"
BUILD_DIR="${SCRIPT_DIR}/build-appimage"
APPDIR="${BUILD_DIR}/${APP_NAME}.AppDir"

if [[ ! -f "$SRC_PY" ]]; then
  echo "Error: no se encuentra openargentos-usb-studio.py en $SCRIPT_DIR"
  exit 1
fi

echo "==> Limpiando build anterior..."
rm -rf "$BUILD_DIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$APPDIR/usr/share/metainfo"
mkdir -p "$APPDIR/usr/share/nemo/actions"

echo "==> Instalando aplicación en AppDir..."
install -m 755 "$SRC_PY" "$APPDIR/usr/bin/${APP_BIN}"
if ! head -1 "$APPDIR/usr/bin/${APP_BIN}" | grep -q '^#!'; then
  sed -i '1i#!/usr/bin/env python3' "$APPDIR/usr/bin/${APP_BIN}"
fi

# --- AppRun: parted está en /usr/sbin y no aparece con command -v ---
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
set +e
HERE="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"
export PATH="/usr/sbin:/sbin:/usr/bin:/bin:${HERE}/usr/bin:${PATH:-}"
export APPDIR="${HERE}"

show_error() {
  msg="$1"
  printf '%s\n' "$msg" >&2
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="OpenArgentOS USB Studio" --width=420 --text="$msg" 2>/dev/null
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical "OpenArgentOS USB Studio" "$msg"
  fi
}

# parted, mkfs.* y wipefs viven en /usr/sbin y no están en el PATH de un usuario normal
have() {
  command -v "$1" >/dev/null 2>&1 && return 0
  for d in /usr/sbin /sbin /usr/bin /bin; do
    if [[ -x "$d/$1" ]]; then
      return 0
    fi
  done
  return 1
}

missing=""
command -v python3 >/dev/null 2>&1 || missing="${missing}
• python3"
python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" 2>/dev/null \
  || missing="${missing}
• python3-gi + gir1.2-gtk-4.0"
python3 -c "import gi; gi.require_version('Adw','1'); from gi.repository import Adw" 2>/dev/null \
  || missing="${missing}
• gir1.2-adw-1"
have pkexec || missing="${missing}
• pkexec"
have parted || missing="${missing}
• parted"

if [[ -n "$missing" ]]; then
  show_error "Faltan dependencias del sistema:${missing}

Instalá con:
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 parted dosfstools util-linux pkexec"
  exit 1
fi

BIN="${HERE}/usr/bin/openargentos-usb-studio"
if [[ ! -x "$BIN" ]]; then
  show_error "No se encuentra el ejecutable:
$BIN"
  exit 1
fi

exec python3 "$BIN" "$@"
EOF
chmod 755 "$APPDIR/AppRun"

cat > "$APPDIR/${APP_ID}.desktop" << EOF
[Desktop Entry]
Name=OpenArgentOS USB Studio
Comment=Grabar ISO, formatear y reparar pendrives USB
Exec=AppRun %F
Icon=${APP_ID}
Terminal=false
Type=Application
Categories=System;Utility;
Keywords=USB;ISO;pendrive;format;dd;checksum;
MimeType=application/x-cd-image;application/x-iso9660-image;application/vnd.efi.iso;
StartupNotify=true
StartupWMClass=${APP_ID}
X-AppImage-Version=${VERSION}
EOF
cp "$APPDIR/${APP_ID}.desktop" "$APPDIR/usr/share/applications/"

cat > "$APPDIR/usr/share/nemo/actions/${APP_ID}.nemo_action" << EOF
[Nemo Action]
Active=true
Name=Grabar con USB Studio
Comment=Abrir esta imagen ISO en OpenArgentOS USB Studio
Exec=${APP_BIN} %F
Icon-Name=drive-removable-media-usb
Selection=s
Extensions=iso;ISO;
Quote=double
EOF

cat > "$APPDIR/${APP_ID}.svg" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect width="256" height="256" rx="48" fill="#1c71d8"/>
  <g fill="#ffffff" transform="translate(48,32)">
    <rect x="40" y="48" width="80" height="140" rx="12"/>
    <rect x="58" y="20" width="44" height="36" rx="4"/>
    <rect x="66" y="8" width="8" height="16" rx="2"/>
    <rect x="86" y="8" width="8" height="16" rx="2"/>
    <circle cx="80" cy="100" r="8" fill="#8ff0a4"/>
    <rect x="56" y="130" width="48" height="8" rx="2" fill="#1c71d8"/>
    <rect x="56" y="150" width="48" height="8" rx="2" fill="#1c71d8"/>
  </g>
</svg>
EOF
cp "$APPDIR/${APP_ID}.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
cp "$APPDIR/${APP_ID}.svg" "$APPDIR/.DirIcon"

cat > "$APPDIR/usr/share/metainfo/${APP_ID}.metainfo.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>${APP_ID}</id>
  <name>OpenArgentOS USB Studio</name>
  <summary>Grabar ISO, formatear y reparar pendrives USB</summary>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <description>
    <p>Herramienta gráfica para grabar ISO, formatear y reparar pendrives USB.</p>
  </description>
  <launchable type="desktop-id">${APP_ID}.desktop</launchable>
  <categories>
    <category>System</category>
    <category>Utility</category>
  </categories>
</component>
EOF

echo "==> Preparando appimagetool..."
TOOL_DIR="${BUILD_DIR}/tools"
mkdir -p "$TOOL_DIR"
APPIMAGETOOL="${TOOL_DIR}/appimagetool"

if command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL="$(command -v appimagetool)"
  echo "    Usando appimagetool del sistema: $APPIMAGETOOL"
else
  case "$ARCH" in
    x86_64)  AI_ARCH="x86_64" ;;
    aarch64|arm64) AI_ARCH="aarch64" ;;
    armv7l)  AI_ARCH="armhf" ;;
    i686|i386) AI_ARCH="i686" ;;
    *)
      echo "Arquitectura no soportada: $ARCH"
      exit 1
      ;;
  esac
  URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${AI_ARCH}.AppImage"
  echo "    Descargando appimagetool (${AI_ARCH})..."
  if command -v wget >/dev/null 2>&1; then
    wget -q --show-progress -O "$APPIMAGETOOL" "$URL"
  elif command -v curl >/dev/null 2>&1; then
    curl -L --progress-bar -o "$APPIMAGETOOL" "$URL"
  else
    echo "Error: necesitás wget o curl"
    exit 1
  fi
  chmod +x "$APPIMAGETOOL"
fi

echo "==> Generando AppImage..."
OUT_NAME="${APP_NAME}-${VERSION}-${ARCH}.AppImage"
OUT_PATH="${SCRIPT_DIR}/${OUT_NAME}"
export ARCH

cd "$BUILD_DIR"
set +e
"$APPIMAGETOOL" "$APPDIR" "$OUT_PATH"
rc=$?
if [[ $rc -ne 0 ]]; then
  echo "    Reintentando con --appimage-extract-and-run..."
  "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$OUT_PATH"
  rc=$?
fi
set -e

if [[ $rc -ne 0 ]] || [[ ! -f "$OUT_PATH" ]]; then
  echo "Error: no se pudo generar el AppImage"
  exit 1
fi

chmod +x "$OUT_PATH"

echo ""
echo "✓ AppImage generado: $OUT_PATH"
echo ""
echo "  Probar:"
echo "    ./$(basename "$OUT_PATH")"
echo ""
