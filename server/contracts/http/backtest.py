"""Shared backtest HTTP contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from core.types import AssetClass, BarFrequency


class StrategyInfoResponse(BaseModel):
    registry_contract_version: str = "karkinos.strategy_registry.v1"
    schema_version: str = "karkinos.strategy.v1"
    strategy_id: str
    name: str
    display_name: str
    description: str
    source_type: str = "builtin"
    is_extension: bool = False
    params: list[dict[str, Any]]
    parameter_schema: list[dict[str, Any]]
    asset_universe: list[str] = Field(default_factory=list)
    supported_frequencies: list[str] = Field(default_factory=list)
    benchmark_role: str | None = None
    benchmark_universe: list[str] = Field(default_factory=list)
    requires_out_of_sample_validation: bool = False
    requires_after_cost_report: bool = False
    validation_notes: list[str] = Field(default_factory=list)
    execution_boundary: dict[str, Any] = Field(default_factory=dict)


class StrategyValidationRowResponse(BaseModel):
    strategy_id: str
    benchmark_role: str
    requires_out_of_sample_validation: bool
    requires_after_cost_report: bool
    has_out_of_sample_validation: bool
    has_after_cost_report: bool
    validation_status: str | None = None
    backtest_result_id: int | None = None
    missing_requirements: list[str] = Field(default_factory=list)
    is_ready: bool


class StrategyValidationMatrixResponse(BaseModel):
    required_strategy_count: int
    ready_strategy_count: int
    is_complete: bool
    rows: list[StrategyValidationRowResponse]
    limitations: list[str] = Field(default_factory=list)


class StrategyPromotionReadinessRowResponse(BaseModel):
    strategy_id: str
    benchmark_role: str
    backtest_result_id: int | None = None
    has_after_cost_and_oos_evidence: bool
    has_risk_block_evidence: bool
    has_paper_shadow_evidence: bool
    has_paper_shadow_divergence_review: bool
    has_account_truth_evidence: bool = True
    account_truth_gate_status: str = "not_evaluated"
    account_truth_score: int | None = None
    has_strategy_attribution_evidence: bool = True
    strategy_attribution_status: str = "not_evaluated"
    missing_requirements: list[str] = Field(default_factory=list)
    promotion_status: str
    is_promotable: bool


class StrategyPromotionReadinessResponse(BaseModel):
    required_strategy_count: int
    promotable_strategy_count: int
    is_complete: bool
    rows: list[StrategyPromotionReadinessRowResponse]
    limitations: list[str] = Field(default_factory=list)


class StrategySignalPreviewBar(BaseModel):
    timestamp: datetime
    close: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal = Decimal("0")
    frequency: str = BarFrequency.DAILY.value
    data_status: str = "confirmed"


class StrategySignalPreviewRequest(BaseModel):
    strategy: str = "dual_ma"
    symbol: str
    asset_class: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    params: dict[str, Any] | None = None
    bars: list[StrategySignalPreviewBar] = Field(default_factory=list)
    dataset_snapshot: dict[str, Any] = Field(default_factory=dict)


class StrategySignalPreviewResponse(BaseModel):
    schema_version: str
    strategy_id: str
    symbol: str
    params: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    dataset_snapshot_id: str | None = None
    record_count: int
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    does_not_enable_execution: bool = True


class BacktestRiskPreviewRequest(BaseModel):
    strategy: str
    symbol: str
    asset_class: str = AssetClass.STOCK.value
    action: str
    quantity: Decimal = Field(gt=Decimal("0"))
    reference_price: Decimal = Field(gt=Decimal("0"))
    target_weight: Decimal = Decimal("0")
    data_quality_status: str = "pass"


class BacktestPaperShadowPreviewRequest(BaseModel):
    strategy: str
    symbol: str
    asset_class: str = AssetClass.STOCK.value
    action: str
    quantity: Decimal = Field(gt=Decimal("0"))
    reference_price: Decimal = Field(gt=Decimal("0"))
    target_weight: Decimal = Decimal("0")
    signal_id: str | None = None
    dataset_snapshot_id: str | None = None
    risk_preview_passed: bool = False
    risk_reasons: list[str] = Field(default_factory=list)


class BacktestAttributionPreviewRequest(BaseModel):
    strategy: str
    symbol: str
    asset_class: str = AssetClass.STOCK.value
    signal_id: str | None = None
    dataset_snapshot_id: str | None = None
    risk_preview_passed: bool = False
    risk_reasons: list[str] = Field(default_factory=list)
    paper_shadow_status: str | None = None
    paper_shadow_order: dict[str, Any] | None = None
    paper_shadow_fill: dict[str, Any] | None = None


__all__ = (
    "BacktestAttributionPreviewRequest",
    "BacktestPaperShadowPreviewRequest",
    "BacktestRiskPreviewRequest",
    "StrategyInfoResponse",
    "StrategyPromotionReadinessResponse",
    "StrategyPromotionReadinessRowResponse",
    "StrategySignalPreviewBar",
    "StrategySignalPreviewRequest",
    "StrategySignalPreviewResponse",
    "StrategyValidationMatrixResponse",
    "StrategyValidationRowResponse",
)
