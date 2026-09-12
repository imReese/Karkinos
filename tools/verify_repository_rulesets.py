#!/usr/bin/env python3
"""Verify tracked repository ruleset desired state against GitHub server state.

This command is deliberately read-only. Repository security configuration is an
owner-controlled operation; normal CI may detect drift but must never mutate
branch or tag protection as a side effect.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RulesetVerificationError(RuntimeError):
    """Raised when repository ruleset state is missing, unsafe, or divergent."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("repository_ruleset_api_redirect_rejected")


urlopen = build_opener(_NoRedirectHandler()).open


def _validate_api_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RulesetVerificationError("repository_ruleset_api_url_invalid")
    return value.rstrip("/")


def _get_json(url: str, token: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "karkinos-ruleset-verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RulesetVerificationError(
                    f"repository_ruleset_api_status_unexpected:{response.status}"
                )
            return json.load(response)
    except HTTPError as exc:
        raise RulesetVerificationError(
            f"repository_ruleset_api_http_error:{exc.code}"
        ) from exc
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RulesetVerificationError(
            "repository_ruleset_api_request_inconclusive"
        ) from exc


def _sorted_json(values: list[Any]) -> list[Any]:
    return sorted(values, key=lambda value: json.dumps(value, sort_keys=True))


def canonical_ruleset(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the security-relevant subset used for desired-state comparison."""

    conditions = payload.get("conditions")
    if not isinstance(conditions, dict):
        raise RulesetVerificationError("repository_ruleset_conditions_invalid")
    ref_name = conditions.get("ref_name")
    if not isinstance(ref_name, dict):
        raise RulesetVerificationError("repository_ruleset_ref_condition_invalid")

    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise RulesetVerificationError("repository_ruleset_rules_invalid")
    normalized_rules: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
            raise RulesetVerificationError("repository_ruleset_rule_invalid")
        normalized = {"type": rule["type"]}
        parameters = rule.get("parameters")
        if parameters is not None:
            if not isinstance(parameters, dict):
                raise RulesetVerificationError(
                    "repository_ruleset_rule_parameters_invalid"
                )
            parameters = dict(parameters)
            checks = parameters.get("required_status_checks")
            if checks is not None:
                if not isinstance(checks, list):
                    raise RulesetVerificationError(
                        "repository_ruleset_required_checks_invalid"
                    )
                parameters["required_status_checks"] = _sorted_json(checks)
            normalized["parameters"] = parameters
        normalized_rules.append(normalized)

    bypass = payload.get("bypass_actors", [])
    if not isinstance(bypass, list):
        raise RulesetVerificationError("repository_ruleset_bypass_invalid")

    name = payload.get("name")
    target = payload.get("target")
    enforcement = payload.get("enforcement")
    if not all(isinstance(value, str) and value for value in (name, target, enforcement)):
        raise RulesetVerificationError("repository_ruleset_identity_invalid")

    include = ref_name.get("include", [])
    exclude = ref_name.get("exclude", [])
    if not isinstance(include, list) or not isinstance(exclude, list):
        raise RulesetVerificationError("repository_ruleset_ref_values_invalid")

    return {
        "name": name,
        "target": target,
        "enforcement": enforcement,
        "bypass_actors": _sorted_json(bypass),
        "conditions": {
            "ref_name": {
                "include": sorted(include),
                "exclude": sorted(exclude),
            }
        },
        "rules": _sorted_json(normalized_rules),
    }


def load_desired(directory: Path) -> dict[str, dict[str, Any]]:
    desired: dict[str, dict[str, Any]] = {}
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise RulesetVerificationError("repository_ruleset_desired_state_missing")
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RulesetVerificationError(
                f"repository_ruleset_desired_state_invalid:{path}"
            ) from exc
        if not isinstance(payload, dict):
            raise RulesetVerificationError(
                f"repository_ruleset_desired_state_invalid:{path}"
            )
        canonical = canonical_ruleset(payload)
        name = canonical["name"]
        if name in desired:
            raise RulesetVerificationError(
                f"repository_ruleset_duplicate_desired_name:{name}"
            )
        desired[name] = canonical
    return desired


def fetch_actual(
    *, api_url: str, repository: str, token: str
) -> dict[str, dict[str, Any]]:
    base = f"{_validate_api_url(api_url)}/repos/{repository}"
    collection = _get_json(f"{base}/rulesets", token)
    if not isinstance(collection, list):
        raise RulesetVerificationError("repository_ruleset_collection_invalid")

    actual: dict[str, dict[str, Any]] = {}
    for summary in collection:
        if not isinstance(summary, dict):
            raise RulesetVerificationError("repository_ruleset_summary_invalid")
        ruleset_id = summary.get("id")
        name = summary.get("name")
        if type(ruleset_id) is not int or ruleset_id <= 0 or not isinstance(name, str):
            raise RulesetVerificationError("repository_ruleset_summary_invalid")
        detail = _get_json(f"{base}/rulesets/{ruleset_id}", token)
        if not isinstance(detail, dict):
            raise RulesetVerificationError("repository_ruleset_detail_invalid")
        canonical = canonical_ruleset(detail)
        if canonical["name"] != name:
            raise RulesetVerificationError("repository_ruleset_name_changed")
        if name in actual:
            raise RulesetVerificationError(
                f"repository_ruleset_duplicate_server_name:{name}"
            )
        actual[name] = canonical
    return actual


def verify(desired: Mapping[str, dict[str, Any]], actual: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    missing = sorted(set(desired) - set(actual))
    drifted = sorted(
        name for name in set(desired) & set(actual) if desired[name] != actual[name]
    )
    result = {
        "schema_version": "karkinos.repository_ruleset_drift.v1",
        "desired_rulesets": sorted(desired),
        "missing_rulesets": missing,
        "drifted_rulesets": drifted,
        "in_sync": not missing and not drifted,
    }
    if not result["in_sync"]:
        raise RulesetVerificationError(json.dumps(result, sort_keys=True))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--desired-dir", type=Path, default=Path(".github/rulesets"))
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    args = parser.parse_args(argv)

    if "/" not in args.repository or args.repository.startswith("/") or args.repository.endswith("/"):
        print("repository_ruleset_repository_invalid", file=sys.stderr)
        return 1

    try:
        desired = load_desired(args.desired_dir)
        actual = fetch_actual(
            api_url=args.api_url,
            repository=quote(args.repository, safe="/"),
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
        result = verify(desired, actual)
    except RulesetVerificationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
