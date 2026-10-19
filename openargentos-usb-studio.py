#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio
import json
import subprocess
import threading
import os
import shlex
import re
import time
import hashlib
import shutil
import tempfile


# Rutas absolutas: pkexec usa un PATH restringido
def _find_tool(*candidates):
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    for c in candidates:
        name = os.path.basename(c) if c else None
        if name:
            found = shutil.which(name)
            if found:
                return found
    return candidates[0] if candidates else None


PARTED = _find_tool("/usr/sbin/parted", "/sbin/parted", "parted")
WIPEFS = _find_tool("/usr/sbin/wipefs", "/sbin/wipefs", "wipefs")
MKFS_VFAT = _find_tool("/usr/sbin/mkfs.vfat", "/sbin/mkfs.vfat", "mkfs.vfat")
MKFS_NTFS = _find_tool("/usr/sbin/mkfs.ntfs", "/sbin/mkfs.ntfs", "mkfs.ntfs")
MKFS_EXFAT = _find_tool("/usr/sbin/mkfs.exfat", "/sbin/mkfs.exfat", "mkfs.exfat")
MKFS_EXT4 = _find_tool("/usr/sbin/mkfs.ext4", "/sbin/mkfs.ext4", "mkfs.ext4")
UMOUNT = _find_tool("/usr/bin/umount", "/bin/umount", "umount")
DD = _find_tool("/usr/bin/dd", "/bin/dd", "dd")
LSBLK = _find_tool("/usr/bin/lsblk", "/bin/lsblk", "lsblk")
PKEXEC = _find_tool("/usr/bin/pkexec", "pkexec")
BASH = _find_tool("/usr/bin/bash", "/bin/bash", "bash")


class USBStudioWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_default_size(720, 700)
        self.set_title("OpenArgentOS USB Studio")
        # Icono de la ventana / aplicación
        self.set_icon_name("drive-removable-media-usb")

        self.selected_iso_path = None
        self._iso_checksum_ok = None

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        self.header_bar = Adw.HeaderBar()
        main_box.append(self.header_bar)

        btn_refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        btn_refresh.set_tooltip_text("Recargar dispositivos USB")
        btn_refresh.connect("clicked", lambda x: self.load_usb_devices())
        self.header_bar.pack_start(btn_refresh)

        self.stack = Adw.ViewStack()

        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        self.header_bar.set_title_widget(switcher)

        self.device_model = Gtk.StringList()
        self.device_data_map = {}

        dev_card = Adw.PreferencesGroup()
        dev_card.set_margin_start(16)
        dev_card.set_margin_end(16)
        dev_card.set_margin_top(12)
        dev_card.set_margin_bottom(8)

        self.combo_row = Adw.ComboRow(
            title="Dispositivo USB de Destino",
            subtitle="Seleccioná la unidad sobre la cual operar"
        )
        self.combo_row.set_model(self.device_model)
        dev_card.add(self.combo_row)
        main_box.append(dev_card)

        self.status_label = Gtk.Label(label="Listo.")
        self.status_label.set_margin_bottom(8)
        self.status_label.set_wrap(True)
        self.status_label.set_xalign(0)
        self.status_label.set_margin_start(16)
        self.status_label.set_margin_end(16)

        self.build_iso_page()
        self.build_format_page()
        self.build_repair_page()

        main_box.append(self.stack)
        main_box.append(self.status_label)

        self.load_usb_devices()
        self._check_dependencies()

    def set_iso_path(self, path):
        """Preselecciona una ISO (menú contextual / argumentos de línea de comandos)."""
        if not path:
            return
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            self.update_status(f"No se encontró el archivo: {path}")
            return
        if not path.lower().endswith(".iso"):
            self.update_status(f"El archivo no parece una ISO: {path}")
            return
        self.selected_iso_path = path
        self.file_row.set_subtitle(path)
        self._iso_checksum_ok = None
        self.checksum_result_row.set_subtitle("Sin verificar")
        self.checksum_result_row.remove_css_class("success")
        self.checksum_result_row.remove_css_class("error")
        # Ir a la pestaña de grabar ISO
        self.stack.set_visible_child_name("iso")
        self.update_status(f"ISO cargada: {os.path.basename(path)}")

    def _check_dependencies(self):
        missing = []
        for name, path in [
            ("parted", PARTED),
            ("wipefs", WIPEFS),
            ("mkfs.vfat", MKFS_VFAT),
            ("pkexec", PKEXEC),
            ("lsblk", LSBLK),
            ("dd", DD),
        ]:
            if not path or not os.path.isfile(path):
                missing.append(name)
        if missing:
            self.update_status(
                "Faltan herramientas: " + ", ".join(missing)
                + ". Instalá con: sudo apt install parted dosfstools "
                "ntfs-3g exfatprogs e2fsprogs util-linux pkexec"
            )

    def load_usb_devices(self):
        self.device_model.splice(0, self.device_model.get_n_items(), [])
        self.device_data_map.clear()

        try:
            res = subprocess.run(
                [LSBLK or "lsblk", "-J", "-b", "-o", "NAME,SIZE,RM,TRAN,TYPE,MODEL,LABEL"],
                capture_output=True, text=True, check=True
            )
            data = json.loads(res.stdout)
            devices = data.get("blockdevices", [])

            count = 0
            for dev in devices:
                is_removable = bool(dev.get("rm"))
                is_usb = (dev.get("tran") or "").lower() == "usb"
                if dev.get("type") == "disk" and (is_removable or is_usb):
                    name = dev.get("name")
                    if not name:
                        continue
                    dev_path = f"/dev/{name}"
                    size_bytes = int(dev.get("size") or 0)
                    gb_size = round(size_bytes / (1024 ** 3), 1)
                    model_name = (dev.get("model") or "USB Drive").strip()
                    display_text = f"{model_name} ({dev_path} - {gb_size} GB)"

                    self.device_model.append(display_text)
                    self.device_data_map[count] = dev_path
                    count += 1

            if count == 0:
                self.device_model.append("No se detectaron pendrives extraíbles")
                self.update_status("No hay dispositivos USB extraíbles conectados.")
            else:
                self.update_status("Dispositivos USB detectados.")
                self.combo_row.set_selected(0)
        except Exception as e:
            self.device_model.append("Error al escanear unidades")
            self.update_status(f"Error: {e}")

    def get_selected_device(self):
        idx = self.combo_row.get_selected()
        return self.device_data_map.get(idx)

    def update_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def _is_still_usb(self, dev_path):
        if not dev_path or not os.path.exists(dev_path):
            return False
        try:
            name = os.path.basename(dev_path)
            res = subprocess.run(
                [LSBLK or "lsblk", "-J", "-b", "-o", "NAME,RM,TRAN,TYPE"],
                capture_output=True, text=True, check=True
            )
            data = json.loads(res.stdout)
            for dev in data.get("blockdevices", []):
                if dev.get("name") == name and dev.get("type") == "disk":
                    is_removable = bool(dev.get("rm"))
                    is_usb = (dev.get("tran") or "").lower() == "usb"
                    return is_removable or is_usb
            return False
        except Exception:
            return False

    def _confirm_destructive(self, title, body, callback):
        dialog = Adw.AlertDialog(heading=title, body=body)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("ok", "Continuar")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(dlg, response):
            if response == "ok":
                callback()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _wait_for_partition(self, part_path, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(part_path):
                return True
            time.sleep(0.2)
        return os.path.exists(part_path)

    def _run_privileged_script(self, script: str, capture=True):
        """
        Ejecuta un script bash completo con UN solo pkexec.
        Así el usuario solo introduce la contraseña una vez por operación.
        """
        # Escribimos el script en un archivo temporal legible por root
        fd, path = tempfile.mkstemp(prefix="usbstudio-", suffix=".sh")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("#!/bin/bash\nset -e\n")
                f.write(script)
                if not script.endswith("\n"):
                    f.write("\n")
            os.chmod(path, 0o700)

            cmd = [PKEXEC or "pkexec", BASH or "bash", path]
            if capture:
                return subprocess.run(cmd, capture_output=True, text=True)
            else:
                # Para dd con progreso: no capturamos, devolvemos el Popen
                return subprocess.Popen(
                    cmd, stderr=subprocess.PIPE, text=True, bufsize=1
                )
        finally:
            # No borramos todavía si es Popen; el caller limpia
            # Para run síncrono sí borramos después
            pass

    def _cleanup_script(self, path):
        try:
            os.unlink(path)
        except Exception:
            pass

    def _unmount_script_lines(self, dev_path):
        """Líneas de script para desmontar dispositivo y particiones."""
        umount = UMOUNT or "umount"
        lines = [
            f"# Desmontar {dev_path}",
            f"for p in $(lsblk -ln -o NAME {shlex.quote(dev_path)} 2>/dev/null); do",
            f"  {umount} \"/dev/$p\" 2>/dev/null || true",
            f"done",
            f"{umount} {shlex.quote(dev_path)}* 2>/dev/null || true",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Checksum
    # ------------------------------------------------------------------
    def _get_hash_algo(self):
        idx = self.hash_combo.get_selected()
        if idx == 1:
            return "sha1", hashlib.sha1
        if idx == 2:
            return "md5", hashlib.md5
        return "sha256", hashlib.sha256

    def _compute_file_hash(self, path, hash_factory, progress_cb=None, size=None):
        h = hash_factory()
        chunk = 1024 * 1024 * 4
        read = 0
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                h.update(data)
                read += len(data)
                if progress_cb and size and size > 0:
                    progress_cb(min(read / size, 1.0))
        return h.hexdigest()

    def _compute_device_hash(self, dev_path, hash_factory, byte_count, progress_cb=None):
        h = hash_factory()
        chunk = 1024 * 1024 * 4
        read = 0
        with open(dev_path, "rb") as f:
            while read < byte_count:
                to_read = min(chunk, byte_count - read)
                data = f.read(to_read)
                if not data:
                    break
                h.update(data)
                read += len(data)
                if progress_cb and byte_count > 0:
                    progress_cb(min(read / byte_count, 1.0))
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Vista 1: Grabar ISO
    # ------------------------------------------------------------------
    def build_iso_page(self):
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page_box.set_margin_start(16)
        page_box.set_margin_end(16)
        page_box.set_margin_top(8)

        group = Adw.PreferencesGroup(title="Grabación de Imagen ISO")

        self.file_row = Adw.ActionRow(
            title="Imagen de Sistema",
            subtitle="Ningún archivo .iso seleccionado"
        )
        btn_select_file = Gtk.Button(label="Examinar...")
        btn_select_file.set_valign(Gtk.Align.CENTER)
        btn_select_file.connect("clicked", self.on_select_iso_clicked)
        self.file_row.add_suffix(btn_select_file)
        group.add(self.file_row)
        page_box.append(group)

        checksum_group = Adw.PreferencesGroup(
            title="Verificación de integridad (checksum)",
            description="Pegá el hash oficial de la ISO para comprobarla antes de grabar."
        )

        algo_model = Gtk.StringList.new(["SHA256", "SHA1", "MD5"])
        self.hash_combo = Adw.ComboRow(title="Algoritmo", model=algo_model)
        checksum_group.add(self.hash_combo)

        self.checksum_entry = Adw.EntryRow(title="Hash esperado")
        self.checksum_entry.set_text("")
        checksum_group.add(self.checksum_entry)

        self.checksum_result_row = Adw.ActionRow(
            title="Resultado",
            subtitle="Sin verificar"
        )
        btn_verify = Gtk.Button(label="Calcular y verificar")
        btn_verify.set_valign(Gtk.Align.CENTER)
        btn_verify.add_css_class("suggested-action")
        btn_verify.connect("clicked", self.on_verify_checksum_clicked)
        self.checksum_result_row.add_suffix(btn_verify)
        checksum_group.add(self.checksum_result_row)

        self.verify_after_switch = Adw.SwitchRow(
            title="Verificar después de grabar",
            subtitle="Lee el pendrive y compara el hash (más lento, más seguro)"
        )
        self.verify_after_switch.set_active(False)
        checksum_group.add(self.verify_after_switch)

        page_box.append(checksum_group)

        self.iso_progress = Gtk.ProgressBar(show_text=True)
        self.iso_progress.set_fraction(0.0)
        self.iso_progress.set_text("0 %")
        page_box.append(self.iso_progress)

        self.btn_burn = Gtk.Button(label="Grabar ISO en Pendrive")
        self.btn_burn.add_css_class("suggested-action")
        self.btn_burn.add_css_class("pill")
        self.btn_burn.connect("clicked", self.on_start_burn)
        page_box.append(self.btn_burn)

        page = self.stack.add_titled(page_box, "iso", "Grabar ISO")
        page.set_icon_name("media-flash-symbolic")

    def on_select_iso_clicked(self, button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Seleccionar imagen ISO")

        filter_iso = Gtk.FileFilter()
        filter_iso.set_name("Archivos ISO (*.iso)")
        filter_iso.add_pattern("*.iso")
        filter_iso.add_pattern("*.ISO")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_iso)
        dialog.set_filters(filters)
        dialog.set_default_filter(filter_iso)

        dialog.open(self, None, self.on_iso_selected_callback)

    def on_iso_selected_callback(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self.selected_iso_path = file.get_path()
                self.file_row.set_subtitle(
                    self.selected_iso_path or "Ningún archivo .iso seleccionado"
                )
                self._iso_checksum_ok = None
                self.checksum_result_row.set_subtitle("Sin verificar")
                self.checksum_result_row.remove_css_class("success")
                self.checksum_result_row.remove_css_class("error")
        except GLib.Error:
            pass
        except Exception:
            pass

    def on_verify_checksum_clicked(self, button):
        if not self.selected_iso_path or not os.path.isfile(self.selected_iso_path):
            self.update_status("Error: Seleccioná un archivo .iso primero.")
            return

        expected = (self.checksum_entry.get_text() or "").strip().lower()
        algo_name, hash_factory = self._get_hash_algo()
        iso_size = os.path.getsize(self.selected_iso_path)

        button.set_sensitive(False)
        self.checksum_result_row.set_subtitle(f"Calculando {algo_name.upper()}...")
        self.update_status(f"Calculando {algo_name.upper()} de la ISO...")

        def progress_cb(frac):
            GLib.idle_add(self.iso_progress.set_fraction, frac)
            GLib.idle_add(self.iso_progress.set_text, f"Checksum {int(frac * 100)} %")

        def worker():
            try:
                digest = self._compute_file_hash(
                    self.selected_iso_path, hash_factory, progress_cb, iso_size
                ).lower()

                def update_ui():
                    button.set_sensitive(True)
                    self.iso_progress.set_fraction(1.0)
                    self.iso_progress.set_text("100 %")

                    if not expected:
                        self._iso_checksum_ok = None
                        self.checksum_result_row.set_subtitle(digest)
                        self.checksum_result_row.remove_css_class("success")
                        self.checksum_result_row.remove_css_class("error")
                        try:
                            display = self.get_display()
                            if display:
                                display.get_clipboard().set(digest)
                                self.update_status(
                                    f"{algo_name.upper()}: {digest}  (copiado al portapapeles)"
                                )
                            else:
                                self.update_status(f"{algo_name.upper()}: {digest}")
                        except Exception:
                            self.update_status(f"{algo_name.upper()}: {digest}")
                        return

                    if digest == expected:
                        self._iso_checksum_ok = True
                        self.checksum_result_row.set_subtitle(f"✓ Coincide — {digest[:16]}…")
                        self.checksum_result_row.add_css_class("success")
                        self.checksum_result_row.remove_css_class("error")
                        self.update_status(f"Checksum {algo_name.upper()} correcto.")
                    else:
                        self._iso_checksum_ok = False
                        self.checksum_result_row.set_subtitle(
                            f"✗ No coincide — calculado: {digest[:16]}…"
                        )
                        self.checksum_result_row.add_css_class("error")
                        self.checksum_result_row.remove_css_class("success")
                        self.update_status(
                            f"Checksum {algo_name.upper()} INCORRECTO. La ISO puede estar corrupta."
                        )

                GLib.idle_add(update_ui)
            except Exception as e:
                def on_err():
                    button.set_sensitive(True)
                    self.checksum_result_row.set_subtitle(f"Error: {e}")
                    self.update_status(f"Error al calcular checksum: {e}")
                GLib.idle_add(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def on_start_burn(self, button):
        dev = self.get_selected_device()
        if not dev:
            self.update_status("Error: Por favor seleccioná un dispositivo USB válido.")
            return
        if not self.selected_iso_path or not os.path.isfile(self.selected_iso_path):
            self.update_status("Error: Seleccioná un archivo .iso primero.")
            return

        if not self._is_still_usb(dev):
            self.update_status("Error: El dispositivo ya no es un USB extraíble o fue desconectado.")
            return

        expected = (self.checksum_entry.get_text() or "").strip()
        if expected and self._iso_checksum_ok is False:
            self.update_status(
                "El checksum de la ISO no coincide. No se grabará. "
                "Verificá el hash o descargá de nuevo la imagen."
            )
            return

        iso_name = os.path.basename(self.selected_iso_path)
        iso_size = os.path.getsize(self.selected_iso_path)
        iso_gb = round(iso_size / (1024 ** 3), 2)
        verify_after = self.verify_after_switch.get_active()
        algo_name, hash_factory = self._get_hash_algo()

        def do_burn():
            self.btn_burn.set_sensitive(False)
            GLib.idle_add(self.iso_progress.set_fraction, 0.0)
            GLib.idle_add(self.iso_progress.set_text, "0 %")
            self.update_status(f"Escribiendo {iso_name} ({iso_gb} GB) en {dev}...")
            threading.Thread(
                target=self._run_burn_task,
                args=(self.selected_iso_path, dev, iso_size, verify_after,
                      algo_name, hash_factory, expected),
                daemon=True
            ).start()

        warn_checksum = ""
        if expected and self._iso_checksum_ok is None:
            warn_checksum = (
                "\n\nNota: hay un hash esperado pero aún no se verificó. "
                "Se calculará antes de grabar."
            )
        elif expected and self._iso_checksum_ok is True:
            warn_checksum = "\n\nChecksum de la ISO: correcto ✓"

        self._confirm_destructive(
            "Confirmar grabación de ISO",
            f"Se va a escribir «{iso_name}» ({iso_gb} GB) en {dev}.\n"
            "TODO el contenido del pendrive se perderá."
            + warn_checksum
            + ("\n\nDespués se verificará el hash del pendrive." if verify_after else "")
            + "\n\n¿Deseás continuar?",
            do_burn
        )

    def _run_burn_task(self, iso_path, dev_path, iso_size, verify_after,
                       algo_name, hash_factory, expected):
        script_path = None
        try:
            if not self._is_still_usb(dev_path):
                self.update_status("Error: El dispositivo ya no es un USB extraíble.")
                return

            if expected and self._iso_checksum_ok is not True:
                self.update_status(f"Verificando {algo_name.upper()} de la ISO antes de grabar...")

                def prog(f):
                    GLib.idle_add(self.iso_progress.set_fraction, f * 0.3)
                    GLib.idle_add(self.iso_progress.set_text, f"Checksum {int(f * 100)} %")

                digest = self._compute_file_hash(iso_path, hash_factory, prog, iso_size).lower()
                if digest != expected.strip().lower():
                    self.update_status(
                        f"Checksum {algo_name.upper()} INCORRECTO. Grabación cancelada."
                    )
                    GLib.idle_add(self.iso_progress.set_fraction, 0.0)
                    GLib.idle_add(self.iso_progress.set_text, "Checksum falló")
                    return
                self.update_status(f"Checksum {algo_name.upper()} OK. Iniciando grabación...")

            # Un solo script = una sola contraseña (umount + dd)
            dd = DD or "dd"
            script = self._unmount_script_lines(dev_path) + "\n"
            script += (
                f"{shlex.quote(dd)} if={shlex.quote(iso_path)} of={shlex.quote(dev_path)} "
                f"bs=4M status=progress conv=fsync oflag=direct\n"
            )

            fd, script_path = tempfile.mkstemp(prefix="usbstudio-burn-", suffix=".sh")
            with os.fdopen(fd, "w") as f:
                f.write("#!/bin/bash\nset -e\n")
                f.write(script)
            os.chmod(script_path, 0o700)

            cmd = [PKEXEC or "pkexec", BASH or "bash", script_path]
            proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, text=True, bufsize=1
            )

            bytes_re = re.compile(r"^(\d+)\s+bytes")
            base = 0.3 if (expected and self._iso_checksum_ok is not True) else 0.0
            span = 0.95 - base if verify_after else 1.0 - base

            for raw_line in proc.stderr:
                line = raw_line.replace("\r", "\n").strip()
                if not line:
                    continue
                match = bytes_re.match(line)
                if match and iso_size > 0:
                    written = int(match.group(1))
                    fraction = base + min(written / iso_size, 1.0) * span
                    pct = int(min(fraction, 0.99) * 100)
                    GLib.idle_add(self.iso_progress.set_fraction, min(fraction, 0.99))
                    GLib.idle_add(self.iso_progress.set_text, f"{pct} %")
                    self.update_status(f"Escribiendo: {line}")
                elif "bytes" in line.lower() or "copied" in line.lower():
                    self.update_status(f"Escribiendo: {line}")

            proc.wait()
            if proc.returncode != 0:
                self.update_status("Ocurrió un error o se canceló la grabación.")
                GLib.idle_add(self.iso_progress.set_fraction, 0.0)
                GLib.idle_add(self.iso_progress.set_text, "Error")
                return

            self.update_status("¡Grabación completada!")
            GLib.idle_add(self.iso_progress.set_fraction, 0.95 if verify_after else 1.0)
            GLib.idle_add(self.iso_progress.set_text, "95 %" if verify_after else "100 %")

            if verify_after:
                self.update_status(
                    f"Verificando {algo_name.upper()} del pendrive "
                    f"(leyendo {round(iso_size / 1e9, 2)} GB)..."
                )

                def prog_dev(f):
                    GLib.idle_add(self.iso_progress.set_fraction, 0.95 + f * 0.05)
                    GLib.idle_add(self.iso_progress.set_text, f"Verificando {int(f * 100)} %")

                try:
                    device_digest = self._compute_device_hash(
                        dev_path, hash_factory, iso_size, prog_dev
                    ).lower()
                except PermissionError:
                    self.update_status("Solicitando permisos para verificar el pendrive...")
                    device_digest = self._hash_device_via_pkexec(
                        dev_path, algo_name, iso_size, prog_dev
                    )

                if expected:
                    iso_digest = expected.strip().lower()
                else:
                    self.update_status(f"Recalculando {algo_name.upper()} de la ISO para comparar...")
                    iso_digest = self._compute_file_hash(
                        iso_path, hash_factory, None, iso_size
                    ).lower()

                if device_digest == iso_digest:
                    self.update_status(
                        f"¡Verificación OK! {algo_name.upper()} del pendrive coincide."
                    )
                    GLib.idle_add(self.iso_progress.set_fraction, 1.0)
                    GLib.idle_add(self.iso_progress.set_text, "100 % ✓")
                else:
                    self.update_status(
                        f"¡ERROR de verificación! El hash del pendrive no coincide. "
                        f"ISO={iso_digest[:12]}…  USB={device_digest[:12]}…"
                    )
                    GLib.idle_add(self.iso_progress.set_text, "Verificación falló")
            else:
                GLib.idle_add(self.iso_progress.set_fraction, 1.0)
                GLib.idle_add(self.iso_progress.set_text, "100 %")

        except Exception as e:
            self.update_status(f"Error durante la grabación: {e}")
            GLib.idle_add(self.iso_progress.set_fraction, 0.0)
            GLib.idle_add(self.iso_progress.set_text, "Error")
        finally:
            if script_path:
                try:
                    os.unlink(script_path)
                except Exception:
                    pass
            GLib.idle_add(self.btn_burn.set_sensitive, True)
            GLib.idle_add(self.load_usb_devices)

    def _hash_device_via_pkexec(self, dev_path, algo_name, byte_count, progress_cb=None):
        tool_map = {
            "sha256": _find_tool("/usr/bin/sha256sum", "sha256sum"),
            "sha1": _find_tool("/usr/bin/sha1sum", "sha1sum"),
            "md5": _find_tool("/usr/bin/md5sum", "md5sum"),
        }
        tool = tool_map.get(algo_name) or "sha256sum"
        block = 4 * 1024 * 1024
        count = (byte_count + block - 1) // block
        dd = DD or "dd"
        script = (
            f"{shlex.quote(dd)} if={shlex.quote(dev_path)} bs=4M count={count} "
            f"status=none 2>/dev/null | head -c {byte_count} | {shlex.quote(tool)}\n"
        )
        fd, path = tempfile.mkstemp(prefix="usbstudio-hash-", suffix=".sh")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("#!/bin/bash\nset -e\n")
                f.write(script)
            os.chmod(path, 0o700)
            res = subprocess.run(
                [PKEXEC or "pkexec", BASH or "bash", path],
                capture_output=True, text=True
            )
            if res.returncode != 0:
                raise RuntimeError(res.stderr.strip() or "No se pudo verificar el dispositivo")
            digest = res.stdout.strip().split()[0]
            if progress_cb:
                progress_cb(1.0)
            return digest.lower()
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Vista 2: Formatear USB
    # ------------------------------------------------------------------
    def build_format_page(self):
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page_box.set_margin_start(16)
        page_box.set_margin_end(16)
        page_box.set_margin_top(8)

        group = Adw.PreferencesGroup(title="Opciones de Formato")

        self.label_entry = Adw.EntryRow(title="Nombre del Pendrive")
        self.label_entry.set_text("OPENARGENT")
        group.add(self.label_entry)

        fs_model = Gtk.StringList.new(["FAT32", "NTFS", "exFAT", "EXT4"])
        self.fs_combo = Adw.ComboRow(title="Sistema de Archivos", model=fs_model)
        group.add(self.fs_combo)

        table_model = Gtk.StringList.new(["MBR (msdos)", "GPT"])
        self.table_combo = Adw.ComboRow(
            title="Tabla de particiones",
            subtitle="MBR para máxima compatibilidad, GPT para discos grandes / UEFI",
            model=table_model
        )
        group.add(self.table_combo)

        page_box.append(group)

        self.btn_format = Gtk.Button(label="Formatear Unidad")
        self.btn_format.add_css_class("destructive-action")
        self.btn_format.add_css_class("pill")
        self.btn_format.connect("clicked", self.on_start_format)
        page_box.append(self.btn_format)

        page = self.stack.add_titled(page_box, "format", "Formatear")
        page.set_icon_name("drive-harddisk-symbolic")

    def on_start_format(self, button):
        dev = self.get_selected_device()
        if not dev:
            self.update_status("Error: Seleccioná un dispositivo USB.")
            return

        if not self._is_still_usb(dev):
            self.update_status("Error: El dispositivo ya no es un USB extraíble o fue desconectado.")
            return

        if not PARTED or not os.path.isfile(PARTED):
            self.update_status(
                "Error: no se encontró 'parted'. Instalá con: sudo apt install parted"
            )
            return

        label = (self.label_entry.get_text() or "USB").strip()
        label = "".join(c for c in label if c.isalnum() or c in ("-", "_", " "))[:11].strip() or "USB"
        fs_idx = self.fs_combo.get_selected()
        table_idx = self.table_combo.get_selected()

        fs_names = ["FAT32", "NTFS", "exFAT", "EXT4"]
        fs_name = fs_names[fs_idx] if 0 <= fs_idx < len(fs_names) else "FAT32"
        table_name = "GPT" if table_idx == 1 else "MBR"

        def do_format():
            self.btn_format.set_sensitive(False)
            self.update_status(f"Formateando {dev} como {fs_name} ({table_name})...")
            threading.Thread(
                target=self._run_format_task,
                args=(dev, fs_idx, label, table_idx),
                daemon=True
            ).start()

        self._confirm_destructive(
            "Confirmar formateo",
            f"Se va a formatear {dev} como {fs_name} ({table_name}) "
            f"con el nombre «{label}».\n"
            "TODO el contenido se borrará de forma irreversible.\n\n"
            "¿Deseás continuar?",
            do_format
        )

    def _run_format_task(self, dev_path, fs_idx, label, table_idx):
        script_path = None
        try:
            if not self._is_still_usb(dev_path):
                self.update_status("Error: El dispositivo ya no es un USB extraíble.")
                return

            part_type_map = {0: "fat32", 1: "ntfs", 2: "fat32", 3: "ext4"}
            part_type = part_type_map.get(fs_idx, "fat32")
            label_type = "gpt" if table_idx == 1 else "msdos"
            part_path = f"{dev_path}1"

            if fs_idx == 0:
                mkfs = MKFS_VFAT or "mkfs.vfat"
                mkfs_cmd = f"{shlex.quote(mkfs)} -F 32 -n {shlex.quote(label)} {shlex.quote(part_path)}"
            elif fs_idx == 1:
                mkfs = MKFS_NTFS or "mkfs.ntfs"
                mkfs_cmd = f"{shlex.quote(mkfs)} -f -L {shlex.quote(label)} {shlex.quote(part_path)}"
            elif fs_idx == 2:
                mkfs = MKFS_EXFAT or "mkfs.exfat"
                mkfs_cmd = f"{shlex.quote(mkfs)} -n {shlex.quote(label)} {shlex.quote(part_path)}"
            else:
                mkfs = MKFS_EXT4 or "mkfs.ext4"
                mkfs_cmd = f"{shlex.quote(mkfs)} -F -L {shlex.quote(label)} {shlex.quote(part_path)}"

            script = self._unmount_script_lines(dev_path) + "\n"
            script += (
                f"{shlex.quote(PARTED)} -s {shlex.quote(dev_path)} "
                f"mklabel {label_type} "
                f"mkpart primary {part_type} 1MiB 100%\n"
            )
            script += "sleep 1\n"
            script += f"{mkfs_cmd}\n"

            fd, script_path = tempfile.mkstemp(prefix="usbstudio-fmt-", suffix=".sh")
            with os.fdopen(fd, "w") as f:
                f.write("#!/bin/bash\nset -e\n")
                f.write(script)
            os.chmod(script_path, 0o700)

            res = subprocess.run(
                [PKEXEC or "pkexec", BASH or "bash", script_path],
                capture_output=True, text=True
            )
            if res.returncode == 0:
                self.update_status("¡Formato completado con éxito!")
            else:
                err = (res.stderr or res.stdout or "").strip()
                self.update_status(
                    f"Error durante el formateo: {err or 'código ' + str(res.returncode)}"
                )
        except Exception as e:
            self.update_status(f"Error al formatear: {e}")
        finally:
            if script_path:
                try:
                    os.unlink(script_path)
                except Exception:
                    pass
            GLib.idle_add(self.btn_format.set_sensitive, True)
            GLib.idle_add(self.load_usb_devices)

    # ------------------------------------------------------------------
    # Vista 3: Reparar y Rescatar
    # ------------------------------------------------------------------
    def build_repair_page(self):
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page_box.set_margin_start(16)
        page_box.set_margin_end(16)
        page_box.set_margin_top(8)

        group = Adw.PreferencesGroup(
            title="Diagnóstico y Rescate de Hardware",
            description="Soluciona bloqueos de sólo lectura, tablas corruptas y firmas cruzadas."
        )

        group.add(Adw.ActionRow(
            title="1. Limpieza Total de Firmas (wipefs)",
            subtitle="Elimina firmas de ISOs híbridas y bloques corruptos"
        ))
        group.add(Adw.ActionRow(
            title="2. Reconstrucción de Tabla de Particiones",
            subtitle="Crea una tabla de particiones nueva y limpia"
        ))
        group.add(Adw.ActionRow(
            title="3. Recreación de Partición FAT32",
            subtitle="Formatea la unidad dejando un sistema de archivos funcional"
        ))

        page_box.append(group)

        table_group = Adw.PreferencesGroup(title="Tabla de particiones de recuperación")
        repair_table_model = Gtk.StringList.new(["MBR (msdos)", "GPT"])
        self.repair_table_combo = Adw.ComboRow(
            title="Tabla a crear",
            subtitle="MBR suele ser más compatible en pendrives antiguos",
            model=repair_table_model
        )
        table_group.add(self.repair_table_combo)
        page_box.append(table_group)

        self.btn_repair = Gtk.Button(label="Iniciar Reparación Automática")
        self.btn_repair.add_css_class("suggested-action")
        self.btn_repair.add_css_class("pill")
        self.btn_repair.connect("clicked", self.on_start_repair)
        page_box.append(self.btn_repair)

        page = self.stack.add_titled(page_box, "repair", "Reparar")
        # Icono más habitual en temas Adwaita / Papirus / etc.
        page.set_icon_name("applications-engineering-symbolic")

    def on_start_repair(self, button):
        dev = self.get_selected_device()
        if not dev:
            self.update_status("Error: Seleccioná un dispositivo USB.")
            return

        if not self._is_still_usb(dev):
            self.update_status("Error: El dispositivo ya no es un USB extraíble o fue desconectado.")
            return

        if not PARTED or not os.path.isfile(PARTED):
            self.update_status(
                "Error: no se encontró 'parted'. Instalá con: sudo apt install parted"
            )
            return
        if not WIPEFS or not os.path.isfile(WIPEFS):
            self.update_status(
                "Error: no se encontró 'wipefs'. Instalá con: sudo apt install util-linux"
            )
            return

        table_idx = self.repair_table_combo.get_selected()
        table_name = "GPT" if table_idx == 1 else "MBR"

        def do_repair():
            self.btn_repair.set_sensitive(False)
            self.update_status(f"Iniciando secuencia de reparación en {dev} ({table_name})...")
            threading.Thread(
                target=self._run_repair_task,
                args=(dev, table_idx),
                daemon=True
            ).start()

        self._confirm_destructive(
            "Confirmar reparación",
            f"Se va a reparar {dev} ({table_name}):\n"
            "• Borrar todas las firmas (wipefs)\n"
            f"• Crear tabla {table_name} nueva\n"
            "• Formatear como FAT32 (nombre RECOVERED)\n\n"
            "TODO el contenido se perderá.\n\n"
            "¿Deseás continuar?",
            do_repair
        )

    def _run_repair_task(self, dev_path, table_idx):
        script_path = None
        try:
            if not self._is_still_usb(dev_path):
                self.update_status("Error: El dispositivo ya no es un USB extraíble.")
                return

            label_type = "gpt" if table_idx == 1 else "msdos"
            part_path = f"{dev_path}1"
            mkfs = MKFS_VFAT or "mkfs.vfat"

            script = self._unmount_script_lines(dev_path) + "\n"
            script += f"{shlex.quote(WIPEFS)} -a -f {shlex.quote(dev_path)}\n"
            script += (
                f"{shlex.quote(PARTED)} -s {shlex.quote(dev_path)} "
                f"mklabel {label_type} "
                f"mkpart primary fat32 1MiB 100%\n"
            )
            script += "sleep 1\n"
            script += f"{shlex.quote(mkfs)} -F 32 -n RECOVERED {shlex.quote(part_path)}\n"

            fd, script_path = tempfile.mkstemp(prefix="usbstudio-repair-", suffix=".sh")
            with os.fdopen(fd, "w") as f:
                f.write("#!/bin/bash\nset -e\n")
                f.write(script)
            os.chmod(script_path, 0o700)

            self.update_status("Ejecutando reparación (una sola solicitud de contraseña)...")
            res = subprocess.run(
                [PKEXEC or "pkexec", BASH or "bash", script_path],
                capture_output=True, text=True
            )
            if res.returncode == 0:
                self.update_status("¡El pendrive ha sido reparado con éxito!")
            else:
                err = (res.stderr or res.stdout or "").strip()
                self.update_status(f"Error en la reparación: {err or 'código ' + str(res.returncode)}")
        except Exception as e:
            self.update_status(f"Error en la reparación: {e}")
        finally:
            if script_path:
                try:
                    os.unlink(script_path)
                except Exception:
                    pass
            GLib.idle_add(self.btn_repair.set_sensitive, True)
            GLib.idle_add(self.load_usb_devices)


class USBStudioApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.openargentos.usbstudio",
            flags=Gio.ApplicationFlags.HANDLES_OPEN
            | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._pending_iso = None
        self._window = None

    def _ensure_window(self):
        if self._window is None:
            self._window = USBStudioWindow(application=self)
        return self._window

    def do_activate(self):
        win = self._ensure_window()
        if self._pending_iso:
            win.set_iso_path(self._pending_iso)
            self._pending_iso = None
        win.present()

    def do_open(self, files, hint):
        # Clic derecho → "Abrir con" / asociación MIME
        if files:
            path = files[0].get_path()
            if path:
                self._pending_iso = path
        self.activate()

    def do_command_line(self, command_line):
        args = command_line.get_arguments()
        # args[0] = ejecutable; el resto pueden ser rutas a ISO
        for arg in args[1:]:
            if arg.startswith("-"):
                continue
            candidate = os.path.abspath(arg)
            if os.path.isfile(candidate) and candidate.lower().endswith(".iso"):
                self._pending_iso = candidate
                break
        self.activate()
        return 0


if __name__ == "__main__":
    app = USBStudioApp()
    app.run(None)
