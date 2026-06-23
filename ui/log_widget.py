from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtGui import QTextCursor
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

class LogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log)

        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("Limpiar")
        self.btn_copy = QPushButton("Copiar")
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.btn_clear.clicked.connect(self.clear)
        self.btn_copy.clicked.connect(self.copy_all)

    def append_line(self, text: str, level: str = "info"):
        """
        Añade una línea con color según level (info/warning/error).
        Hace scroll automático a la última línea.
        """
        color = {
            "info": "#FFFFFF",
            "warning": "#FFD54F",
            "error": "#FF6B6B",
        }.get(level, "#FFFFFF")
        # usar HTML simple
        safe = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log.append(f'<span style="color:{color};">{safe}</span>')
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self):
        self.log.clear()

    def copy_all(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log.toPlainText())
