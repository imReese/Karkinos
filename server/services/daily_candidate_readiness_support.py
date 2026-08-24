"""Pure safety and normalization helpers for candidate readiness projections."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def non_authority_boundary_blockers(
    *,
    cockpit: dict[str, Any],
    preflight: dict[str, Any],
    runtime: dict[str, Any],
    trial: dict[str, Any],
    research: dict[str, Any],
) -> list[str]:
    checks = {
        "cockpit_broker_submission_enabled": cockpit.get("broker_submission_enabled"),
        "preflight_provider_contact_performed": preflight.get(
            "provider_contact_performed"
        ),
        "preflight_database_writes_performed": preflight.get(
            "database_writes_performed"
        ),
        "preflight_broker_submission_enabled": preflight.get(
            "broker_submission_enabled"
        ),
        "preflight_authorizes_execution": preflight.get("authorizes_execution"),
        "preflight_changes_capital_authority": preflight.get(
            "changes_capital_authority"
        ),
        "runtime_provider_contact_performed": runtime.get("provider_contact_performed"),
        "runtime_database_writes_performed": runtime.get("database_writes_performed"),
        "runtime_broker_submission_enabled": runtime.get("broker_submission_enabled"),
        "runtime_authorizes_execution": runtime.get("authorizes_execution"),
        "runtime_changes_capital_authority": runtime.get("changes_capital_authority"),
        "trial_broker_submission_enabled": trial.get("broker_submission_enabled"),
        "trial_authorizes_execution": trial.get("authorizes_execution"),
        "trial_changes_capital_authority": trial.get("changes_capital_authority"),
        "research_broker_submission_enabled": research.get("broker_submission_enabled"),
        "research_production_strategy_mutation_enabled": research.get(
            "production_strategy_mutation_enabled"
        ),
        "research_automatic_strategy_replacement_enabled": research.get(
            "automatic_strategy_replacement_enabled"
        ),
    }
    return [
        f"{name}_boundary_invalid"
        for name, value in checks.items()
        if value is not False
    ]


def research_policy_blockers(
    policy: dict[str, Any],
    *,
    max_candidates: int,
    max_provider_calls: int,
    unbounded_token_budget_mode: str,
    policy_confirmation: str,
) -> list[str]:
    blockers = []
    if policy.get("enabled") is not True:
        blockers.append("five_sequential_iteration_policy_disabled")
    if policy.get("max_candidates_per_run") != max_candidates:
        blockers.append("five_sequential_iteration_count_not_authorized")
    if policy.get("max_provider_calls_per_market_date") != max_provider_calls:
        blockers.append("ten_provider_call_limit_not_authorized")
    if (
        policy.get("daily_token_budget") is not None
        or policy.get("token_budget_mode") != unbounded_token_budget_mode
    ):
        blockers.append("unbounded_daily_token_policy_not_authorized")
    if policy.get("authorization") != policy_confirmation:
        blockers.append("five_sequential_iteration_authorization_missing")
    if policy.get("require_complete_account_evidence") is not True:
        blockers.append("complete_account_evidence_requirement_disabled")
    return blockers


def schema_blockers(
    expected_schemas: dict[str, str],
    **payloads: dict[str, Any],
) -> list[str]:
    return [
        f"{name}_contract_invalid"
        for name, expected in expected_schemas.items()
        if payloads[name].get("schema_version") != expected
    ]


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return unique([str(item) for item in value if str(item)])


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_sha256(value: Any) -> bool:
    normalized = str(value or "")
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def matches_fingerprint(value: dict[str, Any], expected: Any) -> bool:
    if not is_sha256(expected):
        return False
    try:
        return expected == fingerprint(value)
    except (TypeError, ValueError):
        return False


def safe_fingerprint(value: Any) -> str | None:
    normalized = str(value or "")
    if len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    ):
        return normalized
    return None


def safe_code(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if not normalized or len(normalized) > 120:
        return "daily_candidate_production_readiness_unavailable"
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_:-."
        for character in normalized
    ):
        return "daily_candidate_production_readiness_unavailable"
    return normalized


def is_safe_code(value: Any) -> bool:
    return isinstance(value, str) and value == safe_code(value)


def is_safe_code_list(value: Any, *, allow_empty: bool = False) -> bool:
    return bool(
        isinstance(value, list)
        and (value or allow_empty)
        and all(is_safe_code(item) for item in value)
    )


def fingerprint(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
