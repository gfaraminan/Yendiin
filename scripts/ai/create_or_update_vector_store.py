from __future__ import annotations

import os
import re
from pathlib import Path

import requests

OPENAI_API_BASE = "https://api.openai.com/v1"


def _api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY no configurada")
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
    }


def _detect_docs_dir() -> Path:
    readme = Path("README.md")
    if readme.exists():
        text = readme.read_text(encoding="utf-8")

        code_matches = re.findall(r"`([^`]*docs/[^`]*)`", text)
        md_link_matches = re.findall(r"\[[^\]]+\]\(([^)]*docs/[^)]*)\)", text)

        for match in [*code_matches, *md_link_matches]:
            cleaned = match.strip().strip("./")
            p = Path(cleaned)
            if p.exists():
                return p if p.is_dir() else p.parent

    fallback = Path("docs")
    if fallback.exists():
        return fallback
    raise RuntimeError("No se encontró carpeta de documentación")


def _create_vector_store_if_needed(vector_store_id: str | None) -> str:
    if vector_store_id:
        return vector_store_id
    resp = requests.post(
        f"{OPENAI_API_BASE}/vector_stores",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"name": "ticketera-support-docs"},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _iter_docs_files(docs_dir: Path):
    for p in docs_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".md", ".txt", ".pdf"}:
            yield p


def _upload_file(path: Path) -> str:
    with path.open("rb") as fh:
        resp = requests.post(
            f"{OPENAI_API_BASE}/files",
            headers=_headers(),
            data={"purpose": "assistants"},
            files={"file": (path.name, fh)},
            timeout=90,
        )
    resp.raise_for_status()
    return resp.json()["id"]


def _attach_file_to_vector_store(vector_store_id: str, file_id: str) -> None:
    resp = requests.post(
        f"{OPENAI_API_BASE}/vector_stores/{vector_store_id}/files",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"file_id": file_id},
        timeout=45,
    )
    resp.raise_for_status()




def _vector_store_item_file_id(item: dict) -> str | None:
    # In OpenAI vector store file listings, `file_id` is the file object id.
    # Some payloads may still expose only `id` depending on API shape/version.
    return item.get("file_id") or item.get("id")


def _existing_vector_store_file_ids(vector_store_id: str) -> set[str]:
    existing: set[str] = set()
    cursor: str | None = None
    while True:
        params = {"limit": 100}
        if cursor:
            params["after"] = cursor
        resp = requests.get(
            f"{OPENAI_API_BASE}/vector_stores/{vector_store_id}/files",
            headers=_headers(),
            params=params,
            timeout=45,
        )
        resp.raise_for_status()
        payload = resp.json()
        for item in payload.get("data", []):
            file_id = _vector_store_item_file_id(item)
            if file_id:
                existing.add(file_id)

        if not payload.get("has_more"):
            break
        data = payload.get("data", [])
        if not data:
            break
        cursor = data[-1].get("id")
        if not cursor:
            break
    return existing


def _file_info(file_id: str) -> tuple[str | None, int | None]:
    resp = requests.get(f"{OPENAI_API_BASE}/files/{file_id}", headers=_headers(), timeout=45)
    resp.raise_for_status()
    payload = resp.json()
    filename = payload.get("filename")
    size = payload.get("bytes")
    return filename, int(size) if isinstance(size, int) else None


def _existing_filename_sizes(vector_store_id: str) -> dict[str, set[int]]:
    by_name: dict[str, set[int]] = {}
    for file_id in _existing_vector_store_file_ids(vector_store_id):
        try:
            name, size = _file_info(file_id)
            if not name or size is None:
                continue
            by_name.setdefault(name, set()).add(size)
        except Exception:
            continue
    return by_name


def _should_skip_upload(path: Path, existing_filename_sizes: dict[str, set[int]]) -> bool:
    sizes = existing_filename_sizes.get(path.name)
    if not sizes:
        return False
    return path.stat().st_size in sizes


def main() -> None:
    docs_dir = _detect_docs_dir()
    vector_store_id = _create_vector_store_if_needed((os.getenv("OPENAI_VECTOR_STORE_ID") or "").strip() or None)
    existing_filename_sizes = _existing_filename_sizes(vector_store_id)

    print(f"Usando docs dir: {docs_dir}")
    uploaded = 0
    skipped = 0

    for path in _iter_docs_files(docs_dir):
        if _should_skip_upload(path, existing_filename_sizes):
            skipped += 1
            print(f"Skip (ya existe nombre+tamaño): {path.name}")
            continue
        file_id = _upload_file(path)
        _attach_file_to_vector_store(vector_store_id, file_id)
        uploaded += 1
        existing_filename_sizes.setdefault(path.name, set()).add(path.stat().st_size)
        print(f"Indexado: {path} -> {file_id}")

    print(f"Archivos subidos: {uploaded}")
    print(f"Archivos omitidos: {skipped}")
    print(f"vector_store_id={vector_store_id}")


if __name__ == "__main__":
    main()
