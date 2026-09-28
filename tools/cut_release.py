#!/usr/bin/env python3
"""Safely verify release readiness and publish an immutable release tag.

This tool guarantees that a release tag is never created or pushed unless:
1. Local git working tree is clean;
2. Codebase versions in server, web, and tests match the target tag exactly;
3. The target commit has already been promoted to and merged into origin/main;
4. The Release Candidate workflow has completed successfully on main with
   attested candidate artifacts (Docker image + macOS native bundles);
5. The tag does not already exist on remote.

This fail-closed design prevents deadlocks caused by GitHub's immutable tag ruleset.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

_SEMVER_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_DEFAULT_REPO = "imReese/Karkinos"


class CutReleaseError(RuntimeError):
    """Raised when release pre-conditions are not met or release fails."""


def validate_version(tag: str) -> str:
    """Validate that tag is a strict SemVer tag (e.g. 'v0.4.0') and return version."""
    match = _SEMVER_TAG.match(tag)
    if not match:
        raise CutReleaseError(
            f"invalid_tag_format: tag '{tag}' must match format vMAJOR.MINOR.PATCH (e.g. v0.4.0)"
        )
    return tag[1:]


def check_working_tree_clean(repo_root: Path) -> None:
    """Ensure git working directory has no uncommitted changes or untracked files."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CutReleaseError("failed_to_check_git_status") from exc

    if proc.stdout.strip():
        raise CutReleaseError(
            "working_tree_dirty: uncommitted changes detected. "
            "Please commit, stash, or clean working tree before cutting a release."
        )


def check_codebase_versions(repo_root: Path, expected_version: str) -> None:
    """Verify that server/__init__.py, web/package.json, and release tests match expected_version."""
    server_init = repo_root / "server" / "__init__.py"
    if not server_init.is_file():
        raise CutReleaseError("missing_server_init: server/__init__.py not found")
    server_content = server_init.read_text(encoding="utf-8")
    server_match = re.search(r'__version__\s*=\s*"([^"]+)"', server_content)
    if not server_match or server_match.group(1) != expected_version:
        found = server_match.group(1) if server_match else "missing"
        raise CutReleaseError(
            f"version_mismatch: server/__init__.py has version '{found}', expected '{expected_version}'"
        )

    web_pkg = repo_root / "web" / "package.json"
    if not web_pkg.is_file():
        raise CutReleaseError("missing_web_package: web/package.json not found")
    try:
        pkg_data = json.loads(web_pkg.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CutReleaseError("invalid_web_package_json") from exc

    web_version = pkg_data.get("version")
    if web_version != expected_version:
        raise CutReleaseError(
            f"version_mismatch: web/package.json has version '{web_version}', expected '{expected_version}'"
        )

    test_release = repo_root / "tests" / "server" / "test_release_version.py"
    if test_release.is_file():
        test_content = test_release.read_text(encoding="utf-8")
        expected_statement = f'server.__version__ == "{expected_version}"'
        if expected_statement not in test_content:
            raise CutReleaseError(
                f"version_mismatch: tests/server/test_release_version.py does not assert '{expected_statement}'"
            )


def resolve_commit_sha(repo_root: Path, ref: str = "HEAD") -> str:
    """Resolve a git ref to its full 40-character commit SHA."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        sha = proc.stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CutReleaseError(
            f"failed_to_resolve_ref: unable to resolve '{ref}'"
        ) from exc

    if not _FULL_SHA.match(sha):
        raise CutReleaseError(f"invalid_commit_sha: '{sha}' is not a valid 40-char SHA")
    return sha


def verify_origin_main_ancestry(
    repo_root: Path, commit_sha: str, *, fetch: bool = True
) -> None:
    """Verify that commit_sha is an ancestor of origin/main."""
    if fetch:
        try:
            subprocess.run(
                ["git", "fetch", "--no-tags", "origin", "main"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise CutReleaseError("failed_to_fetch_origin_main") from exc

    try:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit_sha, "origin/main"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise CutReleaseError("failed_to_check_merge_base") from exc

    if proc.returncode != 0:
        raise CutReleaseError(
            f"commit_not_in_origin_main: Commit {commit_sha[:8]} is not an ancestor of origin/main.\n"
            "The release pipeline requires the commit to be promoted to 'main' first.\n"
            "Ensure dev CI is green and 'promote-dev' workflow has completed."
        )


def get_github_token() -> str | None:
    """Obtain GitHub token from environment or gh CLI."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def query_candidate_workflow(
    repository: str,
    commit_sha: str,
    token: str | None = None,
    api_url: str = "https://api.github.com",
) -> dict[str, Any]:
    """Verify that Release Candidate workflow succeeded on main and has required artifacts."""
    query = urlencode({"branch": "main", "head_sha": commit_sha, "per_page": 10})
    url = f"{api_url}/repos/{repository}/actions/workflows/candidate.yml/runs?{query}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "karkinos-cut-release",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise CutReleaseError(
            f"candidate_api_http_error: HTTP {exc.code} querying candidate runs"
        ) from exc
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CutReleaseError(
            "candidate_api_network_error: failed to contact GitHub API"
        ) from exc

    runs = [
        r
        for r in data.get("workflow_runs", [])
        if r.get("head_sha") == commit_sha and r.get("head_branch") == "main"
    ]
    if not runs:
        raise CutReleaseError(
            f"candidate_workflow_not_found: No Release Candidate workflow run found on main for {commit_sha[:8]}.\n"
            "Wait for candidate.yml to trigger and complete on main before pushing a release tag."
        )

    latest_run = runs[0]
    status = latest_run.get("status")
    conclusion = latest_run.get("conclusion")
    run_id = latest_run.get("id")

    if status != "completed":
        raise CutReleaseError(
            f"candidate_workflow_in_progress: Release Candidate run {run_id} is currently '{status}'.\n"
            "Pushing the tag now would deadlock release.yml under immutable tag rules.\n"
            f"View run: https://github.com/{repository}/actions/runs/{run_id}"
        )

    if conclusion != "success":
        raise CutReleaseError(
            f"candidate_workflow_failed: Release Candidate run {run_id} finished with conclusion '{conclusion}'.\n"
            "Cannot cut a release from a failed candidate build."
        )

    # Verify candidate artifacts
    artifacts_url = f"{api_url}/repos/{repository}/actions/runs/{run_id}/artifacts"
    art_req = urllib.request.Request(artifacts_url, headers=headers)
    try:
        with urllib.request.urlopen(art_req, timeout=30) as resp:
            art_data = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CutReleaseError("failed_to_fetch_candidate_artifacts") from exc

    artifact_names = {
        a["name"] for a in art_data.get("artifacts", []) if not a.get("expired")
    }
    required_artifacts = [
        f"karkinos-candidate-{commit_sha}",
    ]
    missing = [name for name in required_artifacts if name not in artifact_names]
    if missing:
        raise CutReleaseError(
            f"candidate_artifacts_missing: Required artifacts not found in candidate run {run_id}: {missing}"
        )

    return {
        "run_id": run_id,
        "run_url": latest_run.get("html_url"),
        "artifacts": sorted(artifact_names),
    }


def check_remote_tag(repo_root: Path, tag: str) -> None:
    """Ensure tag does not already exist on remote."""
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CutReleaseError(f"failed_to_check_remote_tag: {tag}") from exc

    if proc.stdout.strip():
        raise CutReleaseError(
            f"remote_tag_exists: Tag '{tag}' already exists on origin.\n"
            "Repository rules prohibit deleting or updating existing release tags."
        )


def cut_release(
    repo_root: Path,
    tag: str,
    commit_ref: str = "HEAD",
    repository: str = _DEFAULT_REPO,
    *,
    dry_run: bool = False,
    fetch: bool = True,
) -> dict[str, Any]:
    """Execute full pre-flight verification and safely create and push release tag."""
    version = validate_version(tag)
    check_working_tree_clean(repo_root)
    check_codebase_versions(repo_root, version)

    commit_sha = resolve_commit_sha(repo_root, commit_ref)
    verify_origin_main_ancestry(repo_root, commit_sha, fetch=fetch)

    token = get_github_token()
    candidate_info = query_candidate_workflow(repository, commit_sha, token=token)

    check_remote_tag(repo_root, tag)

    result = {
        "tag": tag,
        "version": version,
        "commit_sha": commit_sha,
        "candidate_run_id": candidate_info["run_id"],
        "candidate_run_url": candidate_info["run_url"],
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    # Create annotated tag locally
    try:
        subprocess.run(
            ["git", "tag", "-a", tag, commit_sha, "-m", f"Release version {version}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CutReleaseError(f"failed_to_create_tag: {exc}") from exc

    # Push tag to origin
    try:
        subprocess.run(
            ["git", "push", "origin", tag],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CutReleaseError(f"failed_to_push_tag: {exc}") from exc

    result["pushed"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify release readiness and publish an immutable release tag safely."
    )
    parser.add_argument(
        "tag",
        nargs="?",
        help="SemVer release tag to publish (e.g. v0.4.0). If omitted, reads from server/__init__.py.",
    )
    parser.add_argument(
        "--commit",
        default="HEAD",
        help="Commit reference to tag (default: HEAD).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root directory.",
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", _DEFAULT_REPO),
        help="GitHub repository in 'owner/repo' format.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all pre-flight verifications without creating or pushing tag.",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip 'git fetch origin main' during ancestry verification.",
    )

    args = parser.parse_args(argv)

    tag = args.tag
    if not tag:
        # Default tag from server/__init__.py
        init_file = args.repo_root / "server" / "__init__.py"
        if init_file.is_file():
            m = re.search(
                r'__version__\s*=\s*"([^"]+)"', init_file.read_text(encoding="utf-8")
            )
            if m:
                tag = f"v{m.group(1)}"
    if not tag:
        print(
            "Error: Tag not provided and could not be inferred from server/__init__.py",
            file=sys.stderr,
        )
        return 1

    try:
        result = cut_release(
            repo_root=args.repo_root,
            tag=tag,
            commit_ref=args.commit,
            repository=args.repository,
            dry_run=args.dry_run,
            fetch=not args.no_fetch,
        )
    except CutReleaseError as exc:
        print(f"Pre-flight failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    if not args.dry_run:
        print(
            f"\nSuccessfully verified and published release tag {tag} -> commit {result['commit_sha'][:8]}"
        )
        print(f"Candidate provenance: {result['candidate_run_url']}")
        print(
            f"Follow Release workflow: https://github.com/{args.repository}/actions/workflows/release.yml"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
