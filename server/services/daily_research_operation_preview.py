"""Read-only publication of a verified normalized research operation preview."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from server.contracts.content_identity import content_fingerprint
from server.persistence.database_identity import optional_database_path
from server.projections.normalized_research_operation_preview import (
    is_valid_research_operation_recommendation,
)
from server.projections.normalized_research_recommendation import (
    is_valid_normalized_research_recommendation,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.daily_decision_background_schedule import next_trading_day
from server.services.daily_decision_evidence_values import json_object_list
from server.services.market_calendar_evidence import validate_verified_market_calendar

DAILY_RESEARCH_OPERATION_PREVIEW_SCHEMA = (
    "karkinos.decision.research_operation_preview.v1"
)
_DAILY_OPERATION_FIELDS = {
    "symbol",
    "signal_date",
    "signal_type",
    "operation",
    "target_weight",
    "account_position_status",
    "next_session_only",
    "research_only",
    "executable",
}
_DAILY_PREVIEW_FIELDS = {
    "schema_version",
    "status",
    "market_date",
    "target_market_date",
    "market_calendar_evidence_refs",
    "run_id",
    "selection_id",
    "selection_fingerprint",
    "backup_artifact_fingerprint",
    "research_winner_candidate_id",
    "source_preview_fingerprint",
    "dataset_snapshot_id",
    "formula_fingerprint",
    "research_window_end_date",
    "signal_observed_at",
    "execution_timing",
    "allocation_slots",
    "canonical_target_weight",
    "operations",
    "blockers",
    "account_qualification_status",
    "account_positions_evaluated",
    "provider_contacted",
    "database_writes_performed",
    "read_only",
    "research_only",
    "executable",
    "authorizes_order_creation",
    "authorizes_execution",
    "authority_effect",
    "evidence_fingerprint",
}


def resolve_latest_verified_research_operation_preview(
    database: object | None,
    *,
    plan_date: str | None,
) -> dict[str, Any]:
    """Resolve the latest exact selection/backup pair without provider contact."""

    database_path = optional_database_path(database)
    if database_path is None:
        return unavailable_daily_research_operation_preview(
            "daily_research_artifact_store_unavailable"
        )
    artifacts = DailyStrategyArtifactStore(
        database_path,
        database_path.parent / "strategy-research-backups",
    )
    try:
        verified = artifacts.load_latest_verified_research_artifacts()
        target_market_date, calendar_evidence_refs = _next_verified_target_market_date(
            database,
            selection_market_date=str(verified["selection"].get("market_date") or ""),
        )
        return build_verified_daily_research_operation_preview(
            selection=verified["selection"],
            backup=verified["backup"],
            backup_payload=verified["payload"],
            target_market_date=target_market_date,
            plan_date=plan_date,
            market_calendar_evidence_refs=calendar_evidence_refs,
        )
    except Exception:
        return unavailable_daily_research_operation_preview(
            "verified_daily_research_operation_preview_unavailable"
        )


def build_verified_daily_research_operation_preview(
    *,
    selection: Mapping[str, Any],
    backup: Mapping[str, Any],
    backup_payload: Mapping[str, Any],
    target_market_date: str,
    plan_date: str | None,
    market_calendar_evidence_refs: list[str],
) -> dict[str, Any]:
    """Bind a valid winner preview to the verified daily artifact identities."""

    recommendation = selection.get("research_recommendation")
    operation_preview = (
        recommendation.get("research_operation_preview")
        if isinstance(recommendation, Mapping)
        else None
    )
    winner_candidate_id = (
        recommendation.get("research_winner_candidate_id")
        if isinstance(recommendation, Mapping)
        else None
    )
    ranked_candidates = (
        recommendation.get("ranked_candidates")
        if isinstance(recommendation, Mapping)
        else None
    )
    winner_rows = (
        [
            item
            for item in ranked_candidates
            if isinstance(item, Mapping)
            and item.get("candidate_id") == winner_candidate_id
        ]
        if isinstance(ranked_candidates, list)
        else []
    )
    winner_row = winner_rows[0] if len(winner_rows) == 1 else None
    backup_binding = _verified_backup_research_winner_binding(
        payload=backup_payload,
        selection=selection,
        candidate_id=str(winner_candidate_id or ""),
    )
    if (
        selection.get("integrity_status") != "verified"
        or backup.get("verification_status") != "verified"
        or backup.get("run_id") != selection.get("run_id")
        or backup.get("selection_id") != selection.get("selection_id")
        or not is_valid_normalized_research_recommendation(recommendation)
        or recommendation.get("status") != "best_available_for_further_research"
        or not is_valid_research_operation_recommendation(operation_preview)
        or operation_preview.get("research_winner_candidate_id") != winner_candidate_id
        or winner_row is None
        or backup_binding is None
        or operation_preview.get("formula_fingerprint")
        != winner_row.get("formula_fingerprint")
        or operation_preview.get("dataset_snapshot_id")
        != winner_row.get("dataset_snapshot_id")
        or operation_preview.get("formula_fingerprint")
        != backup_binding["strategy"].get("formula_fingerprint")
        or operation_preview.get("dataset_snapshot_id")
        != backup_binding["strategy"].get("dataset_snapshot_id")
        or winner_row.get("draft_id") != backup_binding["snapshot"].get("draft_id")
        or operation_preview.get("research_window_end_date")
        != selection.get("market_date")
        or not target_market_date
        or plan_date
        not in {str(selection.get("market_date") or ""), target_market_date}
        or not market_calendar_evidence_refs
    ):
        return unavailable_daily_research_operation_preview(
            (
                "research_operation_preview_outside_target_market_date"
                if target_market_date
                and plan_date
                not in {str(selection.get("market_date") or ""), target_market_date}
                else "verified_daily_research_operation_preview_invalid"
            ),
            target_market_date=target_market_date or None,
        )

    core = {
        "schema_version": DAILY_RESEARCH_OPERATION_PREVIEW_SCHEMA,
        "status": operation_preview["status"],
        "market_date": selection.get("market_date"),
        "target_market_date": target_market_date,
        "market_calendar_evidence_refs": list(market_calendar_evidence_refs),
        "run_id": selection.get("run_id"),
        "selection_id": selection.get("selection_id"),
        "selection_fingerprint": selection.get("selection_fingerprint"),
        "backup_artifact_fingerprint": backup.get("artifact_fingerprint"),
        "research_winner_candidate_id": recommendation.get(
            "research_winner_candidate_id"
        ),
        "source_preview_fingerprint": operation_preview.get(
            "source_preview_fingerprint"
        ),
        "dataset_snapshot_id": operation_preview.get("dataset_snapshot_id"),
        "formula_fingerprint": operation_preview.get("formula_fingerprint"),
        "research_window_end_date": operation_preview.get("research_window_end_date"),
        "signal_observed_at": operation_preview.get("signal_observed_at"),
        "execution_timing": operation_preview.get("execution_timing"),
        "allocation_slots": operation_preview.get("allocation_slots"),
        "canonical_target_weight": operation_preview.get("canonical_target_weight"),
        "operations": [dict(item) for item in operation_preview["operations"]],
        "blockers": list(operation_preview.get("blockers") or []),
        "account_qualification_status": "not_evaluated",
        "account_positions_evaluated": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "read_only": True,
        "research_only": True,
        "executable": False,
        "authorizes_order_creation": False,
        "authorizes_execution": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def unavailable_daily_research_operation_preview(
    reason: str,
    *,
    target_market_date: str | None = None,
) -> dict[str, Any]:
    """Return a stable fail-closed sibling that cannot affect the trading plan."""

    core = {
        "schema_version": DAILY_RESEARCH_OPERATION_PREVIEW_SCHEMA,
        "status": "unavailable",
        "market_date": None,
        "target_market_date": target_market_date,
        "market_calendar_evidence_refs": [],
        "run_id": None,
        "selection_id": None,
        "selection_fingerprint": None,
        "backup_artifact_fingerprint": None,
        "research_winner_candidate_id": None,
        "source_preview_fingerprint": None,
        "dataset_snapshot_id": None,
        "formula_fingerprint": None,
        "research_window_end_date": None,
        "signal_observed_at": None,
        "execution_timing": "next_verified_market_session",
        "allocation_slots": None,
        "canonical_target_weight": None,
        "operations": [],
        "blockers": [reason],
        "account_qualification_status": "not_evaluated",
        "account_positions_evaluated": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "read_only": True,
        "research_only": True,
        "executable": False,
        "authorizes_order_creation": False,
        "authorizes_execution": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def project_daily_research_operation_preview(value: Any) -> dict[str, Any] | None:
    """Validate the final read model before attaching it beside a trading plan."""

    if not isinstance(value, Mapping):
        return None
    if set(value) != _DAILY_PREVIEW_FIELDS:
        return None
    projected = {key: value.get(key) for key in _DAILY_PREVIEW_FIELDS}
    operations = value.get("operations")
    calendar_refs = value.get("market_calendar_evidence_refs")
    blockers = value.get("blockers")
    if not isinstance(operations, list) or not isinstance(calendar_refs, list):
        return None
    if not isinstance(blockers, list):
        return None
    projected["operations"] = [
        dict(item) for item in operations if isinstance(item, Mapping)
    ]
    projected["market_calendar_evidence_refs"] = list(calendar_refs)
    projected["blockers"] = list(blockers)
    if len(projected["operations"]) != len(operations):
        return None
    payload = dict(projected)
    fingerprint = payload.pop("evidence_fingerprint", None)
    operations = payload["operations"]
    status = payload.get("status")
    source_preview_fingerprint = payload.get("source_preview_fingerprint")
    if any(
        not isinstance(item, Mapping) or set(item) != _DAILY_OPERATION_FIELDS
        for item in operations
    ):
        return None
    calendar_refs = payload["market_calendar_evidence_refs"]
    if any(not isinstance(item, str) or not item for item in calendar_refs):
        return None
    if any(not isinstance(item, str) or not item for item in payload["blockers"]):
        return None
    if not (
        payload.get("schema_version") == DAILY_RESEARCH_OPERATION_PREVIEW_SCHEMA
        and status in {"available", "no_formula_condition", "unavailable"}
        and (status == "available") == bool(operations)
        and (status == "unavailable") == bool(payload["blockers"])
        and payload.get("execution_timing") == "next_verified_market_session"
        and _valid_daily_operations(
            operations,
            allocation_slots=payload.get("allocation_slots"),
            canonical_target_weight=payload.get("canonical_target_weight"),
            signal_date=payload.get("research_window_end_date"),
        )
        and payload.get("account_qualification_status") == "not_evaluated"
        and payload.get("account_positions_evaluated") is False
        and payload.get("provider_contacted") is False
        and payload.get("database_writes_performed") is False
        and payload.get("read_only") is True
        and payload.get("research_only") is True
        and payload.get("executable") is False
        and payload.get("authorizes_order_creation") is False
        and payload.get("authorizes_execution") is False
        and payload.get("authority_effect") == "none"
        and (
            (
                _valid_fingerprint(source_preview_fingerprint)
                and _valid_fingerprint(payload.get("dataset_snapshot_id"))
                and _valid_fingerprint(payload.get("formula_fingerprint"))
                and _valid_fingerprint(payload.get("selection_fingerprint"))
                and _valid_fingerprint(payload.get("backup_artifact_fingerprint"))
                and bool(payload.get("run_id"))
                and bool(payload.get("selection_id"))
                and bool(payload.get("research_winner_candidate_id"))
                and bool(payload.get("target_market_date"))
                and bool(calendar_refs)
                and payload.get("research_window_end_date")
                == payload.get("market_date")
            )
            or (
                status == "unavailable"
                and source_preview_fingerprint is None
                and payload.get("dataset_snapshot_id") is None
                and payload.get("formula_fingerprint") is None
                and payload.get("market_date") is None
                and payload.get("run_id") is None
                and payload.get("selection_id") is None
                and payload.get("selection_fingerprint") is None
                and payload.get("backup_artifact_fingerprint") is None
                and payload.get("research_winner_candidate_id") is None
                and payload.get("research_window_end_date") is None
                and payload.get("signal_observed_at") is None
                and not calendar_refs
            )
        )
        and isinstance(fingerprint, str)
        and fingerprint == content_fingerprint(payload)
    ):
        return None
    return projected


def _verified_backup_research_winner_binding(
    *,
    payload: Mapping[str, Any],
    selection: Mapping[str, Any],
    candidate_id: str,
) -> dict[str, Mapping[str, Any]] | None:
    expected_selection = dict(selection)
    expected_selection.pop("integrity_status", None)
    candidates = payload.get("candidates")
    if (
        not candidate_id
        or payload.get("run_id") != selection.get("run_id")
        or payload.get("market_date") != selection.get("market_date")
        or payload.get("selection") != expected_selection
        or not isinstance(candidates, list)
    ):
        return None
    matches = [
        item
        for item in candidates
        if isinstance(item, Mapping) and item.get("candidate_id") == candidate_id
    ]
    if len(matches) != 1:
        return None
    snapshot = matches[0]
    strategy = snapshot.get("strategy")
    if (
        not isinstance(strategy, Mapping)
        or snapshot.get("strategy_artifact_fingerprint")
        != content_fingerprint(strategy)
        or snapshot.get("draft_id") != strategy.get("draft_id")
        or not isinstance(strategy.get("formula_ast"), Mapping)
        or not _valid_fingerprint(strategy.get("formula_fingerprint"))
        or not _valid_fingerprint(strategy.get("dataset_snapshot_id"))
    ):
        return None
    return {"snapshot": snapshot, "strategy": strategy}


def _valid_daily_operations(
    operations: list[Any],
    *,
    allocation_slots: Any,
    canonical_target_weight: Any,
    signal_date: Any,
) -> bool:
    try:
        slots = int(allocation_slots)
        target_weight = float(canonical_target_weight)
    except (TypeError, ValueError):
        return (
            not operations
            and allocation_slots is None
            and canonical_target_weight is None
        )
    if slots < 1 or target_weight != 1.0 / slots or not str(signal_date or ""):
        return False
    buy_count = 0
    order_keys: list[tuple[int, str]] = []
    for item in operations:
        operation = item.get("operation")
        symbol = str(item.get("symbol") or "")
        try:
            item_weight = float(item.get("target_weight"))
        except (TypeError, ValueError):
            return False
        if operation == "buy_candidate":
            buy_count += 1
            semantic_valid = (
                item.get("signal_type") == "entry" and item_weight == target_weight
            )
            priority = 1
        elif operation == "exit_if_held_candidate":
            semantic_valid = item.get("signal_type") == "exit" and item_weight == 0.0
            priority = 0
        else:
            return False
        if (
            not symbol
            or not semantic_valid
            or item.get("signal_date") != signal_date
            or item.get("account_position_status") != "not_evaluated"
            or item.get("next_session_only") is not True
            or item.get("research_only") is not True
            or item.get("executable") is not False
        ):
            return False
        order_keys.append((priority, symbol))
    return buy_count <= slots and order_keys == sorted(order_keys)


def _valid_fingerprint(value: Any) -> bool:
    text = str(value or "").removeprefix("sha256:")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _next_verified_target_market_date(
    database: object,
    *,
    selection_market_date: str,
) -> tuple[str, list[str]]:
    """Resolve exactly one next SSE session from complete verified calendars."""

    try:
        selection_date = date.fromisoformat(selection_market_date)
    except ValueError as exc:
        raise ValueError("daily_research_selection_market_date_invalid") from exc
    calendar_reader = getattr(database, "get_market_calendar_snapshot_sync", None)
    if not callable(calendar_reader):
        raise ValueError("verified_market_calendar_reader_unavailable")
    calendar = calendar_reader(exchange="SSE", year=selection_date.year)
    validation = validate_verified_market_calendar(calendar)
    if not validation.verified or not validation.evidence_ref:
        raise ValueError("daily_research_selection_calendar_not_verified")
    days = json_object_list(calendar.get("days_json"))
    selection_day = next(
        (item for item in days if str(item.get("date") or "") == selection_market_date),
        None,
    )
    if not isinstance(selection_day, Mapping) or (
        selection_day.get("is_trading_day") is not True
    ):
        raise ValueError("daily_research_selection_date_not_verified_trading_day")
    target = next_trading_day(
        days=days,
        run_date=selection_market_date,
        include_current_date=False,
    )
    evidence_refs = [validation.evidence_ref]
    if target is None:
        next_calendar = calendar_reader(exchange="SSE", year=selection_date.year + 1)
        next_validation = validate_verified_market_calendar(next_calendar)
        if not next_validation.verified or not next_validation.evidence_ref:
            raise ValueError("next_market_calendar_not_verified")
        target = next_trading_day(
            days=json_object_list(next_calendar.get("days_json")),
            run_date=selection_market_date,
            include_current_date=False,
        )
        evidence_refs.append(next_validation.evidence_ref)
    if target is None:
        raise ValueError("next_verified_market_date_unavailable")
    return target, evidence_refs


__all__ = [
    "DAILY_RESEARCH_OPERATION_PREVIEW_SCHEMA",
    "build_verified_daily_research_operation_preview",
    "project_daily_research_operation_preview",
    "resolve_latest_verified_research_operation_preview",
    "unavailable_daily_research_operation_preview",
]
