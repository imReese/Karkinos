"""Read-only, evidence-bound eligibility for an exact publication incident."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from data.market_daily_store import verify_market_daily_receipt_on_connection
from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.persistence.database_normalization import stable_json_fingerprint
from server.persistence.valuation_publication_recovery import (
    publication_incident_ref,
    unresolved_publications,
)

RULE_VERSION = "karkinos.daily_close_recovery_preview.v1"


class _Blocked(ValueError):
    pass


def _require(condition: bool, blocker: str) -> None:
    if not condition:
        raise _Blocked(blocker)


def _read_bound_incident(conn: sqlite3.Connection, incident_ref: str, observed: dict):
    incidents = unresolved_publications(conn)
    matches = [
        item
        for item in incidents
        if item.get("incident_ref", publication_incident_ref(item)) == incident_ref
    ]
    _require(len(matches) == 1, "incident_not_found_or_ambiguous")
    incident = matches[0]
    observed["incident"] = incident
    _require(
        publication_incident_ref(incident) == incident_ref, "incident_identity_drift"
    )
    binding = incident.get("daily_close_conflict")
    _require(isinstance(binding, dict), "incident_fact_binding_missing")
    _require(
        binding.get("schema_version") == "karkinos.daily_close_conflict.v1"
        and binding.get("run_id") == incident.get("quote_fetch_run_id")
        and incident.get("error_type") == "DailyCloseEvidenceConflict"
        and incident.get("reason") == "quote_batch_publication_failed",
        "incident_fact_binding_invalid",
    )
    run = conn.execute(
        "SELECT * FROM main.quote_fetch_runs WHERE run_id = ?", (binding["run_id"],)
    ).fetchone()
    observed["run"] = dict(run) if run is not None else None
    _require(
        run is not None
        and run["status"] == "failed"
        and run["finished_at"] == incident.get("failed_at")
        and run["success_count"] == run["symbol_count"]
        and run["failure_count"] == 0,
        "failed_run_binding_mismatch",
    )
    rows = conn.execute(
        "SELECT * FROM main.quote_ingestion_items WHERE run_id = ? "
        "ORDER BY symbol, asset_type, id",
        (binding["run_id"],),
    ).fetchall()
    observed["staged_items"] = [dict(row) for row in rows]
    _require(len(rows) == run["symbol_count"], "staged_batch_incomplete")
    commands = []
    manifest = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        command = QuoteIngestionCommand.from_dict(payload)
        fingerprint = stable_json_fingerprint(command.to_dict())
        _require(
            stable_json_fingerprint(payload)
            == fingerprint
            == row["payload_fingerprint"]
            and command.fetch_run_id == binding["run_id"]
            and command.symbol == row["symbol"]
            and command.asset_type == row["asset_type"],
            "staged_item_identity_drift",
        )
        commands.append(command)
        manifest.append(
            {
                "symbol": command.symbol,
                "instrument_type": command.asset_type,
                "payload_fingerprint": fingerprint,
            }
        )
    _require(manifest == binding.get("staged_items"), "staged_batch_identity_drift")
    scope = sorted([[item["instrument_type"], item["symbol"]] for item in manifest])
    _require(
        bool(scope)
        and scope == binding.get("requested_scope") == incident.get("scope"),
        "requested_scope_unknown_or_mismatched",
    )
    facts = binding.get("required_facts")
    close_commands = [item for item in commands if item.daily_close_date is not None]
    _require(
        isinstance(facts, list) and bool(facts) and len(facts) == len(close_commands),
        "required_facts_incomplete",
    )
    _require(
        any(fact.get("conflicting") is True for fact in facts),
        "close_conflict_not_bound",
    )
    for fact, command in zip(facts, close_commands, strict=True):
        session = command.daily_close_date
        _require(
            date.fromisoformat(session).isoformat() == session, "fact_session_invalid"
        )
        _require(
            fact.get("fact_kind") == "daily_close"
            and fact.get("symbol") == command.symbol
            and fact.get("instrument_type") == command.asset_type
            and fact.get("session") == session
            and fact.get("candidate")
            == {
                "close_price": command.daily_close_price,
                "source": command.daily_close_source or "reported_previous_close",
                "payload_fingerprint": stable_json_fingerprint(command.to_dict()),
            },
            "required_fact_binding_mismatch",
        )
        existing = fact.get("existing")
        _require(
            existing is None
            or (
                isinstance(existing, dict)
                and existing.get("symbol") == command.symbol
                and existing.get("instrument_type") == command.asset_type
                and existing.get("trade_date") == session
                and bool(existing.get("source"))
                and bool(existing.get("captured_at"))
                and bool(existing.get("identity_provenance"))
            ),
            "conflicting_source_binding_invalid",
        )
    return facts


def preview_daily_close_recovery(
    database_path: str | Path,
    *,
    incident_ref: str,
    market_database_path: str | Path | None = None,
    resolution_evidence_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Inspect committed evidence without changing facts, incidents or authority.

    Current close storage has no replayable link to its original normalization
    observation. Even a verified candidate therefore cannot yet justify removal
    of the prior evidence. This is an explicit blocker, not an inferred repair.
    """
    requested = resolution_evidence_refs or []
    result: dict[str, Any] = {
        "rule_version": RULE_VERSION,
        "incident_ref": incident_ref,
        "status": "blocked",
        "required_facts": [],
        "resolution_evidence_refs": [],
        "candidate_evidence_verified": False,
        "blockers": [],
        "authorizes_execution": False,
    }
    observed: dict[str, Any] = {"requested_evidence_refs": requested}
    conn = None
    try:
        app_path = Path(database_path).resolve(strict=True)
        conn = sqlite3.connect(f"{app_path.as_uri()}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        if market_database_path is not None:
            meta_path = Path(market_database_path).resolve(strict=True)
            _require(app_path != meta_path, "market_database_identity_invalid")
            conn.execute(
                "ATTACH DATABASE ? AS market_meta", (f"{meta_path.as_uri()}?mode=ro",)
            )
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        # Explicit immutable refs are read first. No 'latest' lookup and no claim
        # that the two databases share an atomic publication generation.
        receipts = _read_receipts(conn, requested, observed) if requested else []
        facts = _read_bound_incident(conn, incident_ref, observed)
        result["required_facts"] = facts
        _require(bool(receipts), "resolution_evidence_missing")
        _verify_candidate_facts(conn, facts, receipts, observed)
        result["resolution_evidence_refs"] = requested
        result["candidate_evidence_verified"] = True
        raise _Blocked("prior_evidence_disposition_unproven")
    except _Blocked as exc:
        result["blockers"].append(str(exc))
    except FileNotFoundError:
        result["blockers"].append("evidence_database_missing")
    except (
        sqlite3.Error,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
    ):
        result["blockers"].append("evidence_invalid_or_unreadable")
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()
    result["proof_fingerprint"] = "sha256:" + stable_json_fingerprint(
        {"result": result, "observed": observed}
    )
    return result


def _read_receipts(conn, refs, observed):
    receipts = []
    observed["receipts"] = []
    keys = set()
    for ref in refs:
        _require(
            isinstance(ref, dict)
            and set(ref) == {"trade_date", "provider_name", "receipt_fingerprint"}
            and all(isinstance(value, str) and value.strip() for value in ref.values()),
            "resolution_evidence_ref_invalid",
        )
        key = (ref["trade_date"], ref["provider_name"])
        _require(key not in keys, "resolution_evidence_ref_duplicate")
        keys.add(key)
        row = conn.execute(
            "SELECT * FROM market_meta.market_daily_ingestion_receipts "
            "WHERE trade_date = ? AND provider_name = ?",
            key,
        ).fetchone()
        observed["receipts"].append(dict(row) if row is not None else None)
        _require(row is not None, "resolution_evidence_not_found")
        receipt = json.loads(row["receipt_json"])
        _require(
            receipt.get("schema_version")
            == "karkinos.market_daily_ingestion_receipt.v2"
            and receipt.get("trade_date") == ref["trade_date"]
            and receipt.get("provider_name") == ref["provider_name"]
            and receipt.get("row_count") == row["row_count"]
            and receipt.get("dataset_fingerprint") == row["dataset_fingerprint"],
            "resolution_evidence_identity_mismatch",
        )
        _require(
            receipt.get("receipt_fingerprint") == ref["receipt_fingerprint"],
            "resolution_evidence_revision_drift",
        )
        _require(
            verify_market_daily_receipt_on_connection(
                conn, receipt, schema="market_meta"
            ),
            "resolution_evidence_integrity_failed",
        )
        receipts.append(receipt)
    return receipts


def _verify_candidate_facts(conn, facts, receipts, observed):
    observed["current_closes"] = []
    commands = {
        (row["asset_type"], row["symbol"]): json.loads(row["payload_json"])
        for row in observed["staged_items"]
    }
    used = set()
    for fact in facts:
        _require(fact["instrument_type"] == "stock", "fact_instrument_type_unsupported")
        command = commands[(fact["instrument_type"], fact["symbol"])]
        matching = [
            receipt
            for receipt in receipts
            if receipt["trade_date"] == fact["session"]
            and receipt["provider_name"] == command["provider_name"]
            and fact["symbol"] in receipt["symbols"]
        ]
        _require(len(matching) == 1, "required_fact_evidence_missing_or_ambiguous")
        receipt = matching[0]
        used.add(receipt["receipt_fingerprint"])
        _require(
            fact["candidate"]["source"] == "market_bar_close",
            "candidate_close_source_unproven",
        )
        metadata = command.get("metadata", {})
        _require(
            metadata.get("receipt_fingerprint") == receipt["receipt_fingerprint"]
            and metadata.get("market_dataset_fingerprint")
            == receipt["dataset_fingerprint"],
            "candidate_publication_binding_missing_or_drifted",
        )
        bars = conn.execute(
            "SELECT * FROM market_meta.market_bars_v2 "
            "WHERE instrument_type = 'stock' AND symbol = ? AND frequency = '1d' "
            "AND substr(timestamp, 1, 10) = ?",
            (fact["symbol"], fact["session"]),
        ).fetchall()
        _require(len(bars) == 1, "published_daily_close_ambiguous")
        bar = dict(bars[0])
        _require(
            bar["close"] == fact["candidate"]["close_price"],
            "candidate_close_revision_requires_adjudication",
        )
        current = conn.execute(
            "SELECT * FROM main.daily_close_snapshots_v2 "
            "WHERE instrument_type = ? AND symbol = ? AND trade_date = ?",
            (fact["instrument_type"], fact["symbol"], fact["session"]),
        ).fetchone()
        observed["current_closes"].append(
            {"current": dict(current) if current else None, "bar": bar}
        )
        _require(
            current is not None
            and current["close_price"] == bar["close"]
            and current["source"] == "market_bar_close",
            "canonical_close_not_reconciled",
        )
    _require(
        used == {receipt["receipt_fingerprint"] for receipt in receipts},
        "resolution_evidence_outside_required_facts",
    )
