from __future__ import annotations

from pathlib import Path

MAIN_CI = Path(".github/workflows/ci.yml")
DEV_CI = Path(".github/workflows/dev-ci.yml")


def _main_ci() -> str:
    return MAIN_CI.read_text(encoding="utf-8")


def _dev_ci() -> str:
    return DEV_CI.read_text(encoding="utf-8")


def test_main_ci_is_main_only_and_full() -> None:
    workflow = _main_ci()

    assert "name: CI" in workflow
    assert "branches:\n      - main" in workflow
    assert "      - dev" not in workflow
    assert "pull_request:" not in workflow
    for job_name in (
        "Backend tests",
        "Production dependency audit",
        "Trading safety invariants",
        "Frontend checks",
        "Docker runtime smoke",
        "Browser safety smoke",
        "Repository acceptance audit",
    ):
        assert f"name: {job_name}" in workflow


def test_dev_ci_is_incremental_and_never_runs_main_full_suite() -> None:
    workflow = _dev_ci()

    assert "name: Dev CI" in workflow
    assert "branches:\n      - dev" in workflow
    assert "pull_request:" in workflow
    assert "Dev change classification" in workflow
    assert "git diff --name-only" in workflow
    assert "Frontend changed-scope checks" in workflow
    assert "Trading safety changed-scope checks" in workflow
    assert "Dependency changed-scope audit" in workflow
    for main_only_job in (
        "Run backend test suite",
        "Docker runtime smoke",
        "Browser safety smoke",
        "Repository acceptance audit",
    ):
        assert main_only_job not in workflow


def test_both_workflows_expose_the_same_promotion_gate_name() -> None:
    assert "name: Code CI gate" in _main_ci()
    assert "name: Code CI gate" in _dev_ci()
