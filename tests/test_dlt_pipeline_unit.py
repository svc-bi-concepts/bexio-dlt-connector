"""Unit tests for dlt_pipeline helpers (no Bexio API calls)."""

from __future__ import annotations

import logging

import requests

from dlt_pipeline import (
    _endpoint_http_outcome,
    _root_http_error,
    flatten,
    psa_business_row_hash,
)


def test_psa_business_row_hash_ignores_lineage_fields() -> None:
    """SCD2 row version must not change when only PSA metadata differs."""
    business = {"id": 1, "name": "Acme", "amount": "10.5"}
    h1 = psa_business_row_hash(
        {**business, "_loaded_at": "2025-01-01T00:00:00+00:00", "_extract_run_id": "run-a"}
    )
    h2 = psa_business_row_hash(
        {**business, "_loaded_at": "2025-06-01T12:00:00+00:00", "_extract_run_id": "run-b"}
    )
    assert h1 == h2


def test_psa_business_row_hash_changes_when_business_changes() -> None:
    a = {"id": 1, "name": "A"}
    b = {"id": 1, "name": "B"}
    assert psa_business_row_hash(a) != psa_business_row_hash(b)


def test_flatten_envelope_data_list() -> None:
    payload = {"data": [{"id": 42, "nested": {"x": 1}}]}
    rows = flatten(payload)
    assert len(rows) == 1
    assert rows[0]["id"] == 42
    assert rows[0]["nested_x"] == 1


def test_flatten_top_level_list() -> None:
    rows = flatten([{"id": 1, "k": "v"}])
    assert rows == [{"id": 1, "k": "v"}]


def _http_error(status: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    err = requests.HTTPError(response=resp)
    return err


def test_endpoint_http_outcome_403() -> None:
    label, level = _endpoint_http_outcome(_http_error(403))
    assert label == "skipped_forbidden"
    assert level == logging.WARNING


def test_endpoint_http_outcome_404() -> None:
    label, level = _endpoint_http_outcome(_http_error(404))
    assert label == "skipped_not_found"
    assert level == logging.WARNING


def test_endpoint_http_outcome_wrapped_http_error() -> None:
    root = _http_error(403)
    wrapped = RuntimeError("dlt failed")
    wrapped.__cause__ = root
    label, level = _endpoint_http_outcome(wrapped)
    assert label == "skipped_forbidden"
    assert level == logging.WARNING


def test_root_http_error_finds_nested() -> None:
    root = _http_error(404)
    mid = ValueError("mid")
    mid.__cause__ = root
    assert _root_http_error(mid) is root


def test_root_http_error_none_when_no_http() -> None:
    assert _root_http_error(ValueError("plain")) is None
