"""Tests for built-in baseline initialization and 40-instrument panel unification."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.store import DataStore
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    ShadowResearchPolicy,
    ShadowResearchRejected,
)
from server.contracts.ai_shadow_research_qualification import (
    ShadowResearchQualificationRejected,
)
from server.db import AppDatabase
from server.services.ai_shadow import ai_shadow_research_baseline as baseline_runtime
from server.services.ai_shadow.ai_shadow_research_baseline import (
    _initialize_default_baseline_seed,
    _load_baseline_seed,
)
from server.services.ai_shadow.ai_shadow_research_qualification import (
    AiShadowResearchQualificationService,
)
from server.services.research.datasets import (
    MAX_VERIFIED_DAILY_JOB_INSTRUMENTS,
    ResearchDatasetError,
    ResearchDatasetService,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize("clock_format", ["datetime", "iso_z"])
def test_default_qualification_baseline_reads_current_clock_for_market_verification(
    tmp_path, monkeypatch, clock_format
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market = DataStore(tmp_path / "data")
    market.save_market_universe_snapshot(
        trade_date="2026-09-21",
        provider_name="deterministic_fixture",
        members=[{"symbol": "600000"}],
    )
    current = [datetime(2026, 9, 21, 10, tzinfo=timezone.utc)]

    def clock():
        value = current[0]
        return (
            value
            if clock_format == "datetime"
            else value.isoformat().replace("+00:00", "Z")
        )

    service = AiShadowResearchQualificationService(
        db=db,
        store=object(),
        daily_artifact_store=object(),
        research_store=object(),
        data_store=market,
        capture_service=None,
        account_identity_reader=lambda: None,
        reviewed_fee_schedule_resolver=lambda **_: None,
        now=clock,
    )
    policy = ShadowResearchPolicy(
        enabled=False,
        research_capital_mode="normalized_notional",
        research_end_date="2026-09-21",
        sealed_end_date="2026-10-21",
    )
    observed = []
    verify = baseline_runtime._verify_and_load_baseline_market_truth

    def record_verification(*args, **kwargs):
        observed.append(kwargs["as_of"])
        return verify(*args, **kwargs)

    monkeypatch.setattr(
        baseline_runtime, "_verify_and_load_baseline_market_truth", record_verification
    )
    for _ in range(2):
        # The default preparer executes the inherited baseline and reaches the
        # real market-truth gate; absent evidence still blocks without writes.
        with pytest.raises(
            ShadowResearchRejected, match="research_calendar_incomplete"
        ):
            service._baseline_preparer(policy, research_start_date="2026-09-21")
        assert observed[-1] == current[0]
        assert isinstance(observed[-1], datetime)
        assert observed[-1].utcoffset() is not None
        current[0] += timedelta(minutes=1)
    assert len(observed) == 2
    assert asyncio.run(db.get_backtest_results()) == []


@pytest.mark.parametrize(
    "clock_value", [datetime(2026, 9, 21, 10), "2026-09-21T10:00:00", "invalid"]
)
def test_default_qualification_baseline_rejects_invalid_clock_before_verification(
    tmp_path, monkeypatch, clock_value
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    market = DataStore(tmp_path / "data")
    market.save_market_universe_snapshot(
        trade_date="2026-09-21",
        provider_name="deterministic_fixture",
        members=[{"symbol": "600000"}],
    )
    service = AiShadowResearchQualificationService(
        db=db,
        store=object(),
        daily_artifact_store=object(),
        research_store=object(),
        data_store=market,
        capture_service=None,
        account_identity_reader=lambda: None,
        reviewed_fee_schedule_resolver=lambda **_: None,
        now=lambda: clock_value,
    )

    def unexpected_verification(*args, **kwargs):
        pytest.fail("invalid qualification clock reached market verification")

    monkeypatch.setattr(
        baseline_runtime,
        "_verify_and_load_baseline_market_truth",
        unexpected_verification,
    )
    with pytest.raises(
        ShadowResearchQualificationRejected, match="qualification_clock_invalid"
    ):
        service._baseline_preparer(
            ShadowResearchPolicy(
                enabled=False,
                research_capital_mode="normalized_notional",
                research_end_date="2026-09-21",
                sealed_end_date="2026-10-21",
            ),
            research_start_date="2026-09-21",
        )
    assert asyncio.run(db.get_backtest_results()) == []


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

    # Calling _load_baseline_seed on a clean workspace initializes the built-in seed configuration
    seed, config, start_date = _load_baseline_seed(
        db,
        policy,
        research_start_date=None,
        expected_dataset_snapshot_id=None,
    )

    assert isinstance(seed, dict)
    assert seed.get("id") is None  # Not yet persisted as an uncalculated dummy
    assert seed.get("unpersisted_seed") is True
    assert config["strategy"] == "dual_ma"
    assert config["short_period"] == 5
    assert config["long_period"] == 20
    assert start_date == "2025-03-30"  # 540 days before 2026-09-21

    # Verify that backtest_results in db remains clean with 0 unexecuted placeholder rows
    post_rows = await db.get_backtest_results()
    assert len(post_rows) == 0

    # Clean workspace missing universe raises baseline_universe_replay_missing gracefully
    from data.store import DataStore
    from server.services.ai_shadow.ai_shadow_research_qualification_support import (
        QualificationBaselinePreparer,
    )

    baseline_service = QualificationBaselinePreparer(
        db=db,
        data_store=DataStore(tmp_path / "data"),
        now=lambda: datetime(2026, 9, 21, 10, tzinfo=timezone.utc),
    )
    with pytest.raises(ShadowResearchRejected) as exc_info:
        baseline_service._prepare_baseline(policy)
    assert exc_info.value.args[0] == "baseline_universe_replay_missing"
    # Even after failed preparation, backtest_results remains unpolluted
    assert await db.get_backtest_results() == []


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


def test_verified_provider_jobs_retain_their_batch_limit() -> None:
    assert MAX_VERIFIED_DAILY_JOB_INSTRUMENTS == 100


from data.providers.tdx import TdxRuntimeSettings


def test_prepare_daily_dataset_accepts_more_than_one_provider_batch(
    tmp_path, monkeypatch
) -> None:
    """Dataset scope is independent of the provider's acquisition jobs."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    instruments_41 = tuple(
        InstrumentKey(f"{600000 + i:06d}", InstrumentType.STOCK) for i in range(41)
    )
    request_41 = DailyBarRequest(instruments_41, date(2026, 9, 1), date(2026, 9, 5))

    service = ResearchDatasetService(tmp_path / "datasets", TdxRuntimeSettings())
    called = []
    monkeypatch.setattr(TdxRuntimeSettings, "require_credentials", lambda self: None)
    monkeypatch.setattr(
        "server.services.research.datasets.verified_dataset_dates",
        lambda *_args: (date(2026, 9, 1),),
    )
    monkeypatch.setattr(
        service,
        "_prepare_in_child",
        lambda request, dates, refresh: (
            called.append(request) or {"status": "prepared"}
        ),
    )
    assert service.prepare(request_41, db=db) == {"status": "prepared"}
    assert called == [request_41]
