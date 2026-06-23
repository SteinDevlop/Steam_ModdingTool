import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QFileDialog, QHBoxLayout, QLabel, QMessageBox
)
from PyQt6.QtCore import Qt
import subprocess

SETTINGS_FILE = Path("config") / "settings.json"

class OptionsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load()

    def _init_ui(self):
        v = QVBoxLayout(self)
        form = QFormLayout()

        # steamcmd path
        self.steamcmd_edit = QLineEdit()
        btn_browse_sc = QPushButton("…")
        btn_browse_sc.clicked.connect(self._browse_steamcmd)
        row_sc = QWidget()
        row_sc_l = QHBoxLayout(row_sc)
        row_sc_l.setContentsMargins(0,0,0,0)
        row_sc_l.addWidget(self.steamcmd_edit)
        row_sc_l.addWidget(btn_browse_sc)
        form.addRow("steamcmd path", row_sc)

        # download base dir
        self.download_dir = QLineEdit()
        btn_browse = QPushButton("…")
        btn_browse.clicked.connect(self._browse_download_dir)
        row2 = QWidget()
        row2_l = QHBoxLayout(row2)
        row2_l.setContentsMargins(0,0,0,0)
        row2_l.addWidget(self.download_dir)
        row2_l.addWidget(btn_browse)
        form.addRow("Download base dir", row2)

        self.btn_save = QPushButton("Guardar")
        self.btn_test = QPushButton("Probar steamcmd")
        h = QHBoxLayout()
        h.addWidget(self.btn_save)
        h.addWidget(self.btn_test)
        v.addLayout(form)
        v.addLayout(h)

        self.btn_save.clicked.connect(self._save)
        self.btn_test.clicked.connect(self._test_steamcmd)

    def _browse_steamcmd(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleccionar steamcmd ejecutable")
        if f:
            self.steamcmd_edit.setText(f)

    def _browse_download_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if d:
            self.download_dir.setText(d)

    def _load(self):
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        else:
            data = {}
        self.steamcmd_edit.setText(data.get("steamcmd_path",""))
        self.download_dir.setText(data.get("download_base_dir",""))

    def _save(self):
        data = {
            "steamcmd_path": self.steamcmd_edit.text().strip(),
            "download_base_dir": self.download_dir.text().strip()
        }
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        QMessageBox.information(self, "Guardado", "Settings guardados.")

    def _test_steamcmd(self):
        path = self.steamcmd_edit.text().strip() or "steamcmd"
        try:
            proc = subprocess.run([path, "+quit"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10, text=True)
            if proc.returncode == 0:
                QMessageBox.information(self, "steamcmd", "steamcmd ejecutado correctamente.")
            else:
                QMessageBox.warning(self, "steamcmd", f"steamcmd retornó código {proc.returncode}.\nSalida:\n{proc.stdout[:1000]}")
        except FileNotFoundError:
            QMessageBox.warning(self, "steamcmd", f"steamcmd no encontrado en: {path}")
        except Exception as e:
            QMessageBox.warning(self, "steamcmd", f"Error al ejecutar steamcmd: {e}")
