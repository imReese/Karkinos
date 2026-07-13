"""Verify a built Karkinos container starts with fail-closed authority defaults."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args(argv)

    settings = _wait_for_json(
        f"{args.base_url.rstrip('/')}/api/settings",
        timeout_seconds=args.timeout_seconds,
    )
    statuses = {
        "settings": settings,
        "capital_authority": _fetch_json(
            f"{args.base_url.rstrip('/')}/api/automation/capital-authority/status"
        ),
        "controlled_bridge": _fetch_json(
            f"{args.base_url.rstrip('/')}/api/automation/controlled-bridge/status"
        ),
        "controlled_submission": _fetch_json(
            f"{args.base_url.rstrip('/')}/api/automation/controlled-broker-submission/status"
        ),
    }
    _assert_fail_closed_defaults(statuses)
    print(json.dumps(statuses, ensure_ascii=False, sort_keys=True))
    return 0


def _wait_for_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return _fetch_json(url)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"container did not become healthy: {type(last_error).__name__}")


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5.0) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status: {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    return payload


def _assert_fail_closed_defaults(statuses: Mapping[str, Mapping[str, Any]]) -> None:
    capital = statuses["capital_authority"]
    bridge = statuses["controlled_bridge"]
    submission = statuses["controlled_submission"]

    expected = {
        "capital runtime authority": capital.get("runtime_authority_status")
        == "disabled",
        "capital execution authority": capital.get("execution_authority_enabled")
        is False,
        "capital broker submission": capital.get("broker_submission_enabled") is False,
        "bridge runtime authority": bridge.get("runtime_execution_authority")
        == "disabled",
        "bridge broker submission": bridge.get("broker_submission_enabled") is False,
        "bridge live gateway": bridge.get("live_gateway_implemented") is False,
        "default broker submission": submission.get("default_broker_submission_enabled")
        is False,
        "automatic broker submission": submission.get("automatic_submission_enabled")
        is False,
        "strategy-direct broker submission": submission.get(
            "strategy_direct_submission_enabled"
        )
        is False,
        "recovery resubmission": submission.get("recovery_resubmission_enabled")
        is False,
        "no production gateway": submission.get("registered_gateway_ids") == [],
    }
    failures = [name for name, passed in expected.items() if not passed]
    if failures:
        raise AssertionError(
            "container authority defaults are not fail-closed: " + ", ".join(failures)
        )


if __name__ == "__main__":
    raise SystemExit(main())
