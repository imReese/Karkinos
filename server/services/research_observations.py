"""Explicit, persisted research-to-target shadow observation commands.

No market provider, AI workflow, actual account, order or fill is consulted.
Only an explicit advance publishes the latest known closed session and measures
previously frozen future intervals. Historical warmup cannot create publications.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa

from analytics.forward_target_outcomes import (
    FORWARD_TARGET_OUTCOME_POLICY_ID,
    evaluate_forward_target_outcome,
)
from core.types import InstrumentKey
from data.storage.objects import ContentAddressedObjectStore
from domain.research_targets import (
    RESEARCH_TARGET_POLICY_ID,
    build_research_target_weights,
)
from risk.target_limits import TARGET_LIMITS_POLICY_ID, evaluate_target_limits
from server.ai_runtime.contracts import content_fingerprint
from server.persistence.research_observations import ResearchObservationsRepository
from server.services.research_observation_forecasts import (
    FORECAST_POLICY_ID,
    build_observation_forecasts,
)
from server.services.research_observation_inputs import (
    latest_closed_session,
    load_research_observation_source,
    observation_outcome_sessions,
    read_research_observation_dataset,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_POLICY_ID = "karkinos.research.explicit_target_observation.v1"


def observation_code_binding() -> dict[str, Any]:
    """Bind the deterministic calculations and reader implementation in use."""
    root = Path(__file__).resolve().parents[2]
    paths = (
        "server/services/research_observations.py",
        "server/services/research_observation_forecasts.py",
        "server/services/research_observation_inputs.py",
        "server/services/market_calendar_evidence.py",
        "server/services/research_datasets.py",
        "server/persistence/research_observations.py",
        "server/ai_runtime/formula_dsl.py",
        "strategy/base.py",
        "strategy/builtins/dual_ma.py",
        "core/event_bus.py",
        "core/events.py",
        "core/types.py",
        "data/features.py",
        "data/dataset/reader.py",
        "data/dataset/model.py",
        "data/dataset/manifest.py",
        "data/market/model.py",
        "data/market/capture.py",
        "data/market/revision.py",
        "data/market/quality_evidence.py",
        "data/market/verification_evidence.py",
        "data/storage/objects.py",
        "domain/research_targets.py",
        "risk/target_limits.py",
        "analytics/forward_target_outcomes.py",
        "analytics/dataset_snapshot.py",
    )
    hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths
    }
    payload = {
        "files": hashes,
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "pyarrow": pa.__version__,
    }
    return {**payload, "fingerprint": content_fingerprint(payload)}


class ResearchObservationService:
    def __init__(self, db: Any, *, clock: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.repository = ResearchObservationsRepository(db.path, clock=self.clock)
        self.objects = ContentAddressedObjectStore(
            db.path.resolve().parent / "research" / "objects"
        )

    async def start(
        self,
        *,
        request_id: str,
        source_backtest_result_id: int,
        horizon_sessions: int,
        max_symbol_weight: Decimal,
        max_gross_weight: Decimal,
    ) -> dict[str, Any]:
        if not 1 <= horizon_sessions <= 60 or any(
            not value.is_finite() or not 0 < value <= 1
            for value in (max_symbol_weight, max_gross_weight)
        ):
            raise ValueError("observation_policy_invalid")
        request = {
            "source_backtest_result_id": source_backtest_result_id,
            "horizon_sessions": horizon_sessions,
            "max_symbol_weight": str(max_symbol_weight),
            "max_gross_weight": str(max_gross_weight),
        }
        identity = str(
            uuid5(NAMESPACE_URL, f"karkinos:research-observation:{request_id}")
        )
        fingerprint = content_fingerprint(request)
        replay = self.repository.get_operation(
            observation_id=identity,
            request_id=request_id,
            kind="start",
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return replay
        row = await self.db.get_backtest_result(source_backtest_result_id)
        if row is None:
            raise ValueError("observation_source_not_found")
        source = load_research_observation_source(row, self.objects)
        if len(source["instruments"]) > 50:
            raise ValueError("observation_universe_budget_exceeded")
        source["source_row_fingerprint"] = content_fingerprint(dict(row))
        # A fresh observation is a new, now-frozen derivative. Old backtests did
        # not bind these code bytes and are never retroactively certified.
        policy = {
            "policy_id": _POLICY_ID,
            "scope": "independent_target_shadow",
            "decision_actor": "human_command",
            **request,
            "forecast_policy_id": FORECAST_POLICY_ID,
            "portfolio_policy_id": RESEARCH_TARGET_POLICY_ID,
            "risk_policy_id": TARGET_LIMITS_POLICY_ID,
            "outcome_policy_id": FORWARD_TARGET_OUTCOME_POLICY_ID,
            "concurrency_limit": 20,
            "max_dataset_rows": 200_000,
            "entry_weight": source["entry_target_weight"],
            "contains_fills": False,
            "account_authority": False,
        }
        return self.repository.start(
            observation_id=identity,
            request_id=request_id,
            request_fingerprint=fingerprint,
            source_backtest_result_id=source_backtest_result_id,
            source=source,
            code_binding=observation_code_binding(),
            policy=policy,
            universe=source["instruments"],
            max_active_observations=20,
        )

    def advance(
        self,
        observation_id: str,
        *,
        request_id: str,
        expected_version: int,
        dataset_id: str,
    ) -> dict[str, Any]:
        fingerprint = content_fingerprint(
            {"expected_version": expected_version, "dataset_id": dataset_id}
        )
        replay = self.repository.get_operation(
            observation_id=observation_id,
            request_id=request_id,
            kind="advance",
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return replay
        observation = self.repository.get(observation_id)
        if observation is None:
            raise ValueError("observation_not_found")
        if observation["version"] != expected_version:
            raise ValueError("observation_version_conflict")
        now = self.clock()
        source = observation["source"]
        policy = observation["policy"]
        outcomes: list[dict[str, Any]] = []
        publication = None
        deadline = None
        blocker = None
        try:
            if observation["code_binding"] != observation_code_binding():
                raise ValueError("observation_code_changed")
            calendar = self._calendar(date.fromisoformat(source["start_date"]), now)
            result = read_research_observation_dataset(
                self.objects,
                dataset_id,
                instruments=tuple(
                    InstrumentKey.from_values(item["symbol"], item["instrument_type"])
                    for item in observation["universe"]
                ),
                start_date=date.fromisoformat(source["start_date"]),
                now=now,
                calendar_rows=calendar,
                minimum_bars=source["minimum_bars"],
            )
            if len(result.bars) > policy["max_dataset_rows"]:
                raise ValueError("observation_dataset_budget_exceeded")
            decision_session = latest_closed_session(calendar, now=now)
            outcomes = self._outcomes(
                observation, result, dataset_id, now, decision_session
            )
            if observation["lifecycle"] == "paused":
                blocker = {"code": "observation_publication_paused"}
            elif any(
                item["decision_session"] == decision_session.isoformat()
                for item in observation["publications"]
            ):
                blocker = {"code": "observation_session_already_published"}
            else:
                try:
                    reference_session, end_session = observation_outcome_sessions(
                        calendar,
                        published_at=now,
                        horizon_sessions=policy["horizon_sessions"],
                        now=now,
                    )
                except ValueError as exc:
                    if str(exc) != "observation_calendar_horizon_missing":
                        raise
                    next_year = self.db.get_market_calendar_snapshot_sync(
                        exchange="SSE", year=now.year + 1
                    )
                    if next_year is None:
                        raise
                    calendar.append(next_year)
                    reference_session, end_session = observation_outcome_sessions(
                        calendar,
                        published_at=now,
                        horizon_sessions=policy["horizon_sessions"],
                        now=now,
                    )
                deadline = datetime.combine(reference_session, time(9, 30), _SHANGHAI)
                publication = self._publication(
                    observation,
                    result.bars,
                    dataset_id,
                    decision_session,
                    reference_session,
                    end_session,
                )
                publication["payload"]["calculation_started_at"] = now.isoformat()
                publication["payload"]["calendar_binding"] = [
                    {
                        key: row.get(key)
                        for key in (
                            "exchange",
                            "year",
                            "source_fingerprint",
                            "fetched_at",
                            "official_source_fingerprint",
                            "official_verified_at",
                        )
                    }
                    for row in calendar
                ]
                publication["payload"]["outcome_calendar_days"] = [
                    {"date": day["date"], "is_trading_day": day["is_trading_day"]}
                    for row in calendar
                    for day in row.get("days", json.loads(row.get("days_json") or "[]"))
                    if decision_session.isoformat()
                    <= day["date"]
                    <= end_session.isoformat()
                ]
        except ValueError as exc:
            blocker = {"code": str(exc)}
        return self.repository.advance(
            observation_id=observation_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            expected_version=expected_version,
            publication=publication,
            outcomes=outcomes,
            blocker=blocker,
            publication_deadline=deadline,
            computation_not_before=now,
        )

    def pause(
        self, observation_id: str, *, request_id: str, expected_version: int
    ) -> dict[str, Any]:
        return self.repository.pause(
            observation_id=observation_id,
            request_id=request_id,
            request_fingerprint=content_fingerprint(
                {"expected_version": expected_version}
            ),
            expected_version=expected_version,
        )

    def _calendar(self, start: date, now: datetime) -> list[dict[str, Any]]:
        if now.year - start.year > 10:
            raise ValueError("observation_history_budget_exceeded")
        rows = []
        for year in range(start.year, now.year + 1):
            row = self.db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
            if row is not None:
                rows.append(row)
        return rows

    @staticmethod
    def _publication(
        observation, bars, dataset_id, decision_session, reference_session, end_session
    ):
        policy = observation["policy"]
        previous = {item["symbol"]: Decimal(0) for item in observation["universe"]}
        if observation["publications"]:
            previous = {
                symbol: Decimal(weight)
                for symbol, weight in observation["publications"][-1]["payload"][
                    "target_weights"
                ].items()
            }
        forecasts = build_observation_forecasts(
            observation["source"],
            bars,
            decision_session=decision_session,
            previous_targets=previous,
        )
        desired = dict(previous)
        for forecast in forecasts:
            if forecast["action"] == "enter":
                desired[forecast["symbol"]] = Decimal(policy["entry_weight"])
            elif forecast["action"] == "exit":
                desired[forecast["symbol"]] = Decimal(0)
        limits = {
            name: Decimal(policy[name])
            for name in ("max_symbol_weight", "max_gross_weight")
        }
        targets = build_research_target_weights(desired, **limits)
        risk = evaluate_target_limits(
            targets, frozen_universe=tuple(previous), **limits
        )
        if risk["status"] != "allowed":
            raise ValueError("observation_target_risk_blocked")
        return {
            "id": str(uuid5(NAMESPACE_URL, f"{observation['id']}:{decision_session}")),
            "decision_session": decision_session.isoformat(),
            "dataset_id": dataset_id,
            "payload": {
                "forecasts": forecasts,
                "previous_target_weights": {
                    key: str(value) for key, value in previous.items()
                },
                "desired_weights": {key: str(value) for key, value in desired.items()},
                "target_weights": {key: str(value) for key, value in targets.items()},
                "risk_decision": risk,
                "rebalance_weight_deltas": {
                    key: str(targets[key] - previous[key]) for key in targets
                },
                "reference_session": reference_session.isoformat(),
                "end_session": end_session.isoformat(),
                "horizon_sessions": policy["horizon_sessions"],
                "scope": "independent_target_shadow",
                "contains_fills": False,
            },
        }

    @staticmethod
    def _outcomes(observation, result, dataset_id, now, decision_session):
        measured = {item["publication_id"] for item in observation["outcomes"]}
        outcomes = []
        for publication in observation["publications"]:
            payload = publication["payload"]
            end = date.fromisoformat(payload["end_session"])
            if publication["id"] in measured or end > decision_session:
                continue
            outcome = evaluate_forward_target_outcome(
                publication_at=datetime.fromisoformat(publication["published_at"]),
                reference_session=date.fromisoformat(payload["reference_session"]),
                end_session=end,
                target_weights={
                    key: Decimal(value)
                    for key, value in payload["target_weights"].items()
                },
                bars=result.bars,
                evaluated_at=now,
            )
            if outcome["status"] == "measured":
                outcome["corporate_action_evidence"] = result.corporate_action_evidence
                outcomes.append(
                    {
                        "publication_id": publication["id"],
                        "horizon": payload["horizon_sessions"],
                        "dataset_id": dataset_id,
                        "payload": outcome,
                    }
                )
        return outcomes
