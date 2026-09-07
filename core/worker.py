from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event, Lock

from PySide6.QtCore import QObject, Signal, Slot

from .crypto import VaultCancelledError, decrypt_file, encrypt_file

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
}
MAX_FILE_WORKERS = 4


class FileWorker(QObject):
    progress = Signal(int, int, str)
    file_done = Signal(str)
    error = Signal(str)
    finished = Signal(int, int)
    cancelled = Signal()

    def __init__(self, mode, input_dir, output_dir, password, workers):
        super().__init__()
        self.mode = mode
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.password = password
        # Keep the UI control unchanged, but impose a safe process-wide cap.
        self.workers = max(1, min(int(workers), MAX_FILE_WORKERS, os.cpu_count() or 1))
        self._cancel = Event()
        self._lock = Lock()
        self._completed = 0

    def cancel(self):
        self._cancel.set()

    def _inside(self, child: Path, parent: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def _files(self):
        input_root = self.input_dir.resolve(strict=True)
        output_root = self.output_dir.resolve()
        if input_root == output_root or self._inside(output_root, input_root):
            raise ValueError("Input and output folders must differ and must not overlap.")

        result = []
        pattern = "*" if self.mode == "encrypt" else "*.aesvault"
        for p in self.input_dir.rglob(pattern):
            # Do not follow/operate on symlinks, junction-like entries, or paths
            # whose final target has escaped the selected input tree.
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                resolved = p.resolve(strict=True)
                if not self._inside(resolved, input_root):
                    continue
                if self.mode == "encrypt" and resolved.suffix.lower() not in MEDIA_EXTENSIONS:
                    continue
                result.append(resolved)
            except OSError:
                continue
        return result

    def _destination(self, src):
        relative = src.relative_to(self.input_dir.resolve())
        if self.mode == "encrypt":
            return (self.output_dir / relative).with_name(relative.name + ".aesvault")
        return (self.output_dir / relative).with_suffix("")

    @Slot()
    def run(self):
        try:
            files = self._files()
            total = sum(p.stat().st_size for p in files)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            self.finished.emit(0, 0)
            return

        if not files:
            self.error.emit(
                "No supported media files were found."
                if self.mode == "encrypt"
                else "No .aesvault files were found."
            )
            self.finished.emit(0, 0)
            return

        successful = failed = 0

        def process(src):
            if self._cancel.is_set():
                return False, str(src), "cancelled"

            try:
                dst = self._destination(src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    raise FileExistsError(f"Output already exists: {dst}")

                def on_progress(value):
                    with self._lock:
                        last = getattr(on_progress, "_last", 0)
                        self._completed += max(0, value - last)
                        on_progress._last = value
                        now = self._completed
                    self.progress.emit(now, total, src.name)

                if self.mode == "encrypt":
                    encrypt_file(src, dst, self.password, on_progress, self._cancel)
                else:
                    decrypt_file(src, dst, self.password, on_progress, self._cancel)
                return True, str(src), ""
            except VaultCancelledError:
                return False, str(src), "cancelled"
            except Exception as exc:
                # Crypto/storage core already removes its temporary output.
                try:
                    dst.unlink(missing_ok=True)
                except (OSError, UnboundLocalError):
                    pass
                return False, str(src), f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="aes-vault") as pool:
            futures = {pool.submit(process, p): p for p in files}
            for future in as_completed(futures):
                if self._cancel.is_set():
                    for f in futures:
                        f.cancel()
                try:
                    ok, name, message = future.result()
                except Exception as exc:
                    ok, name, message = False, str(futures[future]), f"{type(exc).__name__}: {exc}"
                if ok:
                    successful += 1
                    self.file_done.emit(name)
                elif message == "cancelled":
                    continue
                else:
                    failed += 1
                    self.error.emit(f"{Path(name).name}: {message}")

        if self._cancel.is_set():
            self.cancelled.emit()
        self.finished.emit(successful, failed)
