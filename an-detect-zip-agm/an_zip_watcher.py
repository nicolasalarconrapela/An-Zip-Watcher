from __future__ import annotations

import json
import queue
import threading
import time
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
from typing import Optional, Dict, Tuple, Callable
from collections import deque
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from version import __version__


# =========================
# Constants & Enums
# =========================

class UIStatus(Enum):
    """Estados de la interfaz."""
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"


# =========================
# App paths & settings
# =========================

def app_dir() -> Path:
    return Path(sys.argv[0]).resolve().parent


SETTINGS_PATH = app_dir() / "settings.json"

# Default values for settings
DEFAULT_EXTRACT_SUBDIR = "extracted"
DEFAULT_OUTPUT_SUBDIR = "output"
DEFAULT_PROCESSED_SUBDIR = "processed"
DEFAULT_TRASH_SUBDIR = "Trash"
DEFAULT_POLL_SECONDS = 1.0
DEFAULT_MAX_SETTLE_TRIES = 30
DEFAULT_SCAN_INTERVAL = 0.5
DEFAULT_MAX_RECENT_EVENTS = 50
DEFAULT_MAX_LOG_STORE = 5000  # <-- NUEVO: límite de logs en memoria
MIN_SCAN_INTERVAL = 0.2

# Directorio de sesiones
SESSIONS_DIR = app_dir() / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)
AUTO_SESSION_FILE = SESSIONS_DIR / "last_session.json"

DEFAULT_SETTINGS = {
    "watch_dir": "",
    "extract_subdir": DEFAULT_EXTRACT_SUBDIR,
    "output_subdir": DEFAULT_OUTPUT_SUBDIR,
    "processed_subdir": DEFAULT_PROCESSED_SUBDIR,
    "trash_subdir": DEFAULT_TRASH_SUBDIR,
    "poll_settle_seconds": DEFAULT_POLL_SECONDS,
    "max_settle_tries": DEFAULT_MAX_SETTLE_TRIES,
    "scan_interval_seconds": DEFAULT_SCAN_INTERVAL,
    "max_recent_events": DEFAULT_MAX_RECENT_EVENTS,
    "max_log_store": DEFAULT_MAX_LOG_STORE,
    "welcome_banner_shown": False,  # <-- NUEVO: track si se mostró banner
    "advanced_config_expanded": False,  # <-- NUEVO: estado de config avanzada
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
    """Guarda configuración en JSON."""
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
# Type Aliases
# =========================

EmitFunc = Callable[[str, str], None]


# =========================
# Core ZIP processing
# =========================

def wait_until_file_stable(file_path: Path, poll_seconds: float, max_tries: int) -> None:
    """Espera hasta que el archivo se estabilice (tamaño no cambia)."""
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
    """Mueve src a dest, creando dest.parent si necesario."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    final_dest = dest
    if final_dest.exists():
        final_dest = dest.with_name(f"{dest.stem}__{int(time.time())}{dest.suffix}")
    shutil.move(str(src), str(final_dest))
    return final_dest


def zip_directory(src_dir: Path, dest_zip: Path) -> None:
    """Comprime recursivamente src_dir en dest_zip."""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            files_added = 0
            for p in src_dir.rglob("*"):
                if p.is_file():
                    try:
                        zf.write(p, p.relative_to(src_dir).as_posix())
                        files_added += 1
                    except Exception as e:
                        raise IOError(f"Error añadiendo {p.name} al ZIP: {e}") from e
        if files_added == 0:
            raise ValueError(f"No se comprimió ningún archivo de {src_dir}")
    except zipfile.BadZipFile as e:
        raise IOError(f"Error creando ZIP en {dest_zip}: {e}") from e
    except Exception as e:
        raise IOError(f"Error en zip_directory: {e}") from e


def process_zip(zip_path: Path, watch_dir: Path, settings: dict, emit: EmitFunc) -> None:
    """Procesa ZIP: extrae → comprime primera carpeta → mueve original."""
    try:
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
                bad_file = zf.testzip()
                if bad_file:
                    emit("WARN", f"ZIP corrupto o incompleto: primer archivo dañado {bad_file}")
                    return
        except zipfile.BadZipFile as e:
            emit("WARN", f"ZIP no válido: {zip_path.name} -> {e}")
            return
        except Exception as e:
            emit("WARN", f"Error validando ZIP: {zip_path.name} -> {e}")
            return

        # Extraer en extracted/<stem>
        extract_dir = extract_root / zip_path.stem
        if extract_dir.exists():
            extract_dir = extract_root / f"{zip_path.stem}__{int(time.time())}"

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            emit("OK", f"Descomprimido en: {extract_dir}")
        except zipfile.BadZipFile as e:
            emit("ERROR", f"ZIP corrupto al descomprimir {zip_path.name}: {e}")
            return
        except PermissionError as e:
            emit("ERROR", f"Permisos insuficientes para extraer {zip_path.name}: {e}")
            return
        except Exception as e:
            emit("ERROR", f"Error descomprimiendo {zip_path.name}: {e}")
            return

        # Primera carpeta dentro del nodo descomprimido
        folders = sorted(
            [p for p in extract_dir.iterdir() if p.is_dir()],
            key=lambda p: p.name.lower()
        )
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
        except (IOError, ValueError) as e:
            emit("ERROR", f"Error comprimiendo {target_folder}: {e}")
            return
        except Exception as e:
            emit("ERROR", f"Error inesperado comprimiendo: {e}")
            return

        # Mover original a processed
        try:
            moved = safe_move(zip_path, processed_dir / zip_path.name)
            emit("OK", f"Original movido a: {moved}")
        except FileNotFoundError as e:
            emit("WARN", f"ZIP ya no existe: {e}")
        except PermissionError as e:
            emit("WARN", f"Permisos insuficientes para mover: {e}")
        except Exception as e:
            emit("WARN", f"No se pudo mover el original: {e}")

    except Exception as e:
        emit("ERROR", f"Error crítico en process_zip: {e}")


# =========================
# Watcher (polling thread)
# =========================

class WatcherThread(threading.Thread):
    def __init__(
        self,
        settings_getter: Callable[[], dict],
        emit: EmitFunc,
        stop_event: threading.Event,
        zip_queue: "queue.Queue[tuple[Path, Path]]",
    ):
        super().__init__(daemon=True)
        self.settings_getter = settings_getter
        self.emit = emit
        self.stop_event = stop_event
        self.zip_queue = zip_queue
        self.seen: set[Tuple[str, int, int]] = set()

    def run(self):
        self.emit("START", "Watcher iniciado.")
        while not self.stop_event.is_set():
            settings = self.settings_getter()
            watch_dir_raw = (settings.get("watch_dir") or "").strip()
            scan_interval = float(settings.get("scan_interval_seconds", 0.5))

            if not watch_dir_raw:
                time.sleep(max(0.2, scan_interval))
                continue

            try:
                watch_dir = Path(watch_dir_raw).expanduser().resolve()
                watch_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.emit("WARN", f"Error accediendo a directorio: {e}")
                time.sleep(max(0.2, scan_interval))
                continue

            try:
                # Buscar solo archivos .zip una vez
                zip_files = []
                for p in watch_dir.iterdir():
                    if self.stop_event.is_set():
                        break
                    if p.is_file() and p.suffix.lower() == ".zip":
                        zip_files.append(p)

                # Procesar cada ZIP con su stat en una pasada
                for p in zip_files:
                    if self.stop_event.is_set():
                        break
                    try:
                        st = p.stat()
                        fp = (str(p), st.st_mtime_ns, st.st_size)
                        if fp not in self.seen:
                            self.seen.add(fp)
                            self.zip_queue.put((p, watch_dir))
                            self.emit("INFO", f"ZIP en cola: {p.name}")
                    except FileNotFoundError:
                        continue
                    except Exception as e:
                        self.emit("WARN", f"Error procesando {p.name}: {e}")

            except PermissionError:
                self.emit("WARN", f"Permisos insuficientes en {watch_dir_raw}")
            except Exception as e:
                self.emit("WARN", f"Error leyendo directorio: {e}")

            time.sleep(max(0.2, scan_interval))

        self.emit("STOP", "Watcher detenido.")


class ZipProcessorThread(threading.Thread):
    def __init__(
        self,
        settings_getter: Callable[[], dict],
        emit: EmitFunc,
        stop_event: threading.Event,
        zip_queue: "queue.Queue[tuple[Path, Path]]",
    ):
        super().__init__(daemon=True)
        self.settings_getter = settings_getter
        self.emit = emit
        self.stop_event = stop_event
        self.zip_queue = zip_queue

    def run(self):
        self.emit("START", "Procesador de ZIP iniciado.")
        while True:
            if self.stop_event.is_set() and self.zip_queue.empty():
                break
            try:
                zip_path, watch_dir = self.zip_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                settings = self.settings_getter()
                process_zip(zip_path, watch_dir, settings, self.emit)
            except Exception as e:
                self.emit("WARN", f"Error en cola de procesamiento: {e}")
            finally:
                self.zip_queue.task_done()

        self.emit("STOP", "Procesador de ZIP detenido.")


# =========================
# UI
# =========================

class ZipWatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"An-Zip-Watcher v{__version__}")
        self.minsize(1120, 720)
        
        # Cargar icono
        try:
            # 1. Icono de la ventana (Nativo Windows .ico)
            ico_path = app_dir() / "imgs" / "app.ico"
            if ico_path.exists():
                self.iconbitmap(str(ico_path))
            
            # 2. Imágenes para la UI (PNG)
            png_path = app_dir() / "imgs" / "icons.png"
            if png_path.exists():
                self._app_icon = tk.PhotoImage(file=str(png_path))
                # Crear versión pequeña para Sidebar
                self._app_icon_small = self._app_icon.subsample(32, 32)
                # Crear versión mediana para Dashboard
                self._app_icon_medium = self._app_icon.subsample(12, 12)
            else:
                self._app_icon = None
                self._app_icon_small = None
                self._app_icon_medium = None
                
        except Exception as e:
            print(f"Error cargando iconos: {e}")
            self._app_icon = None
            self._app_icon_small = None
            self._app_icon_medium = None

        self.settings = load_settings()

        self._log_queue: "queue.Queue[LogEvent]" = queue.Queue()
        self._zip_queue: "queue.Queue[tuple[Path, Path]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: WatcherThread | None = None
        self._processor: ZipProcessorThread | None = None

        # store para logs (LIMITADO con deque)
        self._max_log_store = int(self.settings.get("max_log_store", DEFAULT_MAX_LOG_STORE))
        self._log_store: deque[LogEvent] = deque(maxlen=self._max_log_store)

        # counters
        self._count_info = 0
        self._count_ok = 0
        self._count_warn = 0
        self._count_error = 0

        # Eventos procesados (tabla de actividad)
        self._event_counter = 0
        self._processed_events: deque = deque(maxlen=100)  # Últimos 100 eventos
        self._processed_status_cache: dict[str, str] = {}
        
        # Rastreo de procesamiento de ZIP (persiste entre batches)
        self._current_processing_zip = None
        self._current_zip_output = None
        self._last_events_refresh = 0.0
        self._events_refresh_interval = 10.0

        self._build_style()
        self._build_layout()
        self._load_to_form()

        self._tick_logs()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._set_status("Listo", "idle")
        
        # Cargar última sesión automáticamente
        self.after(500, lambda: self.load_session(AUTO_SESSION_FILE))

        # Bind redimensionamiento para ajustar wraplength dinámicamente
        self.bind("<Configure>", self._on_resize)

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
        style.configure("WelcomeBanner.TFrame", background="#dbeafe", relief="solid", borderwidth=1)
        style.configure("H1.TLabel", font=("Segoe UI", 16, "bold"), background="#ffffff")
        style.configure("Muted.TLabel", foreground="#6b7280", background="#ffffff")
        style.configure("SidebarTitle.TLabel", foreground="#ffffff", background="#111827", font=("Segoe UI", 12, "bold"))
        style.configure("SidebarText.TLabel", foreground="#d1d5db", background="#111827", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#ffffff")
        style.configure("StatusPill.TLabel", background="#e5e7eb", foreground="#374151", font=("Segoe UI", 9, "bold"), padding=(8, 4))
        style.configure("Primary.TButton", padding=(14, 10))
        style.configure("Danger.TButton", padding=(14, 10), background="#fee2e2")
        style.configure("Ghost.TButton", padding=(12, 10))

    # ---------- Layout
    def _build_layout(self):
        self.configure(bg="#f6f7fb")

        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        # Sidebar (simplificado)
        self.sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=180)
        self.sidebar.pack(side="left", fill="both", padx=0)
        self.sidebar.pack_propagate(False)

        # Main area
        main = ttk.Frame(root, style="App.TFrame")
        main.pack(side="left", fill="both", expand=True)

        # Header común (Título + Status Pill)
        header = ttk.Frame(main, style="Toolbar.TFrame")
        header.pack(side="top", fill="x") # Sin padding, estilo flat

        # Header simplificado: solo Status pill (título removido por UX cleanup)
        
        # Status pill (mejorado)
        self.status_text = tk.StringVar(value="Listo")
        self.status_pill_text = tk.StringVar(value="⏸️ Detenido")
        
        status_frame = ttk.Frame(header, style="Toolbar.TFrame")
        status_frame.pack(side="right", padx=18, pady=12)
        
        self.status_pill_label = tk.Label(
            status_frame, 
            textvariable=self.status_pill_text, 
            bg="#e5e7eb", 
            fg="#374151",
            font=("Segoe UI", 9, "bold"),
            padx=12, 
            pady=6,
            relief="flat"
        )
        self.status_pill_label.pack(side="right")

        # Toolbar de acciones globales (debajo del header)
        toolbar = ttk.Frame(main, style="App.TFrame") # Color de fondo app para separar
        toolbar.pack(side="top", fill="x", padx=18, pady=(4, 10))

        self.btn_start = ttk.Button(toolbar, text="▶ Iniciar", style="Primary.TButton", command=self.start_watcher)
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = ttk.Button(toolbar, text="⏹ Parar", style="Danger.TButton", command=self.stop_watcher, state="disabled")
        self.btn_stop.pack(side="left", padx=0)
        
        self.btn_open = ttk.Button(toolbar, text="📂 Abrir carpeta", style="Ghost.TButton", command=self.open_watch_folder)
        self.btn_open.pack(side="left", padx=8)

        # NOTEBOOK (Pestañas)
        # Estilo custom para tabs más grandes
        style = ttk.Style()
        style.configure("TNotebook", background="#f6f7fb", borderwidth=0)
        style.configure("TNotebook.Tab", map={"background": [("selected", "#ffffff"), ("active", "#e5e7eb")]},
                        background="#f3f4f6", padding=[20, 10], font=("Segoe UI", 10))
        
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        # --- TAB 1: HOME (Logs + Monitor) ---
        self.tab_home = ttk.Frame(self.notebook, style="App.TFrame")
        self.notebook.add(self.tab_home, text="🏠 Home")
        
        # --- TAB 2: CONFIGURACIÓN ---
        self.tab_config = ttk.Frame(self.notebook, style="App.TFrame")
        self.notebook.add(self.tab_config, text="⚙️ Configuración")

        # --- TAB 3: MANTENIMIENTO ---
        self.tab_maintenance = ttk.Frame(self.notebook, style="App.TFrame")
        self.notebook.add(self.tab_maintenance, text="🧹 Mantenimiento")

        # ==================== CONTENIDO HOME ====================
        
        # Dashboard compacta arriba
        self.card_dash = ttk.Frame(self.tab_home, style="Card.TFrame")
        self.card_dash.pack(fill="x", pady=18, padx=18)
        
        dash_inner = ttk.Frame(self.card_dash, style="Card.TFrame")
        dash_inner.pack(fill="x", padx=18, pady=14)
        
        # Monitor info row
        mon_row = ttk.Frame(dash_inner, style="Card.TFrame")
        mon_row.pack(fill="x")
        
        # Logo a la derecha del todo (Visual identity)
        if self._app_icon_medium:
             logo_label = ttk.Label(mon_row, image=self._app_icon_medium, background="#ffffff")
             logo_label.pack(side="right", padx=(24, 0))

        # Estado (Emoji grande)
        self.dash_state_emoji = tk.StringVar(value="🔴")
        self.dash_state_text = tk.StringVar(value="Detenido")
        
        tk.Label(mon_row, textvariable=self.dash_state_emoji, background="#ffffff", font=("Segoe UI", 24)).pack(side="left")
        
        info_col = ttk.Frame(mon_row, style="Card.TFrame")
        info_col.pack(side="left", padx=(14, 0))
        
        ttk.Label(info_col, textvariable=self.dash_state_text, background="#ffffff", foreground="#111827", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        
        self.dash_watch = tk.StringVar(value="(sin configurar)")
        ttk.Label(info_col, textvariable=self.dash_watch, background="#ffffff", foreground="#6b7280", font=("Segoe UI", 10)).pack(anchor="w")

        # Contadores a la derecha
        stats_col = ttk.Frame(mon_row, style="Card.TFrame")
        stats_col.pack(side="right")
        
        self.counts_var = tk.StringVar(value="✅ 0   ⚠️ 0   ❌ 0")
        ttk.Label(stats_col, text="Sesión", background="#ffffff", foreground="#9ca3af", font=("Segoe UI", 9)).pack(anchor="e")
        ttk.Label(stats_col, textvariable=self.counts_var, background="#ffffff", font=("Segoe UI", 12, "bold")).pack(anchor="e")

        # Tabla de Eventos Procesados
        events_card = ttk.Frame(self.tab_home, style="Card.TFrame")
        events_card.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        
        events_header = ttk.Frame(events_card, style="Card.TFrame")
        events_header.pack(fill="x", padx=14, pady=(14, 0))
        
        tk.Label(events_header, text="Eventos Procesados", background="#ffffff", font=("Segoe UI", 11, "bold"), fg="#111827").pack(side="left")
        
        # Botones de gestión de sesión
        ttk.Button(events_header, text="🔍 Verificar", command=self.verify_missing_files).pack(side="right", padx=(0, 4))
        ttk.Button(events_header, text="📥 Importar", command=self.import_session).pack(side="right", padx=(0, 4))
        ttk.Button(events_header, text="💾 Exportar", command=self.export_session).pack(side="right", padx=(0, 8))
        ttk.Button(events_header, text="🗑️ Limpiar", command=self.clear_events_table).pack(side="right")
        
        # Tabla con Treeview
        table_container = ttk.Frame(events_card, style="Card.TFrame")
        table_container.pack(fill="both", expand=True, padx=14, pady=(10, 14))
        
        # Scrollbars
        table_scroll = ttk.Scrollbar(table_container)
        table_scroll.pack(side="right", fill="y")
        table_scroll_x = ttk.Scrollbar(table_container, orient="horizontal")
        table_scroll_x.pack(side="bottom", fill="x")
        
        # Treeview
        columns = ("id", "hora", "zip", "resultado", "output")
        self.events_tree = ttk.Treeview(
            table_container,
            columns=columns,
            show="headings",
            height=6,
            yscrollcommand=table_scroll.set,
            xscrollcommand=table_scroll_x.set,
        )
        
        self.events_tree.heading("id", text="ID")
        self.events_tree.heading("hora", text="Hora")
        self.events_tree.heading("zip", text="Archivo ZIP")
        self.events_tree.heading("resultado", text="Estado")
        self.events_tree.heading("output", text="Carpeta Salida")
        
        self.events_tree.column("id", width=60, anchor="center", stretch=False)
        self.events_tree.column("hora", width=160, anchor="w", stretch=False)
        self.events_tree.column("zip", width=320, anchor="w", stretch=False)
        self.events_tree.column("resultado", width=140, anchor="center", stretch=False)
        self.events_tree.column("output", width=520, anchor="w", stretch=False)
        
        self.events_tree.pack(side="left", fill="both", expand=True)
        table_scroll.config(command=self.events_tree.yview)
        table_scroll_x.config(command=self.events_tree.xview)
        
        # Doble click para abrir carpeta
        self.events_tree.bind("<Double-Button-1>", self._on_event_double_click)
        
        # Logs container (ocupa el resto)
        logs_frame = ttk.Frame(self.tab_home, style="Card.TFrame")
        logs_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        
        # Tabs de logs
        log_tabs_bar = ttk.Frame(logs_frame, style="Card.TFrame")
        log_tabs_bar.pack(fill="x", padx=14, pady=14)
        
        self.current_log_tab = tk.StringVar(value="todos")
        # Variables de filtro
        self.filter_info = tk.BooleanVar(value=True)
        self.filter_ok = tk.BooleanVar(value=True)
        self.filter_warn = tk.BooleanVar(value=True)
        self.filter_error = tk.BooleanVar(value=True)

        self.tab_todos = tk.Button(log_tabs_bar, text="Todos", command=lambda: self.switch_log_tab("todos"), 
                                 bg="#3b82f6", fg="white", font=("Segoe UI", 9, "bold"), relief="flat", padx=16, pady=6, cursor="hand2")
        self.tab_todos.pack(side="left", padx=(0, 4))
        
        self.tab_problemas = tk.Button(log_tabs_bar, text="Solo problemas", command=lambda: self.switch_log_tab("problemas"), 
                                     bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9), relief="flat", padx=16, pady=6, cursor="hand2")
        self.tab_problemas.pack(side="left", padx=(0, 4))
        
        self.tab_buscar = tk.Button(log_tabs_bar, text="Buscar", command=lambda: self.switch_log_tab("buscar"), 
                                  bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9), relief="flat", padx=16, pady=6, cursor="hand2")
        self.tab_buscar.pack(side="left")

        # Botones log acciones (derecha)
        self.btn_clear_logs = ttk.Button(log_tabs_bar, text="🧽 Limpiar", command=self.clear_logs_only)
        self.btn_clear_logs.pack(side="right", padx=(6, 0))
        ttk.Button(log_tabs_bar, text="💾 Exportar", command=self.export_logs).pack(side="right")

        # Search frame (oculto)
        self.search_frame = ttk.Frame(logs_frame, style="Card.TFrame")
        self.search_var = tk.StringVar(value="")
        ttk.Entry(self.search_frame, textvariable=self.search_var).pack(side="left", fill="x", expand=True, padx=(14, 8))
        ttk.Button(self.search_frame, text="🔎 Buscar", command=self.search_logs).pack(side="left", padx=(0, 4))
        ttk.Button(self.search_frame, text="X", command=self.clear_search, width=3).pack(side="left", padx=(0, 14))

        # Text area logs
        logs_container = ttk.Frame(logs_frame, style="Card.TFrame")
        logs_container.pack(fill="both", expand=True, padx=1, pady=1) # Border overlap
        
        logs_border = tk.Frame(logs_container, background="#e2e8f0", bd=1)
        logs_border.pack(fill="both", expand=True)

        scrollbar_y = ttk.Scrollbar(logs_border)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x = ttk.Scrollbar(logs_border, orient="horizontal")
        scrollbar_x.pack(side="bottom", fill="x")

        self.txt_logs = tk.Text(logs_border, height=10, wrap="none", bg="#1e293b", fg="#f8fafc", 
                              insertbackground="#f8fafc", relief="flat", padx=12, pady=10,
                              yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set, font=("Consolas", 10))
        self.txt_logs.pack(side="left", fill="both", expand=True)
        self.txt_logs.configure(state="disabled")
        scrollbar_y.config(command=self.txt_logs.yview)
        scrollbar_x.config(command=self.txt_logs.xview)
        
        # Configurar tags
        self._configure_log_tags()

        # ================= CONIGURACIÓN TAB =================
        self.card_config = ttk.Frame(self.tab_config, style="Card.TFrame")
        self.card_config.pack(fill="x", padx=18, pady=18)
        
        cfg = ttk.Frame(self.card_config, style="Card.TFrame")
        cfg.pack(fill="x", padx=24, pady=24)
        
        ttk.Label(cfg, text="Configuración del Monitor", style="H1.TLabel").pack(anchor="w", pady=(0, 16))
        
        self.var_watch_dir = tk.StringVar()
        self.var_poll = tk.StringVar()
        self.var_tries = tk.StringVar()
        self.var_scan = tk.StringVar()

        tk.Label(cfg, text="Ruta de vigilancia", background="#ffffff", font=("Segoe UI", 10, "bold"), fg="#374151").pack(anchor="w")
        # Descripción eliminada por ruido visual
        
        row_dir = ttk.Frame(cfg, style="Card.TFrame")
        row_dir.pack(fill="x", pady=(0, 16))
        ttk.Entry(row_dir, textvariable=self.var_watch_dir, font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(row_dir, text="Explorar...", command=self.browse_folder).pack(side="left", padx=(8, 0))

        # Opciones avanzadas siempre visibles en pestaña dedicada
        tk.Label(cfg, text="Parámetros", background="#ffffff", font=("Segoe UI", 10, "bold"), fg="#374151").pack(anchor="w", pady=(6, 0))
        
        row_opts = ttk.Frame(cfg, style="Card.TFrame")
        row_opts.pack(fill="x", pady=(8, 0))
        
        def config_field(parent, label, var, tooltip):
            f = ttk.Frame(parent, style="Card.TFrame")
            lbl = tk.Label(f, text=label, background="#ffffff", fg="#374151")
            lbl.pack(anchor="w")
            self._create_tooltip(lbl, tooltip)
            ttk.Entry(f, textvariable=var, width=15).pack(anchor="w", pady=(2, 0))
            return f

        config_field(row_opts, "Espera (s)", self.var_poll, "Tiempo de estabilidad del archivo").pack(side="left", padx=(0, 20))
        config_field(row_opts, "Reintentos", self.var_tries, "Máximo de intentos de acceso").pack(side="left", padx=(0, 20))
        config_field(row_opts, "Frecuencia (s)", self.var_scan, "Intervalo de escaneo de carpeta").pack(side="left")
        
        # Botón guardar grande
        ttk.Separator(cfg).pack(fill="x", pady=20)
        btn_save_config = ttk.Button(cfg, text="💾 Guardar configuración", style="Primary.TButton", command=self.save_from_form)
        btn_save_config.pack(anchor="e")

        # ================= MANTENIMIENTO TAB =================
        self.card_activity = ttk.Frame(self.tab_maintenance, style="Card.TFrame")
        self.card_activity.pack(fill="both", expand=True, padx=18, pady=18)
        
        maint = ttk.Frame(self.card_activity, style="Card.TFrame")
        maint.pack(fill="both", expand=True, padx=24, pady=24)
        
        ttk.Label(maint, text="Mantenimiento de Carpetas", style="H1.TLabel").pack(anchor="w", pady=(0, 16))
        
        ttk.Label(maint, text="Limpieza manual", background="#ffffff", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        
        row_m1 = ttk.Frame(maint, style="Card.TFrame")
        row_m1.pack(fill="x", pady=(0, 16))
        self.btn_clean_processed = ttk.Button(row_m1, text="Processed", command=lambda: self.clean_dir_to_trash("processed"))
        self.btn_clean_processed.pack(side="left", padx=(0, 8))
        self.btn_clean_extracted = ttk.Button(row_m1, text="Extracted", command=lambda: self.clean_dir_to_trash("extracted"))
        self.btn_clean_extracted.pack(side="left", padx=(0, 8))
        self.btn_clean_output = ttk.Button(row_m1, text="Output", command=lambda: self.clean_dir_to_trash("output"))
        self.btn_clean_output.pack(side="left")
        
        ttk.Separator(maint).pack(fill="x", pady=16)
        
        ttk.Label(maint, text="Zona de riesgo", background="#ffffff", font=("Segoe UI", 11, "bold"), foreground="#dc2626").pack(anchor="w", pady=(0, 8))
        
        self.btn_clean_all = ttk.Button(maint, text="🧹 Vaciar carpetas", command=self.clean_all_to_trash)
        self.btn_clean_all.pack(anchor="w", pady=(0, 8))
        self.btn_empty_trash = ttk.Button(maint, text="🗑️ Vaciar papelera definitivamente", style="Danger.TButton", command=self.empty_trash)
        self.btn_empty_trash.pack(anchor="w")

        # Banner logic (si watch_dir vacio, ir a tab config)
        if not self.settings.get("watch_dir", "").strip():
            self.notebook.select(1) # Tab Configuración
            messagebox.showinfo("Bienvenido", "Por favor configura la carpeta de vigilancia para comenzar.")

        # Sidebar setup
        self._build_sidebar()

        # Statusbar
        self.statusbar = ttk.Frame(main, style="Toolbar.TFrame")
        self.statusbar.pack(side="bottom", fill="x")
        self.sb_left = tk.StringVar(value="Config: " + str(SETTINGS_PATH))
        ttk.Label(self.statusbar, textvariable=self.sb_left, style="Status.TLabel").pack(side="left", padx=14, pady=6)
        self.sb_right = tk.StringVar(value="")
        ttk.Label(self.statusbar, textvariable=self.sb_right, style="Status.TLabel").pack(side="right", padx=14, pady=6)

    def _configure_log_tags(self):
        self.txt_logs.tag_config("INFO", foreground="#94a3b8", background="#1e293b")
        self.txt_logs.tag_config("OK", foreground="#4ade80", background="#1e293b")
        self.txt_logs.tag_config("WARN", foreground="#facc15", background="#422006")
        self.txt_logs.tag_config("ERROR", foreground="#f87171", background="#450a0a")
        self.txt_logs.tag_config("START", foreground="#4ade80", background="#1e293b", font=("Consolas", 10, "bold"))
        self.txt_logs.tag_config("STOP", foreground="#f87171", background="#1e293b", font=("Consolas", 10, "bold"))
        self.txt_logs.tag_config("ZIP", foreground="#a78bfa", background="#1e293b")
        self.txt_logs.tag_config("FOLDER", foreground="#22d3ee", background="#1e293b")
        self.txt_logs.tag_config("CLEAN", foreground="#34d399", background="#1e293b")
        self.txt_logs.tag_config("TRASH", foreground="#94a3b8", background="#1e293b")
        self.txt_logs.tag_config("SEARCH", foreground="#fbbf24", background="#78350f", font=("Consolas", 10, "bold"))
        self.txt_logs.tag_config("SEPARATOR", foreground="#475569", background="#1e293b")
        # Fin de configuración de tags


    def _build_sidebar(self):
        """Sidebar simplificado - solo info de vistazo."""
        pad = {"padx": 14, "pady": 10}
        
        # Header con Icono + Texto + Versión
        header_frame = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        header_frame.pack(fill="x", **pad)
        
        if self._app_icon_small:
            lbl_icon = ttk.Label(header_frame, image=self._app_icon_small, background="#f3f4f6")
            lbl_icon.pack(side="left", padx=(0, 8))
        
        # Contenedor para título y versión
        title_col = ttk.Frame(header_frame, style="Sidebar.TFrame")
        title_col.pack(side="left")
        
        ttk.Label(title_col, text="An-Zip-Watcher", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(title_col, text=f"v{__version__}", font=("Segoe UI", 9), foreground="#6b7280", background="#f3f4f6").pack(anchor="w")

        ttk.Separator(self.sidebar).pack(fill="x", padx=14, pady=(0, 10))

        self.side_state_emoji = tk.StringVar(value="🔴")
        self.side_state_text = tk.StringVar(value="Detenido")
        
        # Solo texto de estado (emoji removido por UX cleanup)
        tk.Label(self.sidebar, textvariable=self.side_state_text, background="#111827", foreground="#e5e7eb", font=("Segoe UI", 10, "bold"), anchor="w", padx=14, pady=10).pack(anchor="w")

        ttk.Separator(self.sidebar).pack(fill="x", padx=14, pady=(12, 10))

        # Contadores compactos
        ttk.Label(self.sidebar, text="Actividad:", background="#111827", foreground="#9ca3af", font=("Segoe UI", 9)).pack(anchor="w", padx=14)
        
        self.side_ok_count = tk.StringVar(value="✅ 0 procesados")
        self.side_warn_count = tk.StringVar(value="⚠️ 0 advertencias")
        self.side_error_count = tk.StringVar(value="❌ 0 errores")
        
        ttk.Label(self.sidebar, textvariable=self.side_ok_count, style="SidebarText.TLabel").pack(anchor="w", padx=14, pady=(4, 2))
        ttk.Label(self.sidebar, textvariable=self.side_warn_count, style="SidebarText.TLabel").pack(anchor="w", padx=14, pady=2)
        ttk.Label(self.sidebar, textvariable=self.side_error_count, style="SidebarText.TLabel").pack(anchor="w", padx=14, pady=2)
        
        # Spacer
        ttk.Frame(self.sidebar, style="Sidebar.TFrame").pack(fill="both", expand=True)
        
        # Versión al fondo
        ttk.Label(self.sidebar, text="v1.0.0", background="#111827", foreground="#6b7280", font=("Segoe UI", 8)).pack(side="bottom", pady=10)

    # ---------- Event Handlers
    def _on_resize(self, event):
        """Ajusta dinámicamente wraplength cuando se redimensiona."""
        if event.widget != self:
            return

    def _build_welcome_banner(self, parent):
        """Banner de bienvenida para primera ejecución."""
        banner = ttk.Frame(parent, style="WelcomeBanner.TFrame")
        banner.pack(fill="x", pady=(0, 14))
        self.banner_frame = banner
        
        content = ttk.Frame(banner, style="WelcomeBanner.TFrame")
        content.pack(fill="x", padx=16, pady=14)
        
        tk.Label(content, text="👋 ¡Bienvenido a ZIP Watcher!", background="#dbeafe", foreground="#1e40af", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(content, text="Para comenzar:", background="#dbeafe", foreground="#1e3a8a", font=("Segoe UI", 10)).pack(anchor="w", pady=(8, 4))
        
        steps = [
            "1️⃣ Selecciona la carpeta donde llegarán los archivos ZIP",
            "2️⃣ Haz clic en 'Guardar' para aplicar la configuración",
            "3️⃣ Presiona 'Iniciar' para activar la vigilancia"
        ]
        for step in steps:
            tk.Label(content, text=step, background="#dbeafe", foreground="#1e3a8a", font=("Segoe UI", 9)).pack(anchor="w", pady=1)
        
        btn_frame = ttk.Frame(content, style="WelcomeBanner.TFrame")
        btn_frame.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_frame, text="Seleccionar carpeta y comenzar →", command=self._quick_start, style="Primary.TButton").pack(side="left")
    
    def _quick_start(self):
        """Acción rápida del banner: abre explorador + guarda + oculta banner."""
        path = filedialog.askdirectory(title="Selecciona carpeta de vigilancia")
        if path:
            self.var_watch_dir.set(path)
            self.save_from_form()
            if self.banner_frame:
                self.banner_frame.destroy()
                self.banner_frame = None
    
    def toggle_advanced_config(self):
        """Toggle para mostrar/ocultar configuración avanzada."""
        is_expanded = self.advanced_expanded.get()
        
        if is_expanded:
            # Colapsar
            self.advanced_frame.pack_forget()
            self.adv_toggle_btn.configure(text="▶ Configuración avanzada (opcional)")
            self.advanced_expanded.set(False)
        else:
            # Expandir
            self.advanced_frame.pack(fill="x", pady=(6, 12), after=self.adv_toggle_btn.master)
            self.adv_toggle_btn.configure(text="▼ Configuración avanzada (opcional)")
            self.advanced_expanded.set(True)
        
        # Guardar estado
        self.settings["advanced_config_expanded"] = self.advanced_expanded.get()
        save_settings(self.settings)
    
    def _create_tooltip(self, widget, text):
        """Crea un tooltip simple para un widget."""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            label = tk.Label(tooltip, text=text, background="#fffbeb", foreground="#78350f", 
                           relief="solid", borderwidth=1, font=("Segoe UI", 9), padx=8, pady=4)
            label.pack()
            widget._tooltip = tooltip
        
        def on_leave(event):
            if hasattr(widget, '_tooltip'):
                widget._tooltip.destroy()
                del widget._tooltip
        
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    # ---------- Status helpers
    def _set_status(self, text: str, pill: str):
        self.status_text.set(text)
        self.sb_right.set(time.strftime("%Y-%m-%d %H:%M:%S"))

        status = pill.lower()
        if status == UIStatus.RUNNING.value:
            # Status pill
            self.status_pill_text.set("▶️ Vigilando")
            self.status_pill_label.configure(bg="#d1fae5", fg="#065f46")
            
            # Dashboard
            self.dash_state_emoji.set("🟢")
            self.dash_state_text.set("Activo")
            
            # Sidebar
            self.side_state_emoji.set("🟢")
            self.side_state_text.set("Activo")
            
        elif status == UIStatus.STOPPING.value:
            # Status pill
            self.status_pill_text.set("⏳ Deteniendo...")
            self.status_pill_label.configure(bg="#fef3c7", fg="#92400e")
            
            # Dashboard
            self.dash_state_emoji.set("🟡")
            self.dash_state_text.set("Deteniendo...")
            
            # Sidebar
            self.side_state_emoji.set("🟡")
            self.side_state_text.set("Deteniendo...")
            
        else:  # IDLE
            # Status pill
            self.status_pill_text.set("⏸️ Detenido")
            self.status_pill_label.configure(bg="#e5e7eb", fg="#374151")
            
            # Dashboard
            self.dash_state_emoji.set("🔴")
            self.dash_state_text.set("Detenido")
            
            # Sidebar
            self.side_state_emoji.set("🔴")
            self.side_state_text.set("Detenido")

    def _is_running(self) -> bool:
        return bool(
            (self._worker and self._worker.is_alive())
            or (self._processor and self._processor.is_alive())
        )

    def settings_getter(self):
        return dict(self.settings)

    def emit(self, level: str, msg: str):
        """Envía un evento de log a la cola (thread-safe)."""
        ev = LogEvent(level=level, msg=msg, ts=time.time())
        self._log_queue.put(ev)

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
        subdir_map = {
            "output": self.settings.get("output_subdir") or "output",
            "extracted": self.settings.get("extract_subdir") or "extracted",
            "processed": self.settings.get("processed_subdir") or "processed",
            "trash": self.settings.get("trash_subdir") or DEFAULT_TRASH_SUBDIR,
        }
        if key in subdir_map:
            return wd / subdir_map[key]
        return None

    def _get_all_paths(self) -> dict[str, Optional[Path]]:
        wd = self._watch_dir()
        if wd is None:
            return {"watch": None, "extracted": None, "output": None, "processed": None, "trash": None}
        return {
            "watch": wd,
            "extracted": wd / (self.settings.get("extract_subdir") or "extracted"),
            "output": wd / (self.settings.get("output_subdir") or "output"),
            "processed": wd / (self.settings.get("processed_subdir") or "processed"),
            "trash": wd / (self.settings.get("trash_subdir") or DEFAULT_TRASH_SUBDIR),
        }

    def _refresh_paths_display(self):
        paths = self._get_all_paths()

        if paths["watch"] is None:
            self.dash_watch.set("(sin configurar)")
            return

        # Dashboard solo muestra la carpeta principal
        self.dash_watch.set(str(paths["watch"]))

    # Compat: antes llamabas a _refresh_dashboard_paths, ahora lo mapeamos
    def _refresh_dashboard_paths(self):
        self._refresh_paths_display()

    # ---------- Config load/save
    def _load_to_form(self):
        self.var_watch_dir.set(self.settings.get("watch_dir", ""))
        self.var_poll.set(str(self.settings.get("poll_settle_seconds", 1.0)))
        self.var_tries.set(str(self.settings.get("max_settle_tries", 30)))
        self.var_scan.set(str(self.settings.get("scan_interval_seconds", 0.5)))
        self._refresh_paths_display()

    def browse_folder(self):
        path = filedialog.askdirectory(title="Selecciona carpeta de escucha")
        if path:
            self.var_watch_dir.set(path)

    def _validate_form(self) -> tuple[bool, str]:
        watch_dir = (self.var_watch_dir.get() or "").strip()
        if not watch_dir:
            return False, "Por favor, selecciona una carpeta para comenzar a vigilar archivos."

        try:
            path = Path(watch_dir).expanduser().resolve()
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except PermissionError:
                    return False, f"No tienes permisos para crear o acceder a: {path}"
        except Exception as e:
            return False, f"Ruta inválida: {e}"

        try:
            poll = float(self.var_poll.get().strip())
            tries = int(self.var_tries.get().strip())
            scan = float(self.var_scan.get().strip())
            if poll <= 0:
                return False, "El tiempo de espera debe ser mayor a 0 segundos."
            if tries <= 0:
                return False, "Los intentos máximos deben ser mayores a 0."
            if scan < MIN_SCAN_INTERVAL:
                return False, f"La frecuencia de escaneo no puede ser menor a {MIN_SCAN_INTERVAL} segundos."
        except ValueError as e:
            return False, f"Parámetros inválidos (se esperan números): {e}"
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
        self._refresh_paths_display()
        self.emit("OK", f"Configuración guardada en {SETTINGS_PATH}")
        status = UIStatus.RUNNING.value if self._is_running() else UIStatus.IDLE.value
        self._set_status("Configuración guardada", status)

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
        self._worker = WatcherThread(self.settings_getter, self.emit, self._stop_event, self._zip_queue)
        self._processor = ZipProcessorThread(self.settings_getter, self.emit, self._stop_event, self._zip_queue)
        self._worker.start()
        self._processor.start()

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        self._set_maintenance_enabled(False)

        self._set_status("En ejecución", UIStatus.RUNNING.value)
        self.emit("START", "Monitorización activa.")

    def stop_watcher(self):
        if not self._is_running():
            return
        self._stop_event.set()
        self._drain_zip_queue()
        self._set_status("Deteniendo…", UIStatus.STOPPING.value)
        self.btn_stop.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self._set_maintenance_enabled(False)
        self.after(150, self._join_worker)

    def _join_worker(self):
        if (self._worker and self._worker.is_alive()) or (self._processor and self._processor.is_alive()):
            self.after(150, self._join_worker)
            return

        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._set_maintenance_enabled(True)
        self._set_status("Parado", UIStatus.IDLE.value)
        self.emit("STOP", "Watcher parado.")

    def _drain_zip_queue(self):
        drained = 0
        try:
            while True:
                self._zip_queue.get_nowait()
                self._zip_queue.task_done()
                drained += 1
        except queue.Empty:
            pass
        if drained:
            self.emit("INFO", f"Cola de ZIPs vaciada ({drained}).")

    def _shutdown_threads(self):
        self._stop_event.set()
        self._drain_zip_queue()
        for thread in (self._worker, self._processor):
            if thread and thread.is_alive():
                thread.join(timeout=2)

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

    def switch_log_tab(self, tab_name: str):
        """Cambia entre pestañas de logs."""
        self.current_log_tab.set(tab_name)
        
        # Actualizar estilos de botones
        if tab_name == "todos":
            self.tab_todos.configure(bg="#3b82f6", fg="white", font=("Segoe UI", 9, "bold"))
            self.tab_problemas.configure(bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9))
            self.tab_buscar.configure(bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9))
            
            # Mostrar todos los niveles
            self.filter_info.set(True)
            self.filter_ok.set(True)
            self.filter_warn.set(True)
            self.filter_error.set(True)
            
            # Ocultar búsqueda
            self.search_frame.pack_forget()
            
        elif tab_name == "problemas":
            self.tab_todos.configure(bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9))
            self.tab_problemas.configure(bg="#3b82f6", fg="white", font=("Segoe UI", 9, "bold"))
            self.tab_buscar.configure(bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9))
            
            # Mostrar solo WARN y ERROR
            self.filter_info.set(False)
            self.filter_ok.set(False)
            self.filter_warn.set(True)
            self.filter_error.set(True)
            
            # Ocultar búsqueda
            self.search_frame.pack_forget()
            
        elif tab_name == "buscar":
            self.tab_todos.configure(bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9))
            self.tab_problemas.configure(bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9))
            self.tab_buscar.configure(bg="#3b82f6", fg="white", font=("Segoe UI", 9, "bold"))
            
            # Mostrar búsqueda
            self.search_frame.pack(fill="x", pady=(0, 10))
            self.search_var.set("")  # Limpiar búsqueda anterior
            
        self.refresh_logs_view()
    
    def clear_search(self):
        """Limpia la búsqueda y vuelve a mostrar todos los logs."""
        self.search_var.set("")
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

        trash.mkdir(parents=True, exist_ok=True)

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
        self._refresh_processed_events_status(show_dialog=False)

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

        trash.mkdir(parents=True, exist_ok=True)

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
        self._refresh_processed_events_status(show_dialog=False)

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
        self._refresh_processed_events_status(show_dialog=False)

    # ========= Logs UI =========

    def _bucket_for_level(self, level: str) -> str:
        return COUNT_BUCKET.get(level.upper(), "INFO")

    def _adjust_counts_for_event(self, ev: LogEvent, delta: int):
        bucket = self._bucket_for_level(ev.level)
        if bucket == "INFO":
            self._count_info += delta
        elif bucket == "OK":
            self._count_ok += delta
        elif bucket == "WARN":
            self._count_warn += delta
        elif bucket == "ERROR":
            self._count_error += delta

    def clear_logs_only(self):
        # Limpia UI + store + counters (NO toca filesystem)
        self._log_store.clear()
        self._count_info = self._count_ok = self._count_warn = self._count_error = 0
        self._update_counts_label()

        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.configure(state="disabled")

        self._append_log_direct("SEARCH", "Logs limpiados (solo UI).")



    def copy_logs(self):
        """Copia los logs al portapapeles con formato."""
        self.txt_logs.configure(state="normal")
        text = self.txt_logs.get("1.0", "end-1c")
        self.txt_logs.configure(state="disabled")

        if not text.strip():
            messagebox.showwarning("Sin logs", "No hay logs para copiar.")
            return

        self.clipboard_clear()
        self.clipboard_append(text)

        lines = len(text.split('\n'))
        self.emit("OK", f"Logs copiados al portapapeles ({lines} líneas).")

    def export_logs(self):
        """Exporta los logs a un archivo con encabezado informativo."""
        path = filedialog.asksaveasfilename(
            title="Exportar logs",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            self.txt_logs.configure(state="normal")
            text = self.txt_logs.get("1.0", "end-1c")
            self.txt_logs.configure(state="disabled")

            header = f"""
================================================================================
                         ZIP WATCHER - REPORTE DE LOGS
================================================================================
Fecha:      {time.strftime("%Y-%m-%d %H:%M:%S")}
Aplicación: ZIP Watcher v2.0
Directorio: {self.settings.get('watch_dir', 'N/A')}
================================================================================

"""

            summary = f"""
RESUMEN:
  - INFO:   {self._count_info:5} eventos
  - OK:     {self._count_ok:5} eventos
  - WARN:   {self._count_warn:5} eventos
  - ERROR:  {self._count_error:5} eventos
  - Total:  {sum([self._count_info, self._count_ok, self._count_warn, self._count_error]):5} eventos

LOG DETALLADO:
================================================================================

"""

            content = header + summary + text + "\n\n" + "=" * 80 + "\nFin del reporte\n"
            Path(path).write_text(content, encoding="utf-8")
            self.emit("OK", f"Logs exportados a {path}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar: {e}")
            self.emit("ERROR", f"Error exportando logs: {e}")

    def search_logs(self):
        q = (self.search_var.get() or "").strip().lower()
        if not q:
            self.refresh_logs_view()
            return

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

    # ========== Gestión de Tabla de Eventos Procesados ==========
    
    def add_processed_event(self, zip_name: str, result: str, output_path: str = ""):
        """Registra un evento de procesamiento en la tabla."""
        self._event_counter += 1
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        event_id = f"#{self._event_counter:04d}"
        
        # Guardar en memoria
        event_data = {
            "id": event_id,
            "timestamp": timestamp,
            "zip": zip_name,
            "result": result,
            "output": output_path
        }
        self._processed_events.append(event_data)
        self._update_status_cache(output_path, result)
        
        # Insertar en la tabla (al inicio para mostrar los más recientes primero)
        self.events_tree.insert("", 0, values=(
            event_id,
            timestamp,
            zip_name,
            result,
            output_path if output_path else "N/A"
        ))
        
        # Aplicar color según resultado
        item = self.events_tree.get_children()[0]
        if "✅" in result or "ÉXITO" in result.upper():
            self.events_tree.item(item, tags=("success",))
        elif "⚠" in result or "WARN" in result.upper():
            self.events_tree.item(item, tags=("warning",))
        elif "❌" in result or "ERROR" in result.upper():
            self.events_tree.item(item, tags=("error",))
        
        # Configurar colores de tags
        self.events_tree.tag_configure("success", foreground="#059669")
        self.events_tree.tag_configure("warning", foreground="#d97706")
        self.events_tree.tag_configure("error", foreground="#dc2626")

    def _update_status_cache(self, output_path: str, result: str) -> None:
        if not output_path or output_path == "N/A":
            return
        status = None
        if "TRASH" in result:
            status = "TRASH"
        elif "MISSING" in result:
            status = "MISSING"
        elif "✅" in result or "ÉXITO" in result.upper():
            status = "OK"
        if status:
            self._processed_status_cache[output_path] = status
    
    def clear_events_table(self):
        """Limpia la tabla de eventos."""
        if not messagebox.askyesno("Confirmar", "¿Limpiar todos los eventos procesados?"):
            return
        
        for item in self.events_tree.get_children():
            self.events_tree.delete(item)
        
        self._processed_events.clear()
        self._processed_status_cache.clear()
        self._event_counter = 0
        self.emit("INFO", "Tabla de eventos limpiada.")
    
    def _on_event_double_click(self, event):
        """Maneja el doble click en la tabla para abrir carpeta de salida."""
        selection = self.events_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        values = self.events_tree.item(item, "values")
        
        if len(values) >= 5:
            output_path = values[4]  # Columna "output"
            
            if output_path and output_path != "N/A":
                try:
                    # Abrir carpeta padre del archivo
                    folder = Path(output_path).parent
                    if folder.exists():
                        import os
                        os.startfile(str(folder))
                    else:
                        messagebox.showwarning("Carpeta no encontrada", f"La ruta no existe:\n{folder}")
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")

    def _refresh_processed_events_status(self, show_dialog: bool) -> int:
        """Actualiza el estado de eventos procesados (trash/missing) como histórico lineal."""
        trash_dir = self._dir("trash")
        changes_count = 0

        for item in self.events_tree.get_children():
            values = self.events_tree.item(item, "values")
            if len(values) < 5:
                continue

            current_status = values[3]
            output_path = values[4]
            zip_name = values[2]

            # Solo verificar si tiene un path válido y no ha fallado previamente
            if output_path and output_path != "N/A" and "ERROR" not in current_status:
                path = Path(output_path)

                new_status = "OK"

                if not path.exists():
                    # El archivo no está donde debería. Buscar en Trash (recursivo).
                    is_in_trash = False
                    if trash_dir and trash_dir.exists():
                        for t_file in trash_dir.rglob(path.name):
                            if t_file.is_file() and t_file.name == path.name:
                                is_in_trash = True
                                break

                    if is_in_trash:
                        new_status = "TRASH"
                    else:
                        new_status = "MISSING"

                previous_status = self._processed_status_cache.get(output_path)
                if new_status != "OK" and new_status != previous_status:
                    label = "🗑️ TRASH" if new_status == "TRASH" else "👻 MISSING"
                    self.add_processed_event(zip_name, label, output_path)
                    changes_count += 1

                self._processed_status_cache[output_path] = new_status

        if show_dialog:
            if changes_count > 0:
                messagebox.showinfo(
                    "Verificación",
                    f"Se actualizaron {changes_count} eventos.\nAlgunos archivos han sido movidos a la papelera o eliminados."
                )
            else:
                messagebox.showinfo("Verificación", "Todos los archivos verificados están accesibles.")

        return changes_count

    def _maybe_refresh_processed_events(self):
        if not self._processed_events:
            return
        now = time.time()
        if now - self._last_events_refresh >= self._events_refresh_interval:
            self._refresh_processed_events_status(show_dialog=False)
            self._last_events_refresh = now

    def verify_missing_files(self):
        """Verifica si los archivos de salida existen o si han sido movidos a trash/borrados."""
        self._refresh_processed_events_status(show_dialog=True)

    # ========== Gestión de Sesiones ==========
    
    def save_session(self, filename: Path = None):
        """Guarda la sesión actual (eventos + logs) en un archivo JSON."""
        if filename is None:
            filename = AUTO_SESSION_FILE
        
        try:
            # Convertir eventos a formato serializable
            events_data = [
                {
                    "id": ev["id"],
                    "timestamp": ev["timestamp"],
                    "zip": ev["zip"],
                    "result": ev["result"],
                    "output": ev["output"]
                }
                for ev in self._processed_events
            ]
            
            # Convertir logs a formato serializable
            logs_data = [
                {
                    "level": log.level,
                    "msg": log.msg,
                    "timestamp": log.ts
                }
                for log in self._log_store
            ]
            
            session_data = {
                "version": "2.0",
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "watch_dir": self.settings.get("watch_dir", ""),
                "event_counter": self._event_counter,
                "events": events_data,
                "status_cache": self._processed_status_cache,
                "logs": logs_data,
                "counters": {
                    "info": self._count_info,
                    "ok": self._count_ok,
                    "warn": self._count_warn,
                    "error": self._count_error
                }
            }
            
            filename.parent.mkdir(parents=True, exist_ok=True)
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            self.emit("ERROR", f"Error guardando sesión: {e}")
            return False
    
    def load_session(self, filename: Path):
        """Carga una sesión desde un archivo JSON."""
        try:
            if not filename.exists():
                return False
            
            with open(filename, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            # Restaurar contador de eventos
            self._event_counter = session_data.get("event_counter", 0)
            
            # Restaurar eventos procesados
            self._processed_events.clear()
            for item in self.events_tree.get_children():
                self.events_tree.delete(item)

            for ev_data in session_data.get("events", []):
                self._processed_events.append(ev_data)
                self.events_tree.insert("", "end", values=(
                    ev_data["id"],
                    ev_data["timestamp"],
                    ev_data["zip"],
                    ev_data["result"],
                    ev_data.get("output", "N/A")
                ))
                
                # Aplicar colores
                item = self.events_tree.get_children()[-1]
                result = ev_data["result"]
                if "✅" in result:
                    self.events_tree.item(item, tags=("success",))
                elif "⚠" in result:
                    self.events_tree.item(item, tags=("warning",))
                elif "❌" in result:
                    self.events_tree.item(item, tags=("error",))
            
            # Configurar tags de color
            self.events_tree.tag_configure("success", foreground="#059669")
            self.events_tree.tag_configure("warning", foreground="#d97706")
            self.events_tree.tag_configure("error", foreground="#dc2626")

            self._processed_status_cache = session_data.get("status_cache", {})
            if not self._processed_status_cache:
                for ev in self._processed_events:
                    self._update_status_cache(ev.get("output", ""), ev.get("result", ""))
            
            # Restaurar contadores
            counters = session_data.get("counters", {})
            self._count_info = counters.get("info", 0)
            self._count_ok = counters.get("ok", 0)
            self._count_warn = counters.get("warn", 0)
            self._count_error = counters.get("error", 0)
            self._update_counts_label()
            
            # Restaurar logs (opcional, puede ser pesado)
            # Los logs se reconstruirán naturalmente con nuevos eventos
            
            self.emit("INFO", f"Sesión cargada: {session_data.get('saved_at', 'desconocida')}")
            self._refresh_processed_events_status(show_dialog=False)
            return True
            
        except Exception as e:
            self.emit("ERROR", f"Error cargando sesión: {e}")
            return False
    
    def export_session(self):
        """Exporta la sesión actual a un archivo elegido por el usuario."""
        default_name = f"session_{time.strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = filedialog.asksaveasfilename(
            title="Exportar Sesión",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(SESSIONS_DIR),
            initialfile=default_name
        )
        
        if filepath:
            if self.save_session(Path(filepath)):
                messagebox.showinfo("Exportado", f"Sesión exportada a:\n{filepath}")
                self.emit("OK", f"Sesión exportada: {filepath}")
    
    def import_session(self):
        """Importa una sesión desde un archivo elegido por el usuario."""
        filepath = filedialog.askopenfilename(
            title="Importar Sesión",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(SESSIONS_DIR)
        )
        
        if filepath:
            if messagebox.askyesno("Confirmar", "¿Reemplazar la sesión actual con la importada?\nSe perderán los datos actuales no guardados."):
                if self.load_session(Path(filepath)):
                    messagebox.showinfo("Importado", "Sesión importada correctamente.")
                else:
                    messagebox.showerror("Error", "No se pudo importar la sesión.")

    # ---------- Log pump + rendering (BATCH)
    def _tick_logs(self):
        drained: list[LogEvent] = []
        try:
            while True:
                drained.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass

        if drained:
            self._handle_log_events_batch(drained)

        self._maybe_refresh_processed_events()
        self.after(120, self._tick_logs)

    def _handle_log_events_batch(self, events: list[LogEvent]):
        visible_events: list[LogEvent] = []

        for ev in events:
            was_full = (len(self._log_store) == self._log_store.maxlen)
            expelled = self._log_store[0] if was_full and len(self._log_store) > 0 else None

            self._log_store.append(ev)

            if expelled is not None:
                self._adjust_counts_for_event(expelled, -1)
            self._adjust_counts_for_event(ev, +1)

            if self._level_visible(ev.level):
                visible_events.append(ev)
            
            # Detectar eventos de procesamiento de ZIP (usando variables de instancia)
            if ev.level == "ZIP" and "Detectado ZIP:" in ev.msg:
                # Extraer nombre del ZIP
                self._current_processing_zip = ev.msg.split("Detectado ZIP:")[-1].strip()
                self._current_zip_output = None  # Reset output
            
            elif self._current_processing_zip and ev.level == "OK" and "Creado ZIP:" in ev.msg:
                # Extraer ruta del output
                zip_output_name = ev.msg.split("Creado ZIP:")[-1].strip()
                # Construir ruta completa
                wd = self._watch_dir()
                if wd:
                    output_dir = wd / (self.settings.get("output_subdir") or "output")
                    self._current_zip_output = str(output_dir / zip_output_name)
                else:
                    self._current_zip_output = zip_output_name
            
            elif self._current_processing_zip and ev.level == "OK" and "Original movido a:" in ev.msg:
                # Proceso completado exitosamente
                self.add_processed_event(
                    self._current_processing_zip, 
                    "✅ ÉXITO", 
                    self._current_zip_output if self._current_zip_output else ""
                )
                self._current_processing_zip = None
                self._current_zip_output = None
            
            elif self._current_processing_zip and ev.level == "ERROR":
                # Error durante el procesamiento
                error_msg = ev.msg[:50] + "..." if len(ev.msg) > 50 else ev.msg
                self.add_processed_event(self._current_processing_zip, f"❌ ERROR: {error_msg}", "")
                self._current_processing_zip = None
                self._current_zip_output = None
            
            elif self._current_processing_zip and ev.level == "WARN" and ("ZIP corrupto" in ev.msg or "ZIP no válido" in ev.msg or "No hay carpetas" in ev.msg):
                # Advertencia crítica que detiene el proceso
                warn_msg = ev.msg[:50] + "..." if len(ev.msg) > 50 else ev.msg
                self.add_processed_event(self._current_processing_zip, f"⚠️ ADVERTENCIA: {warn_msg}", "")
                self._current_processing_zip = None
                self._current_zip_output = None

        self._update_counts_label()
        self._refresh_dashboard_paths()
        self.sb_right.set(time.strftime("%Y-%m-%d %H:%M:%S"))

        if visible_events:
            self._append_logs_to_text_batch(visible_events)

    def _is_user_at_bottom(self) -> bool:
        first, last = self.txt_logs.yview()
        return last > 0.98

    def _append_logs_to_text_batch(self, events: list[LogEvent]):
        auto_scroll = self._is_user_at_bottom()

        self.txt_logs.configure(state="normal")
        for ev in events:
            ts = time.strftime("%H:%M:%S", time.localtime(ev.ts))
            lvl = ev.level.upper()
            line = f"[{ts}] {lvl:8} | {ev.msg}\n"

            start = self.txt_logs.index("end-1c")
            self.txt_logs.insert("end", line)
            end = self.txt_logs.index("end-1c")

            tag = lvl if lvl in LEVEL_EMOJI else "INFO"
            self.txt_logs.tag_add(tag, start, end)

        if auto_scroll:
            self.txt_logs.see("end")

        self.txt_logs.configure(state="disabled")

    def _update_counts_label(self):
        # Dashboard
        self.counts_var.set(
            f"✅ Procesados: {self._count_ok}  |  ⚠️ Advertencias: {self._count_warn}  |  ❌ Errores: {self._count_error}"
        )
        
        # Sidebar
        self.side_ok_count.set(f"✅ {self._count_ok} procesados")
        self.side_warn_count.set(f"⚠️ {self._count_warn} advertencias")
        self.side_error_count.set(f"❌ {self._count_error} errores")

    def _append_log_to_text(self, ev: LogEvent):
        # Para refresh/search (menos frecuente). El batch es para el flujo normal.
        ts = time.strftime("%H:%M:%S", time.localtime(ev.ts))
        lvl = ev.level.upper()
        line = f"[{ts}] {lvl:8} | {ev.msg}\n"

        auto_scroll = self._is_user_at_bottom()

        self.txt_logs.configure(state="normal")
        start = self.txt_logs.index("end-1c")
        self.txt_logs.insert("end", line)
        end = self.txt_logs.index("end-1c")

        tag = lvl if lvl in LEVEL_EMOJI else "INFO"
        self.txt_logs.tag_add(tag, start, end)
        if auto_scroll:
            self.txt_logs.see("end")
        self.txt_logs.configure(state="disabled")

    def _append_log_direct(self, level: str, msg: str):
        # Inserta sin store/counters (para acciones UI)
        ts = time.strftime("%H:%M:%S")
        lvl = level.upper()
        line = f"{ts} {emoji(lvl)} [{lvl}] {msg}\n"

        auto_scroll = self._is_user_at_bottom()

        self.txt_logs.configure(state="normal")
        start = self.txt_logs.index("end-1c")
        self.txt_logs.insert("end", line)
        end = self.txt_logs.index("end-1c")
        tag = lvl if lvl in LEVEL_EMOJI else "INFO"
        self.txt_logs.tag_add(tag, start, end)
        if auto_scroll:
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



    # ---------- Close
    def on_close(self):
        if self._is_running():
            if not messagebox.askyesno("Salir", "El watcher está en ejecución. ¿Parar y salir?"):
                return
            self._shutdown_threads()
        
        # Guardar sesión automáticamente antes de cerrar
        self.save_session()
        self.destroy()


if __name__ == "__main__":
    app = ZipWatcherApp()
    app.mainloop()
