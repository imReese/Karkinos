"""Top-level daily and intraday Decision response projection."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from server.services.decision_candidate_market_evidence import (
    bind_candidate_market_evidence,
    candidate_market_evidence,
)
from server.services.decision_contracts import (
    DecisionProjectionPorts,
    has_ready_manual_confirmation,
    is_intraday_action,
    overall_decision,
    parse_action_timestamp,
)
from server.services.decision_portfolio_projection import (
    action_filter_date,
    response_decision_date,
)


def daily_candidate_generation_status(db: Any, decision_date: str) -> dict[str, Any]:
    """Separate today's persisted generation outcome from an empty task queue."""

    from server.projections.account_action_recommendation import (
        resolve_latest_verified_promoted_strategy_scan,
    )
    from server.services.daily_decision_background_schedule import (
        project_daily_candidate_background_schedule,
    )
    from server.services.daily_decision_evidence_identity import (
        daily_candidate_input_fingerprint,
        daily_candidate_record_fingerprint,
    )

    base: dict[str, Any] = {
        "run_date": decision_date,
        "status": "unavailable",
        "generation_verified": False,
        "recommendation_authoritative": False,
        "attempt_run_id": None,
        "daily_evidence_run_id": None,
        "scan_run_id": None,
        "bound_scan_action_ids": [],
        "formal_candidate_action_ids": [],
        "failure_stage": None,
        "failure_code": None,
    }
    reader = getattr(db, "list_automation_runs_sync", None)
    if not decision_date or not callable(reader):
        return base
    attempts = reader(
        run_type="daily_candidate_background_attempt",
        run_date=decision_date,
        limit=1,
        offset=0,
    )
    if not attempts:
        unlinked_evidence = reader(
            run_type="daily_decision_evidence",
            run_date=decision_date,
            limit=1,
            offset=0,
        )
        if unlinked_evidence:
            return {
                **base,
                "status": "unlinked_daily_evidence",
                "daily_evidence_run_id": unlinked_evidence[0].get("run_id"),
                "failure_code": "background_attempt_missing",
            }
        schedule = project_daily_candidate_background_schedule(db=db)
        return {
            **base,
            "status": (
                "missed_window"
                if schedule.get("run_date") == decision_date
                and schedule.get("status") == "missed_decision_window"
                else "not_generated"
            ),
        }
    attempt = dict(attempts[0])
    attempt_payload = _automation_payload(attempt)
    base.update(
        attempt_run_id=attempt.get("run_id"),
        daily_evidence_run_id=attempt_payload.get("result_run_id"),
        failure_stage=attempt_payload.get("failure_stage"),
        failure_code=attempt_payload.get("failure_code"),
    )
    attempt_status = str(attempt.get("status") or "")
    if attempt_status in {"failed_closed", "interrupted_fail_closed"}:
        return {**base, "status": "failed_closed"}
    if attempt_status == "claimed":
        schedule = project_daily_candidate_background_schedule(db=db)
        return {
            **base,
            "status": (
                "claim_unresolved"
                if schedule.get("status") == "claim_unresolved_after_window"
                else "running"
            ),
        }
    if attempt_status != "completed":
        return base
    evidence_run_id = str(attempt_payload.get("result_run_id") or "")
    if not evidence_run_id or attempt.get("source_ref") != evidence_run_id:
        return {**base, "failure_code": "daily_evidence_link_invalid"}
    evidence_reader = getattr(db, "get_automation_run_sync", None)
    evidence = evidence_reader(evidence_run_id) if callable(evidence_reader) else None
    if (
        not isinstance(evidence, dict)
        or evidence.get("run_type") != "daily_decision_evidence"
        or evidence.get("run_date") != decision_date
    ):
        return {**base, "failure_code": "daily_evidence_missing"}
    evidence_payload = _automation_payload(evidence)
    if (
        evidence_payload.get("schema_version")
        != "karkinos.daily_decision_evidence_automation.v3"
        or evidence_payload.get("input_fingerprint")
        != daily_candidate_input_fingerprint(evidence_payload)
        or evidence_payload.get("production_record_fingerprint")
        != daily_candidate_record_fingerprint(evidence_payload)
    ):
        return {**base, "failure_code": "daily_evidence_fingerprint_invalid"}
    if evidence_payload.get("decision_outcome") != attempt_payload.get(
        "decision_outcome"
    ):
        return {**base, "failure_code": "daily_evidence_outcome_mismatch"}
    production_gate = evidence_payload.get("production_gate")
    production_gate = production_gate if isinstance(production_gate, dict) else {}
    production_blockers = [
        str(item) for item in production_gate.get("blockers") or [] if str(item)
    ]
    snapshot = evidence_payload.get("input_snapshot")
    bound_scan_run_id = (
        str(snapshot.get("promoted_strategy_scan_run_id") or "")
        if isinstance(snapshot, dict)
        else ""
    )
    if (
        not bound_scan_run_id
        and not attempt_payload.get("promoted_strategy_scan_run_id")
        and production_gate.get("status") == "blocked"
    ):
        return {
            **base,
            "status": "blocked",
            "failure_code": production_blockers[0]
            if production_blockers
            else "production_gate_blocked",
        }
    if (
        not bound_scan_run_id
        or attempt_payload.get("promoted_strategy_scan_run_id") != bound_scan_run_id
    ):
        return {**base, "failure_code": "promoted_scan_link_missing_or_conflicting"}
    scan = resolve_latest_verified_promoted_strategy_scan(
        db,
        decision_date=decision_date,
        expected_run_id=bound_scan_run_id,
    )
    base["scan_run_id"] = scan.get("run_id")
    if scan.get("run_id") != bound_scan_run_id:
        return {**base, "failure_code": "promoted_scan_link_mismatch"}
    scan_action_ids = scan.get("action_task_ids")
    parsed_scan_action_ids = (
        [_action_task_id(item) for item in scan_action_ids]
        if isinstance(scan_action_ids, list)
        else []
    )
    if any(item is None for item in parsed_scan_action_ids):
        return {**base, "failure_code": "promoted_scan_action_id_invalid"}
    base["bound_scan_action_ids"] = sorted(set(parsed_scan_action_ids))
    if scan.get("status") == "completed_no_signal" and (
        scan.get("normal_no_signal") is True
        and evidence.get("status") == "no_candidates"
        and evidence_payload.get("decision_outcome") == "no_action"
        and production_gate.get("status") == "pass"
        and not production_blockers
        and evidence_payload.get("candidate_count") == 0
        and evidence_payload.get("manual_ticket_candidate_count") == 0
        and not evidence_payload.get("manual_order_ticket_candidates")
    ):
        return {**base, "status": "completed_no_signal", "generation_verified": True}
    if scan.get("status") == "completed_no_signal" and scan.get("account_blocked_buys"):
        return {
            **base,
            "status": "blocked",
            "failure_code": "account_buy_candidates_ineligible",
        }
    if production_gate.get("status") != "pass" or production_blockers:
        return {
            **base,
            "status": "blocked",
            "failure_code": production_blockers[0]
            if production_blockers
            else "production_gate_blocked",
        }
    tickets = evidence_payload.get("manual_order_ticket_candidates")
    ticket_ids = (
        [_action_task_id(item.get("action_id")) for item in tickets]
        if isinstance(tickets, list) and all(isinstance(item, dict) for item in tickets)
        else []
    )
    if any(item is None for item in ticket_ids):
        return {
            **base,
            "status": "blocked",
            "failure_code": "manual_ticket_action_id_invalid",
        }
    formal_action_ids = sorted(set(ticket_ids) & set(base["bound_scan_action_ids"]))
    if scan.get("status") == "completed" and (
        evidence_payload.get("decision_outcome") == "manual_order_ticket_candidate"
        and evidence.get("status") == "paper_shadow_completed"
        and isinstance(tickets, list)
        and len(ticket_ids) == len(tickets)
        and len(tickets) == evidence_payload.get("manual_ticket_candidate_count")
        and len(tickets) > 0
        and int(scan.get("selected_signal_count") or 0) > 0
        and formal_action_ids
    ):
        return {
            **base,
            "status": "completed_with_candidates",
            "generation_verified": True,
            "recommendation_authoritative": True,
            "formal_candidate_action_ids": formal_action_ids,
        }
    return {**base, "status": "blocked"}


def _automation_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _action_task_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def suppress_unverified_daily_scan_candidates(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Hide only same-day promoted-scan tasks lacking a completed run chain."""

    from server.services.decision_workflow_projection import workflow_tasks

    generation = payload.get("generation")
    if payload.get("lane") != "daily":
        return payload
    if not isinstance(generation, dict):
        generation = {
            "status": "unavailable",
            "recommendation_authoritative": False,
            "formal_candidate_action_ids": [],
        }
    formal_action_ids = set(generation.get("formal_candidate_action_ids") or [])
    decision_date = str(payload.get("decision_date") or "")
    candidates = [
        dict(item) for item in payload.get("candidates") or [] if isinstance(item, dict)
    ]
    retained: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for candidate in candidates:
        evidence = candidate.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        signal = evidence.get("signal")
        signal = signal if isinstance(signal, dict) else {}
        strategy = evidence.get("strategy")
        strategy = strategy if isinstance(strategy, dict) else {}
        strategy_id = str(signal.get("strategy_id") or "")
        timestamp = parse_action_timestamp(signal.get("timestamp"))
        scan_origin = (
            strategy_id.startswith("ai_formula_shadow:")
            and strategy.get("strategy_id") == strategy_id
            and timestamp is not None
            and timestamp.date().isoformat() == decision_date
            and signal.get("id") is not None
            and candidate.get("action_id") is not None
        )
        if scan_origin and (
            generation.get("recommendation_authoritative") is not True
            or _action_task_id(candidate["action_id"]) not in formal_action_ids
        ):
            suppressed.append(
                {
                    "action_id": candidate["action_id"],
                    "source_signal_id": signal["id"],
                    "symbol": candidate.get("symbol"),
                    "strategy_id": strategy_id,
                    "reason": (
                        "daily_generation_not_verified"
                        if generation.get("recommendation_authoritative") is not True
                        else "action_not_in_bound_scan"
                    ),
                }
            )
        else:
            retained.append(candidate)
    if not suppressed:
        return payload

    summary = dict(payload.get("summary") or {})
    risk_blocked_count = sum(
        item.get("risk_gate_status") == "blocked" for item in retained
    )
    ready_count = sum(
        item.get("manual_confirmation_status") == "ready_for_manual_confirmation"
        for item in retained
    )
    action_tasks = {
        "total_count": len(retained),
        "pending_count": sum(
            item.get("action_task_status") == "pending" for item in retained
        ),
        "deferred_count": sum(
            item.get("action_task_status") == "deferred" for item in retained
        ),
        "symbols": [str(item.get("symbol")) for item in retained if item.get("symbol")],
    }
    audit = dict(summary.get("audit") or {})
    audit.update(
        signal_count=len(
            {
                (item.get("evidence") or {}).get("signal", {}).get("id")
                for item in retained
                if (item.get("evidence") or {}).get("signal", {}).get("id") is not None
            }
        ),
        risk_checked_count=sum(
            item.get("risk_gate_status") in {"passed", "blocked"} for item in retained
        ),
        risk_blocked_count=risk_blocked_count,
    )
    summary.update(
        candidate_count=len(retained),
        risk_blocked_count=risk_blocked_count,
        ready_for_manual_confirmation_count=ready_count,
        action_tasks=action_tasks,
        audit=audit,
        workflow_tasks=workflow_tasks(
            market_data=dict(summary.get("market_data") or {}),
            account_truth=dict(summary.get("account_truth") or {}),
            strategy_attribution=dict(summary.get("strategy_attribution") or {}),
            action_tasks=action_tasks,
            audit=audit,
            candidate_count=len(retained),
            ready_for_manual_confirmation_count=ready_count,
        ),
    )
    return {
        **payload,
        "generation": generation,
        "decision": overall_decision(retained),
        "requires_manual_confirmation": has_ready_manual_confirmation(retained),
        "summary": summary,
        "candidates": retained,
        "suppressed_unverified_candidates": suppressed,
        "no_action_reasons": (
            payload.get("no_action_reasons")
            if retained
            else [f"daily_generation_{generation.get('status') or 'unavailable'}"]
        ),
    }


def _prepare_decision_projection(
    state: Any,
    ports: DecisionProjectionPorts,
    portfolio_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Read the first canonical persisted-fact stage in one worker thread."""

    db = state.db
    resolved_portfolio_context = portfolio_context or ports.portfolio_context(state)
    raw_actions = ports.read_action_tasks(
        db,
        decision_date=action_filter_date(resolved_portfolio_context),
    )
    if resolved_portfolio_context.get("authority") == "persisted_valuation_snapshot":
        resolved_portfolio_context = bind_candidate_market_evidence(
            resolved_portfolio_context,
            candidate_market_evidence(db, raw_actions, state=state),
        )
    actions = ports.allocate_actions(
        state,
        resolved_portfolio_context,
        raw_actions,
    )
    return {
        "db": db,
        "portfolio_context": resolved_portfolio_context,
        "actions": actions,
        "decision_date": response_decision_date(
            resolved_portfolio_context,
            actions,
        ),
        "journal_by_signal": ports.journal_by_signal_id(db),
    }


def _decision_evidence(
    state: Any,
    ports: DecisionProjectionPorts,
    prepared: dict[str, Any],
    validation_by_strategy: dict[str, dict[str, Any]],
    candidate_actions: list[dict[str, Any]],
    *,
    attribution_actions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Compose evidence-bound candidates in one worker-thread stage."""

    db = prepared["db"]
    portfolio_context = prepared["portfolio_context"]
    journal_by_signal = prepared["journal_by_signal"]
    account_truth = ports.account_truth_evidence(state)
    strategy_attribution = ports.strategy_attribution_evidence(
        state,
        db,
        candidate_actions if attribution_actions is None else attribution_actions,
    )
    candidate_quotes = dict(
        portfolio_context.get("candidate_quotes")
        if portfolio_context.get("authority") == "persisted_valuation_snapshot"
        else portfolio_context.get("quotes") or {}
    )
    strategy_order_gate_cache: dict[tuple[str, str | None], dict[str, Any]] = {}
    candidates = [
        ports.decision_candidate(
            action,
            journal_by_signal,
            validation_by_strategy,
            db,
            account_truth,
            strategy_attribution,
            state=state,
            quotes=candidate_quotes,
            allow_direct_quote_fallback=(
                portfolio_context.get("authority") != "persisted_valuation_snapshot"
            ),
            strategy_order_gate_cache=strategy_order_gate_cache,
        )
        for action in candidate_actions
    ]
    return account_truth, strategy_attribution, candidates


def _finish_intraday_decision_projection(
    state: Any,
    ports: DecisionProjectionPorts,
    prepared: dict[str, Any],
    validation_by_strategy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    actions = prepared["actions"]
    intraday_actions = [action for action in actions if is_intraday_action(action)]
    daily_actions = [action for action in actions if not is_intraday_action(action)]
    account_truth, strategy_attribution, candidates = _decision_evidence(
        state,
        ports,
        prepared,
        validation_by_strategy,
        intraday_actions,
        attribution_actions=actions,
    )
    no_action_reasons = [] if candidates else ["no_intraday_stock_or_etf_action_tasks"]
    return {
        "lane": "intraday",
        "decision_date": prepared["decision_date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cadence": "polling_or_minute_level",
        "decision": overall_decision(candidates),
        "requires_manual_confirmation": has_ready_manual_confirmation(candidates),
        "summary": {
            **ports.decision_summary(
                state,
                actions=actions,
                candidates=candidates,
                journal_by_signal=prepared["journal_by_signal"],
                account_truth=account_truth,
                strategy_attribution=strategy_attribution,
                portfolio_context=prepared["portfolio_context"],
            ),
            "excluded_daily_count": len(daily_actions),
        },
        "candidates": candidates,
        "excluded_daily_symbols": [
            str(action.get("symbol")) for action in daily_actions
        ],
        "no_action_reasons": no_action_reasons,
        "limitations": [
            "Intraday decisions are polling/minute-level platform candidates, not high-frequency trading instructions.",
            "Decision platform output is research and portfolio evidence, not investment advice.",
            "Live-like execution remains manual-confirmation only by default.",
        ],
    }


def _finish_today_decision_projection(
    state: Any,
    ports: DecisionProjectionPorts,
    prepared: dict[str, Any],
    validation_by_strategy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    actions = prepared["actions"]
    account_truth, strategy_attribution, candidates = _decision_evidence(
        state,
        ports,
        prepared,
        validation_by_strategy,
        actions,
    )
    for action, candidate in zip(actions, candidates, strict=True):
        candidate["action_task_status"] = str(action.get("status") or "unknown")
    no_action_reasons = [] if candidates else ["no_pending_action_tasks"]
    generation = (
        daily_candidate_generation_status(prepared["db"], prepared["decision_date"])
        if prepared["portfolio_context"].get("authority")
        == "persisted_valuation_snapshot"
        else None
    )
    return {
        "lane": "daily",
        "decision_date": prepared["decision_date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": overall_decision(candidates),
        "requires_manual_confirmation": has_ready_manual_confirmation(candidates),
        "summary": ports.decision_summary(
            state,
            actions=actions,
            candidates=candidates,
            journal_by_signal=prepared["journal_by_signal"],
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            portfolio_context=prepared["portfolio_context"],
        ),
        "candidates": candidates,
        "generation": generation,
        "no_action_reasons": no_action_reasons,
        "limitations": [
            "Decision platform output is research and portfolio evidence, not investment advice.",
            "Live-like execution remains manual-confirmation only by default.",
        ],
    }


async def build_intraday_decision_payload(
    state: Any,
    *,
    ports: DecisionProjectionPorts,
) -> dict[str, Any]:
    """Build the canonical intraday Decision projection."""

    prepared = await asyncio.to_thread(
        _prepare_decision_projection,
        state,
        ports,
        None,
    )
    validation_by_strategy = await ports.validation_by_strategy_id(prepared["db"])
    return await asyncio.to_thread(
        _finish_intraday_decision_projection,
        state,
        ports,
        prepared,
        validation_by_strategy,
    )


async def build_today_decision_payload(
    state: Any,
    *,
    ports: DecisionProjectionPorts,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prepared = await asyncio.to_thread(
        _prepare_decision_projection,
        state,
        ports,
        portfolio_context,
    )
    validation_by_strategy = await ports.validation_by_strategy_id(prepared["db"])
    return await asyncio.to_thread(
        _finish_today_decision_projection,
        state,
        ports,
        prepared,
        validation_by_strategy,
    )
