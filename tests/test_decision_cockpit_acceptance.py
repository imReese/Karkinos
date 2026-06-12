from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
from fastapi.routing import APIRoute

from analytics.oos_validation import build_out_of_sample_validation
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


class DecisionFixtureStrategy(Strategy):
    def __init__(self, event_bus: EventBus) -> None:
        super().__init__("fixture_decision_momentum", event_bus)
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
    dates = pd.bdate_range("2026-01-05", periods=24)
    close = [4.0 + index * 0.04 for index in range(len(dates))]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [value - 0.01 for value in close],
            "high": [value + 0.03 for value in close],
            "low": [value - 0.03 for value in close],
            "close": close,
            "volume": [2_000_000.0] * len(dates),
        }
    )


def _decision_endpoint(path: str):
    from server.routes import decision as decision_routes

    router = decision_routes.create_router()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path
    )
    return route.endpoint


def test_fixture_cache_to_decision_api_dashboard_contract(
    monkeypatch, tmp_path
) -> None:
    symbol = Symbol("510300")
    instrument = make_etf("510300", "沪深300ETF")

    store = DataStore(tmp_path / "market-cache")
    store.save_bars(
        symbol,
        BarFrequency.DAILY,
        _fixture_bars(),
        provider_name="fixture",
        data_source="deterministic_decision_fixture",
        adjustment_mode="none",
    )
    meta = store.get_meta(symbol, BarFrequency.DAILY)
    cached_bars = store.load_bars(symbol, BarFrequency.DAILY)

    assert meta is not None
    assert meta["provider_name"] == "fixture"
    assert meta["dataset_id"]
    assert meta["row_count"] == 24
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
    strategy = DecisionFixtureStrategy(EventBus())
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
    assert result.cost_summary.gross_turnover > Decimal("0")
    assert "成本后证据" in report

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
        detail=(
            f"{signal.strategy_id} 触发，目标仓位 20%，" f"dataset={meta['dataset_id']}"
        ),
        direction="buy",
        urgency="high",
        target_weight=float(signal.target_weight),
        price=float(signal.price) if signal.price is not None else None,
        strategy_id=signal.strategy_id,
        timestamp=signal.timestamp.isoformat(),
        asset_class="fund",
    )
    db.upsert_latest_quote_sync(
        symbol=str(signal.symbol),
        asset_type="fund",
        price=float(signal.price or Decimal("4.92")),
        quote_timestamp="2026-01-30T14:50:00+08:00",
        quote_source="deterministic_fixture",
        provider_name="fixture",
        provider_status="ok",
        quote_status="live",
        metadata={"dataset_id": meta["dataset_id"], "feature_columns": ["sma_3"]},
    )

    oos_validation = build_out_of_sample_validation(
        strategy_id=signal.strategy_id,
        benchmark_role="decision_acceptance_fixture",
        result=result,
        split_timestamp=result.equity_curve[len(result.equity_curve) // 2][0],
        benchmark_return=Decimal("0.01"),
        limitations=["Fixture evidence is deterministic and not a profit claim."],
    )
    metrics_json = result.metrics.to_json_dict()
    metrics_json["evidence_bundle"] = result.evidence_bundle.to_json_dict()
    metrics_json["oos_validation"] = oos_validation.to_json_dict()
    backtest_result_id = asyncio.run(
        db.save_backtest_result(
            config_json=json.dumps(
                {
                    "strategy": signal.strategy_id,
                    "fixture": "decision_cockpit_acceptance",
                    "dataset_id": meta["dataset_id"],
                }
            ),
            initial_cash=float(result.initial_cash),
            final_equity=float(result.final_equity),
            total_return=float(result.total_return),
            sharpe=float(result.metrics.sharpe),
            max_dd=float(result.metrics.max_drawdown),
            equity_curve_json="[]",
            annual_return=float(result.metrics.annual_return),
            sortino=float(result.metrics.sortino),
            win_rate=float(result.metrics.win_rate),
            duration_days=result.metrics.duration_days,
            metrics_json=json.dumps(metrics_json, ensure_ascii=False),
            cost_summary_json=json.dumps(
                result.cost_summary.to_json_dict(), ensure_ascii=False
            ),
        )
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
            max_position_weight=Decimal("0.30"),
        ),
        db=db,
    )
    risk_bus.publish_and_process(
        OrderIntentEvent(
            timestamp=datetime(2026, 1, 30, 14, 50),
            intent_id="INTENT-DECISION-1",
            strategy_id=signal.strategy_id,
            symbol=symbol,
            side=OrderSide.BUY,
            target_weight=Decimal("0.20"),
            quantity=Decimal("4000"),
            reference_price=Decimal("4.90"),
            asset_class=AssetClass.FUND,
            source_signal_id="1",
            reason="deterministic decision cockpit acceptance",
        )
    )
    risk_bus.drain()

    actions = db.get_action_tasks_sync()
    journal = db.list_signal_journal_sync()

    assert actions[0]["risk_gate_status"] == "passed"
    assert actions[0]["manual_confirmation_status"] == ("ready_for_manual_confirmation")
    assert journal[0]["latest_event"]["event_type"] == "risk.signal.recorded"

    fake_portfolio = SimpleNamespace(
        cash=80400.0,
        positions={"510300": SimpleNamespace(market_value=19600.0)},
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(
            config=SimpleNamespace(
                assets=[{"symbol": "510300", "asset_class": "fund"}]
            ),
            scheduler=SimpleNamespace(
                portfolio=fake_portfolio,
                latest_quotes={},
                watchlist=[("510300", "fund")],
            ),
            db=db,
        ),
    )

    today = asyncio.run(_decision_endpoint("/api/decision/today")())
    intraday = asyncio.run(_decision_endpoint("/api/decision/intraday")())

    assert today["lane"] == "daily"
    assert today["decision"] == "buy"
    assert today["requires_manual_confirmation"] is True
    assert today["summary"]["portfolio"]["total_equity"] == 100000.0
    assert today["summary"]["market_data"]["source_health"] == "live"
    assert today["summary"]["audit"]["signal_count"] == 1
    assert today["summary"]["audit"]["risk_checked_count"] == 1
    assert today["summary"]["audit"]["journal_entry_count"] == 1

    candidate = today["candidates"][0]
    assert candidate["symbol"] == "510300"
    assert candidate["action"] == "buy"
    assert candidate["risk_gate_status"] == "passed"
    assert candidate["manual_confirmation_status"] == "ready_for_manual_confirmation"
    assert candidate["evidence"]["strategy"]["strategy_id"] == (
        "fixture_decision_momentum"
    )
    assert candidate["evidence"]["signal"]["id"] == 1
    assert candidate["evidence"]["risk_gate"]["status"] == "passed"
    assert candidate["evidence"]["risk_gate"]["passed"] is True
    assert candidate["evidence"]["data_freshness"]["status"] == "live"
    assert candidate["evidence"]["manual_confirmation"]["required"] is True
    assert candidate["evidence"]["journal"]["has_journal_entry"] is True
    assert candidate["evidence"]["journal"]["latest_event_type"] == (
        "risk.signal.recorded"
    )

    validation = candidate["evidence"]["after_cost_oos_validation"]
    assert validation["status"] == "attached"
    assert validation["backtest_result_id"] == backtest_result_id
    assert validation["has_after_cost_report"] is True
    assert validation["has_out_of_sample_validation"] is True
    assert validation["after_cost"]["fill_count"] == len(result.fills)
    assert validation["oos_validation"]["validation_status"] in {
        "benchmark_passed",
        "needs_review",
    }

    assert intraday["lane"] == "intraday"
    assert intraday["cadence"] == "polling_or_minute_level"
    assert intraday["decision"] == "buy"
    assert [candidate["symbol"] for candidate in intraday["candidates"]] == ["510300"]
    assert intraday["no_action_reasons"] == []

    dashboard_candidate = intraday["candidates"][0]
    assert dashboard_candidate["manual_confirmation_required"] is True
    assert dashboard_candidate["evidence"]["risk_gate"]["decision_id"]
    assert (
        dashboard_candidate["evidence"]["after_cost_oos_validation"]["status"]
        == "attached"
    )
    assert dashboard_candidate["evidence"]["data_freshness"]["price"] == float(
        signal.price
    )
