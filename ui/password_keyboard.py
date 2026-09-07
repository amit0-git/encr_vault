from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout


class VirtualPasswordLineEdit(QLineEdit):
    """Password editor that rejects OS keyboard and clipboard input.

    Text can only be inserted through insert_virtual_text(), which is used by
    the application's on-screen keyboard.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(False)
        self.setReadOnly(True)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.setMaxLength(6)  # Intentionally preserved from the existing app.

    def keyPressEvent(self, event: QKeyEvent):
        event.ignore()

    def keyReleaseEvent(self, event: QKeyEvent):
        event.ignore()

    def inputMethodEvent(self, event):
        event.ignore()

    def insertFromMimeData(self, source):
        # QLineEdit normally obtains clipboard text through this path.
        return

    def canInsertFromMimeData(self, source):
        return False

    def dragEnterEvent(self, event):
        event.ignore()

    def dragMoveEvent(self, event):
        event.ignore()

    def dropEvent(self, event):
        event.ignore()

    def insert_virtual_text(self, text: str):
        if not text:
            return
        current = self.text()
        room = max(0, self.maxLength() - len(current))
        if room:
            self.setText(current + text[:room])
            self.setCursorPosition(len(self.text()))

    def virtual_backspace(self):
        self.setText(self.text()[:-1])
        self.setCursorPosition(len(self.text()))

    def virtual_clear(self):
        self.clear()


class OnScreenKeyboard(QDialog):
    """Compact mouse/touch keyboard for virtual-only password entry."""

    def __init__(self, target: VirtualPasswordLineEdit, parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle("On-Screen Keyboard")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumWidth(430)
        self._shift = False
        self._buttons: list[QPushButton] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(7)

        rows = [
            list("1234567890"),
            list("qwertyuiop"),
            list("asdfghjkl"),
            list("zxcvbnm"),
            list("!@#$%^&*()-_=+[]{};:',.<>/?\\|`~\""),
        ]
        for chars in rows:
            row = QHBoxLayout()
            row.setSpacing(5)
            for char in chars:
                button = QPushButton(char)
                button.setMinimumHeight(38)
                button.clicked.connect(lambda checked=False, c=char: self._character(c))
                row.addWidget(button, 1)
                self._buttons.append(button)
            root.addLayout(row)

        actions = QHBoxLayout()
        shift = QPushButton("Shift")
        shift.setCheckable(True)
        shift.clicked.connect(self._toggle_shift)
        back = QPushButton("⌫ Backspace")
        back.clicked.connect(self.target.virtual_backspace)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.target.virtual_clear)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        for widget in (shift, back, clear, done):
            actions.addWidget(widget, 1)
        root.addLayout(actions)
        self._shift_button = shift

    def _toggle_shift(self, checked: bool):
        self._shift = checked
        self._shift_button.setText("Shift ON" if checked else "Shift")
        for button in self._buttons:
            text = button.text()
            if len(text) == 1 and text.isalpha():
                button.setText(text.upper() if checked else text.lower())

    def _character(self, char: str):
        self.target.insert_virtual_text(char.upper() if self._shift and char.isalpha() else char)
        if self._shift:
            self._shift = False
            self._shift_button.setChecked(False)
            self._toggle_shift(False)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
