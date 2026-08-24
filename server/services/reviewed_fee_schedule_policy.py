"""Pure validation and identity policy for reviewed fee schedules."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    InvalidOperation,
)
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from server.contracts.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_REVIEW_SCHEMA_VERSION,
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReview,
)

REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_schedule_preview.v4"
)
SUPPORTED_REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSIONS = frozenset(
    {
        "karkinos.account_truth.reviewed_fee_schedule_preview.v1",
        "karkinos.account_truth.reviewed_fee_schedule_preview.v2",
        "karkinos.account_truth.reviewed_fee_schedule_preview.v3",
        REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    }
)
REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_schedule_resolution.v1"
)
REVIEWED_COST_MODEL_PREFIX = "karkinos.backtest.reviewed_account_fee_schedule.v1:"
NOTIONAL_ENVELOPE_SCHEMA_VERSION = (
    "karkinos.account_truth.reviewed_fee_notional_envelope.v1"
)

SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SUPPORTED_ASSET_CLASSES = frozenset({"stock", "etf"})
TRADE_EVENT_TYPES = frozenset({"trade_buy", "trade_sell"})
ROUNDING_MODES = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "down": ROUND_DOWN,
    "up": ROUND_UP,
}
SCHEDULE_FIELDS = (
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


def normalize_schedule(raw: Mapping[str, Any]) -> dict[str, Any]:
    schedule_id = str(raw.get("schedule_id") or "").strip()
    account_profile_id = str(raw.get("account_profile_id") or "").strip()
    if not SAFE_ID_PATTERN.fullmatch(schedule_id):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_id_invalid")
    if not SAFE_ID_PATTERN.fullmatch(account_profile_id):
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
        normalized_rates[normalized_key] = decimal_text(value, nonnegative=True)
    limitations = raw.get("limitations") or ()
    if not isinstance(limitations, list | tuple):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_limitations_invalid")
    money_precision = raw.get("money_precision")
    transfer_fee_rate = raw.get("transfer_fee_rate")
    fund_etf_transfer_fee_rate = raw.get("fund_etf_transfer_fee_rate")
    if fund_etf_transfer_fee_rate is None:
        fund_etf_transfer_fee_rate = transfer_fee_rate
    rounding_mode = str(raw.get("money_rounding_mode") or "none").strip().lower()
    if rounding_mode not in {"none", *ROUNDING_MODES}:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_rounding_mode_invalid")
    if (money_precision is None) != (rounding_mode == "none"):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_rounding_terms_inconsistent"
        )
    return {
        "schedule_id": schedule_id,
        "account_profile_id": account_profile_id,
        "broker_name": str(raw.get("broker_name") or "").strip(),
        "stock_a_commission_rate": decimal_text(
            raw.get("stock_a_commission_rate"), nonnegative=True
        ),
        "stock_a_min_commission": decimal_text(
            raw.get("stock_a_min_commission"), nonnegative=True
        ),
        "fund_etf_commission_rate": decimal_text(
            raw.get("fund_etf_commission_rate"), nonnegative=True
        ),
        "fund_etf_min_commission": decimal_text(
            raw.get("fund_etf_min_commission"), nonnegative=True
        ),
        "stamp_tax_rate": decimal_text(raw.get("stamp_tax_rate"), nonnegative=True),
        "transfer_fee_rate": decimal_text(transfer_fee_rate, nonnegative=True),
        "fund_etf_transfer_fee_rate": decimal_text(
            fund_etf_transfer_fee_rate, nonnegative=True
        ),
        "exchange_transfer_fee_rates": dict(sorted(normalized_rates.items())),
        "other_fee_rate": decimal_text(raw.get("other_fee_rate"), nonnegative=True),
        "money_precision": (
            decimal_text(money_precision, positive=True)
            if money_precision is not None
            else None
        ),
        "money_rounding_mode": rounding_mode,
        "limitations": sorted(
            {str(item).strip() for item in limitations if str(item).strip()}
        ),
    }


def schedule_from_config(config: Any) -> dict[str, Any]:
    schedule = getattr(config, "broker_fee_schedule", None)
    if schedule is None:
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_config_missing")
    return normalize_schedule(
        {
            field_name: getattr(schedule, field_name, None)
            for field_name in SCHEDULE_FIELDS
        }
    )


def validated_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(preview)
    schema_version = normalized.get("schema_version")
    if schema_version not in SUPPORTED_REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSIONS:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_preview_schema_invalid"
        )
    fingerprint = str(normalized.pop("preview_fingerprint", ""))
    if fingerprint != fingerprint_payload(normalized):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_preview_fingerprint_invalid"
        )
    normalized["preview_fingerprint"] = fingerprint
    if schema_version == REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION:
        reviewed_asset_classes = normalize_reviewed_asset_classes(
            normalized.get("reviewed_asset_classes")
        )
        if list(reviewed_asset_classes) != normalized.get("reviewed_asset_classes"):
            raise ReviewedFeeScheduleRejected(
                "reviewed_fee_schedule_preview_asset_scope_invalid"
            )
    for field_name in (
        "schedule_fingerprint",
        "account_truth_source_fingerprint",
        "account_truth_scope_fingerprint",
        "account_reference_hash",
    ):
        if not SHA256_PATTERN.fullmatch(str(normalized.get(field_name) or "")):
            raise ReviewedFeeScheduleRejected(
                f"reviewed_fee_schedule_preview_{field_name}_invalid"
            )
    return normalized


def review_from_row(row: Mapping[str, Any]) -> ReviewedFeeScheduleReview:
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
    validate_review_identity(review)
    validate_review_bindings(review, schedule=schedule, preview=preview)
    return review


def validate_review_identity(review: ReviewedFeeScheduleReview) -> None:
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
        or not SAFE_ID_PATTERN.fullmatch(review.reviewer)
        or not SAFE_ID_PATTERN.fullmatch(review.account_truth_import_run_id)
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
        if not SHA256_PATTERN.fullmatch(value):
            raise ReviewedFeeScheduleReadRejected(
                "reviewed_fee_schedule_review_fingerprint_invalid"
            )
    try:
        date_window(review.effective_start_date, review.effective_end_date)
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
    if review.review_fingerprint != fingerprint_payload(core):
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_review_fingerprint_invalid"
        )


def validate_review_bindings(
    review: ReviewedFeeScheduleReview,
    *,
    schedule: Mapping[str, Any],
    preview: Mapping[str, Any],
) -> None:
    try:
        normalized_schedule = normalize_schedule(schedule)
    except ReviewedFeeScheduleRejected as exc:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_schedule_invalid"
        ) from exc
    accepted_schedule_fingerprints = {fingerprint_payload(normalized_schedule)}
    if "fund_etf_transfer_fee_rate" not in schedule:
        legacy_schedule = dict(normalized_schedule)
        legacy_schedule.pop("fund_etf_transfer_fee_rate")
        accepted_schedule_fingerprints.add(fingerprint_payload(legacy_schedule))
    if review.schedule_fingerprint not in accepted_schedule_fingerprints:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_schedule_fingerprint_invalid"
        )
    try:
        normalized_preview = validated_preview(preview)
    except ReviewedFeeScheduleRejected as exc:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_preview_invalid"
        ) from exc
    if normalized_preview["preview_fingerprint"] != review.preview_fingerprint:
        raise ReviewedFeeScheduleReadRejected(
            "reviewed_fee_schedule_preview_binding_invalid"
        )


def normalize_asset_class(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return "etf" if normalized in {"fund", "fund_etf"} else normalized


def normalize_reviewed_asset_classes(
    values: Sequence[str] | object | None,
) -> tuple[str, ...]:
    if values is None:
        return tuple(sorted(SUPPORTED_ASSET_CLASSES))
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_reviewed_asset_classes_invalid"
        )
    normalized = tuple(sorted({normalize_asset_class(item) for item in values}))
    if not normalized or any(
        item not in SUPPORTED_ASSET_CLASSES for item in normalized
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_reviewed_asset_classes_invalid"
        )
    return normalized


def reviewed_asset_classes_from_preview(
    preview: Mapping[str, Any],
) -> tuple[str, ...]:
    if preview.get("schema_version") in {
        "karkinos.account_truth.reviewed_fee_schedule_preview.v3",
        REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    }:
        return normalize_reviewed_asset_classes(preview.get("reviewed_asset_classes"))
    return tuple(sorted(SUPPORTED_ASSET_CLASSES))


def account_truth_clock(
    account_truth_as_of: datetime | None,
) -> Callable[[], datetime] | None:
    if account_truth_as_of is None:
        return None
    if (
        not isinstance(account_truth_as_of, datetime)
        or account_truth_as_of.tzinfo is None
        or account_truth_as_of.utcoffset() is None
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_account_truth_as_of_invalid"
        )
    frozen = account_truth_as_of
    return lambda: frozen


def date_window(start: str, end: str) -> tuple[str, str]:
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


def event_date(value: object) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.date().isoformat()


def decimal_value(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def decimal_text(
    value: object,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> str:
    parsed = decimal_value(value)
    if parsed is None or (nonnegative and parsed < 0) or (positive and parsed <= 0):
        raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_numeric_term_invalid")
    return format(parsed.normalize(), "f")


def database_path(state: Any) -> Path | None:
    value = getattr(getattr(state, "db", None), "_path", None)
    return Path(value) if value is not None else None


def mapping_payload(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def fingerprint_payload(payload: Mapping[str, Any]) -> str:
    return (
        "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    )


__all__ = [
    "NOTIONAL_ENVELOPE_SCHEMA_VERSION",
    "REVIEWED_COST_MODEL_PREFIX",
    "REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION",
    "REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION",
    "ROUNDING_MODES",
    "SAFE_ID_PATTERN",
    "SHA256_PATTERN",
    "SUPPORTED_ASSET_CLASSES",
    "SUPPORTED_REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSIONS",
    "TRADE_EVENT_TYPES",
    "account_truth_clock",
    "canonical_json",
    "database_path",
    "date_window",
    "decimal_text",
    "decimal_value",
    "event_date",
    "fingerprint_payload",
    "mapping_payload",
    "normalize_asset_class",
    "normalize_reviewed_asset_classes",
    "normalize_schedule",
    "review_from_row",
    "reviewed_asset_classes_from_preview",
    "schedule_from_config",
    "validated_preview",
]
