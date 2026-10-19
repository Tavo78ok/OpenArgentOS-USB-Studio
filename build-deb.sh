#!/bin/bash
# =============================================================================
# build-deb.sh — Empaqueta OpenArgentOS USB Studio como .deb
# Uso:  ./build-deb.sh
# Requiere: dpkg-deb, fakeroot (opcional pero recomendado)
# =============================================================================
set -euo pipefail

APP_NAME="openargentos-usb-studio"
APP_ID="org.openargentos.usbstudio"
VERSION="1.1.0"
ARCH="all"
MAINTAINER="OpenArgentOS <soporte@openargentos.org>"
DESCRIPTION="Herramienta gráfica para grabar ISO, formatear y reparar pendrives USB"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PY="${SCRIPT_DIR}/openargentos-usb-studio.py"
BUILD_DIR="${SCRIPT_DIR}/build-deb"
PKG_ROOT="${BUILD_DIR}/${APP_NAME}_${VERSION}_${ARCH}"

# --- Comprobaciones ---
if [[ ! -f "$SRC_PY" ]]; then
  echo "Error: no se encuentra openargentos-usb-studio.py en $SCRIPT_DIR"
  exit 1
fi

command -v dpkg-deb >/dev/null 2>&1 || {
  echo "Error: falta dpkg-deb. Instalá con: sudo apt install dpkg-dev"
  exit 1
}

echo "==> Limpiando build anterior..."
rm -rf "$BUILD_DIR"
mkdir -p "$PKG_ROOT"

# --- Estructura del paquete ---
echo "==> Creando estructura del paquete..."
mkdir -p "$PKG_ROOT/DEBIAN"
mkdir -p "$PKG_ROOT/usr/bin"
mkdir -p "$PKG_ROOT/usr/share/applications"
mkdir -p "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$PKG_ROOT/usr/share/metainfo"
mkdir -p "$PKG_ROOT/usr/share/doc/${APP_NAME}"

# --- Binario / script ---
echo "==> Instalando aplicación..."
install -m 755 "$SRC_PY" "$PKG_ROOT/usr/bin/${APP_NAME}"

# Asegurar shebang
if ! head -1 "$PKG_ROOT/usr/bin/${APP_NAME}" | grep -q '^#!'; then
  sed -i '1i#!/usr/bin/env python3' "$PKG_ROOT/usr/bin/${APP_NAME}"
fi

# --- Desktop entry (también asocia MIME de ISO → Abrir con) ---
cat > "$PKG_ROOT/usr/share/applications/${APP_ID}.desktop" << EOF
[Desktop Entry]
Name=OpenArgentOS USB Studio
Comment=${DESCRIPTION}
Exec=${APP_NAME} %F
Icon=drive-removable-media-usb
Terminal=false
Type=Application
Categories=System;Utility;
Keywords=USB;ISO;pendrive;format;dd;checksum;
MimeType=application/x-cd-image;application/x-iso9660-image;application/vnd.efi.iso;
StartupNotify=true
StartupWMClass=${APP_ID}
EOF

# --- Acción de Nemo (Cinnamon): clic derecho sobre ISO ---
mkdir -p "$PKG_ROOT/usr/share/nemo/actions"
cat > "$PKG_ROOT/usr/share/nemo/actions/${APP_ID}.nemo_action" << EOF
[Nemo Action]
Active=true
Name=Grabar con USB Studio
Comment=Abrir esta imagen ISO en OpenArgentOS USB Studio
Exec=${APP_NAME} %F
Icon-Name=drive-removable-media-usb
Selection=s
Extensions=iso;ISO;
Quote=double
EOF

# --- Acción de Nautilus (GNOME), por si se usa en el futuro ---
mkdir -p "$PKG_ROOT/usr/share/file-manager/actions"
cat > "$PKG_ROOT/usr/share/file-manager/actions/${APP_ID}.desktop" << EOF
[Desktop Entry]
Type=Action
Name=Grabar con USB Studio
Icon=drive-removable-media-usb
TargetLocation=true
TargetToolbar=true
MimeTypes=application/x-cd-image;application/x-iso9660-image;
Profiles=profile-zero;

[X-Action-Profile profile-zero]
Name=Grabar con USB Studio
Exec=${APP_NAME} %F
EOF

# --- AppStream metainfo (opcional, mejora integración en centros de software) ---
cat > "$PKG_ROOT/usr/share/metainfo/${APP_ID}.metainfo.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>${APP_ID}</id>
  <name>OpenArgentOS USB Studio</name>
  <summary>${DESCRIPTION}</summary>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <description>
    <p>
      OpenArgentOS USB Studio permite grabar imágenes ISO en pendrives,
      formatear unidades USB (FAT32, NTFS, exFAT, EXT4) con tabla MBR o GPT,
      y reparar pendrives con firmas corruptas o tablas dañadas.
      Incluye verificación de checksum (SHA256, SHA1, MD5).
    </p>
  </description>
  <launchable type="desktop-id">${APP_ID}.desktop</launchable>
  <categories>
    <category>System</category>
    <category>Utility</category>
  </categories>
</component>
EOF

# --- Documentación mínima ---
cat > "$PKG_ROOT/usr/share/doc/${APP_NAME}/copyright" << EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: OpenArgentOS USB Studio
Source: https://openargentos.org

Files: *
Copyright: OpenArgentOS contributors
License: GPL-3.0-or-later
EOF

cat > "$PKG_ROOT/usr/share/doc/${APP_NAME}/changelog" << EOF
${APP_NAME} (${VERSION}) unstable; urgency=medium

  * Empaquetado inicial.

 -- ${MAINTAINER}  $(date -R)
EOF
gzip -9n -f "$PKG_ROOT/usr/share/doc/${APP_NAME}/changelog"

# --- Control file ---
# Calcular tamaño instalado aproximado (kB)
INSTALLED_SIZE=$(du -sk "$PKG_ROOT/usr" | cut -f1)

cat > "$PKG_ROOT/DEBIAN/control" << EOF
Package: ${APP_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE}
Maintainer: ${MAINTAINER}
Depends: python3 (>= 3.10),
         python3-gi,
         gir1.2-gtk-4.0,
         gir1.2-adw-1,
         parted,
         dosfstools,
         util-linux,
         pkexec | polkitd | policykit-1
Recommends: ntfs-3g, exfatprogs, e2fsprogs
Description: ${DESCRIPTION}
 Herramienta gráfica (GTK4 + libadwaita) para:
  - Grabar imágenes ISO en pendrives con progreso y checksum
  - Formatear USB (FAT32, NTFS, exFAT, EXT4) con MBR o GPT
  - Reparar pendrives con firmas o tablas corruptas
EOF

# --- postinst / postrm (actualizar caché de iconos y desktop) ---
cat > "$PKG_ROOT/DEBIAN/postinst" << 'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database /usr/share/mime >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
fi
exit 0
EOF
chmod 755 "$PKG_ROOT/DEBIAN/postinst"

cat > "$PKG_ROOT/DEBIAN/postrm" << 'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
exit 0
EOF
chmod 755 "$PKG_ROOT/DEBIAN/postrm"

# --- Construir .deb ---
echo "==> Construyendo paquete .deb..."
OUT_DEB="${SCRIPT_DIR}/${APP_NAME}_${VERSION}_${ARCH}.deb"

if command -v fakeroot >/dev/null 2>&1; then
  fakeroot dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUT_DEB"
else
  dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUT_DEB"
fi

echo ""
echo "✓ Paquete generado: $OUT_DEB"
echo ""
echo "  Instalar con:"
echo "    sudo apt install ./$(basename "$OUT_DEB")"
echo "  o:"
echo "    sudo dpkg -i $(basename "$OUT_DEB")"
echo "    sudo apt-get install -f   # si faltan dependencias"
echo ""
