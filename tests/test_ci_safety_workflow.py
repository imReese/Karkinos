from __future__ import annotations

import json
import os
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
    marker_block = conftest.split("def _is_trading_safety_test", maxsplit=1)[1]
    assert '"test_profit_discipline_smoke.py"' not in marker_block


def test_ci_has_incremental_python_quality_and_independent_trading_safety_jobs(
    monkeypatch,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
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
    assert "Python changed-file quality" in workflow
    assert "uv run python scripts/ci/check_python_quality.py" in workflow
    assert "Trading safety invariants" in workflow
    assert "python -m pytest -m trading_safety" in workflow

    jobs = yaml.load(workflow, Loader=yaml.BaseLoader)["jobs"]
    assert set(jobs["repository-acceptance-audit"]["needs"]) == {
        "changes",
        "backend",
        "frontend",
        "trading-safety",
    }
    assert "needs.changes.outputs.docs_only == 'true'" in jobs[
        "repository-acceptance-audit"
    ]["if"]


def test_ci_pins_uv_and_requires_every_scheduled_code_ci_job_to_pass(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    expected_jobs = {
        "changes",
        "python-quality",
        "repository-contracts",
        "backend",
        "dependency-audit",
        "trading-safety",
        "frontend",
        "docker-runtime",
        "browser-safety",
        "repository-acceptance-audit",
        "secret-scan",
        "hygiene",
    }

    assert 'env:\n  UV_VERSION: "0.11.28"' in workflow
    pip_install_lines = {
        line.strip().removeprefix("run: ")
        for line in workflow.splitlines()
        if "python -m pip install" in line
    }
    assert pip_install_lines == {'python -m pip install "uv==${UV_VERSION}"'}

    jobs = yaml.load(workflow, Loader=yaml.BaseLoader)["jobs"]
    gate = jobs["code-ci-gate"]
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == expected_jobs == set(jobs) - {"code-ci-gate"}
    step = gate["steps"][0]
    assert step["env"]["CI_JOB_RESULTS"] == "${{ toJSON(needs) }}"
    assert step["shell"] == "python"

    def execute(results):
        return subprocess.run(
            [sys.executable, "-c", step["run"]],
            env={
                **os.environ,
                "CI_JOB_RESULTS": json.dumps(results),
                "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    results = {name: {"result": "success"} for name in expected_jobs}
    results["changes"]["outputs"] = {"docs_only": "false"}
    passed = execute(results)
    assert passed.returncode == 0, passed.stderr
    for name in sorted(expected_jobs):
        failed = execute({**results, name: {"result": "failure"}})
        assert failed.returncode != 0, name
        assert name in failed.stderr
