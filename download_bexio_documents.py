"""
Download all Bexio inbox/files (3.0/files) to a local folder.

For bill + manual-entry attachments only (not inbox), use download_bexio_booking_attachments.py.

Usage:
  python download_bexio_documents.py
  BEXIO_DOCUMENTS_DIR=./my_docs python download_bexio_documents.py
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

from bexio_credentials import build_headers, resolve_bearer_token
from dlt_pipeline import grab_data, request_with_retries

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = "bexio_documents"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _safe_filename(file_id: int, name: str, extension: str) -> str:
    base = INVALID_FILENAME_CHARS.sub("_", (name or f"file_{file_id}").strip()).strip(" .")
    if not base:
        base = f"file_{file_id}"
    ext = (extension or "").lstrip(".").lower()
    if ext and not base.lower().endswith(f".{ext}"):
        return f"{file_id}_{base}.{ext}"
    return f"{file_id}_{base}"


def _filename_from_disposition(header: str | None, fallback: str) -> str:
    if not header:
        return fallback
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.I)
    if match:
        return INVALID_FILENAME_CHARS.sub("_", unquote(match.group(1).strip()))
    return fallback


def download_all_documents(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = build_headers(resolve_bearer_token())
    manifest: list[dict[str, Any]] = []
    downloaded = 0
    skipped = 0
    failed = 0

    for meta in grab_data("3.0/files", 2000, headers):
        file_id = meta.get("id")
        if file_id is None:
            continue
        fallback = _safe_filename(
            int(file_id),
            str(meta.get("name") or ""),
            str(meta.get("extension") or ""),
        )
        dest = output_dir / fallback
        if dest.exists() and dest.stat().st_size > 0:
            logger.info("Skip existing %s", dest.name)
            skipped += 1
            manifest.append({**meta, "local_path": str(dest), "status": "skipped_existing"})
            continue

        try:
            response = request_with_retries(
                f"3.0/files/{file_id}/download",
                {},
                headers,
            )
            filename = _filename_from_disposition(
                response.headers.get("Content-Disposition"),
                fallback,
            )
            if not filename.startswith(f"{file_id}_"):
                filename = f"{file_id}_{filename}"
            dest = output_dir / filename
            dest.write_bytes(response.content)
            downloaded += 1
            logger.info("Downloaded %s (%s bytes)", dest.name, len(response.content))
            manifest.append(
                {
                    **meta,
                    "local_path": str(dest),
                    "bytes": len(response.content),
                    "status": "downloaded",
                }
            )
        except requests.RequestException as exc:
            failed += 1
            logger.error("Failed file_id=%s: %s", file_id, exc)
            manifest.append({**meta, "status": "failed", "error": str(exc)})

    summary = {
        "output_dir": str(output_dir.resolve()),
        "downloaded": downloaded,
        "skipped_existing": skipped,
        "failed": failed,
        "total": len(manifest),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"summary": summary, "files": manifest}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    _configure_logging()
    out = Path(os.getenv("BEXIO_DOCUMENTS_DIR", DEFAULT_OUTPUT_DIR))
    summary = download_all_documents(out)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
