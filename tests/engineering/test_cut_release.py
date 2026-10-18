from __future__ import annotations

import json
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import cut_release


def _commit_version(
    root: Path,
    version: str,
    *,
    web_version: str | None = None,
    lock_version: str | None = None,
) -> str:
    (root / "server").mkdir(exist_ok=True)
    (root / "server/__init__.py").write_text(
        f'__version__ = "{version}"\nraise AssertionError("source must not execute")\n'
    )
    (root / "web").mkdir(exist_ok=True)
    (root / "web/package.json").write_text(
        json.dumps({"version": web_version or version})
    )
    (root / "web/package-lock.json").write_text(
        json.dumps({"version": lock_version or version})
    )
    subprocess.run(["git", "add", "server", "web"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic Release",
            "-c",
            "user.email=release@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "-qm",
            f"Version {version}",
        ],
        cwd=root,
        check=True,
    )
    return cut_release.resolve_commit_sha(root)


@pytest.fixture
def release_history(tmp_path):
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main"], cwd=tmp_path, check=True
    )
    old = _commit_version(tmp_path, "0.4.0")
    current = _commit_version(tmp_path, "0.4.1")
    return tmp_path, old, current


@pytest.fixture
def published_candidate(monkeypatch):
    """Keep local Git reads real, but never contact or mutate any remote/tag."""
    run = subprocess.run
    writes = []

    def run_without_publication(command, **kwargs):
        if command[:2] in (["git", "tag"], ["git", "push"]):
            writes.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return run(command, **kwargs)

    monkeypatch.setattr(cut_release.subprocess, "run", run_without_publication)
    monkeypatch.setattr(cut_release, "get_github_token", lambda: None)
    monkeypatch.setattr(
        cut_release, "verify_origin_main_ancestry", lambda *a, **k: None
    )
    monkeypatch.setattr(cut_release, "check_remote_tag", lambda *a, **k: None)
    monkeypatch.setattr(
        cut_release,
        "query_candidate_workflow",
        lambda *a, **k: {"run_id": 123, "run_url": "https://example.invalid/candidate"},
    )
    return writes


@pytest.mark.parametrize(("tag", "success"), [("v0.4.1", False), ("v0.4.0", True)])
def test_explicit_commit_checks_target_version_before_publication(
    release_history, published_candidate, capsys, tag, success
):
    root, old, current = release_history
    assert old != current

    status = cut_release.main(
        [tag, "--commit", old, "--repo-root", str(root), "--no-fetch"]
    )

    assert status == (0 if success else 1)
    if success:
        assert published_candidate == [
            ["git", "tag", "-a", tag, old, "-m", f"Release version {tag[1:]}"],
            ["git", "push", "origin", tag],
        ]
    else:
        assert "version_mismatch: server/__init__.py" in capsys.readouterr().err
        assert published_candidate == []


def test_target_lock_version_must_match_before_publication(
    release_history, published_candidate, capsys
):
    root, _, _ = release_history
    target = _commit_version(root, "0.4.1", lock_version="0.4.0")

    status = cut_release.main(
        ["v0.4.1", "--commit", target, "--repo-root", str(root), "--no-fetch"]
    )

    assert status == 1
    assert "version_mismatch: web/package-lock.json" in capsys.readouterr().err
    assert published_candidate == []


def test_default_head_dry_run_keeps_publication_disabled(
    release_history, published_candidate, capsys
):
    root, _, current = release_history

    status = cut_release.main(
        ["v0.4.1", "--repo-root", str(root), "--no-fetch", "--dry-run"]
    )

    assert status == 0
    result = json.loads(capsys.readouterr().out)
    assert result["commit_sha"] == current
    assert result["dry_run"] is True
    assert published_candidate == []


def test_validate_version_accepts_valid_semver():
    assert cut_release.validate_version("v0.4.0") == "0.4.0"
    assert cut_release.validate_version("v1.0.0") == "1.0.0"
    assert cut_release.validate_version("v12.34.56") == "12.34.56"


@pytest.mark.parametrize(
    "invalid_tag",
    [
        "0.4.0",
        "v0.4",
        "v0.4.0.0",
        "v0.4.0-rc1",
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
        "release-0.4.0",
        "",
    ],
)
def test_validate_version_rejects_invalid_semver(invalid_tag):
    with pytest.raises(cut_release.CutReleaseError, match="invalid_tag_format"):
        cut_release.validate_version(invalid_tag)


def test_check_working_tree_clean_passes_when_status_empty():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        cut_release.check_working_tree_clean(Path("/tmp"))
        mock_run.assert_called_once_with(
            ["git", "status", "--porcelain"],
            cwd=Path("/tmp"),
            capture_output=True,
            text=True,
            check=True,
        )


def test_check_working_tree_clean_fails_when_dirty():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout=" M server/__init__.py\n", returncode=0
        )
        with pytest.raises(cut_release.CutReleaseError, match="working_tree_dirty"):
            cut_release.check_working_tree_clean(Path("/tmp"))


def test_check_codebase_versions_passes_when_in_sync(release_history):
    root, old, _ = release_history
    cut_release.check_codebase_versions(root, "0.4.0", commit_sha=old)


def test_check_codebase_versions_fails_on_server_mismatch(release_history):
    root, old, _ = release_history
    with pytest.raises(
        cut_release.CutReleaseError, match="version_mismatch: server/__init__.py"
    ):
        cut_release.check_codebase_versions(root, "0.4.1", commit_sha=old)


def test_check_codebase_versions_fails_on_web_mismatch(release_history):
    root, _, _ = release_history
    target = _commit_version(root, "0.4.0", web_version="0.3.9")
    with pytest.raises(
        cut_release.CutReleaseError, match="version_mismatch: web/package.json"
    ):
        cut_release.check_codebase_versions(root, "0.4.0", commit_sha=target)


def test_verify_origin_main_ancestry_passes_when_ancestor():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        cut_release.verify_origin_main_ancestry(Path("/tmp"), "a" * 40, fetch=False)
        mock_run.assert_called_once_with(
            ["git", "merge-base", "--is-ancestor", "a" * 40, "origin/main"],
            cwd=Path("/tmp"),
            capture_output=True,
            text=True,
        )


def test_verify_origin_main_ancestry_fails_when_not_ancestor():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        with pytest.raises(
            cut_release.CutReleaseError, match="commit_not_in_origin_main"
        ):
            cut_release.verify_origin_main_ancestry(Path("/tmp"), "a" * 40, fetch=False)


def test_query_candidate_workflow_fails_when_run_missing():
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"workflow_runs": []}).encode("utf-8")
    fake_response.__enter__.return_value = fake_response

    with patch("urllib.request.urlopen", return_value=fake_response):
        with pytest.raises(
            cut_release.CutReleaseError, match="candidate_workflow_not_found"
        ):
            cut_release.query_candidate_workflow("test/repo", "a" * 40)


def test_query_candidate_workflow_fails_when_pending():
    fake_run = {
        "id": 12345,
        "head_sha": "a" * 40,
        "head_branch": "main",
        "status": "in_progress",
        "conclusion": None,
    }
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"workflow_runs": [fake_run]}).encode(
        "utf-8"
    )
    fake_response.__enter__.return_value = fake_response

    with patch("urllib.request.urlopen", return_value=fake_response):
        with pytest.raises(
            cut_release.CutReleaseError, match="candidate_workflow_in_progress"
        ):
            cut_release.query_candidate_workflow("test/repo", "a" * 40)


def test_query_candidate_workflow_fails_when_failed():
    fake_run = {
        "id": 12345,
        "head_sha": "a" * 40,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "failure",
    }
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"workflow_runs": [fake_run]}).encode(
        "utf-8"
    )
    fake_response.__enter__.return_value = fake_response

    with patch("urllib.request.urlopen", return_value=fake_response):
        with pytest.raises(
            cut_release.CutReleaseError, match="candidate_workflow_failed"
        ):
            cut_release.query_candidate_workflow("test/repo", "a" * 40)


def test_query_candidate_workflow_fails_when_artifact_missing():
    commit = "a" * 40
    fake_run = {
        "id": 12345,
        "head_sha": commit,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/test/repo/actions/runs/12345",
    }
    runs_resp = MagicMock()
    runs_resp.read.return_value = json.dumps({"workflow_runs": [fake_run]}).encode(
        "utf-8"
    )
    runs_resp.__enter__.return_value = runs_resp

    artifacts_resp = MagicMock()
    artifacts_resp.read.return_value = json.dumps(
        {"artifacts": [{"name": f"other-artifact-{commit}", "expired": False}]}
    ).encode("utf-8")
    artifacts_resp.__enter__.return_value = artifacts_resp

    with patch("urllib.request.urlopen", side_effect=[runs_resp, artifacts_resp]):
        with pytest.raises(
            cut_release.CutReleaseError, match="candidate_artifacts_missing"
        ):
            cut_release.query_candidate_workflow("test/repo", commit)


def test_query_candidate_workflow_succeeds_when_all_artifacts_present():
    commit = "a" * 40
    fake_run = {
        "id": 12345,
        "head_sha": commit,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/test/repo/actions/runs/12345",
    }
    runs_resp = MagicMock()
    runs_resp.read.return_value = json.dumps({"workflow_runs": [fake_run]}).encode(
        "utf-8"
    )
    runs_resp.__enter__.return_value = runs_resp

    artifacts_resp = MagicMock()
    artifacts_resp.read.return_value = json.dumps(
        {
            "artifacts": [
                {"name": f"karkinos-candidate-{commit}", "expired": False},
            ]
        }
    ).encode("utf-8")
    artifacts_resp.__enter__.return_value = artifacts_resp

    with patch("urllib.request.urlopen", side_effect=[runs_resp, artifacts_resp]):
        info = cut_release.query_candidate_workflow("test/repo", commit)
        assert info["run_id"] == 12345
        assert info["run_url"] == "https://github.com/test/repo/actions/runs/12345"


def test_check_remote_tag_fails_if_tag_exists():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="abc1234567890\trefs/tags/v0.4.0\n", returncode=0
        )
        with pytest.raises(cut_release.CutReleaseError, match="remote_tag_exists"):
            cut_release.check_remote_tag(Path("/tmp"), "v0.4.0")


def test_check_remote_tag_passes_if_tag_absent():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        cut_release.check_remote_tag(Path("/tmp"), "v0.4.0")
