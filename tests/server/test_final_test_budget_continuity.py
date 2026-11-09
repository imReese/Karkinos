"""Frozen final-test allocations survive related policy and sample changes."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta

import pytest

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.contracts.strategy_research import (
    SEALED_TEST_CONFIRMATION,
    SealedTestRequest,
    StrategyResearchRejected,
)
from server.persistence.strategy_research import StrategyResearchAuditStore

CREATED = "2026-12-01T00:00:00+00:00"


def _store(tmp_path):
    store = StrategyResearchAuditStore(tmp_path / "final-budget.sqlite3")
    store.init()
    return store


def _binding(
    name,
    *,
    period=0,
    universe=("600001",),
    family="family-a",
    trials=None,
    scope=None,
    grant=None,
    generation=None,
    alpha="0.05",
    maximum=1,
    total="0.05",
    policy_key="simulation_policy",
):
    first = date(2027, 1, 4) + timedelta(days=20 * period)
    partition = {
        "research_start": "2026-01-01",
        "research_end": (first - timedelta(days=1)).isoformat(),
        "sealed_start": first.isoformat(),
        "sealed_end": (first + timedelta(days=9)).isoformat(),
    }
    scope = scope or content_fingerprint({"universe": list(universe)})
    family_core = {
        "research_family_id": family,
        "scope": {"universe": list(universe)},
        "trial_fingerprints": trials if trials is not None else [family + "-trial"],
    }
    return {
        "source_run_id": name,
        "session_id": name + "-session",
        "draft_id": name + "-draft",
        "backtest_run_id": name + "-backtest",
        "champion_formula_fingerprint": "sha256:" + content_fingerprint(name),
        "trial_family": {
            **family_core,
            "evidence_fingerprint": content_fingerprint(family_core),
        },
        "universe": list(universe),
        "deployment_scope": {"deployment_scope_fingerprint": scope},
        "partition": partition,
        "partition_fingerprint": content_fingerprint(partition),
        "first_evaluation_session": first.isoformat(),
        "frozen_at": CREATED,
        policy_key: {
            "grant_id": grant or name + "-grant",
            "generation": generation or name + "-generation",
            "statistical_policy": {"significance_level": alpha},
            "max_final_tests": maximum,
            "total_error_budget": total,
        },
    }


def _reserve(store, binding):
    return store.reserve_research_champion(binding=binding, created_at=CREATED)


def _rows(store):
    with store._connect_readonly() as conn:
        return [
            dict(row) for row in conn.execute("SELECT * FROM ai_strategy_sealed_tests")
        ]


def _replace_frozen_binding(store, row, binding):
    """Sanitized legacy fixture: scope remains bound, allocation is unavailable."""
    evidence = {"reservation": binding}
    with store._connect(immediate=True) as conn:
        conn.execute(
            "UPDATE ai_strategy_sealed_tests SET evidence_json=?,request_fingerprint=?,"
            "evidence_fingerprint=? WHERE sealed_test_id=?",
            (
                canonical_json(evidence),
                content_fingerprint(binding),
                content_fingerprint(evidence),
                row["sealed_test_id"],
            ),
        )


@pytest.mark.parametrize(
    "relation",
    ["same_family", "shared_trial", "overlapping_assets", "same_scope", "same_grant"],
)
def test_related_new_grant_or_generation_cannot_reset_one_final_test(
    tmp_path, relation
):
    store = _store(tmp_path)
    first = _binding("first")
    _reserve(store, first)
    second = _binding("second", period=1, family="family-b", universe=("600002",))
    if relation == "same_family":
        second["trial_family"]["research_family_id"] = "family-a"
    elif relation == "shared_trial":
        second["trial_family"]["trial_fingerprints"] = ["family-a-trial", "new-trial"]
    elif relation == "overlapping_assets":
        second["universe"] = ["600001", "600002"]
    elif relation == "same_scope":
        second["deployment_scope"] = deepcopy(first["deployment_scope"])
    else:
        second["simulation_policy"]["grant_id"] = first["simulation_policy"]["grant_id"]
    before = _rows(store)
    with pytest.raises(StrategyResearchRejected, match="final_test_budget_exhausted"):
        _reserve(store, second)
    assert _rows(store) == before


@pytest.mark.parametrize("status", ["reserved", "running", "failed", "completed"])
def test_failure_or_retirement_does_not_release_consumed_final_budget(tmp_path, status):
    store = _store(tmp_path)
    first = _reserve(store, _binding("first"))
    with store._connect(immediate=True) as conn:
        conn.execute(
            "UPDATE ai_strategy_sealed_tests SET status=? WHERE sealed_test_id=?",
            (status, first["sealed_test_id"]),
        )
    before = _rows(store)
    with pytest.raises(StrategyResearchRejected, match="final_test_budget_exhausted"):
        _reserve(store, _binding("second", period=1, policy_key="publication_grant"))
    assert _rows(store) == before


def test_related_allocations_sum_once_under_current_configured_limits(tmp_path):
    store = _store(tmp_path)
    first = _reserve(store, _binding("first", alpha="0.01", maximum=2))
    second = _reserve(store, _binding("second", period=1, alpha="0.02", maximum=2))
    assert second["evidence"]["reservation"]["error_budget"] == {
        "grant_id": "second-grant",
        "generation": "second-generation",
        "attempt_count": 2,
        "allocated_alpha": "0.02",
        "error_budget_spent": "0.03",
    }
    assert store.get_sealed_test(first["sealed_test_id"]) == first
    with pytest.raises(StrategyResearchRejected, match="final_test_budget_exhausted"):
        _reserve(store, _binding("third", period=2, alpha="0.01", maximum=2))


def test_prior_larger_alpha_is_not_reset_by_new_smaller_allocation(tmp_path):
    store = _store(tmp_path)
    _reserve(store, _binding("first", alpha="0.05", maximum=1))
    # A valid new profile allows two .025 tests, but the old .05 was already spent.
    with pytest.raises(StrategyResearchRejected, match="final_test_budget_exhausted"):
        _reserve(store, _binding("second", period=1, alpha="0.025", maximum=2))


def test_scope_changes_follow_shared_history_transitively_without_double_counting(
    tmp_path,
):
    store = _store(tmp_path)
    _reserve(store, _binding("a", family="a", alpha="0.01", maximum=3))
    _reserve(
        store,
        _binding(
            "ab",
            period=1,
            universe=("600001", "600002"),
            family="ab",
            alpha="0.01",
            maximum=3,
        ),
    )
    third = _reserve(
        store,
        _binding(
            "b", period=2, universe=("600002",), family="b", alpha="0.01", maximum=3
        ),
    )
    budget = third["evidence"]["reservation"]["error_budget"]
    assert budget["attempt_count"] == 3 and budget["error_budget_spent"] == "0.03"


@pytest.mark.parametrize("missing", ["allocated_alpha", "error_budget", "policy_alpha"])
def test_related_missing_allocation_fails_closed_but_disjoint_scope_stays_usable(
    tmp_path, missing
):
    store = _store(tmp_path)
    first = _reserve(store, _binding("first"))
    legacy = deepcopy(first["evidence"]["reservation"])
    if missing == "allocated_alpha":
        legacy["error_budget"].pop("allocated_alpha")
    elif missing == "error_budget":
        legacy.pop("error_budget")
    else:
        legacy["simulation_policy"]["statistical_policy"].pop("significance_level")
    _replace_frozen_binding(store, first, legacy)
    before = _rows(store)
    with pytest.raises(
        StrategyResearchRejected, match="final_test_budget_binding_missing"
    ):
        _reserve(store, _binding("related", period=1))
    assert _rows(store) == before
    unrelated = _reserve(
        store, _binding("unrelated", period=1, family="other", universe=("600099",))
    )
    assert unrelated["evidence"]["reservation"]["error_budget"]["attempt_count"] == 1
    assert _rows(store)[0] == before[0]


def test_existing_reservation_replay_preserves_original_bytes_and_allocation(tmp_path):
    store = _store(tmp_path)
    original = _binding("legacy-compatible")
    row = _reserve(store, original)
    before = _rows(store)
    later_retry = {**original, "frozen_at": "2026-12-02T00:00:00+00:00"}
    assert (
        store.reserve_research_champion(
            binding=later_retry, created_at="2026-12-02T00:00:00+00:00"
        )
        == row
    )
    assert _reserve(store, row["evidence"]["reservation"]) == row
    assert _rows(store) == before


@pytest.mark.parametrize("bad_alpha", ["0", "NaN", "0.01"])
def test_related_allocation_cannot_be_zero_nonfinite_or_drift_from_frozen_alpha(
    tmp_path, bad_alpha
):
    store = _store(tmp_path)
    first = _reserve(store, _binding("first"))
    damaged = deepcopy(first["evidence"]["reservation"])
    damaged["error_budget"]["allocated_alpha"] = bad_alpha
    _replace_frozen_binding(store, first, damaged)
    with pytest.raises(
        StrategyResearchRejected, match="final_test_budget_binding_missing"
    ):
        _reserve(store, _binding("new-grant", period=1))


def test_related_frozen_binding_hash_drift_cannot_reset_budget(tmp_path):
    store = _store(tmp_path)
    first = _reserve(store, _binding("first"))
    with store._connect(immediate=True) as conn:
        conn.execute(
            "UPDATE ai_strategy_sealed_tests SET request_fingerprint='corrupt' "
            "WHERE sealed_test_id=?",
            (first["sealed_test_id"],),
        )
    with pytest.raises(
        StrategyResearchRejected, match="final_test_budget_binding_missing"
    ):
        _reserve(store, _binding("new-grant", period=1))


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_reservations_cannot_duplicate_or_overspend(tmp_path, same_request):
    store = _store(tmp_path)
    a = _binding("first")
    b = deepcopy(a) if same_request else _binding("second", period=1)

    def attempt(value):
        try:
            return _reserve(store, value)["sealed_test_id"]
        except StrategyResearchRejected as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, [a, b]))
    assert len(_rows(store)) == 1
    if same_request:
        assert results[0] == results[1]
    else:
        assert sum("final_test_budget_exhausted" in value for value in results) == 1


def _legacy_manual(store, source_universe):
    if source_universe is not None:
        with store._connect(immediate=True) as conn:
            conn.execute(
                "INSERT INTO ai_strategy_research_sessions "
                "(session_id,idempotency_key,request_fingerprint,request_json,selection_fingerprint,"
                "status,prompt_version,created_at,updated_at) VALUES(?,?,?,?,?,'completed','fixture',?,?)",
                (
                    "legacy-session",
                    "legacy-session",
                    "legacy-request",
                    json.dumps({"selection": {"universe": source_universe}}),
                    "legacy-selection",
                    CREATED,
                    CREATED,
                ),
            )
    return store.create_or_get_sealed_test(
        SealedTestRequest(
            idempotency_key="manual-legacy",
            requested_by="human:fixture",
            session_id="legacy-session",
            draft_id="legacy-draft",
            backtest_run_id="legacy-backtest",
            confirmation=SEALED_TEST_CONFIRMATION,
        ),
        partition_fingerprint="legacy-partition",
        champion_formula_fingerprint="legacy-formula",
        research_family_id="legacy-distinct-family",
        created_at=CREATED,
    )[0]


@pytest.mark.parametrize("source_universe", [["600001"], ["600099"], None])
def test_legacy_manual_scope_recovers_from_original_session_or_blocks_unknown(
    tmp_path, source_universe
):
    store = _store(tmp_path)
    old = _legacy_manual(store, source_universe)
    before = _rows(store)
    if source_universe == ["600099"]:
        new = _reserve(store, _binding("new", period=1))
        assert new["evidence"]["reservation"]["error_budget"]["attempt_count"] == 1
    else:
        reason = (
            "final_budget_lineage_missing"
            if source_universe is None
            else "final_test_budget_binding_missing"
        )
        with pytest.raises(StrategyResearchRejected, match=reason):
            _reserve(store, _binding("new", period=1))
        assert _rows(store) == before
    assert store.get_sealed_test(old["sealed_test_id"]) == old


@pytest.mark.parametrize("malformed", ["not-json", "[]", '"not-an-object"'])
@pytest.mark.parametrize("source_universe", [["600001"], ["600099"], None])
def test_malformed_legacy_evidence_uses_scope_before_budget_failure(
    tmp_path, malformed, source_universe
):
    store = _store(tmp_path)
    old = _legacy_manual(store, source_universe)
    with store._connect(immediate=True) as conn:
        conn.execute(
            "UPDATE ai_strategy_sealed_tests SET evidence_json=? WHERE sealed_test_id=?",
            (malformed, old["sealed_test_id"]),
        )
    before = _rows(store)
    if source_universe == ["600099"]:
        new = _reserve(store, _binding("unrelated-new", period=1))
        assert new["evidence"]["reservation"]["error_budget"]["attempt_count"] == 1
        assert _rows(store)[0] == before[0]
    else:
        reason = (
            "final_budget_lineage_missing"
            if source_universe is None
            else "final_test_budget_binding_missing"
        )
        with pytest.raises(StrategyResearchRejected, match=reason):
            _reserve(store, _binding("blocked-new", period=1))
        assert _rows(store) == before
