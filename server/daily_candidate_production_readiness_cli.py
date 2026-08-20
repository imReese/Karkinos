"""Loopback-only CLI implementation for live daily-candidate readiness."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from server.services.daily_candidate_production_readiness import (
    project_daily_candidate_production_readiness,
    unavailable_daily_candidate_production_readiness,
)

FetchJson = Callable[[str, float], dict[str, Any]]
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch_json: FetchJson | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    output = stdout or sys.stdout
    try:
        base_url = _loopback_base_url(args.base_url)
        fetch = fetch_json or _fetch_json
        cockpit = fetch(f"{base_url}/api/automation/cockpit", args.timeout)
        research = fetch(
            f"{base_url}/api/ai/strategy-research/shadow-automation",
            args.timeout,
        )
        report = project_daily_candidate_production_readiness(
            cockpit=cockpit,
            research_status=research,
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        report = unavailable_daily_candidate_production_readiness()

    text = json.dumps(
        report,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    output.write(f"{text}\n")
    return 0 if report["ready_for_production_operation"] else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read current Karkinos daily-candidate readiness from loopback-only APIs."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Loopback Karkinos base URL; external hosts and credentials are rejected.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Per-request timeout in seconds, greater than 0 and at most 10.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser


def _loopback_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid loopback base URL") from exc
    if parsed.scheme != "http":
        raise ValueError("base URL must use http")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("base URL must be loopback-only")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("base URL must not contain an API path")
    if port is None:
        raise ValueError("base URL must include an explicit port")
    return urlunsplit(("http", parsed.netloc, "", "", "")).rstrip("/")


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    if timeout <= 0 or timeout > 10:
        raise ValueError("timeout must be greater than 0 and at most 10")
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
        body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("local API response exceeds size limit")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("local API response must be an object")
    return payload
