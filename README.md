# OpenArgentOS USB Studio

Herramienta gráfica del ecosistema **OpenArgentOS** para preparar, grabar y recuperar pendrives USB.

GTK 4 + libadwaita. Pensada para el escritorio de OpenArgentOS (Cinnamon / Nemo), y también usable en Debian, Ubuntu y derivados.

Versión actual: **1.1.1**

<img width="1440" height="900" alt="Captura de pantalla de 2026-10-19 16-48-57" src="https://github.com/user-attachments/assets/bae28a39-a6fe-478d-8bb0-74e3fbcc2ac5" />

## Qué hace

- **Grabar ISO.** Escribe una imagen en el pendrive con `dd`, barra de progreso real y una sola solicitud de contraseña.
- **Checksum.** SHA256, SHA1 o MD5 antes de grabar. Si el hash no coincide, no escribe. Opción de volver a leer el pendrive y comparar.
- **Formatear.** FAT32, NTFS, exFAT o EXT4, con tabla **MBR** o **GPT**.
- **Reparar.** Limpia firmas corruptas (`wipefs`), recrea la tabla de particiones y deja el pendrive en FAT32 (`RECOVERED`).
- **Solo USB.** Antes de escribir comprueba que el destino siga siendo un disco extraíble o con transporte USB.
- **Menú contextual.** Clic derecho sobre un `.iso` en Nemo → **Grabar con USB Studio**. La imagen queda cargada en la pestaña de grabación.

Todas las operaciones destructivas piden confirmación. Borrar, formatear o grabar una ISO elimina el contenido del pendrive.

## Capturas

Pendiente de agregar capturas del escritorio OpenArgentOS:

- `docs/screenshot-grabar.png`
- `docs/screenshot-formatear.png`
- `docs/screenshot-reparar.png`

## Requisitos

Debian 13 / OpenArgentOS (y equivalentes):

```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  parted dosfstools util-linux pkexec \
  ntfs-3g exfatprogs e2fsprogs
```

| Paquete | Para qué |
|---|---|
| `python3`, `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` | Interfaz |
| `parted`, `dosfstools`, `util-linux` | Particiones, FAT32, `wipefs`, `lsblk` |
| `pkexec` | Privilegios (en Debian 13 reemplaza a `policykit-1`) |
| `ntfs-3g`, `exfatprogs`, `e2fsprogs` | NTFS, exFAT y EXT4 |

`parted` y las herramientas `mkfs.*` están en `/usr/sbin`. La aplicación las busca por ruta absoluta; no hace falta ser root para abrirla.

## Instalar el paquete .deb

Recomendado en OpenArgentOS. Integra el lanzador y el menú contextual de Nemo.

```bash
sudo apt install ./openargentos-usb-studio_1.1.0_all.deb
```

Si faltan dependencias:

```bash
sudo apt-get install -f
```

Después de instalar:

- Menú de aplicaciones → **OpenArgentOS USB Studio**
- Clic derecho sobre un `.iso` → **Grabar con USB Studio** o **Abrir con**

Si Nemo no muestra la acción de inmediato:

```bash
update-desktop-database /usr/share/applications
nemo -q
```

## AppImage

Portable. Usa GTK 4, libadwaita y Python del sistema (no los empaqueta).

```bash
chmod +x OpenArgentOS-USB-Studio-1.1.1-x86_64.AppImage
./OpenArgentOS-USB-Studio-1.1.1-x86_64.AppImage
```

También acepta una ISO:

```bash
./OpenArgentOS-USB-Studio-1.1.1-x86_64.AppImage /ruta/imagen.iso
```

El AppImage no instala solo el ítem de Nemo. Para el menú contextual del escritorio, usá el `.deb`.

## Uso rápido

1. Conectá el pendrive y pulsá el botón de recarga si no aparece.
2. Elegí la unidad. El programa solo lista discos extraíbles o USB.
3. **Grabar ISO:** elegí el archivo, pegá el hash oficial y pulsá **Calcular y verificar**. Después, **Grabar ISO en Pendrive**.
4. **Formatear** o **Reparar:** elegí opciones y confirmá. Una sola contraseña por operación.

### Checksum

Dejá el campo de hash vacío para solo calcularlo (se copia al portapapeles). Si pegás el hash publicado por la distro:

- coincidencia: se puede grabar
- no coincide: la grabación se cancela

**Verificar después de grabar** lee del pendrive exactamente el tamaño de la ISO y compara el hash. Es más lento y más seguro.

## Compilar los paquetes

Desde la raíz del repositorio, con `openargentos-usb-studio.py` al lado de los scripts:

```bash
chmod +x build-deb.sh build-appimage.sh openargentos-usb-studio.py

./build-deb.sh
# → openargentos-usb-studio_1.1.0_all.deb

./build-appimage.sh
# → OpenArgentOS-USB-Studio-1.1.1-x86_64.AppImage
```

`build-appimage.sh` descarga `appimagetool` si no está instalado (hace falta `wget` o `curl`).

Ejecutar sin empaquetar:

```bash
python3 openargentos-usb-studio.py
python3 openargentos-usb-studio.py ~/Descargas/imagen.iso
```

## Estructura

```
openargentos-usb-studio.py          Aplicación
build-deb.sh                        Paquete Debian
build-appimage.sh                   AppImage
org.openargentos.usbstudio.desktop  Lanzador y asociación MIME
org.openargentos.usbstudio.nemo_action
```

Identificador: `org.openargentos.usbstudio`.

## Seguridad

La herramienta escribe dispositivos de bloque. Confirmá siempre el destino (`/dev/sdX`) antes de continuar. No opera sobre discos internos que no sean extraíbles ni USB.

Las tareas privilegiadas se agrupan en un script temporal y se ejecutan con **un solo** `pkexec` por operación.

## Licencia

GPL-3.0-or-later.

Parte del ecosistema [OpenArgentOS](https://openargentos.org).
