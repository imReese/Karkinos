#!/usr/bin/env python3
"""Run dev-to-main promotion using the incremental Dev CI as source evidence."""

from __future__ import annotations

from tools import promote_dev as promotion
from tools import verify_release_source_ci as ci

_REQUIRED_JOBS = ("Code CI gate",)
_WORKFLOW_FILE = "dev-ci.yml"
_WORKFLOW_NAME = "Dev CI"
_WORKFLOW_PATH = ".github/workflows/dev-ci.yml"


def latest_run(
    client: promotion.Client,
    repository: str,
    branch: str,
    sha: str,
    event: str = "push",
):
    workflow_id = ci.validate_workflow_identity(
        client.workflow(_WORKFLOW_FILE),
        expected_name=_WORKFLOW_NAME,
        expected_path=_WORKFLOW_PATH,
    )
    return ci.select_latest_exact_run(
        client.workflow_runs(
            workflow_id=workflow_id,
            branch=branch,
            event=event,
            commit_sha=sha,
        ),
        repository=repository,
        workflow_id=workflow_id,
        workflow_path=_WORKFLOW_PATH,
        branch=branch,
        event=event,
        commit_sha=sha,
    )


def verified_dev(client: promotion.Client, repository: str, sha: str):
    return ci.wait_for_verified_source_ci(
        client,
        repository=repository,
        workflow_file=_WORKFLOW_FILE,
        workflow_name=_WORKFLOW_NAME,
        workflow_path=_WORKFLOW_PATH,
        branch="dev",
        event="push",
        commit_sha=sha,
        required_job_names=_REQUIRED_JOBS,
        timeout_seconds=0,
        poll_interval_seconds=1,
    )


def main() -> int:
    promotion.REQUIRED_JOBS = _REQUIRED_JOBS
    promotion.latest_run = latest_run
    promotion.verified_dev = verified_dev
    return promotion.main()


if __name__ == "__main__":
    raise SystemExit(main())
