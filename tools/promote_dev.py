"""Promote an exact, verified dev commit by fast-forward; never merge or force."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from tools import verify_release_source_ci as ci

SHA = re.compile(r"[0-9a-f]{40}")
REQUIRED_JOBS = ("Code CI gate", "Repository acceptance audit")
MAX_COMMITS = 100
PROMOTION_GATE = "Main promotion gate"


def checked_sha(value: Any) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise ci.SourceCIVerificationError("promotion_invalid_sha")
    return value


@dataclass(frozen=True)
class Selection:
    previous_main: str
    observed_dev: str
    commit_sha: str
    run_id: int
    run_attempt: int


@dataclass(frozen=True)
class FullVerification:
    """Output and execution identity from the trusted reusable CI caller."""

    commit_sha: str
    workflow_sha: str
    run_id: int
    run_attempt: int


class Client(ci.GitHubActionsClient):
    def workflow_run(self, run_id: int) -> dict:
        return dict(self._get_json(f"/repos/{self._repository}/actions/runs/{run_id}"))

    def ref(self, branch: str) -> str:
        value = self._get_json(f"/repos/{self._repository}/git/ref/heads/{branch}")
        if value.get("ref") != f"refs/heads/{branch}":
            raise ci.SourceCIVerificationError("promotion_ref_identity_mismatch")
        obj = value.get("object", {})
        if obj.get("type") != "commit":
            raise ci.SourceCIVerificationError("promotion_ref_not_commit")
        return checked_sha(obj.get("sha"))

    def relation(self, base: str, head: str) -> str:
        result = self._get_json(
            f"/repos/{self._repository}/compare/{checked_sha(base)}...{checked_sha(head)}"
        )
        status = result.get("status")
        if status not in {"ahead", "behind", "identical", "diverged"}:
            raise ci.SourceCIVerificationError("promotion_ancestry_inconclusive")
        if status in {"ahead", "identical"}:
            if result.get("merge_base_commit", {}).get("sha") != base:
                raise ci.SourceCIVerificationError("promotion_merge_base_mismatch")
        return status

    def parent(self, sha: str) -> str | None:
        commit = self._get_json(
            f"/repos/{self._repository}/git/commits/{checked_sha(sha)}"
        )
        if commit.get("sha") != sha or not isinstance(commit.get("parents"), list):
            raise ci.SourceCIVerificationError("promotion_commit_identity_mismatch")
        parents = commit["parents"]
        return checked_sha(parents[0].get("sha")) if parents else None

    def write(self, suffix: str, payload: dict, *, method: str) -> None:
        request = Request(
            f"{self._api_url}/repos/{self._repository}/{suffix}",
            data=json.dumps(payload).encode("utf-8"),
            headers={**self._headers, "Content-Type": "application/json"},
            method=method,
        )
        try:
            with ci.urlopen(request, timeout=30) as response:
                expected = {200} if method == "PATCH" else {200, 204}
                if method == "POST" and suffix.startswith("statuses/"):
                    expected = {201}
                if response.status not in expected:
                    raise ci.SourceCIVerificationError("promotion_write_status_invalid")
        except HTTPError as exc:
            raise ci.SourceCIVerificationError(
                f"promotion_write_rejected:{exc.code}; no protection bypass attempted"
            ) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise ci.SourceCIVerificationError(
                "promotion_write_inconclusive; inspect main before retrying"
            ) from exc


def latest_run(client: Client, repository: str, branch: str, sha: str, event="push"):
    workflow_id = ci.validate_workflow_identity(
        client.workflow("ci.yml"),
        expected_name="CI",
        expected_path=".github/workflows/ci.yml",
    )
    return ci.select_latest_exact_run(
        client.workflow_runs(
            workflow_id=workflow_id, branch=branch, event=event, commit_sha=sha
        ),
        repository=repository,
        workflow_id=workflow_id,
        workflow_path=".github/workflows/ci.yml",
        branch=branch,
        event=event,
        commit_sha=sha,
    )


def verified_dev(client: Client, repository: str, sha: str):
    return ci.wait_for_verified_source_ci(
        client,
        repository=repository,
        workflow_file="ci.yml",
        workflow_name="CI",
        workflow_path=".github/workflows/ci.yml",
        branch="dev",
        event="push",
        commit_sha=sha,
        required_job_names=REQUIRED_JOBS,
        timeout_seconds=0,
        poll_interval_seconds=1,
    )


def select(client: Client, repository: str) -> Selection | None:
    main, dev = client.ref("main"), client.ref("dev")
    if main == dev:
        return None
    if client.relation(main, dev) != "ahead":
        raise ci.SourceCIVerificationError("promotion_dev_must_contain_main")
    candidate = dev
    seen = set()
    for _ in range(MAX_COMMITS):
        if candidate in seen:
            raise ci.SourceCIVerificationError("promotion_history_cycle")
        seen.add(candidate)
        if candidate == main or client.relation(main, candidate) != "ahead":
            return None
        run = latest_run(client, repository, "dev", candidate)
        if run is not None:
            if run.get("status") == "completed" and run.get("conclusion") == "success":
                evidence = verified_dev(client, repository, candidate)
                return Selection(
                    main, dev, candidate, evidence.run_id, evidence.run_attempt
                )
            if run.get("status") not in ci._PENDING_STATUSES | {"completed"}:
                raise ci.SourceCIVerificationError("promotion_ci_state_invalid")
        candidate = client.parent(candidate)
        if candidate is None:
            return None
    raise ci.SourceCIVerificationError(
        "promotion_history_limit; no unbounded search performed"
    )


def ensure_followup(client: Client, repository: str, sha: str, base: str) -> list[str]:
    """GITHUB_TOKEN pushes do not trigger CI: dispatch missing exact-main runs.

    Retrying after a successful ref write but failed dispatch repairs only the
    missing dispatch. Existing pending/failed/successful runs are never hidden
    by an automatic retry. Their normal Actions rerun remains an owner action.
    """
    requested = []
    for filename, name in (("ci.yml", "CI"), ("candidate.yml", "Release Candidate")):
        if client.ref("main") != sha:
            raise ci.SourceCIVerificationError("promotion_main_changed_before_dispatch")
        workflow_id = ci.validate_workflow_identity(
            client.workflow(filename),
            expected_name=name,
            expected_path=f".github/workflows/{filename}",
        )
        runs = []
        for event in ("push", "workflow_dispatch"):
            payload = client.workflow_runs(
                workflow_id=workflow_id, branch="main", event=event, commit_sha=sha
            )
            # Validate even existing runs; an unrelated green run is not evidence.
            latest = ci.select_latest_exact_run(
                payload,
                repository=repository,
                workflow_id=workflow_id,
                workflow_path=f".github/workflows/{filename}",
                branch="main",
                event=event,
                commit_sha=sha,
            )
            if latest is not None:
                runs.append(latest)
        if runs:
            continue
        inputs = {"commit_sha": sha}
        if filename == "ci.yml":
            inputs["base_sha"] = base
        client.write(
            f"actions/workflows/{filename}/dispatches",
            {"ref": "main", "inputs": inputs},
            method="POST",
        )
        requested.append(filename)
    return requested


def verify_full_run(
    client: Client, repository: str, selection: Selection, full: FullVerification
) -> str:
    if checked_sha(full.commit_sha) != selection.commit_sha:
        raise ci.SourceCIVerificationError("promotion_verified_sha_mismatch")
    checked_sha(full.workflow_sha)
    if any(
        type(value) is not int or value <= 0
        for value in (full.run_id, full.run_attempt)
    ):
        raise ci.SourceCIVerificationError("promotion_full_run_identity_invalid")
    run = client.workflow_run(full.run_id)
    expected = {
        "id": full.run_id,
        "run_attempt": full.run_attempt,
        "path": ".github/workflows/promote-dev.yml",
        "head_branch": "main",
        "head_sha": full.workflow_sha,
    }
    if (
        any(run.get(key) != value for key, value in expected.items())
        or run.get("repository", {}).get("full_name") != repository
        or run.get("head_repository", {}).get("full_name") != repository
        or run.get("event") not in {"schedule", "workflow_dispatch", "push"}
        or run.get("status") not in {"in_progress", "completed"}
        or (run.get("status") == "completed" and run.get("conclusion") != "success")
    ):
        raise ci.SourceCIVerificationError("promotion_full_run_identity_mismatch")
    ci.verify_required_jobs(
        client.workflow_run_jobs(run_id=full.run_id),
        required_job_names=("Full pre-promotion verification / Code CI gate",),
        commit_sha=full.workflow_sha,
    )
    snapshot_keys = (*expected, "status", "conclusion", "event")
    confirmed = client.workflow_run(full.run_id)
    if any(confirmed.get(key) != run.get(key) for key in snapshot_keys) or any(
        confirmed.get(key, {}).get("full_name") != repository
        for key in ("repository", "head_repository")
    ):
        raise ci.SourceCIVerificationError("promotion_full_run_changed")
    return f"https://github.com/{repository}/actions/runs/{full.run_id}/attempts/{full.run_attempt}"


def apply(
    client: Client, repository: str, selection: Selection, *, full: FullVerification
) -> dict:
    for sha in (selection.previous_main, selection.observed_dev, selection.commit_sha):
        checked_sha(sha)
    evidence = verified_dev(client, repository, selection.commit_sha)
    if (evidence.run_id, evidence.run_attempt) != (
        selection.run_id,
        selection.run_attempt,
    ):
        raise ci.SourceCIVerificationError("promotion_ci_attempt_changed")
    if client.ref("dev") != selection.observed_dev:
        raise ci.SourceCIVerificationError("promotion_dev_changed; retry selection")
    current = client.ref("main")
    if current not in {selection.previous_main, selection.commit_sha}:
        raise ci.SourceCIVerificationError("promotion_main_changed; retry selection")
    if client.relation(selection.commit_sha, selection.observed_dev) not in {
        "ahead",
        "identical",
    }:
        raise ci.SourceCIVerificationError("promotion_candidate_not_on_dev")
    verification_url = verify_full_run(client, repository, selection, full)
    changed = current != selection.commit_sha
    if changed:
        if client.relation(current, selection.commit_sha) != "ahead":
            raise ci.SourceCIVerificationError("promotion_not_fast_forward")
        client.write(
            f"statuses/{selection.commit_sha}",
            {
                "state": "success",
                "context": PROMOTION_GATE,
                "description": "Exact candidate passed the complete reusable CI",
                "target_url": verification_url,
            },
            method="POST",
        )
        # The server checks fast-forward atomically. Never reset, merge, or force.
        client.write(
            "git/refs/heads/main",
            {"sha": selection.commit_sha, "force": False},
            method="PATCH",
        )
    if client.ref("main") != selection.commit_sha:
        raise ci.SourceCIVerificationError("promotion_main_write_not_confirmed")
    requested = ensure_followup(
        client, repository, selection.commit_sha, selection.previous_main
    )
    return {**asdict(selection), "main_updated": changed, "dispatched": requested}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rejected legacy option; ref writes require full workflow evidence",
    )
    parser.add_argument(
        "--repair-followup",
        action="store_true",
        help="Dispatch missing current-main checks without moving a ref",
    )
    args = parser.parse_args(argv)
    try:
        if (args.apply or args.repair_followup) and (
            os.environ.get("GITHUB_REF") != "refs/heads/main"
            or args.repository != os.environ.get("GITHUB_REPOSITORY")
        ):
            raise ci.SourceCIVerificationError("promotion_apply_requires_main_workflow")
        client = Client(
            api_url="https://api.github.com",
            repository=args.repository or "",
            token=os.environ.get("GITHUB_TOKEN", ""),
            api_version="2022-11-28",
        )
        if args.apply:
            raise ci.SourceCIVerificationError(
                "promotion_apply_requires_full_workflow_evidence"
            )
        if args.repair_followup:
            current = client.ref("main")
            verified_dev(client, args.repository, current)
            print(
                json.dumps(
                    {
                        "dispatched": ensure_followup(
                            client, args.repository, current, current
                        )
                    },
                    sort_keys=True,
                )
            )
            return 0
        selection = select(client, args.repository)
        if selection is None:
            result = {"result": "no_eligible_new_commit"}
        else:
            result = {"dry_run": True, **asdict(selection)}
        output = json.dumps(result, sort_keys=True, indent=2)
        print(output)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write("## Dev to main promotion\n```json\n" + output + "\n```\n")
        return 0
    except (ci.SourceCIVerificationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
