from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from core.worker import FileWorker


DARK = """
QMainWindow,QWidget{background:#0e111a;color:#e9edf7;font-family:"Segoe UI";font-size:13px}
QFrame#card{background:#151a26;border:1px solid #242b3a;border-radius:14px}
QLabel#brand{font-size:22px;font-weight:700}
QLabel#title{font-size:30px;font-weight:700}
QLabel#muted{color:#929bad}
QLineEdit,QSpinBox{background:#0b0e15;border:1px solid #2b3344;border-radius:9px;padding:10px;color:#e9edf7}
QLineEdit:focus,QSpinBox:focus{border:1px solid #2ec5ff}
QPushButton{background:#20283a;border:1px solid #303a50;border-radius:9px;padding:10px 16px;font-weight:600}
QPushButton:hover{background:#29344a}
QPushButton#primary{background:#1f8fb7;border:none;min-height:44px;font-size:15px}
QPushButton#primary:hover{background:#27a6d3}
QPushButton:disabled{color:#687184}
QProgressBar{background:#0a0d13;border:none;border-radius:6px;height:12px}
QProgressBar::chunk{background:#2ec5ff;border-radius:6px}
"""

LIGHT = """
QMainWindow,QWidget{background:#f5f7fb;color:#182033;font-family:"Segoe UI";font-size:13px}
QFrame#card{background:#ffffff;border:1px solid #dfe4ee;border-radius:14px}
QLabel#brand{font-size:22px;font-weight:700}
QLabel#title{font-size:30px;font-weight:700}
QLabel#muted{color:#667085}
QLineEdit,QSpinBox{background:#f8fafc;border:1px solid #cbd3e1;border-radius:9px;padding:10px;color:#182033}
QLineEdit:focus,QSpinBox:focus{border:1px solid #178ab5}
QPushButton{background:#e9edf4;border:1px solid #cbd3e1;border-radius:9px;padding:10px 16px;font-weight:600}
QPushButton:hover{background:#dde4ef}
QPushButton#primary{background:#178ab5;color:white;border:none;min-height:44px;font-size:15px}
QPushButton#primary:hover{background:#126f92}
QProgressBar{background:#e5e9f0;border:none;border-radius:6px;height:12px}
QProgressBar::chunk{background:#178ab5;border-radius:6px}
"""


class FolderCard(QFrame):
    def __init__(self, title, hint, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setStyleSheet("font-size:18px;font-weight:700")
        description = QLabel(hint)
        description.setObjectName("muted")
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText("Select a folder…")
        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(browse)
        layout.addWidget(label)
        layout.addWidget(description)
        layout.addLayout(row)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            self.edit.setText(path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.worker = None
        self.dark = True
        self.mode = "encrypt"
        self.setWindowTitle("AES Vault — Secure Media Encryption")
        self.setMinimumSize(900, 650)
        self.resize(1180, 800)
        self.setStyleSheet(DARK)
        self.build_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        header = QHBoxLayout()
        brand = QLabel("AES VAULT")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        self.theme = QPushButton("☀  Light")
        self.theme.setCheckable(True)
        self.theme.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme)
        root.addLayout(header)

        title_row = QHBoxLayout()
        title = QLabel("Encrypt media")
        title.setObjectName("title")
        self.title = title
        title_row.addWidget(title)
        title_row.addStretch()
        self.encrypt_tab = QPushButton("Encrypt")
        self.decrypt_tab = QPushButton("Decrypt")
        self.encrypt_tab.clicked.connect(lambda: self.set_mode("encrypt"))
        self.decrypt_tab.clicked.connect(lambda: self.set_mode("decrypt"))
        title_row.addWidget(self.encrypt_tab)
        title_row.addWidget(self.decrypt_tab)
        root.addLayout(title_row)

        self.subtitle = QLabel("Batch-protect photos and videos without modifying your originals.")
        self.subtitle.setObjectName("muted")
        root.addWidget(self.subtitle)

        key = QFrame()
        key.setObjectName("card")
        key_layout = QVBoxLayout(key)
        key_layout.setContentsMargins(20, 16, 20, 16)
        key_layout.addWidget(QLabel("Encryption key / password"))
        key_row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Strong password — Argon2id derives the AES-256 key.")
        self.show_password = QPushButton("Show")
        self.show_password.setCheckable(True)
        self.show_password.toggled.connect(
            lambda x: self.password.setEchoMode(
                QLineEdit.Normal if x else QLineEdit.Password
            )
        )
        key_row.addWidget(self.password, 1)
        key_row.addWidget(self.show_password)
        key_layout.addLayout(key_row)
        root.addWidget(key)

        grid = QGridLayout()
        grid.setSpacing(16)
        self.input_card = FolderCard(
            "Input folder",
            "Encrypt mode: source media. Decrypt mode: .aesvault files."
        )
        self.output_card = FolderCard(
            "Output folder",
            "Original files are never overwritten."
        )
        grid.addWidget(self.input_card, 0, 0)
        grid.addWidget(self.output_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        performance = QFrame()
        performance.setObjectName("card")
        p = QHBoxLayout(performance)
        p.setContentsMargins(20, 14, 20, 14)
        p.addWidget(QLabel("Parallel workers"))
        self.workers = QSpinBox()
        cpu = os.cpu_count() or 1
        self.workers.setRange(1, cpu)
        self.workers.setValue(min(cpu, 4))
        p.addWidget(self.workers)
        note = QLabel(
            "Concurrent file processing • bounded memory • CPU-aware"
        )
        note.setObjectName("muted")
        p.addWidget(note, 1)
        root.addWidget(performance)

        self.status = QLabel("Ready")
        self.status.setObjectName("muted")
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)

        actions = QHBoxLayout()
        self.start = QPushButton("Start encryption")
        self.start.setObjectName("primary")
        self.start.clicked.connect(self.start_job)
        self.cancel = QPushButton("Cancel")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_job)
        actions.addWidget(self.start, 1)
        actions.addWidget(self.cancel)
        root.addLayout(actions)

        footer = QLabel(
            "AES-256-GCM • Authenticated chunks • Local processing • Originals preserved"
        )
        footer.setObjectName("muted")
        root.addWidget(footer)

        self.set_mode("encrypt")

    def set_mode(self, mode):
        if self.worker:
            return
        self.mode = mode
        decrypt = mode == "decrypt"
        self.title.setText("Decrypt media" if decrypt else "Encrypt media")
        self.subtitle.setText(
            "Restore authenticated .aesvault files to their original media."
            if decrypt else
            "Batch-protect photos and videos without modifying your originals."
        )
        self.start.setText("Start decryption" if decrypt else "Start encryption")
        self.input_card.edit.clear()
        self.output_card.edit.clear()
        self.progress.setValue(0)
        self.status.setText("Ready")
        self.encrypt_tab.setEnabled(decrypt)
        self.decrypt_tab.setEnabled(not decrypt)

    def toggle_theme(self):
        self.dark = not self.dark
        self.setStyleSheet(DARK if self.dark else LIGHT)
        self.theme.setText("☀  Light" if self.dark else "☾  Dark")

    def start_job(self):
        inp = self.input_card.edit.text().strip()
        out = self.output_card.edit.text().strip()
        password = self.password.text()

        if not inp or not Path(inp).is_dir():
            QMessageBox.warning(self, "Input folder", "Select a valid input folder.")
            return
        if not out:
            QMessageBox.warning(self, "Output folder", "Select an output folder.")
            return
        if Path(inp).resolve() == Path(out).resolve():
            QMessageBox.warning(self, "Folders", "Input and output folders must differ.")
            return
        if len(password) < 12:
            QMessageBox.warning(
                self, "Weak password",
                "Use a strong password of at least 12 characters."
            )
            return

        Path(out).mkdir(parents=True, exist_ok=True)
        self.start.setEnabled(False)
        self.cancel.setEnabled(True)
        self.password.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Starting…")

        self.thread = QThread(self)
        self.worker = FileWorker(
            self.mode, inp, out, password, self.workers.value()
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.file_done.connect(
            lambda name: self.status.setText(f"Completed: {Path(name).name}")
        )
        self.worker.error.connect(self.on_error)
        self.worker.cancelled.connect(
            lambda: self.status.setText("Cancellation requested…")
        )
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.thread_done)
        self.thread.start()

    def on_progress(self, done, total, name):
        value = int(done * 100 / total) if total else 0
        self.progress.setValue(value)
        self.status.setText(
            f"{'Decrypting' if self.mode == 'decrypt' else 'Encrypting'} "
            f"{Path(name).name} • {value}%"
        )

    def on_error(self, message):
        self.status.setText("Completed with errors.")
        QMessageBox.warning(self, "File processing error", message)

    def on_finished(self, successful, failed):
        self.cancel.setEnabled(False)
        self.start.setEnabled(True)
        self.password.setEnabled(True)
        self.progress.setValue(100 if failed == 0 and successful else self.progress.value())
        self.status.setText(
            f"Finished • {successful} succeeded • {failed} failed"
        )

    def cancel_job(self):
        if self.worker:
            self.worker.cancel()
            self.cancel.setEnabled(False)
            self.status.setText("Stopping active work…")

    def thread_done(self):
        self.worker = None
        self.thread = None

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel()
            QMessageBox.information(
                self, "Job running",
                "Cancellation was requested. Please wait for active files to finish."
            )
            event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
