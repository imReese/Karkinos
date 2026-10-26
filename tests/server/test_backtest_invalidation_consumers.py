"""Withdraw financial claims at their real read boundaries, retaining raw history."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.ai_runtime.capture import CaptureSelectionError
from server.ai_runtime.karkinos_source import _research_evidence_projection
from server.ai_runtime.strategy_research_session import StrategyResearchSessionMixin
from server.ai_runtime.strategy_research_support import build_research_evaluation_bundle
from server.contracts.ai_shadow_research_automation import ShadowResearchRejected
from server.contracts.ai_shadow_research_qualification import (
    ShadowResearchQualificationRejected,
)
from server.contracts.strategy_research import StrategyResearchRejected
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.persistence.backtest_results import backtest_row_fingerprint
from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.ai_shadow.ai_shadow_research_baseline import _load_baseline_seed
from server.services.ai_shadow.ai_shadow_research_candidate_workflow import (
    AiShadowResearchCandidateWorkflowMixin,
)
from server.services.ai_shadow.ai_shadow_research_commands import (
    _current_candidate_statuses,
    _current_daily_selections,
)
from server.services.research.research_observation_inputs import (
    ResearchObservationInputError,
    load_research_observation_source,
)
from server.services.research.strategy_promotion_support import (
    ai_shadow_readiness_binding_blockers,
)
from tests.server.test_backtest_evidence_invalidation import (
    invalidate,
    raw_row,
)
from tests.server.test_backtest_evidence_invalidation import (
    saved as saved,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["invalidated", "fingerprint_mismatch", "unavailable"]
)
async def test_capture_selection_and_comparison_reject_unusable_evidence(status):
    row = {"id": 8, "evidence_invalidation": {"status": status}}
    db = SimpleNamespace(get_backtest_result=AsyncMock(return_value=row))
    blocker = "backtest_evidence_" + status
    with pytest.raises(CaptureSelectionError, match=blocker):
        await _research_evidence_projection(
            db, tool_name="research_evidence.read", result_id=8
        )
    with pytest.raises(StrategyResearchRejected, match=blocker):
        await StrategyResearchSessionMixin._validate_saved_selection(
            SimpleNamespace(_db=db), SimpleNamespace(saved_backtest_result_id=8)
        )
    with pytest.raises(ShadowResearchRejected, match=blocker):
        await AiShadowResearchCandidateWorkflowMixin._build_comparison(
            SimpleNamespace(_db=db),
            baseline_result_id=8,
            candidate_result_id=9,
            draft={},
            critique={},
            iteration_context={},
            research_capital_mode="normalized_notional",
        )
    with pytest.raises(StrategyResearchRejected, match=blocker):
        build_research_evaluation_bundle(
            backtest_result_id=8, persisted_row=row, metrics={}
        )
    with pytest.raises(ResearchObservationInputError, match=blocker):
        load_research_observation_source(row, objects=None)


@pytest.mark.parametrize(
    "status", ["invalidated", "fingerprint_mismatch", "unavailable"]
)
def test_explicit_baseline_rejects_and_latest_seed_skips_unusable_rows(status):
    invalid = {"id": 9, "evidence_invalidation": {"status": status}}
    valid = {
        "id": 8,
        "config_json": json.dumps(
            {
                "strategy": "dual_ma",
                "assets": [{"symbol": "600000", "asset_class": "stock"}],
                "start_date": "2026-01-02",
            }
        ),
        "equity_curve_json": "[{}]",
    }
    db = SimpleNamespace(
        get_backtest_results=AsyncMock(return_value=[invalid, valid]),
        get_backtest_result=AsyncMock(
            side_effect=lambda result_id: {9: invalid, 8: valid}[result_id]
        ),
    )
    with pytest.raises(ShadowResearchRejected, match="backtest_evidence_" + status):
        _load_baseline_seed(
            db,
            SimpleNamespace(baseline_backtest_result_id=9),
            research_start_date=None,
            expected_dataset_snapshot_id=None,
        )
    seed, _, _ = _load_baseline_seed(
        db,
        SimpleNamespace(baseline_backtest_result_id=None),
        research_start_date=None,
        expected_dataset_snapshot_id=None,
    )
    assert seed is valid


@pytest.mark.parametrize("drift", [False, True])
def test_direct_sql_final_and_qualification_reads_cannot_bypass_withdrawal(
    saved, drift
):
    path, result_id, repo = saved
    invalidate(repo, result_id, backtest_row_fingerprint(raw_row(path, result_id)))
    if drift:
        with sqlite3.connect(path) as conn:
            conn.execute(
                "UPDATE backtest_results SET final_equity=final_equity+1 WHERE id=?",
                (result_id,),
            )
    original = raw_row(path, result_id)
    before = path.read_bytes()
    status = "fingerprint_mismatch" if drift else "invalidated"
    with pytest.raises(StrategyResearchRejected, match="backtest_evidence_" + status):
        StrategyResearchAuditStore(path).research_backtest_result(result_id)
    with pytest.raises(
        ShadowResearchQualificationRejected, match="backtest_evidence_" + status
    ):
        ShadowResearchStore(path).get_qualification_backtest_source(result_id)
    assert raw_row(path, result_id) == original
    assert path.read_bytes() == before


def test_valid_internal_final_source_preserves_original_fingerprint(saved):
    path, result_id, _ = saved
    original = raw_row(path, result_id)
    assert (
        StrategyResearchAuditStore(path).research_backtest_result(result_id) == original
    )


@pytest.mark.parametrize("prefix", ["baseline", "candidate"])
@pytest.mark.parametrize(
    "status", ["invalidated", "fingerprint_mismatch", "unavailable"]
)
def test_legacy_current_promotion_rechecks_both_exact_sources(prefix, status):
    binding = {prefix + "_evidence_invalidation": {"status": status}}
    db = SimpleNamespace(
        get_ai_shadow_strategy_promotion_binding_sync=lambda _: binding
    )
    assert ai_shadow_readiness_binding_blockers(
        db, {"strategy_id": "ai_formula_shadow:fixture-candidate"}
    ) == [f"ai_shadow_{prefix}_backtest_evidence_{status}"]


def test_status_removes_current_financial_claims_without_rewriting_snapshot(saved):
    path, result_id, repo = saved
    candidate = {
        "candidate_id": "fixture-candidate",
        "run_id": "fixture-run",
        "baseline_result_id": result_id,
        "candidate_result_id": result_id,
        "status": "awaiting_human_approval",
        "promotion_status": "paper_shadow_approved",
        "comparison": {
            "baseline": {"total_return": 0},
            "candidate": {"total_return": 0},
            "deltas": {"total_return": 0},
            "promotion_gate": {"status": "pass", "blockers": []},
        },
    }
    original = deepcopy(candidate)
    db = SimpleNamespace(path=path)
    valid = _current_candidate_statuses(db, [candidate])[0]
    assert valid["evidence_invalidation"] is None
    assert valid["comparison"]["promotion_gate"]["status"] == "pass"
    invalidate(repo, result_id, backtest_row_fingerprint(raw_row(path, result_id)))
    before = path.read_bytes()
    current = _current_candidate_statuses(db, [candidate])[0]
    assert current["status"] == "failed_closed"
    assert current["promotion_status"] == "blocked_by_evidence"
    assert (
        current["evidence_invalidation"]["sources"]["baseline_result_id"]["status"]
        == "invalidated"
    )
    assert current["comparison"]["promotion_gate"]["status"] == "blocked"
    assert not {"baseline", "candidate", "deltas"} & current["comparison"].keys()
    assert candidate == original
    assert path.read_bytes() == before


@pytest.mark.parametrize("withdrawn", [False, True])
def test_selection_rechecks_exact_source_beyond_the_candidate_status_page(
    saved, withdrawn
):
    path, result_id, repo = saved
    if withdrawn:
        invalidate(repo, result_id, backtest_row_fingerprint(raw_row(path, result_id)))
    candidate = {
        "candidate_id": "fixture-candidate",
        "run_id": "fixture-run",
        "baseline_result_id": result_id,
        "candidate_result_id": result_id,
        "comparison": {},
    }
    selection = {
        "run_id": "fixture-run",
        "status": "winner_selected",
        "integrity_status": "verified",
        "winner_candidate_id": "fixture-candidate",
    }
    original = deepcopy(selection)
    current = _current_daily_selections(
        SimpleNamespace(path=path),
        SimpleNamespace(get_candidate=lambda _: candidate),
        [selection],
        [],
    )[0]
    assert selection == original
    if withdrawn:
        assert current["integrity_status"] == "source_invalidated"
        assert current["winner_candidate_id"] is None
        assert current["status"] == "no_selection"
    else:
        assert current == original
