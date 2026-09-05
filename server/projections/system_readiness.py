"""Provider-free operational readiness from one read-only SQLite snapshot."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.persistence.valuation_publication_recovery import (
    affected_publications,
    unresolved_publications,
)
from server.projections.quote_status import parse_quote_timestamp, quote_is_stale
from server.projections.valuation_snapshot import valuation_snapshot_from_row


def _state(
    status: str,
    *,
    as_of=None,
    last_success=None,
    latest_attempt=None,
    blockers=(),
    safe_next_action=None,
) -> dict[str, Any]:
    return dict(
        status=status,
        as_of=as_of,
        last_success=last_success,
        latest_attempt=latest_attempt,
        blockers=list(blockers),
        safe_next_action=safe_next_action,
    )


def build_system_readiness(
    database_path: str | Path | None,
    *,
    now: datetime | None = None,
    api_observed: bool = False,
    data_worker_enabled: bool | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("readiness_clock_requires_timezone")
    states = {
        key: _state("unavailable", blockers=("evidence_unavailable",))
        for key in (
            "database",
            "background_worker",
            "research_worker",
            "market_data",
            "valuation_read",
        )
    }
    states["api"] = _state(
        "ready" if api_observed else "not_evaluated", as_of=current.isoformat()
    )
    valuation = None
    failure_codes = ["valuation_unavailable"]
    try:
        if database_path is None:
            raise ValueError("database_unavailable")
        uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            controls = {
                row["key"]: {
                    **json.loads(row["value_json"]),
                    "updated_at": row["updated_at"],
                }
                for row in conn.execute(
                    "SELECT key, value_json, updated_at FROM runtime_controls WHERE key IN "
                    "('valuation_snapshot_publication', 'valuation_snapshot_publication_attempt', "
                    "'data_worker_heartbeat', 'research_worker_heartbeat')"
                )
            }
            states["database"] = _state("ready", as_of=current.isoformat())
            failures = unresolved_publications(conn)
            failure_codes = (
                ["valuation_publication_recovery_required"] if failures else []
            )
            publication = controls.get("valuation_snapshot_publication", {})
            attempt = controls.get("valuation_snapshot_publication_attempt")
            row = conn.execute(
                "SELECT * FROM valuation_snapshots WHERE snapshot_id = ?",
                (publication.get("snapshot_id"),),
            ).fetchone()
            if row is not None and publication.get("status") == "ready":
                valuation = valuation_snapshot_from_row(dict(row))
                scoped_failures = affected_publications(
                    conn, {(q["asset_type"], q["symbol"]) for q in valuation["quotes"]}
                )
                failure_codes = (
                    ["valuation_publication_recovery_required"]
                    if scoped_failures
                    else []
                )
                stale = any(
                    quote_is_stale(
                        {
                            **q,
                            "timestamp": q.get("quote_timestamp") or q.get("timestamp"),
                        },
                        now=current,
                    )
                    for q in valuation["quotes"]
                )
                if stale:
                    failure_codes.append("valuation_stale")
                if valuation["status"] != "complete":
                    failure_codes.append("valuation_incomplete")
                states["valuation_read"] = _state(
                    "degraded" if failure_codes else "ready",
                    as_of=valuation["as_of"],
                    last_success=publication,
                    latest_attempt=attempt,
                    blockers=failure_codes,
                    safe_next_action=(
                        "refresh_required_market_evidence" if failure_codes else None
                    ),
                )
            else:
                failure_codes.append("valuation_unavailable")
            states["market_data"] = _state(
                "degraded" if failures or failure_codes else "ready",
                latest_attempt=attempt,
                blockers=sorted(
                    set(
                        failure_codes
                        + (
                            ["valuation_publication_recovery_required"]
                            if failures
                            else []
                        )
                    )
                ),
                safe_next_action="inspect_market_refresh",
            )
            for name, key in (
                ("background_worker", "data_worker_heartbeat"),
                ("research_worker", "research_worker_heartbeat"),
            ):
                if name == "background_worker" and data_worker_enabled is False:
                    states[name] = _state("disabled")
                    continue
                heartbeat = controls.get(key)
                stamp = parse_quote_timestamp((heartbeat or {}).get("as_of"))
                fresh = (
                    stamp is not None and 0 <= (current - stamp).total_seconds() < 90
                )
                ready = (
                    fresh
                    and heartbeat is not None
                    and heartbeat.get("status") == "ready"
                )
                states[name] = _state(
                    "ready" if ready else "unavailable",
                    as_of=heartbeat.get("as_of") if heartbeat else None,
                    latest_attempt=heartbeat,
                    blockers=(
                        () if ready else ("worker_heartbeat_missing_stale_or_stopped",)
                    ),
                    safe_next_action="inspect_worker",
                )
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        failure_codes = ["readiness_evidence_unavailable"]
        states["valuation_read"] = _state("unavailable", blockers=failure_codes)
        states["market_data"] = _state("unavailable", blockers=failure_codes)
    for name in ("decision", "risk"):
        states[name] = _state(
            "blocked",
            blockers=failure_codes or ["domain_gates_require_evaluation"],
            safe_next_action="evaluate_exact_candidate_and_account_gates",
        )
    states["execution_authority"] = _state(
        "not_evaluated", blockers=("exact_human_authority_evaluation_required",)
    )
    return {
        "schema_version": "karkinos.system_readiness.v1",
        "as_of": current.isoformat(),
        "scope": "account_valuation_and_worker_heartbeats",
        "research_dataset_readiness": "not_evaluated",
        "valuation_snapshot_id": valuation["snapshot_id"] if valuation else None,
        "subsystems": states,
        "authorizes_execution": False,
    }
