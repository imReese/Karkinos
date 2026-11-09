"""Real synthetic final evaluation with the explicitly deferred calendar rule.

Only market/book adapters are synthetic; the final producer, v2 comparison and
persisted evidence blocker are the real owners. No real research data is read.
"""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio

from analytics.sealed_holdout import final_research_evaluation_blocker
from backtest.result import BacktestResult
from server.contracts.content_identity import content_fingerprint
from server.services.research import research_final_evaluation as owner
from tests.server.test_research_final_calendar_timing import opt_in
from tests.server.test_research_final_evaluation import harness  # noqa: F401
from tests.server.test_research_final_statistical_v2 import v2  # noqa: F401


@pytest_asyncio.fixture
async def late_calendar_final(v2, monkeypatch):
    t = v2
    opt_in(t.binding, t)
    cash = Decimal(t.binding["initial_cash"])
    asts = {
        content_fingerprint(t.h.draft["formula_ast"]): "candidate",
        **{
            content_fingerprint(item["formula_binding"]["formula_ast"]): label
            for label, item in t.binding["formula_comparators"].items()
        },
    }
    calls = []

    def replay(**kwargs):
        calls.append(kwargs)
        label = asts.get(
            content_fingerprint(kwargs["draft"]["formula_ast"]), "frozen_baseline"
        )
        curve = (
            t.curves["candidate"]
            if label == "candidate"
            else t.curves["comparators"][label]
        )
        result = BacktestResult(
            equity_curve=[
                (datetime.fromisoformat(day), Decimal(value)) for day, value in curve
            ],
            positions={},
            initial_cash=cash,
            final_equity=Decimal(curve[-1][1]),
            fills=[],
            execution_timing={
                "evaluation_start": "2026-01-17",
                "warmup_basis": "strategy_history_only_fresh_book",
                "warmup_final_bar_targets": True,
            },
        )
        result.dataset_snapshot = t.h.full_snapshot
        result.portfolio_observations = []
        return result

    t.h.adapter.run_sealed = replay
    all_days = [f"2026-01-{i:02}" for i in range(1, 17)] + t.days
    monkeypatch.setattr(
        "server.services.market.market_universe_automation.verified_trading_dates",
        lambda *_a, **kw: [
            day
            for day in all_days
            if kw.get("start_date", "0000") <= day <= kw.get("end_date", "9999")
        ],
    )
    monkeypatch.setattr(owner, "_next_verified_session_opens", lambda *_a: {})
    monkeypatch.setattr(
        owner,
        "_reserved_execution_costs",
        lambda *_a: SimpleNamespace(commission_calc=object()),
    )
    monkeypatch.setattr(
        "server.services.research.datasets.resolve_deployment_evaluation_dataset",
        lambda *_a, **_k: {"status": "ready", "dataset_snapshot": t.h.full_snapshot},
    )
    monkeypatch.setattr(
        "server.services.research.research_paper_books.verify_reserved_forward_book",
        lambda *_a, **_k: {
            "session_equity": [
                {"session": day[:10], "equity": value}
                for day, value in t.curves["candidate"]
            ]
        },
    )

    def assessment(**kwargs):
        result = {
            "status": kwargs["uncertainty"]["status"],
            "uncertainty": kwargs["uncertainty"],
            "deployment_scope_fingerprint": t.binding["deployment_scope"][
                "deployment_scope_fingerprint"
            ],
            "risk_limits": t.sim["risk_limits"],
            "blockers": [],
            "return_basis": "synthetic-after-cost",
            "corporate_action_coverage": "synthetic",
            "membership_sessions": t.days,
            "effective_checkpoint": kwargs["uncertainty"]["effective_checkpoint"],
        }
        return {**result, "evidence_fingerprint": content_fingerprint(result)}

    monkeypatch.setattr(owner, "_deployment_assessment", assessment)
    finished = []
    monkeypatch.setattr(
        t.h.store, "finish_sealed_test", lambda *a, **kw: finished.append(kw)
    )
    t.binding["error_budget"] = {"synthetic_preconsumed_attempt": 1}
    evidence = await owner._evaluate_claimed_champion(
        research_store=t.h.store,
        source=t.h.source,
        adapter=t.h.adapter,
        now=datetime(2026, 3, 19, tzinfo=timezone.utc),
        calendar_db=t.h.db,
        row={
            "sealed_test_id": t.reserved["sealed_test_id"],
            "evidence": {"reservation": t.binding},
        },
        lease=None,
        lease_clock=lambda: datetime.now(timezone.utc),
        require_current=lambda: None,
    )
    assert len(calls) == 12
    assert finished[-1]["status"] == "completed"
    assert "effective_checkpoint" not in evidence["reservation"]
    return evidence


def _rehash(evidence):
    evidence["evidence_fingerprint"] = content_fingerprint(
        {key: value for key, value in evidence.items() if key != "evidence_fingerprint"}
    )
    return evidence


def test_real_late_calendar_final_is_admitted_without_inventing_frozen_session(
    late_calendar_final,
):
    evidence = late_calendar_final
    before = deepcopy(evidence)
    assert final_research_evaluation_blocker(evidence) is None
    assert evidence == before
    profile = evidence["reservation"]["simulation_policy"]["statistical_policy"]
    assert profile["minimum_observations"] == 60
    assert profile["maximum_drawdown"] == "0.15"
    assert (
        evidence["deployment_assessment"]["effective_checkpoint"]
        == evidence["session_curves"]["candidate"][-1][0][:10]
    )


@pytest.mark.parametrize(
    "change", ["checkpoint_rule", "inject_effective_checkpoint", "short_observations"]
)
def test_late_calendar_final_still_rejects_changed_rule_or_insufficient_observations(
    late_calendar_final, change
):
    evidence = deepcopy(late_calendar_final)
    if change == "checkpoint_rule":
        evidence["reservation"]["checkpoint_resolution"][
            "last_session_on_or_before"
        ] = "2026-03-19"
    elif change == "inject_effective_checkpoint":
        evidence["reservation"]["effective_checkpoint"] = "2026-03-17"
    else:
        evidence["session_curves"]["candidate"].pop()
        for curve in evidence["session_curves"]["comparators"].values():
            curve.pop()
    assert final_research_evaluation_blocker(_rehash(evidence)) is not None
