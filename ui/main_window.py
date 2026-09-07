from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from core.worker import EncryptionWorker


STYLE = """
QMainWindow, QWidget {
    background: #0e111a;
    color: #e9edf7;
    font-family: "Segoe UI";
    font-size: 13px;
}
QFrame#card {
    background: #151a26;
    border: 1px solid #242b3a;
    border-radius: 14px;
}
QLabel#brand {
    font-size: 22px;
    font-weight: 700;
}
QLabel#title {
    font-size: 30px;
    font-weight: 700;
}
QLabel#muted {
    color: #929bad;
}
QLineEdit, QSpinBox {
    background: #0b0e15;
    border: 1px solid #2b3344;
    border-radius: 9px;
    padding: 10px;
    color: #e9edf7;
}
QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #2ec5ff;
}
QPushButton {
    background: #20283a;
    border: 1px solid #303a50;
    border-radius: 9px;
    padding: 10px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background: #29344a;
}
QPushButton#primary {
    background: #1f8fb7;
    border: none;
    min-height: 44px;
    font-size: 15px;
}
QPushButton#primary:hover {
    background: #27a6d3;
}
QPushButton:disabled {
    color: #687184;
}
QProgressBar {
    background: #0a0d13;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2ec5ff;
    border-radius: 6px;
}
"""

class FolderRow(QFrame):
    def __init__(self, title: str, placeholder: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setStyleSheet("font-size:18px;font-weight:700;")
        hint = QLabel(placeholder)
        hint.setObjectName("muted")
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText("Select a folder…")
        button = QPushButton("Browse")
        button.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(button)
        layout.addWidget(label)
        layout.addWidget(hint)
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
        self.setWindowTitle("AES Vault — Secure Media Encryption")
        self.setMinimumSize(920, 680)
        self.resize(1180, 800)
        self.setStyleSheet(STYLE)
        self.build_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        header = QHBoxLayout()
        brand = QLabel("AES VAULT")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        security = QLabel("●  AES-256-GCM  •  Local processing")
        security.setStyleSheet("color:#6ee7a0;font-weight:600;")
        header.addWidget(security)
        root.addLayout(header)

        title = QLabel("Encrypt media")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QLabel("Batch-protect photos and videos without modifying your originals.")
        sub.setObjectName("muted")
        root.addWidget(sub)

        key_card = QFrame()
        key_card.setObjectName("card")
        key_layout = QVBoxLayout(key_card)
        key_layout.setContentsMargins(20, 18, 20, 18)
        key_label = QLabel("Encryption key / password")
        key_label.setStyleSheet("font-weight:700;")
        key_layout.addWidget(key_label)
        key_row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Use a strong password; Argon2id derives the AES-256 key.")
        self.show_key = QPushButton("Show")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(
            lambda checked: self.password.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        key_row.addWidget(self.password, 1)
        key_row.addWidget(self.show_key)
        key_layout.addLayout(key_row)
        root.addWidget(key_card)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self.input_row = FolderRow(
            "Input folder",
            "Supported: JPG, PNG, HEIC, MP4, MOV, MKV and common media formats.",
        )
        self.output_row = FolderRow(
            "Output folder",
            "Encrypted files preserve the input folder structure and receive .aesvault.",
        )
        grid.addWidget(self.input_row, 0, 0)
        grid.addWidget(self.output_row, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        perf = QFrame()
        perf.setObjectName("card")
        perf_layout = QHBoxLayout(perf)
        perf_layout.setContentsMargins(20, 16, 20, 16)
        workers_label = QLabel("Parallel workers")
        workers_label.setStyleSheet("font-weight:700;")
        self.workers = QSpinBox()
        cpu = os.cpu_count() or 1
        self.workers.setRange(1, max(1, cpu))
        self.workers.setValue(max(1, min(cpu, 4)))
        self.workers.setToolTip("Number of files encrypted concurrently.")
        perf_layout.addWidget(workers_label)
        perf_layout.addWidget(self.workers)
        perf_layout.addSpacing(20)
        perf_hint = QLabel(
            "Files are processed concurrently with bounded memory. "
            "For large media, more workers are not always faster."
        )
        perf_hint.setObjectName("muted")
        perf_layout.addWidget(perf_hint, 1)
        root.addWidget(perf)

        self.progress_label = QLabel("Ready")
        self.progress_label.setObjectName("muted")
        root.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.start = QPushButton("Start encryption")
        self.start.setObjectName("primary")
        self.start.clicked.connect(self.start_encryption)
        self.cancel = QPushButton("Cancel")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_encryption)

        actions = QHBoxLayout()
        actions.addWidget(self.start, 1)
        actions.addWidget(self.cancel)
        root.addLayout(actions)

        footer = QLabel("Original files are read-only from AES Vault. No network upload is performed.")
        footer.setObjectName("muted")
        root.addWidget(footer)

    def start_encryption(self):
        input_dir = self.input_row.edit.text().strip()
        output_dir = self.output_row.edit.text().strip()
        password = self.password.text()

        if not input_dir or not Path(input_dir).is_dir():
            QMessageBox.warning(self, "Input folder", "Please select a valid input folder.")
            return
        if not output_dir:
            QMessageBox.warning(self, "Output folder", "Please select an output folder.")
            return
        if Path(input_dir).resolve() == Path(output_dir).resolve():
            QMessageBox.warning(
                self, "Output folder",
                "Input and output folders must be different."
            )
            return
        if len(password) < 12:
            QMessageBox.warning(
                self, "Weak key",
                "Use a strong password of at least 12 characters."
            )
            return

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        self.start.setEnabled(False)
        self.cancel.setEnabled(True)
        self.progress.setValue(0)
        self.progress_label.setText("Scanning media…")

        self.thread = QThread(self)
        self.worker = EncryptionWorker(
            input_dir,
            output_dir,
            password,
            self.workers.value(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.file_done.connect(
            lambda name: self.progress_label.setText(f"Encrypted: {Path(name).name}")
        )
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.on_finished)
        self.worker.cancelled.connect(
            lambda: self.progress_label.setText("Cancellation requested…")
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.cleanup_thread)
        self.thread.start()

    def on_progress(self, done, total, filename):
        percent = int(done * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.progress_label.setText(f"Encrypting {Path(filename).name}  •  {percent}%")

    def on_error(self, message):
        self.progress_label.setText("Completed with errors.")
        QMessageBox.warning(self, "Encryption error", message)

    def on_finished(self, successful, failed):
        self.cancel.setEnabled(False)
        self.start.setEnabled(True)
        self.progress.setValue(100 if failed == 0 else self.progress.value())
        self.progress_label.setText(
            f"Finished • {successful} encrypted • {failed} failed"
        )
        self.worker = None
        self.thread = None

    def cancel_encryption(self):
        if self.worker:
            self.worker.cancel()
            self.cancel.setEnabled(False)
            self.progress_label.setText("Stopping after active files finish…")

    def cleanup_thread(self):
        self.thread = None

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel()
            event.ignore()
            QMessageBox.information(
                self,
                "Encryption running",
                "Cancellation has been requested. Close the application after the job finishes.",
            )
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
