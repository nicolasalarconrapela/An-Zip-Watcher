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
    "max_recent_events": 50,
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
    level: str
    msg: str
    ts: float


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
    "TRASH": "🗑️",
    "SEARCH": "🔎",
}

COUNT_BUCKET = {
    "INFO": "INFO",
    "OK": "OK",
    "WARN": "WARN",
    "ERROR": "ERROR",
    "START": "INFO",
    "STOP": "INFO",
    "ZIP": "INFO",
    "FOLDER": "INFO",
    "CLEAN": "INFO",
    "TRASH": "INFO",
    "SEARCH": "INFO",
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
        self.minsize(1120, 720)

        self.settings = load_settings()

        self._log_queue: "queue.Queue[LogEvent]" = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: WatcherThread | None = None

        # store para filtros/busqueda/export
        self._log_store: list[LogEvent] = []

        # counters
        self._count_info = 0
        self._count_ok = 0
        self._count_warn = 0
        self._count_error = 0

        # recent events (tabla)
        self._max_recent = int(self.settings.get("max_recent_events", 50))

        self._build_style()
        self._build_layout()
        self._load_to_form()

        self._tick_logs()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._set_status("Listo", "idle")

    # ---------- Style
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
        self.sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=240)
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

        # Status (right)
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
            text="Monitoriza ZIPs → descomprime → comprime la primera carpeta.",
            font=("Segoe UI", 10),
            bg="#f6f7fb",
            fg="#6b7280",
        ).pack(side="left", padx=(12, 0))

        # Two columns
        body = ttk.Frame(content, style="App.TFrame")
        body.pack(fill="both", expand=True)

        left_col = ttk.Frame(body, style="App.TFrame")
        left_col.pack(side="left", fill="both", expand=True)

        right_col = ttk.Frame(body, style="App.TFrame")
        right_col.pack(side="left", fill="both", expand=True, padx=(14, 0))

        # -------- Dashboard card (left top)
        self.card_dash = ttk.Frame(left_col, style="Card.TFrame")
        self.card_dash.pack(fill="x")

        dash = ttk.Frame(self.card_dash, style="Card.TFrame")
        dash.pack(fill="x", padx=14, pady=14)

        ttk.Label(dash, text="Dashboard", style="H1.TLabel").pack(anchor="w")
        ttk.Label(dash, text="Estado, contadores y rutas principales.", style="Muted.TLabel").pack(anchor="w", pady=(4, 12))

        self.dash_state = tk.StringVar(value="Parado")
        self.dash_watch = tk.StringVar(value="(sin configurar)")
        self.dash_subs = tk.StringVar(value="")

        ttk.Label(dash, textvariable=self.dash_state, background="#ffffff", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(dash, textvariable=self.dash_watch, background="#ffffff", foreground="#374151").pack(anchor="w", pady=(6, 0))
        ttk.Label(dash, textvariable=self.dash_subs, background="#ffffff", foreground="#6b7280", wraplength=520, justify="left").pack(anchor="w", pady=(6, 0))

        self.counts_var = tk.StringVar(value="INFO: 0   OK: 0   WARN: 0   ERROR: 0")
        ttk.Label(dash, textvariable=self.counts_var, background="#ffffff", foreground="#111827", font=("Segoe UI", 11)).pack(anchor="w", pady=(10, 0))

        # -------- Config card (left bottom)
        self.card_config = ttk.Frame(left_col, style="Card.TFrame")
        self.card_config.pack(fill="both", expand=True, pady=(14, 0))

        cfg = ttk.Frame(self.card_config, style="Card.TFrame")
        cfg.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(cfg, text="Configuración", style="H1.TLabel").pack(anchor="w")
        ttk.Label(cfg, text="Ruta de escucha y parámetros.", style="Muted.TLabel").pack(anchor="w", pady=(4, 12))

        self.var_watch_dir = tk.StringVar()
        self.var_poll = tk.StringVar()
        self.var_tries = tk.StringVar()
        self.var_scan = tk.StringVar()

        ttk.Label(cfg, text="Carpeta de escucha", background="#ffffff").pack(anchor="w")
        row = ttk.Frame(cfg, style="Card.TFrame")
        row.pack(fill="x", pady=(4, 10))
        ttk.Entry(row, textvariable=self.var_watch_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Explorar...", command=self.browse_folder).pack(side="left", padx=(8, 0))

        grid = ttk.Frame(cfg, style="Card.TFrame")
        grid.pack(fill="x", pady=(6, 12))

        def field(parent, label, var):
            f = ttk.Frame(parent, style="Card.TFrame")
            ttk.Label(f, text=label, background="#ffffff").pack(anchor="w")
            ttk.Entry(f, textvariable=var, width=16).pack(anchor="w", pady=(4, 0))
            return f

        field(grid, "poll_settle_seconds", self.var_poll).grid(row=0, column=0, sticky="w", padx=(0, 18))
        field(grid, "max_settle_tries", self.var_tries).grid(row=0, column=1, sticky="w", padx=(0, 18))
        field(grid, "scan_interval_seconds", self.var_scan).grid(row=0, column=2, sticky="w")

        ttk.Label(cfg, text="Seguridad: no existe carpeta por defecto. Debe definirse explícitamente.",
                  background="#ffffff", foreground="#6b7280").pack(anchor="w")

        # -------- Activity / Maintenance card (right)
        self.card_activity = ttk.Frame(right_col, style="Card.TFrame")
        self.card_activity.pack(fill="both", expand=True)

        act = ttk.Frame(self.card_activity, style="Card.TFrame")
        act.pack(fill="both", expand=True, padx=14, pady=14)

        top = ttk.Frame(act, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Actividad y mantenimiento", style="H1.TLabel").pack(side="left")

        # Maintenance buttons (filesystem) — separados, explícitos
        self.btn_clean_all = ttk.Button(top, text="🧹 Limpiar TODO → Trash", command=self.clean_all_to_trash)
        self.btn_clean_all.pack(side="right")

        self.btn_clean_output = ttk.Button(top, text="🧹 Output", command=lambda: self.clean_dir_to_trash("output"))
        self.btn_clean_output.pack(side="right", padx=(0, 8))

        self.btn_clean_extracted = ttk.Button(top, text="🧹 Extracted", command=lambda: self.clean_dir_to_trash("extracted"))
        self.btn_clean_extracted.pack(side="right", padx=(0, 8))

        self.btn_clean_processed = ttk.Button(top, text="🧹 Processed", command=lambda: self.clean_dir_to_trash("processed"))
        self.btn_clean_processed.pack(side="right", padx=(0, 8))

        self.btn_empty_trash = ttk.Button(top, text="🗑️ Vaciar Trash", command=self.empty_trash)
        self.btn_empty_trash.pack(side="right", padx=(0, 8))

        # Logs controls
        controls = ttk.Frame(act, style="Card.TFrame")
        controls.pack(fill="x", pady=(12, 8))

        self.btn_clear_logs = ttk.Button(controls, text="🧽 Limpiar logs (UI)", command=self.clear_logs_only)
        self.btn_clear_logs.pack(side="left")

        self.btn_copy_logs = ttk.Button(controls, text="📋 Copiar", command=self.copy_logs)
        self.btn_copy_logs.pack(side="left", padx=(8, 0))

        self.btn_export_logs = ttk.Button(controls, text="💾 Exportar…", command=self.export_logs)
        self.btn_export_logs.pack(side="left", padx=(8, 0))

        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=12)

        # Filters
        self.filter_info = tk.BooleanVar(value=True)
        self.filter_ok = tk.BooleanVar(value=True)
        self.filter_warn = tk.BooleanVar(value=True)
        self.filter_error = tk.BooleanVar(value=True)

        ttk.Checkbutton(controls, text="ℹ️ INFO", variable=self.filter_info, command=self.refresh_logs_view).pack(side="left")
        ttk.Checkbutton(controls, text="✅ OK", variable=self.filter_ok, command=self.refresh_logs_view).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(controls, text="⚠️ WARN", variable=self.filter_warn, command=self.refresh_logs_view).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(controls, text="❌ ERROR", variable=self.filter_error, command=self.refresh_logs_view).pack(side="left", padx=(8, 0))

        self.btn_only_issues = ttk.Button(controls, text="Solo WARN+ERROR", command=self.only_warn_error)
        self.btn_only_issues.pack(side="left", padx=(12, 0))

        self.btn_show_all = ttk.Button(controls, text="Mostrar todo", command=self.show_all_levels)
        self.btn_show_all.pack(side="left", padx=(8, 0))

        # Search
        search = ttk.Frame(act, style="Card.TFrame")
        search.pack(fill="x", pady=(0, 10))
        ttk.Label(search, text="Buscar en logs:", background="#ffffff").pack(side="left")
        self.search_var = tk.StringVar(value="")
        ttk.Entry(search, textvariable=self.search_var).pack(side="left", fill="x", expand=True, padx=(8, 8))
        ttk.Button(search, text="🔎 Buscar", command=self.search_logs).pack(side="left")
        ttk.Button(search, text="Reset", command=self.refresh_logs_view).pack(side="left", padx=(8, 0))

        # Split: logs + recent events
        split = ttk.PanedWindow(act, orient="vertical")
        split.pack(fill="both", expand=True)

        # Logs text
        logs_frame = ttk.Frame(split, style="Card.TFrame")
        self.txt_logs = tk.Text(
            logs_frame,
            height=16,
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

        # Tags
        self.txt_logs.tag_config("INFO", foreground="#93c5fd")
        self.txt_logs.tag_config("OK", foreground="#86efac")
        self.txt_logs.tag_config("WARN", foreground="#fde68a")
        self.txt_logs.tag_config("ERROR", foreground="#fca5a5")
        self.txt_logs.tag_config("START", foreground="#86efac")
        self.txt_logs.tag_config("STOP", foreground="#fca5a5")
        self.txt_logs.tag_config("ZIP", foreground="#c4b5fd")
        self.txt_logs.tag_config("FOLDER", foreground="#67e8f9")
        self.txt_logs.tag_config("CLEAN", foreground="#a7f3d0")
        self.txt_logs.tag_config("TRASH", foreground="#a7f3d0")
        self.txt_logs.tag_config("SEARCH", foreground="#fcd34d")

        # Recent events table
        table_frame = ttk.Frame(split, style="Card.TFrame")
        ttk.Label(table_frame, text="Últimos eventos", background="#ffffff", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 0))

        cols = ("time", "level", "msg")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=7)
        self.tree.heading("time", text="Hora")
        self.tree.heading("level", text="Nivel")
        self.tree.heading("msg", text="Mensaje")
        self.tree.column("time", width=90, anchor="w")
        self.tree.column("level", width=80, anchor="w")
        self.tree.column("msg", width=700, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

        split.add(logs_frame, weight=3)
        split.add(table_frame, weight=1)

        # Sidebar
        self._build_sidebar()

        # Statusbar
        self.statusbar = ttk.Frame(main, style="Toolbar.TFrame")
        self.statusbar.pack(side="bottom", fill="x")
        self.sb_left = tk.StringVar(value="Config: " + str(SETTINGS_PATH))
        ttk.Label(self.statusbar, textvariable=self.sb_left, style="Status.TLabel").pack(side="left", padx=14, pady=6)
        self.sb_right = tk.StringVar(value="")
        ttk.Label(self.statusbar, textvariable=self.sb_right, style="Status.TLabel").pack(side="right", padx=14, pady=6)

    def _build_sidebar(self):
        pad = {"padx": 14, "pady": 10}
        ttk.Label(self.sidebar, text="ZIP Watcher", style="SidebarTitle.TLabel").pack(anchor="w", **pad)
        ttk.Separator(self.sidebar).pack(fill="x", padx=14, pady=(0, 10))

        self.side_info = tk.StringVar(value="Estado: Parado")
        ttk.Label(self.sidebar, textvariable=self.side_info, background="#111827", foreground="#d1d5db").pack(anchor="w", padx=14, pady=(0, 10))

        ttk.Button(self.sidebar, text="Iniciar", command=self.start_watcher).pack(fill="x", padx=14, pady=6)
        ttk.Button(self.sidebar, text="Parar", command=self.stop_watcher).pack(fill="x", padx=14, pady=6)
        ttk.Button(self.sidebar, text="Guardar configuración", command=self.save_from_form).pack(fill="x", padx=14, pady=6)
        ttk.Button(self.sidebar, text="Abrir carpeta", command=self.open_watch_folder).pack(fill="x", padx=14, pady=6)

        ttk.Separator(self.sidebar).pack(fill="x", padx=14, pady=(12, 10))

        self.side_paths = tk.StringVar(value="(sin carpeta configurada)")
        ttk.Label(self.sidebar, text="Rutas:", background="#111827", foreground="#9ca3af").pack(anchor="w", padx=14)
        ttk.Label(self.sidebar, textvariable=self.side_paths, background="#111827", foreground="#d1d5db",
                  wraplength=210, justify="left").pack(anchor="w", padx=14, pady=(4, 0))

    # ---------- Helpers
    def emit(self, level: str, msg: str):
        self._log_queue.put(LogEvent(level=level.upper(), msg=msg, ts=time.time()))

    def _set_status(self, text: str, pill: str):
        self.status_text.set(text)
        self.status_pill.set(pill.upper())
        self.sb_right.set(time.strftime("%Y-%m-%d %H:%M:%S"))

        if pill.lower() == "running":
            self.side_info.set("Estado: En ejecución")
            self.dash_state.set("Estado: En ejecución")
        elif pill.lower() == "stopping":
            self.side_info.set("Estado: Deteniendo…")
            self.dash_state.set("Estado: Deteniendo…")
        else:
            self.side_info.set("Estado: Parado")
            self.dash_state.set("Estado: Parado")

    def _is_running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def settings_getter(self):
        return dict(self.settings)

    # ---------- Paths
    def _watch_dir(self) -> Path | None:
        wd = (self.settings.get("watch_dir") or "").strip()
        if not wd:
            return None
        return Path(wd).expanduser().resolve()

    def _dir(self, key: str) -> Path | None:
        wd = self._watch_dir()
        if wd is None:
            return None
        if key == "output":
            return wd / (self.settings.get("output_subdir") or "output")
        if key == "extracted":
            return wd / (self.settings.get("extract_subdir") or "extracted")
        if key == "processed":
            return wd / (self.settings.get("processed_subdir") or "processed")
        if key == "trash":
            return wd / "Trash"
        return None

    # ---------- Config load/save
    def _load_to_form(self):
        self.var_watch_dir.set(self.settings.get("watch_dir", ""))
        self.var_poll.set(str(self.settings.get("poll_settle_seconds", 1.0)))
        self.var_tries.set(str(self.settings.get("max_settle_tries", 30)))
        self.var_scan.set(str(self.settings.get("scan_interval_seconds", 0.5)))
        self._refresh_sidebar_paths()
        self._refresh_dashboard_paths()

    def _refresh_sidebar_paths(self):
        wd = self._watch_dir()
        if wd is None:
            self.side_paths.set("(sin carpeta configurada)")
            self.dash_watch.set("(sin configurar)")
            self.dash_subs.set("")
            return

        extracted = self._dir("extracted")
        output = self._dir("output")
        processed = self._dir("processed")
        trash = self._dir("trash")
        self.side_paths.set(
            f"{wd}\n\nextracted:\n{extracted}\n\noutput:\n{output}\n\nprocessed:\n{processed}\n\nTrash:\n{trash}"
        )

    def _refresh_dashboard_paths(self):
        wd = self._watch_dir()
        if wd is None:
            self.dash_watch.set("(sin configurar)")
            self.dash_subs.set("")
            return

        extracted = self._dir("extracted")
        output = self._dir("output")
        processed = self._dir("processed")
        trash = self._dir("trash")
        self.dash_watch.set(f"Carpeta de escucha: {wd}")
        self.dash_subs.set(
            f"Subcarpetas: extracted / output / processed / Trash\n"
            f"extracted: {extracted}\n"
            f"output: {output}\n"
            f"processed: {processed}\n"
            f"Trash: {trash}"
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
        self._refresh_dashboard_paths()
        self.emit("OK", f"Configuración guardada en {SETTINGS_PATH}")
        self._set_status("Configuración guardada", "running" if self._is_running() else "idle")

    # ---------- Start/Stop
    def start_watcher(self):
        if self._is_running():
            return

        ok, msg = self._validate_form()
        if not ok:
            messagebox.showerror("Validación", msg)
            return

        self.save_from_form()

        self._stop_event.clear()
        self._worker = WatcherThread(self.settings_getter, self.emit, self._stop_event)
        self._worker.start()

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        # Bloquea mantenimiento mientras corre (evita carreras)
        self._set_maintenance_enabled(False)

        self._set_status("En ejecución", "running")
        self.emit("START", "Monitorización activa.")

    def stop_watcher(self):
        if not self._is_running():
            return
        self._stop_event.set()
        self._set_status("Deteniendo…", "stopping")
        self.btn_stop.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self._set_maintenance_enabled(False)
        self.after(150, self._join_worker)

    def _join_worker(self):
        if self._worker and self._worker.is_alive():
            self.after(150, self._join_worker)
            return

        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._set_maintenance_enabled(True)
        self._set_status("Parado", "idle")
        self.emit("STOP", "Watcher parado.")

    def _set_maintenance_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for btn in (
            self.btn_clean_all,
            self.btn_clean_output,
            self.btn_clean_extracted,
            self.btn_clean_processed,
            self.btn_empty_trash,
        ):
            btn.configure(state=state)

    # ---------- Filters
    def _level_visible(self, level: str) -> bool:
        bucket = COUNT_BUCKET.get(level.upper(), "INFO")
        if bucket == "INFO":
            return self.filter_info.get()
        if bucket == "OK":
            return self.filter_ok.get()
        if bucket == "WARN":
            return self.filter_warn.get()
        if bucket == "ERROR":
            return self.filter_error.get()
        return True

    def only_warn_error(self):
        self.filter_info.set(False)
        self.filter_ok.set(False)
        self.filter_warn.set(True)
        self.filter_error.set(True)
        self.refresh_logs_view()

    def show_all_levels(self):
        self.filter_info.set(True)
        self.filter_ok.set(True)
        self.filter_warn.set(True)
        self.filter_error.set(True)
        self.refresh_logs_view()

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

    # ========= Maintenance (filesystem) =========

    def _move_dir_contents_to_trash(self, src_dir: Path, trash_base: Path, tag: str) -> tuple[int, int, Path]:
        """
        Mueve contenido de src_dir a Trash/<tag>_<timestamp>/...
        Devuelve (moved, total, dest_batch_dir)
        """
        total = 0
        moved = 0

        if not src_dir.exists():
            return moved, total, trash_base

        items = [p for p in src_dir.iterdir()]
        total = len(items)
        if total == 0:
            return moved, total, trash_base

        stamp = time.strftime("%Y%m%d-%H%M%S")
        batch_dir = trash_base / f"{tag}_{stamp}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        for p in items:
            try:
                dest = batch_dir / p.name
                if dest.exists():
                    # colisión
                    suffix = p.suffix if p.is_file() else ""
                    stem = p.stem if p.is_file() else p.name
                    dest = batch_dir / f"{stem}__{int(time.time())}{suffix}"
                shutil.move(str(p), str(dest))
                moved += 1
            except Exception as e:
                self.emit("WARN", f"No se pudo mover {p.name}: {e}")

        return moved, total, batch_dir

    def clean_dir_to_trash(self, which: str):
        if self._is_running():
            messagebox.showwarning("En ejecución", "Detén el watcher antes de limpiar directorios.")
            return

        wd = self._watch_dir()
        if wd is None:
            messagebox.showerror("Error", "Define y guarda una carpeta de escucha antes de limpiar.")
            return

        src = self._dir(which)
        trash = self._dir("trash")
        assert src is not None and trash is not None

        if not src.exists():
            messagebox.showinfo("No existe", f"No existe el directorio:\n{src}")
            return

        items = [p for p in src.iterdir()]
        if not items:
            messagebox.showinfo("Vacío", f"No hay elementos en:\n{src}")
            return

        if not messagebox.askyesno(
            "Confirmar",
            f"Se moverán {len(items)} elementos de:\n{src}\n\nhacia:\n{trash}\n\n¿Continuar?"
        ):
            return

        moved, total, batch_dir = self._move_dir_contents_to_trash(src, trash, which)
        self.emit("CLEAN", f"{which.upper()} limpiado: {moved}/{total} movidos a {batch_dir}")
        messagebox.showinfo("Completado", f"{which.upper()} → Trash\nMovidos {moved}/{total} a:\n{batch_dir}")

    def clean_all_to_trash(self):
        if self._is_running():
            messagebox.showwarning("En ejecución", "Detén el watcher antes de limpiar TODO.")
            return

        wd = self._watch_dir()
        if wd is None:
            messagebox.showerror("Error", "Define y guarda una carpeta de escucha antes de limpiar.")
            return

        trash = self._dir("trash")
        outd = self._dir("output")
        exd = self._dir("extracted")
        prd = self._dir("processed")
        assert trash is not None and outd is not None and exd is not None and prd is not None

        # Conteo previo
        counts = []
        for name, d in (("output", outd), ("extracted", exd), ("processed", prd)):
            n = len(list(d.iterdir())) if d.exists() else 0
            counts.append((name, n))

        if all(n == 0 for _, n in counts):
            messagebox.showinfo("Nada que limpiar", "No hay elementos en output/extracted/processed.")
            return

        summary = "\n".join([f"- {name}: {n}" for name, n in counts])
        if not messagebox.askyesno(
            "Confirmar LIMPIEZA TOTAL",
            f"Se moverá el contenido de:\n{summary}\n\nhacia:\n{trash}\n\n¿Continuar?"
        ):
            return

        total_moved = 0
        total_items = 0
        batches = []

        for name, d in (("output", outd), ("extracted", exd), ("processed", prd)):
            moved, total, batch_dir = self._move_dir_contents_to_trash(d, trash, name)
            total_moved += moved
            total_items += total
            if total > 0:
                batches.append(str(batch_dir))

        self.emit("CLEAN", f"Limpieza TOTAL: {total_moved}/{total_items} movidos a Trash")
        messagebox.showinfo(
            "Limpieza total completada",
            f"Movidos {total_moved}/{total_items} elementos.\n\nDestinos:\n" + "\n".join(batches[:10]) + ("\n..." if len(batches) > 10 else "")
        )

    def empty_trash(self):
        if self._is_running():
            messagebox.showwarning("En ejecución", "Detén el watcher antes de vaciar Trash.")
            return

        wd = self._watch_dir()
        if wd is None:
            messagebox.showerror("Error", "Define y guarda una carpeta de escucha antes de vaciar Trash.")
            return

        trash = self._dir("trash")
        assert trash is not None

        if not trash.exists():
            messagebox.showinfo("Trash", f"No existe Trash:\n{trash}")
            return

        items = [p for p in trash.iterdir()]
        if not items:
            messagebox.showinfo("Trash", "Trash está vacío.")
            return

        # Doble confirmación: esto sí elimina definitivamente
        if not messagebox.askyesno(
            "Confirmar",
            f"Esto eliminará DEFINITIVAMENTE {len(items)} elementos dentro de:\n{trash}\n\n¿Continuar?"
        ):
            return
        if not messagebox.askyesno(
            "Confirmación final",
            "Último aviso: esta acción no se puede deshacer.\n\n¿Eliminar definitivamente?"
        ):
            return

        deleted = 0
        for p in items:
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                deleted += 1
            except Exception as e:
                self.emit("WARN", f"No se pudo eliminar {p.name}: {e}")

        self.emit("TRASH", f"Trash vaciado: {deleted}/{len(items)} eliminados definitivamente")
        messagebox.showinfo("Trash", f"Eliminados {deleted}/{len(items)} elementos de Trash.")

    # ========= Logs UI =========

    def clear_logs_only(self):
        # Limpia UI + store + counters (NO toca filesystem)
        self._log_store.clear()
        self._count_info = self._count_ok = self._count_warn = self._count_error = 0
        self._update_counts_label()

        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.configure(state="disabled")

        # mensaje informativo directo (sin store)
        self._append_log_direct("SEARCH", "Logs limpiados (solo UI).")

        # limpiar tabla recent
        for iid in self.tree.get_children():
            self.tree.delete(iid)

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

    def search_logs(self):
        q = (self.search_var.get() or "").strip().lower()
        if not q:
            self.refresh_logs_view()
            return

        # Re-render con filtro adicional (texto)
        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.configure(state="disabled")

        hits = 0
        for ev in self._log_store:
            if not self._level_visible(ev.level):
                continue
            if q in ev.msg.lower() or q in ev.level.lower():
                self._append_log_to_text(ev)
                hits += 1

        self.emit("SEARCH", f"Búsqueda '{q}': {hits} coincidencias (sobre vista filtrada).")

    # ---------- Log pump + rendering
    def _tick_logs(self):
        try:
            while True:
                ev = self._log_queue.get_nowait()
                self._handle_log_event(ev)
        except queue.Empty:
            pass
        self.after(120, self._tick_logs)

    def _handle_log_event(self, ev: LogEvent):
        # store + counters
        self._log_store.append(ev)
        bucket = COUNT_BUCKET.get(ev.level, "INFO")
        if bucket == "INFO":
            self._count_info += 1
        elif bucket == "OK":
            self._count_ok += 1
        elif bucket == "WARN":
            self._count_warn += 1
        elif bucket == "ERROR":
            self._count_error += 1
        self._update_counts_label()

        # render to text if visible
        if self._level_visible(ev.level):
            self._append_log_to_text(ev)

        # recent events table
        self._push_recent_event(ev)

        # dashboard refresh (ruta + subcarpetas)
        self._refresh_dashboard_paths()

        self.sb_right.set(time.strftime("%Y-%m-%d %H:%M:%S"))

    def _update_counts_label(self):
        self.counts_var.set(
            f"INFO: {self._count_info}   OK: {self._count_ok}   WARN: {self._count_warn}   ERROR: {self._count_error}"
        )

    def _append_log_to_text(self, ev: LogEvent):
        ts = time.strftime("%H:%M:%S", time.localtime(ev.ts))
        lvl = ev.level.upper()
        line = f"{ts} {emoji(lvl)} [{lvl}] {ev.msg}\n"

        self.txt_logs.configure(state="normal")
        start = self.txt_logs.index("end-1c")
        self.txt_logs.insert("end", line)
        end = self.txt_logs.index("end-1c")

        tag = lvl if lvl in LEVEL_EMOJI else "INFO"
        self.txt_logs.tag_add(tag, start, end)
        self.txt_logs.see("end")
        self.txt_logs.configure(state="disabled")

    def _append_log_direct(self, level: str, msg: str):
        # Inserta sin store/counters (para acciones UI)
        ts = time.strftime("%H:%M:%S")
        lvl = level.upper()
        line = f"{ts} {emoji(lvl)} [{lvl}] {msg}\n"

        self.txt_logs.configure(state="normal")
        start = self.txt_logs.index("end-1c")
        self.txt_logs.insert("end", line)
        end = self.txt_logs.index("end-1c")
        tag = lvl if lvl in LEVEL_EMOJI else "INFO"
        self.txt_logs.tag_add(tag, start, end)
        self.txt_logs.see("end")
        self.txt_logs.configure(state="disabled")

    def refresh_logs_view(self):
        # Re-render completo según filtros actuales
        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.configure(state="disabled")

        for ev in self._log_store:
            if self._level_visible(ev.level):
                self._append_log_to_text(ev)

    def _push_recent_event(self, ev: LogEvent):
        ts = time.strftime("%H:%M:%S", time.localtime(ev.ts))
        lvl = ev.level.upper()
        msg = ev.msg
        # Insert on top
        iid = self.tree.insert("", 0, values=(ts, f"{emoji(lvl)} {lvl}", msg))
        # Trim
        children = self.tree.get_children()
        if len(children) > self._max_recent:
            for iid2 in children[self._max_recent:]:
                self.tree.delete(iid2)

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
