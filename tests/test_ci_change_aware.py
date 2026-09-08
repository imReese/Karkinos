from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
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


def test_full_ci_allows_main_and_temporary_dev_bootstrap_pushes() -> None:
    config = _load_workflow(MAIN_CI)
    triggers = config["on"]

    assert config["name"] == "CI"
    assert triggers["push"]["branches"] == ["main", "dev"]
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


def test_dev_ci_runs_selected_backend_checks_without_main_acceptance_jobs() -> None:
    config = _load_workflow(DEV_CI)
    triggers = config["on"]
    job_names = _job_names(config)

    assert config["name"] == "Dev CI"
    assert triggers["push"]["branches"] == ["dev"]
    assert triggers["pull_request"]["branches"] == ["dev"]
    assert {
        "Dev change classification",
        "Backend changed-scope tests",
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


def test_dev_and_main_have_distinct_gate_names() -> None:
    assert "Code CI gate" in _job_names(_load_workflow(MAIN_CI))
    assert "Dev CI gate" in _job_names(_load_workflow(DEV_CI))
    assert "Code CI gate" not in _job_names(_load_workflow(DEV_CI))


def test_dev_backend_scope_and_quality_bind_to_the_classified_diff() -> None:
    jobs = _load_workflow(DEV_CI)["jobs"]
    assert jobs["backend"]["if"] == "${{ needs.changes.outputs.backend == 'true' }}"
    assert jobs["python-quality"]["needs"] == "changes"
    quality = jobs["python-quality"]["steps"][-1]
    assert quality["env"]["BASE_SHA"] == "${{ needs.changes.outputs.base_sha }}"
    assert '--base "${BASE_SHA}" --head "${GITHUB_SHA}"' in quality["run"]
    classifier = jobs["changes"]["steps"][-1]
    assert "classify_dev_changes.py" in classifier["run"]
    assert "github.event.pull_request.base.sha" in classifier["env"]["BASE_SHA"]
    backend = jobs["backend"]["steps"][-1]
    assert backend["env"]["BACKEND_TESTS"] == (
        "${{ needs.changes.outputs.backend_tests }}"
    )
    assert '"--locked"' in backend["run"]
    assert '"--", *selectors' in backend["run"]


def test_dev_audits_npm_dependencies_and_keeps_historical_sha_runs() -> None:
    config = _load_workflow(DEV_CI)
    audit = config["jobs"]["dependency-audit"]["steps"]
    assert any(
        step.get("run") == "npm --prefix web audit --omit=dev --audit-level=moderate"
        for step in audit
    )
    assert any(step.get("with", {}).get("node-version") == "24.20.0" for step in audit)
    assert "github.event.pull_request.head.sha || github.sha" in (
        config["concurrency"]["group"]
    )


def _gate_results() -> dict:
    jobs = _load_workflow(DEV_CI)["jobs"]
    results = {name: {"result": "success"} for name in jobs["code-ci-gate"]["needs"]}
    results["changes"]["outputs"] = dict.fromkeys(
        ("backend", "frontend", "trading", "dependencies", "docker"), "true"
    )
    return results


def _run_gate(monkeypatch, results: dict) -> None:
    monkeypatch.setenv("RESULTS", json.dumps(results))
    step = _load_workflow(DEV_CI)["jobs"]["code-ci-gate"]["steps"][-1]
    exec(compile(step["run"], str(DEV_CI), "exec"), {})


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_dev_gate_rejects_every_unsuccessful_selected_job(monkeypatch, result) -> None:
    for job in _gate_results():
        results = _gate_results()
        results[job]["result"] = result
        with pytest.raises(SystemExit, match=job):
            _run_gate(monkeypatch, results)


def test_dev_gate_only_accepts_skips_with_an_explicit_false_scope(monkeypatch) -> None:
    all_success = _gate_results()
    _run_gate(monkeypatch, all_success)
    flags = {
        "backend": "backend",
        "frontend": "frontend",
        "trading-safety": "trading",
        "dependency-audit": "dependencies",
        "docker-runtime": "docker",
    }
    for job, flag in flags.items():
        results = copy.deepcopy(all_success)
        results[job]["result"] = "skipped"
        results["changes"]["outputs"][flag] = "false"
        _run_gate(monkeypatch, results)
        for invalid in (None, "", "False", "unknown"):
            results["changes"]["outputs"][flag] = invalid
            with pytest.raises(SystemExit, match=job):
                _run_gate(monkeypatch, results)
