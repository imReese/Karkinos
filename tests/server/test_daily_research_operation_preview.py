"""Verified normalized research previews stay beside the trading plan."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from server.db import AppDatabase
from server.contracts.content_identity import content_fingerprint
from server.projections.normalized_research_operation_preview import (
    build_normalized_research_operation_preview,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.daily_research_operation_preview import (
    _next_verified_target_market_date,
    project_daily_research_operation_preview,
    resolve_latest_verified_research_operation_preview,
)
from server.services.daily_trading_plan import build_daily_trading_plan


def _formula() -> dict:
    return {
        "schema_version": "karkinos.ai.formula_ast.v1",
        "entry": {
            "op": "gt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 10},
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 9},
        },
        "position_size": {"op": "equal_weight"},
    }


def _operation_preview() -> dict:
    return build_normalized_research_operation_preview(
        formula_ast=_formula(),
        frames={
            "600001": pd.DataFrame(
                {
                    "timestamp": ["2026-08-28"],
                    "open": [12],
                    "high": [12],
                    "low": [12],
                    "close": [12],
                    "volume": [100_000],
                }
            )
        },
        dataset_snapshot_id="sha256:" + "d" * 64,
        formula_fingerprint="sha256:" + "f" * 64,
        research_window_end_date="2026-08-28",
        allocation_slots=1,
    )


def _candidate() -> dict:
    return {
        "candidate_id": "candidate-normalized-1",
        "run_id": "run-normalized-1",
        "draft_id": "draft-normalized-1",
        "critique_id": "critique-normalized-1",
        "status": "evaluated_research_only",
        "recommendation": "formula_research_candidate",
        "comparison": {
            "research_capital_mode": "normalized_notional",
            "account_qualification_status": "not_evaluated",
            "baseline_source_fingerprint": "sha256:" + "a" * 64,
            "candidate_source_fingerprint": "sha256:" + "b" * 64,
            "normalized_research_operation_preview": _operation_preview(),
            "candidate": {
                "dataset_snapshot_id": "sha256:" + "d" * 64,
                "initial_cash": 1_000_000,
                "total_return": 0.08,
                "mean_oos_return": 0.04,
                "worst_oos_return": 0.02,
                "sharpe": 1.2,
                "max_drawdown": 0.1,
                "total_cost": 1_000,
            },
            "iteration_lineage": {
                "iteration_number": 1,
                "total_iterations": 1,
                "formula_fingerprint": "sha256:" + "f" * 64,
                "parent_candidate_id": None,
                "parent_draft_id": None,
                "parent_formula_fingerprint": None,
                "iteration_context_fingerprint": "sha256:" + "c" * 64,
                "sequential_feedback_bound": True,
            },
            "promotion_gate": {"status": "blocked", "blockers": []},
        },
    }


def _draft() -> dict:
    return {
        "draft_id": "draft-normalized-1",
        "economic_hypothesis": "A deterministic normalized Formula candidate.",
        "risk_impact": "Account qualification has not been evaluated.",
        "failure_conditions": ["Frozen Formula condition no longer holds."],
        "limitations": ["Research only."],
        "anti_lookahead_assumptions": ["Signals use closed daily bars."],
        "formula_ast": _formula(),
        "formula_fingerprint": "sha256:" + "f" * 64,
        "parameter_values": {},
        "parameter_ranges": {},
        "selected_universe": ["600001"],
        "dataset_snapshot_id": "sha256:" + "d" * 64,
        "test_window": {
            "start_date": "2026-01-01",
            "end_date": "2026-08-28",
        },
        "frequency": "1d",
        "cost_model_reference": "karkinos.backtest.costs.cn_default.v1",
        "validation": {"status": "valid", "errors": []},
    }


def _record_artifacts(
    tmp_path: Path,
    *,
    draft_identity_override: tuple[str, str] | None = None,
) -> tuple[AppDatabase, dict]:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    _seed_verified_calendar(database)
    store = DailyStrategyArtifactStore(
        database.path,
        tmp_path / "strategy-research-backups",
    )
    draft = _draft()
    if draft_identity_override is not None:
        draft[draft_identity_override[0]] = draft_identity_override[1]
    result = store.record_daily_artifacts(
        run={
            "run_id": "run-normalized-1",
            "market_date": "2026-08-28",
            "input_fingerprint": "sha256:" + "e" * 64,
        },
        candidates=[_candidate()],
        drafts=[draft],
        expected_candidate_count=1,
        run_status="completed",
        created_at="2026-08-28T08:30:00+00:00",
    )
    return database, result


def _seed_verified_calendar(database: AppDatabase) -> None:
    _seed_verified_calendar_year(
        database,
        year=2026,
        trading_dates={"2026-08-28", "2026-08-31"},
    )


def _seed_verified_calendar_year(
    database: AppDatabase,
    *,
    year: int,
    trading_dates: set[str],
) -> None:
    current = date(year, 1, 1)
    days = []
    while current.year == year:
        market_date = current.isoformat()
        trading = market_date in trading_dates
        days.append(
            {
                "date": market_date,
                "is_trading_day": trading,
                "day_type": "trading_day" if trading else "closed",
                "reason_code": "trading_day" if trading else "closed",
            }
        )
        current += timedelta(days=1)
    database.upsert_market_calendar_snapshot_sync(
        {
            "exchange": "SSE",
            "year": year,
            "provider": "fixture",
            "schema_version": "karkinos.market_calendar.v1",
            "status": "available",
            "trading_day_count": len(trading_dates),
            "closed_day_count": len(days) - len(trading_dates),
            "source_fingerprint": "a" * 64,
            "days": days,
        }
    )
    database.update_market_calendar_verification_sync(
        exchange="SSE",
        year=year,
        source_fingerprint="a" * 64,
        verification_status="verified",
        official_source_url="https://example.test/sse-calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_latest_verified_selection_and_backup_publish_read_only_preview(
    tmp_path: Path,
) -> None:
    database, result = _record_artifacts(tmp_path)

    preview = resolve_latest_verified_research_operation_preview(
        database,
        plan_date="2026-08-31",
    )

    assert result["selection"]["status"] == "no_selection"
    assert preview["status"] == "available"
    assert preview["target_market_date"] == "2026-08-31"
    assert preview["market_calendar_evidence_refs"]
    assert preview["research_winner_candidate_id"] == "candidate-normalized-1"
    assert preview["dataset_snapshot_id"] == "sha256:" + "d" * 64
    assert preview["formula_fingerprint"] == "sha256:" + "f" * 64
    assert preview["operations"][0]["operation"] == "buy_candidate"
    assert preview["operations"][0]["target_weight"] == 1.0
    assert preview["account_qualification_status"] == "not_evaluated"
    assert preview["account_positions_evaluated"] is False
    assert preview["read_only"] is True
    assert preview["executable"] is False
    assert preview["authorizes_order_creation"] is False
    assert preview["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_preview_is_visible_on_research_close_date_before_next_session(
    tmp_path: Path,
) -> None:
    database, _ = _record_artifacts(tmp_path)

    preview = resolve_latest_verified_research_operation_preview(
        database,
        plan_date="2026-08-28",
    )

    assert preview["status"] == "available"
    assert preview["market_date"] == "2026-08-28"
    assert preview["target_market_date"] == "2026-08-31"
    assert preview["operations"][0]["operation"] == "buy_candidate"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_backup_drift_makes_research_operation_preview_unavailable(
    tmp_path: Path,
) -> None:
    database, result = _record_artifacts(tmp_path)
    backup_path = (
        tmp_path / "strategy-research-backups" / result["backup"]["relative_path"]
    )
    backup_path.write_text("{}\n", encoding="utf-8")

    preview = resolve_latest_verified_research_operation_preview(
        database,
        plan_date="2026-08-31",
    )

    assert preview["status"] == "unavailable"
    assert preview["operations"] == []
    assert preview["authorizes_order_creation"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize("identity", ["formula_fingerprint", "dataset_snapshot_id"])
def test_verified_backup_winner_identity_mismatch_fails_closed(
    tmp_path: Path,
    identity: str,
) -> None:
    database, _ = _record_artifacts(
        tmp_path,
        draft_identity_override=(identity, "sha256:" + "9" * 64),
    )

    preview = resolve_latest_verified_research_operation_preview(
        database,
        plan_date="2026-08-31",
    )

    assert preview["status"] == "unavailable"
    assert preview["operations"] == []
    assert preview["authorizes_order_creation"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_public_projection_rejects_rehashed_extra_or_executable_fields(
    tmp_path: Path,
) -> None:
    database, _ = _record_artifacts(tmp_path)
    preview = resolve_latest_verified_research_operation_preview(
        database,
        plan_date="2026-08-31",
    )
    assert project_daily_research_operation_preview(preview) == preview

    extra = deepcopy(preview)
    extra["account_id"] = "private-account"
    core = dict(extra)
    core.pop("evidence_fingerprint")
    extra["evidence_fingerprint"] = content_fingerprint(core)
    assert project_daily_research_operation_preview(extra) is None

    executable = deepcopy(preview)
    executable["operations"][0]["executable"] = True
    core = dict(executable)
    core.pop("evidence_fingerprint")
    executable["evidence_fingerprint"] = content_fingerprint(core)
    assert project_daily_research_operation_preview(executable) is None


@pytest.mark.unit
@pytest.mark.trading_safety
def test_preview_expires_after_exact_next_verified_market_date(tmp_path: Path) -> None:
    database, _ = _record_artifacts(tmp_path)

    preview = resolve_latest_verified_research_operation_preview(
        database,
        plan_date="2026-09-01",
    )

    assert preview["status"] == "unavailable"
    assert preview["target_market_date"] == "2026-08-31"
    assert preview["operations"] == []
    assert preview["blockers"] == [
        "research_operation_preview_outside_target_market_date"
    ]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_next_verified_market_date_crosses_year_only_with_verified_calendar(
    tmp_path: Path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    _seed_verified_calendar_year(
        database,
        year=2026,
        trading_dates={"2026-12-31"},
    )
    _seed_verified_calendar_year(
        database,
        year=2027,
        trading_dates={"2027-01-04"},
    )

    target, evidence_refs = _next_verified_target_market_date(
        database,
        selection_market_date="2026-12-31",
    )

    assert target == "2027-01-04"
    assert len(evidence_refs) == 2
    assert evidence_refs[0].startswith("market_calendar:SSE:2026:")
    assert evidence_refs[1].startswith("market_calendar:SSE:2027:")


@pytest.mark.unit
@pytest.mark.trading_safety
def test_account_truth_block_does_not_hide_or_promote_independent_research_preview(
    tmp_path: Path,
) -> None:
    database, _ = _record_artifacts(tmp_path)
    research_preview = resolve_latest_verified_research_operation_preview(
        database,
        plan_date="2026-08-31",
    )

    plan = build_daily_trading_plan(
        decision_payload={
            "decision_date": "2026-08-31",
            "generated_at": "2026-08-31T09:35:00+08:00",
            "decision": "no_action",
            "summary": {
                "candidate_count": 0,
                "portfolio": {"cash": 0, "total_equity": 0},
                "account_truth": {"gate_status": "blocked"},
                "market_data": {"source_health": "live"},
            },
            "candidates": [],
        },
        config=SimpleNamespace(),
        positions={},
        research_operation_preview=research_preview,
    )

    assert plan["candidate_pool_count"] == 0
    assert plan["blocked_count"] == 0
    assert plan["order_intents"] == []
    assert plan["research_operation_preview"]["status"] == "available"
    assert plan["research_operation_preview"]["operations"][0]["operation"] == (
        "buy_candidate"
    )
    assert "research_operation_preview" not in plan["order_intents"]
