import json
import queue
import threading
import time
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# =========================
# App paths & settings
# =========================

def app_dir() -> Path:
    return Path(sys.argv[0]).resolve().parent


SETTINGS_PATH = app_dir() / "settings.json"

DEFAULT_SETTINGS = {
    "watch_dir": "",
    "extract_subdir": "extracted",
    "output_subdir": "output",
    "processed_subdir": "processed",
    "poll_settle_seconds": 1.0,
    "max_settle_tries": 30,
    "scan_interval_seconds": 0.5,
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
    SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# =========================
# Logging
# =========================

@dataclass(frozen=True)
class LogEvent:
    level: str  # "INFO" | "WARN" | "ERROR" | "OK"
    msg: str


LEVEL_EMOJI = {
    "INFO": "ℹ️",
    "OK": "✅",
    "WARN": "⚠️",
    "ERROR": "❌",
    "START": "🚀",
    "STOP": "🛑",
    "ZIP": "📦",
    "FOLDER": "📁",
    "CLEAN": "🧹",
}


def emoji(level: str) -> str:
    return LEVEL_EMOJI.get(level.upper(), "•")


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


def process_zip(zip_path: Path, watch_dir: Path, settings: dict, emit) -> None:
    poll_seconds = float(settings.get("poll_settle_seconds", 1.0))
    max_tries = int(settings.get("max_settle_tries", 30))

    extract_root = watch_dir / (settings.get("extract_subdir") or "extracted")
    output_dir = watch_dir / (settings.get("output_subdir") or "output")
    processed_dir = watch_dir / (settings.get("processed_subdir") or "processed")

    for d in (extract_root, output_dir, processed_dir):
        d.mkdir(parents=True, exist_ok=True)

    emit("ZIP", f"Detectado ZIP: {zip_path.name}")
    wait_until_file_stable(zip_path, poll_seconds, max_tries)

    # Validar ZIP
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.testzip()
    except Exception as e:
        emit("WARN", f"ZIP inválido o no listo: {zip_path.name} -> {e}")
        return

    # Extraer en extracted/<stem> (si existe, añade timestamp)
    extract_dir = extract_root / zip_path.stem
    if extract_dir.exists():
        extract_dir = extract_root / f"{zip_path.stem}__{int(time.time())}"

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        emit("OK", f"Descomprimido en: {extract_dir}")
    except Exception as e:
        emit("ERROR", f"Error descomprimiendo {zip_path.name}: {e}")
        return

    # Primera carpeta dentro del nodo descomprimido
    folders = sorted([p for p in extract_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
    if not folders:
        emit("WARN", f"No hay carpetas dentro de {extract_dir}. No se comprime nada.")
        return

    target_folder = folders[0]
    emit("FOLDER", f"Carpeta objetivo: {target_folder.name}")

    out_zip = output_dir / f"{target_folder.name}.zip"
    if out_zip.exists():
        out_zip = output_dir / f"{target_folder.name}__{int(time.time())}.zip"

    try:
        zip_directory(target_folder, out_zip)
        emit("OK", f"Creado ZIP: {out_zip.name}")
    except Exception as e:
        emit("ERROR", f"Error comprimiendo {target_folder}: {e}")
        return

    # Mover original a processed
    try:
        moved = safe_move(zip_path, processed_dir / zip_path.name)
        emit("OK", f"Original movido a: {moved}")
    except Exception as e:
        emit("WARN", f"No se pudo mover el original: {e}")


# =========================
# Watcher (polling thread)
# =========================

class WatcherThread(threading.Thread):
    def __init__(self, settings_getter, emit, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.settings_getter = settings_getter
        self.emit = emit
        self.stop_event = stop_event
        self.seen = set()

    def run(self):
        self.emit("START", "Watcher iniciado.")
        while not self.stop_event.is_set():
            settings = self.settings_getter()
            watch_dir_raw = (settings.get("watch_dir") or "").strip()
            scan_interval = float(settings.get("scan_interval_seconds", 0.5))

            if not watch_dir_raw:
                time.sleep(max(0.2, scan_interval))
                continue

            watch_dir = Path(watch_dir_raw).expanduser().resolve()
            watch_dir.mkdir(parents=True, exist_ok=True)

            try:
                for p in watch_dir.iterdir():
                    if self.stop_event.is_set():
                        break
                    if p.is_file() and p.suffix.lower() == ".zip":
                        try:
                            st = p.stat()
                            fp = (str(p), st.st_mtime_ns, st.st_size)
                        except Exception:
                            continue
                        if fp in self.seen:
                            continue
                        self.seen.add(fp)
                        process_zip(p, watch_dir, settings, self.emit)
            except Exception as e:
                self.emit("WARN", f"Error leyendo directorio: {e}")

            time.sleep(max(0.2, scan_interval))

        self.emit("STOP", "Watcher detenido.")


# =========================
# UI
# =========================

class ZipWatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ZIP Watcher")
        self.minsize(980, 640)

        self.settings = load_settings()

        self._log_queue: "queue.Queue[LogEvent]" = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: WatcherThread | None = None

        self._build_style()
        self._build_layout()
        self._load_to_form()

        self._tick_logs()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._set_status("Listo", "idle")

    # ---------- Styling
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            try:
                style.theme_use("clam")
            except Exception:
                pass

        style.configure("App.TFrame", background="#f6f7fb")
        style.configure("Sidebar.TFrame", background="#111827")
        style.configure("Toolbar.TFrame", background="#ffffff")
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("H1.TLabel", font=("Segoe UI", 16, "bold"), background="#ffffff")
        style.configure("Muted.TLabel", foreground="#6b7280", background="#ffffff")
        style.configure("SidebarTitle.TLabel", foreground="#ffffff", background="#111827", font=("Segoe UI", 12, "bold"))
        style.configure("Status.TLabel", background="#ffffff")
        style.configure("Primary.TButton", padding=(14, 10))
        style.configure("Danger.TButton", padding=(14, 10))
        style.configure("Ghost.TButton", padding=(12, 10))

    # ---------- Layout
    def _build_layout(self):
        self.configure(bg="#f6f7fb")

        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        # Sidebar
        self.sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Main
        main = ttk.Frame(root, style="App.TFrame")
        main.pack(side="left", fill="both", expand=True)

        # Toolbar
        toolbar = ttk.Frame(main, style="Toolbar.TFrame")
        toolbar.pack(side="top", fill="x")

        self.btn_start = ttk.Button(toolbar, text="Iniciar", style="Primary.TButton", command=self.start_watcher)
        self.btn_start.pack(side="left", padx=(14, 8), pady=10)

        self.btn_stop = ttk.Button(toolbar, text="Parar", style="Danger.TButton", command=self.stop_watcher, state="disabled")
        self.btn_stop.pack(side="left", padx=8, pady=10)

        self.btn_save = ttk.Button(toolbar, text="Guardar", style="Ghost.TButton", command=self.save_from_form)
        self.btn_save.pack(side="left", padx=8, pady=10)

        self.btn_open = ttk.Button(toolbar, text="Abrir carpeta", style="Ghost.TButton", command=self.open_watch_folder)
        self.btn_open.pack(side="left", padx=8, pady=10)

        # Status
        self.status_text = tk.StringVar(value="Listo")
        self.status_pill = tk.StringVar(value="IDLE")
        status_frame = ttk.Frame(toolbar, style="Toolbar.TFrame")
        status_frame.pack(side="right", padx=14, pady=10)
        ttk.Label(status_frame, textvariable=self.status_pill, style="Status.TLabel").pack(side="right")
        ttk.Label(status_frame, textvariable=self.status_text, style="Status.TLabel").pack(side="right", padx=(0, 10))

        # Content
        content = ttk.Frame(main, style="App.TFrame")
        content.pack(side="top", fill="both", expand=True, padx=14, pady=(0, 14))

        header = ttk.Frame(content, style="App.TFrame")
        header.pack(fill="x", pady=(6, 10))
        tk.Label(header, text="ZIP Watcher", font=("Segoe UI", 18, "bold"), bg="#f6f7fb").pack(side="left")
        tk.Label(
            header,
            text="Monitoriza ZIPs, descomprime y genera un ZIP a partir de la primera carpeta.",
            font=("Segoe UI", 10),
            bg="#f6f7fb",
            fg="#6b7280",
        ).pack(side="left", padx=(12, 0))

        body = ttk.Frame(content, style="App.TFrame")
        body.pack(fill="both", expand=True)

        left_col = ttk.Frame(body, style="App.TFrame")
        left_col.pack(side="left", fill="both", expand=True)

        right_col = ttk.Frame(body, style="App.TFrame")
        right_col.pack(side="left", fill="both", expand=True, padx=(14, 0))

        # Config card
        self.card_config = ttk.Frame(left_col, style="Card.TFrame")
        self.card_config.pack(fill="both", expand=True)

        cfg_inner = ttk.Frame(self.card_config, style="Card.TFrame")
        cfg_inner.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(cfg_inner, text="Configuración", style="H1.TLabel").pack(anchor="w")
        ttk.Label(cfg_inner, text="Define la carpeta de escucha y parámetros de estabilidad.", style="Muted.TLabel").pack(anchor="w", pady=(4, 12))

        self.var_watch_dir = tk.StringVar()
        self.var_poll = tk.StringVar()
        self.var_tries = tk.StringVar()
        self.var_scan = tk.StringVar()

        row = ttk.Frame(cfg_inner, style="Card.TFrame")
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Carpeta de escucha", background="#ffffff").pack(anchor="w")
        r2 = ttk.Frame(row, style="Card.TFrame")
        r2.pack(fill="x", pady=(4, 0))
        ttk.Entry(r2, textvariable=self.var_watch_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(r2, text="Explorar...", command=self.browse_folder).pack(side="left", padx=(8, 0))

        grid = ttk.Frame(cfg_inner, style="Card.TFrame")
        grid.pack(fill="x", pady=(14, 6))

        def field(parent, label, var, width=14):
            f = ttk.Frame(parent, style="Card.TFrame")
            ttk.Label(f, text=label, background="#ffffff").pack(anchor="w")
            ttk.Entry(f, textvariable=var, width=width).pack(anchor="w", pady=(4, 0))
            return f

        field(grid, "poll_settle_seconds", self.var_poll).grid(row=0, column=0, sticky="w", padx=(0, 18))
        field(grid, "max_settle_tries", self.var_tries).grid(row=0, column=1, sticky="w", padx=(0, 18))
        field(grid, "scan_interval_seconds", self.var_scan).grid(row=0, column=2, sticky="w")

        ttk.Label(
            cfg_inner,
            text="Nota: por seguridad, no existe carpeta por defecto. Debe configurarse explícitamente.",
            background="#ffffff",
            foreground="#6b7280"
        ).pack(anchor="w", pady=(14, 0))

        # Activity card
        self.card_activity = ttk.Frame(right_col, style="Card.TFrame")
        self.card_activity.pack(fill="both", expand=True)

        act_inner = ttk.Frame(self.card_activity, style="Card.TFrame")
        act_inner.pack(fill="both", expand=True, padx=14, pady=14)

        top_act = ttk.Frame(act_inner, style="Card.TFrame")
        top_act.pack(fill="x")
        ttk.Label(top_act, text="Actividad", style="H1.TLabel").pack(side="left")

        self.btn_clean_output = ttk.Button(top_act, text="🧹 Limpiar output → Trash", command=self.clean_output_to_trash)
        self.btn_clean_output.pack(side="right")

        self.btn_clear_logs = ttk.Button(top_act, text="🧽 Limpiar logs", command=self.clear_logs)
        self.btn_clear_logs.pack(side="right", padx=(0, 8))

        self.btn_export_logs = ttk.Button(top_act, text="💾 Exportar…", command=self.export_logs)
        self.btn_export_logs.pack(side="right", padx=(0, 8))

        self.btn_copy_logs = ttk.Button(top_act, text="📋 Copiar", command=self.copy_logs)
        self.btn_copy_logs.pack(side="right", padx=(0, 8))

        ttk.Label(act_inner, text="Registro en tiempo real (con emojis).", style="Muted.TLabel").pack(anchor="w", pady=(4, 10))

        self.txt_logs = tk.Text(
            act_inner,
            height=18,
            wrap="word",
            bg="#0b1220",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            padx=10,
            pady=8
        )
        self.txt_logs.pack(fill="both", expand=True)
        self.txt_logs.configure(state="disabled")

        # Sidebar
        self._build_sidebar()

        # Bottom status bar
        self.statusbar = ttk.Frame(main, style="Toolbar.TFrame")
        self.statusbar.pack(side="bottom", fill="x")
        self.sb_left = tk.StringVar(value="Config: " + str(SETTINGS_PATH))
        ttk.Label(self.statusbar, textvariable=self.sb_left, style="Status.TLabel").pack(side="left", padx=14, pady=6)

        self.sb_right = tk.StringVar(value="")
        ttk.Label(self.statusbar, textvariable=self.sb_right, style="Status.TLabel").pack(side="right", padx=14, pady=6)

        # Tag styles (once)
        self.txt_logs.tag_config("INFO", foreground="#93c5fd")
        self.txt_logs.tag_config("OK", foreground="#86efac")
        self.txt_logs.tag_config("WARN", foreground="#fde68a")
        self.txt_logs.tag_config("ERROR", foreground="#fca5a5")
        # “special” levels map to INFO unless specified
        self.txt_logs.tag_config("START", foreground="#86efac")
        self.txt_logs.tag_config("STOP", foreground="#fca5a5")
        self.txt_logs.tag_config("ZIP", foreground="#c4b5fd")
        self.txt_logs.tag_config("FOLDER", foreground="#67e8f9")
        self.txt_logs.tag_config("CLEAN", foreground="#a7f3d0")

    def _build_sidebar(self):
        pad = {"padx": 14, "pady": 10}
        ttk.Label(self.sidebar, text="ZIP Watcher", style="SidebarTitle.TLabel").pack(anchor="w", **pad)

        ttk.Separator(self.sidebar).pack(fill="x", padx=14, pady=(0, 10))

        self.side_info = tk.StringVar(value="Estado: Parado")
        ttk.Label(self.sidebar, textvariable=self.side_info, background="#111827", foreground="#d1d5db").pack(anchor="w", padx=14, pady=(0, 10))

        ttk.Button(self.sidebar, text="Iniciar", command=self.start_watcher).pack(fill="x", padx=14, pady=6)
        ttk.Button(self.sidebar, text="Parar", command=self.stop_watcher).pack(fill="x", padx=14, pady=6)
        ttk.Button(self.sidebar, text="Guardar configuración", command=self.save_from_form).pack(fill="x", padx=14, pady=6)
        ttk.Button(self.sidebar, text="Abrir carpeta de escucha", command=self.open_watch_folder).pack(fill="x", padx=14, pady=6)

        ttk.Separator(self.sidebar).pack(fill="x", padx=14, pady=(12, 10))

        self.side_paths = tk.StringVar(value="(sin carpeta configurada)")
        ttk.Label(self.sidebar, text="Rutas:", background="#111827", foreground="#9ca3af").pack(anchor="w", padx=14)
        ttk.Label(self.sidebar, textvariable=self.side_paths, background="#111827", foreground="#d1d5db",
                  wraplength=190, justify="left").pack(anchor="w", padx=14, pady=(4, 0))

    # ---------- Helpers
    def emit(self, level: str, msg: str):
        self._log_queue.put(LogEvent(level=level, msg=msg))

    def _set_status(self, text: str, pill: str):
        self.status_text.set(text)
        self.status_pill.set(pill.upper())
        self.sb_right.set(time.strftime("%Y-%m-%d %H:%M:%S"))

        if pill.lower() == "running":
            self.side_info.set("Estado: En ejecución")
        elif pill.lower() == "stopping":
            self.side_info.set("Estado: Deteniendo…")
        else:
            self.side_info.set("Estado: Parado" if pill.lower() == "idle" else f"Estado: {pill}")

    def _is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

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

    def settings_getter(self):
        return dict(self.settings)

    # ---------- Form load/save
    def _load_to_form(self):
        self.var_watch_dir.set(self.settings.get("watch_dir", ""))
        self.var_poll.set(str(self.settings.get("poll_settle_seconds", 1.0)))
        self.var_tries.set(str(self.settings.get("max_settle_tries", 30)))
        self.var_scan.set(str(self.settings.get("scan_interval_seconds", 0.5)))
        self._refresh_sidebar_paths()

    def _refresh_sidebar_paths(self):
        wd = self._watch_dir()
        if wd is None:
            self.side_paths.set("(sin carpeta configurada)")
            return
        extracted = wd / (self.settings.get("extract_subdir") or "extracted")
        output = wd / (self.settings.get("output_subdir") or "output")
        processed = wd / (self.settings.get("processed_subdir") or "processed")
        trash = wd / "Trash"
        self.side_paths.set(
            f"{wd}\n\nextracted:\n{extracted}\n\noutput:\n{output}\n\nprocessed:\n{processed}\n\nTrash:\n{trash}"
        )

    def browse_folder(self):
        path = filedialog.askdirectory(title="Selecciona carpeta de escucha")
        if path:
            self.var_watch_dir.set(path)

    def _validate_form(self) -> tuple[bool, str]:
        watch_dir = (self.var_watch_dir.get() or "").strip()
        if not watch_dir:
            return False, "La carpeta de escucha es obligatoria (por seguridad)."

        try:
            poll = float(self.var_poll.get().strip())
            tries = int(self.var_tries.get().strip())
            scan = float(self.var_scan.get().strip())
            if poll <= 0:
                return False, "poll_settle_seconds debe ser > 0"
            if tries <= 0:
                return False, "max_settle_tries debe ser > 0"
            if scan < 0.2:
                return False, "scan_interval_seconds debe ser >= 0.2"
        except Exception as e:
            return False, f"Parámetros inválidos: {e}"

        return True, ""

    def save_from_form(self):
        ok, msg = self._validate_form()
        if not ok:
            messagebox.showerror("Validación", msg)
            return

        self.settings["watch_dir"] = (self.var_watch_dir.get() or "").strip()
        self.settings["poll_settle_seconds"] = float(self.var_poll.get().strip())
        self.settings["max_settle_tries"] = int(self.var_tries.get().strip())
        self.settings["scan_interval_seconds"] = float(self.var_scan.get().strip())

        save_settings(self.settings)
        self._refresh_sidebar_paths()
        self.emit("OK", f"Configuración guardada en {SETTINGS_PATH}")
        self._set_status("Configuración guardada", "running" if self._is_running() else "idle")

    # ---------- Watcher controls
    def start_watcher(self):
        if self._is_running():
            return

        ok, msg = self._validate_form()
        if not ok:
            messagebox.showerror("Validación", msg)
            return

        # Persist and use latest values
        self.save_from_form()

        self._stop_event.clear()
        self._worker = WatcherThread(self.settings_getter, self.emit, self._stop_event)
        self._worker.start()

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_clean_output.configure(state="disabled")  # evita limpiar mientras corre
        self._set_status("En ejecución", "running")
        self.emit("START", "Monitorización activa.")

    def stop_watcher(self):
        if not self._is_running():
            return
        self._stop_event.set()
        self._set_status("Deteniendo…", "stopping")
        self.btn_stop.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self.btn_clean_output.configure(state="disabled")
        self.after(150, self._join_worker)

    def _join_worker(self):
        if self._worker and self._worker.is_alive():
            self.after(150, self._join_worker)
            return

        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_clean_output.configure(state="normal")
        self._set_status("Parado", "idle")
        self.emit("STOP", "Watcher parado.")

    # ---------- Actions
    def open_watch_folder(self):
        wd = self._watch_dir()
        if wd is None:
            messagebox.showinfo("Carpeta", "Configura una carpeta de escucha primero.")
            return
        try:
            import os
            os.startfile(str(wd))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta: {e}")

    def clean_output_to_trash(self):
        if self._is_running():
            messagebox.showwarning("En ejecución", "Por seguridad, detén el watcher antes de limpiar.")
            return

        wd = self._watch_dir()
        if wd is None:
            messagebox.showerror("Error", "Define y guarda una carpeta de escucha antes de limpiar.")
            return

        output_dir = self._output_dir()
        trash_dir = self._trash_dir()
        assert output_dir is not None and trash_dir is not None

        if not output_dir.exists():
            messagebox.showinfo("Output", f"No existe la carpeta output:\n{output_dir}")
            return

        items = [p for p in output_dir.iterdir()]
        if not items:
            messagebox.showinfo("Output", "No hay elementos en output para mover.")
            return

        if not messagebox.askyesno(
            "Confirmar",
            f"Se moverán {len(items)} elementos de:\n{output_dir}\n\nhacia:\n{trash_dir}\n\n¿Continuar?"
        ):
            return

        stamp = time.strftime("%Y%m%d-%H%M%S")
        batch_dir = trash_dir / f"output_{stamp}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        moved = 0
        for p in items:
            try:
                dest = batch_dir / p.name
                if dest.exists():
                    dest = batch_dir / f"{p.stem}__{int(time.time())}{p.suffix}"
                shutil.move(str(p), str(dest))
                moved += 1
            except Exception as e:
                self.emit("WARN", f"No se pudo mover {p.name}: {e}")

        self.emit("CLEAN", f"Limpieza completada: {moved}/{len(items)} movidos a {batch_dir}")
        messagebox.showinfo("Limpieza", f"Movidos {moved}/{len(items)} elementos a:\n{batch_dir}")

    def clear_logs(self):
        # Limpieza de logs (UI)
        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.configure(state="disabled")
        self.emit("CLEAN", "Logs limpiados.")

    def copy_logs(self):
        self.txt_logs.configure(state="normal")
        text = self.txt_logs.get("1.0", "end-1c")
        self.txt_logs.configure(state="disabled")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.emit("OK", "Logs copiados al portapapeles.")

    def export_logs(self):
        path = filedialog.asksaveasfilename(
            title="Exportar logs",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return

        self.txt_logs.configure(state="normal")
        text = self.txt_logs.get("1.0", "end-1c")
        self.txt_logs.configure(state="disabled")

        try:
            Path(path).write_text(text, encoding="utf-8")
            self.emit("OK", f"Logs exportados a {path}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar: {e}")

    # ---------- Log pump
    def _tick_logs(self):
        try:
            while True:
                ev = self._log_queue.get_nowait()
                self._append_log(ev)
        except queue.Empty:
            pass
        self.after(120, self._tick_logs)

    def _append_log(self, ev: LogEvent):
        ts = time.strftime("%H:%M:%S")
        lvl = ev.level.upper()

        # Emoji + label
        prefix = f"{emoji(lvl)}"
        line = f"{ts} {prefix} [{lvl}] {ev.msg}\n"

        self.txt_logs.configure(state="normal")
        start = self.txt_logs.index("end-1c")
        self.txt_logs.insert("end", line)
        end = self.txt_logs.index("end-1c")

        # Tag by level, fallback to INFO
        tag = lvl if lvl in ("INFO", "OK", "WARN", "ERROR", "START", "STOP", "ZIP", "FOLDER", "CLEAN") else "INFO"
        self.txt_logs.tag_add(tag, start, end)

        self.txt_logs.see("end")
        self.txt_logs.configure(state="disabled")

        self.sb_right.set(time.strftime("%Y-%m-%d %H:%M:%S"))

    # ---------- Close
    def on_close(self):
        if self._is_running():
            if not messagebox.askyesno("Salir", "El watcher está en ejecución. ¿Parar y salir?"):
                return
            self._stop_event.set()
        self.destroy()


if __name__ == "__main__":
    app = ZipWatcherApp()
    app.mainloop()
