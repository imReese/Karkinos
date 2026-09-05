"""Persist unresolved publication failures independently of last-good reads."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from core.types import InstrumentKey, InstrumentType
from server.persistence.database_normalization import stable_json_fingerprint

RECOVERY_KEY = "valuation_publication_recovery"
ATTEMPT_KEY = "valuation_snapshot_publication_attempt"


def _instrument_scope(scope) -> set[tuple[str, str]]:
    keys = [
        InstrumentKey.from_values(symbol, asset_type) for asset_type, symbol in scope
    ]
    return {(key.instrument_type.value, key.symbol) for key in keys}


def _control(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value_json FROM main.runtime_controls WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    value = json.loads(row[0])
    if not isinstance(value, dict):
        raise ValueError("valuation publication recovery metadata invalid")
    return value


class QuoteRunScopeUnavailable(ValueError):
    """Legacy audit metadata cannot establish an exact requested scope."""


class InvalidQuoteRunScope(ValueError):
    """An explicit request identity is malformed or internally inconsistent."""


def quote_run_scope(
    conn: sqlite3.Connection, run_id: str | None, *, require_exact: bool = False
) -> list[list[str]] | None:
    """Unknown historical scope blocks reads; every new publication requires proof."""
    run = conn.execute(
        "SELECT asset_type, symbol_count, metadata_json FROM main.quote_fetch_runs "
        "WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    try:
        return _requested_scope(run)
    except (QuoteRunScopeUnavailable, InvalidQuoteRunScope):
        if require_exact:
            raise
        return None


def _requested_scope(run) -> list[list[str]]:
    if run is None:
        raise QuoteRunScopeUnavailable("quote publication requested scope unavailable")
    try:
        metadata = json.loads(run[2] or "{}")
    except (ValueError, TypeError) as exc:
        raise InvalidQuoteRunScope(
            "quote publication request metadata invalid"
        ) from exc
    if not isinstance(metadata, dict):
        raise InvalidQuoteRunScope("quote publication request metadata invalid")
    if not {"requested_symbols", "symbols"}.intersection(metadata):
        raise QuoteRunScopeUnavailable("quote publication requested scope unavailable")
    symbols = metadata.get("requested_symbols", metadata.get("symbols"))
    if (
        not isinstance(symbols, list)
        or len(symbols) != run[1]
        or not symbols
        or any(not isinstance(s, str) or not s.strip() for s in symbols)
    ):
        raise InvalidQuoteRunScope("quote publication requested symbols invalid")
    asset_types = metadata.get(
        "instrument_types", metadata.get("asset_types", [run[0]] * len(symbols))
    )
    if (
        not isinstance(asset_types, list)
        or len(asset_types) != len(symbols)
        or any(not isinstance(kind, str) or not kind.strip() for kind in asset_types)
    ):
        raise InvalidQuoteRunScope(
            "quote publication requested instrument types invalid"
        )
    if "instrument_types" in metadata:
        if any(
            kind not in {item.value for item in InstrumentType} for kind in asset_types
        ):
            raise InvalidQuoteRunScope(
                "quote publication requires canonical instrument types"
            )
    elif any(kind.strip().lower() == "fund" for kind in asset_types):
        # Broad fund identity cannot establish an ETF or open-end-fund request.
        raise QuoteRunScopeUnavailable(
            "quote publication requested fund identity unavailable"
        )
    try:
        scope = _instrument_scope(zip(asset_types, symbols, strict=True))
    except (TypeError, ValueError) as exc:
        raise InvalidQuoteRunScope(
            "quote publication requested identity invalid"
        ) from exc
    if len(scope) != len(symbols):
        raise InvalidQuoteRunScope("quote publication requested identities duplicated")
    return [list(key) for key in sorted(scope)]


def unresolved_publications(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    control = _control(conn, RECOVERY_KEY)
    if control is not None:
        failures = control.get("failures")
        if not isinstance(failures, list) or any(
            not isinstance(item, dict) for item in failures
        ):
            raise ValueError("valuation publication recovery metadata invalid")
        for item in failures:
            scope = item.get("scope")
            if scope is not None and (
                not isinstance(scope, list)
                or any(
                    not isinstance(key, list)
                    or len(key) != 2
                    or any(not isinstance(part, str) or not part for part in key)
                    for key in scope
                )
            ):
                raise ValueError("valuation publication recovery scope invalid")
        return failures
    # Older releases persisted only the latest attempt. Keep that failure when
    # startup or an unrelated ledger write publishes another valuation.
    attempt = _control(conn, ATTEMPT_KEY)
    if attempt is None:
        # Schema-10 releases wrote failure into the current pointer itself.
        # Preserve it before a startup publication replaces that legacy control.
        attempt = _control(conn, "valuation_snapshot_publication")
    if attempt and attempt.get("status") == "failed":
        return [
            {
                **attempt,
                "scope": quote_run_scope(conn, attempt.get("quote_fetch_run_id")),
            }
        ]
    return []


def affected_publications(
    conn: sqlite3.Connection, instruments: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Unknown failure scope blocks; known scope affects only its consumers."""
    return [
        failure
        for failure in unresolved_publications(conn)
        if not failure.get("scope")
        or _instrument_scope(instruments).intersection(
            _instrument_scope(failure["scope"])
        )
    ]


def record_publication_recovery(
    conn: sqlite3.Connection, failure: dict[str, Any], *, updated_at: str
) -> None:
    failures = unresolved_publications(conn)
    run_id = failure.get("quote_fetch_run_id")
    failures = [item for item in failures if item.get("quote_fetch_run_id") != run_id]
    incident = {
        **failure,
        "scope": quote_run_scope(conn, run_id),
        "failed_at": updated_at,
    }
    failures.append({**incident, "incident_ref": publication_incident_ref(incident)})
    _save(conn, failures, updated_at)


def assert_quote_publication_not_started(conn: sqlite3.Connection, run_id: str) -> None:
    if any(
        item.get("quote_fetch_run_id") == run_id
        for item in unresolved_publications(conn)
    ):
        raise RuntimeError("quote publication already unresolved")


def begin_quote_publication(
    conn: sqlite3.Connection, *, run_id: str, updated_at: str
) -> str:
    """Persist a scope fence before any candidate fact can be materialized."""
    assert_quote_publication_not_started(conn, run_id)
    pending = {
        "status": "pending",
        "reason": "quote_batch_publication_incomplete",
        "quote_fetch_run_id": run_id,
        "scope": quote_run_scope(conn, run_id),
        "started_at": updated_at,
    }
    ref = publication_incident_ref(pending)
    _save(
        conn,
        [*unresolved_publications(conn), {**pending, "incident_ref": ref}],
        updated_at,
    )
    return ref


def complete_quote_publication(
    conn: sqlite3.Connection, *, attempt_ref: str, updated_at: str
) -> None:
    """Only the transaction that began this attempt may commit its success."""
    failures = unresolved_publications(conn)
    pending = [item for item in failures if item.get("incident_ref") == attempt_ref]
    if len(pending) != 1 or pending[0].get("status") != "pending":
        raise RuntimeError("quote publication attempt identity drift")
    _save(
        conn,
        [item for item in failures if item.get("incident_ref") != attempt_ref],
        updated_at,
    )


def publication_incident_ref(incident: dict[str, Any]) -> str:
    return "sha256:" + stable_json_fingerprint(
        {key: value for key, value in incident.items() if key != "incident_ref"}
    )


def preserve_publication_recovery(conn: sqlite3.Connection, *, updated_at: str) -> None:
    """Retain incidents until a fact-bound repair receipt can prove resolution.

    A complete valuation or a later successful request is not such a receipt:
    neither proves that a prior session's conflicting close has been repaired.
    """
    failures = unresolved_publications(conn)
    if not failures:
        return
    _save(conn, failures, updated_at)


def _save(conn: sqlite3.Connection, failures: list[dict[str, Any]], at: str) -> None:
    conn.execute(
        "INSERT INTO runtime_controls(key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
        "updated_at=excluded.updated_at",
        (RECOVERY_KEY, json.dumps({"failures": failures}, sort_keys=True), at),
    )
