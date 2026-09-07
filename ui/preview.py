from __future__ import annotations

from collections import OrderedDict
import sys
import time
from pathlib import Path

# Allow this UI module to be launched directly by an IDE as well as imported
# from main.py.  In direct-script mode, Python otherwise only searches `ui/`.
if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QSettings, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QToolButton, QVBoxLayout, QWidget, QMessageBox, QPushButton, QStyle, QSpinBox
)

from core.preview import decrypt_preview, decrypt_to_temp

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
    ready = Signal(str, QPixmap)


class ThumbnailTask(QRunnable):
    def __init__(self, path: Path, password: str, size: QSize, signals: ThumbSignals):
        super().__init__()
        self.path, self.password, self.size, self.signals = path, password, size, signals

    @Slot()
    def run(self):
        try:
            data = decrypt_preview(self.path, self.password, max_bytes=48 * 1024 * 1024)
            image = QImage()
            if not image.loadFromData(data):
                raise ValueError("unsupported image")
            pix = QPixmap.fromImage(image).scaled(
                self.size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self.signals.ready.emit(str(self.path), pix)
        except Exception:
            self.signals.ready.emit(str(self.path), placeholder(self.size, "Unavailable"))


class PreviewWindow(QDialog):
    def __init__(self, source: Path, password: str, parent=None, timeout_minutes: int = 10):
        super().__init__(parent)
        self.source, self.password = Path(source), password
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
        return

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        header = QFrame(); header.setObjectName("card")
        h = QHBoxLayout(header); h.setContentsMargins(12, 8, 10, 8); h.setSpacing(8)
        icon = QToolButton(); icon.setIcon(self.style().standardIcon(QStyle.SP_FileIcon)); icon.setEnabled(False); h.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(1)
        title = QLabel(self.source.name.removesuffix(".aesvault")); title.setObjectName("previewTitle")
        title_box.addWidget(title)
        self.meta = QLabel("Authenticating secure image…"); self.meta.setObjectName("muted"); title_box.addWidget(self.meta)
        h.addLayout(title_box, 1)
        close = QToolButton(); close.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton)); close.setToolTip("Close preview"); close.clicked.connect(self.close); h.addWidget(close)
        root.addWidget(header)

        canvas = QFrame(); canvas.setObjectName("previewCanvas")
        cv = QVBoxLayout(canvas); cv.setContentsMargins(8, 8, 8, 8)
        self.image = QLabel(); self.image.setAlignment(Qt.AlignCenter); self.image.setMinimumSize(400, 360); cv.addWidget(self.image, 1)
        root.addWidget(canvas, 1)

        footer = QFrame(); footer.setObjectName("card")
        f = QHBoxLayout(footer); f.setContentsMargins(10, 7, 10, 7)
        badge = QLabel("✓ AUTHENTICATED"); badge.setObjectName("pill"); f.addWidget(badge)
        f.addStretch()
        self.dimensions = QLabel("—"); self.dimensions.setObjectName("muted"); f.addWidget(self.dimensions)
        done = QPushButton("Close"); done.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton)); done.clicked.connect(self.close); f.addWidget(done)
        root.addWidget(footer)
        self._load()

    def _load(self):
        try:
            data = decrypt_preview(self.source, self.password, max_bytes=256 * 1024 * 1024)
            if not self._image.loadFromData(data):
                raise ValueError("The authenticated image could not be decoded by Qt.")
            self._fit_image()
            self._preview_authenticated = True
            return True
        except Exception:
            # Never show a large preview or an error dialog when authentication
            # fails. Clear the in-memory image before closing.
            self._clear_preview()
            if self.parent() is not None and hasattr(self.parent(), "clear_gallery"):
                self.parent().clear_gallery(clear_password=True)
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
            self.image.setPixmap(QPixmap.fromImage(self._image).scaled(
                self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

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
        self.password = ""
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
        self.thumb.setPixmap(pix.scaled(self.thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

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
        super().__init__(parent); self.password=""; self.paths=[]; self.loaded=0; self.batch_size=30; self._loading=False; self._tiles={}; self._thumb_cache=OrderedDict(); self._thumb_cache_bytes=0; self._thumb_cache_limit=90*1024*1024; self._thumb_loading=set(); self._cache_loaded_count=0; self._cache_evicted_count=0; self.pool=QThreadPool(self); self.pool.setMaxThreadCount(2); self.signals=ThumbSignals(); self.signals.ready.connect(self._thumbnail_ready); self._preview_deadline=None; self._active_preview=None; self._preview_timer=QTimer(self); self._preview_timer.setInterval(1000); self._preview_timer.timeout.connect(self._tick_global_preview_timer); self._build_ui(); self._cache_limit_changed(self.cache_limit.value())

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
        self.canvas=QWidget(); self.grid=QGridLayout(self.canvas); self.grid.setContentsMargins(2,2,2,18); self.grid.setHorizontalSpacing(9); self.grid.setVerticalSpacing(9); self.scroll.setWidget(self.canvas); root.addWidget(self.scroll,1)
        self.empty=QFrame(); self.empty.setObjectName("emptyState"); el=QVBoxLayout(self.empty); el.setAlignment(Qt.AlignCenter); icon=QLabel(); icon.setPixmap(self.style().standardIcon(QStyle.SP_DirOpenIcon).pixmap(38,38)); icon.setAlignment(Qt.AlignCenter); el.addWidget(icon); msg=QLabel("Your secure gallery is empty"); msg.setObjectName("emptyTitle"); msg.setAlignment(Qt.AlignCenter); el.addWidget(msg); sub=QLabel("Choose an encrypted folder and unlock it with your 4–12 character key."); sub.setObjectName("muted"); sub.setAlignment(Qt.AlignCenter); el.addWidget(sub); root.addWidget(self.empty,1); self.empty.raise_()

    def _password_changed(self,value): self.password=value; self.auth.setEnabled(4 <= len(value) <= 12 and bool(self.folder.text().strip()))
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
        paths = [p for p in sorted(folder.rglob("*.aesvault")) if media_type(p) == "photo"]
        if paths:
            try:
                # Authenticate before showing any thumbnails or opening previews.
                decrypt_preview(paths[0], password, max_bytes=256 * 1024 * 1024)
            except Exception:
                # Wrong password: silently clear any previously displayed gallery.
                self.clear_gallery(clear_password=True)
                return
        # Start the single global preview session timer immediately after a
        # successful unlock. It is intentionally independent of the large
        # preview dialog, so time is consumed from the moment the gallery is
        # unlocked rather than from the first image click.
        self.password=password
        self._start_global_preview_timer()
        self.paths=paths; self.loaded=0; self._clear_thumbnail_cache(); self._tiles.clear()
        while self.grid.count():
            item=self.grid.takeAt(0); w=item.widget(); w.deleteLater() if w else None
        self.count.setText(f"{len(self.paths)} photos"); self.empty.setVisible(not bool(self.paths)); self.scroll.setVisible(bool(self.paths)); self.load_more()

    def _columns(self): return max(2, min(8, max(2, self.scroll.viewport().width() // 184)))
    def load_more(self):
        if self._loading or self.loaded>=len(self.paths): return
        self._loading=True; end=min(self.loaded+self.batch_size,len(self.paths)); cols=self._columns()
        for idx,path in enumerate(self.paths[self.loaded:end],start=self.loaded):
            tile=MediaTile(path); tile.clicked.connect(self.open_preview); self._tiles[str(path)]=tile; self.grid.addWidget(tile,idx//cols,idx%cols)
            size=QSize(162,112); key=str(path)
            if key in self._thumb_cache:
                pix, _bytes = self._thumb_cache.pop(key); self._thumb_cache[key]=(pix, _bytes); tile.set_thumbnail(pix)
            else:
                tile.thumb.setPixmap(placeholder(size, "Loading…"))
                if key not in self._thumb_loading:
                    self._thumb_loading.add(key)
                    self._emit_cache_status("Loading")
                    self.pool.start(ThumbnailTask(path,self.password,size,self.signals))
        self.loaded=end; self.loaded_label.setText(f"{self.loaded} / {len(self.paths)} shown"); self._loading=False

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
            return max(1, int(pix.toImage().sizeInBytes()))
        except Exception:
            return max(1, pix.width() * pix.height() * 4)

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

    def _thumbnail_ready(self,key,pix):
        self._thumb_loading.discard(key)
        if key not in self._tiles:
            self._emit_cache_status("Released")
            return
        size = self._pixmap_bytes(pix)
        old = self._thumb_cache.pop(key, None)
        if old is not None:
            self._thumb_cache_bytes -= old[1]
        self._thumb_cache[key]=(pix, size)
        self._thumb_cache_bytes += size
        self._cache_loaded_count += 1
        self._trim_thumbnail_cache()
        self._emit_cache_status("Loaded")
        tile=self._tiles.get(key)
        if tile:
            # It may have been evicted immediately if the configured limit is tiny.
            cached=self._thumb_cache.get(key)
            if cached is not None:
                tile.set_thumbnail(cached[0])

    def _refresh_visible_thumbnails(self):
        viewport = self.scroll.viewport()
        view_rect = viewport.rect()
        for key, tile in self._tiles.items():
            if tile.geometry().intersects(view_rect.translated(0, self.scroll.verticalScrollBar().value())):
                cached = self._thumb_cache.get(key)
                if cached is not None:
                    pix, size = self._thumb_cache.pop(key); self._thumb_cache[key]=(pix,size); tile.set_thumbnail(pix)
                elif key not in self._thumb_loading:
                    tile.thumb.setPixmap(placeholder(tile.thumb.size(), "Loading…"))
                    self._thumb_loading.add(key)
                    self.pool.start(ThumbnailTask(Path(key),self.password,tile.thumb.size(),self.signals))

    def _scroll(self,value):
        bar=self.scroll.verticalScrollBar()
        if value>=bar.maximum()-max(260,self.scroll.viewport().height()): self.load_more()
        self._refresh_visible_thumbnails()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.paths and self.loaded:
            # Reflow existing tiles compactly as the window changes size.
            cols=self._columns()
            for i,path in enumerate(self.paths[:self.loaded]):
                tile=self._tiles.get(str(path))
                if tile: self.grid.addWidget(tile,i//cols,i%cols)

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

    def clear_gallery(self, clear_password=True):
        # Remove all decrypted/in-memory preview state and thumbnails.
        self._preview_timer.stop()
        self._preview_deadline = None
        self.preview_timer_finished.emit()
        if self._active_preview is not None:
            self._active_preview._clear_preview()
            self._active_preview = None
        self.password = ""
        self.paths = []
        self.loaded = 0
        self._loading = False
        self._clear_thumbnail_cache()
        self._thumb_loading.clear()
        self._tiles.clear()
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.count.setText("0 items")
        self.loaded_label.setText("0 loaded")
        self.empty.setVisible(True)
        self.scroll.setVisible(False)
        if clear_password:
            self.password_edit.clear()
        self.auth.setEnabled(4 <= len(self.password_edit.text()) <= 12 and bool(self.folder.text().strip()))

    def open_preview(self,path):
        # One global preview window timer for the whole gallery session.
        # Opening another item never resets the deadline.
        if self._preview_deadline is not None and time.monotonic() >= self._preview_deadline:
            self.clear_gallery(clear_password=True)
            return
        dialog = PreviewWindow(Path(path),self.password,self,self.timeout.value())
        if not dialog._preview_authenticated:
            return
        self._active_preview = dialog
        self._update_active_preview_timer()
        dialog.exec()
        if self._active_preview is dialog:
            self._active_preview = None
