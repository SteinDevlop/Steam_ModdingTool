import json
from pathlib import Path
from typing import List, Dict, Optional
import uuid

CONFIG_DIR = Path("config")
PROFILES_FILE = CONFIG_DIR / "profiles.json"

# Campos esperados en cada perfil
PROFILE_FIELDS = [
    "id",
    "name",                # editable combo (base names list)
    "engine",              # "Source" or "GoldSource"
    "steam_app_id",
    "game_dir",
    # Game setup
    "executable",          # ruta al exe principal del juego
    "executable_options",  # opciones de línea de comandos (texto)
    "gameinfo_txt",        # ruta a gameinfo.txt
    "model_compiler",      # ruta a model compiler (.exe)
    "model_viewer",        # ruta a model viewer (.exe)
    "mapping_tool",        # ruta a mapping tool (.exe)
    "packer_tool",         # ruta a packer tool (.exe)
    # Steam / Proton
    "steam_executable",    # ruta al ejecutable de Steam
]

def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def _example_profiles() -> List[Dict]:
    """Genera dos perfiles de ejemplo (L4D2 y GMod)."""
    return [
        {
            "id": str(uuid.uuid4()),
            "name": "Left 4 Dead 2",
            "engine": "Source",
            "steam_app_id": "550",
            "game_dir": "/path/to/left4dead2",
            "executable": "/path/to/left4dead2/hl2_linux",
            "executable_options": "",
            "gameinfo_txt": "/path/to/left4dead2/gameinfo.txt",
            "model_compiler": "/usr/bin/studiomdl",
            "model_viewer": "/usr/bin/hlmv",
            "mapping_tool": "/usr/bin/vmf_tool",
            "packer_tool": "/usr/bin/vpk",
            "steam_executable": "/usr/bin/steam",
            "active": True,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Garry's Mod",
            "engine": "GoldSource",
            "steam_app_id": "4000",
            "game_dir": "/path/to/gmod",
            "executable": "/path/to/gmod/gmod.exe",
            "executable_options": "",
            "gameinfo_txt": "/path/to/gmod/gameinfo.txt",
            "model_compiler": "/usr/bin/studiomdl",
            "model_viewer": "/usr/bin/hlmv",
            "mapping_tool": "/usr/bin/vmf_tool",
            "packer_tool": "/usr/bin/vpk",
            "steam_executable": "/usr/bin/steam",
            "active": False,
        },
    ]

def load_profiles() -> List[Dict]:
    """Retorna lista de perfiles desde JSON (o lista vacía si no existe)."""
    _ensure_config_dir()
    if not PROFILES_FILE.exists():
        # crear con ejemplos y persistir
        examples = _example_profiles()
        save_profiles(examples)
        return examples
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            # normalizar (asegurar campos)
            out = []
            for p in data:
                obj = {k: p.get(k, "") for k in PROFILE_FIELDS}
                obj["active"] = bool(p.get("active", False))
                out.append(obj)
            return out
    except Exception:
        return []

def save_profiles(profiles: List[Dict]) -> None:
    """Persiste la lista de perfiles en disco."""
    _ensure_config_dir()
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)

def validate_profile(profile: Dict) -> Dict:
    """
    Verifica que los paths obligatorios existan en el sistema de archivos.
    Devuelve dict con 'ok' (bool) y 'missing' (lista de keys faltantes).
    """
    missing = []
    # Campos cuya existencia en disco verificamos si no están vacíos
    check_paths = ["game_dir", "executable", "gameinfo_txt", "model_compiler", "model_viewer", "mapping_tool", "packer_tool", "steam_executable"]
    for key in check_paths:
        val = profile.get(key)
        if val:
            if not Path(val).exists():
                missing.append(key)
    # Campos obligatorios a nivel de formulario (no vacío)
    required = ["name", "engine", "game_dir"]
    for key in required:
        if not profile.get(key):
            missing.append(key)
    return {"ok": len(missing) == 0, "missing": missing}

def get_active_profile() -> Optional[Dict]:
    """Retorna el perfil marcado como activo o None."""
    profiles = load_profiles()
    for p in profiles:
        if p.get("active"):
            return p
    return None

def add_profile(profile: Dict) -> None:
    """Agrega un nuevo perfil (espera que tenga 'id')."""
    profiles = load_profiles()
    profiles.append(profile)
    save_profiles(profiles)

def update_profile(profile_id: str, new_profile: Dict) -> None:
    """Actualiza un perfil existente por id."""
    profiles = load_profiles()
    updated = False
    for i, p in enumerate(profiles):
        if p.get("id") == profile_id:
            profiles[i] = new_profile
            updated = True
            break
    if not updated:
        profiles.append(new_profile)
    save_profiles(profiles)

def delete_profile(profile_id: str) -> None:
    profiles = load_profiles()
    profiles = [p for p in profiles if p.get("id") != profile_id]
    save_profiles(profiles)

def set_active_profile(profile_id: str) -> None:
    profiles = load_profiles()
    for p in profiles:
        p["active"] = (p.get("id") == profile_id)
    save_profiles(profiles)
