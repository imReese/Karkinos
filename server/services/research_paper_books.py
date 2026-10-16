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

from analytics.paper_performance import validate_paper_health_policy
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
    daily_bar_dataset_read_scope,
    read_dataset_corporate_action_evidence,
)
from domain.instrument import Instrument, make_etf, make_research_stock, make_stock
from domain.research_targets import (
    FORMULA_PORTFOLIO_POLICY_ID,
    build_research_target_weights,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.http.strategy_models import BacktestCostAssumptions
from server.contracts.research_observation_automation import reserved_forward_identity
from server.persistence.research_paper_books import ResearchPaperBooksRepository
from server.services.backtest_costs import (
    resolve_paper_book_costs as resolve_paper_book_costs,
)
from server.services.research_observation_inputs import (
    latest_closed_session,
    observation_deployment_scope,
    observation_input_binding,
    observation_outcome_sessions,
    read_research_observation_dataset,
    require_observation_dataset_prefix,
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
        "analytics/paper_performance.py",
        "server/persistence/research_paper_books.py",
        "server/services/backtest_costs.py",
        "backtest/paper_replay.py",
        "server/ai_runtime/formula_portfolio.py",
        "server/services/account_board_permissions.py",
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
        "domain/research_targets.py",
        "server/services/reviewed_fee_schedule.py",
        "server/services/reviewed_fee_schedule_workflows.py",
        "server/services/reviewed_fee_schedule_commission.py",
        "server/services/reviewed_fee_schedule_repository.py",
        "server/services/reviewed_fee_schedule_policy.py",
        "execution/simulator.py",
        "execution/commission.py",
        "execution/slippage.py",
        "risk/manager.py",
        "risk/rules.py",
        "server/services/research_observation_inputs.py",
        "server/services/research_datasets.py",
        "server/services/research/datasets.py",
        "server/services/research_corporate_action_jobs.py",
        "server/services/research_observation_data_preparation.py",
        "server/persistence/automation_runs.py",
        "server/contracts/recommendation_publication.py",
        "server/services/market_universe_truth.py",
        "server/services/market_calendar_evidence.py",
        "data/dataset/reader.py",
        "data/dataset/model.py",
        "data/dataset/manifest.py",
        "data/market/model.py",
        "data/market/capture.py",
        "data/market/revision.py",
        "data/market/contracts.py",
        "data/market/capture.py",
        "data/market/normalize.py",
        "data/market/ingestion.py",
        "data/market/cross_source.py",
        "data/market/quality.py",
        "data/providers/baostock.py",
        "data/providers/tencent.py",
        "data/providers/tushare.py",
        "data/providers/akshare.py",
        "data/providers/eastmoney.py",
        "data/market/quality_evidence.py",
        "data/market/verification_evidence.py",
        "data/market/corporate_actions.py",
        "data/providers/tushare_corporate_actions.py",
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


def verify_reserved_forward_book(db, reservation, *, through_session, now):
    """Reopen the real publication and settlement prefix for a final decision."""
    from analytics.paper_performance import (
        evaluate_paper_health,
        paper_book_performance,
    )

    binding = (reservation.get("evidence") or {}).get("reservation", reservation)
    sealed_id = (
        reservation.get("sealed_test_id")
        or "ai-sealed-auto-"
        + content_fingerprint({"run_id": binding["source_run_id"]})[:24]
    )
    grant = binding["publication_grant"]
    _, identity = reserved_forward_identity(sealed_id, grant)
    observations = ResearchObservationService(db, clock=lambda: now)
    observed = observations.repository.get(identity)
    book = ResearchPaperBooksRepository(db.path, clock=lambda: now).get(identity)
    if observed is None or book is None:
        raise ValueError("deployment_forward_book_missing")
    if (
        observed["lifecycle"] != "active"
        or book["lifecycle"] != "active"
        or book["health"].get("action") == "pause_paper_target_acceptance"
    ):
        raise ValueError("deployment_forward_book_health_blocked")
    if (
        observed["code_binding"] != observation_code_binding()
        or book["code_binding"] != paper_book_code_binding()
    ):
        raise ValueError("deployment_forward_book_code_changed")
    authorization = observed["policy"].get("authorization_binding", {})
    if (
        authorization
        != {
            "grant_id": grant["grant_id"],
            "generation": grant["generation"],
            "reservation_id": sealed_id,
        }
        or observed["source_backtest_result_id"] != binding["candidate_result_id"]
        or observed["policy"].get("portfolio_policy_id") != FORMULA_PORTFOLIO_POLICY_ID
        or observation_deployment_scope(observed["source"])
        != binding["deployment_scope"]
        or Decimal(book["initial_cash"]) != Decimal(binding["initial_cash"])
        or book["policy"].get("fee_schedule_binding") != binding["fee_schedule"]
        or observed["policy"].get("entry_board_policy")
        != grant.get("entry_board_policy")
        or binding.get("entry_board_policy") != grant.get("entry_board_policy")
        or book["policy"].get("entry_board_policy") != grant.get("entry_board_policy")
    ):
        raise ValueError("deployment_forward_book_binding_mismatch")
    risk = grant["risk_limits"]
    equity = Decimal(book["state"]["equity"])
    if not equity.is_finite() or equity <= 0:
        raise ValueError("deployment_forward_observed_equity_invalid")
    values = []
    for position in book["state"]["positions"].values():
        quantity = Decimal(position["quantity"])
        value = Decimal(position["market_value"])
        if (
            not quantity.is_finite()
            or quantity < 0
            or not value.is_finite()
            or value < 0
        ):
            raise ValueError("deployment_forward_observed_position_invalid")
        if quantity > 0:
            values.append(value)
    drawdown = Decimal(book["performance"]["max_drawdown"])
    if (
        len(values) > risk["max_positions"]
        or sum(values, Decimal(0)) / equity > Decimal(risk["max_gross_weight"])
        or max(values, default=Decimal(0)) / equity > Decimal(risk["max_symbol_weight"])
        or not drawdown.is_finite()
        or drawdown < 0
        or drawdown > Decimal(risk["max_drawdown"])
    ):
        raise ValueError("deployment_forward_observed_risk_exceeds_grant")
    resolve_paper_book_costs(db, book["policy"], tuple(book["instruments"]))
    start = date.fromisoformat(binding["partition"]["sealed_start"])
    through = (
        date.fromisoformat(through_session)
        if isinstance(through_session, str)
        else through_session
    )
    calendar = observations._calendar(
        date.fromisoformat(observation_input_binding(observed["source"])["start_date"]),
        now,
    )
    if through > latest_closed_session(calendar, now=now):
        raise ValueError("deployment_forward_checkpoint_not_closed")
    expected = [
        day.isoformat() for day in _sessions(calendar) if start <= day <= through
    ]
    if (
        not expected
        or expected[-1] != through.isoformat()
        or book["evaluation_start"] != expected[0]
    ):
        raise ValueError("deployment_forward_book_start_mismatch")
    steps = [step for step in book["steps"] if step["session"] <= expected[-1]]
    if [step["session"] for step in steps] != expected:
        raise ValueError("deployment_forward_settlement_incomplete")
    publications = [
        publication
        for publication in observed["publications"]
        if publication["payload"]["reference_session"] in expected
    ]
    if sorted(p["payload"]["reference_session"] for p in publications) != expected:
        raise ValueError("deployment_forward_publication_incomplete")
    trading_dates = _sessions(calendar)
    for publication in publications:
        payload = publication["payload"]
        reference = date.fromisoformat(payload["reference_session"])
        decision = date.fromisoformat(publication["decision_session"])
        prior = [day for day in trading_dates if day < reference]
        paper_binding = payload.get("paper_book_binding", {})
        version = paper_binding.get("version")
        if (
            not prior
            or decision != prior[-1]
            or _instant(publication["published_at"])
            >= datetime.combine(reference, time(9, 30), _SHANGHAI)
            or _instant(publication["published_at"]) < _instant(book["started_at"])
            or paper_binding.get("book_id") != book["id"]
            or type(version) is not int
        ):
            raise ValueError("deployment_forward_publication_binding_invalid")
        known = [step for step in book["steps"] if step["book_version"] <= version]
        if (
            (version == 0 and payload["reference_session"] != expected[0])
            or version > 0
            and (
                not known
                or known[-1]["session"] != decision.isoformat()
                or any(
                    _instant(step["settled_at"]) > _instant(publication["published_at"])
                    for step in known
                )
            )
        ):
            raise ValueError("deployment_forward_actual_holdings_not_bound")
    prefix = {
        **book,
        "steps": steps,
        "state": steps[-1]["projection"],
        "version": steps[-1]["book_version"],
        "last_settled_session": expected[-1],
        **{
            field: [
                item for step in steps for item in step["projection"].get(field, [])
            ]
            for field in ("fills", "attempts")
        },
    }
    performance = paper_book_performance(prefix)
    health = evaluate_paper_health(performance, book["policy"].get("health_policy"))
    if health["status"] != "within_rule":
        raise ValueError("deployment_forward_health_not_ready")
    core = {
        "schema_version": "karkinos.reserved_forward_book.v1",
        "observation_id": identity,
        "book_id": book["id"],
        "reservation_id": sealed_id,
        "source_result_id": binding["candidate_result_id"],
        "source_fingerprint": content_fingerprint(observed["source"]),
        "code_fingerprint": book["code_binding"]["fingerprint"],
        "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        "deployment_scope_fingerprint": binding["deployment_scope"][
            "deployment_scope_fingerprint"
        ],
        "initial_cash": book["initial_cash"],
        "fee_schedule_binding": binding["fee_schedule"],
        "entry_board_policy": binding.get("entry_board_policy"),
        "first_session": expected[0],
        "through_session": expected[-1],
        "settled_sessions": len(steps),
        "publications_fingerprint": content_fingerprint(publications),
        "settled_steps_fingerprint": content_fingerprint(steps),
        "health": {key: health[key] for key in ("status", "policy_id", "breaches")},
        "session_equity": [
            {
                "session": step["session"],
                "equity": step["projection"]["equity"],
                "cash": step["projection"]["cash"],
                "benchmark_equity": step["projection"]
                .get("benchmark", {})
                .get("equity"),
            }
            for step in steps
        ],
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


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
        asset_class=AssetClass.FUND
        if bar.instrument.instrument_type is InstrumentType.ETF
        else AssetClass.STOCK,
        instrument_type=bar.instrument.instrument_type,
    )


def _merge_distributions(evidence_rows, *, evaluation_start):
    merged, terms, filtered = {}, {}, []
    known_periods = set()
    try:
        for evidence in evidence_rows:
            if evidence is None:
                raise ValueError("cash_dividend_evidence_required")
            events = []
            reported_periods, relevant_periods = set(), set()
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
                    reported_periods.add(key)
                    if not past:
                        relevant_periods.add(key)
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
            # Each input is the complete bound provider report for this basket.
            # A disappeared known event may be a retraction or an incomplete
            # refresh; retaining its old terms would invent continuing validity.
            # Proven-zero pre-start entitlements never enter known_periods.
            if not known_periods.issubset(reported_periods):
                raise ValueError("paper_book_corporate_action_revision_conflict")
            known_periods.update(relevant_periods)
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
        corporate_action_mode: str | None = None,
        health_policy: dict[str, Any] | None = None,
        fee_schedule_binding: dict[str, Any] | None = None,
    ):
        if not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError("paper_book_initial_cash_invalid")
        cost_inputs = (cost_assumptions or BacktestCostAssumptions()).model_dump(
            mode="json"
        )
        validated_health = (
            validate_paper_health_policy(health_policy)
            if health_policy is not None
            else None
        )
        fingerprint = content_fingerprint(
            {
                "initial_cash": str(initial_cash),
                "cost_inputs": cost_inputs,
                "corporate_action_mode": corporate_action_mode,
                "health_policy": validated_health,
                **(
                    {"fee_schedule_binding": fee_schedule_binding}
                    if fee_schedule_binding
                    else {}
                ),
            }
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
        scope = observation_deployment_scope(observation["source"])
        universe = observation["universe"]
        if any(
            item["instrument_type"] not in {"stock", "etf"} for item in universe
        ) or len({item["symbol"] for item in universe}) != len(universe):
            raise ValueError("paper_book_instrument_unsupported")
        has_etf = any(item["instrument_type"] == "etf" for item in universe)
        action_mode = corporate_action_mode or (
            "price_only" if has_etf else "reported_distributions_gross"
        )
        if action_mode not in {"price_only", "reported_distributions_gross"} or (
            has_etf and action_mode != "price_only"
        ):
            raise ValueError("paper_book_corporate_action_mode_unsupported")
        now = _instant(self.clock())
        calendar = self.observations._calendar(
            date.fromisoformat(
                observation_input_binding(observation["source"])["start_date"]
            ),
            now,
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
        _, effective_costs = resolve_paper_book_costs(
            self.db,
            {
                "cost_inputs": cost_inputs,
                **(
                    {"fee_schedule_binding": fee_schedule_binding}
                    if fee_schedule_binding
                    else {}
                ),
            },
            (item["symbol"] for item in universe),
        )
        policy = {
            "schema_version": "karkinos.research_paper_book.v1",
            "currency": "CNY",
            "replay_policy_id": PAPER_REPLAY_POLICY_ID,
            "execution_model": "forward_published_target_daily_close",
            "ordering": "session_mark_then_exits_then_entries_single_attempt"
            if scope
            else "session_then_symbol_single_attempt",
            "historical_pit_verified": False,
            "contains_simulated_fills": True,
            "observation_target_policy": observation["policy"],
            **(
                {"entry_board_policy": observation["policy"]["entry_board_policy"]}
                if "entry_board_policy" in observation["policy"]
                else {}
            ),
            "corporate_action_mode": action_mode,
            "health_policy": validated_health,
            "cost_inputs": cost_inputs,
            **(
                {"fee_schedule_binding": fee_schedule_binding}
                if fee_schedule_binding
                else {}
            ),
            "cost_assumptions": effective_costs,
            "warmup_session": earlier[-1].isoformat(),
            "max_sessions": observation["policy"]
            .get("resource_limits", {})
            .get("max_paper_sessions", 2000),
            **(
                {
                    "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
                    "deployment_scope": scope,
                    "resource_limits": observation["policy"]["resource_limits"],
                }
                if scope
                else {}
            ),
            "max_dataset_rows": observation["policy"]["max_dataset_rows"],
            "limitations": [
                *_STATE_LIMITATIONS,
                *effective_costs["limitations"],
                "Empty corporate-action responses never prove the absence of events or complete economic-return coverage.",
                "ETF model uses canonical 100-unit lots, T+1 and 10% limits; instrument-specific T+0, special limits and ETF distributions are not verified.",
            ]
            if has_etf
            else [*_STATE_LIMITATIONS, *effective_costs["limitations"]],
        }
        equal = {item["symbol"]: Decimal(1) / len(universe) for item in universe}
        benchmark_weights = build_research_target_weights(
            equal,
            **{
                name: Decimal(observation["policy"][name])
                for name in ("max_symbol_weight", "max_gross_weight")
            },
        )
        policy["benchmark"] = {
            "policy_id": "karkinos.paper.equal_weight_buy_and_hold.v1",
            "name": "Equal-weight same-universe buy-and-hold, capped by frozen observation limits",
            "target_weights": {
                key: str(value) for key, value in benchmark_weights.items()
            },
            "execution": "one_attempt_at_first_accepted_target_close",
            "activation": "first_real_published_target_accepted_after_book_start",
            "same_initial_cash_instruments_costs_and_distribution_mode": True,
            "cash_interest": "zero",
            "rebalances": False,
            "limitations": [
                "A bounded simulated comparator; not a risk-factor neutral alpha or executable venue return."
            ],
        }
        if scope:
            policy["benchmark"].update(
                policy_id="karkinos.paper.liquidity_capped_buy_and_hold.v1",
                name="Executable liquidity-ranked buy-and-hold under the frozen universe and capital limits",
                target_weights={},
                selection="first_accepted_target_decision_session_liquidity_and_costs",
            )
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
                    (
                        make_etf
                        if item["instrument_type"] == "etf"
                        else make_research_stock
                        if scope
                        else make_stock
                    )(item["symbol"], item["symbol"])
                )
                for item in universe
            },
            initial_cash=str(initial_cash),
            evaluation_start=evaluation_start,
            computation_not_before=now,
        )

    @daily_bar_dataset_read_scope(join_existing=True)
    def settle(
        self,
        observation_id,
        *,
        request_id,
        expected_version,
        dataset_id,
        automation_generation=None,
        automation_stop_requested=None,
    ):
        fingerprint = content_fingerprint(
            {
                "expected_version": expected_version,
                "dataset_id": dataset_id,
                **(
                    {"automation_generation": automation_generation}
                    if automation_generation is not None
                    else {}
                ),
            }
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
            date.fromisoformat(observation_input_binding(book["source"])["start_date"]),
            now,
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

        verified_source = None

        def read(identity, captured, rows, *, verified_parent=None):
            nonlocal verified_source
            result = read_research_observation_dataset(
                self.observations.objects,
                identity,
                instruments=tuple(
                    InstrumentKey.from_values(item["symbol"], item["instrument_type"])
                    for item in book["source"]["universe"]
                ),
                start_date=date.fromisoformat(
                    observation_input_binding(book["source"])["start_date"]
                ),
                now=_instant(captured),
                calendar_rows=rows,
                minimum_bars=book["source"]["minimum_bars"],
                deployment_scope=observation_deployment_scope(book["source"]),
                membership_after=date.fromisoformat(
                    observation_input_binding(book["source"])["end_date"]
                ),
                verified_parent=verified_parent,
            )
            if "forward_input" in book["source"]:
                verified_source = require_observation_dataset_prefix(
                    self.observations.objects,
                    book["source"],
                    result.snapshot,
                    verified_parent=verified_parent or result,
                    verified_source=verified_source,
                )
            if len(result.bars) > book["policy"]["max_dataset_rows"]:
                raise ValueError("paper_book_dataset_budget_exceeded")
            # Inspect the complete bound provider report, including terms
            # revised out of the current price window. It is still the same
            # immutable observation, with its original capture/cutoff checks.
            try:
                evidence = (
                    read_dataset_corporate_action_evidence(
                        self.observations.objects,
                        replace(
                            result.snapshot, start_date=date.min, end_date=date.max
                        ),
                        include_capture_freshness=True,
                    )
                    if book["policy"]["corporate_action_mode"] != "price_only"
                    else None
                )
            except (DatasetReaderError, OSError):
                raise ValueError(
                    "paper_book_corporate_action_evidence_unreadable"
                ) from None
            return replace(result, corporate_action_evidence=evidence)

        current_input = {"read_at": now.isoformat(), "calendar": calendar}
        current = read(dataset_id, current_input["read_at"], calendar)
        if book["policy"]["corporate_action_mode"] != "price_only":
            evidence = current.corporate_action_evidence
            if evidence is None:
                raise ValueError("cash_dividend_evidence_required")
            # Every stock needs a report captured after the latest session's
            # close. This is freshness of provider-reported evidence, never a
            # completeness claim. Historical steps retain their original inputs.
            oldest = evidence.get("oldest_captured_at")
            if oldest is None or _instant(oldest) < datetime.combine(
                end, time(15), _SHANGHAI
            ):
                raise ValueError("paper_book_corporate_action_evidence_stale")
        evidence_rows = []
        bars = []
        warmup = date.fromisoformat(book["policy"]["warmup_session"])
        dynamic_scope = observation_deployment_scope(book["source"])
        memberships = {}
        warmup_bars = []
        prior, prior_key = None, None
        for index, step in enumerate(old_steps):
            key = (
                step["dataset_id"],
                step["input"]["read_at"],
                content_fingerprint(step["input"]["calendar"]),
            )
            if key != prior_key:
                # Release the previous complete history before reopening another.
                prior = None
                prior = read(
                    step["dataset_id"],
                    step["input"]["read_at"],
                    step["input"]["calendar"],
                    verified_parent=current,
                )
                prior_key = key
            day = date.fromisoformat(step["session"])
            session_bars = tuple(bar for bar in prior.bars if bar.session_date == day)
            bars.extend(_market_event(bar) for bar in session_bars)
            if dynamic_scope:
                memberships[day] = tuple(
                    Symbol(bar.instrument.symbol) for bar in session_bars
                )
            if index == 0:
                warmup_bars = [bar for bar in prior.bars if bar.session_date == warmup]
            evidence_rows.append(prior.corporate_action_evidence)
        prior = None
        if not old_steps:
            warmup_bars = [bar for bar in current.bars if bar.session_date == warmup]
        if not dynamic_scope and len(warmup_bars) != len(book["instruments"]):
            raise ValueError("paper_book_previous_close_required")
        bars.extend(_market_event(bar) for bar in warmup_bars)
        bars.extend(
            _market_event(bar)
            for bar in current.bars
            if bar.session_date in new_sessions
        )
        evidence_rows.append(current.corporate_action_evidence)
        distributions = (
            _merge_distributions(evidence_rows, evaluation_start=start)
            if book["policy"]["corporate_action_mode"] != "price_only"
            else ()
        )
        observation = self.observations.repository.get(observation_id)
        publications = self._targets(book, observation, now, end)
        costs, effective = resolve_paper_book_costs(
            self.db,
            book["policy"],
            (key.symbol for key in current.snapshot.instruments),
        )
        if effective != book["policy"]["cost_assumptions"]:
            raise ValueError("paper_book_cost_policy_changed")
        replay_instruments = {
            Symbol(key): _restore_instrument(value)
            for key, value in book["instruments"].items()
        }
        replay_options = {}
        if dynamic_scope:
            replay_instruments = {
                Symbol(key.symbol): make_research_stock(key.symbol, key.symbol)
                for key in current.snapshot.instruments
            }
            for day in [warmup, *new_sessions]:
                memberships[day] = tuple(
                    Symbol(bar.instrument.symbol)
                    for bar in current.bars
                    if bar.session_date == day
                )
            replay_options = {
                "session_instruments": memberships,
                "max_dataset_rows": book["policy"]["max_dataset_rows"],
                "max_instruments": book["policy"]["resource_limits"]["max_instruments"],
            }
        result = replay_paper_book(
            book_id=book["id"],
            initial_cash=Decimal(book["initial_cash"]),
            instruments=replay_instruments,
            bars=bars,
            publications=publications,
            evaluation_start=start,
            through_session=end,
            cost_config=costs,
            distributions=distributions,
            **replay_options,
        )
        projections = {item["session"]: item for item in result["sessions"]}
        benchmark_policy = book["policy"].get("benchmark")
        if benchmark_policy is not None:
            first_target = min(
                publications, key=lambda item: item.reference_session, default=None
            )
            benchmark_publications = []
            if first_target is not None:
                benchmark_publications = [
                    PublishedPaperTarget(
                        id=book["id"] + ":benchmark",
                        published_at=first_target.published_at,
                        reference_session=first_target.reference_session,
                        target_weights={
                            key: Decimal(value)
                            for key, value in (
                                next(
                                    item["payload"]["benchmark_target_weights"]
                                    for item in observation["publications"]
                                    if item["id"] == first_target.id
                                )
                                if dynamic_scope
                                else benchmark_policy["target_weights"]
                            ).items()
                        },
                    )
                ]
            benchmark = replay_paper_book(
                book_id=book["id"] + ":benchmark",
                initial_cash=Decimal(book["initial_cash"]),
                instruments=replay_instruments,
                bars=bars,
                publications=benchmark_publications,
                evaluation_start=start,
                through_session=end,
                cost_config=costs,
                distributions=distributions,
                **replay_options,
            )
            for row in benchmark["sessions"]:
                projections[row["session"]]["benchmark"] = row
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
            automation_generation=automation_generation,
            automation_stop_requested=automation_stop_requested,
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
            bound_at_start = (
                published == start
                and book["policy"].get("portfolio_policy_id")
                == FORMULA_PORTFOLIO_POLICY_ID
                and publication["payload"].get("paper_book_binding", {}).get("book_id")
                == book["id"]
            )
            if not (
                start < published <= cutoff or bound_at_start and published <= cutoff
            ):
                continue
            payload = publication["payload"]
            reference = date.fromisoformat(payload["reference_session"])
            if reference > end:
                continue
            if published >= datetime.combine(reference, time(9, 30), _SHANGHAI):
                raise ValueError("paper_book_target_published_too_late")
            if observation_deployment_scope(book["source"]) is not None:
                if payload.get("portfolio_policy_id") != FORMULA_PORTFOLIO_POLICY_ID:
                    raise ValueError("paper_book_target_policy_conflict")
                frozen_entry = book["policy"].get("entry_board_policy")
                if frozen_entry is not None:
                    from server.services.account_board_permissions import (
                        entry_board_policy_symbols,
                    )

                    entries = [
                        key
                        for key, value in payload["target_weights"].items()
                        if Decimal(value) > 0
                    ]
                    if payload.get("entry_board_policy") != frozen_entry or set(
                        entries
                    ) != entry_board_policy_symbols(frozen_entry, entries):
                        raise ValueError("paper_book_entry_board_policy_conflict")
            elif set(payload["target_weights"]) != set(book["instruments"]):
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
