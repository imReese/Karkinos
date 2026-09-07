from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import yaml


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


def test_python_quality_checks_remain_identical_for_dev_and_main(monkeypatch) -> None:
    quality = runpy.run_path("scripts/ci/check_python_quality.py")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert quality["run_checks"](Path.cwd(), ["example.py"]) == 0
    assert calls == [
        [sys.executable, "-m", "ruff", "check", "--", "example.py"],
        [sys.executable, "-m", "black", "--check", "--diff", "--", "example.py"],
        [sys.executable, "-m", "isort", "--check-only", "--diff", "--", "example.py"],
        [sys.executable, "-m", "mypy"],
        [sys.executable, "tools/check_python_architecture.py"],
    ]


def test_main_ci_runs_full_safety_and_acceptance_suite() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    jobs = yaml.load(workflow, Loader=yaml.BaseLoader)["jobs"]

    assert "python -m pytest -m trading_safety" in workflow
    assert set(jobs["repository-acceptance-audit"]["needs"]) == {
        "backend",
        "frontend",
        "trading-safety",
    }
    assert "docker-runtime" in jobs
    assert "browser-safety" in jobs
    assert "dependency-audit" in jobs


def test_dev_ci_runs_trading_safety_only_for_relevant_changes() -> None:
    workflow = Path(".github/workflows/dev-ci.yml").read_text(encoding="utf-8")
    jobs = yaml.load(workflow, Loader=yaml.BaseLoader)["jobs"]

    assert "python -m pytest -m trading_safety" in workflow
    assert (
        jobs["trading-safety"]["if"]
        == "${{ needs.changes.outputs.trading == 'true' }}"
    )
    assert "repository-acceptance-audit" not in jobs
    assert "docker-runtime" not in jobs
    assert "browser-safety" not in jobs


def test_both_workflows_pin_uv_and_expose_code_ci_gate() -> None:
    for path in (".github/workflows/ci.yml", ".github/workflows/dev-ci.yml"):
        workflow = Path(path).read_text(encoding="utf-8")
        jobs = yaml.load(workflow, Loader=yaml.BaseLoader)["jobs"]
        assert 'UV_VERSION: "0.11.28"' in workflow
        assert jobs["code-ci-gate"]["name"] == "Code CI gate"
        assert jobs["code-ci-gate"]["if"] == "always()"
