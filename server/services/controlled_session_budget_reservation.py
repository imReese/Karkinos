"""Atomic budget reservations for signed, still non-executing sessions."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any, Callable
from zoneinfo import ZoneInfo

CONTROLLED_SESSION_BUDGET_RESERVATION_SCHEMA_VERSION = (
    "karkinos.controlled_session_budget_reservation.v2"
)
CONTROLLED_SESSION_BUDGET_RESERVATION_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_session_budget_reservation_status.v2"
)
CONTROLLED_SESSION_BUDGET_RESERVATION_REJECTION_EVENT_TYPE = (
    "controlled_session.budget_reservation_rejected"
)
CONTROLLED_SESSION_BUDGET_RESERVATION_ENTITY_TYPE = (
    "controlled_session_budget_reservation"
)
CONTROLLED_SESSION_BUDGET_RESERVATION_EVENT_SOURCE = (
    "controlled_session_budget_reservation"
)
CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT = (
    "reserve_exact_non_authorizing_controlled_session_budget"
)
CONTROLLED_SESSION_MONEY_UNIT_SCALE = 10_000
CONTROLLED_SESSION_TRADING_TIMEZONE = "Asia/Shanghai"

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ControlledSessionBudgetReservationRejected(ValueError):
    """Raised after a rejected atomic reservation attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionBudgetReservationService:
    """Reserve capital for one current signed envelope without issuing a session."""

    def __init__(
        self,
        *,
        db: Any,
        attestation_provider: Callable[[str], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._attestation_provider = attestation_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": (
                CONTROLLED_SESSION_BUDGET_RESERVATION_STATUS_SCHEMA_VERSION
            ),
            "contract_status": "atomic_budget_reservation_non_executing",
            "attestation_revalidation_required": True,
            "transaction_mode": "sqlite_begin_immediate_fail_closed",
            "money_unit_scale": CONTROLLED_SESSION_MONEY_UNIT_SCALE,
            "money_rounding": "positive_amounts_round_up_to_0.0001_cny",
            "per_symbol_runtime_budget": "required_and_atomic",
            "runtime_session_authority": "disabled",
            "session_issue_enabled": False,
            "broker_submission_enabled": False,
            "acknowledgement": (CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT),
            "safety": _safety_flags(reserves_budget=False),
        }

    def preview(self, *, attestation_id: str) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized = str(attestation_id or "").strip().lower()
        blockers: list[str] = []
        attestation: dict[str, Any] = {}
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            blockers.append("controlled_session_attestation_id_invalid")
        elif not callable(self._attestation_provider):
            blockers.append("controlled_session_attestation_provider_unavailable")
        else:
            try:
                resolved = self._attestation_provider(normalized) or {}
            except Exception:
                resolved = {}
                blockers.append("controlled_session_attestation_provider_failed")
            attestation = resolved if isinstance(resolved, dict) else {}
        if attestation.get("status") != "current_verified_non_executing":
            blockers.append("controlled_session_attestation_not_current")
            blockers.extend(
                f"attestation:{item}"
                for item in attestation.get("blockers") or []
                if isinstance(item, str)
            )

        envelope = (
            attestation.get("current_envelope")
            if isinstance(attestation.get("current_envelope"), dict)
            else {}
        )
        capital = (
            envelope.get("capital_evaluation")
            if isinstance(envelope.get("capital_evaluation"), dict)
            else {}
        )
        scope = capital.get("scope") if isinstance(capital.get("scope"), dict) else {}
        budget = (
            envelope.get("budget_projection")
            if isinstance(envelope.get("budget_projection"), dict)
            else {}
        )
        symbol_limit_summary = (
            envelope.get("per_symbol_runtime_limits")
            if isinstance(envelope.get("per_symbol_runtime_limits"), dict)
            else {}
        )
        gross = _decimal(budget.get("projected_gross_order_value"))
        buy = _decimal(budget.get("projected_buy_value"))
        effective_capital = _decimal(budget.get("effective_capital"))
        current_exposure = _decimal(budget.get("current_authorized_exposure"))
        available_cash = _decimal(budget.get("available_cash"))
        remaining_turnover_after = _decimal(
            budget.get("remaining_daily_turnover_after_projection")
        )
        order_count = _positive_int(budget.get("order_count"))
        order_count_capacity = _positive_int(budget.get("projected_rate_capacity"))
        monetary_values = (
            gross,
            buy,
            effective_capital,
            current_exposure,
            available_cash,
            remaining_turnover_after,
        )
        if any(value is None or value < 0 for value in monetary_values):
            blockers.append("controlled_session_budget_projection_invalid")
        if order_count is None or order_count_capacity is None:
            blockers.append("controlled_session_order_count_projection_invalid")
        elif order_count > order_count_capacity:
            blockers.append("controlled_session_order_count_projection_exceeded")
        projected_by_symbol = _decimal_map(budget.get("projected_by_symbol"))
        symbol_capacity = _decimal_map(symbol_limit_summary.get("requested_limits"))
        if symbol_limit_summary.get("status") != "pass":
            blockers.append("per_symbol_runtime_limits_not_clear")
        if (
            not projected_by_symbol
            or set(projected_by_symbol) != set(symbol_capacity)
            or any(value < 0 for value in projected_by_symbol.values())
            or any(value <= 0 for value in symbol_capacity.values())
        ):
            blockers.append("per_symbol_runtime_budget_invalid")
        for symbol, projected in projected_by_symbol.items():
            if projected > symbol_capacity.get(symbol, Decimal("0")):
                blockers.append(f"per_symbol_runtime_budget_exceeded:{symbol}")

        requested_start_at = _parse_timestamp(envelope.get("requested_start_at"))
        requested_expires_at = _parse_timestamp(envelope.get("requested_expires_at"))
        if requested_start_at is None or requested_expires_at is None:
            blockers.append("controlled_session_reservation_window_invalid")
        elif requested_expires_at <= now:
            blockers.append("controlled_session_reservation_window_expired")

        authorization_id = str(capital.get("authorization_id") or "")
        policy_version = str(capital.get("policy_version") or "")
        account_alias = str(scope.get("account_alias") or "")
        strategy_id = str(scope.get("strategy_id") or "")
        capital_input_fingerprint = str(capital.get("input_fingerprint") or "")
        envelope_fingerprint = str(attestation.get("envelope_fingerprint") or "")
        if not authorization_id or not policy_version:
            blockers.append("controlled_session_capital_authorization_scope_missing")
        if not account_alias or not strategy_id:
            blockers.append("controlled_session_account_strategy_scope_missing")
        if not _FINGERPRINT_PATTERN.fullmatch(capital_input_fingerprint):
            blockers.append("controlled_session_capital_evaluation_fingerprint_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(envelope_fingerprint):
            blockers.append("controlled_session_envelope_fingerprint_invalid")

        safe_gross = gross or Decimal("0")
        safe_buy = buy or Decimal("0")
        capital_capacity = max(
            Decimal("0"),
            (effective_capital or Decimal("0")) - (current_exposure or Decimal("0")),
        )
        turnover_capacity = max(
            Decimal("0"),
            (remaining_turnover_after or Decimal("0")) + safe_gross,
        )
        trading_day = (
            requested_start_at.astimezone(ZoneInfo(CONTROLLED_SESSION_TRADING_TIMEZONE))
            .date()
            .isoformat()
            if requested_start_at is not None
            else ""
        )
        reservation_core = {
            "schema_version": CONTROLLED_SESSION_BUDGET_RESERVATION_SCHEMA_VERSION,
            "attestation_id": normalized,
            "envelope_fingerprint": envelope_fingerprint,
            "capital_evaluation_input_fingerprint": capital_input_fingerprint,
            "authorization_id": authorization_id,
            "policy_version": policy_version,
            "account_alias": account_alias,
            "strategy_id": strategy_id,
            "trading_day": trading_day,
            "requested_start_at": (
                requested_start_at.isoformat() if requested_start_at else ""
            ),
            "requested_expires_at": (
                requested_expires_at.isoformat() if requested_expires_at else ""
            ),
            "reserved_budget": {
                "gross_order_value": _decimal_string(safe_gross),
                "buy_value": _decimal_string(safe_buy),
                "daily_turnover_value": _decimal_string(safe_gross),
                "order_count": order_count or 0,
                "by_symbol": {
                    symbol: _decimal_string(value)
                    for symbol, value in sorted(projected_by_symbol.items())
                },
            },
            "reservation_capacity": {
                "capital_value": _decimal_string(capital_capacity),
                "cash_value": _decimal_string(available_cash or Decimal("0")),
                "daily_turnover_value": _decimal_string(turnover_capacity),
                "order_count": order_count_capacity or 0,
                "by_symbol": {
                    symbol: _decimal_string(value)
                    for symbol, value in sorted(symbol_capacity.items())
                },
            },
            "money_unit_scale": CONTROLLED_SESSION_MONEY_UNIT_SCALE,
            "money_rounding": "round_ceiling",
        }
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **reservation_core,
            "reservation_fingerprint": _fingerprint(reservation_core),
            "generated_at": now.isoformat(),
            "review_status": (
                "ready_for_atomic_reservation" if not unique_blockers else "blocked"
            ),
            "review_ready": not unique_blockers,
            "blockers": unique_blockers,
            "availability_status": "evaluated_atomically_on_record",
            "runtime_session_status": "not_issued",
            "budget_reserved": False,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(reserves_budget=False),
        }

    def record(
        self,
        *,
        attestation_id: str,
        reservation_fingerprint: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview(attestation_id=attestation_id)
        rejection_reasons: list[str] = []
        if reservation_fingerprint != preview["reservation_fingerprint"]:
            rejection_reasons.append("budget_reservation_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if preview["blockers"]:
            rejection_reasons.append("budget_reservation_review_blocked")
        if rejection_reasons:
            evidence = self._record_rejection(
                preview=preview,
                submitted_reservation_fingerprint=reservation_fingerprint,
                acknowledgement=acknowledgement,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise ControlledSessionBudgetReservationRejected(
                "controlled session budget reservation rejected: "
                + ", ".join(rejection_reasons),
                evidence=evidence,
            )

        now = _aware_utc(self._clock())
        reserved_budget = preview["reserved_budget"]
        capacity = preview["reservation_capacity"]
        payload = {
            **{
                key: preview[key]
                for key in (
                    "schema_version",
                    "attestation_id",
                    "envelope_fingerprint",
                    "capital_evaluation_input_fingerprint",
                    "authorization_id",
                    "policy_version",
                    "account_alias",
                    "strategy_id",
                    "trading_day",
                    "requested_start_at",
                    "requested_expires_at",
                    "reserved_budget",
                    "reservation_capacity",
                    "money_unit_scale",
                    "money_rounding",
                    "reservation_fingerprint",
                )
            },
            "reservation_id": preview["reservation_fingerprint"],
            "status": "reserved",
            "budget_reserved": True,
            "cleared_hard_submission_blockers": [
                "atomic_budget_reservation_not_implemented"
            ],
            "runtime_session_status": "not_issued",
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(reserves_budget=True),
        }
        transaction = self._db.reserve_controlled_session_budget_sync(
            reservation={
                **{
                    key: payload[key]
                    for key in (
                        "reservation_id",
                        "attestation_id",
                        "envelope_fingerprint",
                        "capital_evaluation_input_fingerprint",
                        "authorization_id",
                        "policy_version",
                        "account_alias",
                        "strategy_id",
                        "trading_day",
                        "requested_start_at",
                        "requested_expires_at",
                    )
                },
                "reserved_gross_units": _money_units(
                    reserved_budget["gross_order_value"]
                ),
                "reserved_buy_units": _money_units(reserved_budget["buy_value"]),
                "reserved_turnover_units": _money_units(
                    reserved_budget["daily_turnover_value"]
                ),
                "reserved_order_count": int(reserved_budget["order_count"]),
                "capital_capacity_units": _capacity_units(capacity["capital_value"]),
                "cash_capacity_units": _capacity_units(capacity["cash_value"]),
                "turnover_capacity_units": _capacity_units(
                    capacity["daily_turnover_value"]
                ),
                "order_count_capacity": int(capacity["order_count"]),
                "reserved_by_symbol_units": {
                    symbol: _money_units(value)
                    for symbol, value in reserved_budget["by_symbol"].items()
                },
                "symbol_capacity_units": {
                    symbol: _capacity_units(value)
                    for symbol, value in capacity["by_symbol"].items()
                },
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") != "reserved":
            evidence = self._record_rejection(
                preview=preview,
                submitted_reservation_fingerprint=reservation_fingerprint,
                acknowledgement=acknowledgement,
                rejection_reasons=["atomic_budget_reservation_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
                transaction=transaction,
            )
            raise ControlledSessionBudgetReservationRejected(
                "controlled session budget reservation rejected atomically",
                evidence=evidence,
            )
        return _reservation_response(
            transaction.get("reservation") or {},
            reused=bool(transaction.get("reused")),
            aggregate_before=transaction.get("aggregate_before") or {},
            aggregate_after=transaction.get("aggregate_after") or {},
        )

    def list_reservations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_session_budget_reservations_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [_reservation_response(row, reused=False) for row in rows]

    def resolve(self, reservation_id: str) -> dict[str, Any]:
        normalized = str(reservation_id or "").strip().lower()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            return _blocked_resolution(
                normalized,
                ["controlled_session_budget_reservation_id_invalid"],
            )
        row = self._db.get_controlled_session_budget_reservation_sync(normalized)
        if row is None:
            return _blocked_resolution(
                normalized,
                ["controlled_session_budget_reservation_not_found"],
            )
        response = _reservation_response(row, reused=False)
        expires_at = _parse_timestamp(response.get("requested_expires_at"))
        now = _aware_utc(self._clock())
        blockers: list[str] = []
        if expires_at is None or now >= expires_at:
            blockers.append("controlled_session_budget_reservation_expired")
        if not callable(self._attestation_provider):
            blockers.append("controlled_session_attestation_provider_unavailable")
        else:
            try:
                attestation = self._attestation_provider(
                    str(response.get("attestation_id") or "")
                )
            except Exception:
                attestation = {}
                blockers.append("controlled_session_attestation_provider_failed")
            if not isinstance(attestation, dict) or attestation.get("status") != (
                "current_verified_non_executing"
            ):
                blockers.append("controlled_session_attestation_not_current")
        if blockers:
            return {
                **response,
                "resolution_status": "blocked",
                "blockers": list(dict.fromkeys(blockers)),
                "authorizes_execution": False,
            }
        return {
            **response,
            "resolution_status": "current_reserved_non_executing",
            "blockers": [],
            "authorizes_execution": False,
        }

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_reservation_fingerprint: str,
        acknowledgement: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
        transaction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SESSION_BUDGET_RESERVATION_SCHEMA_VERSION,
            "status": "rejected",
            "attestation_id": str(preview.get("attestation_id") or ""),
            "reservation_fingerprint": str(
                preview.get("reservation_fingerprint") or ""
            ),
            "submitted_reservation_fingerprint": str(
                submitted_reservation_fingerprint or ""
            ),
            "acknowledgement": acknowledgement,
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "aggregate_before": (transaction or {}).get("aggregate_before") or {},
            "aggregate_after": (transaction or {}).get("aggregate_after") or {},
            "runtime_session_status": "not_issued",
            "budget_reserved": False,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(reserves_budget=False),
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_BUDGET_RESERVATION_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_BUDGET_RESERVATION_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_SESSION_BUDGET_RESERVATION_EVENT_SOURCE,
            source_ref=str(preview.get("reservation_fingerprint") or ""),
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            "attempt_id": attempt_id,
            **payload,
        }


def _reservation_response(
    row: dict[str, Any],
    *,
    reused: bool,
    aggregate_before: dict[str, Any] | None = None,
    aggregate_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "persisted": True,
        "reused": reused,
        "created_at": str(row.get("created_at") or ""),
        "aggregate_before": aggregate_before or {},
        "aggregate_after": aggregate_after or {},
    }


def _blocked_resolution(reservation_id: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_SESSION_BUDGET_RESERVATION_SCHEMA_VERSION,
        "reservation_id": reservation_id,
        "resolution_status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_session_status": "not_issued",
        "budget_reserved": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "safety": _safety_flags(reserves_budget=False),
    }


def _money_units(value: Any) -> int:
    parsed = _decimal(value)
    if parsed is None or parsed < 0:
        return 0
    return int(
        (parsed * Decimal(CONTROLLED_SESSION_MONEY_UNIT_SCALE)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def _capacity_units(value: Any) -> int:
    parsed = _decimal(value)
    if parsed is None or parsed < 0:
        return 0
    return int(
        (parsed * Decimal(CONTROLLED_SESSION_MONEY_UNIT_SCALE)).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_map(value: Any) -> dict[str, Decimal]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Decimal] = {}
    for key, item in value.items():
        parsed = _decimal(item)
        if parsed is None:
            return {}
        result[str(key)] = parsed
    return result


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safety_flags(*, reserves_budget: bool) -> dict[str, bool]:
    return {
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_or_enable_runtime_session": True,
        "does_reserve_bounded_budget": reserves_budget,
        "does_not_auto_resume_renew_or_expand": True,
        "does_not_grant_or_scale_capital_authority": True,
    }
