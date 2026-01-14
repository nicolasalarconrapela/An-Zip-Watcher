import argparse
import json
import os
import time
import shutil
import zipfile
import tempfile
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


DEFAULT_CONFIG_PATH = Path(__file__).with_name("settings.json")


def default_downloads_dir() -> Path:
    # Multiplataforma: en Windows suele resolver a C:\Users\<user>\Downloads
    # En Linux/macOS: /home/<user>/Downloads o /Users/<user>/Downloads
    return Path.home() / "Downloads"


def load_settings(config_path: Path) -> dict:
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
        except Exception:
            # Si el JSON está roto, arrancamos con defaults
            return {}
    return {}


def resolve_watch_dir(cli_watch_dir: str | None, settings: dict) -> Path:
    if cli_watch_dir:
        return Path(cli_watch_dir).expanduser().resolve()

    watch_dir = (settings.get("watch_dir") or "").strip()
    if watch_dir:
        return Path(watch_dir).expanduser().resolve()

    return default_downloads_dir().expanduser().resolve()


def wait_until_file_stable(file_path: Path, poll_seconds: float, max_tries: int) -> None:
    last_size = -1
    tries = 0

    while tries < max_tries:
        if not file_path.exists():
            time.sleep(poll_seconds)
            tries += 1
            continue

        size = file_path.stat().st_size
        if size == last_size and size > 0:
            return

        last_size = size
        time.sleep(poll_seconds)
        tries += 1


def first_folder_in_dir(root: Path) -> Path | None:
    folders = sorted([p for p in root.iterdir() if p.is_dir()])
    return folders[0] if folders else None


def zip_directory(src_dir: Path, dest_zip: Path) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in src_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(src_dir)
                zf.write(file_path, arcname.as_posix())


def process_zip(
    zip_path: Path,
    output_dir: Path,
    processed_dir: Path,
    poll_seconds: float,
    max_tries: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    wait_until_file_stable(zip_path, poll_seconds=poll_seconds, max_tries=max_tries)

    # Validación básica: ¿es zip?
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.testzip()
    except Exception as e:
        print(f"[WARN] No se pudo abrir como ZIP (aún): {zip_path.name} -> {e}")
        return

    with tempfile.TemporaryDirectory(prefix="unzip_") as tmp:
        tmp_dir = Path(tmp)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)
        except Exception as e:
            print(f"[ERROR] Fallo al descomprimir {zip_path.name}: {e}")
            return

        top_folder = first_folder_in_dir(tmp_dir)
        if top_folder is None:
            print(f"[WARN] {zip_path.name} no contiene carpetas de primer nivel. Se omite.")
            return

        out_name = f"{zip_path.stem}__{top_folder.name}.zip"
        out_zip = output_dir / out_name

        if out_zip.exists():
            out_zip = output_dir / f"{zip_path.stem}__{top_folder.name}__{int(time.time())}.zip"

        try:
            zip_directory(top_folder, out_zip)
            print(f"[OK] Creado: {out_zip} (desde carpeta: {top_folder.name})")
        except Exception as e:
            print(f"[ERROR] Fallo al crear el zip destino para {zip_path.name}: {e}")
            return

    # Mover zip original a processed para no reprocesarlo
    try:
        dest = processed_dir / zip_path.name
        if dest.exists():
            dest = processed_dir / f"{zip_path.stem}__{int(time.time())}.zip"
        shutil.move(str(zip_path), str(dest))
        print(f"[OK] Movido original a: {dest}")
    except Exception as e:
        print(f"[WARN] No se pudo mover el original {zip_path.name}: {e}")


class ZipHandler(FileSystemEventHandler):
    def __init__(self, output_dir: Path, processed_dir: Path, poll_seconds: float, max_tries: int):
        self.output_dir = output_dir
        self.processed_dir = processed_dir
        self.poll_seconds = poll_seconds
        self.max_tries = max_tries

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".zip":
            process_zip(
                path,
                output_dir=self.output_dir,
                processed_dir=self.processed_dir,
                poll_seconds=self.poll_seconds,
                max_tries=self.max_tries,
            )

    def on_moved(self, event):
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if path.suffix.lower() == ".zip":
            process_zip(
                path,
                output_dir=self.output_dir,
                processed_dir=self.processed_dir,
                poll_seconds=self.poll_seconds,
                max_tries=self.max_tries,
            )


def main():
    parser = argparse.ArgumentParser(description="Watch a directory for ZIPs, unzip, then rezip first folder.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Ruta a settings.json")
    parser.add_argument("--watch-dir", default=None, help="Carpeta a escuchar (override de settings.json)")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    settings = load_settings(config_path)

    watch_dir = resolve_watch_dir(args.watch_dir, settings)

    output_subdir = (settings.get("output_subdir") or "output").strip()
    processed_subdir = (settings.get("processed_subdir") or "processed").strip()

    output_dir = watch_dir / output_subdir
    processed_dir = watch_dir / processed_subdir

    poll_seconds = float(settings.get("poll_settle_seconds", 1.0))
    max_tries = int(settings.get("max_settle_tries", 30))

    watch_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    handler = ZipHandler(output_dir=output_dir, processed_dir=processed_dir, poll_seconds=poll_seconds, max_tries=max_tries)
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()

    print(f"Config:          {config_path}")
    print(f"Escuchando en:   {watch_dir}")
    print(f"Salida en:       {output_dir}")
    print(f"Procesados en:   {processed_dir}")
    print("Ctrl+C para salir.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
