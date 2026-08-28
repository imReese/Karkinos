#!/usr/bin/env python3
"""Verify that a release commit already passed the complete main CI gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_PENDING_STATUSES = {
    "in_progress",
    "pending",
    "queued",
    "requested",
    "waiting",
}


class SourceCIVerificationError(RuntimeError):
    """Raised when release CI evidence is missing, unsafe, or inconclusive."""


@dataclass(frozen=True)
class VerifiedSourceCI:
    commit_sha: str
    run_id: int
    run_attempt: int
    run_url: str
    required_job_ids: tuple[int, ...]


class GitHubActionsClient:
    def __init__(
        self,
        *,
        api_url: str,
        repository: str,
        token: str,
        api_version: str,
    ) -> None:
        if not token:
            raise SourceCIVerificationError("release_source_ci_token_missing")
        self._api_url = api_url.rstrip("/")
        self._repository = repository
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "karkinos-release-source-ci-verifier",
            "X-GitHub-Api-Version": api_version,
        }

    def workflow(self, workflow_file: str) -> Mapping[str, Any]:
        workflow = quote(workflow_file, safe="")
        return self._get_json(f"/repos/{self._repository}/actions/workflows/{workflow}")

    def workflow_runs(
        self,
        *,
        workflow_id: int,
        branch: str,
        event: str,
        commit_sha: str,
    ) -> Mapping[str, Any]:
        return self._get_json(
            f"/repos/{self._repository}/actions/workflows/{workflow_id}/runs",
            {
                "branch": branch,
                "event": event,
                "head_sha": commit_sha,
                "per_page": "100",
            },
        )

    def workflow_run_jobs(self, *, run_id: int) -> Mapping[str, Any]:
        return self._get_json(
            f"/repos/{self._repository}/actions/runs/{run_id}/jobs",
            {"filter": "latest", "per_page": "100"},
        )

    def _get_json(
        self, path: str, query: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        url = f"{self._api_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(url, headers=self._headers)
        try:
            with urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise SourceCIVerificationError(
                        f"release_source_ci_api_status_unexpected:{response.status}"
                    )
                payload = json.load(response)
        except HTTPError as exc:
            raise SourceCIVerificationError(
                f"release_source_ci_api_http_error:{exc.code}"
            ) from exc
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SourceCIVerificationError(
                "release_source_ci_api_request_inconclusive"
            ) from exc
        if not isinstance(payload, dict):
            raise SourceCIVerificationError("release_source_ci_api_payload_invalid")
        return payload


def validate_workflow_identity(
    payload: Mapping[str, Any], *, expected_name: str, expected_path: str
) -> int:
    workflow_id = payload.get("id")
    if not isinstance(workflow_id, int) or workflow_id <= 0:
        raise SourceCIVerificationError("release_source_ci_workflow_id_invalid")
    if payload.get("name") != expected_name:
        raise SourceCIVerificationError("release_source_ci_workflow_name_mismatch")
    if payload.get("path") != expected_path:
        raise SourceCIVerificationError("release_source_ci_workflow_path_mismatch")
    if payload.get("state") != "active":
        raise SourceCIVerificationError("release_source_ci_workflow_not_active")
    return workflow_id


def select_latest_exact_run(
    payload: Mapping[str, Any],
    *,
    repository: str,
    workflow_id: int,
    workflow_path: str,
    branch: str,
    event: str,
    commit_sha: str,
) -> Mapping[str, Any] | None:
    runs = _complete_page(payload, "workflow_runs")
    if not runs:
        return None

    validated: list[Mapping[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            raise SourceCIVerificationError("release_source_ci_run_payload_invalid")
        repository_payload = run.get("repository")
        head_repository = run.get("head_repository")
        if not isinstance(repository_payload, dict) or not isinstance(
            head_repository, dict
        ):
            raise SourceCIVerificationError(
                "release_source_ci_repository_identity_missing"
            )
        expected = {
            "workflow_id": workflow_id,
            "head_branch": branch,
            "event": event,
            "head_sha": commit_sha,
        }
        if any(run.get(key) != value for key, value in expected.items()):
            raise SourceCIVerificationError("release_source_ci_run_identity_mismatch")
        if _workflow_path_without_ref(run.get("path")) != workflow_path:
            raise SourceCIVerificationError("release_source_ci_run_path_mismatch")
        if repository_payload.get("full_name") != repository:
            raise SourceCIVerificationError("release_source_ci_run_repository_mismatch")
        if head_repository.get("full_name") != repository:
            raise SourceCIVerificationError(
                "release_source_ci_run_head_repository_mismatch"
            )
        _positive_int(run, "id", "release_source_ci_run_id_invalid")
        _positive_int(run, "run_number", "release_source_ci_run_number_invalid")
        _positive_int(run, "run_attempt", "release_source_ci_run_attempt_invalid")
        if not isinstance(run.get("html_url"), str) or not run["html_url"]:
            raise SourceCIVerificationError("release_source_ci_run_url_invalid")
        validated.append(run)

    return max(
        validated,
        key=lambda run: (
            int(run["run_number"]),
            int(run["run_attempt"]),
            int(run["id"]),
        ),
    )


def verify_required_jobs(
    payload: Mapping[str, Any],
    *,
    required_job_names: Sequence[str],
    commit_sha: str,
) -> tuple[int, ...]:
    jobs = _complete_page(payload, "jobs")
    verified_ids: list[int] = []
    for required_name in required_job_names:
        matches = [
            job
            for job in jobs
            if isinstance(job, dict) and job.get("name") == required_name
        ]
        if not matches:
            raise SourceCIVerificationError(
                f"release_source_ci_required_job_missing:{required_name}"
            )
        if len(matches) != 1:
            raise SourceCIVerificationError(
                f"release_source_ci_required_job_ambiguous:{required_name}"
            )
        job = matches[0]
        if job.get("head_sha") != commit_sha:
            raise SourceCIVerificationError(
                f"release_source_ci_required_job_sha_mismatch:{required_name}"
            )
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise SourceCIVerificationError(
                f"release_source_ci_required_job_not_success:{required_name}"
            )
        verified_ids.append(
            _positive_int(
                job,
                "id",
                f"release_source_ci_required_job_id_invalid:{required_name}",
            )
        )
    return tuple(verified_ids)


def wait_for_verified_source_ci(
    client: GitHubActionsClient,
    *,
    repository: str,
    workflow_file: str,
    workflow_name: str,
    workflow_path: str,
    branch: str,
    event: str,
    commit_sha: str,
    required_job_names: Sequence[str],
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> VerifiedSourceCI:
    if timeout_seconds < 0 or poll_interval_seconds <= 0:
        raise ValueError("release_source_ci_poll_configuration_invalid")
    if not required_job_names or len(set(required_job_names)) != len(
        required_job_names
    ):
        raise ValueError("release_source_ci_required_jobs_invalid")

    workflow_id = validate_workflow_identity(
        client.workflow(workflow_file),
        expected_name=workflow_name,
        expected_path=workflow_path,
    )
    deadline = time.monotonic() + timeout_seconds
    last_state = "missing"

    def fetch_latest_run() -> Mapping[str, Any] | None:
        return select_latest_exact_run(
            client.workflow_runs(
                workflow_id=workflow_id,
                branch=branch,
                event=event,
                commit_sha=commit_sha,
            ),
            repository=repository,
            workflow_id=workflow_id,
            workflow_path=workflow_path,
            branch=branch,
            event=event,
            commit_sha=commit_sha,
        )

    while True:
        run = fetch_latest_run()
        if run is not None:
            status = run.get("status")
            if status == "completed":
                conclusion = run.get("conclusion")
                if conclusion != "success":
                    raise SourceCIVerificationError(
                        f"release_source_ci_run_not_success:{conclusion}"
                    )
                run_id = int(run["id"])
                run_attempt = int(run["run_attempt"])
                job_ids = verify_required_jobs(
                    client.workflow_run_jobs(run_id=run_id),
                    required_job_names=required_job_names,
                    commit_sha=commit_sha,
                )
                confirmed_run = fetch_latest_run()
                if _run_snapshot(confirmed_run) == _run_snapshot(run):
                    return VerifiedSourceCI(
                        commit_sha=commit_sha,
                        run_id=run_id,
                        run_attempt=run_attempt,
                        run_url=str(run["html_url"]),
                        required_job_ids=job_ids,
                    )
                last_state = "changed_during_verification"
            else:
                if status not in _PENDING_STATUSES:
                    raise SourceCIVerificationError(
                        f"release_source_ci_run_status_invalid:{status}"
                    )
                last_state = str(status)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceCIVerificationError(
                f"release_source_ci_not_ready_before_timeout:{last_state}"
            )
        time.sleep(min(poll_interval_seconds, remaining))


def _complete_page(payload: Mapping[str, Any], key: str) -> list[Any]:
    values = payload.get(key)
    total_count = payload.get("total_count")
    if not isinstance(values, list) or not isinstance(total_count, int):
        raise SourceCIVerificationError(f"release_source_ci_{key}_payload_invalid")
    if total_count != len(values):
        raise SourceCIVerificationError(
            f"release_source_ci_{key}_pagination_incomplete"
        )
    return values


def _run_snapshot(run: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
    if run is None:
        return None
    return (
        run.get("id"),
        run.get("run_number"),
        run.get("run_attempt"),
        run.get("status"),
        run.get("conclusion"),
        run.get("head_sha"),
    )


def _workflow_path_without_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.split("@", 1)[0]


def _positive_int(payload: Mapping[str, Any], key: str, error: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value <= 0:
        raise SourceCIVerificationError(error)
    return value


def _append_github_outputs(path: Path, result: VerifiedSourceCI) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"commit_sha={result.commit_sha}\n")
        output.write(f"source_ci_run_id={result.run_id}\n")
        output.write(f"source_ci_run_attempt={result.run_attempt}\n")
        output.write(f"source_ci_run_url={result.run_url}\n")
        output.write(
            "source_ci_required_job_ids="
            f"{','.join(str(job_id) for job_id in result.required_job_ids)}\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--workflow-file", default="ci.yml")
    parser.add_argument("--workflow-name", default="CI")
    parser.add_argument("--workflow-path", default=".github/workflows/ci.yml")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--event", default="push")
    parser.add_argument("--required-job", action="append", dest="required_jobs")
    parser.add_argument("--timeout-seconds", type=float, default=1200)
    parser.add_argument("--poll-interval-seconds", type=float, default=15)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    if _REPOSITORY.fullmatch(args.repository) is None:
        print("release_source_ci_repository_invalid", file=sys.stderr)
        return 1
    if _FULL_SHA.fullmatch(args.commit_sha) is None:
        print("release_source_ci_commit_sha_invalid", file=sys.stderr)
        return 1

    required_jobs = tuple(
        args.required_jobs or ("Code CI gate", "Repository acceptance audit")
    )
    try:
        client = GitHubActionsClient(
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            repository=args.repository,
            token=os.environ.get("GITHUB_TOKEN", ""),
            api_version=os.environ.get("GITHUB_API_VERSION", "2026-03-10"),
        )
        result = wait_for_verified_source_ci(
            client,
            repository=args.repository,
            workflow_file=args.workflow_file,
            workflow_name=args.workflow_name,
            workflow_path=args.workflow_path,
            branch=args.branch,
            event=args.event,
            commit_sha=args.commit_sha,
            required_job_names=required_jobs,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
    except (SourceCIVerificationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.github_output is not None:
        _append_github_outputs(args.github_output, result)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
