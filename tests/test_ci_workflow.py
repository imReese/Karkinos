from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
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


def test_full_ci_protects_real_verification_layers_without_acceptance_audit() -> None:
    config = _workflow(".github/workflows/ci.yml")
    jobs = config["jobs"]
    names = {job["name"] for job in jobs.values()}

    assert {
        "Verify exact source",
        "Python changed-file quality",
        "Repository integrity",
        "Secret scan",
        "Backend tests",
        "Frontend checks",
        "Production dependency audit",
        "Docker runtime smoke",
        "Browser safety smoke",
        "Code CI gate",
    } <= names
    assert "Repository acceptance audit" not in names
    assert "Repository contract tests" not in names

    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "check_docs_integrity.py" in text
    assert "check_docs_health.py" not in text
    assert "export_acceptance_audit.py" not in text
    assert "tools.ci_reuse" not in text
    assert '-m "not acceptance"' in text


def test_release_entry_accepts_stable_semver() -> None:
    release = _workflow(".github/workflows/release.yml")
    step = release["jobs"]["verify_main_code_ci"]["steps"][0]
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={"GITHUB_REF_NAME": "v1.2.3"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "tag",
    ["v1.2.3-alpha.1", "v1.2", "1.2.3", "v01.2.3"],
)
def test_release_entry_rejects_non_stable_semver(tag: str) -> None:
    release = _workflow(".github/workflows/release.yml")
    step = release["jobs"]["verify_main_code_ci"]["steps"][0]
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={"GITHUB_REF_NAME": tag},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_release_and_candidate_verify_exact_main_code_ci() -> None:
    for path in (".github/workflows/candidate.yml", ".github/workflows/release.yml"):
        text = Path(path).read_text(encoding="utf-8")
        assert "tools/verify_release_source_ci.py" in text
        assert '--required-job "Code CI gate"' in text
        assert 'Repository acceptance audit' not in text


def test_candidate_and_release_never_persist_checkout_credentials() -> None:
    for path in (".github/workflows/candidate.yml", ".github/workflows/release.yml"):
        text = Path(path).read_text(encoding="utf-8")
        assert "persist-credentials: false" in text
        assert "AUTHORIZATION: bearer" not in text
