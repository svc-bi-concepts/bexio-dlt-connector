"""Tests for loader_state (no dlt / no API)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from loader_state import (
    ResourceRunAccumulator,
    atomic_write_json,
    classify_id_hash,
    history_dir,
    history_snapshot_path,
    last_run_path,
    load_fingerprint,
    state_root,
)


def test_classify_id_hash() -> None:
    prev = {"10": "hash_a"}
    assert classify_id_hash(10, "hash_a", prev) == ("10", "unchanged")
    assert classify_id_hash(10, "hash_b", prev) == ("10", "updated")
    assert classify_id_hash(99, "x", prev) == ("99", "new")
    assert classify_id_hash(None, "x", prev) == ("", "no_id")


def test_accumulator_tracks_changes() -> None:
    prev = {"1": "a", "2": "b"}
    acc = ResourceRunAccumulator(resource_name="contacts", prev_fingerprint=prev)
    acc.observe_row(1, "a")
    acc.observe_row(2, "c")
    acc.observe_row(3, "d")
    acc.observe_row(None, "z")
    assert acc.counts == {"new": 1, "updated": 1, "unchanged": 1, "no_id": 1}
    assert acc.current_fingerprint == {"1": "a", "2": "c", "3": "d"}


def test_load_fingerprint_roundtrip(tmp_path) -> None:
    p = tmp_path / "fp.json"
    atomic_write_json(p, {"42": "hex", "43": "other"})
    assert load_fingerprint(p) == {"42": "hex", "43": "other"}


def test_atomic_write_json_valid_utf8(tmp_path) -> None:
    p = tmp_path / "nested" / "doc.json"
    atomic_write_json(p, {"umlaut": "ü", "n": 1})
    assert json.loads(p.read_text(encoding="utf-8"))["umlaut"] == "ü"


def test_state_root_respects_loader_state_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEXIO_LOADER_STATE_DIR", str(tmp_path / "custom"))
    monkeypatch.delenv("BEXIO_DATA_DIR", raising=False)
    assert state_root() == tmp_path / "custom"
    assert last_run_path() == tmp_path / "custom" / "last_run.json"


def test_history_snapshot_path_format(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEXIO_LOADER_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("BEXIO_DATA_DIR", raising=False)
    dt = datetime(2026, 5, 15, 14, 30, 5, tzinfo=timezone.utc)
    p = history_snapshot_path(dt, "job/abc:test")
    assert p.parent == history_dir()
    assert p.name.startswith("20260515T143005_")
    assert p.name.endswith("_job_abc_test.json")


def test_history_snapshot_paths_differ(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BEXIO_LOADER_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("BEXIO_DATA_DIR", raising=False)
    dt = datetime(2026, 5, 15, 14, 30, 5, tzinfo=timezone.utc)
    assert history_snapshot_path(dt, "same") != history_snapshot_path(dt, "same")
