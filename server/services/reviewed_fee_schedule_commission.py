"""Evidence-bounded commission resolution for reviewed fee schedules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from core.types import CommissionType, OrderSide
from execution.commission import (
    CommissionCalculator,
    ETFCommission,
    FeeBreakdown,
    MultiAssetCommission,
    StockACommission,
)
from server.contracts.reviewed_fee_schedule import (
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReview,
)
from server.services.reviewed_fee_schedule_policy import (
    NOTIONAL_ENVELOPE_SCHEMA_VERSION,
    REVIEWED_COST_MODEL_PREFIX,
    REVIEWED_FEE_SCHEDULE_RESOLUTION_SCHEMA_VERSION,
    ROUNDING_MODES,
    SHA256_PATTERN,
    SUPPORTED_ASSET_CLASSES,
    decimal_value,
    fingerprint_payload,
    mapping_payload,
    normalize_asset_class,
    reviewed_asset_classes_from_preview,
)


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
        self._rounding = ROUNDING_MODES[rounding_mode]

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
            "reviewed_asset_classes": list(
                reviewed_asset_classes_from_preview(self.review.preview)
            ),
            "broker_statement_reconciled": True,
            "persisted_review_only": True,
            "provider_contacted": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }


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


def validated_notional_envelope(value: Any) -> tuple[dict[str, Decimal], str]:
    envelope = mapping_payload(value)
    if envelope.get("schema_version") != NOTIONAL_ENVELOPE_SCHEMA_VERSION:
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_schema_invalid"
        )
    fingerprint = str(envelope.pop("evidence_fingerprint", ""))
    if not SHA256_PATTERN.fullmatch(fingerprint) or fingerprint != fingerprint_payload(
        envelope
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_fingerprint_invalid"
        )
    if envelope.get("enforcement_mode") != (
        "maximum_matched_historical_gross_by_asset_class"
    ):
        raise ReviewedFeeScheduleRejected(
            "reviewed_fee_schedule_notional_envelope_mode_invalid"
        )
    raw_limits = mapping_payload(envelope.get("limits"))
    limits: dict[str, Decimal] = {}
    for asset_class, raw_limit in raw_limits.items():
        normalized_asset_class = normalize_asset_class(asset_class)
        terms = mapping_payload(raw_limit)
        maximum = decimal_value(terms.get("maximum_gross_amount"))
        try:
            matched_trade_count = int(terms.get("matched_trade_count") or 0)
        except (TypeError, ValueError):
            matched_trade_count = 0
        if (
            normalized_asset_class not in SUPPORTED_ASSET_CLASSES
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


def build_commission_calculator(
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
        for key, value in mapping_payload(
            schedule.get("exchange_transfer_fee_rates")
        ).items()
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


__all__ = [
    "ReviewedFeeScheduleResolution",
    "build_commission_calculator",
    "is_reviewed_cost_model_reference",
    "reviewed_cost_model_reference",
    "validated_notional_envelope",
]
