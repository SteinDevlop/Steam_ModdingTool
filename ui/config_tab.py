from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QListWidget, QListWidgetItem, QFormLayout, QLineEdit,
    QPushButton, QVBoxLayout, QFileDialog, QMessageBox, QLabel, QSplitter, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import uuid

from core import profile_manager as pm

# Lista base de nombres de juego sugeridos
BASE_GAME_NAMES = [
    "Left 4 Dead 2",
    "Garry's Mod",
    "Team Fortress 2",
    "Counter-Strike 2",
]

ENGINE_CHOICES = ["Source", "GoldSource"]

class ConfigTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles = []
        self.current_id = None
        self._init_ui()
        self.load_profiles()

    def _init_ui(self):
        main_l = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_l.addWidget(splitter)

        # Left: list of profiles
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self.on_selection_changed)
        splitter.addWidget(self.list_widget)

        # Right: form (Game setup + Steam executable)
        right = QWidget()
        form_l = QVBoxLayout(right)
        game_setup_label = QLabel("Game setup")
        game_setup_label.setStyleSheet("font-weight: bold;")
        form_l.addWidget(game_setup_label)

        form = QFormLayout()
        self.edits = {}

        # name: editable combo with base list
        name_cb = QComboBox()
        name_cb.setEditable(True)
        name_cb.addItems(BASE_GAME_NAMES)
        self.edits["name"] = name_cb
        form.addRow("Name", name_cb)

        # engine: restricted choices
        engine_cb = QComboBox()
        engine_cb.addItems(ENGINE_CHOICES)
        self.edits["engine"] = engine_cb
        form.addRow("Engine", engine_cb)

        # Steam App ID
        steam_app_id_le = QLineEdit()
        self.edits["steam_app_id"] = steam_app_id_le
        form.addRow("Steam App ID", steam_app_id_le)

        # game_dir (directory)
        game_dir_le = QLineEdit()
        self.edits["game_dir"] = game_dir_le
        btn_game_dir = QPushButton("…")
        btn_game_dir.setFixedWidth(30)
        btn_game_dir.clicked.connect(lambda: self._browse_dir("game_dir"))
        row = QWidget()
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0,0,0,0)
        row_l.addWidget(game_dir_le)
        row_l.addWidget(btn_game_dir)
        form.addRow("Game directory", row)

        # executable (file) + executable_options (text)
        exe_le = QLineEdit()
        self.edits["executable"] = exe_le
        btn_exe = QPushButton("…")
        btn_exe.setFixedWidth(30)
        btn_exe.clicked.connect(lambda: self._browse_file("executable"))
        row = QWidget()
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0,0,0,0)
        row_l.addWidget(exe_le)
        row_l.addWidget(btn_exe)
        form.addRow("Executable", row)

        exe_opts_le = QLineEdit()
        self.edits["executable_options"] = exe_opts_le
        form.addRow("Executable options", exe_opts_le)

        # gameinfo.txt (file)
        gameinfo_le = QLineEdit()
        self.edits["gameinfo_txt"] = gameinfo_le
        btn_gameinfo = QPushButton("…")
        btn_gameinfo.setFixedWidth(30)
        btn_gameinfo.clicked.connect(lambda: self._browse_file("gameinfo_txt", filter="Text files (*.txt);;All files (*)"))
        row = QWidget()
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0,0,0,0)
        row_l.addWidget(gameinfo_le)
        row_l.addWidget(btn_gameinfo)
        form.addRow("gameinfo.txt", row)

        # model_compiler, model_viewer, mapping_tool, packer_tool (files)
        for key, label in [
            ("model_compiler", "Model compiler"),
            ("model_viewer", "Model viewer"),
            ("mapping_tool", "Mapping tool"),
            ("packer_tool", "Packer tool"),
        ]:
            le = QLineEdit()
            self.edits[key] = le
            btn = QPushButton("…")
            btn.setFixedWidth(30)
            btn.clicked.connect(lambda _, k=key: self._browse_file(k))
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0,0,0,0)
            row_l.addWidget(le)
            row_l.addWidget(btn)
            form.addRow(label, row)

        # Steam executable (file)
        steam_le = QLineEdit()
        self.edits["steam_executable"] = steam_le
        btn_steam = QPushButton("…")
        btn_steam.setFixedWidth(30)
        btn_steam.clicked.connect(lambda: self._browse_file("steam_executable"))
        row = QWidget()
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0,0,0,0)
        row_l.addWidget(steam_le)
        row_l.addWidget(btn_steam)
        form.addRow("Steam executable", row)

        form_l.addLayout(form)

        # Buttons
        btn_row = QWidget()
        btn_l = QHBoxLayout(btn_row)
        self.btn_new = QPushButton("Nuevo")
        self.btn_save = QPushButton("Guardar")
        self.btn_delete = QPushButton("Eliminar")
        self.btn_set_active = QPushButton("Establecer como activo")
        btn_l.addWidget(self.btn_new)
        btn_l.addWidget(self.btn_save)
        btn_l.addWidget(self.btn_delete)
        btn_l.addWidget(self.btn_set_active)
        btn_l.addStretch()
        form_l.addWidget(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Conexiones
        self.btn_new.clicked.connect(self.on_new)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_set_active.clicked.connect(self.on_set_active)

    # ---------- helpers ----------
    def _browse_dir(self, key):
        d = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if d:
            widget = self.edits.get(key)
            if widget:
                widget.setText(d)

    def _browse_file(self, key, filter="All files (*)"):
        f, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo", filter=filter)
        if f:
            widget = self.edits.get(key)
            if widget:
                widget.setText(f)
            if key == "gameinfo_txt":
                self._fill_app_id_from_gameinfo(f)

    def _fill_app_id_from_gameinfo(self, gameinfo_path: str):
        steam_app_id_widget = self.edits.get("steam_app_id")
        if not steam_app_id_widget:
            return
        current_app_id = steam_app_id_widget.text().strip()
        if current_app_id:
            return
        app_id = pm.extract_app_id_from_gameinfo(gameinfo_path)
        if app_id:
            steam_app_id_widget.setText(app_id)

    def load_profiles(self):
        self.profiles = pm.load_profiles()
        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for p in self.profiles:
            item = QListWidgetItem(p.get("name") or "(sin nombre)")
            item.setData(Qt.ItemDataRole.UserRole, p.get("id"))
            # marcar activo en negrita
            if p.get("active"):
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.list_widget.addItem(item)

    def on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            self.current_id = None
            for k, w in self.edits.items():
                if isinstance(w, QLineEdit):
                    w.setText("")
                elif isinstance(w, QComboBox):
                    w.setCurrentIndex(0) if w.count() else None
            return
        pid = current.data(Qt.ItemDataRole.UserRole)
        self.current_id = pid
        p = next((x for x in self.profiles if x.get("id") == pid), None)
        if not p:
            return
        for k, w in self.edits.items():
            val = p.get(k, "") or ""
            if isinstance(w, QLineEdit):
                w.setText(str(val))
            elif isinstance(w, QComboBox):
                # si no existe el valor en la lista, añadirlo (editable names)
                idx = w.findText(str(val))
                if idx == -1:
                    w.addItem(str(val))
                    idx = w.findText(str(val))
                w.setCurrentIndex(idx)

    def on_new(self):
        new_id = str(uuid.uuid4())
        new_profile = {k: "" for k in pm.PROFILE_FIELDS}
        new_profile["id"] = new_id
        new_profile["active"] = False
        new_profile["name"] = "Nuevo perfil"
        new_profile["engine"] = ENGINE_CHOICES[0]
        pm.add_profile(new_profile)
        self.load_profiles()
        # seleccionar el nuevo
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == new_id:
                self.list_widget.setCurrentItem(it)
                break

    def on_save(self):
        # recopilar campos (soporta QLineEdit y QComboBox)
        data = {}
        for k, w in self.edits.items():
            if isinstance(w, QLineEdit):
                data[k] = w.text().strip()
            elif isinstance(w, QComboBox):
                data[k] = w.currentText().strip()

        # validaciones: campos obligatorios
        required = ["name", "engine", "game_dir"]
        missing_required = [k for k in required if not data.get(k)]
        if missing_required:
            QMessageBox.warning(self, "Advertencia", f"Faltan campos obligatorios: {', '.join(missing_required)}")
            return

        # preparar perfil
        profile = {k: "" for k in pm.PROFILE_FIELDS}
        profile["id"] = self.current_id if self.current_id else str(uuid.uuid4())
        if self.current_id:
            existing = next((x for x in self.profiles if x.get("id") == self.current_id), {})
            profile["active"] = bool(existing.get("active", False))
        else:
            profile["active"] = False
        profile.update(data)

        # Si no hay app_id definido, tratar de extraerlo desde gameinfo.txt
        if not profile.get("steam_app_id") and profile.get("gameinfo_txt"):
            extracted_app_id = pm.extract_app_id_from_gameinfo(profile["gameinfo_txt"])
            if extracted_app_id:
                profile["steam_app_id"] = extracted_app_id
                if isinstance(self.edits.get("steam_app_id"), QLineEdit):
                    self.edits["steam_app_id"].setText(extracted_app_id)

        # validar engine value
        if profile.get("engine") not in ENGINE_CHOICES:
            QMessageBox.warning(self, "Advertencia", "Engine debe ser 'Source' o 'GoldSource'.")
            return

        # validar paths existentes
        v = pm.validate_profile(profile)
        if not v["ok"]:
            resp = QMessageBox.question(
                self,
                "Validación de paths",
                "Se encontraron campos faltantes o paths inexistentes:\n"
                + ", ".join(v["missing"])
                + "\n\n¿Desea guardar de todas formas?",
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        pm.update_profile(profile["id"], profile)
        self.load_profiles()
        # re-seleccionar el elemento guardado
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == profile["id"]:
                self.list_widget.setCurrentItem(it)
                break

    def on_delete(self):
        if not self.current_id:
            return
        resp = QMessageBox.question(self, "Eliminar perfil", "¿Eliminar el perfil seleccionado?")
        if resp != QMessageBox.StandardButton.Yes:
            return
        pm.delete_profile(self.current_id)
        self.load_profiles()
        # limpiar formulario
        for k, w in self.edits.items():
            if isinstance(w, QLineEdit):
                w.setText("")
            elif isinstance(w, QComboBox):
                if w.count():
                    w.setCurrentIndex(0)
        self.current_id = None

    def on_set_active(self):
        if not self.current_id:
            return
        pm.set_active_profile(self.current_id)
        self.load_profiles()
        self._notify_status_refresh()

    def _notify_status_refresh(self):
        window = self.window()
        if hasattr(window, "update_status_profile"):
            window.update_status_profile()
