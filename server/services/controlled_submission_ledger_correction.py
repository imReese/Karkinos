"""Signed append-only correction for one controlled ledger posting."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from server.ledger.models import LedgerEntry
from server.projections.models import ProjectedPosition
from server.projections.service import build_portfolio_projection
from server.services.operator_approval import resolve_operator_approval_with_proof
from server.services.valuation_snapshot import build_current_valuation_snapshot

CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SCHEMA_VERSION = (
    "karkinos.controlled_submission_ledger_correction.v1"
)
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_submission_ledger_correction_status.v1"
)
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_PLAN_SCHEMA_VERSION = (
    "karkinos.controlled_submission_ledger_correction_plan.v1"
)
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT = (
    "apply_exact_compensating_ledger_correction_once"
)
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ENTRY_TYPE = "controlled_projection_correction"
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE = (
    "controlled_submission_ledger_correction"
)
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_REJECTION_EVENT_TYPE = (
    "controlled_broker.ledger_correction_rejected"
)
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_MAX_ACCOUNT_TRUTH_AGE_SECONDS = 120
CONTROLLED_SUBMISSION_LEDGER_CORRECTION_REASON_CODES = frozenset(
    {
        "broker_evidence_superseded",
        "duplicate_controlled_posting",
        "operator_confirmed_mapping_error",
    }
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_OPERATOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ControlledSubmissionLedgerCorrectionRejected(ValueError):
    """Raised after a correction attempt is rejected and audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSubmissionLedgerCorrectionPlanError(ValueError):
    """Raised when the original posting cannot be safely compensated."""

    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


class ControlledSubmissionLedgerCorrectionService:
    """Preview and apply one exact, signed, append-only correction."""

    def __init__(
        self,
        *,
        db: Any,
        account_truth_provider: Callable[[], dict[str, Any]] | None = None,
        trusted_operator_identities: Iterable[Any] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._account_truth_provider = account_truth_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        configured = callable(self._account_truth_provider) and bool(
            self._trusted_operator_identities
        )
        return {
            "schema_version": (
                CONTROLLED_SUBMISSION_LEDGER_CORRECTION_STATUS_SCHEMA_VERSION
            ),
            "contract_status": (
                "signed_append_only_correction_available"
                if configured
                else "disabled_waiting_for_account_truth_and_operator_signature"
            ),
            "preview_enabled": True,
            "apply_enabled": configured,
            "reason_codes": sorted(
                CONTROLLED_SUBMISSION_LEDGER_CORRECTION_REASON_CODES
            ),
            "acknowledgement": (
                CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT
            ),
            "correction_mode": "derived_append_only_compensating_event",
            "original_ledger_deletion_enabled": False,
            "arbitrary_financial_input_enabled": False,
            "automatic_correction_enabled": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "capital_authority_changed": False,
            "safety": _safety_flags(),
        }

    def preview(
        self,
        *,
        posting_id: str,
        reason_code: str,
        operator_id: str,
    ) -> dict[str, Any]:
        normalized_posting_id = str(posting_id or "").strip().lower()
        normalized_reason = str(reason_code or "").strip().lower()
        normalized_operator = str(operator_id or "").strip()
        existing = (
            self._db.get_controlled_submission_ledger_correction_for_posting_sync(
                normalized_posting_id
            )
            if _FINGERPRINT_PATTERN.fullmatch(normalized_posting_id)
            else None
        )
        if existing is not None:
            return {
                **_correction_response(existing, reused=True),
                "review_status": "already_applied",
                "review_ready": False,
                "blockers": [],
            }

        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_posting_id):
            blockers.append("controlled_ledger_correction_posting_id_invalid")
        if (
            normalized_reason
            not in CONTROLLED_SUBMISSION_LEDGER_CORRECTION_REASON_CODES
        ):
            blockers.append("controlled_ledger_correction_reason_invalid")
        if not _OPERATOR_ID_PATTERN.fullmatch(normalized_operator):
            blockers.append("controlled_ledger_correction_operator_id_invalid")

        posting = (
            self._db.get_controlled_submission_ledger_posting_sync(
                normalized_posting_id
            )
            if not blockers or _FINGERPRINT_PATTERN.fullmatch(normalized_posting_id)
            else None
        )
        if posting is None:
            blockers.append("controlled_ledger_correction_posting_not_found")
            posting = {}
        if str(posting.get("status") or "") != "applied":
            blockers.append("controlled_ledger_correction_posting_not_applied")

        original_entry_ids = _parse_integer_list(posting.get("ledger_entry_ids_json"))
        if int(posting.get("ledger_entry_count") or 0) <= 0 or not original_entry_ids:
            blockers.append("controlled_ledger_correction_zero_fill_posting")

        ledger_rows = _load_all_ledger_rows(self._db)
        original_rows = [
            row for row in ledger_rows if int(row.get("id") or 0) in original_entry_ids
        ]
        original_entry_fingerprint = _fingerprint(original_rows)
        if len(original_rows) != len(original_entry_ids):
            blockers.append("controlled_ledger_correction_original_entry_missing")
        if any(
            str(row.get("source") or "") != "controlled_submission_ledger_posting"
            for row in original_rows
        ):
            blockers.append("controlled_ledger_correction_original_lineage_invalid")

        plan: dict[str, Any] = {}
        if not blockers:
            try:
                plan = build_controlled_ledger_correction_plan(
                    ledger_rows=ledger_rows,
                    original_entry_ids=original_entry_ids,
                    posting_id=normalized_posting_id,
                )
            except ControlledSubmissionLedgerCorrectionPlanError as exc:
                blockers.append(exc.blocker)

        account_truth = self._resolve_account_truth(posting=posting)
        blockers.extend(account_truth["blockers"])
        account_truth_review = self._db.get_account_truth_review_identity_sync(
            str(posting.get("account_truth_import_run_id") or "")
        )
        expected_review_fingerprint = str(
            posting.get("account_truth_review_fingerprint") or ""
        )
        if account_truth_review["fingerprint"] != expected_review_fingerprint:
            blockers.append("controlled_ledger_correction_account_truth_review_changed")

        pre_valuation = build_current_valuation_snapshot(self._db, persist=False)
        plan_fingerprint = _fingerprint(plan) if plan else ""
        correction_core = {
            "schema_version": (CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SCHEMA_VERSION),
            "action": "reverse_controlled_submission_ledger_posting",
            "posting_id": normalized_posting_id,
            "posting_fingerprint": str(posting.get("posting_fingerprint") or ""),
            "original_ledger_entry_ids": original_entry_ids,
            "original_ledger_entry_fingerprint": original_entry_fingerprint,
            "reason_code": normalized_reason,
            "operator_id": normalized_operator,
            "account_truth_import_run_id": str(
                posting.get("account_truth_import_run_id") or ""
            ),
            "account_truth_file_fingerprint": str(
                posting.get("account_truth_file_fingerprint") or ""
            ),
            "account_truth_source_fingerprint": str(
                posting.get("account_truth_source_fingerprint") or ""
            ),
            "account_truth_review_fingerprint": expected_review_fingerprint,
            "pre_valuation_snapshot_id": str(pre_valuation.get("snapshot_id") or ""),
            "pre_valuation_as_of": str(pre_valuation.get("as_of") or ""),
            "pre_valuation_status": str(pre_valuation.get("status") or ""),
            "pre_ledger_cutoff_id": int(pre_valuation.get("ledger_cutoff_id") or 0),
            "pre_ledger_fingerprint": str(
                pre_valuation.get("ledger_fingerprint") or ""
            ),
            "plan_fingerprint": plan_fingerprint,
            "correction_plan": plan,
        }
        correction_fingerprint = _fingerprint(correction_core)
        correction_id = _fingerprint(
            {
                "domain": "karkinos.controlled_submission.ledger_correction_id.v1",
                "correction_fingerprint": correction_fingerprint,
            }
        )
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **correction_core,
            "correction_id": correction_id,
            "correction_fingerprint": correction_fingerprint,
            "generated_at": _aware_utc(self._clock()).isoformat(),
            "review_status": (
                "ready_for_final_signature" if not unique_blockers else "blocked"
            ),
            "review_ready": not unique_blockers,
            "blockers": unique_blockers,
            "account_truth": account_truth,
            "account_truth_review": account_truth_review,
            "required_operator_approval": {
                "action": "reverse_controlled_submission_ledger_posting",
                "artifact_type": "controlled_submission_ledger_correction",
                "artifact_fingerprint": correction_fingerprint,
            },
            "production_ledger_mutated": False,
            "safety": _safety_flags(),
        }

    def apply(
        self,
        *,
        posting_id: str,
        reason_code: str,
        operator_id: str,
        correction_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        existing = (
            self._db.get_controlled_submission_ledger_correction_for_posting_sync(
                posting_id
            )
        )
        if existing is not None:
            if (
                str(existing.get("correction_fingerprint") or "")
                == correction_fingerprint
            ):
                return self._post_apply_response(existing, reused=True)
            raise ControlledSubmissionLedgerCorrectionRejected(
                "ledger correction retry conflicts with persisted correction",
                evidence={
                    "status": "rejected",
                    "posting_id": posting_id,
                    "blockers": ["controlled_ledger_correction_retry_conflict"],
                    "production_ledger_mutated": False,
                },
            )

        preview = self.preview(
            posting_id=posting_id,
            reason_code=reason_code,
            operator_id=operator_id,
        )
        rejection_reasons: list[str] = []
        if correction_fingerprint != preview["correction_fingerprint"]:
            rejection_reasons.append(
                "controlled_ledger_correction_fingerprint_mismatch"
            )
        if acknowledgement != CONTROLLED_SUBMISSION_LEDGER_CORRECTION_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_ledger_correction_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_ledger_correction_review_blocked")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="reverse_controlled_submission_ledger_posting",
            expected_artifact_type="controlled_submission_ledger_correction",
            expected_artifact_fingerprint=preview["correction_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("controlled_ledger_correction_operator_blocked")
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append("controlled_ledger_correction_operator_mismatch")

        if rejection_reasons:
            concurrent = (
                self._db.get_controlled_submission_ledger_correction_for_posting_sync(
                    posting_id
                )
            )
            if concurrent is not None and str(
                concurrent.get("correction_fingerprint") or ""
            ) == str(correction_fingerprint or ""):
                return self._post_apply_response(concurrent, reused=True)
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=correction_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise ControlledSubmissionLedgerCorrectionRejected(
                "controlled submission ledger correction rejected",
                evidence=evidence,
            )

        now = _aware_utc(self._clock())
        payload = {
            key: preview[key]
            for key in (
                "schema_version",
                "correction_id",
                "correction_fingerprint",
                "posting_id",
                "posting_fingerprint",
                "original_ledger_entry_ids",
                "original_ledger_entry_fingerprint",
                "reason_code",
                "operator_id",
                "account_truth_import_run_id",
                "account_truth_file_fingerprint",
                "account_truth_source_fingerprint",
                "account_truth_review_fingerprint",
                "pre_valuation_snapshot_id",
                "pre_valuation_as_of",
                "pre_valuation_status",
                "pre_ledger_cutoff_id",
                "pre_ledger_fingerprint",
                "plan_fingerprint",
                "correction_plan",
            )
        }
        payload.update(
            {
                "operator_approval_id": operator_approval_id,
                "status": "applied",
                "manual_final_signature_verified": True,
                "automatic_correction_enabled": False,
                "broker_submission_enabled": False,
                "broker_cancel_enabled": False,
                "capital_authority_changed": False,
            }
        )
        transaction = self._db.record_controlled_submission_ledger_correction_sync(
            correction={
                **payload,
                "applied_at_epoch_ms": int(now.timestamp() * 1000),
                "applied_at": now.isoformat(),
                "payload": payload,
            }
        )
        if transaction.get("status") != "applied":
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=correction_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["controlled_ledger_correction_transaction_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise ControlledSubmissionLedgerCorrectionRejected(
                "controlled submission ledger correction transaction rejected",
                evidence=evidence,
            )
        return self._post_apply_response(
            transaction.get("correction") or {},
            reused=bool(transaction.get("reused")),
        )

    def get_correction(self, correction_id: str) -> dict[str, Any]:
        row = self._db.get_controlled_submission_ledger_correction_sync(correction_id)
        return (
            _correction_response(row, reused=False)
            if row is not None
            else {"status": "not_found", "correction_id": correction_id}
        )

    def list_corrections(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            _correction_response(row, reused=False)
            for row in self._db.list_controlled_submission_ledger_corrections_sync(
                limit=limit
            )
        ]

    def _resolve_account_truth(self, *, posting: dict[str, Any]) -> dict[str, Any]:
        blockers: list[str] = []
        raw: dict[str, Any] = {}
        if not callable(self._account_truth_provider):
            blockers.append("controlled_ledger_correction_account_truth_unavailable")
        else:
            try:
                value = self._account_truth_provider() or {}
            except Exception:
                value = {}
                blockers.append("controlled_ledger_correction_account_truth_failed")
            raw = value if isinstance(value, dict) else {}

        expected = {
            "import_run_id": str(posting.get("account_truth_import_run_id") or ""),
            "file_fingerprint": str(
                posting.get("account_truth_file_fingerprint") or ""
            ),
            "source_fingerprint": str(
                posting.get("account_truth_source_fingerprint") or ""
            ),
        }
        for field, expected_value in expected.items():
            if str(raw.get(field) or "") != expected_value:
                blockers.append(
                    f"controlled_ledger_correction_account_truth_{field}_changed"
                )
        if str(raw.get("data_freshness_status") or "") != "fresh":
            blockers.append("controlled_ledger_correction_account_truth_not_fresh")
        if _mapping(raw.get("ledger_coverage")).get("status") != "covered":
            blockers.append("controlled_ledger_correction_ledger_not_covered")
        if raw.get("does_not_mutate_production_ledger") is not True:
            blockers.append(
                "controlled_ledger_correction_account_truth_boundary_invalid"
            )
        captured_at = _parse_timestamp(raw.get("captured_at"))
        age_seconds: int | None = None
        if captured_at is None:
            blockers.append("controlled_ledger_correction_account_truth_time_invalid")
        else:
            age = (_aware_utc(self._clock()) - captured_at).total_seconds()
            age_seconds = int(max(0, age))
            if age < -30 or age > (
                CONTROLLED_SUBMISSION_LEDGER_CORRECTION_MAX_ACCOUNT_TRUTH_AGE_SECONDS
            ):
                blockers.append(
                    "controlled_ledger_correction_account_truth_time_not_fresh"
                )
        return {
            "status": "current" if not blockers else "blocked",
            **expected,
            "captured_at": str(raw.get("captured_at") or ""),
            "age_seconds": age_seconds,
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _post_apply_response(
        self,
        row: dict[str, Any],
        *,
        reused: bool,
    ) -> dict[str, Any]:
        response = _correction_response(row, reused=reused)
        try:
            post_valuation = self._db.publish_current_valuation_snapshot_sync()
            valuation_status = "published"
        except Exception:
            post_valuation = {}
            valuation_status = "publication_failed"
        raw_account_truth: dict[str, Any] = {}
        if callable(self._account_truth_provider):
            try:
                value = self._account_truth_provider() or {}
                raw_account_truth = value if isinstance(value, dict) else {}
            except Exception:
                raw_account_truth = {}
        covered = _mapping(raw_account_truth.get("ledger_coverage")).get("status")
        return {
            **response,
            "post_apply_status": "account_truth_recheck_required",
            "post_valuation_publication_status": valuation_status,
            "post_valuation_snapshot_id": str(post_valuation.get("snapshot_id") or ""),
            "post_ledger_cutoff_id": int(
                post_valuation.get("ledger_cutoff_id")
                or response.get("post_ledger_cutoff_id")
                or 0
            ),
            "post_account_truth": {
                "status": raw_account_truth.get("status"),
                "import_run_id": raw_account_truth.get("import_run_id"),
                "ledger_coverage": raw_account_truth.get("ledger_coverage"),
                "gate_status": raw_account_truth.get("gate_status"),
                "blockers": raw_account_truth.get("blockers"),
            },
            "post_account_truth_ledger_covered": covered == "covered",
        }

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SCHEMA_VERSION,
            "status": "rejected",
            "correction_id": str(preview.get("correction_id") or ""),
            "posting_id": str(preview.get("posting_id") or ""),
            "expected_fingerprint": str(preview.get("correction_fingerprint") or ""),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "production_ledger_mutated": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "capital_authority_changed": False,
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SUBMISSION_LEDGER_CORRECTION_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type="controlled_submission_ledger_correction_rejection",
            entity_id=attempt_id,
            source=CONTROLLED_SUBMISSION_LEDGER_CORRECTION_SOURCE,
            source_ref=payload["posting_id"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {"event_id": event_id, "attempt_id": attempt_id, **payload}


def build_controlled_ledger_correction_plan(
    *,
    ledger_rows: list[dict[str, Any]],
    original_entry_ids: list[int],
    posting_id: str,
) -> dict[str, Any]:
    """Derive the only allowed correction from deterministic ledger replay."""
    normalized_ids = sorted({int(value) for value in original_entry_ids if int(value)})
    if not normalized_ids:
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_zero_fill_posting"
        )
    original_id_set = set(normalized_ids)
    rows_by_id = {
        int(row["id"]): dict(row) for row in ledger_rows if row.get("id") is not None
    }
    if any(entry_id not in rows_by_id for entry_id in normalized_ids):
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_original_entry_missing"
        )
    original_rows = [rows_by_id[entry_id] for entry_id in normalized_ids]
    if any(
        str(row.get("source") or "") != "controlled_submission_ledger_posting"
        for row in original_rows
    ):
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_original_lineage_invalid"
        )
    symbols = {str(row.get("symbol") or "").strip() for row in original_rows}
    symbols.discard("")
    if len(symbols) != 1:
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_symbol_scope_invalid"
        )
    symbol = next(iter(symbols))
    asset_classes = {
        str(row.get("asset_class") or "stock").strip().lower() for row in original_rows
    }
    if len(asset_classes) != 1:
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_asset_class_scope_invalid"
        )

    try:
        current = build_portfolio_projection(
            [LedgerEntry.from_row(row) for row in ledger_rows]
        )
        target = build_portfolio_projection(
            [
                LedgerEntry.from_row(row)
                for row in ledger_rows
                if int(row.get("id") or 0) not in original_id_set
            ]
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_replay_invalid"
        ) from None

    all_symbols = set(current.positions) | set(target.positions)
    for other_symbol in all_symbols - {symbol}:
        if _position_state(current.positions.get(other_symbol)) != _position_state(
            target.positions.get(other_symbol)
        ):
            raise ControlledSubmissionLedgerCorrectionPlanError(
                "controlled_ledger_correction_scope_expanded"
            )
    total_deposits_delta = target.total_deposits - current.total_deposits
    if total_deposits_delta != Decimal("0"):
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_deposit_boundary_invalid"
        )

    return {
        "schema_version": CONTROLLED_SUBMISSION_LEDGER_CORRECTION_PLAN_SCHEMA_VERSION,
        "posting_id": posting_id,
        "original_ledger_entry_ids": normalized_ids,
        "effective_at": _next_ledger_timestamp(ledger_rows),
        "symbol": symbol,
        "asset_class": next(iter(asset_classes)),
        "cash_delta": _decimal_string(target.cash - current.cash),
        "total_deposits_delta": "0",
        "position_before": _position_state(current.positions.get(symbol)),
        "position_after": _position_state(target.positions.get(symbol)),
        "derivation": "canonical_replay_excluding_exact_original_posting_entries",
        "arbitrary_financial_input_used": False,
    }


def correction_plan_fingerprint(plan: dict[str, Any]) -> str:
    return _fingerprint(plan)


def _position_state(position: ProjectedPosition | None) -> dict[str, Any]:
    position = position or ProjectedPosition(symbol="")
    return {
        "quantity": _decimal_string(position.quantity),
        "available_qty": _decimal_string(position.available_qty),
        "frozen_qty": _decimal_string(position.frozen_qty),
        "avg_cost": _decimal_string(position.avg_cost),
        "realized_pnl": _decimal_string(position.realized_pnl),
        "commission_paid": _decimal_string(position.commission_paid),
        "broker_displayed_cost_basis": _decimal_string(
            position.broker_displayed_cost_basis
        ),
        "broker_displayed_unit_cost": _decimal_string(
            position.broker_displayed_unit_cost
        ),
        "broker_cost_basis_difference": _decimal_string(
            position.broker_cost_basis_difference
        ),
        "broker_cost_basis_method": position.broker_cost_basis_method,
        "broker_cost_basis_status": position.broker_cost_basis_status,
    }


def _next_ledger_timestamp(rows: list[dict[str, Any]]) -> str:
    timestamps = [_parse_timestamp(row.get("timestamp")) for row in rows]
    valid = [value for value in timestamps if value is not None]
    try:
        effective = max(valid, default=datetime(1970, 1, 1, tzinfo=timezone.utc))
        return (
            (effective + timedelta(seconds=1))
            .astimezone(timezone.utc)
            .isoformat(timespec="seconds")
        )
    except OverflowError:
        raise ControlledSubmissionLedgerCorrectionPlanError(
            "controlled_ledger_correction_timestamp_unavailable"
        ) from None


def _load_all_ledger_rows(db: Any, *, batch_size: int = 500) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = list(db.get_ledger_entries_sync(limit=batch_size, offset=offset) or [])
        rows.extend(dict(row) for row in batch)
        if len(batch) < batch_size:
            break
        offset += batch_size
    return sorted(rows, key=lambda row: int(row.get("id") or 0))


def _parse_integer_list(value: Any) -> list[int]:
    if isinstance(value, list):
        raw = value
    else:
        try:
            raw = json.loads(str(value or "[]"))
        except (TypeError, ValueError):
            raw = []
    if not isinstance(raw, list):
        return []
    try:
        return sorted({int(item) for item in raw if int(item) > 0})
    except (TypeError, ValueError):
        return []


def _correction_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    original_ids = _parse_integer_list(row.get("original_ledger_entry_ids_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "correction_id": str(row.get("correction_id") or ""),
        "correction_fingerprint": str(row.get("correction_fingerprint") or ""),
        "posting_id": str(row.get("posting_id") or ""),
        "status": str(row.get("status") or "applied"),
        "reason_code": str(row.get("reason_code") or ""),
        "original_ledger_entry_ids": original_ids,
        "correction_ledger_entry_id": int(row.get("correction_ledger_entry_id") or 0),
        "pre_ledger_cutoff_id": int(row.get("pre_ledger_cutoff_id") or 0),
        "post_ledger_cutoff_id": int(row.get("post_ledger_cutoff_id") or 0),
        "applied_at": str(row.get("applied_at") or ""),
        "persisted": bool(row),
        "reused": reused,
        "production_ledger_mutated": bool(row),
        "original_ledger_entries_deleted": False,
        "automatic_correction_enabled": False,
        "broker_submission_enabled": False,
        "broker_cancel_enabled": False,
        "capital_authority_changed": False,
        "safety": _safety_flags(),
    }


def _safety_flags() -> dict[str, Any]:
    return {
        "append_only": True,
        "original_history_preserved": True,
        "canonical_replay_derived": True,
        "ledger_identity_rechecked_in_write_transaction": True,
        "account_truth_recheck_required_after_apply": True,
        "strategy_access": "none",
        "ai_access": "none",
        "oms_mutation": "none",
        "risk_mutation": "none",
        "kill_switch_mutation": "none",
        "capital_authority_mutation": "none",
        "provider_contact": "none",
        "broker_submit": "none",
        "broker_cancel": "none",
    }


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal_string(value: Decimal | Any) -> str:
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
