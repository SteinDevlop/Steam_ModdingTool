from pathlib import Path
import logging
import json
import os
try:
    import vdf
except Exception:
    vdf = None

LOG = logging.getLogger(__name__)
SETTINGS_FILE = Path("config") / "settings.json"
DEFAULT_VDF = Path.home() / ".steam" / "steam" / "config" / "loginusers.vdf"

def _read_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            LOG.debug("Could not parse settings.json", exc_info=True)
    return {}

def get_vdf_path() -> Path:
    settings = _read_settings()
    custom = settings.get("steam_vdf_path")
    if custom:
        p = Path(os.path.expanduser(custom))
        if p.exists():
            return p
        LOG.debug("Custom steam_vdf_path set in settings but does not exist: %s", p)
        return p  # still return so caller can see error
    return DEFAULT_VDF

def get_steam_user_id() -> str | None:
    """
    Returns steamid64 (as str) of the most recent logged-in Steam user, or None.
    Logs a warning if no user is found or file cannot be read.
    """
    if vdf is None:
        LOG.warning("vdf library not available; cannot read loginusers.vdf")
        return None

    vdf_path = get_vdf_path()
    if not vdf_path.exists():
        LOG.warning("Steam loginusers.vdf not found at: %s", vdf_path)
        return None

    try:
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            data = vdf.load(f)
    except Exception as e:
        LOG.warning("Error parsing loginusers.vdf: %s", e)
        return None

    # Typical structure: { "users": { "7656119...": { "AccountName": "...", "MostRecent": "1", ... }, ... } }
    users = {}
    if isinstance(data, dict):
        # Try common keys
        if "users" in data and isinstance(data["users"], dict):
            users = data["users"]
        else:
            # Sometimes top-level *is* the users dict
            users = data

    most_recent_id = None
    for sid, info in users.items():
        if isinstance(info, dict):
            # keys may vary in capitalization
            mr = info.get("MostRecent") or info.get("mostrecent") or info.get("most_recent")
            if str(mr) in ("1", "true", "True", "yes"):
                most_recent_id = sid
                break

    if most_recent_id:
        return str(most_recent_id)
    LOG.warning("No Steam user marked as most recent in %s", vdf_path)
    return None
