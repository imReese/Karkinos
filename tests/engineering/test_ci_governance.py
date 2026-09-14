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
    python_id, python = _named_job(config, "Python tests")
    trading = next(
        step
        for step in python["steps"]
        if step.get("name") == "Trading safety invariants"
    )
    _, gate = _named_job(config, "Promotion Gate")
    assert gate["if"] == "${{ always() }}"
    assert python_id in gate["needs"]
    assert python["needs"] == "plan"
    assert "if" not in python
    assert trading["if"] == "${{ !cancelled() }}"
    assert python.get("continue-on-error", "false") == "false"
    assert trading.get("continue-on-error", "false") == "false"


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


def test_ruleset_verifier_rejects_unobservable_bypass_actors() -> None:
    server = _ruleset(".github/rulesets/main.json")
    del server["bypass_actors"]

    with pytest.raises(
        rulesets.RulesetVerificationError,
        match="^repository_ruleset_bypass_unobservable$",
    ):
        rulesets.canonical_ruleset(server)


@pytest.mark.parametrize("scope", ["observable", "owner"])
def test_ruleset_verifier_accepts_explicitly_empty_bypass_actors(scope) -> None:
    desired = rulesets.canonical_ruleset(_ruleset(".github/rulesets/main.json"))
    actual = rulesets.canonical_ruleset({**desired, "bypass_actors": []})

    result = rulesets.verify(
        {desired["name"]: desired}, {actual["name"]: actual}, scope=scope
    )
    assert result["in_sync"]
    assert result["complete_audit"]
    assert result["unobservable_fields"] == []


@pytest.mark.parametrize("scope", ["observable", "owner"])
def test_ruleset_verifier_rejects_added_bypass_actor(scope) -> None:
    desired = rulesets.canonical_ruleset(_ruleset(".github/rulesets/main.json"))
    actual = rulesets.canonical_ruleset(
        {
            **desired,
            "bypass_actors": [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
        }
    )

    with pytest.raises(rulesets.RulesetVerificationError, match="drifted_rulesets"):
        rulesets.verify(
            {desired["name"]: desired}, {actual["name"]: actual}, scope=scope
        )


def test_observable_audit_reports_hidden_bypass_without_inventing_empty_list() -> None:
    desired = rulesets.load_desired(Path(".github/rulesets"))
    actual = json.loads(json.dumps(desired))
    del actual["main-verified-fast-forward"]["bypass_actors"]
    actual = {
        name: rulesets.canonical_ruleset(payload, scope="observable")
        for name, payload in actual.items()
    }
    assert "bypass_actors" not in actual["main-verified-fast-forward"]

    result = rulesets.verify(desired, actual, scope="observable")
    assert result["in_sync"]
    assert result["complete_audit"] is False
    assert result["unobservable_fields"] == ["bypass_actors"]
    with pytest.raises(
        rulesets.RulesetVerificationError,
        match="^repository_ruleset_bypass_unobservable$",
    ):
        rulesets.verify(desired, actual, scope="owner")


@pytest.mark.parametrize("field", ["target", "enforcement", "conditions", "rules"])
def test_observable_audit_still_rejects_visible_drift_with_hidden_bypass(field) -> None:
    desired = rulesets.load_desired(Path(".github/rulesets"))
    actual = json.loads(json.dumps(desired))
    main = actual["main-verified-fast-forward"]
    del main["bypass_actors"]
    main[field] = {
        "target": "tag",
        "enforcement": "disabled",
        "conditions": {"ref_name": {"include": ["refs/heads/other"], "exclude": []}},
        "rules": [],
    }[field]

    with pytest.raises(rulesets.RulesetVerificationError) as exc:
        rulesets.verify(desired, actual, scope="observable")
    report = json.loads(str(exc.value))
    assert report["drifted_rulesets"] == [main["name"]]
    assert report["complete_audit"] is False
    assert report["unobservable_fields"] == ["bypass_actors"]


@pytest.mark.parametrize("bypass", [None, {}, "hidden"])
def test_observable_audit_rejects_malformed_visible_bypass(bypass) -> None:
    server = _ruleset(".github/rulesets/main.json")
    server["bypass_actors"] = bypass
    with pytest.raises(
        rulesets.RulesetVerificationError,
        match="^repository_ruleset_bypass_invalid$",
    ):
        rulesets.canonical_ruleset(server, scope="observable")


@pytest.mark.parametrize("scope", [None, "owner", "observable"])
def test_ruleset_audit_cli_scope_with_hidden_api_bypass(
    scope, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    desired = rulesets.load_desired(Path(".github/rulesets"))
    summaries = [
        {"id": index, "name": name} for index, name in enumerate(desired, start=1)
    ]
    responses = {"/rulesets": summaries}
    for summary in summaries:
        detail = dict(desired[summary["name"]])
        del detail["bypass_actors"]
        responses[f"/rulesets/{summary['id']}"] = detail

    def get_json(url, token):
        return responses[url.removeprefix("https://api.github.com/repos/test/repo")]

    monkeypatch.setattr(rulesets, "_get_json", get_json)
    argv = ["--repository", "test/repo", "--api-url", "https://api.github.com"]
    if scope:
        argv.extend(["--scope", scope])
    code = rulesets.main(argv)
    output = capsys.readouterr()
    if scope == "observable":
        assert code == 0
        report = json.loads(output.out)
        assert report["scope"] == "observable"
        assert report["in_sync"]
        assert report["complete_audit"] is False
        assert report["unobservable_fields"] == ["bypass_actors"]
    else:
        assert code == 1
        assert output.err.strip() == "repository_ruleset_bypass_unobservable"
