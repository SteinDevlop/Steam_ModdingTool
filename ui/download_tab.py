"""
Pestaña de Descarga de Workshop
================================
Permite descargar un item del Workshop de Steam a partir de su enlace.
Usa steamcmd con +workshop_download_item bajo el hood.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from ui.log_widget import LogWidget
from core import workshop as workshop_core
from core.profile_manager import get_active_profile
import re
import subprocess
import logging
import os

LOG = logging.getLogger(__name__)


def _extract_item_id(url_or_id: str) -> str | None:
    """Extrae el published file ID de una URL de Workshop o devuelve el ID directo."""
    url_or_id = url_or_id.strip()
    # Si es solo dígitos, es el ID directo
    if re.fullmatch(r"\d+", url_or_id):
        return url_or_id
    # Intentar extraer ?id=XXXXXX de una URL de Steam Workshop
    m = re.search(r"[?&]id=(\d+)", url_or_id)
    if m:
        return m.group(1)
    return None


def _get_steamcmd_path() -> str:
    import json
    from pathlib import Path
    settings_file = Path("config") / "settings.json"
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("steamcmd_path", "steamcmd")
        except Exception:
            pass
    return "steamcmd"


class _DownloadWorker(QThread):
    log_line   = pyqtSignal(str, str)   # (text, level)
    finished_ok  = pyqtSignal(str)       # dest_path
    finished_err = pyqtSignal(str)       # error message

    def __init__(self, app_id: str, item_id: str, dest_dir: str, parent=None):
        super().__init__(parent)
        self.app_id   = app_id
        self.item_id  = item_id
        self.dest_dir = dest_dir

    def run(self):
        steamcmd = _get_steamcmd_path()
        args = [
            steamcmd,
            "+force_install_dir", self.dest_dir,
            "+login", "anonymous",
            "+workshop_download_item", self.app_id, self.item_id,
            "+quit",
        ]
        self.log_line.emit(f"▶ Ejecutando: {' '.join(args)}", "info")
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                level = "error" if any(w in line.lower() for w in ("error", "fail", "failed")) else \
                        "warning" if "warning" in line.lower() else "info"
                self.log_line.emit(line, level)

            proc.wait()
            if proc.returncode != 0:
                self.finished_err.emit(f"steamcmd salió con código {proc.returncode}")
                return

            # El contenido queda en: <dest_dir>/steamapps/workshop/content/<app_id>/<item_id>/
            expected = os.path.join(
                self.dest_dir,
                "steamapps", "workshop", "content",
                self.app_id, self.item_id
            )
            self.finished_ok.emit(expected)

        except FileNotFoundError:
            self.finished_err.emit(
                f"steamcmd no encontrado en '{steamcmd}'. "
                "Configura la ruta en la pestaña Configuración."
            )
        except Exception as e:
            self.finished_err.emit(str(e))


class DownloadTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._init_ui()

    def _init_ui(self):
        v = QVBoxLayout(self)
        v.setSpacing(12)

        # ── Sección de entrada ───────────────────────────────────────────────
        input_group = QGroupBox("Descargar item de Workshop")
        form = QFormLayout(input_group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText(
            "https://steamcommunity.com/sharedfiles/filedetails/?id=XXXXXXXX  —  o solo el ID numérico"
        )
        self.edit_url.setClearButtonEnabled(True)
        form.addRow("Enlace o ID del artículo:", self.edit_url)

        # Destino: mostrar pero no editable por el usuario; viene del perfil activo
        self.lbl_dest = QLabel()
        self.lbl_dest.setWordWrap(True)
        self.lbl_dest.setStyleSheet("color: #aaa; font-size: 11px;")
        self._refresh_dest_label()
        form.addRow("Destino de descarga:", self.lbl_dest)

        v.addWidget(input_group)

        # ── Botón de descarga ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_download = QPushButton("⬇  Iniciar descarga")
        self.btn_download.setFixedHeight(36)
        self.btn_download.setStyleSheet(
            "QPushButton { font-size: 13px; font-weight: bold; } "
        )
        self.btn_cancel = QPushButton("⏹  Cancelar")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.setEnabled(False)
        btn_row.addWidget(self.btn_download)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch()
        v.addLayout(btn_row)

        # ── Log ─────────────────────────────────────────────────────────────
        log_group = QGroupBox("Progreso de descarga")
        log_l = QVBoxLayout(log_group)
        self.log = LogWidget()
        log_l.addWidget(self.log)
        v.addWidget(log_group, stretch=1)

        # Conexiones
        self.btn_download.clicked.connect(self._on_start)
        self.btn_cancel.clicked.connect(self._on_cancel)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _refresh_dest_label(self):
        """Actualiza la etiqueta de destino a partir del perfil activo."""
        try:
            profile = get_active_profile()
            game_dir = profile.get("game_dir", "") if profile else ""
        except Exception:
            game_dir = ""

        if game_dir:
            dest = os.path.join(
                game_dir, "..", "..", "workshop", "content"
            )
            dest = os.path.normpath(dest)
            self.lbl_dest.setText(
                f"{dest}  (steamapps/workshop/content/&lt;appid&gt;/&lt;itemid&gt;/)\n"
                "El destino real lo determina steamcmd según el perfil activo."
            )
            self._dest_dir = os.path.normpath(os.path.join(game_dir, "..", ".."))
        else:
            self.lbl_dest.setText(
                "⚠ Sin perfil activo. Configure un perfil con ruta de juego para determinar el destino."
            )
            self._dest_dir = None

    # ── Slots ────────────────────────────────────────────────────────────────

    def _on_start(self):
        url = self.edit_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Validación", "Ingresa el enlace o ID del artículo.")
            return

        item_id = _extract_item_id(url)
        if not item_id:
            QMessageBox.warning(
                self, "Enlace inválido",
                "No se pudo extraer el ID del artículo.\n"
                "Usa la URL completa de Steam Workshop o solo el número de ID."
            )
            return

        # Refrescar destino
        self._refresh_dest_label()

        # Necesitamos app_id del perfil activo
        try:
            profile = get_active_profile()
            app_id = str(profile.get("steam_app_id", "")) if profile else ""
        except Exception:
            app_id = ""

        if not app_id:
            QMessageBox.information(
                self, "Sin perfil",
                "No hay perfil activo con app_id configurado.\n"
                "Configura un perfil en la pestaña Configuración."
            )
            return

        if not self._dest_dir:
            QMessageBox.information(
                self, "Sin destino",
                "No se pudo determinar el directorio de destino.\n"
                "Configura la ruta del juego en el perfil activo."
            )
            return

        self.log.clear()
        self.log.append_line(f"Iniciando descarga del item {item_id} (AppID: {app_id})", "info")
        self.log.append_line(f"Destino base: {self._dest_dir}", "info")

        self.btn_download.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        self._worker = _DownloadWorker(app_id, item_id, self._dest_dir)
        self._worker.log_line.connect(self.log.append_line)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.finished_err.connect(self._on_error)
        self._worker.start()

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
            self.log.append_line("⏹ Descarga cancelada por el usuario.", "warning")
        self.btn_download.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _on_done(self, path: str):
        self.btn_download.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.log.append_line(f"✓ Descarga completada. Contenido en: {path}", "info")
        self.log.append_line("", "info")
        self.log.append_line("Listo ✓", "info")

    def _on_error(self, err: str):
        self.btn_download.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.log.append_line(f"❌ Error: {err}", "error")
        QMessageBox.warning(self, "Error de descarga", err)
