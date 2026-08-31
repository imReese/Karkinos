"""Deterministic market and account bound baseline preparation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pandas as pd

from analytics.backtest_capacity_evidence import build_backtest_capacity_evidence
from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.backtest_fee_tax_evidence import build_backtest_fee_tax_evidence
from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)
from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from analytics.oos_validation import build_rolling_out_of_sample_validation
from backtest.engine import BacktestEngine
from core.types import BarFrequency, Symbol
from data.handler import DataHandler
from data.manager import DataManager
from server.ai_runtime.strategy_research import rolling_oos_parameters
from server.ai_runtime.formula_dsl import CANONICAL_COST_MODEL_REFERENCE
from server.ai_runtime.strategy_research_privacy import (
    NORMALIZED_RESEARCH_NOTIONAL,
)
from server.bootstrap import build_strategy
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
    PreparedBaseline,
    ShadowResearchPolicy,
    ShadowResearchRejected,
    shadow_research_json_object,
)
from server.models import BacktestRequest
from server.services.ai_shadow_research_support import (
    NullShadowResearchEventBus,
    shadow_research_asset_class,
    shadow_research_market_close_as_of,
)
from server.services.backtest_result_projection import (
    build_backtest_report_metrics_json,
    fill_to_response,
)
from server.services.market_universe_automation import verified_trading_dates
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    MarketUniverseRejected,
    build_market_universe_truth,
)
from server.services.reviewed_fee_schedule import ReviewedFeeScheduleRejected


class AiShadowResearchBaselineMixin:
    def _prepare_baseline(self, policy: ShadowResearchPolicy) -> PreparedBaseline:
        rows = asyncio.run(self._db.get_backtest_results())
        seed = None
        if policy.baseline_backtest_result_id is not None:
            seed = asyncio.run(
                self._db.get_backtest_result(policy.baseline_backtest_result_id)
            )
        else:
            for summary in rows:
                candidate = asyncio.run(
                    self._db.get_backtest_result(int(summary["id"]))
                )
                config = shadow_research_json_object(
                    candidate.get("config_json") if candidate else None
                )
                if candidate and config.get("strategy") not in {
                    None,
                    "",
                    "ai_formula_research",
                }:
                    seed = candidate
                    break
        if not isinstance(seed, dict):
            raise ShadowResearchRejected("eligible_baseline_backtest_missing")
        config = shadow_research_json_object(seed.get("config_json"))
        assets = config.get("assets")
        if not isinstance(assets, list) or not assets:
            raise ShadowResearchRejected("baseline_assets_missing")
        for asset in assets:
            if not isinstance(asset, dict) or not asset.get("symbol"):
                raise ShadowResearchRejected("baseline_asset_invalid")
            if str(asset.get("asset_class") or "stock").strip().lower() != "stock":
                raise ShadowResearchRejected(
                    "daily_candidate_strategy_asset_class_not_supported"
                )
        start_date = str(config.get("start_date") or "")
        if not start_date:
            raise ShadowResearchRejected("baseline_start_date_missing")
        seed_initial_cash = float(
            config.get("initial_cash") or seed.get("initial_cash") or 0
        )
        initial_cash = (
            NORMALIZED_RESEARCH_NOTIONAL
            if policy.research_capital_mode
            == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
            else seed_initial_cash
        )
        market_universe_snapshot = self._data_store.get_market_universe_snapshot()
        market_date = str((market_universe_snapshot or {}).get("trade_date") or "")
        provider_name = str((market_universe_snapshot or {}).get("provider_name") or "")
        try:
            ingestion_run = self._db.get_automation_run_sync(
                f"market_universe_sync:v2:{provider_name}:{market_date}"
            )
            ingestion_payload = shadow_research_json_object(
                ingestion_run.get("payload_json") if ingestion_run else None
            )
            if (
                not ingestion_run
                or ingestion_run.get("status") != "completed"
                or ingestion_payload.get("schema_version")
                != "karkinos.market_universe_automation.v2"
                or ingestion_payload.get("market_universe_snapshot_id")
                != (market_universe_snapshot or {}).get("snapshot_id")
                or ingestion_payload.get("full_market_history_frozen") is not True
            ):
                raise MarketUniverseRejected(
                    "full_market_universe_ingestion_not_complete"
                )
            trading_dates = verified_trading_dates(
                self._db,
                start_date=start_date,
                end_date=market_date,
            )
            receipts = self._data_store.list_market_daily_ingestion_receipts(
                start_date=start_date,
                end_date=market_date,
                provider_name=provider_name,
            )
            if [str(item.get("trade_date") or "") for item in receipts] != (
                trading_dates
            ):
                raise MarketUniverseRejected(
                    "full_market_daily_receipt_coverage_incomplete"
                )
            market_universe_truth = build_market_universe_truth(
                data_store=self._data_store,
                snapshot=market_universe_snapshot or {},
                start_date=start_date,
                end_date=market_date,
                initial_cash=initial_cash,
                receipt_fingerprints=[
                    str(item.get("receipt_fingerprint") or "") for item in receipts
                ],
                required_trading_date_count=len(trading_dates),
                policy=MarketUniversePolicy(),
            )
        except MarketUniverseRejected as exc:
            raise ShadowResearchRejected(str(exc)) from exc
        research_panel = market_universe_truth["research_panel"]
        market_date = str(research_panel["trade_date"])
        panel_symbols = [str(symbol) for symbol in research_panel["symbols"]]
        handlers: dict[Symbol, DataHandler] = {}
        instruments: dict[Symbol, Any] = {}
        frames: dict[Symbol, pd.DataFrame] = {}
        normalized_assets: list[dict[str, str]] = []
        for symbol_text in panel_symbols:
            symbol = Symbol(symbol_text)
            asset_class_text = "stock"
            asset_class = shadow_research_asset_class(asset_class_text)
            frame = self._data_store.load_bars(symbol, BarFrequency.DAILY)
            if frame is None or frame.empty or "timestamp" not in frame.columns:
                raise ShadowResearchRejected(f"persisted_bars_missing:{symbol}")
            frame = frame.copy()
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])
            frame = frame.loc[
                frame["timestamp"] >= pd.Timestamp(start_date)
            ].sort_values("timestamp")
            if frame.empty:
                raise ShadowResearchRejected(f"persisted_window_empty:{symbol}")
            if frame["timestamp"].iloc[-1].date().isoformat() != market_date:
                raise ShadowResearchRejected(f"persisted_market_date_missing:{symbol}")
            frames[symbol] = frame
            normalized_assets.append(
                {"symbol": str(symbol), "asset_class": asset_class_text}
            )
            instruments[symbol] = DataManager.get_instrument(symbol, asset_class)
        for asset, (symbol, frame) in zip(
            normalized_assets, frames.items(), strict=True
        ):
            asset_class = shadow_research_asset_class(asset["asset_class"])
            sliced = frame.loc[
                frame["timestamp"]
                <= pd.Timestamp(market_date)
                + pd.Timedelta(days=1)
                - pd.Timedelta(microseconds=1)
            ].reset_index(drop=True)
            handlers[symbol] = DataHandler(
                sliced, symbol, BarFrequency.DAILY, asset_class
            )
        snapshot = build_backtest_dataset_snapshot(
            start_date=start_date,
            end_date=market_date,
            configured_source=None,
            data_handlers=handlers,
            store=self._data_store,
            source_names=[],
        )
        if snapshot.get("data_quality", {}).get("status") != "ok":
            raise ShadowResearchRejected("baseline_dataset_quality_not_complete")
        request = BacktestRequest(
            start_date=start_date,
            end_date=market_date,
            initial_cash=initial_cash,
            strategy=str(config.get("strategy")),
            short_period=int(config.get("short_period") or 5),
            long_period=int(config.get("long_period") or 20),
            params=dict(config.get("params") or {}),
            assets=normalized_assets,
            oos_mode="rolling",
        )
        if (
            policy.research_capital_mode
            == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
        ):
            commission_calc = None
            cost_model_reference = CANONICAL_COST_MODEL_REFERENCE
            fee_schedule_evidence = {
                "schema_version": "karkinos.ai.normalized_notional_cost.v1",
                "cost_model_reference": cost_model_reference,
                "fee_schedule_source": "canonical_default_estimate",
                "account_specific": False,
                "broker_statement_reconciled": False,
                "authorizes_promotion": False,
                "authorizes_execution": False,
            }
        else:
            fee_resolution = self._resolve_reviewed_fee_schedule(
                start_date=start_date,
                end_date=market_date,
                universe=tuple(asset["symbol"] for asset in normalized_assets),
                asset_classes=tuple(
                    asset["asset_class"] for asset in normalized_assets
                ),
                account_truth_as_of=shadow_research_market_close_as_of(
                    market_date,
                    policy.after_close_time,
                ),
            )
            commission_calc = getattr(fee_resolution, "commission_calc", None)
            fee_schedule_evidence = getattr(fee_resolution, "fee_evidence", None)
            cost_model_reference = str(
                getattr(fee_resolution, "cost_model_reference", "") or ""
            )
            if (
                commission_calc is None
                or not isinstance(fee_schedule_evidence, Mapping)
                or not cost_model_reference
            ):
                raise ReviewedFeeScheduleRejected(
                    "reviewed_fee_schedule_resolution_invalid"
                )
            fee_schedule_evidence = dict(fee_schedule_evidence)
        strategy = build_strategy(
            SimpleNamespace(
                strategy=request.strategy,
                short_period=request.short_period,
                long_period=request.long_period,
                params=request.params,
            ),
            NullShadowResearchEventBus(),
        )
        result = BacktestEngine(
            strategy=strategy,
            instruments=instruments,
            data_handlers=handlers,
            initial_cash=Decimal(str(request.initial_cash)),
            commission_calc=commission_calc,
            db=None,
        ).run()
        min_train, test_window, step = rolling_oos_parameters(len(result.equity_curve))
        request.oos_min_train_points = min_train
        request.oos_test_window_points = test_window
        request.oos_step_points = step
        evidence = (
            result.evidence_bundle.to_json_dict() if result.evidence_bundle else {}
        )
        metrics = result.metrics
        metrics_json = metrics.to_json_dict()
        metrics_json.update(
            {
                "evidence_bundle": evidence,
                "dataset_snapshot": snapshot,
                "oos_validation": build_rolling_out_of_sample_validation(
                    strategy_id=request.strategy,
                    benchmark_role="current_persisted_baseline",
                    result=result,
                    min_train_points=min_train,
                    test_window_points=test_window,
                    step_points=step,
                ).to_json_dict(),
                "fee_component_evidence": build_backtest_fee_tax_evidence(
                    fills=result.fills,
                    cost_model_reference=cost_model_reference,
                    account_specific=bool(
                        fee_schedule_evidence.get("account_specific", False)
                    ),
                    fee_schedule_source=str(
                        fee_schedule_evidence.get("fee_schedule_source") or ""
                    ),
                    fee_schedule_fingerprint=str(
                        fee_schedule_evidence.get("fee_schedule_fingerprint") or ""
                    ),
                    broker_statement_reconciled=bool(
                        fee_schedule_evidence.get("broker_statement_reconciled", False)
                    ),
                    fee_schedule_binding=fee_schedule_evidence,
                ),
                "capacity_review": build_backtest_capacity_evidence(
                    fills=result.fills,
                    data_handlers=handlers,
                    initial_cash=result.initial_cash,
                ),
                "drawdown_evidence": build_backtest_drawdown_evidence(
                    equity_curve=result.equity_curve,
                ),
                "market_regime_robustness": build_backtest_market_regime_evidence(
                    result=result,
                    data_handlers=handlers,
                ),
                "market_universe_truth": market_universe_truth,
                "automatic_baseline_refresh": True,
                "persisted_market_data_only": True,
            }
        )
        payload = {
            "initial_cash": float(result.initial_cash),
            "final_equity": float(result.final_equity),
            "total_return": float(result.total_return),
            "annual_return": metrics.annual_return,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "max_drawdown": metrics.max_drawdown,
            "win_rate": metrics.win_rate,
            "duration_days": result.duration_days,
            "equity_curve": [
                {"timestamp": timestamp.isoformat(), "equity": float(value)}
                for timestamp, value in result.equity_curve
            ],
            "metrics_json": metrics_json,
            "cost_summary_json": result.cost_summary.to_json_dict(),
            "evidence_json": evidence,
            "fills": [fill_to_response(fill) for fill in result.fills],
        }
        payload["metrics_json"] = build_backtest_report_metrics_json(
            request,
            payload,
        )
        return PreparedBaseline(
            seed_result_id=int(seed["id"]),
            market_date=market_date,
            snapshot=snapshot,
            request=request,
            result=payload,
            cost_model_reference=cost_model_reference,
            fee_schedule_evidence=fee_schedule_evidence,
        )
