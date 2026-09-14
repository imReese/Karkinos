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


def _named_job(config: dict, name: str) -> tuple[str, dict]:
    matches = [
        (key, job) for key, job in config["jobs"].items() if job.get("name") == name
    ]
    assert len(matches) == 1
    return matches[0]


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
    config = _workflow(".github/workflows/ci.yml")
    for event in ("pull_request", "push"):
        trigger = config["on"][event]
        assert trigger["branches"] == ["dev"]
        assert not {"paths", "paths-ignore"} & trigger.keys()
    _named_job(config, "Promotion Gate")


def test_trading_safety_always_contributes_to_promotion_gate() -> None:
    config = _workflow(".github/workflows/ci.yml")
    trading_id, trading = _named_job(config, "Trading safety invariants")
    _, gate = _named_job(config, "Promotion Gate")
    assert gate["if"] == "${{ always() }}"
    assert trading_id in gate["needs"]
    assert "if" not in trading


def test_promotion_gate_rejects_unsuccessful_dependencies_and_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, gate = _named_job(_workflow(".github/workflows/ci.yml"), "Promotion Gate")
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

    for invalid_results in ({}, None, [], "invalid"):
        monkeypatch.setenv("RESULTS", json.dumps(invalid_results))
        with pytest.raises(SystemExit):
            exec(script, {})


@pytest.mark.parametrize("filename", ["ci.yml", "nightly.yml", "governance.yml"])
def test_source_verification_and_governance_permissions_are_read_only(filename) -> None:
    config = _workflow(f".github/workflows/{filename}")
    permissions = config["permissions"]
    assert isinstance(permissions, dict)
    assert set(permissions.values()) <= {"read", "none"}
    for job in config["jobs"].values():
        effective_permissions = job.get("permissions", permissions)
        assert isinstance(effective_permissions, dict)
        assert set(effective_permissions.values()) <= {"read", "none"}


def test_only_trusted_main_promotion_jobs_have_branch_write_credentials() -> None:
    promotion = _workflow(".github/workflows/promote-dev.yml")
    permissions = promotion["permissions"]
    assert isinstance(permissions, dict)
    assert set(permissions.values()) <= {"read", "none"}
    for job in promotion["jobs"].values():
        effective_permissions = job.get("permissions", permissions)
        assert isinstance(effective_permissions, dict)
        writes = {
            key for key, value in effective_permissions.items() if value == "write"
        }
        assert writes <= {"contents"}
        if writes:
            assert "github.repository == 'imReese/Karkinos'" in job["if"]
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


def test_dev_ruleset_protects_persistent_development_history_without_bypass() -> None:
    canonical = rulesets.canonical_ruleset(_ruleset(".github/rulesets/dev.json"))
    assert canonical["target"] == "branch"
    assert canonical["enforcement"] == "active"
    assert canonical["bypass_actors"] == []
    assert canonical["conditions"]["ref_name"] == {
        "include": ["refs/heads/dev"],
        "exclude": [],
    }
    assert {"deletion", "non_fast_forward"} <= {
        rule["type"] for rule in canonical["rules"]
    }


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
