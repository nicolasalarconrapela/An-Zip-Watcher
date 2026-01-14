import os
import time
import shutil
import zipfile
import tempfile
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


WATCH_DIR = Path(r"./watch")          # Cambia esta ruta
OUTPUT_DIR = WATCH_DIR / "output"
PROCESSED_DIR = WATCH_DIR / "processed"

POLL_SETTLE_SECONDS = 1.0            # Espera mínima para evitar zips a medio copiar
MAX_SETTLE_TRIES = 30                 # Reintentos para que el tamaño del zip se estabilice


def wait_until_file_stable(file_path: Path) -> None:
    """Espera a que el archivo deje de cambiar de tamaño (útil si lo están copiando)."""
    last_size = -1
    tries = 0

    while tries < MAX_SETTLE_TRIES:
        if not file_path.exists():
            time.sleep(POLL_SETTLE_SECONDS)
            tries += 1
            continue

        size = file_path.stat().st_size
        if size == last_size and size > 0:
            return

        last_size = size
        time.sleep(POLL_SETTLE_SECONDS)
        tries += 1

    # Si no se estabiliza, seguimos igualmente; zipfile puede fallar y se reintentará por nuevo evento.


def first_folder_in_dir(root: Path) -> Path | None:
    """Devuelve la primera carpeta (ordenada) dentro de root, o None si no hay."""
    folders = sorted([p for p in root.iterdir() if p.is_dir()])
    return folders[0] if folders else None


def zip_directory(src_dir: Path, dest_zip: Path) -> None:
    """Crea un zip con el contenido de src_dir (manteniendo estructura relativa)."""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in src_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(src_dir)
                zf.write(file_path, arcname.as_posix())


def process_zip(zip_path: Path) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    wait_until_file_stable(zip_path)

    # Validación básica: ¿es zip?
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.testzip()  # Lanza si hay corrupción notable
    except Exception as e:
        print(f"[WARN] No se pudo abrir como ZIP (aún): {zip_path.name} -> {e}")
        return

    with tempfile.TemporaryDirectory(prefix="unzip_") as tmp:
        tmp_dir = Path(tmp)

        # Descomprimir
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)
        except Exception as e:
            print(f"[ERROR] Fallo al descomprimir {zip_path.name}: {e}")
            return

        # Encontrar la primera carpeta del primer nivel
        top_folder = first_folder_in_dir(tmp_dir)
        if top_folder is None:
            print(f"[WARN] {zip_path.name} no contiene carpetas de primer nivel. Se omite.")
            return

        # Generar zip nuevo: nombre basado en zip original + nombre carpeta
        out_name = f"{zip_path.stem}__{top_folder.name}.zip"
        out_zip = OUTPUT_DIR / out_name

        # Si ya existe, evita sobrescribir: añade timestamp
        if out_zip.exists():
            out_zip = OUTPUT_DIR / f"{zip_path.stem}__{top_folder.name}__{int(time.time())}.zip"

        try:
            zip_directory(top_folder, out_zip)
            print(f"[OK] Creado: {out_zip.name} (desde carpeta: {top_folder.name})")
        except Exception as e:
            print(f"[ERROR] Fallo al crear el zip destino para {zip_path.name}: {e}")
            return

    # Mover zip original a processed para no reprocesarlo
    try:
        dest = PROCESSED_DIR / zip_path.name
        if dest.exists():
            dest = PROCESSED_DIR / f"{zip_path.stem}__{int(time.time())}.zip"
        shutil.move(str(zip_path), str(dest))
        print(f"[OK] Movido original a: {dest}")
    except Exception as e:
        print(f"[WARN] No se pudo mover el original {zip_path.name}: {e}")


class ZipHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".zip":
            process_zip(path)

    def on_moved(self, event):
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if path.suffix.lower() == ".zip":
            process_zip(path)


def main():
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(ZipHandler(), str(WATCH_DIR), recursive=False)
    observer.start()

    print(f"Escuchando en: {WATCH_DIR.resolve()}")
    print(f"Salida en:      {OUTPUT_DIR.resolve()}")
    print(f"Procesados en:  {PROCESSED_DIR.resolve()}")
    print("Ctrl+C para salir.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
