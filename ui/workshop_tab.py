from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QTextEdit, QLabel, QSplitter, QMessageBox, QSizePolicy, QLineEdit, QComboBox, QFileDialog, QFormLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from ui.log_widget import LogWidget
from core import workshop as workshop_core
from core import steam_session
import datetime
import time
import os

class _FetchWorker(QThread):
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(self, api_key: str | None, steam_id: str | None, app_id: str, parent=None):
        super().__init__(parent)
        # api_key parameter kept for compatibility but we don't use it anymore
        self.api_key = None
        self.steam_id = steam_id
        self.app_id = app_id

    def run(self):
        try:
            if not self.steam_id:
                # attempt to read from local steam session
                self.steam_id = steam_session.get_steam_user_id()
            # workshop_core.get_user_workshop_items now uses steamcmd/scraping fallback (no API key)
            items = workshop_core.get_user_workshop_items(None, self.steam_id, self.app_id)
            self.finished_ok.emit(items)
        except Exception as e:
            self.finished_err.emit(str(e))

class _ActionWorker(QThread):
    finished_ok = pyqtSignal(object)
    finished_err = pyqtSignal(str)

    def __init__(self, action: str, api_key: str | None, app_id: str, item_id: str | None, metadata: dict, content_path: str | None, parent=None):
        super().__init__(parent)
        self.action = action  # 'create' | 'update' | 'upload'
        self.api_key = api_key
        self.app_id = app_id
        self.item_id = item_id
        self.metadata = metadata or {}
        self.content_path = content_path

    def run(self):
        try:
            if self.action == "create":
                new_id = workshop_core.create_workshop_item(self.api_key, self.app_id, self.metadata)
                self.finished_ok.emit({"action": "create", "id": new_id})
            elif self.action == "update":
                rsp = workshop_core.update_workshop_item(self.api_key, self.item_id, self.metadata)
                self.finished_ok.emit({"action": "update", "response": rsp})
            elif self.action == "upload":
                out = workshop_core.upload_content(self.item_id, self.content_path, app_id=self.app_id)
                self.finished_ok.emit({"action": "upload", "output": out})
            else:
                raise RuntimeError("Unknown action")
        except Exception as e:
            self.finished_err.emit(str(e))

class WorkshopTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.action_worker = None
        self._init_ui()

    def _init_ui(self):
        v = QVBoxLayout(self)
        top_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Actualizar lista")
        top_row.addWidget(self.btn_refresh)
        top_row.addStretch()
        v.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        v.addWidget(splitter)

        # Table of items
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Título", "ID", "Visibilidad", "Última actualización"])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        splitter.addWidget(self.table)

        # Detail / Edit panel (right)
        right = QWidget()
        right_l = QVBoxLayout(right)
        self.detail_title = QLabel("<b>Selecciona un item</b>")
        right_l.addWidget(self.detail_title)

        # Form fields
        self.edit_title = QLineEdit()
        self.edit_description = QTextEdit()
        self.edit_changelog = QLineEdit()
        self.edit_visibility = QComboBox()
        self.edit_visibility.addItems(["Public", "Friends", "Private"])
        self.edit_tags = QLineEdit()  # comma-separated
        self.edit_content = QLineEdit()
        btn_browse_content = QPushButton("…")
        btn_browse_content.setFixedWidth(30)
        btn_browse_content.clicked.connect(lambda: self._browse_content())

        form_layout = QFormLayout()
        form_layout.addRow("Title", self.edit_title)
        form_layout.addRow("Description", self.edit_description)
        form_layout.addRow("Changelog", self.edit_changelog)
        form_layout.addRow("Visibility", self.edit_visibility)
        form_layout.addRow("Tags (comma)", self.edit_tags)
        row = QWidget()
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0,0,0,0)
        row_l.addWidget(self.edit_content)
        row_l.addWidget(btn_browse_content)
        form_layout.addRow("Content path", row)

        right_l.addLayout(form_layout)

        # Buttons for actions
        btn_row = QHBoxLayout()
        self.btn_create = QPushButton("Crear nuevo item")
        self.btn_save_meta = QPushButton("Guardar metadatos")
        self.btn_upload = QPushButton("Subir contenido")
        btn_row.addWidget(self.btn_create)
        btn_row.addWidget(self.btn_save_meta)
        btn_row.addWidget(self.btn_upload)
        right_l.addLayout(btn_row)

        # Log widget
        self.log = LogWidget()
        right_l.addWidget(self.log)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Connections
        self.btn_refresh.clicked.connect(self.on_refresh)
        self.btn_create.clicked.connect(self.on_create)
        self.btn_save_meta.clicked.connect(self.on_save_meta)
        self.btn_upload.clicked.connect(self.on_upload)

        # Inform user that steamcmd/local Steam session is used (no API key required)
        lbl = QLabel("Se usa steamcmd o la sesión local de Steam para operaciones Workshop (asegúrate de estar logueado en steamcmd o tener el perfil público).")
        v.addWidget(lbl)
        self.btn_refresh.setEnabled(True)

    def on_refresh(self):
        # Determine app_id: prefer active profile's steam_app_id else ask user later
        active = None
        try:
            from core.profile_manager import get_active_profile
            active = get_active_profile()
        except Exception:
            active = None

        app_id = None
        if active:
            app_id = active.get("steam_app_id")
        if not app_id:
            # ask user
            QMessageBox.information(self, "Seleccione juego", "No hay perfil activo con app_id. Seleccione un perfil activo o configure app_id.")
            return

        # Start worker (uses steamcmd/scraping fallback)
        self.btn_refresh.setEnabled(False)
        self.window().statusBar().showMessage("Cargando items…")
        self.worker = _FetchWorker(None, None, str(app_id))
        self.worker.finished_ok.connect(self._on_items_loaded)
        self.worker.finished_err.connect(self._on_items_error)
        self.worker.start()

    def _on_items_loaded(self, items):
        self.btn_refresh.setEnabled(True)
        self.window().statusBar().showMessage("Listo")
        self._populate_table(items)

    def _on_items_error(self, err):
        self.btn_refresh.setEnabled(True)
        self.window().statusBar().showMessage("Error cargando items")
        QMessageBox.warning(self, "Error", f"Error al obtener items: {err}")

    def _populate_table(self, items):
        self.table.setRowCount(0)
        for it in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            title = it.get("title") or ""
            pid = it.get("publishedfileid") or ""
            vis = str(it.get("visibility") or "")
            ts = it.get("time_updated") or 0
            try:
                dt = datetime.datetime.fromtimestamp(int(ts))
                ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ts_str = str(ts)
            self.table.setItem(row, 0, QTableWidgetItem(title))
            self.table.setItem(row, 1, QTableWidgetItem(pid))
            self.table.setItem(row, 2, QTableWidgetItem(vis))
            self.table.setItem(row, 3, QTableWidgetItem(ts_str))
            # store full item on row for detail retrieval
            self.table.setRowHeight(row, 24)
            self.table.setVerticalHeaderItem(row, QTableWidgetItem(""))  # keep consistent
            self.table.item(row,0).setData(Qt.ItemDataRole.UserRole, it)

        if self.table.rowCount() == 0:
            self.detail_title.setText("<b>No items</b>")
            self.detail_desc.clear()
            self.detail_tags.setText("")

    def _browse_content(self):
        f = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de contenido")
        if not f:
            f, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo (.gma/.zip/etc)")
        if f:
            self.edit_content.setText(f)

    def _on_selection_changed(self):
        sel = self.table.selectedItems()
        if not sel:
            return
        item = sel[0].data(Qt.ItemDataRole.UserRole)
        if not item:
            row = sel[0].row()
            item = self.table.item(row,0).data(Qt.ItemDataRole.UserRole)
        if not item:
            return
        # Fill form
        self.current_item = item
        self.edit_title.setText(item.get("title",""))
        self.edit_description.setPlainText(item.get("description",""))
        self.edit_changelog.setText("")  # not provided by list API
        vis = item.get("visibility","")
        if vis is not None:
            if str(vis).lower() in ("0","public","publico","public"):
                self.edit_visibility.setCurrentText("Public")
            elif str(vis).lower() in ("1","friends","friendsonly"):
                self.edit_visibility.setCurrentText("Friends")
            else:
                self.edit_visibility.setCurrentText("Private")
        tags = item.get("tags") or []
        if isinstance(tags, (list,tuple)):
            self.edit_tags.setText(", ".join(tags))
        else:
            self.edit_tags.setText(str(tags))
        self.edit_content.setText("")

    # ---------- Actions (create/update/upload) ----------

    def on_create(self):
        title = self.edit_title.text().strip()
        content = self.edit_content.text().strip()
        if not title or not content:
            QMessageBox.warning(self, "Validación", "Título y ruta de contenido son obligatorios para crear un item.")
            return
        # prepare metadata
        metadata = {
            "title": title,
            "description": self.edit_description.toPlainText(),
            "visibility": self.edit_visibility.currentText(),
            "tags": [t.strip() for t in self.edit_tags.text().split(",") if t.strip()],
        }
        # disable buttons
        self._set_action_enabled(False)
        self.log.append_line(f"Creando item '{title}'...", "info")
        active = None
        try:
            from core.profile_manager import get_active_profile
            active = get_active_profile()
        except Exception:
            active = None
        app_id = active.get("steam_app_id") if active else None
        if not app_id:
            QMessageBox.information(self, "Seleccione juego", "No hay perfil activo con app_id. Seleccione un perfil activo o configure app_id.")
            self._set_action_enabled(True)
            return
        # create via steamcmd (no API key)
        self.action_worker = _ActionWorker("create", None, str(app_id), None, metadata, content)
        self.action_worker.finished_ok.connect(self._on_action_ok)
        self.action_worker.finished_err.connect(self._on_action_err)
        self.action_worker.start()

    def on_save_meta(self):
        if not getattr(self, "current_item", None):
            QMessageBox.information(self, "Seleccione item", "Seleccione un item para actualizar.")
            return
        item_id = self.current_item.get("publishedfileid")
        metadata = {
            "title": self.edit_title.text().strip(),
            "description": self.edit_description.toPlainText(),
            "changelog": self.edit_changelog.text().strip(),
            "visibility": self.edit_visibility.currentText(),
            "tags": [t.strip() for t in self.edit_tags.text().split(",") if t.strip()],
        }
        if not metadata["title"]:
            QMessageBox.warning(self, "Validación", "Título es obligatorio.")
            return
        self._set_action_enabled(False)
        self.log.append_line(f"Actualizando metadatos de {item_id}...", "info")
        active = None
        try:
            from core.profile_manager import get_active_profile
            active = get_active_profile()
        except Exception:
            active = None
        app_id = active.get("steam_app_id") if active else None
        self.action_worker = _ActionWorker("update", None, str(app_id) if app_id else "", item_id, metadata, None)
        self.action_worker.finished_ok.connect(self._on_action_ok)
        self.action_worker.finished_err.connect(self._on_action_err)
        self.action_worker.start()

    def on_upload(self):
        if not getattr(self, "current_item", None):
            QMessageBox.information(self, "Seleccione item", "Seleccione un item para subir contenido.")
            return
        item_id = self.current_item.get("publishedfileid")
        content = self.edit_content.text().strip()
        if not content:
            QMessageBox.warning(self, "Validación", "Ruta de contenido es obligatoria.")
            return
        self._set_action_enabled(False)
        self.log.append_line(f"Subiendo contenido para {item_id} desde {content} ...", "info")
        active = None
        try:
            from core.profile_manager import get_active_profile
            active = get_active_profile()
        except Exception:
            active = None
        app_id = active.get("steam_app_id") if active else None
        self.action_worker = _ActionWorker("upload", None, str(app_id) if app_id else "", item_id, None, content)
        self.action_worker.finished_ok.connect(self._on_action_ok)
        self.action_worker.finished_err.connect(self._on_action_err)
        self.action_worker.start()

    def _on_action_ok(self, payload):
        act = payload.get("action")
        if act == "create":
            new_id = payload.get("id")
            self.log.append_line(f"Item creado: {new_id}", "info")
            # append to table (minimal)
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(self.edit_title.text()))
            self.table.setItem(row, 1, QTableWidgetItem(str(new_id)))
            self.table.setItem(row, 2, QTableWidgetItem(self.edit_visibility.currentText()))
            self.table.setItem(row, 3, QTableWidgetItem(time.strftime("%Y-%m-%d %H:%M:%S")))
            # store item dict for selection
            item_dict = {
                "publishedfileid": str(new_id),
                "title": self.edit_title.text(),
                "description": self.edit_description.toPlainText(),
                "visibility": self.edit_visibility.currentText(),
                "tags": [t.strip() for t in self.edit_tags.text().split(",") if t.strip()],
                "time_updated": int(time.time())
            }
            self.table.item(row,0).setData(Qt.ItemDataRole.UserRole, item_dict)
        elif act == "update":
            self.log.append_line("Metadatos actualizados correctamente.", "info")
        elif act == "upload":
            out = payload.get("output")
            self.log.append_line(f"Upload finished: {out}", "info")
        self._set_action_enabled(True)

    def _on_action_err(self, err):
        self.log.append_line(f"Error: {err}", "error")
        QMessageBox.warning(self, "Error", f"{err}")
        self._set_action_enabled(True)

    def _set_action_enabled(self, enable: bool):
        self.btn_create.setEnabled(enable)
        self.btn_save_meta.setEnabled(enable)
        self.btn_upload.setEnabled(enable)
        self.btn_refresh.setEnabled(enable)
        self.btn_upload.setEnabled(enable)
        self.btn_refresh.setEnabled(enable)
