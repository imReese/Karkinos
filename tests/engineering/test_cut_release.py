from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import cut_release


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


def test_check_codebase_versions_passes_when_in_sync(tmp_path: Path):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "__init__.py").write_text('__version__ = "0.4.0"\n', encoding="utf-8")

    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text(
        json.dumps({"version": "0.4.0"}), encoding="utf-8"
    )

    tests_dir = tmp_path / "tests" / "server"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_release_version.py").write_text(
        'assert server.__version__ == "0.4.0"\n', encoding="utf-8"
    )

    cut_release.check_codebase_versions(tmp_path, "0.4.0")


def test_check_codebase_versions_fails_on_server_mismatch(tmp_path: Path):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "__init__.py").write_text('__version__ = "0.3.9"\n', encoding="utf-8")

    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text(
        json.dumps({"version": "0.4.0"}), encoding="utf-8"
    )

    with pytest.raises(
        cut_release.CutReleaseError, match="version_mismatch: server/__init__.py"
    ):
        cut_release.check_codebase_versions(tmp_path, "0.4.0")


def test_check_codebase_versions_fails_on_web_mismatch(tmp_path: Path):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "__init__.py").write_text('__version__ = "0.4.0"\n', encoding="utf-8")

    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text(
        json.dumps({"version": "0.3.9"}), encoding="utf-8"
    )

    with pytest.raises(
        cut_release.CutReleaseError, match="version_mismatch: web/package.json"
    ):
        cut_release.check_codebase_versions(tmp_path, "0.4.0")


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
