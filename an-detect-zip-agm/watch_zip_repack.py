import json
import queue
import threading
import time
import shutil
import zipfile
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# =========================
# Paths & Settings
# =========================

def app_dir() -> Path:
    # Directorio donde está el .py o el .exe (PyInstaller)
    return Path(sys.argv[0]).resolve().parent


SETTINGS_PATH = app_dir() / "settings.json"

DEFAULT_SETTINGS = {
    "watch_dir": "",
    "extract_subdir": "extracted",
    "output_subdir": "output",
    "processed_subdir": "processed",
    "poll_settle_seconds": 1.0,
    "max_settle_tries": 30
}


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = DEFAULT_SETTINGS.copy()
                merged.update(data)
                return merged
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


# =========================
# Core ZIP processing
# =========================

def wait_until_file_stable(file_path: Path, poll_seconds: float, max_tries: int) -> None:
    last_size = -1
    for _ in range(max_tries):
        if not file_path.exists():
            time.sleep(poll_seconds)
            continue
        size = file_path.stat().st_size
        if size == last_size and size > 0:
            return
        last_size = size
        time.sleep(poll_seconds)


def safe_move(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    final_dest = dest
    if final_dest.exists():
        final_dest = dest.with_name(f"{dest.stem}__{int(time.time())}{dest.suffix}")
    shutil.move(str(src), str(final_dest))
    return final_dest


def zip_directory(src_dir: Path, dest_zip: Path) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir).as_posix())


def process_zip(zip_path: Path, watch_dir: Path, settings: dict, log) -> None:
    poll_seconds = float(settings.get("poll_settle_seconds", 1.0))
    max_tries = int(settings.get("max_settle_tries", 30))

    extract_root = watch_dir / (settings.get("extract_subdir") or "extracted")
    output_dir = watch_dir / (settings.get("output_subdir") or "output")
    processed_dir = watch_dir / (settings.get("processed_subdir") or "processed")

    for d in (extract_root, output_dir, processed_dir):
        d.mkdir(parents=True, exist_ok=True)

    log(f"Detectado ZIP: {zip_path.name}")
    wait_until_file_stable(zip_path, poll_seconds, max_tries)

    # Validar ZIP
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.testzip()
    except Exception as e:
        log(f"[WARN] ZIP inválido o no listo: {zip_path.name} -> {e}")
        return

    # Extraer en extracted/<stem> (si existe, añade timestamp)
    extract_dir = extract_root / zip_path.stem
    if extract_dir.exists():
        extract_dir = extract_root / f"{zip_path.stem}__{int(time.time())}"

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        log(f"[OK] Descomprimido en: {extract_dir}")
    except Exception as e:
        log(f"[ERROR] Error descomprimiendo {zip_path.name}: {e}")
        return

    # Tomar primera carpeta dentro del nodo descomprimido
    folders = sorted([p for p in extract_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
    if not folders:
        log(f"[WARN] No hay carpetas dentro de {extract_dir}. No se comprime nada.")
        return

    target_folder = folders[0]
    out_zip = output_dir / f"{target_folder.name}.zip"
    if out_zip.exists():
        out_zip = output_dir / f"{target_folder.name}__{int(time.time())}.zip"

    try:
        zip_directory(target_folder, out_zip)
        log(f"[OK] Creado ZIP: {out_zip.name} (desde {target_folder.name})")
    except Exception as e:
        log(f"[ERROR] Error comprimiendo {target_folder}: {e}")
        return

    # Mover original a processed
    try:
        moved = safe_move(zip_path, processed_dir / zip_path.name)
        log(f"[OK] Original movido a: {moved}")
    except Exception as e:
        log(f"[WARN] No se pudo mover el original: {e}")


# =========================
# Watcher Thread (polling)
# =========================

class WatcherThread(threading.Thread):
    """
    Watcher por polling (no requiere watchdog).
    Ventaja: más fácil de empaquetar y estable en Windows.
    """
    def __init__(self, settings_getter, log, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.settings_getter = settings_getter
        self.log = log
        self.stop_event = stop_event
        self.seen = set()

    def run(self):
        self.log("Watcher iniciado.")
        while not self.stop_event.is_set():
            settings = self.settings_getter()
            watch_dir_raw = (settings.get("watch_dir") or "").strip()
            if not watch_dir_raw:
                time.sleep(0.5)
                continue

            watch_dir = Path(watch_dir_raw).expanduser().resolve()
            watch_dir.mkdir(parents=True, exist_ok=True)

            try:
                for p in watch_dir.iterdir():
                    if self.stop_event.is_set():
                        break
                    if p.is_file() and p.suffix.lower() == ".zip":
                        try:
                            fp = (str(p), p.stat().st_mtime_ns, p.stat().st_size)
                        except Exception:
                            continue
                        if fp in self.seen:
                            continue
                        self.seen.add(fp)
                        process_zip(p, watch_dir, settings, self.log)
            except Exception as e:
                self.log(f"[WARN] Error leyendo directorio: {e}")

            time.sleep(0.5)

        self.log("Watcher detenido.")


# =========================
# GUI
# =========================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ZIP Watcher")
        self.geometry("820x560")

        self.log_queue = queue.Queue()
        self.settings = load_settings()

        self.stop_event = threading.Event()
        self.worker = None

        self._build_ui()
        self._load_to_form()
        self._tick_logs()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- Helpers for dirs
    def _watch_dir(self) -> Path | None:
        wd = (self.settings.get("watch_dir") or "").strip()
        if not wd:
            return None
        return Path(wd).expanduser().resolve()

    def _output_dir(self) -> Path | None:
        wd = self._watch_dir()
        if wd is None:
            return None
        return wd / (self.settings.get("output_subdir") or "output")

    def _trash_dir(self) -> Path | None:
        wd = self._watch_dir()
        if wd is None:
            return None
        return wd / "Trash"

    def _is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    # ---- UI
    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        # --- Config
        config_box = ttk.LabelFrame(frm, text="Configuración")
        config_box.pack(fill="x", **pad)

        self.watch_dir_var = tk.StringVar()
        self.poll_var = tk.StringVar()
        self.tries_var = tk.StringVar()

        row1 = ttk.Frame(config_box)
        row1.pack(fill="x", padx=10, pady=6)
        ttk.Label(row1, text="Carpeta de escucha:").pack(side="left")
        self.watch_entry = ttk.Entry(row1, textvariable=self.watch_dir_var)
        self.watch_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row1, text="Explorar...", command=self.browse_folder).pack(side="left")

        row2 = ttk.Frame(config_box)
        row2.pack(fill="x", padx=10, pady=6)
        ttk.Label(row2, text="poll_settle_seconds:").pack(side="left")
        ttk.Entry(row2, width=10, textvariable=self.poll_var).pack(side="left", padx=8)
        ttk.Label(row2, text="max_settle_tries:").pack(side="left", padx=(12, 0))
        ttk.Entry(row2, width=10, textvariable=self.tries_var).pack(side="left", padx=8)

        row3 = ttk.Frame(config_box)
        row3.pack(fill="x", padx=10, pady=6)
        ttk.Button(row3, text="Guardar configuración", command=self.save_from_form).pack(side="left")

        # --- Controls
        ctrl_box = ttk.LabelFrame(frm, text="Control")
        ctrl_box.pack(fill="x", **pad)

        self.status_var = tk.StringVar(value="Parado")

        self.toggle_btn = ttk.Button(ctrl_box, text="Iniciar", command=self.toggle)
        self.toggle_btn.pack(side="left", padx=10, pady=10)

        # NUEVO: botón Limpiar (mueve output/* a watch_dir/Trash)
        self.clean_btn = ttk.Button(ctrl_box, text="Limpiar output → Trash", command=self.clean_output_to_trash)
        self.clean_btn.pack(side="left", padx=10, pady=10)

        ttk.Label(ctrl_box, text="Estado:").pack(side="left", padx=(15, 5))
        ttk.Label(ctrl_box, textvariable=self.status_var).pack(side="left")

        # --- Logs
        log_box = ttk.LabelFrame(frm, text="Logs")
        log_box.pack(fill="both", expand=True, **pad)

        self.log_text = tk.Text(log_box, height=18, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text.configure(state="disabled")

    def _load_to_form(self):
        self.watch_dir_var.set(self.settings.get("watch_dir", ""))
        self.poll_var.set(str(self.settings.get("poll_settle_seconds", 1.0)))
        self.tries_var.set(str(self.settings.get("max_settle_tries", 30)))

    def browse_folder(self):
        path = filedialog.askdirectory(title="Selecciona carpeta de escucha")
        if path:
            self.watch_dir_var.set(path)

    def save_from_form(self):
        watch_dir = (self.watch_dir_var.get() or "").strip()
        if not watch_dir:
            messagebox.showerror("Error", "La carpeta de escucha es obligatoria (por seguridad).")
            return

        try:
            poll = float(self.poll_var.get().strip())
            tries = int(self.tries_var.get().strip())
            if poll <= 0:
                raise ValueError("poll_settle_seconds debe ser > 0")
            if tries <= 0:
                raise ValueError("max_settle_tries debe ser > 0")
        except Exception as e:
            messagebox.showerror("Error", f"Parámetros inválidos: {e}")
            return

        self.settings["watch_dir"] = watch_dir
        self.settings["poll_settle_seconds"] = poll
        self.settings["max_settle_tries"] = tries

        save_settings(self.settings)
        self.log(f"[OK] Config guardada en {SETTINGS_PATH}")

    def settings_getter(self):
        # el thread leerá esta config en caliente
        return dict(self.settings)

    def toggle(self):
        if self._is_running():
            # Stop
            self.stop_event.set()
            self.status_var.set("Deteniendo...")
            self.toggle_btn.configure(state="disabled")
            self.clean_btn.configure(state="disabled")
            self.after(200, self._join_worker)
        else:
            # Start
            if not (self.settings.get("watch_dir") or "").strip():
                self.save_from_form()
                if not (self.settings.get("watch_dir") or "").strip():
                    return

            self.stop_event.clear()
            self.worker = WatcherThread(self.settings_getter, self.log, self.stop_event)
            self.worker.start()
            self.status_var.set("En ejecución")
            self.toggle_btn.configure(text="Parar")
            self.clean_btn.configure(state="disabled")  # Evitar limpiar mientras corre

    def _join_worker(self):
        if self.worker and self.worker.is_alive():
            self.after(200, self._join_worker)
            return

        self.toggle_btn.configure(state="normal", text="Iniciar")
        self.clean_btn.configure(state="normal")
        self.status_var.set("Parado")
        self.log("[OK] Watcher parado.")

    # =========================
    # NUEVO: Limpiar output -> Trash
    # =========================
    def clean_output_to_trash(self):
        if self._is_running():
            messagebox.showwarning("En ejecución", "Para seguridad, detén el watcher antes de limpiar.")
            return

        wd = self._watch_dir()
        if wd is None:
            messagebox.showerror("Error", "Define y guarda una carpeta de escucha antes de limpiar.")
            return

        output_dir = self._output_dir()
        trash_dir = self._trash_dir()
        assert output_dir is not None and trash_dir is not None

        if not output_dir.exists():
            messagebox.showinfo("Sin output", f"No existe la carpeta output: {output_dir}")
            return

        # Contenido a mover
        items = [p for p in output_dir.iterdir()]
        if not items:
            messagebox.showinfo("Sin archivos", "No hay archivos en output para mover.")
            return

        if not messagebox.askyesno(
            "Confirmar limpieza",
            f"Se moverán {len(items)} elementos de:\n{output_dir}\n\nhacia:\n{trash_dir}\n\n¿Continuar?"
        ):
            return

        # En Trash, creamos un subdirectorio con timestamp para evitar colisiones
        stamp = time.strftime("%Y%m%d-%H%M%S")
        batch_dir = trash_dir / f"output_{stamp}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        moved_count = 0
        for p in items:
            try:
                dest = batch_dir / p.name
                # Si colisiona, añade timestamp
                if dest.exists():
                    dest = batch_dir / f"{p.stem}__{int(time.time())}{p.suffix}"
                shutil.move(str(p), str(dest))
                moved_count += 1
            except Exception as e:
                self.log(f"[WARN] No se pudo mover {p.name}: {e}")

        self.log(f"[OK] Limpieza completada. Movidos {moved_count}/{len(items)} a {batch_dir}")
        messagebox.showinfo("Limpieza completada", f"Movidos {moved_count}/{len(items)} elementos a:\n{batch_dir}")

    # ---- Logging
    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.put(f"{timestamp} {msg}")

    def _tick_logs(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", line + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass

        self.after(150, self._tick_logs)

    def on_close(self):
        if self._is_running():
            if not messagebox.askyesno("Salir", "El watcher está ejecutándose. ¿Parar y salir?"):
                return
            self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
