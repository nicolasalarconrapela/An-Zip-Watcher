import argparse
import json
import time
import shutil
import zipfile
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


DEFAULT_CONFIG_PATH = Path(__file__).with_name("settings.json")

def load_settings(config_path: Path) -> dict:
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def resolve_watch_dir(cli_watch_dir: str | None, settings: dict) -> Path:
    watch_dir = cli_watch_dir or settings.get("watch_dir")

    if not watch_dir:
        raise RuntimeError(
            "No se ha definido watch_dir. "
            "Es obligatorio especificar --watch-dir o settings.json"
        )

    return Path(watch_dir).expanduser().resolve()

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


def zip_directory(src_dir: Path, dest_zip: Path) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in src_dir.rglob("*"):
            if path.is_file():
                arcname = path.relative_to(src_dir)
                zf.write(path, arcname.as_posix())


def safe_move(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    final_dest = dest
    if final_dest.exists():
        final_dest = dest.with_name(f"{dest.stem}__{int(time.time())}{dest.suffix}")
    shutil.move(str(src), str(final_dest))
    return final_dest


def process_zip(
    zip_path: Path,
    extract_root: Path,
    output_dir: Path,
    processed_dir: Path,
    poll_seconds: float,
    max_tries: int,
) -> None:
    extract_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    wait_until_file_stable(zip_path, poll_seconds, max_tries)

    # Validar ZIP
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.testzip()
    except Exception as e:
        print(f"[WARN] ZIP inválido: {zip_path.name} -> {e}")
        return

    extract_dir = extract_root / zip_path.stem
    if extract_dir.exists():
        extract_dir = extract_root / f"{zip_path.stem}__{int(time.time())}"

    # 1) Descomprimir
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        print(f"[OK] Descomprimido: {zip_path.name} -> {extract_dir}")
    except Exception as e:
        print(f"[ERROR] Error al descomprimir {zip_path.name}: {e}")
        return

    # 2) Tomar la PRIMERA carpeta dentro del nodo descomprimido
    folders = sorted([p for p in extract_dir.iterdir() if p.is_dir()])
    if not folders:
        print(f"[WARN] {zip_path.name} no contiene carpetas. No se comprime nada.")
        return

    target_folder = folders[0]

    # 3) Comprimir SOLO esa carpeta
    out_zip = output_dir / f"{target_folder.name}.zip"
    if out_zip.exists():
        out_zip = output_dir / f"{target_folder.name}__{int(time.time())}.zip"

    try:
        zip_directory(target_folder, out_zip)
        print(f"[OK] Comprimido: {out_zip} (desde {target_folder})")
    except Exception as e:
        print(f"[ERROR] Error al comprimir {target_folder}: {e}")
        return

    # 4) Mover ZIP original
    try:
        moved = safe_move(zip_path, processed_dir / zip_path.name)
        print(f"[OK] ZIP original movido a: {moved}")
    except Exception as e:
        print(f"[WARN] No se pudo mover el ZIP original {zip_path.name}: {e}")


class ZipHandler(FileSystemEventHandler):
    def __init__(self, extract_root: Path, output_dir: Path, processed_dir: Path, poll_seconds: float, max_tries: int):
        self.extract_root = extract_root
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
                self.extract_root,
                self.output_dir,
                self.processed_dir,
                self.poll_seconds,
                self.max_tries,
            )

    def on_moved(self, event):
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if path.suffix.lower() == ".zip":
            process_zip(
                path,
                self.extract_root,
                self.output_dir,
                self.processed_dir,
                self.poll_seconds,
                self.max_tries,
            )


def main():
    parser = argparse.ArgumentParser(
        description="Escucha un directorio, descomprime ZIPs y comprime la primera carpeta resultante."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Ruta a settings.json")
    parser.add_argument("--watch-dir", default=None, help="Carpeta a escuchar")
    args = parser.parse_args()

    settings = load_settings(Path(args.config))
    try:
        watch_dir = resolve_watch_dir(args.watch_dir, settings)
    except RuntimeError as e:
        print(f"[FATAL] {e}")
        return

    extract_root = watch_dir / (settings.get("extract_subdir") or "extracted")
    output_dir = watch_dir / (settings.get("output_subdir") or "output")
    processed_dir = watch_dir / (settings.get("processed_subdir") or "processed")

    poll_seconds = float(settings.get("poll_settle_seconds", 1.0))
    max_tries = int(settings.get("max_settle_tries", 30))

    watch_dir.mkdir(parents=True, exist_ok=True)
    extract_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(
        ZipHandler(extract_root, output_dir, processed_dir, poll_seconds, max_tries),
        str(watch_dir),
        recursive=False,
    )
    observer.start()

    print(f"Escuchando en:     {watch_dir}")
    print(f"Descomprime en:    {extract_root}")
    print(f"ZIP generado en:   {output_dir}")
    print(f"ZIP procesados:    {processed_dir}")
    print("Regla:             se comprime SOLO la primera carpeta encontrada")
    print("Ctrl+C para salir.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
