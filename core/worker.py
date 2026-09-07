from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event, Lock

from PySide6.QtCore import QObject, Signal, Slot

from .crypto import decrypt_file, encrypt_file

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
}


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
        self.workers = max(1, min(int(workers), os.cpu_count() or 1))
        self._cancel = Event()
        self._lock = Lock()
        self._completed = 0

    def cancel(self):
        self._cancel.set()

    def _files(self):
        if self.mode == "encrypt":
            return [
                p for p in self.input_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS
                and self.output_dir.resolve() not in p.resolve().parents
            ]
        return [
            p for p in self.input_dir.rglob("*.aesvault")
            if p.is_file() and self.output_dir.resolve() not in p.resolve().parents
        ]

    def _destination(self, src):
        relative = src.relative_to(self.input_dir)
        if self.mode == "encrypt":
            return (self.output_dir / relative).with_name(
                relative.name + ".aesvault"
            )
        # Restore the original filename and directory structure.
        return (self.output_dir / relative).with_suffix("")

    @Slot()
    def run(self):
        files = self._files()
        total = sum(p.stat().st_size for p in files)

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

            dst = self._destination(src)
            dst.parent.mkdir(parents=True, exist_ok=True)

            def on_progress(value):
                with self._lock:
                    self._completed += value - getattr(on_progress, "_last", 0)
                    on_progress._last = value
                    now = self._completed
                self.progress.emit(now, total, src.name)

            try:
                if dst.exists():
                    raise FileExistsError(f"Output already exists: {dst}")
                if self.mode == "encrypt":
                    encrypt_file(src, dst, self.password, on_progress)
                else:
                    decrypt_file(src, dst, self.password, on_progress)
                return True, str(src), ""
            except Exception as exc:
                try:
                    dst.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, str(src), f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(
            max_workers=self.workers,
            thread_name_prefix="aes-vault"
        ) as pool:
            futures = {pool.submit(process, p): p for p in files}

            for future in as_completed(futures):
                if self._cancel.is_set():
                    for f in futures:
                        f.cancel()
                    self.cancelled.emit()
                    break

                ok, name, message = future.result()
                if ok:
                    successful += 1
                    self.file_done.emit(name)
                elif message != "cancelled":
                    failed += 1
                    self.error.emit(f"{Path(name).name}: {message}")

        self.finished.emit(successful, failed)
