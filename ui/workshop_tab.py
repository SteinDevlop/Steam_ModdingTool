from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QTextEdit, QLabel, QSplitter, QMessageBox, QSizePolicy, QLineEdit, QComboBox,
    QFileDialog, QFormLayout, QFrame, QScrollArea, QGroupBox,
    QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices
from ui.log_widget import LogWidget
from core import workshop as workshop_core
from core import steam_session
import datetime
import time
import os
import logging
import urllib.request

LOG = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  Dialog: Crear nuevo item
# ─────────────────────────────────────────────────────────────────────────────

class CreateItemDialog(QDialog):
    """Diálogo modal para crear un nuevo item de Workshop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear nuevo item de Workshop")
        self.setMinimumWidth(480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Nombre del item")
        form.addRow("Título *:", self.edit_title)

        self.edit_description = QTextEdit()
        self.edit_description.setFixedHeight(80)
        self.edit_description.setPlaceholderText("Descripción del item")
        form.addRow("Descripción:", self.edit_description)

        self.edit_visibility = QComboBox()
        self.edit_visibility.addItems(["Public", "Friends", "Private"])
        form.addRow("Visibilidad:", self.edit_visibility)

        self.edit_tags = QLineEdit()
        self.edit_tags.setPlaceholderText("tag1, tag2, tag3")
        form.addRow("Tags:", self.edit_tags)

        # Contenido: solo archivo .gma o .bpk
        content_row = QWidget()
        content_l = QHBoxLayout(content_row)
        content_l.setContentsMargins(0, 0, 0, 0)
        self.edit_content = QLineEdit()
        self.edit_content.setPlaceholderText("Archivo .gma o .bpk *")
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self._browse_content)
        content_l.addWidget(self.edit_content)
        content_l.addWidget(btn_browse)
        form.addRow("Archivo de contenido *:", content_row)

        layout.addLayout(form)

        # Nota: Changelog no requerido al crear
        note = QLabel("* Campos obligatorios. Changelog no es necesario al crear.")
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)

        # Botones OK / Cancelar
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Crear item")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_content(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo de contenido",
            "",
            "Archivos de contenido (*.gma *.bpk);;Todos los archivos (*)"
        )
        if f:
            self.edit_content.setText(f)

    def _validate_and_accept(self):
        if not self.edit_title.text().strip():
            QMessageBox.warning(self, "Validación", "El título es obligatorio.")
            return
        if not self.edit_content.text().strip():
            QMessageBox.warning(self, "Validación", "El archivo de contenido es obligatorio.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "title": self.edit_title.text().strip(),
            "description": self.edit_description.toPlainText(),
            "visibility": self.edit_visibility.currentText(),
            "tags": [t.strip() for t in self.edit_tags.text().split(",") if t.strip()],
            "content": self.edit_content.text().strip(),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Workers
# ─────────────────────────────────────────────────────────────────────────────

class _FetchWorker(QThread):
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(self, api_key, steam_id, app_id, game_dir, parent=None):
        super().__init__(parent)
        self.api_key = None
        self.steam_id = steam_id
        self.app_id = app_id
        self.game_dir = game_dir

    def run(self):
        try:
            if not self.steam_id:
                self.steam_id = steam_session.get_steam_user_id()
            items = workshop_core.get_user_workshop_items(None, self.steam_id, self.app_id, self.game_dir)
            self.finished_ok.emit(items)
        except Exception as e:
            self.finished_err.emit(str(e))


class _ActionWorker(QThread):
    finished_ok = pyqtSignal(object)
    finished_err = pyqtSignal(str)

    def __init__(self, action, api_key, app_id, item_id, metadata, content_path, parent=None):
        super().__init__(parent)
        self.action = action      # 'create' | 'update' | 'upload'
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


# ─────────────────────────────────────────────────────────────────────────────
#  WorkshopTab
# ─────────────────────────────────────────────────────────────────────────────

class WorkshopTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.action_worker = None
        self._init_ui()

    def _init_ui(self):
        v = QVBoxLayout(self)

        # Top toolbar
        top_row = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄 Actualizar lista")
        self.btn_new_item = QPushButton("➕ Nuevo item…")
        top_row.addWidget(self.btn_refresh)
        top_row.addWidget(self.btn_new_item)
        top_row.addStretch()
        lbl_info = QLabel(
            "Items obtenidos vía Steam Community y escaneo local. "
            "Se requiere steamcmd para publicar o actualizar."
        )
        lbl_info.setStyleSheet("color: gray; font-size: 11px;")
        top_row.addWidget(lbl_info)
        v.addLayout(top_row)

        # Main splitter: table on left, detail panel on right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        v.addWidget(splitter)

        # ── Left: Table of items ──────────────────────────────────────────
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Título", "ID", "Visibilidad", "Última actualización"])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        # ── Right: Detail / Edit panel ────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setSpacing(8)

        # Preview image
        preview_group = QGroupBox("Vista previa")
        preview_group_l = QVBoxLayout(preview_group)
        self.preview_label = QLabel("Sin imagen")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setFixedHeight(180)
        self.preview_label.setStyleSheet(
            "background: #1e1e1e; border: 1px solid #444; color: #888; border-radius: 4px;"
        )
        self.preview_label.setScaledContents(False)
        preview_group_l.addWidget(self.preview_label)

        self.lbl_steam_link = QLabel()
        self.lbl_steam_link.setOpenExternalLinks(True)
        self.lbl_steam_link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_steam_link.setStyleSheet("font-size: 11px;")
        preview_group_l.addWidget(self.lbl_steam_link)
        right_l.addWidget(preview_group)

        # Read-only info section
        info_group = QGroupBox("Información del artículo")
        info_l = QFormLayout(info_group)
        self.lbl_item_id    = QLabel("—")
        self.lbl_creator    = QLabel("—")
        self.lbl_app_name   = QLabel("—")
        self.lbl_vis_ro     = QLabel("—")
        self.lbl_tags_ro    = QLabel("—")
        self.lbl_updated_ro = QLabel("—")
        for lbl in (self.lbl_item_id, self.lbl_creator, self.lbl_app_name,
                    self.lbl_vis_ro, self.lbl_tags_ro, self.lbl_updated_ro):
            lbl.setWordWrap(True)
        info_l.addRow("ID:", self.lbl_item_id)
        info_l.addRow("Creador:", self.lbl_creator)
        info_l.addRow("Juego:", self.lbl_app_name)
        info_l.addRow("Visibilidad:", self.lbl_vis_ro)
        info_l.addRow("Tags:", self.lbl_tags_ro)
        info_l.addRow("Actualizado:", self.lbl_updated_ro)
        right_l.addWidget(info_group)

        # Description read-only
        desc_group = QGroupBox("Descripción")
        desc_l = QVBoxLayout(desc_group)
        self.lbl_description_ro = QTextEdit()
        self.lbl_description_ro.setReadOnly(True)
        self.lbl_description_ro.setFixedHeight(100)
        desc_l.addWidget(self.lbl_description_ro)
        right_l.addWidget(desc_group)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        right_l.addWidget(sep)

        # ── Editable fields (only visible when item selected) ─────────────
        edit_group = QGroupBox("Editar artículo")
        form_layout = QFormLayout(edit_group)

        self.edit_title = QLineEdit()
        self.edit_description = QTextEdit()
        self.edit_description.setFixedHeight(80)
        # Changelog: presente al editar
        self.edit_changelog = QLineEdit()
        self.edit_changelog.setPlaceholderText("Describe los cambios de esta actualización")
        self.edit_visibility = QComboBox()
        self.edit_visibility.addItems(["Public", "Friends", "Private"])
        self.edit_tags = QLineEdit()
        self.edit_tags.setPlaceholderText("tag1, tag2, tag3")

        # Contenido: solo archivo .gma / .bpk
        self.edit_content = QLineEdit()
        self.edit_content.setPlaceholderText("Archivo .gma o .bpk (opcional al actualizar)")
        btn_browse_content = QPushButton("…")
        btn_browse_content.setFixedWidth(30)
        btn_browse_content.clicked.connect(self._browse_content)

        form_layout.addRow("Título:", self.edit_title)
        form_layout.addRow("Descripción:", self.edit_description)
        form_layout.addRow("Changelog:", self.edit_changelog)
        form_layout.addRow("Visibilidad:", self.edit_visibility)
        form_layout.addRow("Tags:", self.edit_tags)

        row_w = QWidget()
        row_l2 = QHBoxLayout(row_w)
        row_l2.setContentsMargins(0, 0, 0, 0)
        row_l2.addWidget(self.edit_content)
        row_l2.addWidget(btn_browse_content)
        form_layout.addRow("Archivo de contenido:", row_w)

        right_l.addWidget(edit_group)

        # Action buttons (only for existing items)
        btn_row = QHBoxLayout()
        self.btn_save_meta = QPushButton("💾 Guardar metadatos")
        self.btn_upload    = QPushButton("⬆ Subir contenido")
        for b in (self.btn_save_meta, self.btn_upload):
            btn_row.addWidget(b)
        right_l.addLayout(btn_row)

        # Log widget
        self.log = LogWidget()
        self.log.setFixedHeight(110)
        right_l.addWidget(self.log)
        right_l.addStretch()

        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Wire connections
        self.btn_refresh.clicked.connect(self.on_refresh)
        self.btn_new_item.clicked.connect(self.on_new_item)
        self.btn_save_meta.clicked.connect(self.on_save_meta)
        self.btn_upload.clicked.connect(self.on_upload)

        self.btn_refresh.setEnabled(True)
        self._clear_detail_panel()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _browse_content(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo de contenido",
            "",
            "Archivos de contenido (*.gma *.bpk);;Todos los archivos (*)"
        )
        if f:
            self.edit_content.setText(f)

    def _get_active_app_id(self):
        try:
            from core.profile_manager import get_active_profile
            active = get_active_profile()
            return active.get("steam_app_id") if active else None
        except Exception:
            return None

    # ── Actions ──────────────────────────────────────────────────────────────

    def on_refresh(self):
        active = None
        try:
            from core.profile_manager import get_active_profile
            active = get_active_profile()
        except Exception:
            active = None

        app_id = None
        game_dir = None
        if active:
            app_id = active.get("steam_app_id")
            game_dir = active.get("game_dir")
        if not app_id:
            self.log.append_line("⚠ No hay perfil activo con app_id configurado", "warning")
            QMessageBox.information(self, "Seleccione juego",
                "No hay perfil activo con app_id. Seleccione un perfil activo o configure app_id.")
            return

        self.log.append_line(f"Actualizando workshop items para App ID: {app_id}", "info")

        steam_id = None
        try:
            steam_id = steam_session.get_steam_user_id()
            self.log.append_line(f"Steam ID: {steam_id}", "debug")
        except Exception as e:
            self.log.append_line(f"⚠ No se pudo obtener Steam ID: {e}", "warning")

        self.btn_refresh.setEnabled(False)
        self.window().statusBar().showMessage("Cargando items…")
        self.worker = _FetchWorker(None, steam_id, str(app_id), game_dir)
        self.worker.finished_ok.connect(self._on_items_loaded)
        self.worker.finished_err.connect(self._on_items_error)
        self.worker.start()

    def on_new_item(self):
        """Abre el diálogo para crear un nuevo item."""
        dlg = CreateItemDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        data = dlg.get_data()
        app_id = self._get_active_app_id()
        if not app_id:
            self.log.append_line("❌ No hay perfil activo con app_id", "error")
            QMessageBox.information(self, "Seleccione juego",
                "No hay perfil activo con app_id. Configure un perfil antes de crear items.")
            return

        metadata = {
            "title": data["title"],
            "description": data["description"],
            "visibility": data["visibility"],
            "tags": data["tags"],
        }

        self._set_action_enabled(False)
        self.log.append_line(f"Creando item '{data['title']}'...", "info")
        self.action_worker = _ActionWorker("create", None, str(app_id), None, metadata, data["content"])
        self.action_worker.finished_ok.connect(self._on_action_ok)
        self.action_worker.finished_err.connect(self._on_action_err)
        self.action_worker.start()

    def on_save_meta(self):
        if not getattr(self, "current_item", None):
            self.log.append_line("⚠ Seleccione un item para actualizar", "warning")
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
            self.log.append_line("⚠ El título es obligatorio", "warning")
            QMessageBox.warning(self, "Validación", "Título es obligatorio.")
            return
        self._set_action_enabled(False)
        self.log.append_line(f"Actualizando metadatos de {item_id}...", "info")
        app_id = self._get_active_app_id()
        self.action_worker = _ActionWorker("update", None, str(app_id) if app_id else "", item_id, metadata, None)
        self.action_worker.finished_ok.connect(self._on_action_ok)
        self.action_worker.finished_err.connect(self._on_action_err)
        self.action_worker.start()

    def on_upload(self):
        if not getattr(self, "current_item", None):
            self.log.append_line("⚠ Seleccione un item para subir contenido", "warning")
            QMessageBox.information(self, "Seleccione item", "Seleccione un item para subir contenido.")
            return
        item_id = self.current_item.get("publishedfileid")
        content = self.edit_content.text().strip()
        if not content:
            self.log.append_line("⚠ La ruta del archivo de contenido es obligatoria", "warning")
            QMessageBox.warning(self, "Validación", "Seleccione un archivo .gma o .bpk para subir.")
            return
        self._set_action_enabled(False)
        self.log.append_line(f"Subiendo contenido para {item_id} desde {content} ...", "info")
        app_id = self._get_active_app_id()
        self.action_worker = _ActionWorker("upload", None, str(app_id) if app_id else "", item_id, None, content)
        self.action_worker.finished_ok.connect(self._on_action_ok)
        self.action_worker.finished_err.connect(self._on_action_err)
        self.action_worker.start()

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _on_items_loaded(self, items):
        self.btn_refresh.setEnabled(True)
        self.window().statusBar().showMessage("Listo")
        self._populate_table(items)

    def _on_items_error(self, err):
        self.btn_refresh.setEnabled(True)
        self.window().statusBar().showMessage("Error cargando items")
        self.log.append_line(f"Error: {err}", "error")
        QMessageBox.warning(self, "Error", f"Error al obtener items: {err}")

    def _on_action_ok(self, payload):
        act = payload.get("action")
        if act == "create":
            new_id = payload.get("id")
            self.log.append_line(f"✓ Item creado: {new_id}", "info")
            row = self.table.rowCount()
            self.table.insertRow(row)
            # title from last dialog — stored in worker metadata
            title = self.action_worker.metadata.get("title", "Nuevo item")
            self.table.setItem(row, 0, QTableWidgetItem(title))
            self.table.setItem(row, 1, QTableWidgetItem(str(new_id)))
            self.table.setItem(row, 2, QTableWidgetItem(self.action_worker.metadata.get("visibility", "")))
            self.table.setItem(row, 3, QTableWidgetItem(time.strftime("%Y-%m-%d %H:%M:%S")))
            item_dict = {
                "publishedfileid": str(new_id),
                "title": title,
                "description": self.action_worker.metadata.get("description", ""),
                "visibility": self.action_worker.metadata.get("visibility", ""),
                "tags": self.action_worker.metadata.get("tags", []),
                "time_updated": int(time.time()),
            }
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item_dict)
            self.table.selectRow(row)
        elif act == "update":
            self.log.append_line("✓ Metadatos actualizados correctamente.", "info")
        elif act == "upload":
            out = payload.get("output")
            self.log.append_line(f"✓ Upload finalizado: {out}", "info")
        self._set_action_enabled(True)

    def _on_action_err(self, err):
        self.log.append_line(f"❌ Error: {err}", "error")
        QMessageBox.warning(self, "Error", f"{err}")
        self._set_action_enabled(True)

    # ── Table / Detail panel ─────────────────────────────────────────────────

    def _populate_table(self, items):
        self.table.setRowCount(0)
        self._clear_detail_panel()
        items = [it for it in items if it is not None]
        self.log.append_line(f"Cargando {len(items)} artículos en la tabla...", "info")

        vis_icons = {
            "public":   "🌍 Público",
            "publico":  "🌍 Público",
            "friends":  "👥 Amigos",
            "private":  "🔒 Privado",
            "unlisted": "🔗 No listado",
            "local":    "💾 Local",
        }

        for it in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            title   = it.get("title") or f"Item #{it.get('publishedfileid','?')}"
            pid     = it.get("publishedfileid") or ""
            vis_raw = str(it.get("visibility") or "").lower()
            vis     = vis_icons.get(vis_raw, vis_raw.capitalize() if vis_raw else "—")
            ts      = it.get("time_updated") or 0
            try:
                dt = datetime.datetime.fromtimestamp(int(ts))
                ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ts_str = str(ts) if ts else "—"

            self.table.setItem(row, 0, QTableWidgetItem(title))
            self.table.setItem(row, 1, QTableWidgetItem(pid))
            self.table.setItem(row, 2, QTableWidgetItem(vis))
            self.table.setItem(row, 3, QTableWidgetItem(ts_str))
            self.table.setRowHeight(row, 26)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, it)
            self.log.append_line(f"• [{pid}] {title} ({vis}) — {ts_str}", "debug")

        if self.table.rowCount() == 0:
            self.log.append_line("⚠ No hay artículos disponibles en el workshop.", "warning")
        else:
            self.log.append_line(f"✓ {self.table.rowCount()} artículos cargados exitosamente.", "info")
            self.table.selectRow(0)

    def _clear_detail_panel(self):
        self.preview_label.setText("Sin imagen")
        self.preview_label.setPixmap(QPixmap())
        self.lbl_steam_link.setText("")
        self.lbl_item_id.setText("—")
        self.lbl_creator.setText("—")
        self.lbl_app_name.setText("—")
        self.lbl_vis_ro.setText("—")
        self.lbl_tags_ro.setText("—")
        self.lbl_updated_ro.setText("—")
        self.lbl_description_ro.setPlainText("")
        self.edit_title.clear()
        self.edit_description.clear()
        self.edit_changelog.clear()
        self.edit_tags.clear()
        self.edit_content.clear()
        self.current_item = None

    def _load_preview_image(self, url: str):
        if not url:
            self.preview_label.setText("Sin imagen")
            return
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    300, 170,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled)
                self.preview_label.setText("")
            else:
                self.preview_label.setText("No se pudo cargar la imagen")
        except Exception as e:
            LOG.debug(f"Error cargando imagen de preview: {e}")
            self.preview_label.setText("Sin imagen")

    def _on_selection_changed(self):
        sel = self.table.selectedItems()
        if not sel:
            self._clear_detail_panel()
            return
        row = sel[0].row()
        item = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if not item:
            self._clear_detail_panel()
            return

        self.current_item = item
        item_id = item.get("publishedfileid", "")

        self.lbl_item_id.setText(item_id)
        creator = item.get("creator", "")
        self.lbl_creator.setText(creator if creator else "—")
        app_name = item.get("app_name", "")
        self.lbl_app_name.setText(app_name if app_name else "—")

        vis_raw = str(item.get("visibility", "")).lower()
        vis_map = {
            "public": "🌍 Público", "publico": "🌍 Público", "0": "🌍 Público",
            "friends": "👥 Solo amigos", "friendsonly": "👥 Solo amigos", "1": "👥 Solo amigos",
            "private": "🔒 Privado", "2": "🔒 Privado",
            "unlisted": "🔗 No listado", "3": "🔗 No listado",
            "local": "💾 Local (no publicado)",
        }
        self.lbl_vis_ro.setText(vis_map.get(vis_raw, f"❓ {vis_raw.capitalize()}" if vis_raw else "—"))

        tags = item.get("tags") or []
        if isinstance(tags, (list, tuple)):
            self.lbl_tags_ro.setText(", ".join(tags) if tags else "—")
        else:
            self.lbl_tags_ro.setText(str(tags) if tags else "—")

        ts = item.get("time_updated") or 0
        try:
            dt = datetime.datetime.fromtimestamp(int(ts))
            self.lbl_updated_ro.setText(dt.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            self.lbl_updated_ro.setText(str(ts) if ts else "—")

        desc = item.get("description", "") or ""
        self.lbl_description_ro.setPlainText(desc)

        if item_id:
            link = f'<a href="https://steamcommunity.com/sharedfiles/filedetails/?id={item_id}">Ver en Steam Workshop ↗</a>'
            self.lbl_steam_link.setText(link)
        else:
            self.lbl_steam_link.setText("")

        self._load_preview_image(item.get("preview_url", ""))

        self.edit_title.setText(item.get("title", ""))
        self.edit_description.setPlainText(desc)
        self.edit_changelog.clear()
        self.edit_content.clear()

        if vis_raw in ("public", "publico", "0"):
            self.edit_visibility.setCurrentText("Public")
        elif vis_raw in ("friends", "friendsonly", "1"):
            self.edit_visibility.setCurrentText("Friends")
        else:
            self.edit_visibility.setCurrentText("Private")

        if isinstance(tags, (list, tuple)):
            self.edit_tags.setText(", ".join(tags))
        else:
            self.edit_tags.setText(str(tags) if tags else "")

    def _set_action_enabled(self, enable: bool):
        self.btn_new_item.setEnabled(enable)
        self.btn_save_meta.setEnabled(enable)
        self.btn_upload.setEnabled(enable)
        self.btn_refresh.setEnabled(enable)
