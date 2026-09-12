"""Promote the exact current dev head after its Dev CI gate succeeds."""

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
DEV_WORKFLOW_FILE = "dev-ci.yml"
DEV_WORKFLOW_NAME = "Dev CI"
DEV_WORKFLOW_PATH = ".github/workflows/dev-ci.yml"
REQUIRED_JOBS = ("Dev CI gate",)
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


class Client(ci.GitHubActionsClient):
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


def latest_dev_run(client: Client, repository: str, sha: str):
    workflow_id = ci.validate_workflow_identity(
        client.workflow(DEV_WORKFLOW_FILE),
        expected_name=DEV_WORKFLOW_NAME,
        expected_path=DEV_WORKFLOW_PATH,
    )
    return ci.select_latest_exact_run(
        client.workflow_runs(
            workflow_id=workflow_id,
            branch="dev",
            event="push",
            commit_sha=sha,
        ),
        repository=repository,
        workflow_id=workflow_id,
        workflow_path=DEV_WORKFLOW_PATH,
        branch="dev",
        event="push",
        commit_sha=sha,
    )


def verified_dev(client: Client, repository: str, sha: str):
    return ci.wait_for_verified_source_ci(
        client,
        repository=repository,
        workflow_file=DEV_WORKFLOW_FILE,
        workflow_name=DEV_WORKFLOW_NAME,
        workflow_path=DEV_WORKFLOW_PATH,
        branch="dev",
        event="push",
        commit_sha=sha,
        required_job_names=REQUIRED_JOBS,
        timeout_seconds=0,
        poll_interval_seconds=1,
    )


def select(client: Client, repository: str) -> Selection | None:
    """Select only the current dev head; never promote an older green ancestor."""

    main = client.ref("main")
    dev = client.ref("dev")
    if main == dev:
        return None
    if client.relation(main, dev) != "ahead":
        raise ci.SourceCIVerificationError("promotion_dev_must_contain_main")

    run = latest_dev_run(client, repository, dev)
    if run is None:
        return None
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status in ci._PENDING_STATUSES:
        return None
    if status != "completed":
        raise ci.SourceCIVerificationError("promotion_ci_state_invalid")
    if conclusion != "success":
        return None

    evidence = verified_dev(client, repository, dev)
    return Selection(main, dev, dev, evidence.run_id, evidence.run_attempt)


def ensure_followup(
    client: Client,
    repository: str,
    sha: str,
    base: str,
) -> list[str]:
    """Dispatch missing exact-main CI/candidate runs after a GITHUB_TOKEN ref write."""

    requested: list[str] = []
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
            latest = ci.select_latest_exact_run(
                client.workflow_runs(
                    workflow_id=workflow_id,
                    branch="main",
                    event=event,
                    commit_sha=sha,
                ),
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


def apply(client: Client, repository: str, selection: Selection) -> dict:
    """Revalidate exact Dev CI evidence, publish the gate, then fast-forward main."""

    for sha in (selection.previous_main, selection.observed_dev, selection.commit_sha):
        checked_sha(sha)
    if selection.commit_sha != selection.observed_dev:
        raise ci.SourceCIVerificationError("promotion_candidate_must_be_dev_head")

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
    if client.relation(selection.previous_main, selection.commit_sha) != "ahead":
        raise ci.SourceCIVerificationError("promotion_not_fast_forward")

    changed = current != selection.commit_sha
    if changed:
        verification_url = (
            f"https://github.com/{repository}/actions/runs/"
            f"{selection.run_id}/attempts/{selection.run_attempt}"
        )
        client.write(
            f"statuses/{selection.commit_sha}",
            {
                "state": "success",
                "context": PROMOTION_GATE,
                "description": "Exact dev HEAD passed Dev CI",
                "target_url": verification_url,
            },
            method="POST",
        )
        client.write(
            "git/refs/heads/main",
            {"sha": selection.commit_sha, "force": False},
            method="PATCH",
        )

    if client.ref("main") != selection.commit_sha:
        raise ci.SourceCIVerificationError("promotion_main_write_not_confirmed")
    requested = ensure_followup(
        client,
        repository,
        selection.commit_sha,
        selection.previous_main,
    )
    return {**asdict(selection), "main_updated": changed, "dispatched": requested}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument(
        "--repair-followup",
        action="store_true",
        help="Dispatch missing current-main checks without moving a ref",
    )
    args = parser.parse_args(argv)
    try:
        if args.repair_followup and (
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
        if args.repair_followup:
            current = client.ref("main")
            verified_dev(client, args.repository, current)
            result = {
                "dispatched": ensure_followup(
                    client,
                    args.repository,
                    current,
                    current,
                )
            }
        else:
            selection = select(client, args.repository)
            result = (
                {"result": "no_eligible_new_commit"}
                if selection is None
                else {"dry_run": True, **asdict(selection)}
            )
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
