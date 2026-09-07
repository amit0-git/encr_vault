from __future__ import annotations

import sys
from pathlib import Path

# Allow this UI module to be launched directly by an IDE as well as imported
# from main.py.  In direct-script mode, Python otherwise only searches `ui/`.
if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QToolButton, QVBoxLayout, QWidget, QMessageBox, QPushButton, QStyle
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
    def __init__(self, source: Path, password: str, parent=None):
        super().__init__(parent)
        self.source, self.password = Path(source), password
        self._image = QImage()
        # A frameless dialog leaves no title bar, filename, controls, or
        # metadata beside the image. Press Escape to close it.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.resize(980, 700)
        self.setMinimumSize(720, 560)
        self.setModal(True)

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
            return
            self.dimensions.setText(f"{self._image.width()} × {self._image.height()}")
            self.meta.setText("Decrypted in memory • plaintext file not created")
        except Exception as exc:
            QMessageBox.critical(self, "Preview failed", f"The image could not be authenticated or decoded.\n\n{exc}")
            self.reject()

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

    def closeEvent(self, event):
        self.password = ""
        self._image = QImage()
        self.image.clear()
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

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(e)


class PreviewPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); self.password=""; self.paths=[]; self.loaded=0; self.batch_size=30; self._loading=False; self._tiles={}; self._thumb_cache={}; self.pool=QThreadPool.globalInstance(); self.signals=ThumbSignals(); self.signals.ready.connect(self._thumbnail_ready); self._build_ui()

    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(8)
        toolbar=QFrame(); toolbar.setObjectName("card"); row=QHBoxLayout(toolbar); row.setContentsMargins(10,9,10,9); row.setSpacing(7)
        self.folder=QLineEdit(); self.folder.setReadOnly(True); self.folder.setPlaceholderText("Encrypted vault folder…")
        browse=QToolButton(); browse.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton)); browse.setToolTip("Choose encrypted folder"); browse.clicked.connect(self.browse)
        self.password_edit=QLineEdit(); self.password_edit.setMaxLength(6); self.password_edit.setEchoMode(QLineEdit.Password); self.password_edit.setPlaceholderText("6-char key"); self.password_edit.setFixedWidth(125); self.password_edit.textChanged.connect(self._password_changed)
        self.auth=QPushButton("Unlock gallery"); self.auth.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton)); self.auth.setObjectName("primary"); self.auth.setEnabled(False); self.auth.clicked.connect(self.load_gallery)
        row.addWidget(self.folder,1); row.addWidget(browse); row.addWidget(self.password_edit); row.addWidget(self.auth); root.addWidget(toolbar)

        info=QHBoxLayout(); self.count=QLabel("0 items"); self.count.setObjectName("pill"); self.loaded_label=QLabel("0 loaded"); self.loaded_label.setObjectName("muted"); self.hint=QLabel("Select a photo to open the secure full-size viewer"); self.hint.setObjectName("muted"); info.addWidget(self.count); info.addWidget(self.loaded_label); info.addWidget(self.hint,1); root.addLayout(info)

        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame); self.scroll.verticalScrollBar().valueChanged.connect(self._scroll)
        self.canvas=QWidget(); self.grid=QGridLayout(self.canvas); self.grid.setContentsMargins(2,2,2,18); self.grid.setHorizontalSpacing(9); self.grid.setVerticalSpacing(9); self.scroll.setWidget(self.canvas); root.addWidget(self.scroll,1)
        self.empty=QFrame(); self.empty.setObjectName("emptyState"); el=QVBoxLayout(self.empty); el.setAlignment(Qt.AlignCenter); icon=QLabel(); icon.setPixmap(self.style().standardIcon(QStyle.SP_DirOpenIcon).pixmap(38,38)); icon.setAlignment(Qt.AlignCenter); el.addWidget(icon); msg=QLabel("Your secure gallery is empty"); msg.setObjectName("emptyTitle"); msg.setAlignment(Qt.AlignCenter); el.addWidget(msg); sub=QLabel("Choose an encrypted folder and unlock it with your 6-character key."); sub.setObjectName("muted"); sub.setAlignment(Qt.AlignCenter); el.addWidget(sub); root.addWidget(self.empty,1); self.empty.raise_()

    def _password_changed(self,value): self.password=value; self.auth.setEnabled(len(value)==6 and bool(self.folder.text().strip()))
    def browse(self):
        folder=QFileDialog.getExistingDirectory(self,"Select encrypted folder")
        if folder:
            self.folder.setText(folder)
            # Selecting a folder does not attempt to unlock it. Wait for a
            # complete key and an explicit click on "Unlock gallery".
            self.auth.setEnabled(len(self.password_edit.text()) == 6)

    def load_gallery(self):
        folder=Path(self.folder.text().strip())
        if not folder.is_dir(): QMessageBox.warning(self,"Encrypted folder","Select a valid encrypted folder first."); return
        if len(self.password_edit.text())!=6: QMessageBox.warning(self,"Access key","Enter exactly 6 characters."); return
        password = self.password_edit.text()
        paths = [p for p in sorted(folder.rglob("*.aesvault")) if media_type(p) == "photo"]
        if paths:
            try:
                # Authenticate before showing any thumbnails or opening previews.
                decrypt_preview(paths[0], password, max_bytes=256 * 1024 * 1024)
            except Exception:
                QMessageBox.warning(self, "Access key", "The access key is incorrect or this vault cannot be opened.")
                return
        self.password=password; self.paths=paths; self.loaded=0; self._thumb_cache.clear(); self._tiles.clear()
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
            if key in self._thumb_cache: tile.set_thumbnail(self._thumb_cache[key])
            else:
                tile.thumb.setPixmap(placeholder(size, "Loading…"))
                self.pool.start(ThumbnailTask(path,self.password,size,self.signals))
        self.loaded=end; self.loaded_label.setText(f"{self.loaded} / {len(self.paths)} shown"); self._loading=False

    def _thumbnail_ready(self,key,pix):
        self._thumb_cache[key]=pix
        tile=self._tiles.get(key)
        if tile: tile.set_thumbnail(pix)

    def _scroll(self,value):
        bar=self.scroll.verticalScrollBar()
        if value>=bar.maximum()-max(260,self.scroll.viewport().height()): self.load_more()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.paths and self.loaded:
            # Reflow existing tiles compactly as the window changes size.
            cols=self._columns()
            for i,path in enumerate(self.paths[:self.loaded]):
                tile=self._tiles.get(str(path))
                if tile: self.grid.addWidget(tile,i//cols,i%cols)

    def open_preview(self,path):
        PreviewWindow(Path(path),self.password,self).exec()
