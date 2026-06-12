from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd

from analytics.report import generate_report
from backtest.engine import BacktestEngine
from core.event_bus import EventBus
from core.events import OrderIntentEvent, SignalEvent
from core.types import AssetClass, BarFrequency, OrderSide, Symbol
from data.features import FeatureEngine
from data.handler import DataHandler
from data.store import DataStore
from domain.instrument import make_etf
from execution.slippage import PercentSlippage
from risk.pre_trade import PreTradeContext, PreTradePolicy, PreTradeRiskManager
from server.db import AppDatabase
from server.services.trading_controls import TradingControlState
from strategy.base import Strategy


class MomentumFixtureStrategy(Strategy):
    def __init__(self, event_bus: EventBus) -> None:
        super().__init__("fixture_momentum", event_bus)
        self._count = 0
        self._has_emitted = False

    def on_init(self, symbols: list[Symbol]) -> None:
        self.symbols = symbols

    def on_data(self, event) -> None:
        self._last_timestamp = event.timestamp
        self._count += 1
        if self._count >= 8 and not self._has_emitted:
            self._has_emitted = True
            self.emit_signal(event.symbol, target_weight=0.2, price=float(event.close))


class StaticPreTradeContext:
    def __init__(self, context: PreTradeContext) -> None:
        self._context = context

    def snapshot(self) -> PreTradeContext:
        return self._context


def _fixture_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=20)
    close = [10.0 + index * 0.2 for index in range(len(dates))]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [value - 0.05 for value in close],
            "high": [value + 0.10 for value in close],
            "low": [value - 0.10 for value in close],
            "close": close,
            "volume": [1_000_000.0] * len(dates),
        }
    )


def test_profit_discipline_smoke_path_reaches_risk_journal_and_action_queue(
    tmp_path,
) -> None:
    symbol = Symbol("510300")
    instrument = make_etf("510300", "沪深300ETF")

    store = DataStore(tmp_path / "market-cache")
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        _fixture_bars(),
        provider_name="fixture",
        data_source="deterministic_fixture",
        adjustment_mode="none",
    )
    meta = store.get_meta(symbol, BarFrequency.DAILY)
    cached_bars = store.load_bars(symbol, BarFrequency.DAILY)

    assert meta is not None
    assert meta["provider_name"] == "fixture"
    assert meta["row_count"] == 20
    assert meta["dataset_id"]
    assert cached_bars is not None

    featured_bars = FeatureEngine().add_all_features(
        cached_bars,
        sma_periods=(3, 5),
        ema_periods=(3,),
        rsi_period=3,
        atr_period=3,
        boll_period=5,
    )
    assert featured_bars["sma_3"].iloc[-1] > featured_bars["sma_5"].iloc[-1]

    signal_events: list[SignalEvent] = []
    strategy = MomentumFixtureStrategy(EventBus())
    engine = BacktestEngine(
        strategy=strategy,
        instruments={symbol: instrument},
        data_handlers={
            symbol: DataHandler(
                featured_bars,
                symbol,
                asset_class=AssetClass.FUND,
            )
        },
        initial_cash=Decimal("100000"),
        slippage_model=PercentSlippage(Decimal("0.001")),
    )
    engine.event_bus.subscribe(SignalEvent, signal_events.append)

    result = engine.run()
    report = generate_report(result)

    assert signal_events
    assert result.evidence_bundle is not None
    assert result.evidence_bundle.fill_count == len(result.fills)
    assert result.cost_summary.gross_turnover > Decimal("0")
    assert "成本后证据" in report
    assert "总成交额" in report

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    signal = signal_events[0]
    db.save_signal_sync(
        timestamp=signal.timestamp.isoformat(),
        strategy_id=signal.strategy_id,
        symbol=str(signal.symbol),
        direction="buy",
        target_weight=float(signal.target_weight),
        price=float(signal.price) if signal.price is not None else None,
        asset_class="fund",
    )
    db.upsert_action_task_sync(
        source_signal_id=1,
        symbol=str(signal.symbol),
        title=f"建议增持 {signal.symbol}",
        detail=f"{signal.strategy_id} 触发，目标仓位 20%",
        direction="buy",
        urgency="high",
        target_weight=float(signal.target_weight),
        price=float(signal.price) if signal.price is not None else None,
        strategy_id=signal.strategy_id,
        timestamp=signal.timestamp.isoformat(),
        asset_class="fund",
    )

    risk_bus = EventBus()
    PreTradeRiskManager(
        risk_bus,
        StaticPreTradeContext(
            PreTradeContext(
                cash=Decimal("100000"),
                total_equity=Decimal("100000"),
                peak_equity=Decimal("100000"),
                positions={},
                instruments={symbol: instrument},
                blacklist=set(),
                st_symbols=set(),
                kill_switch_enabled=TradingControlState()
                .snapshot()
                .kill_switch_enabled,
            )
        ),
        PreTradePolicy(
            execution_mode="manual",
            max_position_weight=Decimal("0.10"),
        ),
        db=db,
    )
    risk_bus.publish_and_process(
        OrderIntentEvent(
            timestamp=datetime(2026, 1, 30, 14, 50),
            intent_id="INTENT-SMOKE-1",
            strategy_id=signal.strategy_id,
            symbol=symbol,
            side=OrderSide.BUY,
            target_weight=Decimal("0.20"),
            quantity=Decimal("1800"),
            reference_price=Decimal("11"),
            asset_class=AssetClass.FUND,
            source_signal_id="1",
            reason="deterministic smoke risk gate",
        )
    )
    risk_bus.drain()

    actions = db.get_action_tasks_sync()
    journal = db.list_signal_journal_sync()

    assert actions[0]["risk_gate_passed"] is False
    assert actions[0]["risk_gate_severity"] == "warning"
    assert (
        "projected position weight exceeds max_position_weight"
        in actions[0]["risk_gate_reasons"]
    )
    assert journal[0]["signal"]["strategy_id"] == "fixture_momentum"
    assert journal[0]["action_task"]["status"] == "pending"
    assert journal[0]["risk_decision"]["passed"] is False
    assert journal[0]["latest_event"]["event_type"] == "risk.signal.recorded"
