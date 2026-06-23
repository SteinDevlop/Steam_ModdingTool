import json
import tempfile
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Optional
import logging

LOG = logging.getLogger(__name__)
SETTINGS_FILE = Path("config") / "settings.json"


def _read_settings() -> Dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            LOG.debug("Could not parse settings.json", exc_info=True)
    return {}


def _get_steamcmd_path() -> str:
    settings = _read_settings()
    path = settings.get("steamcmd_path")
    return str(Path(path).expanduser()) if path else "steamcmd"


def _run_steamcmd_with_path(steamcmd: str, args: List[str], timeout: int = 300) -> str:
    cmd = [steamcmd] + args
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError(f"steamcmd not found at '{steamcmd}'. Set steamcmd_path in config/settings.json or install steamcmd.")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("steamcmd timed out") from e

    out = proc.stdout or ""
    if proc.returncode != 0:
        raise RuntimeError(f"steamcmd failed (rc={proc.returncode}): {out}")
    return out


def _run_steamcmd(args: List[str], timeout: int = 300, steamcmd_path: Optional[str] = None) -> str:
    steamcmd = steamcmd_path or _get_steamcmd_path()
    return _run_steamcmd_with_path(steamcmd, args, timeout=timeout)


def _dump_descriptor_to_file(descriptor: Dict, path: Path) -> None:
    """
    Try to dump descriptor dict to path as VDF using python-vdf if available,
    otherwise emit a simple VDF-like text sufficient for steamcmd.
    """
    try:
        import vdf  # type: ignore
        with path.open("w", encoding="utf-8") as f:
            vdf.dump(descriptor, f)
        return
    except Exception:
        # naive writer
        def _dump_kv(d: Dict, indent: int = 0) -> str:
            s = ""
            for k, v in d.items():
                if isinstance(v, dict):
                    s += "\t" * indent + f'"{k}"\n' + "\t" * indent + "{\n" + _dump_kv(v, indent + 1) + "\t" * indent + "}\n"
                else:
                    # ensure value is string
                    s += "\t" * indent + f'"{k}"\t"{v}"\n'
            return s

        with path.open("w", encoding="utf-8") as f:
            f.write(_dump_kv(descriptor))


def _write_descriptor_and_build(descriptor: Dict, timeout: int = 300, steamcmd_path: Optional[str] = None) -> str:
    """
    Write descriptor to a temporary .vdf and call steamcmd +workshop_build_item <file>.
    Returns parsed publishedfileid if found in output, otherwise returns steamcmd stdout.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".vdf")
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        _dump_descriptor_to_file(descriptor, tmp_path)
        out = _run_steamcmd(["+quit", f"+workshop_build_item {str(tmp_path)}"], timeout=timeout, steamcmd_path=steamcmd_path)
        m = re.search(r"PublishedFileId\s*[:=]\s*(\d+)", out) or re.search(r"publishedfileid\s*[:=]\s*(\d+)", out, re.I)
        return m.group(1) if m else out
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def _scrape_user_workshop_items(steam_id: str, app_id: str) -> List[Dict]:
    """
    Minimal scraping fallback for public profiles. Returns list of dicts:
    { publishedfileid, title, description, visibility, tags, time_updated }
    """
    try:
        import requests  # local optional dependency
    except Exception:
        raise RuntimeError("requests library is required for scraping fallback") from None

    if not steam_id:
        raise ValueError("steam_id required for scraping fallback.")

    items: List[Dict] = []
    session = requests.Session()
    page = 1
    while True:
        url = f"https://steamcommunity.com/profiles/{steam_id}/myworkshopfiles/?appid={app_id}&p={page}"
        try:
            r = session.get(url, timeout=15)
        except requests.RequestException as e:
            raise RuntimeError(f"Network error scraping Steam Community: {e}") from e

        if r.status_code != 200:
            raise RuntimeError(f"Failed to fetch community page (HTTP {r.status_code}). Ensure Steam profile is public or use steamcmd login.")

        html = r.text

        matches = re.findall(
            r'<a[^>]*class="[^"]*workshopItemTitle[^"]*"[^>]*href="[^"]*id=(\d+)[^"]*"[^>]*>(.*?)</a>',
            html, flags=re.S | re.I
        )
        if not matches:
            matches = re.findall(
                r'href="/sharedfiles/filedetails/\?id=(\d+)"[^>]*>\s*<div[^>]*class="workshopItemTitle"[^>]*>\s*(.*?)\s*</div>',
                html, flags=re.S | re.I
            )
            if not matches:
                break

        for pid, title_raw in matches:
            title = re.sub(r'<[^>]+>', '', title_raw).strip()
            items.append({
                "publishedfileid": str(pid),
                "title": title,
                "description": "",
                "visibility": "public",
                "tags": [],
                "time_updated": 0,
            })

        if 'workshopBrowsePaging' in html and f'&p={page+1}' in html:
            page += 1
            continue
        break

    if not items:
        raise RuntimeError("No public Workshop items found via scraping. Profile may be private or empty; consider using steamcmd login.")
    return items


try:
    from . import steam_native
except Exception:
    steam_native = None


# --- Public API (steamcmd-based, scraping fallback) ---
def get_user_workshop_items(api_key: Optional[str], steam_id: Optional[str], app_id: str) -> List[Dict]:
    """
    List user's workshop items. api_key parameter is ignored in steamcmd mode.
    Attempts to use provided steam_id, else reads local Steam session.
    Falls back to scraping public profile pages.
    """
    if not steam_id:
        try:
            from .steam_session import get_steam_user_id
            steam_id = get_steam_user_id()
        except Exception:
            steam_id = None

    if not steam_id:
        raise ValueError("No steam_id provided and cannot determine local Steam user. Ensure Steam is logged in locally or provide steam_id.")

    return _scrape_user_workshop_items(steam_id, app_id)


def create_workshop_item(api_key: Optional[str], app_id: str, metadata: Dict, steamcmd_path: Optional[str] = None) -> str:
    """
    Try native Steam API (SteamAPI_Init + SteamUGC) if available; fall back to steamcmd descriptor build.
    """
    # Intentar integración nativa primero si el módulo está presente
    if steam_native:
        try:
            if steam_native.steam_api_init():
                try:
                    return steam_native.create_item_via_native(int(app_id), metadata)
                except NotImplementedError:
                    # native binding not implemented beyond init -> fallback
                    LOG.debug("steam_native present but create_item_via_native not implemented; falling back to steamcmd.")
                except Exception as e:
                    LOG.debug("steam_native.create_item_via_native failed: %s; falling back to steamcmd.", e)
        except Exception as e:
            LOG.debug("steam_native initialization failed: %s", e)

    # Fallback: steamcmd descriptor path
    descriptor = {
        "workshopitem": {
            "appid": str(app_id),
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "contentfolder": metadata.get("contentfolder", ""),
            "visibility": str(metadata.get("visibility", "")),
            "tags": ",".join(metadata.get("tags", [])) if metadata.get("tags") else ""
        }
    }
    return _write_descriptor_and_build(descriptor, steamcmd_path=steamcmd_path)


def update_workshop_item(api_key: Optional[str], item_id: str, metadata: Dict, steamcmd_path: Optional[str] = None) -> str:
    """
    Try native SteamUGC update if available; otherwise use steamcmd descriptor.
    """
    if steam_native:
        try:
            if steam_native.steam_api_init():
                try:
                    return steam_native.start_item_update_via_native(str(item_id))  # placeholder: real impl should handle update handle + submit
                except NotImplementedError:
                    LOG.debug("steam_native.update not implemented; falling back to steamcmd.")
                except Exception as e:
                    LOG.debug("steam_native.update failed: %s; falling back.", e)
        except Exception as e:
            LOG.debug("steam_native init failed: %s", e)

    descriptor = {
        "workshopitem": {
            "publishedfileid": str(item_id),
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "change_note": metadata.get("changelog", ""),
            "visibility": str(metadata.get("visibility", "")),
            "tags": ",".join(metadata.get("tags", [])) if metadata.get("tags") else ""
        }
    }
    return _write_descriptor_and_build(descriptor, steamcmd_path=steamcmd_path)


def upload_content(item_id: Optional[str], content_path: str, app_id: Optional[str] = None, steamcmd_path: Optional[str] = None) -> str:
    """
    Try native SteamUGC upload if available; otherwise use steamcmd descriptor.
    """
    if steam_native:
        try:
            if steam_native.steam_api_init():
                try:
                    # native path would call StartItemUpdate + SetContent/SetPreview + SubmitItemUpdate
                    return steam_native.submit_item_update_via_native(str(item_id), str(content_path))
                except NotImplementedError:
                    LOG.debug("steam_native upload not implemented; falling back to steamcmd.")
                except Exception as e:
                    LOG.debug("steam_native.upload failed: %s; falling back.", e)
        except Exception as e:
            LOG.debug("steam_native init failed: %s", e)

    # Fallback to existing steamcmd descriptor approach
    p = Path(content_path)
    if not p.exists():
        raise FileNotFoundError(f"Content path not found: {content_path}")

    descriptor = {
        "workshopitem": {
            "appid": str(app_id) if app_id else "",
            "publishedfileid": str(item_id) if item_id else "",
            "contentfolder": str(content_path) if p.is_dir() else str(p.parent),
        }
    }

    if steamcmd_path:
        settings = _read_settings()
        settings["steamcmd_path"] = steamcmd_path
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

    return _write_descriptor_and_build(descriptor, steamcmd_path=steamcmd_path)
