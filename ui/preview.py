from __future__ import annotations

from collections import OrderedDict
import sys
import time
from pathlib import Path
from threading import Event

# Allow this UI module to be launched directly by an IDE as well as imported
# from main.py.  In direct-script mode, Python otherwise only searches `ui/`.
if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QSettings, Signal, Slot, QFile
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QImageReader
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QToolButton, QVBoxLayout, QWidget, QMessageBox, QPushButton, QStyle, QSpinBox
)

from core.preview import authenticate_vault, secure_preview_file, cleanup_stale_preview_files

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


def media_extension(path: Path) -> str:
    name = path.name
    if name.lower().endswith(".aesvault"):
        name = name[:-9]
    return Path(name).suffix.lower()


def media_type(path: Path) -> str:
    ext = media_extension(path)
    if ext in IMAGE_EXTENSIONS:
        return "photo"
    return "other"


def placeholder(size: QSize, text="Loading") -> QPixmap:
    pix = QPixmap(size)
    pix.fill(QColor("#0d1424"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#17233a"))
    p.drawRoundedRect(2, 2, size.width()-4, size.height()-4, 10, 10)
    p.setPen(QColor("#8090aa"))
    p.setFont(QFont("Segoe UI", 9, QFont.Bold))
    p.drawText(pix.rect(), Qt.AlignCenter, text)
    p.end()
    return pix




# --- Global preview sidebar timer ---
def _setup_preview_sidebar_timer(self):
    """Create the compact sidebar timer widget once."""
    if getattr(self, "_preview_sidebar_timer_widget", None) is not None:
        return

    # Find the sidebar layout/container without depending on a specific UI name.
    container = None
    for name in ("sidebar_layout", "side_layout", "sidebar", "side_panel", "left_layout"):
        obj = getattr(self, name, None)
        if obj is not None:
            container = obj
            break

    if container is None:
        return

    from PySide6.QtWidgets import QLabel
    self._preview_sidebar_timer_widget = QLabel("Preview 10:00")
    self._preview_sidebar_timer_widget.setObjectName("previewSidebarTimer")
    self._preview_sidebar_timer_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self._preview_sidebar_timer_widget.setMinimumHeight(34)
    self._preview_sidebar_timer_widget.setToolTip("Global preview time remaining")
    self._preview_sidebar_timer_widget.setStyleSheet(
        "QLabel#previewSidebarTimer {"
        " padding: 6px 10px; border-radius: 8px;"
        " font-weight: 600; }"
    )
    try:
        container.addWidget(self._preview_sidebar_timer_widget)
    except AttributeError:
        try:
            container.insertWidget(0, self._preview_sidebar_timer_widget)
        except Exception:
            self._preview_sidebar_timer_widget.deleteLater()
            self._preview_sidebar_timer_widget = None

def _update_preview_sidebar_timer(self, seconds):
    """Mirror the single global preview timer in the sidebar."""
    w = getattr(self, "_preview_sidebar_timer_widget", None)
    if w is None:
        self._setup_preview_sidebar_timer()
        w = getattr(self, "_preview_sidebar_timer_widget", None)
    if w is None:
        return

    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    w.setText(f"Preview {minutes:02d}:{secs:02d}")
    w.show()

def _remove_preview_sidebar_timer(self):
    """Remove the sidebar timer when the global preview session expires."""
    w = getattr(self, "_preview_sidebar_timer_widget", None)
    if w is not None:
        w.hide()
        w.deleteLater()
        self._preview_sidebar_timer_widget = None

class ThumbSignals(QObject):
    ready = Signal(str, QPixmap, int)


class PreviewSession:
    """Owns the gallery password and a cancellation generation.

    The raw password is never copied into individual thumbnail jobs. Each vault
    derives its own short-lived key because every vault has its own salt.
    """
    def __init__(self, password: str):
        self.password = password
        self._closed = False

    def close(self):
        self._closed = True
        self.password = ""


class ThumbnailTask(QRunnable):
    def __init__(self, path: Path, session: PreviewSession, size: QSize, signals: ThumbSignals, cancel_event, generation: int):
        super().__init__()
        self.setAutoDelete(True)
        self.path = Path(path)
        self.session = session
        self.size = QSize(size)
        self.signals = signals
        self.cancel_event = cancel_event
        self.generation = generation

    @Slot()
    def run(self):
        try:
            if self.cancel_event.is_set() or self.session._closed:
                return
            if self.cancel_event.is_set():
                return
            # Authenticate and decrypt through one source file handle. This
            # avoids a time-of-check/time-of-use window between authentication
            # and preview materialization.
            with secure_preview_file(
                self.path, password=self.session.password,
                max_bytes=48 * 1024 * 1024, cancel_event=self.cancel_event
            ) as tmp:
                if self.cancel_event.is_set():
                    return
                image = _read_scaled_image(tmp, self.size, self.cancel_event)
            if image is None or image.isNull() or self.cancel_event.is_set():
                return
            pix = QPixmap.fromImage(image)
            del image
            if self.cancel_event.is_set() or self.session._closed:
                pix = QPixmap()
                return
            self.signals.ready.emit(str(self.path), pix, self.generation)
        except Exception:
            if not self.cancel_event.is_set() and not self.session._closed:
                self.signals.ready.emit(str(self.path), placeholder(self.size, "Unavailable"), self.generation)


def _validate_reader_dimensions(reader, max_pixels: int):
    size = reader.size()
    if not size.isValid() or size.width() <= 0 or size.height() <= 0:
        raise ValueError("Unable to determine image dimensions safely.")
    width, height = int(size.width()), int(size.height())
    max_dimension = 32_768
    if width > max_dimension or height > max_dimension or width * height > max_pixels:
        raise ValueError("Source image exceeds the preview security limit.")
    return width, height


def _read_scaled_image(path: Path, target: QSize, cancel_event=None, max_pixels: int = 50_000_000):
    """Decode directly at display size where Qt supports it.

    The source remains in a private temporary file; only the small display
    image is retained in memory. A pixel ceiling prevents decompression-bomb
    style allocations even when the compressed image itself is small.
    """
    if cancel_event is not None and cancel_event.is_set():
        return None
    qfile = QFile(str(path))
    if not qfile.open(QFile.OpenModeFlag.ReadOnly):
        raise ValueError("Unable to open authenticated preview data.")
    try:
        reader = QImageReader(qfile)
        reader.setAutoTransform(True)
        source_w, source_h = _validate_reader_dimensions(reader, max_pixels)
        # Ask Qt for a bounded size with the same aspect ratio. The caller
        # still applies its original KeepAspectRatio presentation policy, so
        # the UI appearance remains unchanged. The source dimensions are
        # validated before read() to prevent decompression-bomb allocations.
        tw = max(1, target.width())
        th = max(1, target.height())
        scale = min(tw / source_w, th / source_h)
        decode_size = QSize(max(1, int(source_w * scale)), max(1, int(source_h * scale)))
        reader.setScaledSize(decode_size)
        image = reader.read()
        if image.isNull():
            raise ValueError(reader.errorString() or "Unsupported image")
        if image.width() * image.height() > max_pixels:
            raise ValueError("Decoded image exceeds the preview memory limit.")
        return image
    finally:
        qfile.close()


class PreviewWindow(QDialog):
    def __init__(self, source: Path, session: PreviewSession, parent=None, timeout_minutes: int = 10):
        super().__init__(parent)
        self.source, self.session = Path(source), session
        self.timeout_minutes = max(1, int(timeout_minutes))
        self._image = QImage()
        # A frameless dialog leaves no title bar, filename, controls, or
        # metadata beside the image. Press Escape to close it.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.resize(980, 700)
        self.setMinimumSize(720, 560)
        self.setModal(True)
        self._remaining_seconds = 0
        self._preview_authenticated = False

        # The full-size dialog intentionally contains only the photo.  The
        # QLabel scales it whenever the dialog size changes.
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.image = QLabel()
        self.image.setObjectName("previewCanvas")
        self.image.setAlignment(Qt.AlignCenter)
        root.addWidget(self.image, 1)

        self.close_button = QToolButton(self)
        self.close_button.setText("✕")
        self.close_button.setToolTip("Close preview")
        self.close_button.setFixedSize(32, 32)
        self.close_button.setStyleSheet(
            "QToolButton { background: rgba(15, 23, 42, 180); color: white; border: 1px solid rgba(255,255,255,120); border-radius: 16px; font-size: 16px; font-weight: bold; }"
            "QToolButton:hover { background: rgba(50, 65, 85, 220); }"
        )
        self.close_button.clicked.connect(self.close)
        self.close_button.raise_()

        self.timer_label = QLabel(self)
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setText("")
        self.timer_label.setStyleSheet(
            "QLabel { background: rgba(15, 23, 42, 205); color: white; "
            "border: 1px solid rgba(255,255,255,90); border-radius: 10px; "
            "padding: 5px 10px; font-weight: 700; }"
        )
        self.timer_label.adjustSize()
        self.timer_label.raise_()
        self._load()

    def _load(self):
        try:
            # Authenticate and decrypt through the same opened source handle.
            # The plaintext exists only in the private preview temp file while
            # Qt decodes it at the display size.
            with secure_preview_file(
                self.source, password=self.session.password,
                max_bytes=256 * 1024 * 1024
            ) as tmp:
                target = self.image.size()
                if target.width() < 100 or target.height() < 100:
                    target = QSize(980, 700)
                image = _read_scaled_image(tmp, target, max_pixels=50_000_000)
            if image is None or image.isNull():
                raise ValueError("The authenticated image could not be decoded by Qt.")
            self._image = image
            self._fit_image()
            self._preview_authenticated = True
            return True
        except Exception:
            # Never show a large preview or an error dialog when authentication
            # fails. Clear the in-memory image before closing.
            self._clear_preview()
            self.reject()
            return False

    def set_countdown(self, remaining_seconds: int):
        if not self._preview_authenticated:
            return
        self._remaining_seconds = max(0, int(remaining_seconds))
        if self._remaining_seconds <= 0:
            self.timer_label.setText("Preview expired")
        else:
            minutes, seconds = divmod(self._remaining_seconds, 60)
            self.timer_label.setText(f"Preview closes in {minutes:02d}:{seconds:02d}")
        self.timer_label.adjustSize()
        self.timer_label.move(self.width() - self.timer_label.width() - 62, 18)

    def _clear_preview(self):
        self._remaining_seconds = 0
        self._preview_authenticated = False
        self._image = QImage()
        if hasattr(self, "image"):
            self.image.clear()
            self.image.setPixmap(QPixmap())
        if hasattr(self, "timer_label"):
            self.timer_label.clear()

    def _fit_image(self):
        if not self._image.isNull():
            scaled = self._image.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image.setPixmap(QPixmap.fromImage(scaled))
            del scaled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()
        if hasattr(self, "close_button"):
            self.close_button.move(self.width() - self.close_button.width() - 18, 18)
        if hasattr(self, "timer_label") and self.timer_label.text():
            self.timer_label.adjustSize()
            self.timer_label.move(self.width() - self.timer_label.width() - self.close_button.width() - 34, 18)

    def closeEvent(self, event):
        self._clear_preview()
        self.session = None
        event.accept()


class MediaTile(QFrame):
    clicked = Signal(object)
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setObjectName("mediaTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(174)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.thumb = QLabel()
        self.thumb.setObjectName("tileImage")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedSize(174, 128)
        self.thumb.setStyleSheet("QLabel#tileImage { background: #0f172a; border: 1px solid #2b3a4e; border-radius: 8px; }")
        lay.addWidget(self.thumb)

    def set_thumbnail(self, pix):
        # ThumbnailTask already produces the bounded display size; avoid a second
        # QPixmap allocation here, which otherwise doubles cache/display memory.
        self.thumb.setPixmap(pix)

    def clear_thumbnail(self):
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("Loading…")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(e)


class PreviewPanel(QWidget):
    preview_timer_changed = Signal(int)
    preview_timer_finished = Signal()
    cache_status_changed = Signal(str)

    def __init__(self,parent=None):
        cleanup_stale_preview_files()
        super().__init__(parent); self._preview_session=None; self.paths=[]; self.loaded=0; self.batch_size=30; self._loading=False; self._tiles={}; self._thumb_cache=OrderedDict(); self._thumb_cache_bytes=0; self._thumb_cache_limit=90*1024*1024; self._thumb_loading={}; self._live_tile_margin_rows=2; self._tile_row_height=137; self._cache_loaded_count=0; self._thumb_cancel_event=Event(); self._generation=0; self._cache_evicted_count=0; self.pool=QThreadPool(self); self.pool.setMaxThreadCount(2); self.signals=ThumbSignals(); self.signals.ready.connect(self._thumbnail_ready); self._preview_deadline=None; self._active_preview=None; self._preview_timer=QTimer(self); self._preview_timer.setInterval(1000); self._preview_timer.timeout.connect(self._tick_global_preview_timer); self._build_ui(); self._cache_limit_changed(self.cache_limit.value())

    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(8)
        toolbar=QFrame(); toolbar.setObjectName("card")
        controls=QVBoxLayout(toolbar); controls.setContentsMargins(12,11,12,11); controls.setSpacing(9)

        folder_row=QHBoxLayout(); folder_row.setSpacing(8)
        self.folder=QLineEdit(); self.folder.setReadOnly(True); self.folder.setPlaceholderText("Encrypted vault folder…")
        browse=QToolButton(); browse.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton)); browse.setToolTip("Choose encrypted folder"); browse.clicked.connect(self.browse)
        folder_row.addWidget(self.folder,1); folder_row.addWidget(browse)
        controls.addLayout(folder_row)

        options_row=QHBoxLayout(); options_row.setSpacing(10)
        key_box=QVBoxLayout(); key_box.setSpacing(4)
        key_label=QLabel("Access key"); key_label.setObjectName("muted")
        self.password_edit=QLineEdit(); self.password_edit.setMaxLength(12); self.password_edit.setEchoMode(QLineEdit.Password); self.password_edit.setPlaceholderText("4–12 char key"); self.password_edit.textChanged.connect(self._password_changed)
        key_box.addWidget(key_label); key_box.addWidget(self.password_edit)
        options_row.addLayout(key_box,1)

        preview_box=QVBoxLayout(); preview_box.setSpacing(4)
        timeout_label=QLabel("Preview duration"); timeout_label.setObjectName("muted")
        self.timeout=QSpinBox(); self.timeout.setRange(1,120); self.timeout.setValue(10); self.timeout.setSuffix(" min"); self.timeout.setToolTip("Global preview session duration")
        preview_box.addWidget(timeout_label); preview_box.addWidget(self.timeout)
        options_row.addLayout(preview_box)

        cache_box=QVBoxLayout(); cache_box.setSpacing(4)
        cache_label=QLabel("Thumbnail RAM"); cache_label.setObjectName("muted")
        self.cache_limit=QSpinBox(); self.cache_limit.setRange(16,512); self.cache_limit.setValue(QSettings("Encrvault", "Encrvault").value("thumbnail_cache_mb", 90, type=int)); self.cache_limit.setSuffix(" MB"); self.cache_limit.setToolTip("Maximum RAM used by decoded thumbnails"); self.cache_limit.valueChanged.connect(self._cache_limit_changed)
        cache_box.addWidget(cache_label); cache_box.addWidget(self.cache_limit)
        options_row.addLayout(cache_box)

        self.auth=QPushButton("Unlock gallery"); self.auth.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton)); self.auth.setObjectName("primary"); self.auth.setEnabled(False); self.auth.clicked.connect(self.load_gallery)
        options_row.addWidget(self.auth,0,Qt.AlignBottom)
        controls.addLayout(options_row)
        root.addWidget(toolbar)

        info=QHBoxLayout(); self.count=QLabel("0 items"); self.count.setObjectName("pill"); self.loaded_label=QLabel("0 loaded"); self.loaded_label.setObjectName("muted"); self.hint=QLabel("Select a photo to open the secure full-size viewer"); self.hint.setObjectName("muted"); info.addWidget(self.count); info.addWidget(self.loaded_label); info.addWidget(self.hint,1); root.addLayout(info)

        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame); self.scroll.verticalScrollBar().valueChanged.connect(self._scroll)
        self.canvas=QWidget(); self.canvas.setContentsMargins(0,0,0,0); self.scroll.setWidget(self.canvas); root.addWidget(self.scroll,1)
        self.empty=QFrame(); self.empty.setObjectName("emptyState"); el=QVBoxLayout(self.empty); el.setAlignment(Qt.AlignCenter); icon=QLabel(); icon.setPixmap(self.style().standardIcon(QStyle.SP_DirOpenIcon).pixmap(38,38)); icon.setAlignment(Qt.AlignCenter); el.addWidget(icon); msg=QLabel("Your secure gallery is empty"); msg.setObjectName("emptyTitle"); msg.setAlignment(Qt.AlignCenter); el.addWidget(msg); sub=QLabel("Choose an encrypted folder and unlock it with your 4–12 character key."); sub.setObjectName("muted"); sub.setAlignment(Qt.AlignCenter); el.addWidget(sub); root.addWidget(self.empty,1); self.empty.raise_()

    def _password_changed(self,value): self.auth.setEnabled(4 <= len(value) <= 12 and bool(self.folder.text().strip()))
    def browse(self):
        folder=QFileDialog.getExistingDirectory(self,"Select encrypted folder")
        if folder:
            self.folder.setText(folder)
            # Selecting a folder does not attempt to unlock it. Wait for a
            # complete key and an explicit click on "Unlock gallery".
            self.auth.setEnabled(4 <= len(self.password_edit.text()) <= 12)

    def load_gallery(self):
        folder=Path(self.folder.text().strip())
        if not folder.is_dir(): QMessageBox.warning(self,"Encrypted folder","Select a valid encrypted folder first."); return
        if not 4 <= len(self.password_edit.text()) <= 12: QMessageBox.warning(self,"Access key","Enter a key between 4 and 12 characters."); return
        password = self.password_edit.text()
        paths = [str(p) for p in sorted(folder.rglob("*.aesvault")) if media_type(p) == "photo"]
        try:
            # Authenticate without materializing the first full image. The derived
            # key becomes the single session key shared by bounded preview tasks.
            session_key = authenticate_vault(Path(paths[0]), password) if paths else None
        except Exception:
            self.clear_gallery(clear_password=True)
            return
        # Start the single global preview session timer immediately after a
        # successful unlock. It is intentionally independent of the large
        # preview dialog, so time is consumed from the moment the gallery is
        # unlocked rather than from the first image click.
        self._cancel_thumbnail_tasks()
        self._preview_session=PreviewSession(password)
        # The first vault has already been authenticated above; the session
        # derives a separate key for every vault because each file has its own salt.
        from core.crypto import _wipe
        _wipe(session_key)
        self._start_global_preview_timer()
        self.paths=paths; self.loaded=0; self._clear_thumbnail_cache()
        self._destroy_all_tiles()
        self.count.setText(f"{len(self.paths)} photos"); self.empty.setVisible(not bool(self.paths)); self.scroll.setVisible(bool(self.paths)); self._update_canvas_geometry(); self.load_more()

    def _columns(self):
        return max(2, min(8, max(2, self.scroll.viewport().width() // 184)))

    def _update_canvas_geometry(self):
        cols = self._columns()
        rows = (len(self.paths) + cols - 1) // cols
        width = max(self.scroll.viewport().width(), cols * 184 + 2)
        height = max(self.scroll.viewport().height(), rows * self._tile_row_height + 20)
        self.canvas.setMinimumSize(width, height)
        self.canvas.resize(width, height)

    def _make_tile(self, idx: int):
        if not (0 <= idx < len(self.paths)):
            return None
        path = Path(self.paths[idx])
        key = str(path)
        existing = self._tiles.get(key)
        if existing is not None:
            return existing
        tile = MediaTile(path, self.canvas)
        tile.clicked.connect(self.open_preview)
        self._tiles[key] = tile
        size = QSize(162, 112)
        cached = self._thumb_cache.get(key)
        if cached is not None:
            pix, cache_size = self._thumb_cache.pop(key)
            self._thumb_cache[key] = (pix, cache_size)
            tile.set_thumbnail(pix)
        else:
            tile.thumb.setPixmap(placeholder(size, "Loading…"))
            if key not in self._thumb_loading and self._preview_session is not None:
                self._thumb_loading[key] = self._generation
                self._emit_cache_status("Loading")
                self.pool.start(ThumbnailTask(path, self._preview_session, size, self.signals, self._thumb_cancel_event, self._generation))
        return tile

    def _sync_tile_window(self):
        if not self.paths or self._preview_session is None:
            return
        self._update_canvas_geometry()
        cols = self._columns()
        bar_value = self.scroll.verticalScrollBar().value()
        viewport_h = max(1, self.scroll.viewport().height())
        first_row = max(0, bar_value // self._tile_row_height - self._live_tile_margin_rows)
        last_row = min((len(self.paths) + cols - 1) // cols - 1,
                       (bar_value + viewport_h) // self._tile_row_height + self._live_tile_margin_rows)
        wanted = set()
        for row in range(first_row, last_row + 1):
            for col in range(cols):
                idx = row * cols + col
                if idx >= len(self.paths):
                    break
                wanted.add(str(self.paths[idx]))
                tile = self._make_tile(idx)
                if tile is not None:
                    tile.setGeometry(2 + col * 184, 2 + row * self._tile_row_height, 174, 128)
                    tile.show()

        # Keep only a small viewport neighborhood of QWidget/QPixmap objects.
        # The thumbnail cache remains independent and bounded by bytes.
        for key in list(self._tiles):
            if key not in wanted:
                tile = self._tiles.pop(key)
                try:
                    tile.clear_thumbnail()
                    tile.hide()
                    tile.deleteLater()
                except RuntimeError:
                    pass

        self.loaded = max(self.loaded, min(len(self.paths), (last_row + 1) * cols))
        self.loaded_label.setText(f"{self.loaded} / {len(self.paths)} shown")

    def load_more(self):
        if self._loading or self.loaded >= len(self.paths):
            self._sync_tile_window()
            return
        self._loading = True
        self.loaded = min(self.loaded + self.batch_size, len(self.paths))
        self._sync_tile_window()
        self._loading = False

    def _emit_cache_status(self, event="Ready"):
        used_mb = self._thumb_cache_bytes / (1024 * 1024)
        limit_mb = self._thumb_cache_limit / (1024 * 1024)
        loading = len(self._thumb_loading)
        cached = len(self._thumb_cache)
        self.cache_status_changed.emit(
            f"{event}  •  {cached} cached  •  {used_mb:.1f} / {limit_mb:.0f} MB  •  {loading} loading"
        )

    def _cache_limit_changed(self, value):
        value = max(16, min(512, int(value)))
        self._thumb_cache_limit = value * 1024 * 1024
        QSettings("Encrvault", "Encrvault").setValue("thumbnail_cache_mb", value)
        self._trim_thumbnail_cache()
        self._emit_cache_status("Cache limit updated")

    def _clear_thumbnail_cache(self):
        self._thumb_cache.clear()
        self._thumb_cache_bytes = 0
        self._emit_cache_status("Cache cleared")

    def _pixmap_bytes(self, pix):
        try:
            dpr = max(1.0, float(pix.devicePixelRatio()))
        except Exception:
            dpr = 1.0
        # Conservative upper bound for a 32-bit decoded pixmap; avoids creating
        # a temporary QImage just to measure cache usage.
        return max(1, int(pix.width() * pix.height() * 4 * dpr * dpr))

    def _trim_thumbnail_cache(self):
        evicted = 0
        while self._thumb_cache and self._thumb_cache_bytes > self._thumb_cache_limit:
            key, (_pix, size) = self._thumb_cache.popitem(last=False)
            self._thumb_cache_bytes -= size
            evicted += 1
            tile = self._tiles.get(key)
            if tile is not None:
                tile.clear_thumbnail()
        if evicted:
            self._cache_evicted_count += evicted
            self._emit_cache_status(f"Unloaded {evicted}")

    def _thumbnail_ready(self,key,pix,generation):
        if generation != self._generation:
            # Only clear the loading marker if it still belongs to this stale
            # generation. A newer generation may already be decoding the same
            # path and must not be suppressed by an old callback.
            if self._thumb_loading.get(key) == generation:
                self._thumb_loading.pop(key, None)
            pix = QPixmap()
            return
        if self._thumb_loading.get(key) == generation:
            self._thumb_loading.pop(key, None)
        # Cache the completed thumbnail even if the tile scrolled off-screen
        # while decoding. This prevents duplicate jobs when the user scrolls
        # back quickly and keeps widget lifetime independent of decode lifetime.
        size = self._pixmap_bytes(pix)
        old = self._thumb_cache.pop(key, None)
        if old is not None:
            self._thumb_cache_bytes -= old[1]
        self._thumb_cache[key]=(pix, size)
        self._thumb_cache_bytes += size
        self._cache_loaded_count += 1
        self._trim_thumbnail_cache()
        self._emit_cache_status("Loaded" if key in self._tiles else "Cached")
        tile=self._tiles.get(key)
        if tile:
            cached=self._thumb_cache.get(key)
            if cached is not None:
                tile.set_thumbnail(cached[0])

    def _refresh_visible_thumbnails(self):
        self._sync_tile_window()

    def _scroll(self, value):
        # The canvas represents the whole gallery, while only a small viewport
        # neighborhood is materialized as QWidget objects.
        self._sync_tile_window()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.paths:
            self._sync_tile_window()

    def _start_global_preview_timer(self):
        if self._preview_deadline is None:
            self._preview_deadline = time.monotonic() + (self.timeout.value() * 60)
            self._preview_timer.start()
        self._update_active_preview_timer()

    def _update_active_preview_timer(self):
        if self._preview_deadline is None:
            return
        remaining = max(0, int(self._preview_deadline - time.monotonic() + 0.999))
        self.preview_timer_changed.emit(remaining)
        if self._active_preview is not None:
            self._active_preview.set_countdown(remaining)

    def _tick_global_preview_timer(self):
        if self._preview_deadline is None:
            self._preview_timer.stop()
            return
        remaining = self._preview_deadline - time.monotonic()
        if remaining <= 0:
            self._preview_timer.stop()
            self._preview_deadline = None
            self.preview_timer_finished.emit()
            if self._active_preview is not None:
                self._active_preview._clear_preview()
                self._active_preview.reject()
                self._active_preview = None
            self.clear_gallery(clear_password=True)
            return
        self._update_active_preview_timer()

    def _destroy_all_tiles(self):
        for tile in list(self._tiles.values()):
            try:
                tile.clear_thumbnail()
                tile.hide()
                tile.deleteLater()
            except RuntimeError:
                pass
        self._tiles.clear()

    def _cancel_thumbnail_tasks(self):
        try:
            self._thumb_cancel_event.set()
            self.pool.clear()
        except Exception:
            pass
        self._thumb_cancel_event = Event()
        self._generation += 1

    def clear_gallery(self, clear_password=True):
        # Remove all decrypted/in-memory preview state and thumbnails.
        self._cancel_thumbnail_tasks()
        self._preview_timer.stop()
        self._preview_deadline = None
        self.preview_timer_finished.emit()
        if self._active_preview is not None:
            self._active_preview._clear_preview()
            self._active_preview = None
        if self._preview_session is not None:
            try:
                self._preview_session.close()
            except Exception:
                pass
            self._preview_session = None
        self.paths = []
        self.loaded = 0
        self._loading = False
        self._clear_thumbnail_cache()
        self._thumb_loading.clear()
        self._destroy_all_tiles()
        self.count.setText("0 items")
        self.loaded_label.setText("0 loaded")
        self.empty.setVisible(True)
        self.scroll.setVisible(False)
        if clear_password:
            self.password_edit.clear()
        self.auth.setEnabled(4 <= len(self.password_edit.text()) <= 12 and bool(self.folder.text().strip()))

    def closeEvent(self, event):
        self.clear_gallery(clear_password=True)
        try:
            self.pool.waitForDone(2000)
        except Exception:
            pass
        super().closeEvent(event)

    def open_preview(self,path):
        # One global preview window timer for the whole gallery session.
        # Opening another item never resets the deadline.
        if self._preview_deadline is not None and time.monotonic() >= self._preview_deadline:
            self.clear_gallery(clear_password=True)
            return
        dialog = PreviewWindow(Path(path),self._preview_session,self,self.timeout.value())
        if not dialog._preview_authenticated:
            return
        self._active_preview = dialog
        self._update_active_preview_timer()
        dialog.exec()
        if self._active_preview is dialog:
            self._active_preview = None
