from __future__ import annotations

import json

import pytest

from tools import verify_repository_rulesets as rulesets


def _ruleset(name: str) -> dict:
    return {
        "name": name,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": [f"refs/heads/{name}"], "exclude": []}},
        "rules": [{"type": "deletion"}],
        "bypass_actors": [],
    }


def test_verifier_rejects_unexpected_server_rulesets_and_reports_them() -> None:
    desired_rule = _ruleset("expected")
    unexpected_rule = _ruleset("unexpected")
    desired = {"expected": desired_rule}
    actual = {
        "expected": desired_rule,
        "unexpected": unexpected_rule,
    }

    with pytest.raises(rulesets.RulesetVerificationError) as exc:
        rulesets.verify(desired, actual)

    report = json.loads(str(exc.value))
    assert report["missing_rulesets"] == []
    assert report["drifted_rulesets"] == []
    assert report["unexpected_rulesets"] == ["unexpected"]
    assert report["in_sync"] is False
