"""Fast-forward main only to the exact current dev HEAD with a successful gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlencode

GATE = "Promotion Gate"


class PromotionError(RuntimeError):
    """Promotion could not establish or preserve its authorization."""


def checked_sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise PromotionError("promotion_invalid_sha")
    return value


class Client:
    def __init__(self, repository: str):
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
            raise PromotionError("promotion_invalid_repository")
        self.repository = repository

    def request(self, path: str, payload: dict | None = None) -> dict:
        command = [
            "gh",
            "api",
            f"repos/{self.repository}/{path}",
            "--method",
            "GET" if payload is None else "PATCH",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            "-H",
            "Cache-Control: no-cache",
        ]
        if payload is not None:
            command.extend(["--input", "-"])
        try:
            result = subprocess.run(
                command,
                input=None if payload is None else json.dumps(payload),
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            data = json.loads(result.stdout)
        except subprocess.CalledProcessError as exc:
            raise PromotionError(
                f"promotion_api_rejected: {exc.stderr.strip()}"
            ) from exc
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise PromotionError(
                "promotion_api_inconclusive; inspect refs before retrying"
            ) from exc
        if not isinstance(data, dict):
            raise PromotionError("promotion_api_response_invalid")
        return data

    def ref(self, branch: str) -> str:
        ref = self.request(f"git/ref/heads/{branch}")
        if (
            ref.get("ref") != f"refs/heads/{branch}"
            or ref.get("object", {}).get("type") != "commit"
        ):
            raise PromotionError("promotion_ref_identity_invalid")
        return checked_sha(ref["object"].get("sha"))

    def is_ancestor(self, base: str, head: str) -> bool:
        relation = self.request(f"compare/{checked_sha(base)}...{checked_sha(head)}")
        return (
            relation.get("status") in {"ahead", "identical"}
            and relation.get("merge_base_commit", {}).get("sha") == base
        )

    def require_gate(self, sha: str) -> None:
        query = urlencode(
            {
                "branch": "dev",
                "event": "push",
                "head_sha": checked_sha(sha),
                "per_page": 1,
            }
        )
        # Select the latest run, including pending/failed runs; never search for an older green run.
        runs = self.request(f"actions/workflows/ci.yml/runs?{query}").get(
            "workflow_runs", []
        )
        if not runs:
            raise PromotionError("promotion_gate_missing")
        run = runs[0]
        if (
            run.get("head_sha") != sha
            or run.get("head_branch") != "dev"
            or run.get("event") != "push"
            or run.get("path") != ".github/workflows/ci.yml"
            or run.get("repository", {}).get("full_name") != self.repository
            or run.get("head_repository", {}).get("full_name") != self.repository
            or run.get("status") != "completed"
        ):
            raise PromotionError("promotion_gate_source_invalid_or_pending")
        suite = run.get("check_suite_id")
        if type(suite) is not int or suite <= 0:
            raise PromotionError("promotion_gate_suite_invalid")
        query = urlencode({"check_name": GATE, "filter": "latest", "per_page": 100})
        data = self.request(f"check-suites/{suite}/check-runs?{query}")
        checks = data.get("check_runs", [])
        if data.get("total_count") != 1 or len(checks) != 1:
            raise PromotionError("promotion_gate_missing_or_ambiguous")
        check = checks[0]
        if (
            check.get("name") != GATE
            or check.get("head_sha") != sha
            or check.get("check_suite", {}).get("id") != suite
            or check.get("app", {}).get("id") != 15368
            or check.get("app", {}).get("slug") != "github-actions"
            or check.get("status") != "completed"
            or check.get("conclusion") != "success"
        ):
            raise PromotionError("promotion_gate_not_success_or_identity_invalid")


def promote(client: Client, *, apply: bool = False) -> dict:
    previous_main = client.ref("main")
    candidate = client.ref("dev")
    if previous_main == candidate:
        return {"main": previous_main, "dev": candidate, "main_updated": False}
    client.require_gate(candidate)
    if not client.is_ancestor(previous_main, candidate):
        raise PromotionError("promotion_main_must_be_ancestor")
    if apply:
        client.require_gate(candidate)
    # The REST ref API has no compare-and-swap; re-read immediately before its non-force write.
    if client.ref("main") != previous_main or client.ref("dev") != candidate:
        raise PromotionError("promotion_refs_changed")
    if apply:
        client.request("git/refs/heads/main", {"sha": candidate, "force": False})
        # GitHub may briefly serve the previous ref after acknowledging the write.
        for attempt in range(10):
            observed = client.ref("main")
            if observed == candidate:
                break
            if observed != previous_main or attempt == 9:
                raise PromotionError("promotion_main_write_not_confirmed")
            time.sleep(1)
    return {"previous_main": previous_main, "dev": candidate, "main_updated": apply}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the verified non-force fast-forward",
    )
    args = parser.parse_args(argv)
    try:
        result = promote(Client(args.repository), apply=args.apply)
    except PromotionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
