from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from tools import verify_repository_rulesets as rulesets


def _workflow(path: str) -> dict:
    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _ruleset(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_external_github_actions_are_pinned_to_commit_shas() -> None:
    refs: list[str] = []
    for path in sorted(Path(".github/workflows").glob("*.yml")):
        config = _workflow(str(path))
        for job in config["jobs"].values():
            for entry in (job, *job.get("steps", [])):
                ref = entry.get("uses")
                if ref and not ref.startswith("./"):
                    refs.append(ref)
    assert refs
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref) for ref in refs)


def test_single_ci_workflow_verifies_every_dev_push_and_pull_request() -> None:
    assert not Path(".github/workflows/dev-ci.yml").exists()
    config = _workflow(".github/workflows/ci.yml")
    assert set(config["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert config["on"]["pull_request"]["branches"] == ["dev"]
    assert config["on"]["push"]["branches"] == ["dev"]

    names = {job["name"] for job in config["jobs"].values()}
    assert {
        "Verification plan",
        "Python quality",
        "Repository integrity",
        "Secret scan",
        "Backend tests",
        "Trading safety invariants",
        "Frontend checks",
        "Product smoke",
        "Workflow security",
        "Promotion Gate",
        "Full CI gate",
    } <= names

    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "not acceptance" not in text
    assert '-m "not trading_safety"' not in text
    assert "--cov --cov-report=term --cov-report=xml" in text
    assert "classify_dev_changes.py" not in text
    assert "zizmorcore/zizmor-action@" in text
    assert "setup-uv@" in text


def test_promotion_gate_requires_all_checks_without_path_filters() -> None:
    config = _workflow(".github/workflows/ci.yml")
    jobs = config["jobs"]
    gate = jobs["promotion-gate"]
    assert gate["if"] == "${{ always() }}"
    assert set(gate["needs"]) == {
        "plan",
        "python-quality",
        "repository-integrity",
        "secret-scan",
        "backend",
        "trading-safety",
        "frontend",
        "product-smoke",
        "workflow-security",
    }
    for name in gate["needs"]:
        assert "if" not in jobs[name]
    assert jobs["trading-safety"]["needs"] == "plan"


def test_promotion_gate_rejects_unsuccessful_dependencies_and_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _workflow(".github/workflows/ci.yml")["jobs"]["promotion-gate"]
    script = compile(gate["steps"][0]["run"], "promotion-gate", "exec")
    successful = {name: {"result": "success"} for name in gate["needs"]}
    monkeypatch.setenv("RESULTS", json.dumps(successful))
    exec(script, {})

    for name in gate["needs"]:
        for outcome in ("failure", "cancelled", "skipped", None):
            results = {**successful, name: {"result": outcome}}
            monkeypatch.setenv("RESULTS", json.dumps(results))
            with pytest.raises(SystemExit, match=name):
                exec(script, {})

    monkeypatch.setenv("RESULTS", "{}")
    with pytest.raises(SystemExit, match="missing or invalid"):
        exec(script, {})


def test_release_compatibility_gate_requires_successful_dispatch() -> None:
    gate = _workflow(".github/workflows/ci.yml")["jobs"]["full-ci-gate"]
    assert gate["if"] == "${{ always() && github.event_name == 'workflow_dispatch' }}"
    assert gate["needs"] == "promotion-gate"
    step = gate["steps"][0]
    assert step["env"] == {"PROMOTION_RESULT": "${{ needs.promotion-gate.result }}"}
    assert step["run"] == 'test "${PROMOTION_RESULT}" = success'


def test_dispatch_binds_exact_dev_sha_and_base() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'test "${GITHUB_REF}" = refs/heads/dev' in text
    assert 'test "${GITHUB_SHA}" = "${DISPATCH_COMMIT_SHA}"' in text
    assert "git merge-base --is-ancestor" in text


def test_candidate_and_release_consume_promotion_full_ci_evidence() -> None:
    for path in (".github/workflows/candidate.yml", ".github/workflows/release.yml"):
        text = Path(path).read_text(encoding="utf-8")
        assert 'required-job "Full CI gate"' in text
        assert "--branch dev" in text
        assert "--event workflow_dispatch" in text
        assert "Code CI gate" not in text
        assert "Repository acceptance audit" not in text


def test_ci_and_promotion_are_read_only_until_the_trusted_promotion_job() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    assert ci["permissions"] == {"contents": "read"}

    promotion = _workflow(".github/workflows/promote-dev.yml")
    assert promotion["permissions"] == {"contents": "read"}
    for job in promotion["jobs"].values():
        writes = {
            key for key, value in job.get("permissions", {}).items() if value == "write"
        }
        assert writes <= {"contents"}
        if writes:
            assert "github.ref == 'refs/heads/main'" in job["if"]
            checkouts = [
                step
                for step in job["steps"]
                if step.get("uses", "").startswith("actions/checkout@")
            ]
            assert checkouts
            for checkout in checkouts:
                assert checkout["with"]["ref"] == "${{ github.sha }}"
                assert checkout["with"]["persist-credentials"] == "false"


def test_governance_workflow_is_read_only_and_outside_code_ci() -> None:
    config = _workflow(".github/workflows/governance.yml")
    assert set(config["on"]) == {"workflow_dispatch", "schedule"}
    assert config["permissions"] == {"contents": "read"}
    job = config["jobs"]["ruleset-drift"]
    assert job["permissions"] == {"contents": "read"}
    text = Path(".github/workflows/governance.yml").read_text(encoding="utf-8")
    assert "verify_repository_rulesets.py" in text
    assert "PATCH" not in text
    assert "POST" not in text


def test_main_ruleset_requires_promotion_gate_without_bypass() -> None:
    desired = _ruleset(".github/rulesets/main.json")
    canonical = rulesets.canonical_ruleset(desired)
    assert canonical["target"] == "branch"
    assert canonical["enforcement"] == "active"
    assert canonical["bypass_actors"] == []
    assert canonical["conditions"]["ref_name"] == {
        "include": ["refs/heads/main"],
        "exclude": [],
    }

    rule_map = {rule["type"]: rule for rule in canonical["rules"]}
    assert {"deletion", "non_fast_forward", "required_status_checks"} <= set(rule_map)
    required = rule_map["required_status_checks"]["parameters"]
    assert required["strict_required_status_checks_policy"] is True
    assert required["do_not_enforce_on_create"] is False
    assert required["required_status_checks"] == [
        {"context": "Promotion Gate", "integration_id": 15368},
    ]


def test_release_tag_ruleset_is_immutable_without_bypass() -> None:
    canonical = rulesets.canonical_ruleset(_ruleset(".github/rulesets/tags-v.json"))
    assert canonical["target"] == "tag"
    assert canonical["enforcement"] == "active"
    assert canonical["bypass_actors"] == []
    assert canonical["conditions"]["ref_name"] == {
        "include": ["refs/tags/v*"],
        "exclude": [],
    }
    assert {rule["type"] for rule in canonical["rules"]} == {
        "update",
        "deletion",
        "non_fast_forward",
    }


def test_ruleset_verifier_ignores_server_metadata_but_not_security_drift() -> None:
    desired = rulesets.canonical_ruleset(_ruleset(".github/rulesets/main.json"))
    server = {
        **desired,
        "id": 123,
        "source_type": "Repository",
        "current_user_can_bypass": "never",
    }
    actual = rulesets.canonical_ruleset(server)
    assert (
        rulesets.verify({desired["name"]: desired}, {actual["name"]: actual})["in_sync"]
        is True
    )

    drifted = json.loads(json.dumps(actual))
    checks = next(
        rule["parameters"]["required_status_checks"]
        for rule in drifted["rules"]
        if rule["type"] == "required_status_checks"
    )
    checks.pop()
    with pytest.raises(rulesets.RulesetVerificationError):
        rulesets.verify({desired["name"]: desired}, {drifted["name"]: drifted})
