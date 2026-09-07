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
QLabel#previewSessionCaption{color:#6f7e96;font-size:9px;font-weight:800;letter-spacing:1px}
QLabel#previewSidebarTimer{background:#101b2e;border:1px solid #2f496a;border-radius:12px;padding:8px 10px;color:#78e7db;font-weight:800;font-size:12px;letter-spacing:.2px}
QLabel#previewCacheStatus{background:#0d1627;border:1px solid #253652;border-radius:10px;padding:8px;color:#a8b5c9;font-size:10px;line-height:1.25}
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
QLabel#previewSessionCaption{color:#7b8799;font-size:9px;font-weight:800;letter-spacing:1px}
QLabel#previewCacheStatus{background:#f7f9fc;border:1px solid #dce3ee;border-radius:10px;padding:8px;color:#66738a;font-size:10px;line-height:1.25}
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        label = QLabel(title)
        label.setStyleSheet("font-size:13px;font-weight:800")
        desc = QLabel(hint)
        desc.setObjectName("muted")
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText("Choose a folder…")
        self.edit.setMinimumHeight(40)
        browse = QPushButton("Browse")
        browse.setMinimumHeight(40)
        browse.setFixedWidth(78)
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.setSpacing(7)
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

        # One global preview-session timer. It is hidden until a secure
        # preview session starts and is removed/hidden when the session ends.
        timer_caption = QLabel("PREVIEW SESSION")
        timer_caption.setObjectName("previewSessionCaption")
        timer_caption.setAlignment(Qt.AlignCenter)
        side.addWidget(timer_caption)
        self.preview_timer_widget = QLabel()
        self.preview_timer_widget.setObjectName("previewSidebarTimer")
        self.preview_timer_widget.setAlignment(Qt.AlignCenter)
        self.preview_timer_widget.setMinimumHeight(44)
        self.preview_timer_widget.setMaximumHeight(50)
        self.preview_timer_widget.setToolTip("Global preview time remaining")
        self.preview_timer_widget.setText("Preview  00:00")
        self.preview_timer_widget.hide()
        side.addWidget(self.preview_timer_widget)

        self.preview_cache_widget = QLabel("Cache ready  •  0 cached  •  0.0 / 90 MB  •  0 loading")
        self.preview_cache_widget.setObjectName("previewCacheStatus")
        self.preview_cache_widget.setWordWrap(True)
        self.preview_cache_widget.setAlignment(Qt.AlignCenter)
        self.preview_cache_widget.setMinimumHeight(58)
        self.preview_cache_widget.setToolTip("Live thumbnail RAM cache activity")
        side.addWidget(self.preview_cache_widget)
        side.addSpacing(10)
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
        self.preview_page.preview_timer_changed.connect(self._show_preview_sidebar_timer)
        self.preview_page.preview_timer_finished.connect(self._hide_preview_sidebar_timer)
        self.preview_page.cache_status_changed.connect(self._show_preview_cache_status)
        self.stack.addWidget(self.encrypt_page)
        self.stack.addWidget(self.decrypt_page)
        self.stack.addWidget(self.preview_page)
        content.addWidget(self.stack, 1)
        root.addLayout(content, 1)

        self.nav_encrypt.setChecked(True)
        self.set_mode("encrypt")

    def _show_preview_sidebar_timer(self, seconds):
        seconds = max(0, int(seconds))
        minutes, secs = divmod(seconds, 60)
        self.preview_timer_widget.setText(f"Preview  {minutes:02d}:{secs:02d}")
        self.preview_timer_widget.show()

    def _show_preview_cache_status(self, text):
        self.preview_cache_widget.setText(text)
        self.preview_cache_widget.show()

    def _hide_preview_sidebar_timer(self):
        self.preview_timer_widget.clear()
        self.preview_timer_widget.hide()

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
        # Balanced compact layout: fewer elements, but enough spacing and hierarchy
        # that the transfer screen still feels like a finished desktop application.
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(14)

        # Security / key card
        security = QFrame()
        security.setObjectName("card")
        sec = QVBoxLayout(security)
        sec.setContentsMargins(18, 15, 18, 15)
        sec.setSpacing(10)

        sec_head = QHBoxLayout()
        key_title = QLabel("Access key")
        key_title.setStyleSheet("font-size:15px;font-weight:800")
        key_hint = QLabel("6 characters • used locally")
        key_hint.setObjectName("muted")
        sec_head.addWidget(key_title)
        sec_head.addSpacing(8)
        sec_head.addWidget(key_hint)
        sec_head.addStretch()
        workers_label = QLabel("Parallel workers")
        workers_label.setObjectName("muted")
        sec_head.addWidget(workers_label)
        workers = QSpinBox()
        cpu = os.cpu_count() or 1
        workers.setRange(1, cpu)
        workers.setValue(min(cpu, 4))
        workers.setFixedWidth(68)
        sec_head.addWidget(workers)
        sec.addLayout(sec_head)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        password = QLineEdit()
        password.setMaxLength(12)
        password.setEchoMode(QLineEdit.Password)
        password.setPlaceholderText("Enter access key (4–12 characters)")
        password.setMinimumHeight(42)
        show = QPushButton("Show")
        show.setCheckable(True)
        show.setFixedWidth(72)
        show.toggled.connect(lambda x: password.setEchoMode(QLineEdit.Normal if x else QLineEdit.Password))
        key_row.addWidget(password, 1)
        key_row.addWidget(show)
        sec.addLayout(key_row)
        root.addWidget(security)
        page.password = password
        page.workers = workers

        # Folder selection card
        folders = QFrame()
        folders.setObjectName("card")
        fl = QVBoxLayout(folders)
        fl.setContentsMargins(18, 15, 18, 15)
        fl.setSpacing(10)
        folder_title = QLabel("Folders")
        folder_title.setStyleSheet("font-size:15px;font-weight:800")
        fl.addWidget(folder_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        page.input_card = FolderCard(
            "Input folder",
            "Photos and videos" if mode == "encrypt" else "Encrypted .aesvault files",
        )
        page.output_card = FolderCard(
            "Output folder",
            "Encrypted copies" if mode == "encrypt" else "Restored media",
        )
        grid.addWidget(page.input_card, 0, 0)
        grid.addWidget(page.output_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        fl.addLayout(grid)
        root.addWidget(folders)

        # Progress is deliberately quiet until a job starts.
        progress_card = QFrame()
        progress_card.setObjectName("card")
        pl = QVBoxLayout(progress_card)
        pl.setContentsMargins(18, 13, 18, 13)
        pl.setSpacing(8)
        status_row = QHBoxLayout()
        status = QLabel("Ready to start")
        status.setObjectName("muted")
        percent = QLabel("0%")
        percent.setObjectName("muted")
        status_row.addWidget(status)
        status_row.addStretch()
        status_row.addWidget(percent)
        pl.addLayout(status_row)
        progress = QProgressBar()
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setMinimumHeight(9)
        pl.addWidget(progress)
        root.addWidget(progress_card)
        page.status = status
        page.percent = percent
        page.progress = progress

        # Primary action is visually dominant; cancel remains secondary.
        actions = QHBoxLayout()
        actions.setSpacing(10)
        start = QPushButton("Encrypt files" if mode == "encrypt" else "Decrypt files")
        start.setObjectName("primary")
        start.setMinimumHeight(46)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("danger")
        cancel.setMinimumHeight(46)
        cancel.setFixedWidth(110)
        cancel.setEnabled(False)
        start.clicked.connect(lambda: self.start_job(mode))
        cancel.clicked.connect(self.cancel_job)
        actions.addWidget(start, 1)
        actions.addWidget(cancel)
        root.addLayout(actions)
        root.addStretch(1)
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
        if not 4 <= len(password) <= 12:
            QMessageBox.warning(self, "Access key", "The key must be 4–12 characters long.")
            return
        Path(out).mkdir(parents=True, exist_ok=True)
        self.active_page = page
        self._job_errors = []
        page.start.setEnabled(False)
        page.cancel.setEnabled(True)
        page.password.setEnabled(False)
        page.progress.setValue(0)
        page.percent.setText("0%")
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
        page.percent.setText(f"{value}%")
        action = "Decrypting" if self.mode == "decrypt" else "Encrypting"
        page.status.setText(f"{action} {Path(name).name} • {value}%")

    def on_error(self, message):
        """Collect worker errors and show a single dialog when the job ends.

        Decryption can fail for every file when the access key is wrong. Showing
        one QMessageBox per failed file makes the UI unusable, so errors are
        aggregated and presented once after processing finishes.
        """
        if not hasattr(self, "_job_errors"):
            self._job_errors = []
        self._job_errors.append(str(message))
        if self.active_page:
            self.active_page.status.setText("Processing completed with errors…")

    def on_finished(self, successful, failed):
        page = self.active_page
        page.cancel.setEnabled(False)
        page.start.setEnabled(True)
        page.password.setEnabled(True)
        if failed == 0 and successful:
            page.progress.setValue(100)
            page.percent.setText("100%")
        page.status.setText(f"Finished • {successful} succeeded • {failed} failed")

        errors = getattr(self, "_job_errors", [])
        if errors:
            # A wrong key normally causes the same authentication failure for
            # every encrypted file. Collapse that into one useful message.
            if self.mode == "decrypt" and failed:
                title = "Decryption failed"
                if any("InvalidTag" in e or "authentication" in e.lower() or "authenticate" in e.lower() for e in errors):
                    detail = (
                        "The access key is incorrect, or the encrypted file "
                        "has been modified/corrupted. No decrypted files were created for failed items."
                    )
                else:
                    detail = f"{failed} file(s) could not be decrypted."
            else:
                title = "File processing errors"
                # Keep the dialog compact even for many independent failures.
                shown = errors[:8]
                detail = "\n".join(f"• {e}" for e in shown)
                if len(errors) > len(shown):
                    detail += f"\n• …and {len(errors) - len(shown)} more error(s)."
            QMessageBox.warning(self, title, detail)
            self._job_errors = []

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
