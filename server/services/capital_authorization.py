"""Pure, non-submitting capital-authorization policy evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

CAPITAL_AUTHORIZATION_SCHEMA_VERSION = "karkinos.capital_authorization.v2"
CAPITAL_AUTHORIZATION_DECISION_SCHEMA_VERSION = (
    "karkinos.capital_authorization_decision.v1"
)
CAPITAL_AUTHORIZATION_MODES = (
    "disabled",
    "manual_each_order",
    "session_bounded",
)

_CURRENT_MARKET_DATA_STATUSES = frozenset({"confirmed", "live"})
_CLEAR_PAPER_SHADOW_STATUSES = frozenset({"within_expectations", "manually_accepted"})
_CLEAR_RECONCILIATION_STATUSES = frozenset({"clear", "manually_accepted"})


@dataclass(frozen=True)
class CapitalAuthorizationLimits:
    """Hard upper bounds attached to one operator authorization."""

    max_authorized_capital: Decimal = Decimal("0")
    max_order_value: Decimal = Decimal("0")
    max_position_change_value: Decimal = Decimal("0")
    max_daily_turnover: Decimal = Decimal("0")
    max_daily_loss: Decimal = Decimal("0")
    max_drawdown_pct: Decimal = Decimal("0")
    max_order_rate_per_minute: int = 0
    max_consecutive_errors: int = 0


@dataclass(frozen=True)
class CapitalAuthorizationPolicy:
    """Versioned, expiring authority explicitly issued by an operator."""

    authorization_id: str = ""
    policy_version: str = ""
    mode: str = "disabled"
    enabled: bool = False
    authorized_by: str = ""
    # Legacy display scope only. v2 authority is split between the two fields below.
    connector_ids: tuple[str, ...] = ()
    evidence_connector_ids: tuple[str, ...] = ()
    execution_gateway_ids: tuple[str, ...] = ()
    account_aliases: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    limits: CapitalAuthorizationLimits = field(
        default_factory=CapitalAuthorizationLimits
    )
    evidence_refs: tuple[str, ...] = ()
    schema_version: str = CAPITAL_AUTHORIZATION_SCHEMA_VERSION


@dataclass(frozen=True)
class CapitalAuthorizationContext:
    """Current facts used to evaluate one proposed order without side effects."""

    now: datetime
    connector_id: str
    account_alias: str
    strategy_id: str
    symbol: str
    order_value: Decimal
    position_change_value: Decimal
    current_authorized_exposure: Decimal
    daily_turnover_used: Decimal
    current_daily_loss: Decimal
    current_drawdown_pct: Decimal
    order_rate_per_minute: int
    consecutive_errors: int
    available_cash: Decimal
    account_capital_limit: Decimal
    strategy_capital_limit: Decimal
    symbol_capital_limit: Decimal
    liquidity_capital_limit: Decimal
    market_data_status: str
    account_truth_status: str
    risk_gate_status: str
    paper_shadow_status: str
    reconciliation_status: str
    connector_health_status: str
    connector_can_submit: bool
    kill_switch_enabled: bool
    order_fingerprint: str = ""
    manual_confirmation_fingerprint: str = ""
    evidence_refs: tuple[str, ...] = ()
    evidence_connector_id: str = ""
    execution_gateway_id: str = ""
    evidence_connector_health_status: str = ""
    evidence_connector_can_submit: bool = False
    execution_gateway_health_status: str = ""
    execution_gateway_can_submit: bool = False
    connector_account_binding_status: str = ""


@dataclass(frozen=True)
class CapitalAuthorizationDecision:
    """Immutable evaluation evidence; never a broker command."""

    allowed: bool
    mode: str
    authorization_id: str
    policy_version: str
    blocked_reasons: tuple[str, ...]
    effective_limits: tuple[tuple[str, str], ...]
    remaining_budget: tuple[tuple[str, str], ...]
    evidence_refs: tuple[str, ...]
    input_fingerprint: str
    schema_version: str = CAPITAL_AUTHORIZATION_DECISION_SCHEMA_VERSION
    does_not_submit_broker_order: bool = True
    does_not_cancel_broker_order: bool = True
    does_not_mutate_oms: bool = True
    does_not_mutate_production_ledger: bool = True
    does_not_enable_or_expand_authority: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a stable API-ready representation of this read-only evidence."""

        return {
            "schema_version": self.schema_version,
            "allowed": self.allowed,
            "mode": self.mode,
            "authorization_id": self.authorization_id,
            "policy_version": self.policy_version,
            "blocked_reasons": list(self.blocked_reasons),
            "effective_limits": dict(self.effective_limits),
            "remaining_budget": dict(self.remaining_budget),
            "evidence_refs": list(self.evidence_refs),
            "input_fingerprint": self.input_fingerprint,
            "safety": {
                "does_not_submit_broker_order": self.does_not_submit_broker_order,
                "does_not_cancel_broker_order": self.does_not_cancel_broker_order,
                "does_not_mutate_oms": self.does_not_mutate_oms,
                "does_not_mutate_production_ledger": (
                    self.does_not_mutate_production_ledger
                ),
                "does_not_enable_or_expand_authority": (
                    self.does_not_enable_or_expand_authority
                ),
            },
        }


def evaluate_capital_authorization(
    policy: CapitalAuthorizationPolicy,
    context: CapitalAuthorizationContext,
) -> CapitalAuthorizationDecision:
    """Fail closed while evaluating bounded authority for one proposed order."""

    blocked: list[str] = []
    mode = str(policy.mode or "disabled")
    supported_mode = mode in CAPITAL_AUTHORIZATION_MODES

    if policy.schema_version != CAPITAL_AUTHORIZATION_SCHEMA_VERSION:
        blocked.append("unsupported_schema_version")
    if not supported_mode:
        blocked.append("unsupported_authorization_mode")
    if not policy.enabled:
        blocked.append("authorization_disabled")
    if mode == "disabled":
        blocked.append("authorization_mode_disabled")

    active = policy.enabled and supported_mode and mode != "disabled"
    effective_capital = Decimal("0")
    remaining: dict[str, Decimal | int] = {}

    if active:
        _validate_identity_and_time(policy, context, blocked)
        _validate_scope(policy, context, blocked)
        _validate_evidence_gates(context, blocked)
        _validate_order_confirmation(policy, context, blocked)
        effective_capital = _validate_limits(policy, context, blocked)
        remaining = _remaining_budget(policy, context, effective_capital)

    effective_limits = _effective_limits(policy, context, effective_capital)
    return CapitalAuthorizationDecision(
        allowed=not blocked,
        mode=mode,
        authorization_id=policy.authorization_id,
        policy_version=policy.policy_version,
        blocked_reasons=tuple(blocked),
        effective_limits=tuple(effective_limits.items()),
        remaining_budget=tuple(
            (key, _decimal_string(value)) for key, value in remaining.items()
        ),
        evidence_refs=_dedupe((*policy.evidence_refs, *context.evidence_refs)),
        input_fingerprint=_fingerprint({"policy": policy, "context": context}),
    )


def _validate_identity_and_time(
    policy: CapitalAuthorizationPolicy,
    context: CapitalAuthorizationContext,
    blocked: list[str],
) -> None:
    if not policy.authorization_id.strip():
        blocked.append("missing_authorization_id")
    if not policy.policy_version.strip():
        blocked.append("missing_policy_version")
    if not policy.authorized_by.strip():
        blocked.append("missing_authorized_by")

    timestamps = (policy.effective_at, policy.expires_at, context.now)
    if any(value is None or not _is_timezone_aware(value) for value in timestamps):
        blocked.append("invalid_authorization_time")
        return

    assert policy.effective_at is not None
    assert policy.expires_at is not None
    if policy.effective_at >= policy.expires_at:
        blocked.append("invalid_authorization_window")
        return
    if context.now < policy.effective_at:
        blocked.append("authorization_not_yet_effective")
    if context.now >= policy.expires_at:
        blocked.append("authorization_expired")


def _validate_scope(
    policy: CapitalAuthorizationPolicy,
    context: CapitalAuthorizationContext,
    blocked: list[str],
) -> None:
    if (
        context.evidence_connector_id
        and context.evidence_connector_id == context.execution_gateway_id
    ):
        blocked.append("connector_roles_not_separated")
    if set(policy.evidence_connector_ids) & set(policy.execution_gateway_ids):
        blocked.append("connector_role_scope_overlap")
    scopes = (
        (
            context.evidence_connector_id,
            policy.evidence_connector_ids,
            "evidence_connector_not_authorized",
        ),
        (
            context.execution_gateway_id,
            policy.execution_gateway_ids,
            "execution_gateway_not_authorized",
        ),
        (context.account_alias, policy.account_aliases, "account_not_authorized"),
        (context.strategy_id, policy.strategy_ids, "strategy_not_authorized"),
        (context.symbol, policy.symbols, "symbol_not_authorized"),
    )
    for value, allowed, reason in scopes:
        if not value or value not in allowed:
            blocked.append(reason)


def _validate_evidence_gates(
    context: CapitalAuthorizationContext,
    blocked: list[str],
) -> None:
    if context.kill_switch_enabled:
        blocked.append("kill_switch_enabled")
    if context.market_data_status not in _CURRENT_MARKET_DATA_STATUSES:
        blocked.append("market_data_not_current")
    if context.account_truth_status != "pass":
        blocked.append("account_truth_not_clear")
    if context.risk_gate_status != "passed":
        blocked.append("risk_gate_not_passed")
    if context.paper_shadow_status not in _CLEAR_PAPER_SHADOW_STATUSES:
        blocked.append("paper_shadow_not_clear")
    if context.reconciliation_status not in _CLEAR_RECONCILIATION_STATUSES:
        blocked.append("reconciliation_not_clear")
    if context.evidence_connector_health_status != "healthy":
        blocked.append("evidence_connector_not_healthy")
    if context.evidence_connector_can_submit:
        blocked.append("evidence_connector_exposes_submit_capability")
    if context.execution_gateway_health_status != "healthy":
        blocked.append("execution_gateway_not_healthy")
    if not context.execution_gateway_can_submit:
        blocked.append("execution_gateway_submit_capability_unavailable")
    if context.connector_account_binding_status != "verified":
        blocked.append("connector_account_binding_not_verified")


def _validate_order_confirmation(
    policy: CapitalAuthorizationPolicy,
    context: CapitalAuthorizationContext,
    blocked: list[str],
) -> None:
    if policy.mode != "manual_each_order":
        return
    if not context.order_fingerprint:
        blocked.append("missing_order_fingerprint")
    if (
        not context.manual_confirmation_fingerprint
        or context.manual_confirmation_fingerprint != context.order_fingerprint
    ):
        blocked.append("manual_confirmation_mismatch")


def _validate_limits(
    policy: CapitalAuthorizationPolicy,
    context: CapitalAuthorizationContext,
    blocked: list[str],
) -> Decimal:
    limits = policy.limits
    decimal_limits = {
        "max_authorized_capital": limits.max_authorized_capital,
        "max_order_value": limits.max_order_value,
        "max_position_change_value": limits.max_position_change_value,
        "max_daily_turnover": limits.max_daily_turnover,
        "max_daily_loss": limits.max_daily_loss,
        "max_drawdown_pct": limits.max_drawdown_pct,
    }
    for name, value in decimal_limits.items():
        if value <= 0:
            blocked.append(f"invalid_limit:{name}")
    if limits.max_order_rate_per_minute <= 0:
        blocked.append("invalid_limit:max_order_rate_per_minute")
    if limits.max_consecutive_errors <= 0:
        blocked.append("invalid_limit:max_consecutive_errors")

    capital_facts = {
        "available_cash": context.available_cash,
        "account_capital_limit": context.account_capital_limit,
        "strategy_capital_limit": context.strategy_capital_limit,
        "symbol_capital_limit": context.symbol_capital_limit,
        "liquidity_capital_limit": context.liquidity_capital_limit,
    }
    for name, value in capital_facts.items():
        if value <= 0:
            blocked.append(f"invalid_capital_fact:{name}")

    numeric_facts = {
        "order_value": context.order_value,
        "position_change_value": context.position_change_value,
        "current_authorized_exposure": context.current_authorized_exposure,
        "daily_turnover_used": context.daily_turnover_used,
        "current_daily_loss": context.current_daily_loss,
        "current_drawdown_pct": context.current_drawdown_pct,
    }
    for name, value in numeric_facts.items():
        minimum = Decimal("0.00000001") if name == "order_value" else Decimal("0")
        if value < minimum:
            blocked.append(f"invalid_order_fact:{name}")
    if context.order_rate_per_minute < 0:
        blocked.append("invalid_order_fact:order_rate_per_minute")
    if context.consecutive_errors < 0:
        blocked.append("invalid_order_fact:consecutive_errors")

    total_exposure_constraints = [
        limits.max_authorized_capital,
        context.account_capital_limit,
        context.strategy_capital_limit,
        context.symbol_capital_limit,
    ]
    effective_capital = (
        min(total_exposure_constraints)
        if all(value > 0 for value in total_exposure_constraints)
        else Decimal("0")
    )
    order_constraints = [
        limits.max_order_value,
        context.available_cash,
        context.liquidity_capital_limit,
    ]
    effective_order_value = (
        min(order_constraints)
        if all(value > 0 for value in order_constraints)
        else Decimal("0")
    )

    if context.current_authorized_exposure + context.order_value > effective_capital:
        blocked.append("authorized_capital_exceeded")
    if context.order_value > effective_order_value:
        blocked.append("order_value_exceeded")
    if context.position_change_value > limits.max_position_change_value:
        blocked.append("position_change_exceeded")
    if context.daily_turnover_used + context.order_value > limits.max_daily_turnover:
        blocked.append("daily_turnover_exceeded")
    if context.current_daily_loss >= limits.max_daily_loss:
        blocked.append("daily_loss_limit_reached")
    if context.current_drawdown_pct >= limits.max_drawdown_pct:
        blocked.append("drawdown_limit_reached")
    if context.order_rate_per_minute >= limits.max_order_rate_per_minute:
        blocked.append("order_rate_limit_reached")
    if context.consecutive_errors >= limits.max_consecutive_errors:
        blocked.append("consecutive_error_limit_reached")
    return effective_capital


def _remaining_budget(
    policy: CapitalAuthorizationPolicy,
    context: CapitalAuthorizationContext,
    effective_capital: Decimal,
) -> dict[str, Decimal | int]:
    limits = policy.limits
    return {
        "authorized_capital_after_order": max(
            Decimal("0"),
            effective_capital
            - context.current_authorized_exposure
            - context.order_value,
        ),
        "available_cash_after_order": max(
            Decimal("0"), context.available_cash - context.order_value
        ),
        "liquidity_after_order": max(
            Decimal("0"), context.liquidity_capital_limit - context.order_value
        ),
        "daily_turnover_after_order": max(
            Decimal("0"),
            limits.max_daily_turnover
            - context.daily_turnover_used
            - context.order_value,
        ),
        "daily_loss": max(
            Decimal("0"), limits.max_daily_loss - context.current_daily_loss
        ),
        "drawdown_pct": max(
            Decimal("0"), limits.max_drawdown_pct - context.current_drawdown_pct
        ),
        "orders_per_minute": max(
            0, limits.max_order_rate_per_minute - context.order_rate_per_minute
        ),
        "consecutive_errors": max(
            0, limits.max_consecutive_errors - context.consecutive_errors
        ),
    }


def _effective_limits(
    policy: CapitalAuthorizationPolicy,
    context: CapitalAuthorizationContext,
    effective_capital: Decimal,
) -> dict[str, str]:
    limits = policy.limits
    return {
        "operator_authorized_capital": _decimal_string(limits.max_authorized_capital),
        "available_cash": _decimal_string(context.available_cash),
        "account_capital_limit": _decimal_string(context.account_capital_limit),
        "strategy_capital_limit": _decimal_string(context.strategy_capital_limit),
        "symbol_capital_limit": _decimal_string(context.symbol_capital_limit),
        "liquidity_capital_limit": _decimal_string(context.liquidity_capital_limit),
        "effective_capital": _decimal_string(effective_capital),
        "effective_order_value": _decimal_string(
            min(
                limits.max_order_value,
                context.available_cash,
                context.liquidity_capital_limit,
            )
            if (
                limits.max_order_value > 0
                and context.available_cash > 0
                and context.liquidity_capital_limit > 0
            )
            else Decimal("0")
        ),
        "max_order_value": _decimal_string(limits.max_order_value),
        "max_position_change_value": _decimal_string(limits.max_position_change_value),
        "max_daily_turnover": _decimal_string(limits.max_daily_turnover),
        "max_daily_loss": _decimal_string(limits.max_daily_loss),
        "max_drawdown_pct": _decimal_string(limits.max_drawdown_pct),
        "max_order_rate_per_minute": str(limits.max_order_rate_per_minute),
        "max_consecutive_errors": str(limits.max_consecutive_errors),
    }


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decimal_string(value: Decimal | int) -> str:
    if isinstance(value, int):
        return str(value)
    normalized = value.normalize()
    return format(normalized, "f")


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
