from pathlib import Path
import logging

LOG = logging.getLogger(__name__)

try:
    import vpk
except Exception as e:
    vpk = None
    LOG.debug("vpk library not available: %s", e)

def unpack_vpk(vpk_path: str, output_dir: str):
    """
    Extracts a VPK archive to output_dir using the vpk library.
    Returns list of extracted file paths (relative to output_dir).
    Raises descriptive exceptions on errors.
    """
    p = Path(vpk_path)
    if not p.exists():
        raise FileNotFoundError(f"VPK not found: {vpk_path}")
    if vpk is None:
        raise RuntimeError("vpk library not installed. Install 'vpk' from PyPI.")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        archive = vpk.VPK(str(p))
    except Exception as e:
        raise RuntimeError(f"Failed to open VPK: {e}") from e

    processed = []
    try:
        # vpk.VPK provides extract_all in many implementations
        if hasattr(archive, "extract_all"):
            archive.extract_all(str(out_dir))
            # Collect file list from archive entries
            for entry in archive.entries:
                # entry.path returns relative path typically
                try:
                    processed.append(str(Path(entry.path)))
                except Exception:
                    pass
        else:
            # Fallback: iterate files and write manually
            for path, entry in archive.paths.items():
                target = out_dir / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as fh:
                    fh.write(entry.read())
                processed.append(str(path))
    except Exception as e:
        raise RuntimeError(f"Error extracting VPK: {e}") from e

    return processed

def pack_vpk(source_dir: str, output_path: str):
    """
    Pack source_dir into a VPK. Not all vpk library versions provide packing.
    If packing is not available, raise NotImplementedError with instructions.
    """
    if vpk is None:
        raise RuntimeError("vpk library not installed. Install 'vpk' from PyPI.")
    # Many vpk bindings are read-only; check for pack function
    if hasattr(vpk, "pack") or hasattr(vpk, "create"):
        # Best-effort attempt
        try:
            if hasattr(vpk, "create"):
                vpk.create(str(source_dir), str(output_path))
                return [str(p) for p in Path(source_dir).rglob("*") if p.is_file()]
            elif hasattr(vpk, "pack"):
                vpk.pack(str(source_dir), str(output_path))
                return [str(p) for p in Path(source_dir).rglob("*") if p.is_file()]
        except Exception as e:
            raise RuntimeError(f"Error packing VPK: {e}") from e

    raise NotImplementedError(
        "Packing VPK is not supported by the installed 'vpk' library. "
        "If you need packing, consider installing a vpk library that provides pack/create, "
        "or implement packing via Valve's tools."
    )
