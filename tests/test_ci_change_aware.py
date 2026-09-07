from __future__ import annotations

from pathlib import Path

import yaml

MAIN_CI = Path(".github/workflows/ci.yml")
DEV_CI = Path(".github/workflows/dev-ci.yml")


def _load_workflow(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _job_names(config: dict) -> set[str]:
    return {
        job["name"]
        for job in config["jobs"].values()
        if isinstance(job, dict) and "name" in job
    }


def test_main_ci_is_main_only_and_full() -> None:
    config = _load_workflow(MAIN_CI)
    triggers = config["on"]

    assert config["name"] == "CI"
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" not in triggers
    assert {
        "Backend tests",
        "Production dependency audit",
        "Trading safety invariants",
        "Frontend checks",
        "Docker runtime smoke",
        "Browser safety smoke",
        "Repository acceptance audit",
    } <= _job_names(config)


def test_dev_ci_is_incremental_and_never_runs_main_full_suite() -> None:
    config = _load_workflow(DEV_CI)
    triggers = config["on"]
    job_names = _job_names(config)

    assert config["name"] == "Dev CI"
    assert triggers["push"]["branches"] == ["dev"]
    assert triggers["pull_request"]["branches"] == ["dev"]
    assert {
        "Dev change classification",
        "Frontend changed-scope checks",
        "Trading safety changed-scope checks",
        "Dependency changed-scope audit",
    } <= job_names
    assert {
        "Backend tests",
        "Docker runtime smoke",
        "Browser safety smoke",
        "Repository acceptance audit",
    }.isdisjoint(job_names)


def test_both_workflows_expose_the_same_promotion_gate_name() -> None:
    assert "Code CI gate" in _job_names(_load_workflow(MAIN_CI))
    assert "Code CI gate" in _job_names(_load_workflow(DEV_CI))
