"""
Download file attachments linked to purchase bills and manual accounting entries only.

Does NOT use the inbox file list (GET /3.0/files). Files are resolved from:
  - 4.0/purchase/bills → attachment_ids
  - 3.0/accounting/manual_entries → compound + line-level files

Usage:
  python download_bexio_booking_attachments.py
  BEXIO_BOOKING_DOCUMENTS_DIR=./booking_docs python download_bexio_booking_attachments.py
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

from bexio_credentials import build_headers, resolve_bearer_token
from dlt_pipeline import grab_data, request_with_retries

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = "bexio_booking_documents"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
PAGE_LIMIT = 2000


@dataclass
class FileTarget:
    uuid: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    file_meta: dict[str, Any] = field(default_factory=dict)


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _parse_attachment_ids(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
            return [str(parsed)]
        except (SyntaxError, ValueError):
            return [text]
    return [str(value)]


def _safe_part(text: str, fallback: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", (text or "").strip()).strip(" .")
    return cleaned or fallback


def _filename_from_disposition(header: str | None, fallback: str) -> str:
    if not header:
        return fallback
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.I)
    if match:
        return INVALID_FILENAME_CHARS.sub("_", unquote(match.group(1).strip()))
    return fallback


def _page_get(path: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    offset = 0
    rows: list[dict[str, Any]] = []
    while True:
        response = request_with_retries(path, {"limit": PAGE_LIMIT, "offset": offset}, headers)
        batch = response.json()
        if not batch:
            break
        if isinstance(batch, dict) and "data" in batch:
            batch = batch["data"]
        if not isinstance(batch, list):
            break
        rows.extend(batch)
        if len(batch) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return rows


def _register(targets: dict[str, FileTarget], uuid: str, source: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
    if not uuid:
        return
    entry = targets.setdefault(uuid, FileTarget(uuid=uuid))
    entry.sources.append(source)
    if meta:
        entry.file_meta.update(meta)


def collect_bill_attachments(headers: dict[str, str]) -> dict[str, FileTarget]:
    targets: dict[str, FileTarget] = {}
    for bill in grab_data("4.0/purchase/bills", 500, headers):
        bill_id = bill.get("id")
        document_no = bill.get("document_no") or bill_id
        for uuid in _parse_attachment_ids(bill.get("attachment_ids")):
            _register(
                targets,
                uuid,
                {
                    "type": "purchase_bill",
                    "bill_id": bill_id,
                    "document_no": document_no,
                    "title": bill.get("title"),
                    "status": bill.get("status"),
                    "bill_date": bill.get("bill_date"),
                    "vendor": bill.get("vendor"),
                },
            )
    logger.info("Collected %s unique file UUIDs from purchase bills", len(targets))
    return targets


def collect_manual_entry_files(headers: dict[str, str]) -> dict[str, FileTarget]:
    targets: dict[str, FileTarget] = {}
    entries = _page_get("3.0/accounting/manual_entries", headers)
    logger.info("Scanning %s manual entries for attachments...", len(entries))

    for idx, entry in enumerate(entries, start=1):
        me_id = entry.get("id")
        if me_id is None:
            continue
        base_source = {
            "type": "manual_entry",
            "manual_entry_id": me_id,
            "reference_nr": entry.get("reference_nr"),
            "date": entry.get("date"),
            "booking_type": entry.get("booking_type"),
        }

        compound = request_with_retries(
            f"3.0/accounting/manual_entries/{me_id}/files", {}, headers
        ).json()
        if isinstance(compound, list):
            for meta in compound:
                uuid = str(meta.get("uuid") or "")
                _register(targets, uuid, {**base_source, "attachment_level": "compound"}, meta)

        for line in entry.get("entries") or []:
            entry_id = line.get("id")
            if entry_id is None:
                continue
            line_files = request_with_retries(
                f"3.0/accounting/manual_entries/{me_id}/entries/{entry_id}/files",
                {},
                headers,
            ).json()
            if not isinstance(line_files, list):
                continue
            for meta in line_files:
                uuid = str(meta.get("uuid") or "")
                _register(
                    targets,
                    uuid,
                    {
                        **base_source,
                        "attachment_level": "line",
                        "entry_id": entry_id,
                        "description": line.get("description"),
                    },
                    meta,
                )

        if idx % 100 == 0:
            logger.info("  ... scanned %s / %s manual entries", idx, len(entries))

    logger.info("Collected %s unique file UUIDs from manual entries", len(targets))
    return targets


def _pick_subdir(sources: list[dict[str, Any]]) -> str:
    types = {s.get("type") for s in sources}
    if "purchase_bill" in types and "manual_entry" in types:
        return "mixed"
    if "purchase_bill" in types:
        return "purchase_bills"
    return "manual_entries"


def _fallback_name(target: FileTarget) -> str:
    meta = target.file_meta
    name = str(meta.get("name") or target.uuid)
    ext = str(meta.get("extension") or "pdf").lstrip(".")
    short = _safe_part(name, target.uuid[:8])
    return f"{target.uuid}_{short}.{ext}"


def download_booking_attachments(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = build_headers(resolve_bearer_token())

    bill_targets = collect_bill_attachments(headers)
    manual_targets = collect_manual_entry_files(headers)

    merged: dict[str, FileTarget] = {}
    for bucket in (bill_targets, manual_targets):
        for uuid, target in bucket.items():
            if uuid not in merged:
                merged[uuid] = FileTarget(uuid=uuid)
            merged[uuid].sources.extend(target.sources)
            merged[uuid].file_meta.update(target.file_meta)

    logger.info("Total unique attachment UUIDs to download: %s", len(merged))

    manifest: list[dict[str, Any]] = []
    downloaded = 0
    skipped = 0
    failed = 0

    for target in merged.values():
        subdir = output_dir / _pick_subdir(target.sources)
        subdir.mkdir(parents=True, exist_ok=True)
        fallback = _fallback_name(target)
        dest = subdir / fallback

        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            manifest.append(
                {
                    "uuid": target.uuid,
                    "sources": target.sources,
                    "local_path": str(dest),
                    "status": "skipped_existing",
                }
            )
            continue

        try:
            response = request_with_retries(f"3.0/files/{target.uuid}/download", {}, headers)
            filename = _filename_from_disposition(
                response.headers.get("Content-Disposition"),
                fallback,
            )
            if not filename.startswith(target.uuid):
                filename = f"{target.uuid}_{filename}"
            dest = subdir / filename
            dest.write_bytes(response.content)
            downloaded += 1
            logger.info("Downloaded %s (%s bytes)", dest.relative_to(output_dir), len(response.content))
            manifest.append(
                {
                    "uuid": target.uuid,
                    "sources": target.sources,
                    "file_meta": target.file_meta,
                    "local_path": str(dest),
                    "bytes": len(response.content),
                    "status": "downloaded",
                }
            )
        except requests.RequestException as exc:
            failed += 1
            logger.error("Failed uuid=%s: %s", target.uuid, exc)
            manifest.append(
                {
                    "uuid": target.uuid,
                    "sources": target.sources,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    summary = {
        "output_dir": str(output_dir.resolve()),
        "unique_uuids": len(merged),
        "from_bills": len(bill_targets),
        "from_manual_entries": len(manual_targets),
        "downloaded": downloaded,
        "skipped_existing": skipped,
        "failed": failed,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps({"summary": summary, "files": manifest}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    _configure_logging()
    out = Path(os.getenv("BEXIO_BOOKING_DOCUMENTS_DIR", DEFAULT_OUTPUT_DIR))
    summary = download_booking_attachments(out)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
