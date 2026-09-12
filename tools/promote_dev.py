"""Promote the exact current dev head only after complete exact-SHA CI."""

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
CI_WORKFLOW_FILE = "ci.yml"
CI_WORKFLOW_NAME = "CI"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
DEV_GATE = "Dev CI gate"
FULL_GATE = "Full CI gate"
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


def _workflow_id(client: Client) -> int:
    return ci.validate_workflow_identity(
        client.workflow(CI_WORKFLOW_FILE),
        expected_name=CI_WORKFLOW_NAME,
        expected_path=CI_WORKFLOW_PATH,
    )


def latest_dev_run(client: Client, repository: str, sha: str):
    workflow_id = _workflow_id(client)
    return ci.select_latest_exact_run(
        client.workflow_runs(
            workflow_id=workflow_id,
            branch="dev",
            event="push",
            commit_sha=sha,
        ),
        repository=repository,
        workflow_id=workflow_id,
        workflow_path=CI_WORKFLOW_PATH,
        branch="dev",
        event="push",
        commit_sha=sha,
    )


def verified_dev(
    client: Client,
    repository: str,
    sha: str,
    *,
    expected_run_id: int | None = None,
    expected_run_attempt: int | None = None,
):
    return ci.wait_for_verified_source_ci(
        client,
        repository=repository,
        workflow_file=CI_WORKFLOW_FILE,
        workflow_name=CI_WORKFLOW_NAME,
        workflow_path=CI_WORKFLOW_PATH,
        branch="dev",
        event="push",
        commit_sha=sha,
        required_job_names=(DEV_GATE,),
        timeout_seconds=0,
        poll_interval_seconds=1,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
    )


def select(
    client: Client,
    repository: str,
    *,
    expected_run_id: int | None = None,
    expected_run_attempt: int | None = None,
) -> Selection | None:
    """Select only the current green dev head; never fall back to an ancestor."""

    main = client.ref("main")
    dev = client.ref("dev")
    if main == dev:
        return None
    if client.relation(main, dev) != "ahead":
        raise ci.SourceCIVerificationError("promotion_dev_must_contain_main")

    run = latest_dev_run(client, repository, dev)
    if run is None:
        return None
    if expected_run_id is not None and run.get("id") != expected_run_id:
        raise ci.SourceCIVerificationError("promotion_trigger_run_changed")
    if expected_run_attempt is not None and run.get("run_attempt") != expected_run_attempt:
        raise ci.SourceCIVerificationError("promotion_trigger_attempt_changed")

    status = run.get("status")
    if status in ci._PENDING_STATUSES:
        return None
    if status != "completed":
        raise ci.SourceCIVerificationError("promotion_ci_state_invalid")
    if run.get("conclusion") != "success":
        return None

    evidence = verified_dev(
        client,
        repository,
        dev,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
    )
    return Selection(main, dev, dev, evidence.run_id, evidence.run_attempt)


def _latest_full_run(client: Client, repository: str, sha: str):
    workflow_id = _workflow_id(client)
    return ci.select_latest_exact_run(
        client.workflow_runs(
            workflow_id=workflow_id,
            branch="dev",
            event="workflow_dispatch",
            commit_sha=sha,
        ),
        repository=repository,
        workflow_id=workflow_id,
        workflow_path=CI_WORKFLOW_PATH,
        branch="dev",
        event="workflow_dispatch",
        commit_sha=sha,
    )


def ensure_full_ci(
    client: Client,
    repository: str,
    selection: Selection,
    *,
    timeout_seconds: float,
):
    """Ensure complete exact-SHA CI exists before any main/status write.

    A missing full run is dispatched against ``ref=dev`` so GitHub loads the
    candidate SHA's own workflow definition. Existing failed runs are not
    silently replaced; an owner must explicitly rerun or retrigger promotion.
    """

    if client.ref("main") != selection.previous_main:
        raise ci.SourceCIVerificationError("promotion_main_changed_before_full_ci")
    if client.ref("dev") != selection.observed_dev:
        raise ci.SourceCIVerificationError("promotion_dev_changed_before_full_ci")

    latest = _latest_full_run(client, repository, selection.commit_sha)
    if latest is None:
        client.write(
            f"actions/workflows/{CI_WORKFLOW_FILE}/dispatches",
            {
                "ref": "dev",
                "inputs": {
                    "mode": "full",
                    "commit_sha": selection.commit_sha,
                    "base_sha": selection.previous_main,
                },
            },
            method="POST",
        )

    return ci.wait_for_verified_source_ci(
        client,
        repository=repository,
        workflow_file=CI_WORKFLOW_FILE,
        workflow_name=CI_WORKFLOW_NAME,
        workflow_path=CI_WORKFLOW_PATH,
        branch="dev",
        event="workflow_dispatch",
        commit_sha=selection.commit_sha,
        required_job_names=(FULL_GATE,),
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=10,
    )


def apply(
    client: Client,
    repository: str,
    selection: Selection,
    *,
    full: ci.VerifiedSourceCI,
) -> dict:
    """Revalidate both CI layers and refs, then non-force fast-forward main."""

    for sha in (selection.previous_main, selection.observed_dev, selection.commit_sha):
        checked_sha(sha)
    if selection.commit_sha != selection.observed_dev:
        raise ci.SourceCIVerificationError("promotion_candidate_must_be_dev_head")
    if full.commit_sha != selection.commit_sha:
        raise ci.SourceCIVerificationError("promotion_full_ci_sha_mismatch")

    dev_evidence = verified_dev(
        client,
        repository,
        selection.commit_sha,
        expected_run_id=selection.run_id,
        expected_run_attempt=selection.run_attempt,
    )
    if (dev_evidence.run_id, dev_evidence.run_attempt) != (
        selection.run_id,
        selection.run_attempt,
    ):
        raise ci.SourceCIVerificationError("promotion_dev_ci_attempt_changed")

    full_evidence = ci.wait_for_verified_source_ci(
        client,
        repository=repository,
        workflow_file=CI_WORKFLOW_FILE,
        workflow_name=CI_WORKFLOW_NAME,
        workflow_path=CI_WORKFLOW_PATH,
        branch="dev",
        event="workflow_dispatch",
        commit_sha=selection.commit_sha,
        required_job_names=(FULL_GATE,),
        timeout_seconds=0,
        poll_interval_seconds=1,
        expected_run_id=full.run_id,
        expected_run_attempt=full.run_attempt,
    )
    if full_evidence.commit_sha != selection.commit_sha:
        raise ci.SourceCIVerificationError("promotion_full_ci_changed")

    if client.ref("dev") != selection.observed_dev:
        raise ci.SourceCIVerificationError("promotion_dev_changed; retry selection")
    current = client.ref("main")
    if current not in {selection.previous_main, selection.commit_sha}:
        raise ci.SourceCIVerificationError("promotion_main_changed; retry selection")
    if client.relation(selection.previous_main, selection.commit_sha) != "ahead":
        raise ci.SourceCIVerificationError("promotion_not_fast_forward")

    changed = current != selection.commit_sha
    if changed:
        client.write(
            f"statuses/{selection.commit_sha}",
            {
                "state": "success",
                "context": PROMOTION_GATE,
                "description": "Exact dev HEAD passed complete Full CI",
                "target_url": full_evidence.run_url,
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
    return {
        **asdict(selection),
        "main_updated": changed,
        "full_ci_run_id": full_evidence.run_id,
        "full_ci_run_attempt": full_evidence.run_attempt,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--expected-dev-run-id", type=int)
    parser.add_argument("--expected-dev-run-attempt", type=int)
    args = parser.parse_args(argv)
    try:
        client = Client(
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            repository=args.repository or "",
            token=os.environ.get("GITHUB_TOKEN", ""),
            api_version=os.environ.get("GITHUB_API_VERSION", "2022-11-28"),
        )
        selection = select(
            client,
            args.repository or "",
            expected_run_id=args.expected_dev_run_id,
            expected_run_attempt=args.expected_dev_run_attempt,
        )
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
