import logging
import os
import tempfile
from functools import lru_cache

logger = logging.getLogger(__name__)


def _writable_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".write_test_", delete=True):
            pass
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def resolve_upload_dir() -> str:
    """Resuelve un directorio de uploads con preferencia por disco persistente.

    Prioridad:
    1) UPLOAD_DIR explícito.
    2) RENDER_DISK_PATH/uploads si Render expone el path del disco.
    3) /var/data/uploads (mount path más común en Render).
    4) /tmp/uploads como último fallback (efímero).
    """
    candidates: list[str] = []

    configured = (os.getenv("UPLOAD_DIR") or "").strip()
    if configured:
        candidates.append(configured)

    render_disk = (os.getenv("RENDER_DISK_PATH") or "").strip()
    if render_disk:
        candidates.append(os.path.join(render_disk, "uploads"))

    candidates.append("/var/data/uploads")

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if _writable_dir(candidate):
            return candidate

    fallback = "/tmp/uploads"
    os.makedirs(fallback, exist_ok=True)
    logger.warning(
        "Using ephemeral upload directory '%s'. Configure UPLOAD_DIR or mount a Render disk.",
        fallback,
    )
    return fallback
