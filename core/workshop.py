import socket
import json
import re
import os
import sys
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
import logging
import time
import urllib.request
import urllib.error
import urllib.parse

LOG = logging.getLogger(__name__)
SETTINGS_FILE = Path("config") / "settings.json"


def _load_settings() -> Dict[str, str]:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            LOG.debug("No se pudo leer settings.json", exc_info=True)
    return {}


def _get_steamcmd_path() -> str:
    settings = _load_settings()
    return settings.get("steamcmd_path", "steamcmd")


def _run_steamcmd(args: List[str], timeout: int = 600, steamcmd_path: Optional[str] = None) -> str:
    steamcmd = steamcmd_path or _get_steamcmd_path()
    cmd = [steamcmd] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise RuntimeError(f"steamcmd no encontrado en: {steamcmd}") from e
    except Exception as e:
        raise RuntimeError(f"Error ejecutando steamcmd: {e}") from e

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"steamcmd falló con código {proc.returncode}: {output.strip()}")
    return output


def _parse_steamcmd_published_file_id(output: str) -> Optional[str]:
    match = re.search(r"Published file id\s*[:\-]?\s*([0-9]+)", output, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(\d{5,})", output)
    return match.group(1) if match else None


def _find_steamapps_root(game_dir: Optional[str]) -> Optional[Path]:
    """
    Encuentra la raíz de steamapps desde game_dir.
    
    Busca hacia arriba desde game_dir hasta encontrar un directorio llamado 'steamapps'.
    Si game_dir es None, retorna None.
    
    Args:
        game_dir: Ruta del juego
    
    Returns:
        Ruta a la carpeta steamapps o None
    """
    if not game_dir:
        return None
    
    path = Path(game_dir).resolve()
    LOG.debug(f"_find_steamapps_root: buscando desde {path}")
    
    # Buscar hacia arriba
    for p in [path] + list(path.parents):
        if p.name.lower() == "steamapps":
            LOG.debug(f"  ✓ Encontrada raíz steamapps: {p}")
            return p
        LOG.debug(f"  Comprobando: {p.name}")
    
    LOG.warning(f"No se encontró carpeta 'steamapps' en la jerarquía de {game_dir}")
    return None


def _scan_local_workshop_items(app_id: str, game_dir: Optional[str]) -> List[Dict]:
    """Escanea artículos del workshop descargados localmente."""
    workshop_items: List[Dict] = []
    steamapps_root = _find_steamapps_root(game_dir)
    
    LOG.debug(f"_scan_local_workshop_items: app_id={app_id}, game_dir={game_dir}")
    
    if not steamapps_root:
        LOG.warning(f"No se encontró raíz steamapps para game_dir={game_dir}")
        return []
    
    LOG.debug(f"steamapps_root encontrada: {steamapps_root}")
    
    content_dir = steamapps_root / "workshop" / "content" / str(app_id)
    LOG.debug(f"Buscando en: {content_dir}")
    
    if not content_dir.exists():
        LOG.warning(f"Directorio de workshop no existe: {content_dir}")
        return []
    
    if not content_dir.is_dir():
        LOG.warning(f"La ruta no es un directorio: {content_dir}")
        return []
    
    try:
        children = list(content_dir.iterdir())
        LOG.debug(f"Encontrados {len(children)} elementos en {content_dir}")
        
        for child in sorted(children):
            if child.is_dir() and child.name.isdigit():
                item_id = child.name
                try:
                    ts = int(child.stat().st_mtime)
                except Exception:
                    ts = 0
                workshop_items.append({
                    "publishedfileid": item_id,
                    "title": item_id,
                    "description": "",
                    "visibility": "local",
                    "tags": [],
                    "time_updated": ts,
                })
        
        LOG.info(f"Se encontraron {len(workshop_items)} artículos locales en {content_dir}")
    except Exception as e:
        LOG.error(f"Error escaneando workshop items: {e}", exc_info=True)
    
    return workshop_items


def _fetch_item_details_from_steam(
    item_id: str,
    expected_creator: Optional[str] = None,
    expected_app_id: Optional[str] = None,
) -> Dict | None:
    """
    Obtiene detalles completos de un item de workshop usando la Steam Web API pública.
    Si se pasan expected_creator y/o expected_app_id, verifica que el item pertenezca
    a ese usuario y a ese juego — de lo contrario retorna None (no es del usuario/juego).

    Returns:
        Dict con title, description, visibility, tags, preview_url, time_updated o None.
    """
    try:
        url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
        data = urllib.parse.urlencode({"itemcount": 1, "publishedfileids[0]": item_id}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        obj = json.loads(raw)
        files = obj.get("response", {}).get("publishedfiledetails", [])
        if not files:
            return None
        f = files[0]
        if f.get("result", 1) != 1:
            return None

        # Verificar que el creador sea el usuario esperado
        if expected_creator:
            creator = str(f.get("creator", ""))
            if creator != str(expected_creator):
                LOG.debug(
                    f"Item {item_id} descartado: creador={creator!r} != esperado={expected_creator!r}"
                )
                return None

        # Verificar que el item pertenezca al juego (app) esperado
        if expected_app_id:
            item_app = str(f.get("consumer_app_id", "") or f.get("creator_app_id", ""))
            if item_app != str(expected_app_id):
                LOG.debug(
                    f"Item {item_id} descartado: app={item_app!r} != esperado={expected_app_id!r}"
                )
                return None

        # Mapear visibilidad: 0=public, 1=friends, 2=private, 3=unlisted
        vis_map = {0: "public", 1: "friends", 2: "private", 3: "unlisted"}
        visibility = vis_map.get(f.get("visibility", 0), "public")

        tags_raw = f.get("tags") or []
        tags = [t.get("tag", "") for t in tags_raw if isinstance(t, dict)]

        return {
            "title": f.get("title", "").strip() or item_id,
            "description": f.get("description", "").strip(),
            "visibility": visibility,
            "tags": tags,
            "preview_url": f.get("preview_url", ""),
            "time_updated": f.get("time_updated", int(time.time())),
            "creator": f.get("creator", ""),
            "app_name": f.get("app_name", ""),
            "consumer_app_id": str(f.get("consumer_app_id", "")),
        }
    except Exception as e:
        LOG.debug(f"No se pudo obtener detalles de Steam API para {item_id}: {e}")
        return None


def _extract_workshop_metadata(
    item_id: str,
    html: str,
    expected_creator: Optional[str] = None,
    expected_app_id: Optional[str] = None,
) -> Dict | None:
    """
    Extrae metadatos de un artículo desde el HTML del perfil del usuario.
    Primero intenta la Steam Web API (más confiable), luego hace scraping del HTML.
    Solo retorna el item si pertenece a expected_creator y expected_app_id (cuando se proveen).

    Returns:
        Dict con metadatos o None si no es un artículo válido del usuario/juego.
    """
    # --- Intentar Steam Web API primero ---
    api_details = _fetch_item_details_from_steam(
        item_id,
        expected_creator=expected_creator,
        expected_app_id=expected_app_id,
    )
    if api_details and api_details.get("title") and api_details["title"] != item_id:
        metadata = {
            "publishedfileid": item_id,
            "title": api_details["title"],
            "description": api_details.get("description", ""),
            "visibility": api_details.get("visibility", "public"),
            "tags": api_details.get("tags", []),
            "preview_url": api_details.get("preview_url", ""),
            "time_updated": api_details.get("time_updated", int(time.time())),
            "creator": api_details.get("creator", ""),
            "app_name": api_details.get("app_name", ""),
        }
        LOG.debug(f"Metadatos obtenidos de Steam API para {item_id}: title='{metadata['title']}'")
        return metadata

    # --- Fallback: scraping del HTML ---
    metadata = {
        "publishedfileid": item_id,
        "title": "",
        "description": "",
        "visibility": "public",
        "tags": [],
        "preview_url": "",
        "time_updated": int(time.time()),
        "creator": "",
        "app_name": "",
    }

    # Buscar contexto: buscar el ID en el HTML y tomar ventana de 800 chars
    # NOTA: Se evita usar {0,300} dentro de un f-string con re.escape porque
    # genera "multiple repeat" — en su lugar se usa indexación directa.
    idx = html.find(item_id)
    if idx == -1:
        LOG.debug(f"No se encontró el ID {item_id} en el HTML")
        return None

    start = max(0, idx - 400)
    end = min(len(html), idx + 400)
    context = html[start:end]

    # Intentar extraer título - múltiples patrones
    title = ""

    # Patrón 1: data-title="..."
    title_match = re.search(r'data-title=["\']([^"\']+)["\']', context)
    if title_match:
        title = title_match.group(1).strip()
        LOG.debug(f"Título extraído de data-title: {title}")

    # Patrón 2: atributo title en un enlace/elemento cercano
    if not title:
        title_match = re.search(r'title=["\']([^"\']{5,100})["\']', context)
        if title_match:
            candidate = title_match.group(1).strip()
            skip_words = ['ver ', 'view ', 'loading', 'click', 'open in']
            if not any(w in candidate.lower() for w in skip_words):
                title = candidate
                LOG.debug(f"Título extraído de title attribute: {title}")

    # Patrón 3: clase workshopItemTitle
    if not title:
        title_match = re.search(
            r'workshopItemTitle[^>]*>([^<]+)<',
            context,
            re.IGNORECASE
        )
        if title_match:
            title = title_match.group(1).strip()
            LOG.debug(f"Título extraído de workshopItemTitle: {title}")

    # Patrón 4: texto en span/div/a después del ID
    if not title:
        following = context[400:] if len(context) > 400 else context
        title_match = re.search(r'>([^<]{10,100})</(?:span|div|a)', following)
        if title_match:
            candidate = title_match.group(1).strip()
            skip_words = ['click', 'view', 'loading', 'error', 'published', 'updated']
            if not any(x in candidate.lower() for x in skip_words):
                title = candidate
                LOG.debug(f"Título extraído de elemento siguiente: {title}")

    # Si no se encontró título, usar el ID como fallback visible
    if not title or len(title) < 3:
        LOG.debug(f"No se encontró título para {item_id}, se usa ID como nombre")
        title = f"Item #{item_id}"

    metadata["title"] = title

    # Intentar extraer visibilidad
    ctx_lower = context.lower()
    if 'private' in ctx_lower:
        metadata["visibility"] = "private"
    elif 'friends only' in ctx_lower or 'friendsonly' in ctx_lower:
        metadata["visibility"] = "friends"
    else:
        metadata["visibility"] = "public"

    
    LOG.debug(f"Extraído: ID={item_id}, Título='{title}', Visibilidad={metadata['visibility']}")
    return metadata


def _extract_grid_section(html: str) -> str:
    """
    Aísla el bloque HTML que contiene el grid de items del workshop del usuario,
    descartando la navegación, sidebar, items relacionados y otras secciones.
    Esto evita capturar IDs de items de otros usuarios o juegos que aparecen
    en el resto de la página (sugerencias, items populares, etc.).
    """
    # Steam Workshop pone los items del usuario dentro de un div con id/class
    # "workshopBrowseItems" o "profile_block" / "workshopItemCards"
    candidates = [
        r'(<div[^>]+id=["\']workshopBrowseItems["\'][^>]*>.*?</div>\s*</div>)',
        r'(<div[^>]+class=["\'][^"\']*workshopItemCards[^"\']*["\'][^>]*>.*?</div>\s*</div>)',
        r'(<div[^>]+id=["\']profile_block["\'][^>]*>.*?</div>\s*</div>)',
    ]
    for pattern in candidates:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            LOG.debug(f"Sección de grid encontrada ({len(m.group(0))} chars)")
            return m.group(0)

    # Fallback: buscar desde la primera ocurrencia de "sharedfiles/filedetails"
    # hasta el final de la sección de items (antes de "related_items" o similar)
    start = html.find("sharedfiles/filedetails")
    if start == -1:
        LOG.debug("No se encontró ningún item de filedetails en el HTML")
        return html  # devolver todo como último recurso

    # Buscar marcadores que indican el fin del bloque de items del usuario
    end_markers = [
        "relatedWorkshopItems",
        "recommended_items",
        "workshopBrowseItems_end",
        "workshop_rightnav",
        '<div id="footer"',
    ]
    end = len(html)
    for marker in end_markers:
        pos = html.find(marker, start)
        if pos != -1 and pos < end:
            end = pos

    section = html[max(0, start - 500):end]
    LOG.debug(f"Sección de grid por fallback: {len(section)} chars desde pos {start}")
    return section


def _get_user_published_items(steam_id: str, app_id: str) -> List[Dict]:
    """
    Obtiene artículos publicados por el usuario en el juego indicado.
    Usa la página myworkshopfiles del perfil (que ya filtra por usuario y juego)
    y luego verifica cada ID con la Steam Web API para confirmar autoría y app.

    Args:
        steam_id: Steam ID64 del usuario
        app_id:   App ID del juego (ej. "550" para L4D2)

    Returns:
        Lista de dicts con publishedfileid, title, description, visibility, tags,
        preview_url, time_updated, creator, app_name — solo items del usuario en ese juego.
    """
    if not steam_id or not app_id:
        LOG.warning(f"steam_id o app_id vacíos: steam_id={steam_id}, app_id={app_id}")
        return []

    try:
        LOG.info(f"Consultando items publicados por {steam_id} en app {app_id}")

        items = []
        seen_ids: set = set()
        page = 1
        max_pages = 10

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        while page <= max_pages:
            # browsefilter=myfiles → solo items CREADOS por el usuario (no suscritos)
            # appid={app_id}       → solo items del juego seleccionado
            url = (
                f"https://steamcommunity.com/profiles/{steam_id}/myworkshopfiles/"
                f"?appid={app_id}&sort=recent&browsefilter=myfiles&view=gridview&p={page}"
            )
            LOG.debug(f"Consultando página {page}: {url}")

            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
                    html = response.read().decode("utf-8", errors="ignore")
                LOG.debug(f"Página {page} descargada: {len(html)} bytes")
            except urllib.error.URLError as e:
                LOG.warning(f"No se pudo descargar página {page}: {e}")
                break

            if not html or len(html) < 100:
                LOG.debug(f"Página {page} vacía, terminando")
                break

            # Aislar únicamente la sección del grid de items del usuario
            grid_html = _extract_grid_section(html)

            # Extraer IDs solo del bloque de items — patrón específico de filedetails
            raw_ids = re.findall(r'sharedfiles/filedetails/\?id=(\d+)', grid_html)
            # Deduplicar manteniendo orden
            page_ids = []
            for fid in raw_ids:
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    page_ids.append(fid)

            LOG.debug(f"IDs únicos encontrados en página {page}: {page_ids}")

            if not page_ids:
                LOG.debug(f"Sin IDs nuevos en página {page}, terminando paginación")
                break

            for item_id in page_ids:
                # Extraer snippet de HTML alrededor del ID para el fallback de scraping
                idx = grid_html.find(item_id)
                if idx != -1:
                    s = max(0, idx - 400)
                    e = min(len(grid_html), idx + 400)
                    snippet = grid_html[s:e]
                else:
                    snippet = ""

                # _extract_workshop_metadata → primero Steam API (con validación de
                # creator y app_id), luego scraping del snippet como fallback.
                metadata = _extract_workshop_metadata(
                    item_id,
                    snippet,
                    expected_creator=steam_id,
                    expected_app_id=app_id,
                )

                if metadata is not None:
                    items.append(metadata)
                else:
                    LOG.debug(
                        f"Item {item_id} descartado: no pertenece al usuario {steam_id} "
                        f"o al juego {app_id}, o no se pudieron obtener sus metadatos."
                    )

            page += 1
            time.sleep(0.8)  # pausa cortés entre páginas

        LOG.info(
            f"Total de artículos propios del usuario en app {app_id}: {len(items)}"
        )
        for idx, it in enumerate(items[:10], 1):
            LOG.debug(
                f"[{idx}] ID={it.get('publishedfileid')}, "
                f"Título={it.get('title')!r}, "
                f"Visibilidad={it.get('visibility')}"
            )
        return items

    except Exception as e:
        LOG.error(f"Error consultando items publicados: {e}", exc_info=True)
        return []


class PipeClient:
    """Cliente agnóstico del SO para comunicarse con CrowbarSteamPipe.
    
    Usa Unix domain sockets en Linux/Mac y TCP en Windows.
    """
    
    def __init__(self, pipe_name_suffix: str = ""):
        """Inicializa cliente de pipe."""
        self.pipe_name = f"CrowbarSteamPipe{pipe_name_suffix}"
        self.sock = None
        self.is_unix = sys.platform != "win32"
    
    def connect(self) -> None:
        """Conecta al servidor de pipe (Unix socket en Linux, TCP en Windows)."""
        try:
            if self.is_unix:
                self._connect_unix()
            else:
                self._connect_windows()
        except Exception as e:
            raise RuntimeError(f"Error conectando a {self.pipe_name}: {e}") from e
    
    def _connect_unix(self) -> None:
        """Conecta vía Unix domain socket."""
        socket_path = Path(f"/tmp/{self.pipe_name}.sock")
        if not socket_path.exists():
            raise FileNotFoundError(
                f"No se encontró el socket de CrowbarSteamPipe en {socket_path}. "
                "Asegúrate de que el servidor CrowbarSteamPipe esté corriendo."
            )
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(socket_path))
        LOG.debug(f"Conectado a socket Unix: {socket_path}")
    
    def _connect_windows(self) -> None:
        """Conecta vía TCP socket (emulación de named pipes en Windows)."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(("127.0.0.1", 9999))
        LOG.debug("Conectado a TCP socket en Windows")
    
    def connect_async(self, timeout: int = 10) -> None:
        """Intenta conectar con reintentos."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                self.connect()
                LOG.debug(f"Conectado a {self.pipe_name}")
                return
            except RuntimeError:
                time.sleep(0.5)
        raise RuntimeError(f"Timeout conectando a {self.pipe_name} después de {timeout}s")
    
    def send_command(self, command: str) -> str:
        """Envía comando y recibe respuesta."""
        if not self.sock:
            raise RuntimeError("No conectado a CrowbarSteamPipe")
        
        try:
            # Enviar comando
            cmd_bytes = (command + "\n").encode("utf-8")
            self.sock.sendall(cmd_bytes)
            
            # Recibir respuesta (línea completa)
            response = b""
            while b"\n" not in response:
                data = self.sock.recv(4096)
                if not data:
                    raise RuntimeError("Conexión cerrada por servidor")
                response += data
            
            return response.decode("utf-8").strip()
        except Exception as e:
            raise RuntimeError(f"Error en send_command: {e}") from e
    
    def send_command_with_args(self, command: str, *args: str) -> str:
        """Envía comando seguido de argumentos línea por línea."""
        if not self.sock:
            raise RuntimeError("No conectado a CrowbarSteamPipe")
        
        try:
            # Enviar comando principal
            cmd_bytes = (command + "\n").encode("utf-8")
            self.sock.sendall(cmd_bytes)
            
            # Enviar cada argumento
            for arg in args:
                arg_bytes = (str(arg) + "\n").encode("utf-8")
                self.sock.sendall(arg_bytes)
            
            # Recibir respuesta
            response = b""
            while b"\n" not in response:
                data = self.sock.recv(4096)
                if not data:
                    raise RuntimeError("Conexión cerrada por servidor")
                response += data
            
            return response.decode("utf-8").strip()
        except Exception as e:
            raise RuntimeError(f"Error en send_command_with_args: {e}") from e
    
    def close(self) -> None:
        """Cierra la conexión."""
        if self.sock:
            try:
                self.send_command("Free")
            except Exception:
                pass
            finally:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None


# Global pipe client
_pipe_client: Optional[PipeClient] = None


def _get_pipe_client() -> PipeClient:
    """Obtiene o crea cliente de pipe."""
    global _pipe_client
    if _pipe_client is None:
        _pipe_client = PipeClient()
        try:
            _pipe_client.connect_async(timeout=10)
        except Exception as e:
            raise RuntimeError(
                "No se pudo conectar a CrowbarSteamPipe. "
                "Asegúrate de que el servidor CrowbarSteamPipe esté corriendo y de que el socket exista en /tmp/CrowbarSteamPipe.sock. "
                "Si no estás usando CrowbarSteamPipe, esta funcionalidad no está disponible."
            ) from e
        # Inicializar Steam
        result = _pipe_client.send_command("Init")
        if result != "success":
            raise RuntimeError(f"Fallo al inicializar Steam: {result}")
    return _pipe_client


def _parse_query_response(response: str) -> List[Dict]:
    """Parsea respuesta de SteamUGC_SendQueryUGCRequest.
    
    El formato esperado es líneas con JSON o pares clave=valor.
    """
    items = []
    lines = response.strip().split("\n")
    
    for line in lines:
        if not line.strip():
            continue
        try:
            # Intentar parsear como JSON
            item = json.loads(line)
            items.append(item)
        except json.JSONDecodeError:
            # Parsear como pares clave=valor separados por |
            item = {}
            for pair in line.split("|"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    item[k.strip()] = v.strip()
            if item:
                items.append(item)
    
    return items


# --- Public API (CrowbarSteamPipe based) ---

def get_user_workshop_items(api_key: Optional[str], steam_id: Optional[str], app_id: str, game_dir: Optional[str] = None) -> List[Dict]:
    """
    Lista unicamente los items del taller CREADOS por el usuario en el juego indicado.

    Los items locales descargados (suscripciones de otros autores) NO se incluyen,
    porque steamapps/workshop/content/<appid>/ mezcla items propios y ajenos.

    Args:
        api_key:   Ignorado (compatibilidad)
        steam_id:  Steam ID64 del usuario
        app_id:    App ID del juego activo
        game_dir:  No se usa para listar (solo referencia)

    Returns:
        Lista de dicts con publishedfileid, title, description, visibility,
        tags, preview_url, time_updated, creator, app_name.
    """
    LOG.info(f"=== get_user_workshop_items ===")
    LOG.info(f"steam_id={steam_id}, app_id={app_id}, game_dir={game_dir}")

    if not steam_id:
        LOG.warning("No hay steam_id disponible — no se pueden listar items publicados.")
        return []

    published = _get_user_published_items(steam_id, app_id)
    LOG.info(f"Items propios del usuario en app {app_id}: {len(published)}")
    for idx, item in enumerate(published, 1):
        LOG.debug(
            f"[{idx}] {item.get('publishedfileid')}: {item.get('title')!r} "
            f"(visibilidad: {item.get('visibility')})"
        )
    return published


def create_workshop_item(api_key: Optional[str], app_id: str, metadata: Dict,
                        steamcmd_path: Optional[str] = None) -> str:
    """
    Crea nuevo item de taller usando steamcmd.
    
    Args:
        api_key: Ignorado
        app_id: ID de aplicación
        metadata: Dict con title, description, visibility, tags, contentfolder
        steamcmd_path: Optional path a steamcmd
    
    Returns:
        ID del item publicado
    """
    try:
        content_folder = metadata.get("contentfolder") or metadata.get("content") or ""
        if not content_folder:
            raise ValueError("contentfolder es obligatorio para crear un workshop item")
        content_path = Path(content_folder)
        if not content_path.exists():
            raise FileNotFoundError(f"Ruta de contenido no encontrada: {content_path}")

        title = metadata.get("title", "").strip()
        description = metadata.get("description", "").strip()
        visibility = metadata.get("visibility", "public")
        tags = metadata.get("tags") or []
        tags_str = ",".join(tags) if isinstance(tags, (list, tuple)) else str(tags or "")
        preview = metadata.get("preview") or ""

        args = [
            "+login",
            "anonymous",
            "+workshop_build_item",
            str(app_id),
            str(content_path),
            str(preview),
            title,
            description,
            visibility,
            tags_str,
            "+quit",
        ]
        output = _run_steamcmd(args, steamcmd_path=steamcmd_path)
        item_id = _parse_steamcmd_published_file_id(output)
        if not item_id:
            raise RuntimeError(f"No se pudo obtener el ID del item de la salida de steamcmd: {output}")
        return item_id
    except Exception as e:
        LOG.error(f"Error creando item de taller: {e}")
        raise


def update_workshop_item(api_key: Optional[str], item_id: str, metadata: Dict,
                        steamcmd_path: Optional[str] = None) -> str:
    """
    Actualiza item existente del taller usando steamcmd.
    
    Args:
        api_key: Ignorado
        item_id: ID del item a actualizar
        metadata: Dict con title, description, changelog, visibility, tags, contentfolder
        steamcmd_path: Optional path a steamcmd
    
    Returns:
        ID del item (sin cambios)
    """
    try:
        app_id = metadata.get("app_id", "")
        if not app_id:
            raise ValueError("app_id requerido en metadata para actualizar item")

        content_folder = metadata.get("contentfolder") or metadata.get("content") or ""
        if not content_folder:
            raise ValueError("contentfolder es obligatorio para actualizar item")
        content_path = Path(content_folder)
        if not content_path.exists():
            raise FileNotFoundError(f"Ruta de contenido no encontrada: {content_path}")

        title = metadata.get("title", "").strip()
        description = metadata.get("description", "").strip()
        visibility = metadata.get("visibility", "public")
        tags = metadata.get("tags") or []
        tags_str = ",".join(tags) if isinstance(tags, (list, tuple)) else str(tags or "")
        preview = metadata.get("preview") or ""

        args = [
            "+login",
            "anonymous",
            "+workshop_build_item",
            str(app_id),
            str(content_path),
            str(preview),
            title,
            description,
            visibility,
            tags_str,
            "+quit",
        ]
        output = _run_steamcmd(args)
        parsed_id = _parse_steamcmd_published_file_id(output)
        if not parsed_id:
            raise RuntimeError(f"No se pudo confirmar la actualización del item: {output}")
        return item_id
    except Exception as e:
        LOG.error(f"Error actualizando item de taller: {e}")
        raise


def upload_content(item_id: Optional[str], content_path: str, app_id: Optional[str] = None,
                  steamcmd_path: Optional[str] = None) -> str:
    """
    Sube contenido a item existente del taller usando steamcmd.
    
    Args:
        item_id: ID del item
        content_path: Ruta al contenido (archivo o carpeta)
        app_id: ID de aplicación
        steamcmd_path: Optional path a steamcmd
    
    Returns:
        ID del item
    """
    if not item_id or not app_id:
        raise ValueError("item_id y app_id requeridos para upload_content")
    try:
        p = Path(content_path)
        if not p.exists():
            raise FileNotFoundError(f"Ruta de contenido no encontrada: {content_path}")

        args = [
            "+login",
            "anonymous",
            "+workshop_build_item",
            str(app_id),
            str(p),
            "",
            "",
            "",
            "public",
            "",
            "+quit",
        ]
        output = _run_steamcmd(args)
        parsed_id = _parse_steamcmd_published_file_id(output)
        if not parsed_id:
            raise RuntimeError(f"No se pudo confirmar la subida de contenido: {output}")
        return item_id
    except Exception as e:
        LOG.error(f"Error subiendo contenido: {e}")
        raise


def cleanup() -> None:
    """Limpia recursos y cierra conexión con CrowbarSteamPipe."""
    global _pipe_client
    if _pipe_client:
        try:
            _pipe_client.close()
        except Exception as e:
            LOG.debug(f"Error en cleanup: {e}")
        finally:
            _pipe_client = None

