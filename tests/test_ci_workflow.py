from __future__ import annotations

import re
from pathlib import Path

import yaml


def _workflow(path: str) -> dict:
    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


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


def test_single_ci_workflow_owns_incremental_and_full_verification() -> None:
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
        "Production dependency audit",
        "Docker runtime smoke",
        "Browser safety smoke",
        "Workflow security",
        "Dev CI gate",
        "Full CI gate",
    } <= names

    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "not acceptance and not trading_safety" in text
    assert "zizmorcore/zizmor-action@" in text
    assert "setup-uv@" in text


def test_full_dispatch_binds_exact_dev_sha_and_base() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "test \"${GITHUB_REF}\" = refs/heads/dev" in text
    assert "test \"${GITHUB_SHA}\" = \"${DISPATCH_COMMIT_SHA}\"" in text
    assert "git merge-base --is-ancestor" in text
    assert "mode=full" in text


def test_ci_and_promotion_are_read_only_until_the_trusted_promotion_job() -> None:
    ci = _workflow(".github/workflows/ci.yml")
    assert ci["permissions"] == {"contents": "read"}

    promotion = _workflow(".github/workflows/promote-dev.yml")
    assert promotion["permissions"] == {"contents": "read"}
    assert promotion["jobs"]["select"]["permissions"] == {
        "contents": "read",
        "actions": "read",
    }
    assert promotion["jobs"]["promote"]["permissions"] == {
        "contents": "write",
        "actions": "write",
        "statuses": "write",
    }
