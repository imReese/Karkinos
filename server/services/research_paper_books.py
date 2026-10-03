"""Settle a separate paper book from actually published research targets."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa

from backtest.distributions import distributions_from_evidence
from backtest.paper_replay import (
    PAPER_REPLAY_POLICY_ID,
    PublishedPaperTarget,
    replay_paper_book,
)
from core.events import MarketEvent
from core.types import (
    AssetClass,
    CommissionType,
    InstrumentKey,
    InstrumentType,
    Settlement,
    Symbol,
)
from data.dataset.reader import (
    DatasetReaderError,
    read_dataset_corporate_action_evidence,
)
from domain.instrument import Instrument, make_stock
from server.contracts.content_identity import content_fingerprint
from server.contracts.http.strategy_models import BacktestCostAssumptions
from server.persistence.research_paper_books import ResearchPaperBooksRepository
from server.services.backtest_costs import resolve_backtest_costs
from server.services.research_observation_inputs import (
    latest_closed_session,
    observation_outcome_sessions,
    read_research_observation_dataset,
)
from server.services.research_observations import (
    ResearchObservationService,
    observation_code_binding,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_STATE_LIMITATIONS = [
    "Independent simulated cash, positions and fills; no actual account or broker authority.",
    "Daily close fills use the frozen simulation model, not executable venue evidence or liquidity guarantees.",
    "Stock lot, T+1 and 10%/20% price limits are frozen model assumptions; ST and special listing phases are not verified.",
    "Reported corporate actions are modeled gross; source completeness, investor-specific taxes and cash payment rounding remain unverified.",
    "At most 2000 settled sessions and the frozen Dataset row budget are supported; this bounded research book has no rollover or capital authority.",
    "Different corporate-action terms for one symbol and report period are ambiguous and block settlement, including record/ex-date revisions.",
    "Unknown fractional share entitlements and ex-date orders without an official price-limit reference are blocked.",
]


def paper_book_code_binding():
    root = Path(__file__).resolve().parents[2]
    paths = (
        "server/services/research_paper_books.py",
        "server/persistence/research_paper_books.py",
        "server/services/backtest_costs.py",
        "backtest/paper_replay.py",
        "backtest/engine.py",
        "backtest/distributions.py",
        "core/event_bus.py",
        "core/events.py",
        "core/types.py",
        "domain/portfolio.py",
        "domain/position.py",
        "domain/portfolio_accounting.py",
        "domain/a_share_limits.py",
        "domain/instrument.py",
        "execution/simulator.py",
        "execution/commission.py",
        "execution/slippage.py",
        "risk/manager.py",
        "risk/rules.py",
        "server/services/research_observation_inputs.py",
        "server/services/research_datasets.py",
        "server/services/market_calendar_evidence.py",
        "data/dataset/reader.py",
        "data/dataset/model.py",
        "data/dataset/manifest.py",
        "data/market/model.py",
        "data/market/capture.py",
        "data/market/revision.py",
        "data/market/quality_evidence.py",
        "data/market/verification_evidence.py",
        "data/market/corporate_actions.py",
        "data/storage/objects.py",
    )
    payload = {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "pyarrow": pa.__version__,
        "files": {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in paths
        },
    }
    return {**payload, "fingerprint": content_fingerprint(payload)}


def _instant(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if (
        not isinstance(parsed, datetime)
        or parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise ValueError("paper_book_timestamp_invalid")
    return parsed.astimezone(timezone.utc)


def _instrument_payload(instrument):
    return {
        key: value.value if hasattr(value, "value") else str(value)
        for key, value in asdict(instrument).items()
    }


def _restore_instrument(payload):
    values = dict(payload)
    for key, enum in (
        ("asset_class", AssetClass),
        ("instrument_type", InstrumentType),
        ("commission_type", CommissionType),
        ("settlement", Settlement),
    ):
        values[key] = enum(values[key])
    for key in ("lot_size", "price_tick", "limit_pct"):
        values[key] = Decimal(values[key])
    values["symbol"] = Symbol(values["symbol"])
    return Instrument(**values)


def _sessions(calendar):
    return sorted(
        {
            date.fromisoformat(day["date"])
            for row in calendar
            for day in row.get("days", json.loads(row.get("days_json") or "[]"))
            if day["is_trading_day"]
        }
    )


def _market_event(bar):
    return MarketEvent(
        timestamp=bar.event_time,
        symbol=Symbol(bar.instrument.symbol),
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        available_at=bar.available_at,
        asset_class=AssetClass.STOCK,
        instrument_type=InstrumentType.STOCK,
    )


def _merge_distributions(evidence_rows, *, evaluation_start):
    merged, terms, filtered = {}, {}, []
    try:
        for evidence in evidence_rows:
            if evidence is None:
                raise ValueError("cash_dividend_evidence_required")
            events = []
            for event in evidence["events"]:
                # An empty initial book cannot own a pre-start record entitlement.
                # An ex-date inside the book still controls order tradability.
                past = all(
                    event.get(field)
                    and date.fromisoformat(event[field]) < evaluation_start
                    for field in ("record_date", "ex_date")
                )
                period = event.get("end_date")
                if not period and not past:
                    raise ValueError("report_period_required")
                if period:
                    key = (event["symbol"], date.fromisoformat(period))
                    financial = tuple(
                        event.get(field)
                        for field in (
                            "record_date",
                            "ex_date",
                            "pay_date",
                            "cash_div_tax",
                            "stk_div",
                            "stk_bo_rate",
                            "stk_co_rate",
                            "div_listdate",
                        )
                    )
                    terms.setdefault(key, []).append((not past, financial))
                if not past:
                    events.append(event)
            filtered.append(
                {
                    **evidence,
                    "events": events,
                    "undated_event_count": sum(
                        not event.get("ex_date") for event in events
                    ),
                }
            )
        # Full reports detect a revision moved outside the price window, but
        # unrelated, proven-zero pre-start entitlements need no simulated dates.
        for versions in terms.values():
            if (
                any(relevant for relevant, _ in versions)
                and len({value for _, value in versions}) > 1
            ):
                raise ValueError("paper_book_corporate_action_revision_conflict")
        for evidence in filtered:
            for action in distributions_from_evidence(evidence, include_shares=True):
                key = (action.symbol, action.record_date, action.ex_date)
                previous = merged.get(key)
                if previous is not None:
                    fields = (
                        "pay_date",
                        "cash_per_share",
                        "bonus_per_share",
                        "capitalized_per_share",
                        "listing_date",
                    )
                    if any(
                        getattr(previous, field) != getattr(action, field)
                        for field in fields
                    ):
                        raise ValueError(
                            "paper_book_corporate_action_revision_conflict"
                        )
                    continue
                merged[key] = action
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        if str(exc) == "paper_book_corporate_action_revision_conflict":
            raise
        raise ValueError(
            "paper_book_corporate_action_evidence_invalid:" + str(exc)
        ) from None
    return tuple(merged.values())


class ResearchPaperBookService:
    def __init__(self, db, *, clock=None):
        self.db = db
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.observations = ResearchObservationService(db, clock=self.clock)
        self.repository = ResearchPaperBooksRepository(db.path, clock=self.clock)

    def get(self, observation_id):
        if self.observations.repository.get(observation_id) is None:
            raise ValueError("paper_book_observation_not_found")
        return self.repository.get(observation_id)

    def start(
        self,
        observation_id,
        *,
        request_id,
        initial_cash: Decimal,
        cost_assumptions: BacktestCostAssumptions | None = None,
    ):
        if not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError("paper_book_initial_cash_invalid")
        cost_inputs = (cost_assumptions or BacktestCostAssumptions()).model_dump(
            mode="json"
        )
        fingerprint = content_fingerprint(
            {"initial_cash": str(initial_cash), "cost_inputs": cost_inputs}
        )
        replay = self.repository.get_operation(
            observation_id, request_id, "start", fingerprint
        )
        if replay is not None:
            return replay
        observation = self.observations.repository.get(observation_id)
        if observation is None:
            raise ValueError("paper_book_observation_not_found")
        if observation["code_binding"] != observation_code_binding():
            raise ValueError("paper_book_observation_code_changed")
        universe = observation["universe"]
        if any(item["instrument_type"] != "stock" for item in universe) or len(
            {item["symbol"] for item in universe}
        ) != len(universe):
            raise ValueError("paper_book_instrument_unsupported")
        now = _instant(self.clock())
        calendar = self.observations._calendar(
            date.fromisoformat(observation["source"]["start_date"]), now
        )
        try:
            evaluation_start, _ = observation_outcome_sessions(
                calendar, published_at=now, horizon_sessions=1, now=now
            )
        except ValueError as exc:
            if str(exc) != "observation_calendar_horizon_missing":
                raise
            following = self.db.get_market_calendar_snapshot_sync(
                exchange="SSE", year=now.astimezone(_SHANGHAI).year + 1
            )
            if following is None:
                raise
            calendar.append(following)
            evaluation_start, _ = observation_outcome_sessions(
                calendar, published_at=now, horizon_sessions=1, now=now
            )
        earlier = [day for day in _sessions(calendar) if day < evaluation_start]
        if not earlier:
            raise ValueError("paper_book_previous_close_required")
        _, effective_costs = resolve_backtest_costs(
            BacktestCostAssumptions.model_validate(cost_inputs)
        )
        policy = {
            "schema_version": "karkinos.research_paper_book.v1",
            "currency": "CNY",
            "replay_policy_id": PAPER_REPLAY_POLICY_ID,
            "execution_model": "forward_published_target_daily_close",
            "ordering": "session_then_symbol_single_attempt",
            "historical_pit_verified": False,
            "contains_simulated_fills": True,
            "observation_target_policy": observation["policy"],
            "corporate_action_mode": "reported_distributions_gross",
            "cost_inputs": cost_inputs,
            "cost_assumptions": effective_costs,
            "warmup_session": earlier[-1].isoformat(),
            "max_sessions": 2000,
            "max_dataset_rows": observation["policy"]["max_dataset_rows"],
            "limitations": [*_STATE_LIMITATIONS, *effective_costs["limitations"]],
        }
        return self.repository.start(
            book_id=str(
                uuid5(
                    NAMESPACE_URL, f"karkinos:paper-book:{observation_id}:{request_id}"
                )
            ),
            observation_id=observation_id,
            request_id=request_id,
            fingerprint=fingerprint,
            source={
                **observation["source"],
                "observation_id": observation_id,
                "observation_code_binding": observation["code_binding"],
                "universe": universe,
            },
            policy=policy,
            code_binding=paper_book_code_binding(),
            instruments={
                item["symbol"]: _instrument_payload(
                    make_stock(item["symbol"], item["symbol"])
                )
                for item in universe
            },
            initial_cash=str(initial_cash),
            evaluation_start=evaluation_start,
            computation_not_before=now,
        )

    def settle(self, observation_id, *, request_id, expected_version, dataset_id):
        fingerprint = content_fingerprint(
            {"expected_version": expected_version, "dataset_id": dataset_id}
        )
        replay = self.repository.get_operation(
            observation_id, request_id, "settle", fingerprint
        )
        if replay is not None:
            return replay
        book = self.repository.get(observation_id)
        if book is None:
            raise ValueError("paper_book_not_found")
        if type(expected_version) is not int or book["version"] != expected_version:
            raise ValueError("paper_book_version_conflict")
        if book["code_binding"] != paper_book_code_binding():
            raise ValueError("paper_book_code_changed")
        now = _instant(self.clock())
        calendar = self.observations._calendar(
            date.fromisoformat(book["source"]["start_date"]), now
        )
        end = latest_closed_session(calendar, now=now)
        start = date.fromisoformat(book["evaluation_start"])
        sessions = [day for day in _sessions(calendar) if start <= day <= end]
        if len(sessions) > book["policy"]["max_sessions"]:
            raise ValueError("paper_book_session_budget_exceeded")
        old_steps = book["steps"]
        new_sessions = [
            day
            for day in sessions
            if not book["last_settled_session"]
            or day.isoformat() > book["last_settled_session"]
        ]
        if not new_sessions:
            raise ValueError("paper_book_no_new_sessions")
        cache = {}

        def read(identity, captured, rows):
            key = (identity, captured, content_fingerprint(rows))
            if key not in cache:
                result = read_research_observation_dataset(
                    self.observations.objects,
                    identity,
                    instruments=tuple(
                        InstrumentKey.from_values(
                            item["symbol"], item["instrument_type"]
                        )
                        for item in book["source"]["universe"]
                    ),
                    start_date=date.fromisoformat(book["source"]["start_date"]),
                    now=_instant(captured),
                    calendar_rows=rows,
                    minimum_bars=book["source"]["minimum_bars"],
                )
                if len(result.bars) > book["policy"]["max_dataset_rows"]:
                    raise ValueError("paper_book_dataset_budget_exceeded")
                # Inspect the complete bound provider report, including terms
                # revised out of the current price window. It is still the same
                # immutable observation, with its original capture/cutoff checks.
                try:
                    evidence = read_dataset_corporate_action_evidence(
                        self.observations.objects,
                        replace(
                            result.snapshot, start_date=date.min, end_date=date.max
                        ),
                    )
                except (DatasetReaderError, OSError):
                    raise ValueError(
                        "paper_book_corporate_action_evidence_unreadable"
                    ) from None
                result = replace(result, corporate_action_evidence=evidence)
                cache[key] = result
            return cache[key]

        current_input = {"read_at": now.isoformat(), "calendar": calendar}
        current = read(dataset_id, current_input["read_at"], calendar)
        evidence_rows = []
        bars = []
        for step in old_steps:
            prior = read(
                step["dataset_id"], step["input"]["read_at"], step["input"]["calendar"]
            )
            bars.extend(
                _market_event(bar)
                for bar in prior.bars
                if bar.session_date.isoformat() == step["session"]
            )
            evidence_rows.append(prior.corporate_action_evidence)
        warmup = date.fromisoformat(book["policy"]["warmup_session"])
        first = (
            read(
                old_steps[0]["dataset_id"],
                old_steps[0]["input"]["read_at"],
                old_steps[0]["input"]["calendar"],
            )
            if old_steps
            else current
        )
        warmup_bars = [bar for bar in first.bars if bar.session_date == warmup]
        if len(warmup_bars) != len(book["instruments"]):
            raise ValueError("paper_book_previous_close_required")
        bars.extend(_market_event(bar) for bar in warmup_bars)
        bars.extend(
            _market_event(bar)
            for bar in current.bars
            if bar.session_date in new_sessions
        )
        evidence_rows.append(current.corporate_action_evidence)
        distributions = _merge_distributions(evidence_rows, evaluation_start=start)
        observation = self.observations.repository.get(observation_id)
        publications = self._targets(book, observation, now, end)
        costs, effective = resolve_backtest_costs(
            BacktestCostAssumptions.model_validate(book["policy"]["cost_inputs"])
        )
        if effective != book["policy"]["cost_assumptions"]:
            raise ValueError("paper_book_cost_policy_changed")
        result = replay_paper_book(
            book_id=book["id"],
            initial_cash=Decimal(book["initial_cash"]),
            instruments={
                Symbol(key): _restore_instrument(value)
                for key, value in book["instruments"].items()
            },
            bars=bars,
            publications=publications,
            evaluation_start=start,
            through_session=end,
            cost_config=costs,
            distributions=distributions,
        )
        projections = {item["session"]: item for item in result["sessions"]}
        if set(projections) != {day.isoformat() for day in sessions}:
            raise ValueError("paper_book_session_projection_incomplete")
        for step in old_steps:
            if projections[step["session"]] != step["projection"]:
                raise ValueError("paper_book_settled_prefix_conflict")
        return self.repository.settle(
            observation_id=observation_id,
            request_id=request_id,
            fingerprint=fingerprint,
            expected_version=expected_version,
            computation_not_before=now,
            steps=[
                {
                    "session": day.isoformat(),
                    "dataset_id": dataset_id,
                    "input": current_input,
                    "projection": projections[day.isoformat()],
                }
                for day in new_sessions
            ],
        )

    @staticmethod
    def _targets(book, observation, now, end):
        cutoff = _instant(book["paused_at"]) if book["paused_at"] else now
        start = _instant(book["started_at"])
        result = []
        for publication in observation["publications"]:
            published = _instant(publication["published_at"])
            if not start < published <= cutoff:
                continue
            payload = publication["payload"]
            reference = date.fromisoformat(payload["reference_session"])
            if reference > end:
                continue
            if published >= datetime.combine(reference, time(9, 30), _SHANGHAI):
                raise ValueError("paper_book_target_published_too_late")
            if set(payload["target_weights"]) != set(book["instruments"]):
                raise ValueError("paper_book_target_universe_conflict")
            if payload["risk_decision"]["status"] != "allowed":
                raise ValueError("paper_book_target_risk_not_allowed")
            result.append(
                PublishedPaperTarget(
                    id=publication["id"],
                    published_at=published,
                    reference_session=reference,
                    target_weights={
                        key: Decimal(value)
                        for key, value in payload["target_weights"].items()
                    },
                )
            )
        return result

    def pause(self, observation_id, *, request_id, expected_version):
        return self.repository.pause(
            observation_id=observation_id,
            request_id=request_id,
            fingerprint=content_fingerprint({"expected_version": expected_version}),
            expected_version=expected_version,
        )
