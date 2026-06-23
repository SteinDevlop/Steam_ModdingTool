from PyQt6.QtWidgets import QMainWindow, QWidget, QTabWidget, QVBoxLayout, QLabel, QStatusBar
from PyQt6.QtCore import Qt
from ui.log_widget import LogWidget
from ui.config_tab import ConfigTab
from ui.workshop_tab import WorkshopTab
from ui.download_tab import DownloadTab
from ui.options_tab import OptionsTab
from core.profile_manager import get_active_profile

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ModTool Linux")
        self.resize(960, 680)
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        v = QVBoxLayout(central)

        self.tabs = QTabWidget()

        self.config_tab   = ConfigTab()
        self.tools_tab    = QWidget()      # placeholder
        self.workshop_tab = WorkshopTab()
        self.download_tab = DownloadTab()
        self.help_tab     = QWidget()      # placeholder
        self.options_tab  = OptionsTab()

        # Placeholders simples
        for w, name in [
            (self.tools_tab, "Herramientas"),
            (self.help_tab,  "Ayuda"),
        ]:
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay = QVBoxLayout(w)
            lay.addWidget(lbl)

        self.tabs.addTab(self.config_tab,   "Configuración")
        self.tabs.addTab(self.tools_tab,    "Herramientas")
        self.tabs.addTab(self.workshop_tab, "Workshop")
        self.tabs.addTab(self.download_tab, "Descargar")
        self.tabs.addTab(self.help_tab,     "Ayuda")
        self.tabs.addTab(self.options_tab,  "Opciones")

        v.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.update_status_profile()

    def update_status_profile(self):
        try:
            prof = get_active_profile()
        except Exception:
            prof = None
        if prof:
            self.status.showMessage(f"Listo — Perfil activo: {prof.get('name')}")
        else:
            self.status.showMessage("Listo — Sin perfil activo")
