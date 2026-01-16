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

DEFAULT_SETTINGS = {
    "watch_dir": "",
    "extract_subdir": DEFAULT_EXTRACT_SUBDIR,
    "output_subdir": DEFAULT_OUTPUT_SUBDIR,
    "processed_subdir": DEFAULT_PROCESSED_SUBDIR,
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
    def __init__(self, settings_getter: Callable[[], dict], emit: EmitFunc, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.settings_getter = settings_getter
        self.emit = emit
        self.stop_event = stop_event
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
                            process_zip(p, watch_dir, settings, self.emit)
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

        # store para logs (LIMITADO con deque)
        self._max_log_store = int(self.settings.get("max_log_store", DEFAULT_MAX_LOG_STORE))
        self._log_store: deque[LogEvent] = deque(maxlen=self._max_log_store)

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

        # Status pill (mejorado con icono y color)
        self.status_text = tk.StringVar(value="Listo")
        self.status_pill_text = tk.StringVar(value="⏸️ Detenido")
        status_frame = ttk.Frame(toolbar, style="Toolbar.TFrame")
        status_frame.pack(side="right", padx=14, pady=10)
        
        # Pill con fondo de color
        self.status_pill_label = tk.Label(
            status_frame, 
            textvariable=self.status_pill_text, 
            bg="#e5e7eb", 
            fg="#374151",
            font=("Segoe UI", 9, "bold"),
            padx=10, 
            pady=4,
            relief="flat"
        )
        self.status_pill_label.pack(side="right")
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

        # -------- Banner de bienvenida (solo si watch_dir vacío)
        self.banner_frame = None
        if not self.settings.get("watch_dir", "").strip():
            self._build_welcome_banner(left_col)

        # -------- Dashboard card (left top) - SIMPLIFICADO con mejor spacing
        self.card_dash = ttk.Frame(left_col, style="Card.TFrame")
        self.card_dash.pack(fill="x", pady=(0 if self.banner_frame else 0, 0))

        dash = ttk.Frame(self.card_dash, style="Card.TFrame")
        dash.pack(fill="x", padx=18, pady=18)

        ttk.Label(dash, text="Estado del Monitor", style="H1.TLabel").pack(anchor="w")
        ttk.Label(dash, text="Vista general de la vigilancia.", style="Muted.TLabel").pack(anchor="w", pady=(4, 16))

        # Estado visual con emoji
        state_frame = ttk.Frame(dash, style="Card.TFrame")
        state_frame.pack(fill="x", pady=(0, 14))
        
        self.dash_state_emoji = tk.StringVar(value="🔴")
        self.dash_state_text = tk.StringVar(value="Detenido")
        
        tk.Label(state_frame, textvariable=self.dash_state_emoji, background="#ffffff", font=("Segoe UI", 18)).pack(side="left")
        tk.Label(state_frame, textvariable=self.dash_state_text, background="#ffffff", foreground="#111827", font=("Segoe UI", 14, "bold")).pack(side="left", padx=(10, 0))

        # Carpeta vigilada
        ttk.Label(dash, text="📁 Carpeta vigilada", background="#ffffff", foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))
        self.dash_watch = tk.StringVar(value="(sin configurar)")
        ttk.Label(dash, textvariable=self.dash_watch, background="#ffffff", foreground="#374151", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))

        # Contadores reorganizados
        ttk.Label(dash, text="📊 Actividad", background="#ffffff", foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))
        self.counts_var = tk.StringVar(value="✅ Procesados: 0  |  ⚠️ Advertencias: 0  |  ❌ Errores: 0")
        ttk.Label(dash, textvariable=self.counts_var, background="#ffffff", foreground="#111827", font=("Segoe UI", 10)).pack(anchor="w")

        # -------- Config card (left bottom) con mejor spacing
        self.card_config = ttk.Frame(left_col, style="Card.TFrame")
        self.card_config.pack(fill="both", expand=True, pady=(16, 0))

        cfg = ttk.Frame(self.card_config, style="Card.TFrame")
        cfg.pack(fill="both", expand=True, padx=18, pady=18)

        ttk.Label(cfg, text="Configuración", style="H1.TLabel").pack(anchor="w")
        ttk.Label(cfg, text="Carpeta de vigilancia y opciones.", style="Muted.TLabel").pack(anchor="w", pady=(4, 12))

        self.var_watch_dir = tk.StringVar()
        self.var_poll = tk.StringVar()
        self.var_tries = tk.StringVar()
        self.var_scan = tk.StringVar()

        ttk.Label(cfg, text="Carpeta de vigilancia", background="#ffffff", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        row = ttk.Frame(cfg, style="Card.TFrame")
        row.pack(fill="x", pady=(4, 10))
        ttk.Entry(row, textvariable=self.var_watch_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Explorar...", command=self.browse_folder).pack(side="left", padx=(8, 0))

        # Configuración avanzada (colapsable)
        self.advanced_expanded = tk.BooleanVar(value=self.settings.get("advanced_config_expanded", False))
        
        adv_toggle = ttk.Frame(cfg, style="Card.TFrame")
        adv_toggle.pack(fill="x", pady=(10, 6))
        
        self.adv_toggle_btn = ttk.Button(
            adv_toggle, 
            text="▼ Configuración avanzada (opcional)" if self.advanced_expanded.get() else "▶ Configuración avanzada (opcional)",
            command=self.toggle_advanced_config,
            style="Ghost.TButton"
        )
        self.adv_toggle_btn.pack(anchor="w")

        # Frame para configuración avanzada
        self.advanced_frame = ttk.Frame(cfg, style="Card.TFrame")
        if self.advanced_expanded.get():
            self.advanced_frame.pack(fill="x", pady=(6, 12))

        def field(parent, label, var, tooltip=""):
            f = ttk.Frame(parent, style="Card.TFrame")
            label_widget = ttk.Label(f, text=label, background="#ffffff")
            label_widget.pack(anchor="w")
            # Tooltip simple (se puede mejorar con biblioteca externa)
            if tooltip:
                self._create_tooltip(label_widget, tooltip)
            ttk.Entry(f, textvariable=var, width=20).pack(anchor="w", pady=(4, 0))
            return f

        field(self.advanced_frame, "Tiempo de espera (seg)", self.var_poll, 
              "Segundos que espera para verificar que el archivo terminó de copiarse").grid(row=0, column=0, sticky="w", padx=(0, 18), pady=4)
        field(self.advanced_frame, "Intentos máximos", self.var_tries,
              "Cuántas veces verificar antes de considerar el archivo estable").grid(row=0, column=1, sticky="w", padx=(0, 18), pady=4)
        field(self.advanced_frame, "Frecuencia de escaneo (seg)", self.var_scan,
              "Cada cuántos segundos revisar la carpeta (mínimo: 0.2)").grid(row=0, column=2, sticky="w", pady=4)

        # -------- Activity / Maintenance card (right)
        self.card_activity = ttk.Frame(right_col, style="Card.TFrame")
        self.card_activity.pack(fill="both", expand=True)

        act = ttk.Frame(self.card_activity, style="Card.TFrame")
        act.pack(fill="both", expand=True, padx=14, pady=14)

        top = ttk.Frame(act, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Actividad y mantenimiento", style="H1.TLabel").pack(side="left")

        # Botones de mantenimiento con mejor spacing
        ttk.Label(act, text="🧹 Mantenimiento", background="#ffffff", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 6))
        ttk.Label(act, text="Limpia carpetas individuales:", background="#ffffff", foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))
        
        maintenance_row1 = ttk.Frame(act, style="Card.TFrame")
        maintenance_row1.pack(fill="x", pady=(0, 10))

        self.btn_clean_processed = ttk.Button(maintenance_row1, text="Processed", command=lambda: self.clean_dir_to_trash("processed"))
        self.btn_clean_processed.pack(side="left", padx=(0, 6))

        self.btn_clean_extracted = ttk.Button(maintenance_row1, text="Extracted", command=lambda: self.clean_dir_to_trash("extracted"))
        self.btn_clean_extracted.pack(side="left", padx=(0, 6))

        self.btn_clean_output = ttk.Button(maintenance_row1, text="Output", command=lambda: self.clean_dir_to_trash("output"))
        self.btn_clean_output.pack(side="left", padx=(0, 6))

        ttk.Separator(act, orient="horizontal").pack(fill="x", pady=10)
        
        ttk.Label(act, text="Acciones globales:", background="#ffffff", foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))
        self.btn_clean_all = ttk.Button(act, text="🧹 Limpiar todo → Papelera", command=self.clean_all_to_trash)
        self.btn_clean_all.pack(anchor="w", pady=(0, 10))
        
        ttk.Separator(act, orient="horizontal").pack(fill="x", pady=10)
        
        ttk.Label(act, text="⚠️ Zona de peligro:", background="#ffffff", foreground="#dc2626", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self.btn_empty_trash = ttk.Button(act, text="🗑️ Vaciar papelera definitivamente", command=self.empty_trash, style="Danger.TButton")
        self.btn_empty_trash.pack(anchor="w", pady=(0, 16))

        # SISTEMA DE PESTAÑAS para logs
        ttk.Label(act, text="📋 Logs", background="#ffffff", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        
        # Tabs
        tabs_frame = ttk.Frame(act, style="Card.TFrame")
        tabs_frame.pack(fill="x", pady=(0, 10))
        
        self.current_log_tab = tk.StringVar(value="todos")
        
        # Variables de filtro (se mantienen para compatibilidad)
        self.filter_info = tk.BooleanVar(value=True)
        self.filter_ok = tk.BooleanVar(value=True)
        self.filter_warn = tk.BooleanVar(value=True)
        self.filter_error = tk.BooleanVar(value=True)
        
        # Tab buttons
        self.tab_todos = tk.Button(
            tabs_frame, 
            text="Todos", 
            command=lambda: self.switch_log_tab("todos"),
            bg="#3b82f6", 
            fg="white",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2"
        )
        self.tab_todos.pack(side="left", padx=(0, 4))
        
        self.tab_problemas = tk.Button(
            tabs_frame, 
            text="Solo problemas", 
            command=lambda: self.switch_log_tab("problemas"),
            bg="#e5e7eb", 
            fg="#374151",
            font=("Segoe UI", 9),
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2"
        )
        self.tab_problemas.pack(side="left", padx=(0, 4))
        
        self.tab_buscar = tk.Button(
            tabs_frame, 
            text="Buscar", 
            command=lambda: self.switch_log_tab("buscar"),
            bg="#e5e7eb", 
            fg="#374151",
            font=("Segoe UI", 9),
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2"
        )
        self.tab_buscar.pack(side="left")
        
        # Controles según tab activo
        self.tab_content_frame = ttk.Frame(act, style="Card.TFrame")
        self.tab_content_frame.pack(fill="x", pady=(0, 10))
        
        # Frame para búsqueda (oculto por defecto)
        self.search_frame = ttk.Frame(self.tab_content_frame, style="Card.TFrame")
        self.search_var = tk.StringVar(value="")
        ttk.Entry(self.search_frame, textvariable=self.search_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(self.search_frame, text="🔎 Buscar", command=self.search_logs).pack(side="left", padx=(0, 4))
        ttk.Button(self.search_frame, text="Limpiar", command=self.clear_search).pack(side="left")
        
        # Botones de acción (siempre visibles)
        actions_frame = ttk.Frame(act, style="Card.TFrame")
        actions_frame.pack(fill="x", pady=(0, 10))
        
        self.btn_clear_logs = ttk.Button(actions_frame, text="🧽 Limpiar", command=self.clear_logs_only)
        self.btn_clear_logs.pack(side="left", padx=(0, 6))

        self.btn_copy_logs = ttk.Button(actions_frame, text="📋 Copiar", command=self.copy_logs)
        self.btn_copy_logs.pack(side="left", padx=(0, 6))

        self.btn_export_logs = ttk.Button(actions_frame, text="💾 Exportar", command=self.export_logs)
        self.btn_export_logs.pack(side="left")

        # Split: logs + recent events
        split = ttk.PanedWindow(act, orient="vertical")
        split.pack(fill="both", expand=True)

        logs_frame = ttk.Frame(split, style="Card.TFrame")

        scrollbar_y = ttk.Scrollbar(logs_frame)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x = ttk.Scrollbar(logs_frame, orient="horizontal")
        scrollbar_x.pack(side="bottom", fill="x")

        self.txt_logs = tk.Text(
            logs_frame,
            height=16,
            wrap="none",
            bg="#0b1220",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            padx=10,
            pady=8,
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
            font=("Courier New", 10)
        )
        self.txt_logs.pack(side="left", fill="both", expand=True)
        self.txt_logs.configure(state="disabled")

        scrollbar_y.config(command=self.txt_logs.yview)
        scrollbar_x.config(command=self.txt_logs.xview)

        # Tags
        self.txt_logs.tag_config("INFO", foreground="#60a5fa", background="#0f172a")
        self.txt_logs.tag_config("OK", foreground="#4ade80", background="#0b4620")
        self.txt_logs.tag_config("WARN", foreground="#facc15", background="#4a3c0a")
        self.txt_logs.tag_config("ERROR", foreground="#f87171", background="#7f1d1d")
        self.txt_logs.tag_config("START", foreground="#4ade80", background="#0b4620", font=("Courier New", 10, "bold"))
        self.txt_logs.tag_config("STOP", foreground="#f87171", background="#7f1d1d", font=("Courier New", 10, "bold"))
        self.txt_logs.tag_config("ZIP", foreground="#a78bfa", background="#1e1b4b")
        self.txt_logs.tag_config("FOLDER", foreground="#06b6d4", background="#082f49")
        self.txt_logs.tag_config("CLEAN", foreground="#6ee7b7", background="#0d3b2b")
        self.txt_logs.tag_config("TRASH", foreground="#6ee7b7", background="#0d3b2b")
        self.txt_logs.tag_config("SEARCH", foreground="#fbbf24", background="#451407", font=("Courier New", 10, "bold"))
        self.txt_logs.tag_config("SEPARATOR", foreground="#374151", background="#0b1220")

        # Recent events table
        table_frame = ttk.Frame(split, style="Card.TFrame")
        ttk.Label(table_frame, text="Últimos eventos", background="#ffffff", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 0))

        cols = ("time", "level", "msg")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=7)
        self.tree.heading("time", text="Hora")
        self.tree.heading("level", text="Nivel")
        self.tree.heading("msg", text="Mensaje")
        self.tree.column("time", width=80, anchor="w")
        self.tree.column("level", width=70, anchor="w")
        self.tree.column("msg", anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

        split.add(logs_frame, weight=2)
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
        """Sidebar simplificado - solo info de vistazo."""
        pad = {"padx": 14, "pady": 10}
        ttk.Label(self.sidebar, text="ZIP Watcher", style="SidebarTitle.TLabel").pack(anchor="w", **pad)
        ttk.Separator(self.sidebar).pack(fill="x", padx=14, pady=(0, 10))

        self.side_state_emoji = tk.StringVar(value="🔴")
        self.side_state_text = tk.StringVar(value="Detenido")
        
        state_row = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        state_row.pack(anchor="w", padx=14, pady=(0, 10))
        tk.Label(state_row, textvariable=self.side_state_emoji, background="#111827", font=("Segoe UI", 14)).pack(side="left")
        tk.Label(state_row, textvariable=self.side_state_text, background="#111827", foreground="#e5e7eb", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(6, 0))

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
        return bool(self._worker and self._worker.is_alive())

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
            "trash": "Trash",
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
            "trash": wd / "Trash",
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
        self._worker = WatcherThread(self.settings_getter, self.emit, self._stop_event)
        self._worker.start()

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        self._set_maintenance_enabled(False)

        self._set_status("En ejecución", UIStatus.RUNNING.value)
        self.emit("START", "Monitorización activa.")

    def stop_watcher(self):
        if not self._is_running():
            return
        self._stop_event.set()
        self._set_status("Deteniendo…", UIStatus.STOPPING.value)
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
        self._set_status("Parado", UIStatus.IDLE.value)
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

        for iid in self.tree.get_children():
            self.tree.delete(iid)

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

            self._push_recent_event(ev)

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

    def _push_recent_event(self, ev: LogEvent):
        ts = time.strftime("%H:%M:%S", time.localtime(ev.ts))
        lvl = ev.level.upper()
        msg = ev.msg
        iid = self.tree.insert("", 0, values=(ts, f"{emoji(lvl)} {lvl}", msg))
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
