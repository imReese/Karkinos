from __future__ import annotations

import pytest

from server.contracts.strategy_research import (
    SEALED_TEST_CONFIRMATION,
    SealedTestRequest,
    StrategyResearchRejected,
)
from server.persistence.strategy_research import StrategyResearchAuditStore


def _request(idempotency_key: str) -> SealedTestRequest:
    return SealedTestRequest(
        idempotency_key=idempotency_key,
        requested_by="human:owner",
        session_id="session-1",
        draft_id="draft-1",
        backtest_run_id="backtest-1",
        confirmation=SEALED_TEST_CONFIRMATION,
    )


def test_sealed_repository_enforces_one_time_partition_consumption(tmp_path) -> None:
    store = StrategyResearchAuditStore(tmp_path / "research.db")
    store.init()
    partition_fingerprint = "sha256:" + "a" * 64
    champion = "sha256:" + "b" * 64

    row, reused = store.create_or_get_sealed_test(
        _request("sealed-1"),
        partition_fingerprint=partition_fingerprint,
        champion_formula_fingerprint=champion,
        research_family_id="family-1",
        created_at="2026-01-21T00:00:00+00:00",
    )
    assert reused is False
    assert row["status"] == "running"

    # Idempotent retry returns the same sealed test.
    row2, reused2 = store.create_or_get_sealed_test(
        _request("sealed-1"),
        partition_fingerprint=partition_fingerprint,
        champion_formula_fingerprint=champion,
        research_family_id="family-1",
        created_at="2026-01-21T00:00:00+00:00",
    )
    assert reused2 is True
    assert row2["sealed_test_id"] == row["sealed_test_id"]

    # A different request claiming the same partition is rejected before insert.
    with pytest.raises(
        StrategyResearchRejected, match="sealed_partition_already_consumed"
    ):
        store.create_or_get_sealed_test(
            _request("sealed-2"),
            partition_fingerprint=partition_fingerprint,
            champion_formula_fingerprint=champion,
            research_family_id="family-2",
            created_at="2026-01-21T00:00:00+00:00",
        )


def test_sealed_repository_finish_round_trips_evidence(tmp_path) -> None:
    store = StrategyResearchAuditStore(tmp_path / "research.db")
    store.init()
    row, _ = store.create_or_get_sealed_test(
        _request("sealed-1"),
        partition_fingerprint="sha256:" + "a" * 64,
        champion_formula_fingerprint="sha256:" + "b" * 64,
        research_family_id="family-1",
        created_at="2026-01-21T00:00:00+00:00",
    )
    store.finish_sealed_test(
        row["sealed_test_id"],
        status="completed",
        evidence={"sealed_return": 0.02, "consumed_once": True},
        evidence_fingerprint="sha256:" + "c" * 64,
        failure_code=None,
        updated_at="2026-01-21T00:01:00+00:00",
        challenger_comparison={
            "method": "challenger_comparison",
            "champion_rank_percentile": 1.0,
        },
    )
    loaded = store.get_sealed_test(row["sealed_test_id"])
    assert loaded["status"] == "completed"
    assert loaded["evidence"] == {"sealed_return": 0.02, "consumed_once": True}
    assert loaded["challenger_comparison"] == {
        "method": "challenger_comparison",
        "champion_rank_percentile": 1.0,
    }
    assert loaded["failure_code"] is None
    listed = store.list_sealed_tests("session-1")
    assert [item["sealed_test_id"] for item in listed] == [row["sealed_test_id"]]
