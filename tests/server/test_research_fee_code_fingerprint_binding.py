"""Verification of fee implementation file bindings in research code fingerprints.

Ensures that modifications to real fee calculation, policy, rounding, and
reconciliation logic in server/services/account/fees/ properly trigger code
fingerprint invalidation and execution blockers across observations, paper
books, and final evaluation, while unrelated documentation files do not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.contracts.content_identity import content_fingerprint
from server.contracts.strategy_research import StrategyResearchRejected
from server.services.research.research_final_evaluation import (
    FINAL_EVALUATION_SCHEMA,
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
    require_final_reservation,
    sealed_execution_code_binding,
)
from server.services.research.research_observations import observation_code_binding
from server.services.research.research_paper_books import paper_book_code_binding

_FEE_IMPLEMENTATION_FILES = (
    "server/services/account/fees/commission.py",
    "server/services/account/fees/policy.py",
    "server/services/account/fees/workflows.py",
    "server/services/account/fees/reconciliation.py",
    "server/services/account/fees/repository.py",
    "server/services/account/fees/__init__.py",
    "server/services/account/reviewed_fee_schedule_reconciliation.py",
    "server/contracts/reviewed_fee_schedule.py",
)


def test_fee_implementation_files_included_in_all_code_bindings():
    """Verify that actual fee calculation and policy files are explicitly registered."""
    obs_binding = observation_code_binding()
    paper_binding = paper_book_code_binding()
    final_binding = sealed_execution_code_binding()

    for file_path in _FEE_IMPLEMENTATION_FILES:
        assert file_path in obs_binding["files"], (
            f"Missing {file_path} in observation_code_binding"
        )
        assert file_path in paper_binding["files"], (
            f"Missing {file_path} in paper_book_code_binding"
        )
        assert file_path in final_binding["files"], (
            f"Missing {file_path} in sealed_execution_code_binding"
        )


@pytest.mark.parametrize(
    "fee_file",
    [
        "server/services/account/fees/commission.py",
        "server/services/account/fees/policy.py",
        "server/services/account/fees/workflows.py",
        "server/services/account/fees/reconciliation.py",
        "server/services/account/fees/repository.py",
    ],
)
def test_modifying_fee_implementation_changes_all_fingerprints(monkeypatch, fee_file):
    """Real fee implementation edits must invalidate observation, paper, and final fingerprints."""
    obs_base = observation_code_binding()
    paper_base = paper_book_code_binding()
    final_base = sealed_execution_code_binding()

    original_read_bytes = Path.read_bytes

    def patched_read_bytes(self: Path) -> bytes:
        content = original_read_bytes(self)
        if str(self).replace("\\", "/").endswith(fee_file):
            return content + b"\n# simulated_fee_policy_or_rounding_change\n"
        return content

    monkeypatch.setattr(Path, "read_bytes", patched_read_bytes)

    obs_modified = observation_code_binding()
    paper_modified = paper_book_code_binding()
    final_modified = sealed_execution_code_binding()

    # Fingerprints must differ
    assert obs_modified["fingerprint"] != obs_base["fingerprint"]
    assert paper_modified["fingerprint"] != paper_base["fingerprint"]
    assert final_modified["fingerprint"] != final_base["fingerprint"]

    # The specific file hash changed
    assert obs_modified["files"][fee_file] != obs_base["files"][fee_file]
    assert paper_modified["files"][fee_file] != paper_base["files"][fee_file]
    assert final_modified["files"][fee_file] != final_base["files"][fee_file]

    # Other files remain identical
    for file_key in obs_base["files"]:
        if file_key != fee_file:
            assert obs_modified["files"][file_key] == obs_base["files"][file_key]


def test_modifying_unrelated_docs_does_not_change_fingerprints(monkeypatch):
    """Documentation or unrelated file changes must not invalidate frozen research bindings."""
    obs_base = observation_code_binding()
    paper_base = paper_book_code_binding()
    final_base = sealed_execution_code_binding()

    original_read_bytes = Path.read_bytes

    def patched_read_bytes(self: Path) -> bytes:
        content = original_read_bytes(self)
        if str(self).replace("\\", "/").endswith("docs/README.md"):
            return content + b"\n# docs edit\n"
        return content

    monkeypatch.setattr(Path, "read_bytes", patched_read_bytes)

    assert observation_code_binding()["fingerprint"] == obs_base["fingerprint"]
    assert paper_book_code_binding()["fingerprint"] == paper_base["fingerprint"]
    assert sealed_execution_code_binding()["fingerprint"] == final_base["fingerprint"]


def test_fee_modification_triggers_code_blockers(monkeypatch):
    """Modifying fee commission logic triggers code change blockers across services."""
    baseline_obs_binding = observation_code_binding()
    baseline_paper_binding = paper_book_code_binding()
    baseline_final_binding = sealed_execution_code_binding()

    # Simulate modifying server/services/account/fees/commission.py
    original_read_bytes = Path.read_bytes

    def patched_read_bytes(self: Path) -> bytes:
        content = original_read_bytes(self)
        if (
            str(self)
            .replace("\\", "/")
            .endswith("server/services/account/fees/commission.py")
        ):
            return content + b"\n# commission rate changed\n"
        return content

    monkeypatch.setattr(Path, "read_bytes", patched_read_bytes)

    # 1. Final evaluation blocker: require_final_reservation checks code_binding
    reservation_binding = {
        "schema_version": FINAL_EVALUATION_SCHEMA,
        "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
        "candidate_id": "cand_1",
        "selection_fingerprint": "sel_fp",
        "champion_formula_fingerprint": "sha256:"
        + content_fingerprint({"kind": "leaf"}),
        "trial_family": "trials",
        "sealed_book_policy": "fresh_equal_notional_history_warmup_final_bar_target.v1",
        "code_binding": baseline_final_binding,
    }
    reservation_row = {
        "request_fingerprint": content_fingerprint(reservation_binding),
        "evidence": {"reservation": reservation_binding},
    }

    class FakeStore:
        def research_champion_reservation(self, run_id):
            return reservation_row

        def research_trial_family(self, selection, **kwargs):
            return "trials"

    dummy_source = type(
        "Source",
        (),
        {
            "source_candidate": {"run_id": "run_1", "candidate_id": "cand_1"},
            "source_selection": type("Sel", (), {"fingerprint": "sel_fp"})(),
            "source_draft": {"formula_ast": {"kind": "leaf"}},
        },
    )()

    with pytest.raises(
        StrategyResearchRejected, match="independent_final_execution_code_changed"
    ):
        require_final_reservation(
            research_store=FakeStore(),
            source=dummy_source,
            now=datetime.now(timezone.utc),
        )

    # 2. Observation code comparison: past observation with baseline binding is detected as changed
    current_obs_binding = observation_code_binding()
    assert baseline_obs_binding != current_obs_binding
    assert baseline_obs_binding["fingerprint"] != current_obs_binding["fingerprint"]

    # 3. Paper book code comparison: past paper book with baseline binding is detected as changed
    current_paper_binding = paper_book_code_binding()
    assert baseline_paper_binding != current_paper_binding
    assert baseline_paper_binding["fingerprint"] != current_paper_binding["fingerprint"]
