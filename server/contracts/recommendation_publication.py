"""Explicit owner grants for bounded account-recommendation publication."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from server.contracts.content_identity import content_fingerprint

PUBLICATION_POLICY_ID = "ai_recommendation_publication"
PUBLICATION_POLICY_SCHEMA = "karkinos.recommendation_publication_policy.v1"
PUBLICATION_DECISION_SCHEMA = "karkinos.recommendation_publication_decision.v1"
PUBLICATION_AUTHORIZE = (
    "authorize_bounded_automatic_account_recommendation_publication_without_"
    "trade_or_capital_authority"
)
PUBLICATION_REVOKE = "revoke_automatic_account_recommendation_publication"
FINAL_STATISTICAL_POLICY_SCHEMA = "karkinos.research_final_statistical_policy"
LEGACY_FINAL_STATISTICAL_POLICY_SCHEMA = "karkinos.research_final_statistical_policy.v2"
FINAL_CALENDAR_AT_EVALUATION = "actual_sessions_then_complete_at_final"
LEGACY_CALENDAR_AT_EVALUATION = frozenset({"actual_sessions_then_complete_at_final.v1"})


def is_final_calendar_timing(value: Any) -> bool:
    """Accept the current identifier and the persisted legacy identifier."""

    return value in ({FINAL_CALENDAR_AT_EVALUATION} | LEGACY_CALENDAR_AT_EVALUATION)


_PRIMARY_COMPARATOR_POLICY_OPTIONAL_FIELDS = frozenset({"calendar_verification_timing"})
_PRIMARY_COMPARATOR_POLICY_FIELDS = frozenset(
    {
        "research_policy_fingerprint",
        "primary_comparator",
        "comparator_bindings",
        "minimum_candidate_net_return",
        "minimum_annualized_relative_wealth",
        "maximum_drawdown",
    }
)


def publication_time(value: Any) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("publication_timezone_required")
    return stamp.astimezone(timezone.utc)


def publication_number(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("publication_numeric_bound_invalid") from exc
    if isinstance(value, bool) or not number.is_finite():
        raise ValueError("publication_numeric_bound_invalid")
    return number


def fingerprinted(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    core = dict(value)
    fingerprint = core.pop("evidence_fingerprint", None)
    return fingerprint == content_fingerprint(core)


def _fingerprint(value: Any) -> str:
    text = str(value or "")
    bare = text.removeprefix("sha256:")
    if len(bare) != 64 or any(char not in "0123456789abcdef" for char in bare):
        raise ValueError("publication_binding_fingerprint_invalid")
    return text


def validate_entry_board_policy(value: Any) -> dict[str, Any]:
    """Missing old profiles never imply additional account board access."""
    if not isinstance(value, Mapping):
        raise ValueError("deployment_entry_board_policy_missing")
    core = dict(value)
    fingerprint = core.pop("evidence_fingerprint", None)
    allowed = core.get("allowed_boards")
    if (
        set(core)
        != {
            "allowed_boards",
            "permission_evidence_fingerprint",
            "reviewed_at",
            "excluded_boards",
        }
        or not isinstance(allowed, list)
        or any(not isinstance(board, str) for board in allowed)
        or allowed != sorted(set(allowed))
        or "main" not in allowed
        or not set(allowed) <= {"main", "chinext", "beijing"}
        or not isinstance(core["excluded_boards"], Mapping)
        or set(core["excluded_boards"])
        != {"main", "chinext", "star", "beijing"} - set(allowed)
        or core["excluded_boards"].get("star") != "unsupported_trade_unit"
        or fingerprint != content_fingerprint(core)
    ):
        raise ValueError("deployment_entry_board_policy_invalid")
    if set(allowed) - {"main"}:
        permission = str(core.get("permission_evidence_fingerprint") or "")
        if not (
            permission.startswith("sha256:")
            and len(permission) == 71
            and all(char in "0123456789abcdef" for char in permission[7:])
            and core.get("reviewed_at")
        ):
            raise ValueError("deployment_entry_board_permission_missing")
    return {**core, "evidence_fingerprint": fingerprint}


def is_final_statistical_policy(statistical: Mapping[str, Any]) -> bool:
    """Accept the current identifier and the persisted legacy identifier."""

    return statistical.get("schema_version") in {
        FINAL_STATISTICAL_POLICY_SCHEMA,
        LEGACY_FINAL_STATISTICAL_POLICY_SCHEMA,
    }


def validate_final_statistical_policy(
    statistical: Any, fingerprint: str
) -> dict[str, Any]:
    """Shared inference profile, independent of account-publication authority."""
    if (
        not isinstance(statistical, Mapping)
        or content_fingerprint(dict(statistical)) != fingerprint
    ):
        raise ValueError("publication_statistical_policy_binding_invalid")
    if statistical.get("method") != "paired_moving_block_bootstrap.v1":
        raise ValueError("publication_statistical_method_unsupported")
    for field in (
        "minimum_observations",
        "block_length",
        "minimum_effective_blocks",
        "bootstrap_samples",
    ):
        if type(statistical.get(field)) is not int or statistical[field] < 1:
            raise ValueError("publication_statistical_profile_invalid")
    if (
        max(
            statistical["minimum_observations"],
            statistical["block_length"] * statistical["minimum_effective_blocks"],
        )
        > 2000
    ):
        raise ValueError("publication_statistical_observation_budget_exceeded")
    interval = statistical.get("checkpoint_interval_days")
    if interval is not None and (type(interval) is not int or interval < 1):
        raise ValueError("publication_checkpoint_interval_invalid")
    if not 0 < publication_number(statistical.get("significance_level")) < 1:
        raise ValueError("publication_statistical_profile_invalid")
    if publication_number(statistical.get("minimum_net_excess")) < 0:
        raise ValueError("publication_statistical_profile_invalid")
    from datetime import date

    date.fromisoformat(str(statistical.get("decision_checkpoint") or ""))
    if is_final_statistical_policy(statistical):
        _validate_primary_comparator_policy(statistical)
    elif statistical.get("schema_version") is not None or (
        _PRIMARY_COMPARATOR_POLICY_FIELDS | _PRIMARY_COMPARATOR_POLICY_OPTIONAL_FIELDS
    ).intersection(statistical):
        # A primary-comparator profile must never silently receive the legacy
        # all-comparator interpretation. Existing unversioned profiles keep it.
        raise ValueError("publication_statistical_policy_version_unsupported")
    return dict(statistical)


def _validate_primary_comparator_policy(statistical: Mapping[str, Any]) -> None:
    """The accepted primary-comparator profile; no grant or budget is created here.

    The caller derives each executable identity from verified canonical source,
    formula, scope and fees before freezing the policy. A syntactically valid
    fingerprint alone is not evidence that those source checks were performed.
    """
    required = _PRIMARY_COMPARATOR_POLICY_FIELDS | {
        "schema_version",
        "method",
        "minimum_observations",
        "block_length",
        "minimum_effective_blocks",
        "bootstrap_samples",
        "significance_level",
        "minimum_net_excess",
        "decision_checkpoint",
    }
    if (
        not required <= statistical.keys()
        # Existing callers use checkpoint_interval_days to roll deadlines.
        # V2 freezes one checkpoint and cannot carry that renewal instruction.
        or statistical.keys() - (required | _PRIMARY_COMPARATOR_POLICY_OPTIONAL_FIELDS)
        or (
            "calendar_verification_timing" in statistical
            and not is_final_calendar_timing(
                statistical["calendar_verification_timing"]
            )
        )
        or not isinstance(statistical["research_policy_fingerprint"], str)
        or not statistical["research_policy_fingerprint"].startswith("sha256:")
        or any(
            statistical[key] != value
            for key, value in {
                "minimum_observations": 60,
                "block_length": 5,
                "minimum_effective_blocks": 12,
                "bootstrap_samples": 100000,
            }.items()
        )
        or publication_number(statistical["significance_level"]) > Decimal("0.05")
        or any(
            publication_number(statistical[key]) != value
            for key, value in {
                "minimum_net_excess": Decimal("0"),
                "minimum_candidate_net_return": Decimal("0"),
                "minimum_annualized_relative_wealth": Decimal("0.03"),
                "maximum_drawdown": Decimal("0.15"),
            }.items()
        )
    ):
        raise ValueError("publication_statistical_frozen_profile_mismatch")
    _fingerprint(statistical["research_policy_fingerprint"])
    bindings = statistical["comparator_bindings"]
    primary = statistical["primary_comparator"]
    if (
        not isinstance(bindings, Mapping)
        or not bindings
        or not isinstance(primary, str)
        or primary not in bindings
    ):
        raise ValueError("publication_statistical_comparator_binding_invalid")
    identities = set()
    for label, binding in bindings.items():
        if (
            not isinstance(label, str)
            or not label.strip()
            or label != label.strip()
            or not isinstance(binding, Mapping)
            or set(binding) != {"role", "identity_fingerprint"}
            or binding["role"] != ("primary" if label == primary else "diagnostic")
            or not isinstance(binding["identity_fingerprint"], str)
            or not binding["identity_fingerprint"].startswith("sha256:")
        ):
            raise ValueError("publication_statistical_comparator_binding_invalid")
        identity = _fingerprint(binding["identity_fingerprint"])
        if identity in identities:
            raise ValueError("publication_statistical_comparator_identity_duplicate")
        identities.add(identity)


def validate_publication_grant(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(value)
    if policy.get("schema_version") != PUBLICATION_POLICY_SCHEMA:
        raise ValueError("publication_policy_schema_invalid")
    if type(policy.get("enabled")) is not bool:
        raise ValueError("publication_policy_enabled_invalid")
    for field in ("grant_id", "generation"):
        UUID(str(policy.get(field) or ""))
    if policy["enabled"] is False:
        return policy
    if policy.get("authorization") != PUBLICATION_AUTHORIZE:
        raise ValueError("publication_policy_authorization_missing")
    for field in (
        "account_scope_fingerprint",
        "deployment_scope_fingerprint",
        "statistical_policy_fingerprint",
    ):
        _fingerprint(policy.get(field))
    if not str(policy.get("allocation_scope") or "").strip():
        raise ValueError("publication_allocation_scope_missing")
    if policy.get("strategy_family") != "formula":
        raise ValueError("publication_strategy_family_unsupported")
    if publication_number(policy.get("max_initial_cash")) <= 0:
        raise ValueError("publication_capital_bound_invalid")
    risk = policy.get("risk_limits")
    if not isinstance(risk, Mapping) or set(risk) != {
        "max_drawdown",
        "max_gross_weight",
        "max_symbol_weight",
        "max_positions",
    }:
        raise ValueError("publication_risk_limits_invalid")
    for field in ("max_drawdown", "max_gross_weight", "max_symbol_weight"):
        if not 0 < publication_number(risk[field]) <= 1:
            raise ValueError("publication_risk_limits_invalid")
    if type(risk["max_positions"]) is not int or risk["max_positions"] < 1:
        raise ValueError("publication_position_limit_invalid")
    for field in ("max_publications", "max_final_tests"):
        if type(policy.get(field)) is not int or policy[field] < 1:
            raise ValueError("publication_resource_bound_invalid")
    if not 0 < publication_number(policy.get("total_error_budget")) < 1:
        raise ValueError("publication_error_budget_invalid")
    if publication_number(policy.get("min_net_improvement")) < 0:
        raise ValueError("publication_replacement_margin_invalid")
    if type(policy.get("cooldown_days")) is not int or policy["cooldown_days"] < 0:
        raise ValueError("publication_cooldown_invalid")
    validate_final_statistical_policy(
        policy.get("statistical_policy"), policy["statistical_policy_fingerprint"]
    )
    publication_time(policy.get("expires_at"))
    if not str(policy.get("updated_by") or "").strip():
        raise ValueError("publication_owner_missing")
    if "entry_board_policy" in policy:
        validate_entry_board_policy(policy["entry_board_policy"])
    return policy


def read_publication_grant(
    db: Any, *, now: datetime | str | None = None, require_active: bool = True
) -> dict[str, Any]:
    reader = getattr(db, "get_automation_policy_sync", None)
    stored = reader(PUBLICATION_POLICY_ID) if callable(reader) else None
    if not isinstance(stored, Mapping):
        raise ValueError("publication_grant_missing")
    policy = validate_publication_grant(stored)
    if require_active:
        if not policy["enabled"]:
            raise ValueError("publication_grant_disabled")
        validate_entry_board_policy(policy.get("entry_board_policy"))
        clock = publication_time(now or datetime.now(timezone.utc))
        if clock >= publication_time(policy["expires_at"]):
            raise ValueError("publication_grant_expired")
    return policy


def legacy_automated_approval(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    actor = str(value.get("approved_by") or value.get("reviewer") or "").strip()
    return actor.startswith(("automation:", "policy:")) or str(
        value.get("notes") or ""
    ).startswith("automatically_switched_to_latest_optimal_strategy")


def _publication_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value) if isinstance(value, str) and value else {}
    except (ValueError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def publication_source_blocker(db: Any, state: Mapping[str, Any]) -> str | None:
    """Exclude the affected ungranted source without blocking unrelated sources."""
    payload = _publication_object(state.get("payload_json") or state.get("payload"))
    if payload.get("decision_source") == "policy":
        try:
            policy = read_publication_grant(db)
            decision = _publication_object(payload.get("publication_decision"))
            if (
                decision.get("grant_id") != policy["grant_id"]
                or decision.get("generation") != policy["generation"]
            ):
                return "publication_grant_generation_changed"
        except (ValueError, TypeError, KeyError):
            return "publication_grant_inactive_or_invalid"
    elif legacy_automated_approval(payload.get("human_review")):
        return "legacy_automated_publication_has_no_grant"
    return None


def publication_scope_incumbent(
    db: Any, grant: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Read the one source the owner grant may replace; never mutate lifecycle."""
    matching = []
    for row in db.list_strategy_promotion_states_sync():
        decision = _publication_object(
            _publication_object(row.get("payload_json") or row.get("payload")).get(
                "publication_decision"
            )
        )
        if (
            row.get("stage") == "paper_shadow"
            and decision.get("grant_id") == grant["grant_id"]
            and decision.get("generation") == grant["generation"]
            and decision.get("allocation_scope") == grant["allocation_scope"]
        ):
            matching.append(row)
    if len(matching) > 1:
        raise ValueError("publication_scope_incumbent_conflict")
    if matching:
        return dict(matching[0])
    identity = grant.get("incumbent_strategy_id")
    incumbent = db.get_strategy_promotion_state_sync(identity) if identity else None
    if identity and (not incumbent or incumbent.get("stage") != "paper_shadow"):
        raise ValueError("publication_named_incumbent_unavailable")
    return incumbent
