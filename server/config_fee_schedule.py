"""Broker fee schedule parsing and normalization."""

from __future__ import annotations

from decimal import Decimal

from server.config_safety import contains_sensitive_config_key
from server.config_types import BrokerFeeScheduleConfig

_BROKER_FEE_SCHEDULE_ALLOWED_FIELDS = frozenset(
    {
        "schedule_id",
        "profile_id",
        "account_profile_id",
        "broker_name",
        "display_name",
        "schema_version",
        "source",
        "source_type",
        "currency",
        "effective_from",
        "captured_at",
        "precedence",
        "rounding",
        "rule_application",
        "rules",
        "broker_absorbed_components",
        "account_identifier_saved",
        "screenshots_saved",
        "private_exports_saved",
        "commission",
        "taxes_and_fees",
        "stock_a_commission_rate",
        "stock_a_min_commission",
        "fund_etf_commission_rate",
        "fund_etf_min_commission",
        "stamp_tax_rate",
        "transfer_fee_rate",
        "fund_etf_transfer_fee_rate",
        "exchange_transfer_fee_rates",
        "other_fee_rate",
        "limitations",
    }
)
_EXCHANGE_ALIASES = {
    "sh": "shanghai",
    "sse": "shanghai",
    "shanghai": "shanghai",
    "上海": "shanghai",
    "沪": "shanghai",
    "sz": "shenzhen",
    "szse": "shenzhen",
    "shenzhen": "shenzhen",
    "深圳": "shenzhen",
    "深": "shenzhen",
}


def parse_broker_fee_schedule_config(value: object) -> BrokerFeeScheduleConfig:
    if value is None:
        return BrokerFeeScheduleConfig()
    if not isinstance(value, dict):
        raise ValueError("broker fee schedule config must be an object")
    if contains_sensitive_config_key(value):
        raise ValueError(
            "broker fee schedule config must not contain password, secret, "
            "token, or credential fields"
        )
    if any(
        bool(value.get(flag))
        for flag in (
            "account_identifier_saved",
            "screenshots_saved",
            "private_exports_saved",
        )
    ):
        raise ValueError(
            "broker fee schedule config must not store account identifiers, "
            "screenshots, or private exports"
        )
    unknown_fields = sorted(set(value) - _BROKER_FEE_SCHEDULE_ALLOWED_FIELDS)
    if unknown_fields:
        raise ValueError(
            "broker fee schedule config contains unsupported fields: "
            + ", ".join(unknown_fields)
        )

    limitations = value.get(
        "limitations",
        BrokerFeeScheduleConfig.__dataclass_fields__["limitations"].default,
    )
    if not isinstance(limitations, list | tuple):
        raise ValueError("broker fee schedule limitations must be a list")
    exchange_transfer_fee_rates = _exchange_transfer_fee_rates(value)
    money_precision, money_rounding_mode = _broker_fee_rounding(value.get("rounding"))
    limitation_values = [str(item).strip() for item in limitations if str(item).strip()]
    if exchange_transfer_fee_rates:
        limitation_values = [
            item
            for item in limitation_values
            if item != "transfer_fee_exchange_not_split"
        ]
    if _has_nested_broker_fee_schedule(value):
        limitation_values.append("nested_fee_schedule_flattened_for_current_contract")

    transfer_fee_rate = _decimal_fee_config(
        value,
        "transfer_fee_rate",
        _rule_fee_value(
            value,
            component="transfer_fee",
            asset_classes=("stock",),
            field_name="rate",
            default=_nested_fee_value(
                value,
                section="taxes_and_fees",
                names=("transfer_fee", "stock_transfer_fee"),
                default="0.00001",
            ),
        ),
    )
    fund_etf_transfer_fee_rate = _decimal_fee_config(
        value,
        "fund_etf_transfer_fee_rate",
        _rule_fee_value(
            value,
            component="transfer_fee",
            asset_classes=("fund", "etf"),
            field_name="rate",
            default=_nested_fee_value(
                value,
                section="taxes_and_fees",
                names=(
                    "fund_etf_transfer_fee",
                    "etf_transfer_fee",
                    "fund_transfer_fee",
                ),
                default=transfer_fee_rate,
            ),
        ),
    )

    return BrokerFeeScheduleConfig(
        schedule_id=str(_fee_schedule_id(value)).strip()
        or BrokerFeeScheduleConfig().schedule_id,
        account_profile_id=str(value.get("account_profile_id", "")).strip(),
        broker_name=str(value.get("broker_name", "")).strip(),
        stock_a_commission_rate=_decimal_fee_config(
            value,
            "stock_a_commission_rate",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("stock",),
                field_name="rate",
                default=_nested_fee_value(
                    value,
                    section="commission",
                    names=("stock_a", "stock", "a_share", "ashare"),
                    default="0.0001",
                ),
            ),
        ),
        stock_a_min_commission=_decimal_fee_config(
            value,
            "stock_a_min_commission",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("stock",),
                field_name="min_fee",
                default="5",
            ),
        ),
        fund_etf_commission_rate=_decimal_fee_config(
            value,
            "fund_etf_commission_rate",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("fund", "etf"),
                field_name="rate",
                default=_nested_fee_value(
                    value,
                    section="commission",
                    names=("fund_etf", "etf", "fund"),
                    default="0.0001",
                ),
            ),
        ),
        fund_etf_min_commission=_decimal_fee_config(
            value,
            "fund_etf_min_commission",
            _rule_fee_value(
                value,
                component="commission",
                asset_classes=("fund", "etf"),
                field_name="min_fee",
                default="5",
            ),
        ),
        stamp_tax_rate=_decimal_fee_config(
            value,
            "stamp_tax_rate",
            _rule_fee_value(
                value,
                component="stamp_tax",
                asset_classes=("stock",),
                field_name="rate",
                side="sell",
                default=_nested_fee_value(
                    value,
                    section="taxes_and_fees",
                    names=("stamp_tax", "stamp", "stock_stamp_tax"),
                    default="0.0005",
                ),
            ),
        ),
        transfer_fee_rate=transfer_fee_rate,
        fund_etf_transfer_fee_rate=fund_etf_transfer_fee_rate,
        exchange_transfer_fee_rates=exchange_transfer_fee_rates,
        other_fee_rate=_decimal_fee_config(
            value,
            "other_fee_rate",
            _nested_fee_value(
                value,
                section="taxes_and_fees",
                names=("other_fee", "other_fees"),
                default="0",
            ),
        ),
        money_precision=money_precision,
        money_rounding_mode=money_rounding_mode,
        limitations=tuple(dict.fromkeys(limitation_values)),
    )


def _broker_fee_rounding(value: object) -> tuple[Decimal | None, str]:
    if value is None:
        return None, "none"
    if not isinstance(value, dict):
        raise ValueError("broker fee schedule rounding must be an object")
    unknown_fields = sorted(set(value) - {"money_precision", "mode"})
    if unknown_fields:
        raise ValueError(
            "broker fee schedule rounding contains unsupported fields: "
            + ", ".join(unknown_fields)
        )
    precision = Decimal(str(value.get("money_precision", "0.01")))
    if precision <= 0:
        raise ValueError("broker fee schedule money_precision must be positive")
    mode = str(value.get("mode", "half_up")).strip().lower()
    if mode not in {"half_up", "half_even", "down", "up"}:
        raise ValueError(
            "broker fee schedule rounding mode must be one of: "
            "half_up, half_even, down, up"
        )
    return precision, mode


def _decimal_fee_config(
    value: dict[str, object], field_name: str, default: object
) -> Decimal:
    raw_value = value.get(field_name, default)
    return Decimal(str(raw_value))


def _fee_schedule_id(value: dict[str, object]) -> object:
    return value.get(
        "schedule_id",
        value.get(
            "profile_id",
            value.get("source", BrokerFeeScheduleConfig().schedule_id),
        ),
    )


def _has_nested_broker_fee_schedule(value: dict[str, object]) -> bool:
    return any(
        isinstance(value.get(section), dict)
        for section in ("commission", "taxes_and_fees")
    ) or isinstance(value.get("rules"), list)


def _nested_fee_value(
    value: dict[str, object],
    *,
    section: str,
    names: tuple[str, ...],
    default: object,
) -> object:
    section_value = value.get(section)
    if not isinstance(section_value, dict):
        return default
    for name in names:
        if name in section_value:
            return _first_decimal_like(section_value[name], default=default)
    return default


def _rule_fee_value(
    value: dict[str, object],
    *,
    component: str,
    asset_classes: tuple[str, ...],
    field_name: str,
    default: object,
    side: str | None = None,
) -> object:
    rules = value.get("rules")
    if not isinstance(rules, list):
        return default
    for raw_rule in rules:
        if not isinstance(raw_rule, dict):
            continue
        if str(raw_rule.get("component", "")).strip().lower() != component:
            continue
        if not _rule_has_any(raw_rule.get("asset_classes"), asset_classes):
            continue
        if side is not None and not _rule_side_matches(raw_rule.get("side"), side):
            continue
        raw_value = raw_rule.get(field_name)
        if raw_value is not None:
            return raw_value
    return default


def _rule_has_any(value: object, expected: tuple[str, ...]) -> bool:
    expected_values = {item.strip().lower() for item in expected}
    if isinstance(value, list | tuple):
        return any(str(item).strip().lower() in expected_values for item in value)
    return str(value).strip().lower() in expected_values


def _rule_side_matches(value: object, expected: str) -> bool:
    side = str(value or "both").strip().lower()
    return side in {expected, "both", "all"}


def _exchange_transfer_fee_rates(value: dict[str, object]) -> dict[str, Decimal]:
    direct_value = value.get("exchange_transfer_fee_rates")
    raw_rates: dict[str, object] = {}
    if isinstance(direct_value, dict):
        raw_rates.update(direct_value)

    taxes_and_fees = value.get("taxes_and_fees")
    if isinstance(taxes_and_fees, dict):
        transfer_fee = taxes_and_fees.get("transfer_fee")
        if isinstance(transfer_fee, dict):
            for raw_key, raw_value in transfer_fee.items():
                exchange = _normalize_exchange_key(raw_key)
                if exchange:
                    raw_rates.setdefault(exchange, raw_value)

    rules = value.get("rules")
    if isinstance(rules, list):
        for raw_rule in rules:
            if not isinstance(raw_rule, dict):
                continue
            if str(raw_rule.get("component", "")).strip().lower() != "transfer_fee":
                continue
            raw_rate = raw_rule.get("rate")
            if raw_rate is None:
                continue
            markets = raw_rule.get("markets")
            if not isinstance(markets, list | tuple):
                markets = [markets]
            for market in markets:
                exchange = _normalize_exchange_key(market)
                if exchange:
                    raw_rates.setdefault(exchange, raw_rate)

    parsed: dict[str, Decimal] = {}
    for raw_key, raw_value in raw_rates.items():
        exchange = _normalize_exchange_key(raw_key)
        if exchange:
            parsed[exchange] = Decimal(str(raw_value))
    return parsed


def _normalize_exchange_key(value: object) -> str | None:
    key = str(value).strip().lower()
    if not key or key in {"rate", "sell", "buy", "value", "default"}:
        return None
    return _EXCHANGE_ALIASES.get(key)


def _first_decimal_like(value: object, *, default: object) -> object:
    if isinstance(value, int | float | str | Decimal):
        return value
    if isinstance(value, dict):
        for key in ("rate", "sell", "sh", "sz", "value"):
            if key in value:
                return _first_decimal_like(value[key], default=default)
