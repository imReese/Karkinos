from __future__ import annotations

from pathlib import Path


def test_trading_safety_marker_covers_authority_and_integrity_boundaries() -> None:
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")
    expected = {
        "test_account_truth_gate.py",
        "test_automation_control.py",
        "test_controlled_broker_submission.py",
        "test_controlled_session_automatic_pause.py",
        "test_controlled_submission_reconciliation_clearance.py",
        "test_execution_batch_reconciliation.py",
        "test_oms_service.py",
        "test_paper_shadow_run_service.py",
        "test_strategy_broker_boundary.py",
        "test_trading_controls.py",
    }

    assert all(f'"{name}"' in conftest for name in expected)
    marker_block = conftest.split("def _is_trading_safety_test", maxsplit=1)[1]
    assert '"test_profit_discipline_smoke.py"' not in marker_block


def test_ci_has_incremental_python_quality_and_independent_trading_safety_jobs() -> (
    None
):
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Python changed-file quality" in workflow
    assert "uv run black --check" in workflow
    assert "uv run isort --check-only" in workflow
    assert "Trading safety invariants" in workflow
    assert "python -m pytest -m trading_safety" in workflow
    assert "needs: [backend, frontend, trading-safety]" in workflow
