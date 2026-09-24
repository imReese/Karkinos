"""Read-only, per-trading-day history of the persisted decision chain."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from server.contracts.content_identity import content_fingerprint
from server.persistence.database_identity import optional_database_path
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.daily_decision_background_schedule import next_trading_day
from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
)
from server.services.daily_decision_evidence_identity import (
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
)
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.promoted_strategy_universe_scan import (
    PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RUN_TYPES = (
    DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
)


def list_daily_decision_reports(
    db: Any,
    *,
    limit: int = 20,
    offset: int = 0,
    as_of: date | None = None,
) -> dict[str, Any]:
    """List verified market sessions, including days without a run."""

    if not 1 <= limit <= 60 or not 0 <= offset <= 500:
        raise ValueError("daily report pagination is outside the supported range")
    today = as_of or datetime.now(_SHANGHAI).date()
    dates: list[str] = []
    calendar_refs: dict[str, str] = {}
    blockers: list[str] = []
    for year in range(today.year, max(today.year - 5, 0), -1):
        days, evidence_ref, errors = _verified_calendar(db, year)
        if errors:
            blockers.extend(errors)
            break
        if evidence_ref is not None:
            calendar_refs[str(year)] = evidence_ref
        dates.extend(
            str(item["date"])
            for item in reversed(days)
            if item.get("is_trading_day") is True
            and str(item.get("date") or "") <= today.isoformat()
        )
        if len(dates) > offset + limit:
            break
    selected = dates[offset : offset + limit]
    research = _research_by_date(db, set(selected))
    reports = [
        _daily_report(
            db,
            report_date=run_date,
            calendar_ref=calendar_refs[run_date[:4]],
            research_previews=research.get(run_date, []),
            include_receipts=False,
        )
        for run_date in selected
    ]
    return {
        "schema_version": "karkinos.decision.daily_report_index.v1",
        "status": "complete"
        if not blockers
        else "unavailable"
        if not reports
        else "partial",
        "as_of_date": today.isoformat(),
        "reports": reports,
        "limit": limit,
        "offset": offset,
        "has_more": len(dates) > offset + limit,
        "calendar_evidence_refs": list(calendar_refs.values()),
        "blockers": list(dict.fromkeys(blockers)),
        "read_only": True,
        "authorizes_execution": False,
    }


def get_daily_decision_report(db: Any, report_date: str) -> dict[str, Any]:
    """Read one date from its exact persisted runs, never from current /today."""

    try:
        parsed = date.fromisoformat(report_date)
    except ValueError as exc:
        raise ValueError("daily report date must be ISO format") from exc
    if parsed.isoformat() != report_date:
        raise ValueError("daily report date must be ISO format")
    if parsed > datetime.now(_SHANGHAI).date():
        raise ValueError("future daily report is unavailable")
    days, evidence_ref, blockers = _verified_calendar(db, parsed.year)
    if blockers:
        raise LookupError(
            "verified market calendar unavailable: " + ", ".join(blockers)
        )
    if not any(
        item.get("date") == report_date and item.get("is_trading_day") is True
        for item in days
    ):
        raise ValueError("date is not a verified trading day")
    research = _research_by_date(db, {report_date})
    return _daily_report(
        db,
        report_date=report_date,
        calendar_ref=str(evidence_ref),
        research_previews=research.get(report_date, []),
        include_receipts=True,
    )


def _verified_calendar(
    db: Any, year: int
) -> tuple[list[dict[str, Any]], str | None, list[str]]:
    reader = getattr(db, "get_market_calendar_snapshot_sync", None)
    row = reader(exchange="SSE", year=year) if callable(reader) else None
    validation = validate_verified_market_calendar(row)
    if not validation.verified:
        return [], None, [f"{year}:{item}" for item in validation.blockers]
    raw_days = row.get("days", row.get("days_json"))
    days = raw_days if isinstance(raw_days, list) else json.loads(str(raw_days))
    return (
        [item for item in days if isinstance(item, dict)],
        validation.evidence_ref,
        [],
    )


def _daily_report(
    db: Any,
    *,
    report_date: str,
    calendar_ref: str,
    research_previews: list[dict[str, Any]],
    include_receipts: bool,
) -> dict[str, Any]:
    reader = getattr(db, "list_automation_runs_sync", None)
    if not callable(reader):
        raise LookupError("automation run reader unavailable")
    rows = {
        run_type: sorted(
            reader(run_type=run_type, run_date=report_date, limit=-1, offset=0),
            key=lambda item: (
                str(item.get("started_at") or ""),
                str(item.get("created_at") or ""),
                str(item.get("run_id") or ""),
            ),
        )
        for run_type in _RUN_TYPES
    }
    preparations = [
        _preparation_summary(row)
        for row in rows[DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE]
    ]
    attempts = [
        _attempt_summary(row)
        for row in rows[DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE]
    ]
    evidence = [
        _evidence_summary(row)
        for row in rows[DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE]
    ]
    scans = [
        _scan_summary(row, include_receipts=include_receipts)
        for row in rows[PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE]
    ]
    completed_attempts = [item for item in attempts if item["status"] == "completed"]
    linked_evidence = [
        item
        for item in evidence
        if item["integrity_valid"]
        and any(
            attempt.get("source_ref") == item["run_id"]
            and attempt.get("result_run_id") == item["run_id"]
            and attempt.get("result_plan_date") in {None, report_date}
            and attempt.get("decision_outcome") == item["decision_outcome"]
            and attempt.get("scan_run_id") in {None, item["scan_run_id"]}
            for attempt in completed_attempts
        )
    ]
    ticket_bindings = {
        (action_id, str(run["scan_run_id"]))
        for run in linked_evidence
        if run["status"] == "paper_shadow_completed"
        if run["decision_outcome"] == "manual_order_ticket_candidate"
        and run["production_gate_status"] == "pass"
        and run["scan_run_id"]
        for action_id in run["ticket_action_ids"]
    }
    candidates = [
        {
            **candidate,
            "report_authoritative": any(
                candidate["action_id"] == action_id
                and scan_run_id == candidate["scan_run_id"]
                for action_id, scan_run_id in ticket_bindings
            ),
        }
        for scan in scans
        if scan["integrity_valid"] and scan["status"] == "completed"
        for candidate in scan["candidates"]
    ]
    blocked_signals = [item for scan in scans for item in scan["blocked_signals"]]
    authoritative_candidate_count = sum(
        item["report_authoritative"] for item in candidates
    )
    completed_scans = [
        scan
        for scan in scans
        if scan["integrity_valid"]
        and scan["status"] in {"completed", "completed_no_signal"}
    ]
    verified_no_signal = any(
        run["status"] == "no_candidates"
        and run["decision_outcome"] == "no_action"
        and run["production_gate_status"] == "pass"
        and bool(run["scan_run_id"])
        and any(
            scan["status"] == "completed_no_signal"
            and scan["normal_no_signal"] is True
            and scan["raw_signal_count"] == 0
            and scan["selected_signal_count"] == 0
            and scan["action_count"] == 0
            and not scan["account_blocked_buys"]
            and scan["run_id"] == run["scan_run_id"]
            for scan in completed_scans
        )
        for run in linked_evidence
    )
    failed = any(
        item["status"] in {"failed_closed", "interrupted_fail_closed"}
        for item in attempts
    )
    if failed:
        status = "failed"
    elif authoritative_candidate_count:
        status = "formal_candidate"
    elif completed_attempts and linked_evidence:
        status = "completed_no_signal" if verified_no_signal else "blocked"
    elif attempts or evidence:
        status = "blocked"
    else:
        status = "missing_run"
    reasons = [
        reason
        for item in [*preparations, *attempts, *evidence, *scans]
        for reason in item.get("reason_codes", [])
    ]
    reasons.extend(
        str(reason)
        for item in research_previews
        for reason in item.get("reason_codes", [])
    )
    if not attempts and scans:
        reasons.append("promoted_scan_without_daily_attempt")
    if completed_attempts and not linked_evidence:
        reasons.append("completed_attempt_final_evidence_unbound")
    if candidates and not authoritative_candidate_count:
        reasons.append("formal_signals_without_authoritative_daily_ticket")
    if any(
        item["integrity_valid"]
        and item["status"] in {"paper_shadow_completed", "no_candidates"}
        and not item["scan_run_id"]
        for item in linked_evidence
    ):
        reasons.append("final_scan_linkage_missing")
    if any(
        attempt.get("scan_run_id")
        and attempt.get("result_run_id") == item["run_id"]
        and attempt["scan_run_id"] != item["scan_run_id"]
        for attempt in completed_attempts
        for item in evidence
    ):
        reasons.append("daily_attempt_scan_link_conflicting")
    reasons.extend(
        f"account_buy_blocked:{item['symbol']}:{item['reason']}"
        for scan in scans
        for item in scan["account_blocked_buys"]
    )
    return {
        "schema_version": "karkinos.decision.daily_report.v1",
        "report_date": report_date,
        "status": status,
        "calendar_evidence_ref": calendar_ref,
        "preparations": preparations,
        "attempts": attempts,
        "daily_evidence_runs": evidence,
        "scans": [
            {
                key: value
                for key, value in scan.items()
                if key not in {"candidates", "blocked_signals"}
            }
            for scan in scans
        ],
        "candidates": candidates,
        "blocked_signals": blocked_signals,
        "blocked_signal_count": len(blocked_signals),
        "research_previews": research_previews,
        "research_history_status": (
            "unavailable"
            if any(item.get("status") == "unavailable" for item in research_previews)
            else "complete"
        ),
        "authoritative_candidate_count": authoritative_candidate_count,
        "reason_codes": list(dict.fromkeys(reasons)),
        "read_only": True,
        "authorizes_execution": False,
    }


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _run_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(row.get("run_id") or ""),
        "status": str(row.get("status") or ""),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "source_ref": row.get("source_ref"),
    }


def _preparation_summary(row: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(row)
    preparation = payload.get("preparation")
    preparation = preparation if isinstance(preparation, dict) else {}
    return {
        **_run_identity(row),
        "reason_codes": [str(item) for item in preparation.get("blockers") or []],
        "error_type": payload.get("error_type"),
    }


def _attempt_summary(row: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(row)
    failure_code = payload.get("failure_code") or payload.get("error_type")
    return {
        **_run_identity(row),
        "decision_outcome": payload.get("decision_outcome"),
        "result_run_id": payload.get("result_run_id"),
        "result_plan_date": payload.get("result_plan_date"),
        "scan_run_id": payload.get("promoted_strategy_scan_run_id"),
        "failure_stage": payload.get("failure_stage"),
        "failure_code": failure_code,
        "error_type": payload.get("error_type"),
        "evidence_refs": [str(item) for item in payload.get("evidence_refs") or []],
        "attempt_count": payload.get("attempt_count"),
        "reason_codes": [
            *([str(failure_code)] if failure_code else []),
            *[str(item) for item in payload.get("no_action_reasons") or []],
        ],
    }


def _evidence_summary(row: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(row)
    gate = payload.get("production_gate")
    gate = gate if isinstance(gate, dict) else {}
    expected = payload.get("production_record_fingerprint")
    integrity_valid = (
        bool(expected)
        and expected == daily_candidate_record_fingerprint(payload)
        and payload.get("input_fingerprint")
        == daily_candidate_input_fingerprint(payload)
    )
    tickets = payload.get("manual_order_ticket_candidates")
    tickets = tickets if isinstance(tickets, list) else []
    input_snapshot = payload.get("input_snapshot")
    input_snapshot = input_snapshot if isinstance(input_snapshot, dict) else {}
    if input_snapshot.get("plan_date") not in {None, row.get("run_date")}:
        integrity_valid = False
    scan_run_id = input_snapshot.get("promoted_strategy_scan_run_id")
    top_level_scan_run_id = payload.get("promoted_strategy_scan_run_id")
    if top_level_scan_run_id and top_level_scan_run_id != scan_run_id:
        integrity_valid = False
    return {
        **_run_identity(row),
        "integrity_valid": integrity_valid,
        "input_fingerprint": payload.get("input_fingerprint"),
        "production_record_fingerprint": expected,
        "scan_run_id": scan_run_id,
        "decision_outcome": payload.get("decision_outcome"),
        "production_gate_status": gate.get("status"),
        "candidate_count": payload.get("candidate_count"),
        "ticket_action_ids": [
            int(item["action_id"])
            for item in tickets
            if isinstance(item, dict) and str(item.get("action_id") or "").isdigit()
        ],
        "reason_codes": [
            *([] if integrity_valid else ["daily_evidence_fingerprint_invalid"]),
            *[str(item) for item in gate.get("blockers") or []],
            *[str(item) for item in payload.get("no_action_reasons") or []],
        ],
    }


def _scan_summary(row: dict[str, Any], *, include_receipts: bool) -> dict[str, Any]:
    payload = _payload(row)
    expected = payload.get("output_fingerprint")
    core = {key: value for key, value in payload.items() if key != "output_fingerprint"}
    integrity_valid = (
        expected == "sha256:" + content_fingerprint(core)
        and payload.get("status") == row.get("status")
        and payload.get("decision_date") in {None, row.get("run_date")}
    )
    actions = payload.get("action_tasks")
    actions = actions if isinstance(actions, list) else []
    selected = payload.get("selected_signals")
    selected = selected if isinstance(selected, list) else []
    raw_signals = payload.get("raw_signals")
    raw_signals = raw_signals if isinstance(raw_signals, list) else []
    account_blocked_buys = [
        {
            "symbol": str(item.get("symbol") or ""),
            "strategy_id": str(item.get("strategy_id") or ""),
            "board": str(item.get("board") or ""),
            "reason": str(item.get("reason") or ""),
        }
        for item in payload.get("account_blocked_buys") or []
        if isinstance(item, dict)
    ]
    blocked_signals: list[dict[str, Any]] = []
    for blocked in account_blocked_buys:
        matches = [
            (index, raw)
            for index, raw in enumerate(raw_signals)
            if isinstance(raw, dict)
            and raw.get("direction") == "buy"
            and raw.get("symbol") == blocked["symbol"]
            and raw.get("strategy_id") == blocked["strategy_id"]
        ]
        raw_index, frozen = matches[0] if len(matches) == 1 else (None, {})
        blocked_signals.append(
            {
                "kind": "account_blocked_signal",
                "direction": "buy",
                "decision_date": str(row.get("run_date") or ""),
                "symbol": blocked["symbol"],
                "strategy_id": blocked["strategy_id"],
                "board": blocked["board"],
                "reason": blocked["reason"],
                "scan_run_id": str(row.get("run_id") or ""),
                "source_ref": (
                    f"{row.get('run_id')}:raw_signal:{raw_index}"
                    if raw_index is not None
                    else None
                ),
                "frozen_price": frozen.get("frozen_close"),
                "frozen_market_date": frozen.get("frozen_market_date"),
                "source_bound": raw_index is not None and integrity_valid,
                "report_authoritative": False,
            }
        )
    candidates: list[dict[str, Any]] = []
    for signal, action in zip(selected, actions, strict=False):
        if not isinstance(signal, dict) or not isinstance(action, dict):
            continue
        signal_id = action.get("source_signal_id")
        action_id = action.get("action_id")
        if not isinstance(signal_id, int) or not isinstance(action_id, int):
            continue
        candidates.append(
            {
                "kind": "formal_signal",
                "decision_date": str(row.get("run_date") or ""),
                "frozen_market_date": signal.get("frozen_market_date"),
                "symbol": str(signal.get("symbol") or ""),
                "direction": str(signal.get("direction") or ""),
                "strategy_id": str(signal.get("strategy_id") or ""),
                "scan_run_id": str(row.get("run_id") or ""),
                "signal_id": signal_id,
                "action_id": action_id,
                "source_ref": f"{row.get('run_id')}:signal:{signal_id}",
                "frozen_price": signal.get("frozen_close"),
            }
        )
    if (
        len(candidates) != len(selected)
        or len(actions) != len(selected)
        or payload.get("selected_signal_count") != len(selected)
        or (
            "raw_signals" in payload
            and payload.get("raw_signal_count") != len(raw_signals)
        )
    ):
        integrity_valid = False
    if not integrity_valid:
        for blocked in blocked_signals:
            blocked["source_bound"] = False
    return {
        **_run_identity(row),
        "integrity_valid": integrity_valid,
        "market_date": payload.get("market_date"),
        **(
            {
                "receipt_fingerprints": [
                    str(item) for item in payload.get("receipt_fingerprints") or []
                ]
            }
            if include_receipts
            else {}
        ),
        "input_fingerprint": payload.get("input_fingerprint"),
        "output_fingerprint": expected,
        "selected_signal_count": payload.get("selected_signal_count"),
        "raw_signal_count": payload.get("raw_signal_count"),
        "normal_no_signal": payload.get("normal_no_signal") is True,
        "account_blocked_buys": account_blocked_buys,
        "blocked_signals": blocked_signals,
        "action_count": len(actions),
        "candidates": candidates,
        "reason_codes": [
            *([] if integrity_valid else ["promoted_scan_integrity_invalid"]),
            *[str(item) for item in payload.get("blockers") or []],
        ],
    }


def _research_by_date(
    db: Any, report_dates: set[str]
) -> dict[str, list[dict[str, Any]]]:
    path = optional_database_path(db)
    if not report_dates:
        return {}
    if path is None:
        return _unavailable_research(report_dates)
    store = DailyStrategyArtifactStore(path, path.parent / "strategy-research-backups")
    try:
        selections = store.list_selections(limit=-1)
    except Exception:
        return _unavailable_research(report_dates)
    result: dict[str, list[dict[str, Any]]] = {}
    for selection in selections:
        market_date = str(selection.get("market_date") or "")
        if market_date not in report_dates:
            continue
        run_id = str(selection.get("run_id") or "")
        try:
            verified = store.load_verified_research_artifacts(run_id=run_id)
        except Exception:
            result.setdefault(market_date, []).append(
                {
                    "run_id": run_id,
                    "selection_id": selection.get("selection_id"),
                    "status": "unavailable",
                    "reason_codes": ["research_artifact_integrity_unavailable"],
                    "operations": [],
                    "research_only": True,
                }
            )
            continue
        frozen = verified["selection"]
        recommendation = frozen.get("research_recommendation")
        recommendation = recommendation if isinstance(recommendation, dict) else {}
        preview = recommendation.get("research_operation_preview")
        preview = preview if isinstance(preview, dict) else {}
        target_market_date = _next_verified_session(db, market_date)
        operations = [
            {
                "kind": "research_preview",
                "market_date": market_date,
                "target_market_date": target_market_date,
                "signal_date": item.get("signal_date"),
                "symbol": item.get("symbol"),
                "operation": item.get("operation"),
                "source_ref": f"{frozen.get('selection_id')}:operation:{index}",
                "selection_id": frozen.get("selection_id"),
                "run_id": run_id,
                "dataset_snapshot_id": preview.get("dataset_snapshot_id"),
                "formula_fingerprint": preview.get("formula_fingerprint"),
                "frozen_price": None,
                "research_only": True,
                "report_authoritative": False,
            }
            for index, item in enumerate(preview.get("operations") or [])
            if isinstance(item, dict)
        ]
        result.setdefault(market_date, []).append(
            {
                "run_id": run_id,
                "selection_id": frozen.get("selection_id"),
                "status": frozen.get("status"),
                "normalized_research_status": recommendation.get("status"),
                "selection_fingerprint": frozen.get("selection_fingerprint"),
                "research_winner_candidate_id": recommendation.get(
                    "research_winner_candidate_id"
                ),
                "dataset_snapshot_id": preview.get("dataset_snapshot_id"),
                "formula_fingerprint": preview.get("formula_fingerprint"),
                "operations": operations,
                "reason_codes": list(frozen.get("blockers") or []),
                "research_only": True,
            }
        )
    return result


def _next_verified_session(db: Any, market_date: str) -> str | None:
    try:
        year = date.fromisoformat(market_date).year
    except ValueError:
        return None
    for candidate_year in (year, year + 1):
        days, _, blockers = _verified_calendar(db, candidate_year)
        if blockers:
            return None
        candidate = next_trading_day(
            days=days, run_date=market_date, include_current_date=False
        )
        if candidate:
            return candidate
    return None


def _unavailable_research(
    report_dates: set[str],
) -> dict[str, list[dict[str, Any]]]:
    return {
        day: [
            {
                "run_id": None,
                "selection_id": None,
                "status": "unavailable",
                "reason_codes": ["research_artifact_store_unavailable"],
                "operations": [],
                "research_only": True,
            }
        ]
        for day in report_dates
    }


__all__ = ["get_daily_decision_report", "list_daily_decision_reports"]
