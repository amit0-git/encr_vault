from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.worker import FileWorker
from ui.preview import PreviewPanel


DARK = """
QMainWindow,QWidget{background:#0b1020;color:#edf2ff;font-family:"Segoe UI";font-size:12px}
QFrame#sidebar,QFrame#card{background:#12192b;border:1px solid #202a42;border-radius:16px}
QFrame#sidebar{border-radius:16px}
QLabel#brand{font-size:21px;font-weight:800;letter-spacing:1px}
QLabel#eyebrow{color:#62e6d8;font-size:11px;font-weight:800;letter-spacing:1.2px}
QLabel#title{font-size:25px;font-weight:800}
QLabel#subtitle,QLabel#muted{color:#8995ad}
QLabel#metric{font-size:25px;font-weight:800}
QLabel#metricLabel{color:#8995ad;font-size:11px}
QLabel#pill{background:#17243a;border:1px solid #29415f;border-radius:12px;padding:6px 10px;color:#78e7db;font-weight:700}
QLabel#emptyState{background:#10182a;border:1px dashed #31405e;border-radius:16px;color:#77849d;padding:50px;font-size:15px}
QLineEdit,QSpinBox{background:#0d1424;border:1px solid #2a3652;border-radius:10px;padding:10px;color:#edf2ff}
QLineEdit:focus,QSpinBox:focus{border:1px solid #55d9cf}
QPushButton{background:#182238;border:1px solid #2a3855;border-radius:10px;padding:10px 14px;font-weight:700}
QPushButton:hover{background:#22304c;border-color:#3b5277}
QPushButton:disabled{color:#5f6b82;background:#141b2a}
QPushButton#primary{background:#25b9ad;border:none;color:#07151a;min-height:42px}
QPushButton#primary:hover{background:#39d0c3}
QPushButton#nav{background:transparent;border:none;text-align:left;padding:12px 14px;color:#9ba7bd}
QPushButton#nav:checked{background:#1b2a42;color:#74e8dd;border-left:3px solid #55d9cf}
QPushButton#danger{background:#281b28;border-color:#5a3044;color:#f5a6bd}
QProgressBar{background:#0b1120;border:none;border-radius:6px;height:10px}
QProgressBar::chunk{background:#55d9cf;border-radius:6px}
QFrame#mediaTile{background:#141d31;border:1px solid #26334e;border-radius:11px}
QFrame#mediaTile:hover{border:1px solid #55d9cf;background:#17243b}
QLabel#tileImage{background:#0c1322;border-radius:8px}
QLabel#tileName{font-weight:700;padding:0 2px}
QLabel#tileKind{color:#6d7c98;font-size:9px;font-weight:800;padding:0 2px}
QFrame#previewControls{background:#12192b;border:1px solid #202a42;border-radius:10px}
QLabel#previewTitle{font-size:18px;font-weight:800}
QLabel#previewCanvas{background:#070b14;border:1px solid #27334b;border-radius:14px}
"""

LIGHT = """
QMainWindow,QWidget{background:#f3f6fb;color:#172033;font-family:"Segoe UI";font-size:12px}
QFrame#sidebar,QFrame#card{background:#ffffff;border:1px solid #dce3ee;border-radius:16px}
QFrame#sidebar{border-radius:16px}
QLabel#brand{font-size:21px;font-weight:800;letter-spacing:1px}
QLabel#eyebrow{color:#087f78;font-size:11px;font-weight:800;letter-spacing:1.2px}
QLabel#title{font-size:25px;font-weight:800}
QLabel#subtitle,QLabel#muted{color:#66738a}
QLabel#metric{font-size:25px;font-weight:800}
QLabel#metricLabel{color:#66738a;font-size:11px}
QLabel#pill{background:#e8f7f5;border:1px solid #bce7e2;border-radius:12px;padding:6px 10px;color:#087f78;font-weight:700}
QLabel#emptyState{background:#ffffff;border:1px dashed #c9d4e5;border-radius:16px;color:#718096;padding:50px;font-size:15px}
QLineEdit,QSpinBox{background:#f8fafc;border:1px solid #ccd6e4;border-radius:10px;padding:10px;color:#172033}
QLineEdit:focus,QSpinBox:focus{border:1px solid #159e95}
QPushButton{background:#eef2f7;border:1px solid #d0d9e6;border-radius:10px;padding:10px 14px;font-weight:700}
QPushButton:hover{background:#e4eaf2;border-color:#b8c5d6}
QPushButton:disabled{color:#9aa5b6;background:#f1f3f6}
QPushButton#primary{background:#159e95;border:none;color:white;min-height:42px}
QPushButton#primary:hover{background:#087f78}
QPushButton#nav{background:transparent;border:none;text-align:left;padding:12px 14px;color:#64748b}
QPushButton#nav:checked{background:#e8f7f5;color:#087f78;border-left:3px solid #159e95}
QPushButton#danger{background:#fff0f3;border-color:#f2c8d2;color:#b4234d}
QProgressBar{background:#e7ecf3;border:none;border-radius:6px;height:10px}
QProgressBar::chunk{background:#159e95;border-radius:6px}
QFrame#mediaTile{background:#ffffff;border:1px solid #dce3ee;border-radius:11px}
QFrame#mediaTile:hover{border:1px solid #159e95;background:#f8fffe}
QLabel#tileImage{background:#eef2f7;border-radius:8px}
QLabel#tileName{font-weight:700;padding:0 2px}
QLabel#tileKind{color:#718096;font-size:9px;font-weight:800;padding:0 2px}
QFrame#previewControls{background:#ffffff;border:1px solid #dce3ee;border-radius:10px}
QLabel#previewTitle{font-size:18px;font-weight:800}
QLabel#previewCanvas{background:#f7f9fc;border:1px solid #dce3ee;border-radius:14px}
"""


class FolderCard(QFrame):
    def __init__(self, title, hint, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setStyleSheet("font-size:16px;font-weight:800")
        desc = QLabel(hint)
        desc.setObjectName("muted")
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText("Select a folder…")
        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(browse)
        layout.addWidget(label)
        layout.addWidget(desc)
        layout.addLayout(row)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            self.edit.setText(path)


class GraphicBadge(QWidget):
    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1d344b" if self.parentWidget().parentWidget() else "#1d344b"))
        p.drawEllipse(5, 5, 54, 54)
        p.setBrush(QColor("#55d9cf"))
        p.drawEllipse(20, 20, 24, 24)
        p.setPen(QColor("#0b1020"))
        p.setFont(QFont("Segoe UI", 14, QFont.Bold))
        p.drawText(0, 0, 64, 64, Qt.AlignCenter, "✓")
        p.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        self.dark = QSettings("Encrvault", "Encrvault").value("dark", True, type=bool)
        self.mode = "encrypt"
        self.setWindowTitle("Encrvault")
        self.setMinimumSize(1050, 700)
        self.resize(1280, 820)
        self.setStyleSheet(DARK if self.dark else LIGHT)
        self.build_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 14, 12, 14)
        side.setSpacing(5)
        brand = QLabel("ENCRVAULT")
        brand.setObjectName("brand")
        side.addWidget(brand)
        sub = QLabel("SECURE MEDIA WORKSPACE")
        sub.setObjectName("eyebrow")
        side.addWidget(sub)
        side.addSpacing(10)
        self.nav_encrypt = self._nav("🔐  Encrypt media", "encrypt")
        self.nav_decrypt = self._nav("↩  Decrypt media", "decrypt")
        self.nav_preview = self._nav("▦  Secure gallery", "preview")
        side.addWidget(self.nav_encrypt)
        side.addWidget(self.nav_decrypt)
        side.addWidget(self.nav_preview)
        side.addStretch()
        security = QFrame()
        security.setObjectName("card")
        sec = QVBoxLayout(security)
        sec.setContentsMargins(12, 12, 12, 12)
        badge = GraphicBadge()
        badge.setFixedSize(64, 64)
        sec.addWidget(badge, 0, Qt.AlignCenter)
        s1 = QLabel("AES-256-GCM")
        s1.setAlignment(Qt.AlignCenter)
        s1.setStyleSheet("font-weight:800")
        s2 = QLabel("Local • authenticated • chunked")
        s2.setAlignment(Qt.AlignCenter)
        s2.setObjectName("muted")
        sec.addWidget(s1)
        sec.addWidget(s2)
        security.hide()
        side.addWidget(security)
        # `side` is a QVBoxLayout.  The root layout must receive the sidebar
        # widget that owns it, not the layout itself.
        root.addWidget(sidebar)

        content = QVBoxLayout()
        content.setSpacing(9)
        top = QHBoxLayout()
        title_box = QVBoxLayout()
        self.eyebrow = QLabel("SECURE WORKSPACE")
        self.eyebrow.setObjectName("eyebrow")
        self.title = QLabel("Encrypt your media")
        self.title.setObjectName("title")
        self.subtitle = QLabel("Protect photos and videos while preserving your originals.")
        self.subtitle.setObjectName("subtitle")
        title_box.addWidget(self.eyebrow)
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        top.addLayout(title_box, 1)
        self.theme = QPushButton("☀  Light" if self.dark else "☾  Dark")
        self.theme.clicked.connect(self.toggle_theme)
        top.addWidget(self.theme, 0, Qt.AlignTop)
        content.addLayout(top)

        self.stack = QStackedWidget()
        self.encrypt_page = self.build_transfer_page("encrypt")
        self.decrypt_page = self.build_transfer_page("decrypt")
        self.preview_page = PreviewPanel(self)
        self.stack.addWidget(self.encrypt_page)
        self.stack.addWidget(self.decrypt_page)
        self.stack.addWidget(self.preview_page)
        content.addWidget(self.stack, 1)
        root.addLayout(content, 1)

        self.nav_encrypt.setChecked(True)
        self.set_mode("encrypt")

    def _nav(self, text, mode):
        b = QPushButton(text)
        b.setObjectName("nav")
        b.setCheckable(True)
        from PySide6.QtWidgets import QStyle
        icons = {"encrypt": QStyle.SP_DialogSaveButton, "decrypt": QStyle.SP_DialogOpenButton, "preview": QStyle.SP_FileDialogDetailedView}
        b.setIcon(self.style().standardIcon(icons[mode]))
        b.setIconSize(QSize(17,17))
        b.clicked.connect(lambda: self.set_mode(mode))
        return b

    def build_transfer_page(self, mode):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        metrics = QHBoxLayout()
        for value, label in [("AES-256", "Cipher"), ("6", "Max key chars"), ("∞", "Media capacity")]:
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 13, 16, 13)
            v = QLabel(value)
            v.setObjectName("metric")
            l = QLabel(label)
            l.setObjectName("metricLabel")
            box.addWidget(v)
            box.addWidget(l)
            metrics.addWidget(card)
        root.addLayout(metrics)

        key = QFrame()
        key.setObjectName("card")
        kl = QVBoxLayout(key)
        kl.setContentsMargins(14, 12, 14, 12)
        heading = QLabel("Access key")
        heading.setStyleSheet("font-size:16px;font-weight:800")
        hint = QLabel("Use a 6-character key. The key is processed locally and is never written to disk.")
        hint.setObjectName("muted")
        row = QHBoxLayout()
        password = QLineEdit()
        password.setMaxLength(6)
        password.setEchoMode(QLineEdit.Password)
        password.setPlaceholderText("Exactly 6 characters")
        show = QPushButton("Show")
        show.setCheckable(True)
        show.toggled.connect(lambda x: password.setEchoMode(QLineEdit.Normal if x else QLineEdit.Password))
        row.addWidget(password, 1)
        row.addWidget(show)
        kl.addWidget(heading)
        kl.addWidget(hint)
        kl.addLayout(row)
        root.addWidget(key)
        page.password = password

        grid = QGridLayout()
        grid.setSpacing(14)
        page.input_card = FolderCard("Input folder", "Source media for encryption or .aesvault files for decryption.")
        page.output_card = FolderCard("Output folder", "A separate destination keeps originals untouched.")
        grid.addWidget(page.input_card, 0, 0)
        grid.addWidget(page.output_card, 0, 1)
        root.addLayout(grid)

        performance = QFrame()
        performance.setObjectName("card")
        pl = QHBoxLayout(performance)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.addWidget(QLabel("Parallel workers"))
        page.workers = QSpinBox()
        cpu = os.cpu_count() or 1
        page.workers.setRange(1, cpu)
        page.workers.setValue(min(cpu, 4))
        pl.addWidget(page.workers)
        note = QLabel("Independent files are processed concurrently • chunked I/O limits memory usage")
        note.setObjectName("muted")
        pl.addWidget(note, 1)
        root.addWidget(performance)

        status = QLabel("Ready")
        status.setObjectName("muted")
        progress = QProgressBar()
        progress.setValue(0)
        root.addWidget(status)
        root.addWidget(progress)
        page.status = status
        page.progress = progress

        actions = QHBoxLayout()
        start = QPushButton("Start encryption" if mode == "encrypt" else "Start decryption")
        start.setObjectName("primary")
        cancel = QPushButton("Cancel")
        cancel.setObjectName("danger")
        cancel.setEnabled(False)
        start.clicked.connect(lambda: self.start_job(mode))
        cancel.clicked.connect(self.cancel_job)
        actions.addWidget(start, 1)
        actions.addWidget(cancel)
        root.addLayout(actions)
        page.start = start
        page.cancel = cancel
        return page

    def set_mode(self, mode):
        if self.worker:
            return
        self.mode = mode
        self.nav_encrypt.setChecked(mode == "encrypt")
        self.nav_decrypt.setChecked(mode == "decrypt")
        self.nav_preview.setChecked(mode == "preview")
        idx = {"encrypt": 0, "decrypt": 1, "preview": 2}[mode]
        self.stack.setCurrentIndex(idx)
        if mode == "encrypt":
            self.title.setText("Encrypt your media")
            self.subtitle.setText("Protect photos and videos while preserving your originals.")
        elif mode == "decrypt":
            self.title.setText("Restore encrypted media")
            self.subtitle.setText("Authenticate .aesvault files and restore them to a separate folder.")
        else:
            self.title.setText("Secure media gallery")
            self.subtitle.setText("Browse encrypted photos and videos. Full preview happens only when you open an item.")

    def toggle_theme(self):
        self.dark = not self.dark
        QSettings("Encrvault", "Encrvault").setValue("dark", self.dark)
        self.setStyleSheet(DARK if self.dark else LIGHT)
        self.theme.setText("☀  Light" if self.dark else "☾  Dark")

    def start_job(self, mode):
        page = self.encrypt_page if mode == "encrypt" else self.decrypt_page
        inp = page.input_card.edit.text().strip()
        out = page.output_card.edit.text().strip()
        password = page.password.text()
        if not inp or not Path(inp).is_dir():
            QMessageBox.warning(self, "Input folder", "Select a valid input folder.")
            return
        if not out:
            QMessageBox.warning(self, "Output folder", "Select an output folder.")
            return
        if Path(inp).resolve() == Path(out).resolve():
            QMessageBox.warning(self, "Folders", "Input and output folders must differ.")
            return
        if len(password) != 6:
            QMessageBox.warning(self, "Access key", "The key must be exactly 6 characters.")
            return
        Path(out).mkdir(parents=True, exist_ok=True)
        self.active_page = page
        page.start.setEnabled(False)
        page.cancel.setEnabled(True)
        page.password.setEnabled(False)
        page.progress.setValue(0)
        page.status.setText("Starting…")
        self.thread = QThread(self)
        self.worker = FileWorker(mode, inp, out, password, page.workers.value())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.file_done.connect(lambda name: page.status.setText(f"Completed: {Path(name).name}"))
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.thread_done)
        self.thread.start()

    def on_progress(self, done, total, name):
        page = self.active_page
        value = int(done * 100 / total) if total else 0
        page.progress.setValue(value)
        action = "Decrypting" if self.mode == "decrypt" else "Encrypting"
        page.status.setText(f"{action} {Path(name).name} • {value}%")

    def on_error(self, message):
        self.active_page.status.setText("Completed with errors.")
        QMessageBox.warning(self, "File processing error", message)

    def on_finished(self, successful, failed):
        page = self.active_page
        page.cancel.setEnabled(False)
        page.start.setEnabled(True)
        page.password.setEnabled(True)
        if failed == 0 and successful:
            page.progress.setValue(100)
        page.status.setText(f"Finished • {successful} succeeded • {failed} failed")

    def cancel_job(self):
        if self.worker:
            self.worker.cancel()
            self.active_page.cancel.setEnabled(False)
            self.active_page.status.setText("Stopping active work…")

    def thread_done(self):
        self.worker = None
        self.thread = None

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel()
            QMessageBox.information(self, "Job running", "Cancellation was requested. Please wait for active files to finish.")
            event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
