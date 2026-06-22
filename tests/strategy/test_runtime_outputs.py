"""Strategy runtime output normalization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.events import MarketEvent
from core.types import BarFrequency, Symbol
from strategy import (
    StrategyRuntimeContext,
    StrategyRuntimeOutput,
    StrategyRuntimeOutputType,
    StrategyRuntimeRunner,
)


def test_strategy_runtime_normalizes_hook_outputs_into_audit_records() -> None:
    context = StrategyRuntimeContext(
        strategy_id="audited_strategy",
        run_id="runtime-run-001",
        symbols=(Symbol("600000"),),
        parameters={"window": 20},
    )
    bar = MarketEvent(
        timestamp=datetime(2026, 6, 22, 9, 31, tzinfo=UTC),
        symbol=Symbol("600000"),
        open=Decimal("10.00"),
        high=Decimal("10.40"),
        low=Decimal("9.90"),
        close=Decimal("10.20"),
        volume=Decimal("1000"),
        frequency=BarFrequency.MIN_1,
    )

    result = StrategyRuntimeRunner().run_session(
        strategy=_OutputtingRuntimeStrategy(),
        context=context,
        bars=(bar,),
    )

    assert [record.output_type for record in result.outputs] == [
        StrategyRuntimeOutputType.OBSERVATION_SIGNAL,
        StrategyRuntimeOutputType.NO_ACTION,
        StrategyRuntimeOutputType.BUY_CANDIDATE,
        StrategyRuntimeOutputType.RISK_WARNING,
        StrategyRuntimeOutputType.REBALANCE_CANDIDATE,
        StrategyRuntimeOutputType.SELL_CANDIDATE,
    ]
    assert [record.output_id for record in result.outputs] == [
        "runtime-run-001:0001:observation_signal",
        "runtime-run-001:0002:no_action",
        "runtime-run-001:0003:buy_candidate",
        "runtime-run-001:0004:risk_warning",
        "runtime-run-001:0005:rebalance_candidate",
        "runtime-run-001:0006:sell_candidate",
    ]

    buy_record = result.outputs[2]
    assert buy_record.schema_version == "karkinos.strategy_runtime_output.v1"
    assert buy_record.strategy_id == "audited_strategy"
    assert buy_record.run_id == "runtime-run-001"
    assert buy_record.hook == "on_bar"
    assert buy_record.source_event_id == "600000:2026-06-22T09:31:00+00:00"
    assert buy_record.record_kind == "candidate_action"
    assert buy_record.action == "buy"
    assert buy_record.symbol == Symbol("600000")
    assert buy_record.quantity == Decimal("100")
    assert buy_record.price == Decimal("10.20")
    assert buy_record.reason == "short-term signal crossed the buy threshold"
    assert buy_record.confidence == Decimal("0.70")
    assert buy_record.evidence["indicator"] == "runtime_fixture"
    assert buy_record.requires_risk_gate is True
    assert buy_record.requires_account_truth_gate is True
    assert buy_record.requires_paper_shadow_review is True
    assert buy_record.requires_manual_review is True
    assert buy_record.does_not_enable_execution is True

    no_action_record = result.outputs[1]
    assert no_action_record.record_kind == "explanation"
    assert no_action_record.action == "no_action"
    assert no_action_record.requires_risk_gate is False
    assert no_action_record.requires_manual_review is False
    assert no_action_record.does_not_enable_execution is True

    sell_record = result.outputs[5]
    assert sell_record.record_kind == "candidate_action"
    assert sell_record.action == "sell"
    assert sell_record.requires_risk_gate is True
    assert sell_record.does_not_enable_execution is True


class _OutputtingRuntimeStrategy:
    def initialize(self, context: StrategyRuntimeContext) -> StrategyRuntimeOutput:
        return StrategyRuntimeOutput.observation_signal(
            symbol=Symbol("600000"),
            reason="watchlist condition is present",
            confidence=Decimal("0.40"),
        )

    def before_market_open(
        self, context: StrategyRuntimeContext
    ) -> StrategyRuntimeOutput:
        return StrategyRuntimeOutput.no_action(
            reason="account truth evidence is not ready for live-like review",
        )

    def on_bar(
        self,
        context: StrategyRuntimeContext,
        event: MarketEvent,
    ) -> tuple[StrategyRuntimeOutput, StrategyRuntimeOutput]:
        return (
            StrategyRuntimeOutput.buy_candidate(
                symbol=event.symbol,
                reason="short-term signal crossed the buy threshold",
                quantity=Decimal("100"),
                price=event.close,
                confidence=Decimal("0.70"),
                evidence={"indicator": "runtime_fixture"},
            ),
            StrategyRuntimeOutput.risk_warning(
                symbol=event.symbol,
                reason="candidate still requires account-truth and risk gates",
            ),
        )

    def on_tick(
        self,
        context: StrategyRuntimeContext,
        event: MarketEvent,
    ) -> None:
        return None

    def after_market_close(
        self, context: StrategyRuntimeContext
    ) -> tuple[StrategyRuntimeOutput, StrategyRuntimeOutput]:
        return (
            StrategyRuntimeOutput.rebalance_candidate(
                symbol=Symbol("600000"),
                reason="target weight drift exceeded the research threshold",
                target_weight=Decimal("0.15"),
            ),
            StrategyRuntimeOutput.sell_candidate(
                symbol=Symbol("600000"),
                reason="protective exit candidate from runtime fixture",
                quantity=Decimal("100"),
                price=Decimal("10.10"),
                confidence=Decimal("0.60"),
            ),
        )

    def on_order_update(self, context: StrategyRuntimeContext, event: object) -> None:
        return None

    def on_fill_update(self, context: StrategyRuntimeContext, event: object) -> None:
        return None
