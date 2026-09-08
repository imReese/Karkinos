"""Reuse a target-bound, trusted promotion attempt without weakening main CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from tools import verify_release_source_ci as ci

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMOTION_PATH = ".github/workflows/promote-dev.yml"
MAX_AGE_SECONDS = 24 * 60 * 60
REUSED_JOBS = {
    "python-quality": "Python changed-file quality",
    "repository-contracts": "Repository contract tests",
    "backend": "Backend tests",
    "frontend": "Frontend checks",
    "trading-safety": "Trading safety invariants",
    "docker-runtime": "Docker runtime smoke",
    "browser-safety": "Browser safety smoke",
}
FRESH_JOBS = {
    "hygiene": "Repository hygiene",
    "secret-scan": "Secret scan",
    "dependency-audit": "Production dependency audit",
    "repository-acceptance-audit": "Repository acceptance audit",
}
FULL_JOB_NAMES = (
    tuple(REUSED_JOBS.values()) + tuple(FRESH_JOBS.values()) + ("Code CI gate",)
)
_POLICY_PREFIXES = (".github/workflows/", ".github/actions/", "scripts/ci/")
_POLICY_FILES = {
    "tools/ci_reuse.py",
    "tools/verify_release_source_ci.py",
    "tools/check_python_architecture.py",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".pre-commit-config.yaml",
    "Dockerfile",
    ".dockerignore",
    "pytest.ini",
    "conftest.py",
    "tests/conftest.py",
    "web/package.json",
    "web/package-lock.json",
    "web/.npmrc",
}


class ReuseError(ci.SourceCIVerificationError):
    """Evidence cannot authorize skipping a check."""


def _sha(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ReuseError("ci_reuse_invalid_sha")
    return value


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReuseError("ci_reuse_git_identity_unavailable") from exc


def _ancestor(root: Path, base: str, head: str) -> None:
    _git(root, "merge-base", "--is-ancestor", _sha(base), _sha(head))


def _policy_path(path: str) -> bool:
    return (
        path.startswith(_POLICY_PREFIXES)
        or path in _POLICY_FILES
        or (path.startswith("tools/promote_dev") and path.endswith(".py"))
        or (path.startswith("analytics/") and "acceptance" in path)
        or (
            path.startswith("web/")
            and "/" not in path[4:]
            and any(part in path for part in ("config", "prettier", "eslint", "npm"))
        )
    )


def policy_fingerprint(root: Path, sha: str) -> str:
    """Hash committed path, mode, object type and blob identities, never checkout bytes."""
    entries = _git(root, "ls-tree", "-r", "-z", _sha(sha)).split(b"\0")
    policy = []
    paths = set()
    for entry in entries:
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            path = raw_path.decode("utf-8")
            mode, object_type, object_id = metadata.decode("ascii").split()
        except (ValueError, UnicodeError) as exc:
            raise ReuseError("ci_reuse_policy_tree_invalid") from exc
        if _policy_path(path):
            if object_type != "blob" or mode not in {"100644", "100755"}:
                raise ReuseError("ci_reuse_policy_not_regular_file")
            _sha(object_id)
            paths.add(path)
            policy.append(entry)
    required = {PROMOTION_PATH, ".github/workflows/ci.yml", "tools/ci_reuse.py"}
    if not required <= paths:
        raise ReuseError("ci_reuse_policy_incomplete")
    return hashlib.sha256(b"karkinos-ci-policy-v1\0" + b"\0".join(policy)).hexdigest()


@dataclass(frozen=True)
class Context:
    commit_sha: str
    base_sha: str
    workflow_sha: str
    repository: str
    ref: str
    event: str
    pre_promotion: bool
    force_full: bool


def _boolean(env: Mapping[str, str], key: str) -> bool:
    value = env.get(key, "false") or "false"
    if value not in {"true", "false"}:
        raise ReuseError("ci_reuse_invalid_boolean:" + key)
    return value == "true"


def validate_context(env: Mapping[str, str], root: Path) -> Context:
    context = Context(
        _sha(env.get("CI_COMMIT_SHA")),
        _sha(env.get("CI_BASE_SHA")),
        _sha(env.get("GITHUB_SHA")),
        env.get("GITHUB_REPOSITORY", ""),
        env.get("GITHUB_REF", ""),
        env.get("GITHUB_EVENT_NAME", ""),
        _boolean(env, "CI_PRE_PROMOTION"),
        _boolean(env, "CI_FORCE_FULL"),
    )
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", context.repository) is None:
        raise ReuseError("ci_reuse_repository_invalid")
    checkout = _git(root, "rev-parse", "HEAD").decode().strip()
    if checkout != context.workflow_sha:
        raise ReuseError("ci_reuse_checkout_identity_mismatch")
    if context.pre_promotion:
        if context.ref != "refs/heads/main" or context.event not in {
            "schedule",
            "push",
            "workflow_dispatch",
        }:
            raise ReuseError("ci_reuse_pre_promotion_context_invalid")
        if context.base_sha == "0" * 40:
            raise ReuseError("ci_reuse_pre_promotion_base_missing")
        _ancestor(root, context.workflow_sha, context.commit_sha)
    else:
        if context.commit_sha != context.workflow_sha:
            raise ReuseError("ci_reuse_source_identity_mismatch")
        if not (
            context.ref == "refs/heads/main"
            and context.event in {"push", "workflow_dispatch"}
            or context.ref == "refs/heads/dev"
            and context.event == "workflow_dispatch"
        ):
            raise ReuseError("ci_reuse_execution_context_invalid")
    if context.base_sha != "0" * 40:
        _ancestor(root, context.base_sha, context.commit_sha)
    return context


class Client(ci.GitHubActionsClient):
    def workflow_run(self, run_id: int) -> Mapping[str, Any]:
        return self._get_json(f"/repos/{self._repository}/actions/runs/{run_id}")

    def attempt_jobs(self, run_id: int, run_attempt: int) -> Mapping[str, Any]:
        return self._get_json(
            f"/repos/{self._repository}/actions/runs/{run_id}/attempts/{run_attempt}/jobs",
            {"per_page": "100"},
        )


@dataclass(frozen=True)
class Evidence:
    commit_sha: str
    source_run_id: int
    source_run_attempt: int
    source_workflow_sha: str
    policy_fingerprint: str


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ReuseError("ci_reuse_timestamp_invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReuseError("ci_reuse_timestamp_invalid") from exc
    if result.tzinfo is None:
        raise ReuseError("ci_reuse_timestamp_invalid")
    return result


def verify_reuse(
    client: Client,
    context: Context,
    root: Path,
    run_id: int,
    run_attempt: int,
    *,
    expected_workflow_sha: str | None = None,
    expected_policy_fingerprint: str | None = None,
    wait_seconds: float = 30,
) -> Evidence:
    if context.pre_promotion or context.force_full or context.ref != "refs/heads/main":
        raise ReuseError("ci_reuse_context_forbids_reuse")
    if context.repository != "imReese/Karkinos":
        raise ReuseError("ci_reuse_untrusted_repository")
    if any(type(value) is not int or value <= 0 for value in (run_id, run_attempt)):
        raise ReuseError("ci_reuse_run_hint_invalid")
    workflow_id = ci.validate_workflow_identity(
        client.workflow("promote-dev.yml"),
        expected_name="Promote verified dev",
        expected_path=PROMOTION_PATH,
    )
    deadline = time.monotonic() + min(30, max(0, wait_seconds))
    while True:
        run = client.workflow_run(run_id)
        expected = {
            "id": run_id,
            "run_attempt": run_attempt,
            "workflow_id": workflow_id,
            "path": PROMOTION_PATH,
            "head_branch": "main",
        }
        if (
            any(run.get(key) != value for key, value in expected.items())
            or any(
                type(run.get(key)) is not int
                for key in ("id", "run_attempt", "workflow_id")
            )
            or run.get("event") not in {"schedule", "push", "workflow_dispatch"}
            or any(
                not isinstance(run.get(key), dict)
                or run[key].get("full_name") != context.repository
                for key in ("repository", "head_repository")
            )
        ):
            raise ReuseError("ci_reuse_run_identity_mismatch")
        if run.get("status") == "completed":
            if run.get("conclusion") != "success":
                raise ReuseError("ci_reuse_run_not_success")
            break
        remaining = deadline - time.monotonic()
        if run.get("status") not in ci._PENDING_STATUSES or remaining <= 0:
            raise ReuseError("ci_reuse_run_not_complete")
        time.sleep(min(2, remaining))

    workflow_sha = _sha(run.get("head_sha"))
    if workflow_sha == context.commit_sha:
        raise ReuseError("ci_reuse_workflow_not_previous_main")
    _ancestor(root, workflow_sha, context.commit_sha)
    fingerprint = policy_fingerprint(root, context.commit_sha)
    if policy_fingerprint(root, workflow_sha) != fingerprint:
        raise ReuseError("ci_reuse_policy_changed")
    if expected_workflow_sha is not None and expected_workflow_sha != workflow_sha:
        raise ReuseError("ci_reuse_source_workflow_changed")
    if (
        expected_policy_fingerprint is not None
        and expected_policy_fingerprint != fingerprint
    ):
        raise ReuseError("ci_reuse_expected_policy_changed")
    payload = client.attempt_jobs(run_id, run_attempt)
    required = tuple(
        "Full pre-promotion verification / " + name for name in FULL_JOB_NAMES
    )
    required += ("Verified source " + context.commit_sha,)
    ci.verify_required_jobs(
        payload, required_job_names=required, commit_sha=workflow_sha
    )
    jobs = ci._complete_page(payload, "jobs")
    now = datetime.now(timezone.utc)
    ids = set()
    for job in jobs:
        if isinstance(job, dict) and job.get("name") in required:
            if job.get("run_id") != run_id or job.get("id") in ids:
                raise ReuseError("ci_reuse_job_run_identity_mismatch")
            ids.add(job["id"])
            age = (now - _timestamp(job.get("completed_at"))).total_seconds()
            if age < 0 or age > MAX_AGE_SECONDS:
                raise ReuseError("ci_reuse_evidence_expired")
    confirmed = client.workflow_run(run_id)
    keys = (*expected, "head_sha", "event", "status", "conclusion", "updated_at")
    if any(confirmed.get(key) != run.get(key) for key in keys) or any(
        not isinstance(confirmed.get(key), dict)
        or any(
            confirmed[key].get(identity) != run[key].get(identity)
            for identity in ("id", "full_name")
        )
        for key in ("repository", "head_repository")
    ):
        raise ReuseError("ci_reuse_run_changed_during_verification")
    return Evidence(context.commit_sha, run_id, run_attempt, workflow_sha, fingerprint)


def _client(env: Mapping[str, str]) -> Client:
    return Client(
        api_url=env.get("GITHUB_API_URL", "https://api.github.com"),
        repository=env.get("GITHUB_REPOSITORY", ""),
        token=env.get("GITHUB_TOKEN", ""),
        api_version="2022-11-28",
    )


def _hints(env: Mapping[str, str]) -> tuple[int, int]:
    values = (
        env.get("CI_PROMOTION_RUN_ID", ""),
        env.get("CI_PROMOTION_RUN_ATTEMPT", ""),
    )
    if any(re.fullmatch(r"[1-9][0-9]{0,19}", value) is None for value in values):
        raise ReuseError("ci_reuse_run_hint_invalid")
    return tuple(map(int, values))


def decide(
    env: Mapping[str, str], root: Path, client: Client | None = None
) -> dict[str, Any]:
    context = validate_context(env, root)
    result = {"mode": "full", "commit_sha": context.commit_sha}
    if context.pre_promotion:
        return {**result, "reason": "pre_promotion_requires_full"}
    if context.ref == "refs/heads/dev":
        return {**result, "reason": "dev_dispatch_requires_full"}
    if context.force_full:
        return {**result, "reason": "force_full_requested"}
    if not env.get("CI_PROMOTION_RUN_ID") and not env.get("CI_PROMOTION_RUN_ATTEMPT"):
        return {**result, "reason": "promotion_evidence_not_supplied"}
    try:
        evidence = verify_reuse(client or _client(env), context, root, *_hints(env))
    except (ci.SourceCIVerificationError, ValueError) as exc:
        # Only bounded machine reasons are surfaced; never API payloads or credentials.
        reason = str(exc).split(":", 1)[0]
        if re.fullmatch(r"[a-z_]{1,100}", reason) is None:
            reason = "ci_reuse_evidence_unavailable"
        return {**result, "reason": reason}
    return {"mode": "reuse", "reason": "verified_promotion_attempt", **asdict(evidence)}


def require_gate_results(results: Any) -> None:
    required = set(REUSED_JOBS) | set(FRESH_JOBS) | {"verification-plan"}
    if not isinstance(results, dict) or set(results) != required:
        raise ReuseError("ci_reuse_gate_dependencies_mismatch")
    if any(not isinstance(job, dict) for job in results.values()):
        raise ReuseError("ci_reuse_gate_job_invalid")
    plan = results["verification-plan"]
    outputs = plan.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("mode") not in {"full", "reuse"}:
        raise ReuseError("ci_reuse_gate_mode_missing")
    mode = outputs["mode"]
    for name, job in results.items():
        expected = "skipped" if mode == "reuse" and name in REUSED_JOBS else "success"
        if job.get("result") != expected:
            raise ReuseError("ci_reuse_gate_unexpected_result:" + name)
    if mode == "reuse":
        audit_outputs = results["repository-acceptance-audit"].get("outputs")
        if (
            not isinstance(audit_outputs, dict)
            or audit_outputs.get("evidence_rechecked") != "true"
        ):
            raise ReuseError("ci_reuse_gate_evidence_not_rechecked")


def _emit(payload: Mapping[str, Any], env: Mapping[str, str]) -> None:
    if env.get("GITHUB_OUTPUT"):
        with Path(env["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            for key, value in payload.items():
                stream.write(f"{key}={value}\n")
    if env.get("GITHUB_STEP_SUMMARY"):
        with Path(env["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(
                "CI verification: `" + str(payload.get("mode", "verified")) + "`.\n"
            )
            stream.write(
                "Commit: `"
                + str(payload.get("commit_sha", payload.get("verified_sha", "")))
                + "`.\n"
            )
            if payload.get("source_run_id"):
                url = (
                    f"https://github.com/{env['GITHUB_REPOSITORY']}/actions/runs/"
                    f"{payload['source_run_id']}/attempts/{payload['source_run_attempt']}"
                )
                stream.write(f"Evidence: [trusted promotion attempt]({url}).\n")
            if payload.get("reason"):
                stream.write("Reason: `" + str(payload["reason"]) + "`.\n")
    print(json.dumps(payload, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("decide", "verify", "gate"))
    args = parser.parse_args(argv)
    env = os.environ
    try:
        if args.command == "decide":
            result = decide(env, REPO_ROOT)
        elif args.command == "verify":
            context = validate_context(env, REPO_ROOT)
            expected_workflow_sha = _sha(env.get("SOURCE_WORKFLOW_SHA"))
            expected_policy = env.get("POLICY_FINGERPRINT", "")
            if re.fullmatch(r"[0-9a-f]{64}", expected_policy) is None:
                raise ReuseError("ci_reuse_expected_policy_missing")
            evidence = verify_reuse(
                _client(env),
                context,
                REPO_ROOT,
                *_hints(env),
                expected_workflow_sha=expected_workflow_sha,
                expected_policy_fingerprint=expected_policy,
                wait_seconds=0,
            )
            result = {"mode": "reuse", **asdict(evidence), "evidence_rechecked": "true"}
        else:
            results = json.loads(env.get("RESULTS", "null"))
            require_gate_results(results)
            commit_sha = _sha(env.get("CI_COMMIT_SHA"))
            if results["verification-plan"]["outputs"].get("commit_sha") != commit_sha:
                raise ReuseError("ci_reuse_gate_source_identity_mismatch")
            result = {"verified_sha": commit_sha}
        _emit(result, env)
        return 0
    except (ci.SourceCIVerificationError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
