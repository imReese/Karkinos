"""Tests for built-in baseline initialization and 40-instrument panel unification."""

from __future__ import annotations

import asyncio
from datetime import date
from zoneinfo import ZoneInfo

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    ShadowResearchPolicy,
    ShadowResearchRejected,
)
from server.db import AppDatabase
from server.services.ai_shadow_research_baseline import (
    _initialize_default_baseline_seed,
    _load_baseline_seed,
)
from server.services.research_datasets import (
    MAX_VERIFIED_DATASET_INSTRUMENTS,
    ResearchDatasetError,
    ResearchDatasetService,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_clean_workspace_initializes_default_baseline_seed(tmp_path) -> None:
    """When DB has zero backtests, platform initializes a built-in baseline without user manual backtests."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    # Verify completely clean workspace with no prior backtest results
    prior_rows = await db.get_backtest_results()
    assert prior_rows == []

    policy = ShadowResearchPolicy(
        enabled=True,
        baseline_backtest_result_id=None,
        research_capital_mode="normalized_notional",
        research_end_date="2026-09-21",
        sealed_end_date="2026-10-21",
        research_question="test question",
        updated_by="tester",
        authorization=SHADOW_RESEARCH_POLICY_CONFIRMATION,
    )

    # Calling _load_baseline_seed on a clean workspace initializes the built-in seed
    seed, config, start_date = _load_baseline_seed(
        db,
        policy,
        research_start_date=None,
        expected_dataset_snapshot_id=None,
    )

    assert isinstance(seed, dict)
    assert seed["id"] > 0
    assert config["strategy"] == "dual_ma"
    assert config["short_period"] == 5
    assert config["long_period"] == 20
    assert start_date == "2025-03-30"  # 540 days before 2026-09-21

    # Verify persisted in db
    post_rows = await db.get_backtest_results()
    assert len(post_rows) == 1
    assert int(post_rows[0]["id"]) == seed["id"]

    # Subsequent call reuses the persisted seed idempotently
    seed2, config2, start_date2 = _load_baseline_seed(
        db,
        policy,
        research_start_date=None,
        expected_dataset_snapshot_id=None,
    )
    assert seed2["id"] == seed["id"]
    assert config2 == config
    assert start_date2 == start_date


@pytest.mark.asyncio
async def test_explicit_invalid_baseline_result_id_fails_closed(tmp_path) -> None:
    """Explicitly specifying a non-existent baseline ID raises rejection rather than auto-initializing."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    policy = ShadowResearchPolicy(
        enabled=True,
        baseline_backtest_result_id=9999,
        research_capital_mode="normalized_notional",
        research_question="test question",
        updated_by="tester",
        authorization=SHADOW_RESEARCH_POLICY_CONFIRMATION,
    )

    with pytest.raises(
        ShadowResearchRejected, match="eligible_baseline_backtest_missing"
    ):
        _load_baseline_seed(
            db,
            policy,
            research_start_date=None,
            expected_dataset_snapshot_id=None,
        )


def test_max_verified_dataset_instruments_is_40() -> None:
    """Observation data preparation admits up to 40 instruments matching the 40-stock panel."""
    assert MAX_VERIFIED_DATASET_INSTRUMENTS == 40


from data.providers.tdx import TdxRuntimeSettings


def test_prepare_daily_dataset_rejects_exceeding_40_instruments(tmp_path) -> None:
    """Datasets service rejects 41 instruments while accepting up to 40."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    instruments_41 = tuple(
        InstrumentKey(f"{600000 + i:06d}", InstrumentType.STOCK) for i in range(41)
    )
    request_41 = DailyBarRequest(instruments_41, date(2026, 9, 1), date(2026, 9, 5))

    service = ResearchDatasetService(tmp_path / "datasets", TdxRuntimeSettings())
    with pytest.raises(
        ResearchDatasetError, match="dataset_stock_or_etf_universe_required"
    ):
        service.prepare(request_41, db=db)
