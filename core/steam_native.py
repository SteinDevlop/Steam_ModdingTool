import ctypes
import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict

LOG = logging.getLogger(__name__)
_lib = None

def _candidates() -> list[str]:
    # rutas típicas en Linux/Windows; el usuario puede configurar steamcmd_path en settings.json
    home = Path.home()
    return [
        "/usr/lib/libsteam_api.so",
        "/usr/lib64/libsteam_api.so",
        str(home / ".steam" / "ubuntu12_32" / "steam" / "bin" / "libsteam_api.so"),
        "steam_api64.dll",
        "libsteam_api.so",
    ]

def _find_library() -> Optional[str]:
    for p in _candidates():
        if Path(p).exists():
            return p
    # intentar cargar por nombre si está en PATH
    return None

def is_available() -> bool:
    """True si es plausible encontrar la librería nativa de Steam."""
    return _find_library() is not None

def steam_api_init() -> bool:
    """
    Intenta inicializar SteamAPI vía la librería nativa (SteamAPI_Init).
    Retorna True si la llamada existe y devuelve éxito.
    Nota: esto sólo llama a SteamAPI_Init; las funciones UGC requieren bindings C++/SDK adicionales.
    """
    global _lib
    if _lib is None:
        libpath = _find_library()
        if libpath is None:
            LOG.debug("steam_native: libsteam_api no encontrada")
            return False
        try:
            if sys.platform.startswith("win"):
                _lib = ctypes.WinDLL(libpath)
            else:
                _lib = ctypes.CDLL(libpath)
        except Exception as e:
            LOG.debug("steam_native: fallo cargando librería nativa: %s", e)
            return False
    try:
        func = getattr(_lib, "SteamAPI_Init", None)
        if not func:
            LOG.debug("steam_native: SteamAPI_Init no exportada en la librería")
            return False
        func.restype = ctypes.c_bool
        res = func()
        LOG.debug("steam_native: SteamAPI_Init -> %s", res)
        return bool(res)
    except Exception as e:
        LOG.debug("steam_native: error llamando SteamAPI_Init: %s", e)
        return False

# Placeholders / guía
def create_item_via_native(appid: int, metadata: Dict) -> str:
    """
    Placeholder: crear item usando SteamUGC/SteamAPI nativo.
    Implementar con bindings del SDK (C++ extension) o usar una librería Python que exponga SteamUGC.
    Por ahora lanza NotImplementedError con instrucciones.
    """
    raise NotImplementedError(
        "Crear item vía SteamUGC no está implementado en este wrapper Python. "
        "Implementa un binding C++ que llame a SteamAPI_Init() y a SteamUGC()->CreateItem(), "
        "o instala/usa una librería Python que lo exponga (por ejemplo un wrapper de Steamworks SDK)."
    )

def start_item_update_via_native(publishedfileid: str):
    raise NotImplementedError("StartItemUpdate via native SteamUGC no implementado.")

def submit_item_update_via_native(update_handle, changenote: str = ""):
    raise NotImplementedError("SubmitItemUpdate via native SteamUGC no implementado.")
