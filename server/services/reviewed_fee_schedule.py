"""Reviewed, account-bound fee schedules for deterministic research backtests.

The configured schedule is only an ingestion proposal.  It becomes eligible for
strategy research after an append-only owner review binds it to one exact,
currently reconciled Account Truth import and the modeled components agree with
persisted broker trade rows.  No source rows, account identifiers, or filenames
are copied into this review store.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    InvalidOperation,
)
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping, Sequence

from account_truth.broker_evidence import (
    BrokerEvidenceReadRejected,
    BrokerEvidenceRepository,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReviewReadRejected,
    EvidenceScopeReviewRepository,
)
from account_truth.reconciliation import MONEY_RECONCILIATION_TOLERANCE
from core.types import CommissionType, OrderSide
from execution.commission import (
    CommissionCalculator,
    ETFCommission,
    FeeBreakdown,
    MultiAssetCommission,
    StockACommission,
)
from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_readiness,
)
from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_schedule_preview.v1"
)
REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_schedule_review.v1"
)
REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_schedule_resolution.v1"
)
REVIEWED_COST_MODEL_PREFIX = "karkinos.backtest.reviewed_account_fee_schedule.v1:"
REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION = (
    "approve_reconciled_account_fee_schedule_for_research_only_without_execution_"
    "or_capital_authority"
)
REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION = (
    "revoke_reconciled_account_fee_schedule_without_execution_or_capital_authority"
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SUPPORTED_ASSET_CLASSES = frozenset({"stock", "etf"})
_TRADE_EVENT_TYPES = frozenset({"trade_buy", "trade_sell"})
_NOTIONAL_ENVELOPE_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_notional_envelope.v1"
)
_ROUNDING_MODES = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "down": ROUND_DOWN,
    "up": ROUND_UP,
}
_SCHEDULE_FIELDS = (
    "schedule_id",
    "account_profile_id",
    "broker_name",
    "stock_a_commission_rate",
    "stock_a_min_commission",
    "fund_etf_commission_rate",
    "fund_etf_min_commission",
    "stamp_tax_rate",
    "transfer_fee_rate",
    "fund_etf_transfer_fee_rate",
    "exchange_transfer_fee_rates",
    "other_fee_rate",
    "money_precision",
    "money_rounding_mode",
    "limitations",
)
_REVIEW_COLUMNS = (
    "review_id",
    "schema_version",
    "decision",
    "schedule_json",
    "schedule_fingerprint",
    "preview_json",
    "preview_fingerprint",
    "account_truth_import_run_id",
    "account_truth_source_fingerprint",
    "account_truth_scope_fingerprint",
    "account_reference_hash",
    "effective_start_date",
    "effective_end_date",
    "reviewer",
    "review_fingerprint",
    "created_at",
)


class ReviewedFeeScheduleRejected(ValueError):
    """A stable fail-closed rejection for review or resolution."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReviewedFeeScheduleReadRejected(RuntimeError):
    """Persisted review state could not be read without guessing."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _RoundedCommissionCalculator(CommissionCalculator):
    """Apply the reviewed broker's per-component money rounding exactly."""

    def __init__(
        self,
        calculator: CommissionCalculator,
        *,
        precision: Decimal,
        rounding_mode: str,
    ) -> None:
        self._calculator = calculator
        self._precision = precision
        self._rounding = _ROUNDING_MODES[rounding_mode]

    def calculate(
        self,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        return self.breakdown(side, price, quantity).total_fee

    def breakdown(
        self,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> FeeBreakdown:
        source = self._calculator.breakdown(side, price, quantity)
        commission = source.commission.quantize(
            self._precision, rounding=self._rounding
        )
        stamp_tax = source.stamp_tax.quantize(self._precision, rounding=self._rounding)
        transfer_fee = source.transfer_fee.quantize(
            self._precision, rounding=self._rounding
        )
        other_fees = source.other_fees.quantize(
            self._precision, rounding=self._rounding
        )
        return FeeBreakdown(
            gross_amount=source.gross_amount,
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            other_fees=other_fees,
            total_fee=commission + stamp_tax + transfer_fee + other_fees,
            fee_rule_id=source.fee_rule_id,
            limitations=source.limitations,
        )


class _NotionalBoundedCommissionCalculator(CommissionCalculator):
    """Reject cost extrapolation beyond matched historical Account Truth."""

    def __init__(
        self,
        calculator: CommissionCalculator,
        *,
        asset_class: str,
        maximum_gross_amount: Decimal,
    ) -> None:
        self._calculator = calculator
        self._asset_class = asset_class
        self._maximum_gross_amount = maximum_gross_amount

    def calculate(
        self,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        return self.breakdown(side, price, quantity).total_fee

    def breakdown(
        self,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> FeeBreakdown:
        gross_amount = price * quantity
        if (
            not gross_amount.is_finite()
            or gross_amount <= 0
            or gross_amount > self._maximum_gross_amount
        ):
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_notional_envelope_exceeded:"
                f"{self._asset_class}"
            )
        return self._calculator.breakdown(side, price, quantity)


class _UncoveredAssetCommissionCalculator(CommissionCalculator):
    """Fail closed if a resolved model is used for an unreviewed asset class."""

    def __init__(self, asset_class: str) -> None:
        self._asset_class = asset_class

    def calculate(
        self,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        return self.breakdown(side, price, quantity).total_fee

    def breakdown(
        self,
        side: OrderSide,
        price: Decimal,
        quantity: Decimal,
    ) -> FeeBreakdown:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_missing:" f"{self._asset_class}"
        )


@dataclass(frozen=True)
class ReviewedFeeScheduleReview:
    review_id: str
    schema_version: str
    decision: str
    schedule: dict[str, Any]
    schedule_fingerprint: str
    preview: dict[str, Any]
    preview_fingerprint: str
    account_truth_import_run_id: str
    account_truth_source_fingerprint: str
    account_truth_scope_fingerprint: str
    account_reference_hash: str
    effective_start_date: str
    effective_end_date: str
    reviewer: str
    review_fingerprint: str
    created_at: str
    reused: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schedule"] = dict(self.schedule)
        payload["preview"] = dict(self.preview)
        return payload


@dataclass(frozen=True)
class ReviewedFeeScheduleResolution:
    cost_model_reference: str
    commission_calc: MultiAssetCommission
    fee_evidence: dict[str, Any]
    review: ReviewedFeeScheduleReview

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION,
            "status": "resolved",
            "cost_model_reference": self.cost_model_reference,
            "review_id": self.review.review_id,
            "review_fingerprint": self.review.review_fingerprint,
            "schedule_fingerprint": self.review.schedule_fingerprint,
            "effective_start_date": self.review.effective_start_date,
            "effective_end_date": self.review.effective_end_date,
            "account_truth_import_run_id": self.review.account_truth_import_run_id,
            "account_truth_source_fingerprint": (
                self.review.account_truth_source_fingerprint
            ),
            "account_truth_scope_fingerprint": (
                self.review.account_truth_scope_fingerprint
            ),
            "broker_statement_reconciled": True,
            "persisted_review_only": True,
            "provider_contacted": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }


class ReviewedFeeScheduleReviewRepository:
    """Append-only runtime reviews; all reads are SQLite query-only."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def record_review(
        self,
        *,
        preview: Mapping[str, Any],
        expected_preview_fingerprint: str,
        reviewer: str,
        confirmation: str,
    ) -> ReviewedFeeScheduleReview:
        if confirmation != REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION:
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_approval_confirmation_invalid"
            )
        normalized_reviewer = str(reviewer or "").strip()
        if not _SAFE_ID.fullmatch(normalized_reviewer):
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_reviewer_invalid")
        normalized = _validated_preview(preview)
        if normalized["status"] != "ready":
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_preview_blocked")
        if expected_preview_fingerprint != normalized["preview_fingerprint"]:
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_preview_fingerprint_mismatch"
            )
        return self._append(
            decision="accepted",
            preview=normalized,
            reviewer=normalized_reviewer,
        )

    def revoke_latest(
        self,
        *,
        expected_review_id: str,
        expected_review_fingerprint: str,
        reviewer: str,
        confirmation: str,
    ) -> ReviewedFeeScheduleReview:
        if confirmation != REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION:
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_revocation_confirmation_invalid"
            )
        latest = self.get_latest_review()
        if latest is None:
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_review_missing")
        if (
            latest.review_id != expected_review_id
            or latest.review_fingerprint != expected_review_fingerprint
        ):
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_review_fingerprint_mismatch"
            )
        if latest.decision == "revoked":
            return ReviewedFeeScheduleReview(
                **{
                    field.name: getattr(latest, field.name)
                    for field in fields(ReviewedFeeScheduleReview)
                    if field.name != "reused"
                },
                reused=True,
            )
        normalized_reviewer = str(reviewer or "").strip()
        if not _SAFE_ID.fullmatch(normalized_reviewer):
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_reviewer_invalid")
        return self._append(
            decision="revoked",
            preview=latest.preview,
            reviewer=normalized_reviewer,
        )

    def get_latest_review(self) -> ReviewedFeeScheduleReview | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = conn.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return _review_from_row(row) if row is not None else None

    def get_review(self, review_id: str) -> ReviewedFeeScheduleReview | None:
        with self._read_connection() as conn:
            if conn is None:
                return None
            row = conn.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews WHERE review_id=? LIMIT 1",
                (str(review_id),),
            ).fetchone()
        return _review_from_row(row) if row is not None else None

    def _append(
        self,
        *,
        decision: str,
        preview: Mapping[str, Any],
        reviewer: str,
    ) -> ReviewedFeeScheduleReview:
        self._ensure_schema()
        core = {
            "schema_version": REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
            "decision": decision,
            "schedule_fingerprint": preview["schedule_fingerprint"],
            "preview_fingerprint": preview["preview_fingerprint"],
            "account_truth_import_run_id": preview["account_truth_import_run_id"],
            "account_truth_source_fingerprint": preview[
                "account_truth_source_fingerprint"
            ],
            "account_truth_scope_fingerprint": preview[
                "account_truth_scope_fingerprint"
            ],
            "account_reference_hash": preview["account_reference_hash"],
            "effective_start_date": preview["effective_start_date"],
            "effective_end_date": preview["effective_end_date"],
            "reviewer": reviewer,
        }
        review_fingerprint = _fingerprint(core)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            latest = conn.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest is not None:
                existing = _review_from_row(latest)
                if existing.review_fingerprint == review_fingerprint:
                    conn.rollback()
                    return ReviewedFeeScheduleReview(
                        **{
                            field.name: getattr(existing, field.name)
                            for field in fields(ReviewedFeeScheduleReview)
                            if field.name != "reused"
                        },
                        reused=True,
                    )
            review_id = f"fee_review_{uuid.uuid4().hex}"
            created_at = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO reviewed_fee_schedule_reviews (
                    review_id, schema_version, decision, schedule_json,
                    schedule_fingerprint, preview_json, preview_fingerprint,
                    account_truth_import_run_id, account_truth_source_fingerprint,
                    account_truth_scope_fingerprint, account_reference_hash,
                    effective_start_date, effective_end_date, reviewer,
                    review_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
                    decision,
                    _canonical_json(preview["schedule"]),
                    preview["schedule_fingerprint"],
                    _canonical_json(dict(preview)),
                    preview["preview_fingerprint"],
                    preview["account_truth_import_run_id"],
                    preview["account_truth_source_fingerprint"],
                    preview["account_truth_scope_fingerprint"],
                    preview["account_reference_hash"],
                    preview["effective_start_date"],
                    preview["effective_end_date"],
                    reviewer,
                    review_fingerprint,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM reviewed_fee_schedule_reviews WHERE review_id=?",
                (review_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("reviewed fee schedule review was not persisted")
        return _review_from_row(row)

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection | None]:
        if not self._path.is_file():
            yield None
            return
        try:
            uri = f"{self._path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    ("reviewed_fee_schedule_reviews",),
                ).fetchone()
                if row is None:
                    yield None
                    return
                columns = {
                    str(item["name"])
                    for item in conn.execute(
                        "PRAGMA table_info(reviewed_fee_schedule_reviews)"
                    ).fetchall()
                }
                if not set(_REVIEW_COLUMNS).issubset(columns):
                    raise ReviewedFeeScheduleReadRejected(
                        "reviewed_fee_schedule_review_schema_incomplete"
                    )
                yield conn
        except ReviewedFeeScheduleReadRejected:
            raise
        except sqlite3.Error as exc:
            raise ReviewedFeeScheduleReadRejected(
                "reviewed_fee_schedule_review_read_failed"
            ) from exc

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reviewed_fee_schedule_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    schedule_json TEXT NOT NULL,
                    schedule_fingerprint TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    preview_fingerprint TEXT NOT NULL,
                    account_truth_import_run_id TEXT NOT NULL,
                    account_truth_source_fingerprint TEXT NOT NULL,
                    account_truth_scope_fingerprint TEXT NOT NULL,
                    account_reference_hash TEXT NOT NULL,
                    effective_start_date TEXT NOT NULL,
                    effective_end_date TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    review_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviewed_fee_schedule_created "
                "ON reviewed_fee_schedule_reviews(id DESC)"
            )


def build_reviewed_fee_schedule_preview(
    state: Any,
    *,
    effective_start_date: str,
    effective_end_date: str,
    schedule_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare safe schedule terms with the exact current Account Truth trades."""

    start_date, end_date = _date_window(effective_start_date, effective_end_date)
    schedule = (
        _normalize_schedule(schedule_override)
        if schedule_override is not None
        else _schedule_from_config(getattr(state, "config", None))
    )
    schedule_fingerprint = _fingerprint(schedule)
    readiness = build_account_truth_evidence_readiness(state)
    promotion = build_latest_account_truth_promotion_evidence(state)
    evidence_scope = _mapping(readiness.get("evidence_scope"))
    account_binding = _mapping(evidence_scope.get("account_binding"))
    account_alias = str(account_binding.get("account_alias") or "")
    account_reference_hash = str(account_binding.get("account_reference_hash") or "")
    import_run_id = str(readiness.get("account_truth_import_run_id") or "")
    issues: list[str] = []
    if readiness.get("status") != "ready":
        issues.append("reviewed_fee_schedule_account_truth_not_ready")
    if promotion.get("status") != "clear":
        issues.append("reviewed_fee_schedule_account_truth_promotion_blocked")
    if str(promotion.get("import_run_id") or "") != import_run_id:
        issues.append("reviewed_fee_schedule_account_truth_import_mismatch")
    if not account_alias or schedule["account_profile_id"] != account_alias:
        issues.append("reviewed_fee_schedule_account_binding_mismatch")
    if not _SHA256.fullmatch(account_reference_hash):
        issues.append("reviewed_fee_schedule_account_reference_invalid")
    if not _SHA256.fullmatch(str(promotion.get("source_fingerprint") or "")):
        issues.append("reviewed_fee_schedule_account_truth_source_fingerprint_invalid")
    if not _SHA256.fullmatch(str(evidence_scope.get("evidence_fingerprint") or "")):
        issues.append("reviewed_fee_schedule_account_truth_scope_fingerprint_invalid")

    events: Sequence[Any] = ()
    db_path = _db_path(state)
    if db_path is None or not import_run_id:
        issues.append("reviewed_fee_schedule_account_truth_source_missing")
    else:
        repository = BrokerEvidenceRepository(db_path)
        import_run = repository.get_import_run(import_run_id)
        if import_run is None:
            issues.append("reviewed_fee_schedule_account_truth_import_missing")
        else:
            events = repository.list_events(
                import_run.duplicate_of_import_run_id or import_run.import_run_id
            )

    comparison = _compare_schedule_to_events(
        schedule=schedule,
        events=events,
        start_date=start_date,
        end_date=end_date,
    )
    issues.extend(comparison["issues"])
    issues = list(dict.fromkeys(issues))
    core = {
        "schema_version": REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
        "status": "ready" if not issues else "blocked",
        "schedule": schedule,
        "schedule_fingerprint": schedule_fingerprint,
        "effective_start_date": start_date,
        "effective_end_date": end_date,
        "account_truth_import_run_id": import_run_id,
        "account_truth_source_fingerprint": str(
            promotion.get("source_fingerprint") or ""
        ),
        "account_truth_scope_fingerprint": str(
            evidence_scope.get("evidence_fingerprint") or ""
        ),
        "account_reference_hash": account_reference_hash,
        "account_truth_readiness_status": readiness.get("status"),
        "account_truth_promotion_status": promotion.get("status"),
        "component_reconciliation": {
            key: value for key, value in comparison.items() if key != "issues"
        },
        "issues": issues,
        "persisted_broker_events_only": True,
        "stores_broker_event_details": False,
        "provider_contacted": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    return {**core, "preview_fingerprint": _fingerprint(core)}


def build_reviewed_fee_schedule_review_status(
    state: Any,
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Project the current review and optional action-date coverage read-only."""

    db_path = _db_path(state)
    if db_path is None:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_database_unavailable"
        )
    review = ReviewedFeeScheduleReviewRepository(db_path).get_latest_review()
    if review is None:
        return _review_status_payload(
            status="missing",
            review=None,
            blockers=["reviewed_fee_schedule_review_missing"],
            current_preview_fingerprint=None,
        )
    if review.decision != "accepted":
        return _review_status_payload(
            status="revoked",
            review=review,
            blockers=["reviewed_fee_schedule_review_revoked"],
            current_preview_fingerprint=None,
        )

    try:
        current_preview = build_reviewed_fee_schedule_preview(
            state,
            effective_start_date=review.effective_start_date,
            effective_end_date=review.effective_end_date,
            schedule_override=review.schedule,
        )
    except ReviewedFeeScheduleRejected as exc:
        return _review_status_payload(
            status="blocked",
            review=review,
            blockers=[exc.code],
            current_preview_fingerprint=None,
        )

    blockers = [str(item) for item in current_preview.get("issues") or []]
    if current_preview.get("preview_fingerprint") != review.preview_fingerprint:
        blockers.append("reviewed_fee_schedule_source_drift")
    if as_of_date is not None:
        try:
            normalized_date = date.fromisoformat(str(as_of_date)[:10]).isoformat()
        except ValueError:
            blockers.append("reviewed_fee_schedule_action_date_invalid")
        else:
            if not (
                review.effective_start_date
                <= normalized_date
                <= review.effective_end_date
            ):
                blockers.append("reviewed_fee_schedule_action_date_not_covered")
    blockers = list(dict.fromkeys(blockers))
    return _review_status_payload(
        status="blocked" if blockers else "active",
        review=review,
        blockers=blockers,
        current_preview_fingerprint=current_preview.get("preview_fingerprint"),
    )


def _review_status_payload(
    *,
    status: str,
    review: ReviewedFeeScheduleReview | None,
    blockers: list[str],
    current_preview_fingerprint: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "review": review.to_json_dict() if review is not None else None,
        "blockers": list(dict.fromkeys(blockers)),
        "current_preview_fingerprint": current_preview_fingerprint,
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def resolve_reviewed_fee_schedule(
    state: Any,
    *,
    start_date: str,
    end_date: str,
    universe: Sequence[str],
    asset_classes: Sequence[str],
    expected_cost_model_reference: str | None = None,
) -> ReviewedFeeScheduleResolution:
    """Resolve one active review and recheck its current Account Truth binding."""

    db_path = _db_path(state)
    if db_path is None:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_database_unavailable")
    review = ReviewedFeeScheduleReviewRepository(db_path).get_latest_review()
    if review is None:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_review_missing")
    if review.decision != "accepted":
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_review_revoked")
    requested_start, requested_end = _date_window(start_date, end_date)
    if (
        requested_start < review.effective_start_date
        or requested_end > review.effective_end_date
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_backtest_window_not_covered"
        )
    normalized_assets = tuple(_normalize_asset_class(item) for item in asset_classes)
    if (
        not universe
        or len(universe) != len(normalized_assets)
        or any(item not in _SUPPORTED_ASSET_CLASSES for item in normalized_assets)
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_backtest_assets_not_covered"
        )
    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date=review.effective_start_date,
        effective_end_date=review.effective_end_date,
        schedule_override=review.schedule,
    )
    if preview.get("status") != "ready":
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_current_reconciliation_blocked"
        )
    if preview.get("preview_fingerprint") != review.preview_fingerprint:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_source_drift")
    notional_limits, notional_envelope_fingerprint = _validated_notional_envelope(
        _mapping(preview.get("component_reconciliation")).get(
            "reconciled_notional_envelope"
        )
    )
    uncovered_assets = sorted(set(normalized_assets) - set(notional_limits))
    if uncovered_assets:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_asset_notional_envelope_missing:"
            + ",".join(uncovered_assets)
        )
    cost_model_reference = reviewed_cost_model_reference(review)
    if (
        expected_cost_model_reference is not None
        and expected_cost_model_reference != cost_model_reference
    ):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_reference_mismatch")
    calculator = _commission_calculator(
        review.schedule,
        universe=universe,
        asset_classes=normalized_assets,
        fee_rule_version=cost_model_reference,
        notional_limits=notional_limits,
    )
    fee_evidence = {
        "account_specific": True,
        "fee_schedule_source": "reviewed_account_truth_or_reconciled_fee_schedule",
        "fee_schedule_fingerprint": review.schedule_fingerprint,
        "broker_statement_reconciled": True,
        "fee_schedule_review_id": review.review_id,
        "fee_schedule_review_fingerprint": review.review_fingerprint,
        "fee_schedule_preview_fingerprint": review.preview_fingerprint,
        "account_truth_import_run_id": review.account_truth_import_run_id,
        "account_truth_source_fingerprint": review.account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": review.account_truth_scope_fingerprint,
        "effective_start_date": review.effective_start_date,
        "effective_end_date": review.effective_end_date,
        "fee_notional_envelope_enforced": True,
        "fee_notional_envelope_fingerprint": notional_envelope_fingerprint,
        "fee_notional_covered_asset_classes": sorted(notional_limits),
    }
    return ReviewedFeeScheduleResolution(
        cost_model_reference=cost_model_reference,
        commission_calc=calculator,
        fee_evidence=fee_evidence,
        review=review,
    )


def reviewed_cost_model_reference(review: ReviewedFeeScheduleReview) -> str:
    return (
        f"{REVIEWED_COST_MODEL_PREFIX}{review.review_id}:"
        f"{review.review_fingerprint.removeprefix('sha256:')}"
    )


def is_reviewed_cost_model_reference(value: object) -> bool:
    raw = str(value or "")
    if not raw.startswith(REVIEWED_COST_MODEL_PREFIX):
        return False
    suffix = raw.removeprefix(REVIEWED_COST_MODEL_PREFIX)
    review_id, separator, fingerprint = suffix.partition(":")
    return bool(
        separator
        and review_id.startswith("fee_review_")
        and len(review_id) <= 80
        and re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    )


def active_review_matches_fee_evidence(
    db: Any,
    fee_evidence: Mapping[str, Any],
    *,
    as_of_date: str | None = None,
) -> list[str]:
    """Recheck persisted review identity without config or provider access."""

    path = getattr(db, "_path", None)
    if path is None:
        return ["reviewed_fee_schedule_database_unavailable"]
    try:
        review = ReviewedFeeScheduleReviewRepository(path).get_latest_review()
    except ReviewedFeeScheduleReadRejected as exc:
        return [exc.code]
    if review is None:
        return ["reviewed_fee_schedule_review_missing"]
    blockers: list[str] = []
    if review.decision != "accepted":
        blockers.append("reviewed_fee_schedule_review_revoked")
    try:
        notional_limits, notional_envelope_fingerprint = _validated_notional_envelope(
            _mapping(_mapping(review.preview).get("component_reconciliation")).get(
                "reconciled_notional_envelope"
            )
        )
    except ReviewedFeeScheduleRejected as exc:
        blockers.append(exc.code)
        notional_limits = {}
        notional_envelope_fingerprint = ""
    expected = {
        "fee_schedule_review_id": review.review_id,
        "fee_schedule_review_fingerprint": review.review_fingerprint,
        "fee_schedule_fingerprint": review.schedule_fingerprint,
        "fee_schedule_preview_fingerprint": review.preview_fingerprint,
        "account_truth_import_run_id": review.account_truth_import_run_id,
        "account_truth_source_fingerprint": review.account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": review.account_truth_scope_fingerprint,
        "fee_notional_envelope_enforced": True,
        "fee_notional_envelope_fingerprint": notional_envelope_fingerprint,
        "fee_notional_covered_asset_classes": sorted(notional_limits),
    }
    for key, value in expected.items():
        if fee_evidence.get(key) != value:
            blockers.append(f"reviewed_fee_schedule_binding_mismatch:{key}")
    try:
        import_runs = BrokerEvidenceRepository(path).list_import_runs(limit=1)
        latest_scope_review = EvidenceScopeReviewRepository(path).get_latest_review(
            review.account_truth_import_run_id
        )
    except (BrokerEvidenceReadRejected, EvidenceScopeReviewReadRejected) as exc:
        blockers.append(str(getattr(exc, "code", "account_truth_review_read_failed")))
    else:
        if not import_runs:
            blockers.append("reviewed_fee_schedule_account_truth_import_missing")
        elif import_runs[0].import_run_id != review.account_truth_import_run_id:
            blockers.append("reviewed_fee_schedule_account_truth_import_drift")
        if latest_scope_review is None:
            blockers.append("reviewed_fee_schedule_account_truth_scope_review_missing")
        elif latest_scope_review.decision != "accepted":
            blockers.append("reviewed_fee_schedule_account_truth_scope_review_revoked")
        elif (
            latest_scope_review.account_reference_hash != review.account_reference_hash
        ):
            blockers.append("reviewed_fee_schedule_account_reference_drift")
    if as_of_date:
        try:
            normalized = date.fromisoformat(str(as_of_date)[:10]).isoformat()
        except ValueError:
            blockers.append("reviewed_fee_schedule_action_date_invalid")
        else:
            if not (
                review.effective_start_date <= normalized <= review.effective_end_date
            ):
                blockers.append("reviewed_fee_schedule_action_date_not_covered")
    return list(dict.fromkeys(blockers))


def _compare_schedule_to_events(
    *,
    schedule: Mapping[str, Any],
    events: Sequence[Any],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    issues: list[str] = []
    trade_events = [
        event
        for event in events
        if not bool(getattr(event, "is_row_duplicate", False))
        and str(getattr(event, "event_type", "")) in _TRADE_EVENT_TYPES
    ]
    if not trade_events:
        issues.append("reviewed_fee_schedule_trade_evidence_missing")
    side_counts = {"buy": 0, "sell": 0}
    asset_counts: dict[str, int] = {}
    asset_side_counts: dict[str, dict[str, int]] = {}
    matched_notional_limits: dict[str, dict[str, Decimal | int]] = {}
    match_count = 0
    mismatch_counts = {"fee": 0, "tax": 0, "transfer_fee": 0}
    mismatch_counts_by_asset_and_side: dict[tuple[str, str], dict[str, int]] = {}
    maximum_differences = {key: Decimal("0") for key in mismatch_counts}
    config = _config_for_schedule(schedule)

    for event in trade_events:
        occurred_date = _event_date(getattr(event, "occurred_at", ""))
        if occurred_date is None or not (start_date <= occurred_date <= end_date):
            issues.append("reviewed_fee_schedule_trade_outside_effective_window")
            continue
        event_type = str(getattr(event, "event_type", ""))
        side = "buy" if event_type == "trade_buy" else "sell"
        asset_class = _normalize_asset_class(getattr(event, "asset_class", ""))
        if asset_class not in _SUPPORTED_ASSET_CLASSES:
            issues.append("reviewed_fee_schedule_trade_asset_unsupported")
            continue
        quantity = _decimal(getattr(event, "quantity", None))
        price = _decimal(getattr(event, "price", None))
        if quantity is None or quantity <= 0 or price is None or price <= 0:
            issues.append("reviewed_fee_schedule_trade_terms_invalid")
            continue
        resolved = resolve_manual_trade_fee_breakdown(
            config,
            asset_class=asset_class,
            direction=side,
            quantity=float(quantity),
            price=float(price),
            symbol=str(getattr(event, "symbol", "")),
        )
        if resolved is None:
            issues.append("reviewed_fee_schedule_trade_model_unavailable")
            continue
        expected_components = {
            key: _decimal(resolved.fee_breakdown_json.get(key))
            for key in ("commission", "other_fees", "stamp_tax", "transfer_fee")
        }
        if any(value is None for value in expected_components.values()):
            issues.append("reviewed_fee_schedule_trade_component_invalid")
            continue
        expected = {
            "fee": expected_components["commission"]
            + expected_components["other_fees"],
            "tax": expected_components["stamp_tax"],
            "transfer_fee": expected_components["transfer_fee"],
        }
        observed = {
            "fee": _decimal(getattr(event, "fee", None)),
            "tax": _decimal(getattr(event, "tax", None)),
            "transfer_fee": _decimal(getattr(event, "transfer_fee", None)),
        }
        if any(value is None for value in (*expected.values(), *observed.values())):
            issues.append("reviewed_fee_schedule_trade_component_invalid")
            continue
        row_matches = True
        for component in mismatch_counts:
            difference = abs(observed[component] - expected[component])
            maximum_differences[component] = max(
                maximum_differences[component], difference
            )
            if difference > MONEY_RECONCILIATION_TOLERANCE:
                mismatch_counts[component] += 1
                grouped = mismatch_counts_by_asset_and_side.setdefault(
                    (asset_class, side),
                    {"fee": 0, "tax": 0, "transfer_fee": 0},
                )
                grouped[component] += 1
                row_matches = False
        side_counts[side] += 1
        asset_counts[asset_class] = asset_counts.get(asset_class, 0) + 1
        per_asset_sides = asset_side_counts.setdefault(
            asset_class,
            {"buy": 0, "sell": 0},
        )
        per_asset_sides[side] += 1
        if row_matches:
            match_count += 1
            gross_amount = quantity * price
            limit = matched_notional_limits.setdefault(
                asset_class,
                {
                    "maximum_gross_amount": Decimal("0"),
                    "matched_trade_count": 0,
                },
            )
            limit["maximum_gross_amount"] = max(
                Decimal(str(limit["maximum_gross_amount"])),
                gross_amount,
            )
            limit["matched_trade_count"] = int(limit["matched_trade_count"]) + 1

    for side, count in side_counts.items():
        if count == 0:
            issues.append(f"reviewed_fee_schedule_{side}_coverage_missing")
    for asset_class, counts in sorted(asset_side_counts.items()):
        for side, count in counts.items():
            if count == 0:
                issues.append(
                    "reviewed_fee_schedule_asset_side_coverage_missing:"
                    f"{asset_class}:{side}"
                )
    if any(mismatch_counts.values()):
        issues.append("reviewed_fee_schedule_component_mismatch")
    envelope_core = {
        "schema_version": _NOTIONAL_ENVELOPE_SCHEMA_VERSION,
        "enforcement_mode": "maximum_matched_historical_gross_by_asset_class",
        "asset_classes": sorted(matched_notional_limits),
        "limits": {
            asset_class: {
                "maximum_gross_amount": format(
                    Decimal(str(values["maximum_gross_amount"])),
                    "f",
                ),
                "matched_trade_count": int(values["matched_trade_count"]),
            }
            for asset_class, values in sorted(matched_notional_limits.items())
        },
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
    }
    notional_envelope = {
        **envelope_core,
        "evidence_fingerprint": _fingerprint(envelope_core),
    }
    return {
        "status": "pass" if not issues else "blocked",
        "trade_count": len(trade_events),
        "matched_trade_count": match_count,
        "side_counts": side_counts,
        "asset_class_counts": dict(sorted(asset_counts.items())),
        "asset_side_counts": {
            asset_class: dict(counts)
            for asset_class, counts in sorted(asset_side_counts.items())
        },
        "mismatch_counts": mismatch_counts,
        "mismatch_counts_by_asset_and_side": [
            {
                "asset_class": asset_class,
                "side": side,
                **counts,
            }
            for (asset_class, side), counts in sorted(
                mismatch_counts_by_asset_and_side.items()
            )
        ],
        "maximum_absolute_differences": {
            key: format(value, "f") for key, value in maximum_differences.items()
        },
        "tolerance": format(MONEY_RECONCILIATION_TOLERANCE, "f"),
        "reconciled_notional_envelope": notional_envelope,
        "issues": list(dict.fromkeys(issues)),
    }


def _schedule_from_config(config: Any) -> dict[str, Any]:
    schedule = getattr(config, "broker_fee_schedule", None)
    if schedule is None:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_config_missing")
    return _normalize_schedule(
        {
            field_name: getattr(schedule, field_name, None)
            for field_name in _SCHEDULE_FIELDS
        }
    )


def _normalize_schedule(raw: Mapping[str, Any]) -> dict[str, Any]:
    schedule_id = str(raw.get("schedule_id") or "").strip()
    account_profile_id = str(raw.get("account_profile_id") or "").strip()
    if not _SAFE_ID.fullmatch(schedule_id):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_id_invalid")
    if not _SAFE_ID.fullmatch(account_profile_id):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_account_profile_invalid"
        )
    exchange_rates = raw.get("exchange_transfer_fee_rates")
    exchange_rates = exchange_rates if isinstance(exchange_rates, Mapping) else {}
    normalized_rates: dict[str, str] = {}
    for key, value in exchange_rates.items():
        normalized_key = str(key).strip().lower()
        if normalized_key not in {"shanghai", "shenzhen"}:
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_exchange_invalid")
        normalized_rates[normalized_key] = _decimal_text(value, nonnegative=True)
    limitations = raw.get("limitations") or ()
    if not isinstance(limitations, list | tuple):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_limitations_invalid")
    money_precision = raw.get("money_precision")
    transfer_fee_rate = raw.get("transfer_fee_rate")
    fund_etf_transfer_fee_rate = raw.get("fund_etf_transfer_fee_rate")
    if fund_etf_transfer_fee_rate is None:
        fund_etf_transfer_fee_rate = transfer_fee_rate
    rounding_mode = str(raw.get("money_rounding_mode") or "none").strip().lower()
    if rounding_mode not in {"none", *_ROUNDING_MODES}:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_rounding_mode_invalid")
    if (money_precision is None) != (rounding_mode == "none"):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_rounding_terms_inconsistent"
        )
    return {
        "schedule_id": schedule_id,
        "account_profile_id": account_profile_id,
        "broker_name": str(raw.get("broker_name") or "").strip(),
        "stock_a_commission_rate": _decimal_text(
            raw.get("stock_a_commission_rate"), nonnegative=True
        ),
        "stock_a_min_commission": _decimal_text(
            raw.get("stock_a_min_commission"), nonnegative=True
        ),
        "fund_etf_commission_rate": _decimal_text(
            raw.get("fund_etf_commission_rate"), nonnegative=True
        ),
        "fund_etf_min_commission": _decimal_text(
            raw.get("fund_etf_min_commission"), nonnegative=True
        ),
        "stamp_tax_rate": _decimal_text(raw.get("stamp_tax_rate"), nonnegative=True),
        "transfer_fee_rate": _decimal_text(transfer_fee_rate, nonnegative=True),
        "fund_etf_transfer_fee_rate": _decimal_text(
            fund_etf_transfer_fee_rate, nonnegative=True
        ),
        "exchange_transfer_fee_rates": dict(sorted(normalized_rates.items())),
        "other_fee_rate": _decimal_text(raw.get("other_fee_rate"), nonnegative=True),
        "money_precision": (
            _decimal_text(money_precision, positive=True)
            if money_precision is not None
            else None
        ),
        "money_rounding_mode": rounding_mode,
        "limitations": sorted(
            {str(item).strip() for item in limitations if str(item).strip()}
        ),
    }


def _config_for_schedule(schedule: Mapping[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        account_commission_rate=schedule["stock_a_commission_rate"],
        account_min_commission=schedule["stock_a_min_commission"],
        broker_fee_schedule=SimpleNamespace(**dict(schedule)),
    )


def _validated_notional_envelope(value: Any) -> tuple[dict[str, Decimal], str]:
    envelope = _mapping(value)
    if envelope.get("schema_version") != _NOTIONAL_ENVELOPE_SCHEMA_VERSION:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_schema_invalid"
        )
    fingerprint = str(envelope.pop("evidence_fingerprint", ""))
    if not _SHA256.fullmatch(fingerprint) or fingerprint != _fingerprint(envelope):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_fingerprint_invalid"
        )
    if envelope.get("enforcement_mode") != (
        "maximum_matched_historical_gross_by_asset_class"
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_mode_invalid"
        )
    raw_limits = _mapping(envelope.get("limits"))
    limits: dict[str, Decimal] = {}
    for asset_class, raw_limit in raw_limits.items():
        normalized_asset_class = _normalize_asset_class(asset_class)
        terms = _mapping(raw_limit)
        maximum = _decimal(terms.get("maximum_gross_amount"))
        try:
            matched_trade_count = int(terms.get("matched_trade_count") or 0)
        except (TypeError, ValueError):
            matched_trade_count = 0
        if (
            normalized_asset_class not in _SUPPORTED_ASSET_CLASSES
            or normalized_asset_class in limits
            or maximum is None
            or maximum <= 0
            or matched_trade_count <= 0
        ):
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_notional_envelope_limit_invalid"
            )
        limits[normalized_asset_class] = maximum
    if sorted(limits) != sorted(envelope.get("asset_classes") or []):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_assets_invalid"
        )
    if not limits:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_missing"
        )
    return limits, fingerprint


def _commission_calculator(
    schedule: Mapping[str, Any],
    *,
    universe: Sequence[str],
    asset_classes: Sequence[str],
    fee_rule_version: str,
    notional_limits: Mapping[str, Decimal],
) -> MultiAssetCommission:
    rule_id = f"reviewed_fee_schedule:{schedule['schedule_id']}"
    limitations = tuple(str(item) for item in schedule.get("limitations") or [])
    exchange_rates = {
        str(key): Decimal(str(value))
        for key, value in _mapping(schedule.get("exchange_transfer_fee_rates")).items()
    }
    money_precision = schedule.get("money_precision")
    rounding_mode = str(schedule.get("money_rounding_mode") or "none")

    def with_rounding(value: CommissionCalculator) -> CommissionCalculator:
        if money_precision is None:
            return value
        return _RoundedCommissionCalculator(
            value,
            precision=Decimal(str(money_precision)),
            rounding_mode=rounding_mode,
        )

    def evidence_bounded(
        value: CommissionCalculator,
        *,
        asset_class: str,
    ) -> CommissionCalculator:
        maximum = notional_limits.get(asset_class)
        if maximum is None or maximum <= 0:
            return _UncoveredAssetCommissionCalculator(asset_class)
        return _NotionalBoundedCommissionCalculator(
            with_rounding(value),
            asset_class=asset_class,
            maximum_gross_amount=maximum,
        )

    calculator = MultiAssetCommission(fee_rule_version=fee_rule_version)
    calculator.set_commission(
        CommissionType.STOCK_A,
        evidence_bounded(
            StockACommission(
                commission_rate=Decimal(str(schedule["stock_a_commission_rate"])),
                min_commission=Decimal(str(schedule["stock_a_min_commission"])),
                stamp_tax_rate=Decimal(str(schedule["stamp_tax_rate"])),
                transfer_fee_rate=Decimal(str(schedule["transfer_fee_rate"])),
                exchange_transfer_fee_rates=exchange_rates,
                other_fee_rate=Decimal(str(schedule["other_fee_rate"])),
                fee_rule_id=rule_id,
                limitations=limitations,
            ),
            asset_class="stock",
        ),
    )
    calculator.set_commission(
        CommissionType.FUND_ETF,
        evidence_bounded(
            ETFCommission(
                commission_rate=Decimal(str(schedule["fund_etf_commission_rate"])),
                min_commission=Decimal(str(schedule["fund_etf_min_commission"])),
                transfer_fee_rate=Decimal(str(schedule["fund_etf_transfer_fee_rate"])),
                other_fee_rate=Decimal(str(schedule["other_fee_rate"])),
                fee_rule_id=rule_id,
                limitations=limitations,
            ),
            asset_class="etf",
        ),
    )
    for symbol, asset_class in zip(universe, asset_classes, strict=True):
        if asset_class != "stock":
            continue
        exchange = _infer_stock_exchange(str(symbol))
        calculator.set_symbol_commission(
            str(symbol),
            evidence_bounded(
                StockACommission(
                    commission_rate=Decimal(str(schedule["stock_a_commission_rate"])),
                    min_commission=Decimal(str(schedule["stock_a_min_commission"])),
                    stamp_tax_rate=Decimal(str(schedule["stamp_tax_rate"])),
                    transfer_fee_rate=Decimal(str(schedule["transfer_fee_rate"])),
                    exchange=exchange,
                    exchange_transfer_fee_rates=exchange_rates,
                    other_fee_rate=Decimal(str(schedule["other_fee_rate"])),
                    fee_rule_id=rule_id,
                    limitations=limitations,
                ),
                asset_class="stock",
            ),
        )
    return calculator


def _validated_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(preview)
    if normalized.get("schema_version") != REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_preview_schema_invalid"
        )
    fingerprint = str(normalized.pop("preview_fingerprint", ""))
    if fingerprint != _fingerprint(normalized):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_preview_fingerprint_invalid"
        )
    normalized["preview_fingerprint"] = fingerprint
    for field_name in (
        "schedule_fingerprint",
        "account_truth_source_fingerprint",
        "account_truth_scope_fingerprint",
        "account_reference_hash",
    ):
        if not _SHA256.fullmatch(str(normalized.get(field_name) or "")):
            raise ReviewedFeeScheduleRejected(
                f"reviewed_fee_schedule_preview_{field_name}_invalid"
            )
    return normalized


def _review_from_row(row: sqlite3.Row) -> ReviewedFeeScheduleReview:
    try:
        schedule = json.loads(str(row["schedule_json"]))
        preview = json.loads(str(row["preview_json"]))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_json_invalid"
        ) from exc
    if not isinstance(schedule, dict) or not isinstance(preview, dict):
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_json_invalid"
        )
    review = ReviewedFeeScheduleReview(
        review_id=str(row["review_id"]),
        schema_version=str(row["schema_version"]),
        decision=str(row["decision"]),
        schedule=schedule,
        schedule_fingerprint=str(row["schedule_fingerprint"]),
        preview=preview,
        preview_fingerprint=str(row["preview_fingerprint"]),
        account_truth_import_run_id=str(row["account_truth_import_run_id"]),
        account_truth_source_fingerprint=str(row["account_truth_source_fingerprint"]),
        account_truth_scope_fingerprint=str(row["account_truth_scope_fingerprint"]),
        account_reference_hash=str(row["account_reference_hash"]),
        effective_start_date=str(row["effective_start_date"]),
        effective_end_date=str(row["effective_end_date"]),
        reviewer=str(row["reviewer"]),
        review_fingerprint=str(row["review_fingerprint"]),
        created_at=str(row["created_at"]),
    )
    if review.schema_version != REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_schema_invalid"
        )
    if review.decision not in {"accepted", "revoked"}:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_decision_invalid"
        )
    if (
        not review.review_id.startswith("fee_review_")
        or not _SAFE_ID.fullmatch(review.reviewer)
        or not _SAFE_ID.fullmatch(review.account_truth_import_run_id)
    ):
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_identity_invalid"
        )
    for value in (
        review.schedule_fingerprint,
        review.preview_fingerprint,
        review.account_truth_source_fingerprint,
        review.account_truth_scope_fingerprint,
        review.account_reference_hash,
        review.review_fingerprint,
    ):
        if not _SHA256.fullmatch(value):
            raise ReviewedFeeScheduleReadRejected(
                "reviewed_fee_schedule_review_fingerprint_invalid"
            )
    try:
        _date_window(review.effective_start_date, review.effective_end_date)
    except ReviewedFeeScheduleRejected as exc:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_window_invalid"
        ) from exc
    core = {
        "schema_version": review.schema_version,
        "decision": review.decision,
        "schedule_fingerprint": review.schedule_fingerprint,
        "preview_fingerprint": review.preview_fingerprint,
        "account_truth_import_run_id": review.account_truth_import_run_id,
        "account_truth_source_fingerprint": review.account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": review.account_truth_scope_fingerprint,
        "account_reference_hash": review.account_reference_hash,
        "effective_start_date": review.effective_start_date,
        "effective_end_date": review.effective_end_date,
        "reviewer": review.reviewer,
    }
    if review.review_fingerprint != _fingerprint(core):
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_fingerprint_invalid"
        )
    try:
        normalized_schedule = _normalize_schedule(schedule)
    except ReviewedFeeScheduleRejected as exc:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_schedule_invalid"
        ) from exc
    accepted_schedule_fingerprints = {_fingerprint(normalized_schedule)}
    if "fund_etf_transfer_fee_rate" not in schedule:
        legacy_schedule = dict(normalized_schedule)
        legacy_schedule.pop("fund_etf_transfer_fee_rate")
        accepted_schedule_fingerprints.add(_fingerprint(legacy_schedule))
    if review.schedule_fingerprint not in accepted_schedule_fingerprints:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_schedule_fingerprint_invalid"
        )
    try:
        validated_preview = _validated_preview(preview)
    except ReviewedFeeScheduleRejected as exc:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_preview_invalid"
        ) from exc
    if validated_preview["preview_fingerprint"] != review.preview_fingerprint:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_preview_binding_invalid"
        )
    return review


def _normalize_asset_class(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return "etf" if normalized in {"fund", "fund_etf"} else normalized


def _infer_stock_exchange(symbol: str) -> str | None:
    normalized = symbol.strip().upper()
    if normalized.startswith(("5", "6", "9", "688")) or normalized.endswith(
        (".SH", ".SSE")
    ):
        return "shanghai"
    if normalized.startswith(("0", "1", "2", "3")) or normalized.endswith(
        (".SZ", ".SZSE")
    ):
        return "shenzhen"
    return None


def _date_window(start: str, end: str) -> tuple[str, str]:
    try:
        normalized_start = date.fromisoformat(str(start)).isoformat()
        normalized_end = date.fromisoformat(str(end)).isoformat()
    except ValueError as exc:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_effective_window_invalid"
        ) from exc
    if normalized_start > normalized_end:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_effective_window_invalid"
        )
    return normalized_start, normalized_end


def _event_date(value: object) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.date().isoformat()


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_text(
    value: object,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> str:
    parsed = _decimal(value)
    if parsed is None or (nonnegative and parsed < 0) or (positive and parsed <= 0):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_numeric_term_invalid")
    return format(parsed.normalize(), "f")


def _db_path(state: Any) -> Path | None:
    value = getattr(getattr(state, "db", None), "_path", None)
    return Path(value) if value is not None else None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return (
        "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    )
