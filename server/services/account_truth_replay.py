"""Privacy-minimized replay evidence for one historical Account Truth binding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.manual_review import ManualReviewRepository
from server.account_truth_gate import broker_events_for_import_run
from server.services.valuation_snapshot import (
    ledger_identity_from_rows,
    valuation_snapshot_from_row,
)

ACCOUNT_TRUTH_REPLAY_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.account_truth.replay_evidence.v1"
)


def build_account_truth_replay_evidence(
    db: Any,
    *,
    account_truth_ref: str,
    source_fingerprint: str,
    valuation_snapshot_id: str,
    ledger_cutoff_id: int | None,
) -> dict[str, object]:
    """Resolve a privacy-minimized, historical Account Truth replay binding."""

    blockers: list[str] = []
    normalized_ref = str(account_truth_ref or "").removeprefix("account_truth:")
    normalized_source_fingerprint = str(source_fingerprint or "")
    normalized_valuation_snapshot_id = str(valuation_snapshot_id or "")
    normalized_ledger_cutoff_id = int(ledger_cutoff_id or 0)
    db_path = getattr(db, "_path", None)

    if not normalized_ref:
        blockers.append("account_truth_replay_import_ref_missing")
    if not _is_sha256(normalized_source_fingerprint):
        blockers.append("account_truth_replay_source_fingerprint_invalid")
    if not normalized_valuation_snapshot_id:
        blockers.append("account_truth_replay_valuation_snapshot_id_missing")
    if normalized_ledger_cutoff_id <= 0:
        blockers.append("account_truth_replay_ledger_cutoff_invalid")
    if db_path is None:
        blockers.append("account_truth_replay_database_unavailable")

    import_file_fingerprint = ""
    import_events_fingerprint = ""
    manual_reviews_fingerprint = ""
    import_event_count = 0
    import_validation_status = "missing"
    valuation_policy = ""
    valuation_status = "missing"
    valuation_quotes_fingerprint = ""
    valuation_metadata_fingerprint = ""
    ledger_fingerprint = ""

    if db_path is not None and normalized_ref:
        try:
            repository = BrokerEvidenceRepository(Path(db_path))
            import_run = repository.get_import_run(normalized_ref)
            if import_run is None:
                blockers.append("account_truth_replay_import_missing")
            else:
                import_file_fingerprint = str(import_run.file_fingerprint or "")
                import_validation_status = str(import_run.validation_status or "")
                events = broker_events_for_import_run(repository, import_run)
                import_event_count = len(events)
                import_events_fingerprint = _fingerprint_json(
                    [asdict(event) for event in events]
                )
                reviews = ManualReviewRepository(Path(db_path)).list_decisions(
                    normalized_ref
                )
                manual_reviews_fingerprint = _fingerprint_json(
                    [asdict(review) for review in reviews]
                )
                if not _is_sha256(import_file_fingerprint):
                    blockers.append("account_truth_replay_file_fingerprint_invalid")
                if import_validation_status == "blocked":
                    blockers.append("account_truth_replay_import_blocked")
                if import_run.valid_row_count <= 0:
                    blockers.append("account_truth_replay_import_has_no_valid_rows")
                if import_event_count != import_run.valid_row_count:
                    blockers.append("account_truth_replay_event_count_mismatch")
                if any(not _is_sha256(event.row_fingerprint) for event in events):
                    blockers.append("account_truth_replay_event_fingerprint_invalid")
        except Exception:
            blockers.append("account_truth_replay_import_unreadable")

    snapshot_reader = getattr(db, "get_valuation_snapshot_sync", None)
    if callable(snapshot_reader) and normalized_valuation_snapshot_id:
        try:
            raw_snapshot = snapshot_reader(normalized_valuation_snapshot_id)
            if raw_snapshot is None:
                blockers.append("account_truth_replay_valuation_snapshot_missing")
            else:
                snapshot = valuation_snapshot_from_row(raw_snapshot)
                valuation_policy = str(snapshot.get("valuation_policy") or "")
                valuation_status = str(snapshot.get("status") or "")
                snapshot_cutoff = int(snapshot.get("ledger_cutoff_id") or 0)
                ledger_fingerprint = str(snapshot.get("ledger_fingerprint") or "")
                quote_set_fingerprint = str(snapshot.get("quote_set_fingerprint") or "")
                valuation_quotes_fingerprint = _valuation_content_fingerprint(
                    snapshot.get("quotes") or []
                )
                valuation_metadata_fingerprint = _fingerprint_json(
                    snapshot.get("metadata") or {}
                )
                expected_snapshot_id = "valuation-" + _fingerprint_json(
                    {
                        "valuation_policy": valuation_policy,
                        "quote_set_fingerprint": quote_set_fingerprint,
                        "ledger_fingerprint": ledger_fingerprint,
                        "ledger_cutoff_id": snapshot_cutoff,
                    }
                )
                if normalized_valuation_snapshot_id != expected_snapshot_id:
                    blockers.append("account_truth_replay_valuation_identity_mismatch")
                if snapshot_cutoff != normalized_ledger_cutoff_id:
                    blockers.append("account_truth_replay_ledger_cutoff_mismatch")
                if valuation_quotes_fingerprint != quote_set_fingerprint:
                    blockers.append("account_truth_replay_quote_set_drifted")
                if valuation_status != "complete":
                    blockers.append("account_truth_replay_valuation_not_complete")

                historical_ledger = ledger_identity_from_rows(
                    _ledger_rows_through_cutoff(
                        db,
                        ledger_cutoff_id=normalized_ledger_cutoff_id,
                    )
                )
                if historical_ledger["ledger_cutoff_id"] != (
                    normalized_ledger_cutoff_id
                ):
                    blockers.append("account_truth_replay_ledger_cutoff_missing")
                if historical_ledger["ledger_fingerprint"] != ledger_fingerprint:
                    blockers.append("account_truth_replay_ledger_drifted")
        except Exception:
            blockers.append("account_truth_replay_valuation_unreadable")
    else:
        blockers.append("account_truth_replay_valuation_reader_unavailable")

    payload: dict[str, object] = {
        "schema_version": ACCOUNT_TRUTH_REPLAY_EVIDENCE_SCHEMA_VERSION,
        "status": "blocked" if blockers else "pass",
        "account_truth_ref": (
            f"account_truth:{normalized_ref}" if normalized_ref else None
        ),
        "source_fingerprint": normalized_source_fingerprint or None,
        "import_file_fingerprint": import_file_fingerprint or None,
        "import_events_fingerprint": import_events_fingerprint or None,
        "manual_reviews_fingerprint": manual_reviews_fingerprint or None,
        "import_event_count": import_event_count,
        "import_validation_status": import_validation_status,
        "valuation_snapshot_id": normalized_valuation_snapshot_id or None,
        "valuation_policy": valuation_policy or None,
        "valuation_status": valuation_status,
        "valuation_quotes_fingerprint": valuation_quotes_fingerprint or None,
        "valuation_metadata_fingerprint": valuation_metadata_fingerprint or None,
        "ledger_cutoff_id": normalized_ledger_cutoff_id or None,
        "ledger_fingerprint": ledger_fingerprint or None,
        "blockers": list(dict.fromkeys(blockers)),
        "contains_broker_export_rows": False,
        "contains_private_account_identifiers": False,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    payload["evidence_fingerprint"] = account_truth_replay_evidence_fingerprint(payload)
    return payload


def account_truth_replay_evidence_fingerprint(value: object) -> str:
    """Fingerprint one sanitized replay contract without its stored digest."""

    payload = dict(value) if isinstance(value, dict) else {}
    payload.pop("evidence_fingerprint", None)
    return _fingerprint_json(payload)


def verify_account_truth_replay_evidence(value: object) -> bool:
    """Verify the replay contract schema and its content fingerprint."""

    if not isinstance(value, dict):
        return False
    fingerprint = str(value.get("evidence_fingerprint") or "")
    return (
        value.get("schema_version") == ACCOUNT_TRUTH_REPLAY_EVIDENCE_SCHEMA_VERSION
        and _is_sha256(fingerprint)
        and fingerprint == account_truth_replay_evidence_fingerprint(value)
    )


def _fingerprint_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _valuation_content_fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ledger_rows_through_cutoff(
    db: Any,
    *,
    ledger_cutoff_id: int,
) -> list[dict[str, object]]:
    reader = getattr(db, "get_ledger_entries_sync", None)
    if not callable(reader):
        raise RuntimeError("account_truth_replay_ledger_reader_unavailable")
    rows: list[dict[str, object]] = []
    offset = 0
    while True:
        batch = list(reader(limit=500, offset=offset) or [])
        rows.extend(
            dict(row)
            for row in batch
            if int(dict(row).get("id") or 0) <= ledger_cutoff_id
        )
        if len(batch) < 500:
            break
        offset += 500
    return rows


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )
