"""Standing opt-in for independent, noncapital research simulation."""

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from server.contracts.content_identity import content_fingerprint

OBSERVATION_AUTOMATION_SCHEMA = "karkinos.research_observation_automation.v1"
OBSERVATION_AUTOMATION_PREFIX = "research-observation:"
OBSERVATION_DATASET_SELECTION = "latest_verified_exact_prefix.v1"
SIMULATION_VALIDATION_SCHEMA = "karkinos.research_simulation_policy.v1"
SIMULATION_VALIDATION_AUTHORIZE = (
    "authorize_bounded_independent_research_simulation_without_account_"
    "publication_trade_or_capital_authority"
)


def validate_simulation_validation_policy(value):
    """Validate explicit hypothetical scope without borrowing account evidence."""
    from server.contracts.normalized_strategy_research import (
        CANONICAL_COST_MODEL_REFERENCE,
    )
    from server.contracts.recommendation_publication import (
        publication_number,
        publication_time,
        validate_entry_board_policy,
        validate_final_statistical_policy,
    )

    if not isinstance(value, Mapping):
        raise ValueError("simulation_policy_missing")
    policy = dict(value)
    if policy.get("schema_version") != SIMULATION_VALIDATION_SCHEMA:
        raise ValueError("simulation_policy_schema_invalid")
    for key in ("grant_id", "generation"):
        UUID(str(policy.get(key) or ""))
    if type(policy.get("enabled")) is not bool:
        raise ValueError("simulation_policy_enabled_invalid")
    if not policy["enabled"]:
        return policy
    if policy.get("authorization") != SIMULATION_VALIDATION_AUTHORIZE:
        raise ValueError("simulation_policy_authorization_missing")
    if policy.get("strategy_family") != "formula":
        raise ValueError("simulation_strategy_family_unsupported")
    if policy.get("cost_model_reference") != CANONICAL_COST_MODEL_REFERENCE:
        raise ValueError("simulation_cost_model_unsupported")
    if publication_number(policy.get("initial_cash")) <= 0:
        raise ValueError("simulation_notional_invalid")
    if (
        type(policy.get("max_concurrent_candidates")) is not int
        or policy["max_concurrent_candidates"] != 1
    ):
        raise ValueError("simulation_concurrency_unsupported")
    scope = policy.get("deployment_scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("scope_kind") != "full_declared_market"
    ):
        raise ValueError("simulation_full_scope_required")
    # Canonical market-scope equality is checked by the application owner.
    if policy.get("deployment_scope_fingerprint") != scope.get(
        "deployment_scope_fingerprint"
    ):
        raise ValueError("simulation_scope_binding_invalid")
    risk = policy.get("risk_limits")
    if (
        not isinstance(risk, Mapping)
        or set(risk)
        != {"max_drawdown", "max_gross_weight", "max_symbol_weight", "max_positions"}
        or type(risk.get("max_positions")) is not int
        or risk["max_positions"] < 4
    ):
        raise ValueError("simulation_risk_limits_invalid")
    for key, floor in (
        ("max_drawdown", "0"),
        ("max_gross_weight", "0.97"),
        ("max_symbol_weight", "0.25"),
    ):
        number = publication_number(risk[key])
        if not Decimal(floor) <= number <= 1 or number <= 0:
            raise ValueError("simulation_risk_limits_invalid")
    validate_entry_board_policy(policy.get("entry_board_policy"))
    profile = validate_final_statistical_policy(
        policy.get("statistical_policy"),
        str(policy.get("statistical_policy_fingerprint") or ""),
    )
    if profile["minimum_observations"] < 60:
        raise ValueError("simulation_minimum_forward_observations_required")
    if type(policy.get("max_final_tests")) is not int or policy["max_final_tests"] < 1:
        raise ValueError("simulation_final_test_budget_invalid")
    alpha = publication_number(profile["significance_level"])
    budget = publication_number(policy.get("total_error_budget"))
    if not 0 < budget < 1 or alpha * policy["max_final_tests"] > budget:
        raise ValueError("simulation_error_budget_invalid")
    if profile["bootstrap_samples"] * alpha / 10 < 20:
        raise ValueError("simulation_bootstrap_tail_insufficient")
    expiry = publication_time(policy.get("expires_at"))
    from datetime import date

    if date.fromisoformat(profile["decision_checkpoint"]) >= expiry.date():
        raise ValueError("simulation_checkpoint_after_expiry")
    if not str(policy.get("updated_by") or "").strip():
        raise ValueError("simulation_owner_missing")
    return policy


def read_simulation_validation_policy(db, *, now=None):
    from server.contracts.recommendation_publication import publication_time

    raw = db.get_automation_policy_sync("ai_shadow_research") or {}
    policy = validate_simulation_validation_policy(raw.get("simulation_validation"))
    if not policy["enabled"]:
        raise ValueError("simulation_policy_disabled")
    if publication_time(now or datetime.now(timezone.utc)) >= publication_time(
        policy["expires_at"]
    ):
        raise ValueError("simulation_policy_expired")
    return policy


def read_research_validation_policy(db, *, now=None):
    """Independent SIM is preferred; old publication-bound experiments remain valid."""
    from server.contracts.recommendation_publication import read_publication_grant

    raw = db.get_automation_policy_sync("ai_shadow_research") or {}
    if raw.get("simulation_validation") is not None:
        return read_simulation_validation_policy(db, now=now)
    return read_publication_grant(db, now=now)


def reserved_validation_policy(binding):
    return binding.get("simulation_policy") or binding["publication_grant"]


def require_current_simulation_authorization(db, policy, *, now):
    authorization = policy.get("authorization_binding") or {}
    if authorization.get("authority_kind") != "simulation":
        return
    current = read_simulation_validation_policy(db, now=now)
    if any(
        authorization.get(key) != current[key] for key in ("grant_id", "generation")
    ):
        raise ValueError("simulation_authorization_changed")


def reserved_forward_identity(reservation_id, grant):
    key = "reserved-forward:" + content_fingerprint(
        {
            "reservation_id": reservation_id,
            "grant_id": grant["grant_id"],
            "generation": grant["generation"],
        }
    )
    request_id = key + ":observation"
    return key, str(uuid5(NAMESPACE_URL, f"karkinos:research-observation:{request_id}"))


def observation_automation_policy_id(observation_id: str) -> str:
    return f"{OBSERVATION_AUTOMATION_PREFIX}{observation_id}"


def observation_automation_policy_valid(value: object, observation_id: str) -> bool:
    try:
        generation = value.get("generation") if isinstance(value, dict) else None
        if not isinstance(generation, str) or str(UUID(generation)) != generation:
            return False
    except ValueError:
        return False
    return (
        isinstance(observation_id, str)
        and bool(observation_id)
        and isinstance(value, dict)
        and value.get("schema_version") == OBSERVATION_AUTOMATION_SCHEMA
        and value.get("observation_id") == observation_id
        and type(value.get("enabled")) is bool
        and type(value.get("paper_settlement_enabled", False)) is bool
        and type(value.get("dataset_preparation_enabled", False)) is bool
        and value.get("dataset_selection") == OBSERVATION_DATASET_SELECTION
        and value.get("local_data_only") is True
        and value.get("account_authority") is False
    )
