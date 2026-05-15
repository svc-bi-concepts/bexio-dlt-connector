"""
Persistent loader observability: last run timestamps and per-resource row change counts.

Uses a fingerprint map (business id -> row_hash) stored on disk after each *successful*
`pipeline.run` for a resource. The next run classifies extracted rows as new / updated /
unchanged before dlt merge. Fingerprint updates only on success so a failed load does not
advance state.

Rows removed from the API are not flagged here (fingerprints only update for ids seen in a
successful run); use warehouse SCD2 validity or explicit reconciliation if you need deletes.

Env:
  BEXIO_DATA_DIR          block volume root in SPCS (e.g. /data); local default: ./.bexio_pipeline_data
  BEXIO_LOADER_STATE_DIR  optional override for state root (default: {BEXIO_DATA_DIR}/loader_state)

Each completed pipeline run also writes an immutable snapshot under history/ (same payload as
last_run.json). last_run.json remains the latest view for convenience.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Mapping, MutableMapping, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

ChangeKind = Literal["new", "updated", "unchanged", "no_id"]


def _default_data_dir() -> str:
    # SPCS sets BEXIO_DATA_DIR=/data via job spec; local runs fall back to a repo-relative dir.
    return (os.getenv("BEXIO_DATA_DIR") or "").strip() or os.path.join(os.getcwd(), ".bexio_pipeline_data")


def state_root() -> Path:
    explicit = (os.getenv("BEXIO_LOADER_STATE_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    return Path(_default_data_dir()) / "loader_state"


def fingerprint_path(resource_name: str) -> Path:
    return state_root() / "fingerprints" / f"{resource_name}.json"


def last_run_path() -> Path:
    return state_root() / "last_run.json"


def history_dir() -> Path:
    return state_root() / "history"


def history_snapshot_path(finished_at: datetime, pipeline_run_id: str) -> Path:
    """
    Unique filename per run so concurrent jobs or identical timestamps cannot collide.

    pipeline_run_id is sanitized for the filesystem (may be truncated).
    """
    ts = finished_at.strftime("%Y%m%dT%H%M%S")
    salt = uuid4().hex[:12]
    slug = (pipeline_run_id or "").strip() or "no_run_id"
    slug = re.sub(r"[^\w.\-]+", "_", slug)
    if len(slug) > 120:
        slug = slug[:120]
    return history_dir() / f"{ts}_{salt}_{slug}.json"


def ensure_state_layout() -> Path:
    root = state_root()
    (root / "fingerprints").mkdir(parents=True, exist_ok=True)
    (root / "history").mkdir(parents=True, exist_ok=True)
    return root


def load_fingerprint(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring bad fingerprint file %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in data.items():
        out[str(k)] = str(v)
    return out


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def classify_id_hash(
    row_id: Any, row_hash: str, prev: Mapping[str, str]
) -> Tuple[str, ChangeKind]:
    """Return stable key for fingerprint file and change kind."""
    if row_id is None:
        return ("", "no_id")
    key = str(row_id)
    old = prev.get(key)
    if old is None:
        return key, "new"
    if old != row_hash:
        return key, "updated"
    return key, "unchanged"


@dataclass
class ResourceRunAccumulator:
    """Filled while streaming rows; fingerprint saved only after successful load."""

    resource_name: str
    prev_fingerprint: Mapping[str, str]
    counts: MutableMapping[str, int] = field(
        default_factory=lambda: {"new": 0, "updated": 0, "unchanged": 0, "no_id": 0}
    )
    current_fingerprint: Dict[str, str] = field(default_factory=dict)

    def observe_row(self, row_id: Any, row_hash: str) -> None:
        key, kind = classify_id_hash(row_id, row_hash, self.prev_fingerprint)
        self.counts[kind] += 1
        if kind != "no_id":
            self.current_fingerprint[key] = row_hash


