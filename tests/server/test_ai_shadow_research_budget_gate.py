from __future__ import annotations

import pytest

from server.services.ai_shadow_research_automation import (
    qualification_allows_new_research,
)
from server.services.ai_shadow_research_qualification_support import (
    qualification_selection,
)


def _blocked_candidate(*blockers: str) -> dict:
    return {
        "qualification_candidate_id": "qualification-candidate-1",
        "source_candidate_id": "source-candidate-1",
        "status": "blocked",
        "recommendation": "keep_researching",
        "comparison": {
            "promotion_gate": {
                "status": "blocked",
                "blockers": list(blockers),
            }
        },
    }


@pytest.mark.unit
@pytest.mark.trading_safety
def test_quality_only_qualification_failure_allows_another_paid_research_batch() -> (
    None
):
    terminal = qualification_selection(
        qualification_run_id="qualification-run-1",
        source_run_id="source-run-1",
        market_date="2026-09-18",
        candidates=[
            _blocked_candidate(
                "candidate_after_cost_oos_excess_not_positive",
                "candidate_parameter_robustness_not_passing",
            )
        ],
        replay_failed=False,
    )

    retry = terminal["selection"]["research_retry"]
    assert terminal["run_status"] == "blocked"
    assert retry == {
        "recommended": True,
        "reason": "candidate_quality_can_improve",
        "research_addressable_blockers": [
            "candidate_after_cost_oos_excess_not_positive",
            "candidate_parameter_robustness_not_passing",
        ],
        "systemic_blockers": [],
    }
    assert qualification_allows_new_research(
        {
            "status": "blocked",
            "blockers": ["no_candidate_passed_account_qualification"],
            "run": {
                "blockers": ["no_candidate_passed_account_qualification"],
                "research_retry": retry,
            },
        },
        has_promoted_strategy=False,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_systemic_qualification_failure_pauses_paid_research_until_fixed() -> None:
    terminal = qualification_selection(
        qualification_run_id="qualification-run-1",
        source_run_id="source-run-1",
        market_date="2026-09-18",
        candidates=[
            _blocked_candidate(
                "candidate_after_cost_oos_excess_not_positive",
                "baseline_fee_or_tax_evidence_incomplete",
            )
        ],
        replay_failed=False,
    )

    retry = terminal["selection"]["research_retry"]
    assert retry["recommended"] is False
    assert retry["reason"] == "systemic_evidence_must_be_fixed"
    assert retry["research_addressable_blockers"] == [
        "candidate_after_cost_oos_excess_not_positive"
    ]
    assert retry["systemic_blockers"] == ["baseline_fee_or_tax_evidence_incomplete"]
    assert not qualification_allows_new_research(
        {
            "status": "blocked",
            "blockers": ["no_candidate_passed_account_qualification"],
            "run": {
                "blockers": ["no_candidate_passed_account_qualification"],
                "research_retry": retry,
            },
        },
        has_promoted_strategy=False,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_unknown_or_operational_qualification_blockers_do_not_spend_provider_budget() -> (
    None
):
    assert qualification_allows_new_research(
        {
            "status": "blocked",
            "failure_code": "qualification_verified_source_backlog_empty",
            "blockers": ["qualification_verified_source_backlog_empty"],
        },
        has_promoted_strategy=False,
    )
    assert not qualification_allows_new_research(
        {
            "status": "blocked",
            "failure_code": "qualification_reviewed_fee_schedule_drift",
            "blockers": ["qualification_reviewed_fee_schedule_drift"],
        },
        has_promoted_strategy=False,
    )
    assert not qualification_allows_new_research(
        {
            "status": "blocked",
            "blockers": ["no_candidate_passed_account_qualification"],
            "run": {
                "blockers": ["no_candidate_passed_account_qualification"],
            },
        },
        has_promoted_strategy=False,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_completed_qualification_pauses_research_until_winner_is_promoted() -> None:
    result = {"status": "completed", "run": {"status": "completed"}}
    assert not qualification_allows_new_research(
        result,
        has_promoted_strategy=False,
    )
    assert qualification_allows_new_research(
        result,
        has_promoted_strategy=True,
    )
