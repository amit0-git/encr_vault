from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event, Lock

from PySide6.QtCore import QObject, Signal, Slot

from .crypto import encrypt_file

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
}


class EncryptionWorker(QObject):
    progress = Signal(int, int, str)  # completed bytes, total bytes, filename
    file_done = Signal(str)
    finished = Signal(int, int)       # successful, failed
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, input_dir: str, output_dir: str, password: str, workers: int):
        super().__init__()
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.password = password
        self.workers = max(1, min(workers, os.cpu_count() or 1))
        self._cancel = Event()
        self._lock = Lock()

    def cancel(self):
        self._cancel.set()

    def _files(self):
        return [
            p for p in self.input_dir.rglob("*")
            if p.is_file()
            and p.suffix.lower() in MEDIA_EXTENSIONS
            and self.output_dir not in p.parents
        ]

    @Slot()
    def run(self):
        files = self._files()
        total = sum(p.stat().st_size for p in files)
        successful = 0
        failed = 0

        if not files:
            self.error.emit("No supported photo or video files were found.")
            self.finished.emit(0, 0)
            return

        shared_completed = [0]

        def one_file(src: Path):
            if self._cancel.is_set():
                return False, src.name, 0, "cancelled"

            relative = src.relative_to(self.input_dir)
            dst = self.output_dir / relative
            dst = dst.with_name(dst.name + ".aesvault")

            local_done = 0

            def on_progress(value):
                nonlocal local_done
                delta = value - local_done
                local_done = value
                with self._lock:
                    shared_completed[0] += delta
                    now = shared_completed[0]
                self.progress.emit(now, total, src.name)

            try:
                encrypt_file(src, dst, self.password, on_progress)
                return True, str(src), local_done, ""
            except Exception as exc:
                try:
                    dst.unlink(missing_ok=True)
                except OSError:
                    pass
                return False, str(src), local_done, f"{type(exc).__name__}: {exc}"

        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="aes-vault") as pool:
            futures = {pool.submit(one_file, p): p for p in files}
            for future in as_completed(futures):
                if self._cancel.is_set():
                    for f in futures:
                        f.cancel()
                    self.cancelled.emit()
                    break

                ok, name, _, message = future.result()
                if ok:
                    successful += 1
                    self.file_done.emit(name)
                else:
                    failed += 1
                    if message != "cancelled":
                        self.error.emit(f"{name}: {message}")

        self.finished.emit(successful, failed)
