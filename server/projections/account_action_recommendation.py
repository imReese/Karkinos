"""Canonical account-action recommendation beside research-only previews."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from server.contracts.content_identity import content_fingerprint

ACCOUNT_ACTION_RECOMMENDATION_SCHEMA_VERSION = (
    "karkinos.decision.account_action_recommendation.v1"
)
PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION = (
    "karkinos.promoted_strategy_universe_scan.v1"
)
PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE = "promoted_strategy_universe_scan"

_SCAN_INPUT_KEYS = (
    "schema_version",
    "decision_date",
    "market_date",
    "market_universe_snapshot_id",
    "receipt_fingerprints",
    "strategy_bindings",
    "portfolio_binding",
    "evaluation_policy_fingerprint",
    "signal_selection_policy",
    "signal_selection_fingerprint",
    "safety_gate_fingerprint",
)


def resolve_latest_verified_promoted_strategy_scan(
    db: Any,
    *,
    decision_date: str,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    """Reopen and rehash a bound scan, or the latest same-day scan for legacy reads."""

    reader = getattr(db, "list_automation_runs_sync", None)
    if not callable(reader) or not decision_date:
        return _unavailable_scan("promoted_strategy_scan_reader_unavailable")
    if expected_run_id is not None:
        exact_reader = getattr(db, "get_automation_run_sync", None)
        row = exact_reader(expected_run_id) if callable(exact_reader) else None
        rows = [row] if isinstance(row, Mapping) else []
        if not rows:
            return _unavailable_scan("promoted_strategy_scan_bound_run_missing")
    else:
        rows = reader(
            run_type=PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
            run_date=decision_date,
            limit=1,
        )
    if not rows:
        promotion_reader = getattr(db, "list_strategy_promotion_states_sync", None)
        if callable(promotion_reader):
            eligible_promotions = [
                row
                for row in (promotion_reader() or [])
                if str(row.get("strategy_id") or "").startswith("ai_formula_shadow:")
                and str(row.get("stage") or "") == "paper_shadow"
            ]
            if not eligible_promotions:
                return _unavailable_scan("promoted_strategy_not_configured")
        return _unavailable_scan("promoted_strategy_scan_missing")
    row = dict(rows[0])
    payload = _json_object(row.get("payload_json"))
    output_fingerprint = str(payload.get("output_fingerprint") or "")
    output_core = dict(payload)
    output_core.pop("output_fingerprint", None)
    input_core = {key: payload.get(key) for key in _SCAN_INPUT_KEYS}
    expected_input_fingerprint = "sha256:" + content_fingerprint(input_core)
    expected_output_fingerprint = "sha256:" + content_fingerprint(output_core)
    input_fingerprint = str(payload.get("input_fingerprint") or "")
    expected_run_id = (
        f"automation:promoted-strategy-universe-scan:{decision_date}:"
        f"{input_fingerprint.removeprefix('sha256:')[:16]}"
    )
    blockers: list[str] = []
    if row.get("run_type") != PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE:
        blockers.append("promoted_strategy_scan_type_mismatch")
    if row.get("run_date") != decision_date or payload.get("decision_date") != (
        decision_date
    ):
        blockers.append("promoted_strategy_scan_date_mismatch")
    if payload.get("schema_version") != (
        PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION
    ):
        blockers.append("promoted_strategy_scan_schema_mismatch")
    if row.get("status") != payload.get("status"):
        blockers.append("promoted_strategy_scan_status_mismatch")
    blockers.extend(_scan_started_at_blockers(row.get("started_at"), decision_date))
    if str(row.get("run_id") or "") != expected_run_id:
        blockers.append("promoted_strategy_scan_run_identity_mismatch")
    if input_fingerprint != expected_input_fingerprint:
        blockers.append("promoted_strategy_scan_input_fingerprint_mismatch")
    if output_fingerprint != expected_output_fingerprint:
        blockers.append("promoted_strategy_scan_output_fingerprint_mismatch")
    if payload.get("preview_only") is not False:
        blockers.append("promoted_strategy_scan_not_persisted")
    if payload.get("creates_oms_order") is not False:
        blockers.append("promoted_strategy_scan_order_boundary_invalid")
    if payload.get("submits_broker_order") is not False:
        blockers.append("promoted_strategy_scan_broker_boundary_invalid")
    if payload.get("changes_capital_authority") is not False:
        blockers.append("promoted_strategy_scan_capital_boundary_invalid")
    if payload.get("mutates_account_ledger") is not False:
        blockers.append("promoted_strategy_scan_ledger_boundary_invalid")
    if payload.get("changes_strategy_promotion") is not False:
        blockers.append("promoted_strategy_scan_promotion_boundary_invalid")
    if payload.get("manual_confirmation_required") is not True:
        blockers.append("promoted_strategy_scan_human_control_invalid")
    blockers.extend(_scan_semantic_blockers(payload))
    if blockers:
        return _unavailable_scan(blockers[0], blockers=blockers)
    return {
        "decision_date": str(payload.get("decision_date") or "") or None,
        "market_date": str(payload.get("market_date") or "") or None,
        "status": str(payload.get("status") or "unavailable"),
        "run_id": str(row.get("run_id") or ""),
        "started_at": str(row.get("started_at") or "") or None,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "selected_signal_count": int(payload.get("selected_signal_count") or 0),
        "signals": [
            dict(item)
            for item in payload.get("selected_signals") or []
            if isinstance(item, Mapping)
        ],
        "normal_no_signal": payload.get("normal_no_signal") is True,
        "raw_signal_count": int(payload.get("raw_signal_count") or 0),
        "raw_signals": [
            dict(item)
            for item in payload.get("raw_signals") or []
            if isinstance(item, Mapping)
        ],
        "account_blocked_buys": [
            dict(item)
            for item in payload.get("account_blocked_buys") or []
            if isinstance(item, Mapping)
        ],
        "blockers": _strings(payload.get("blockers")),
        "strategy_bindings": [
            dict(item)
            for item in payload.get("strategy_bindings") or []
            if isinstance(item, Mapping)
        ],
        "portfolio_binding": _mapping(payload.get("portfolio_binding")),
        "market_universe_snapshot_id": payload.get("market_universe_snapshot_id"),
        "receipt_fingerprints": _strings(payload.get("receipt_fingerprints")),
        "evaluation_policy_fingerprint": payload.get("evaluation_policy_fingerprint"),
        "signal_selection_fingerprint": payload.get("signal_selection_fingerprint"),
        "safety_gate_fingerprint": payload.get("safety_gate_fingerprint"),
        "action_task_ids": [
            str(item.get("task_id") or item.get("action_id") or "")
            for item in payload.get("action_tasks") or []
            if isinstance(item, Mapping)
            and str(item.get("task_id") or item.get("action_id") or "")
        ],
        "verified": True,
    }


def build_account_action_recommendation(
    *,
    decision_payload: Mapping[str, Any],
    trading_plan: Mapping[str, Any],
    promoted_scan: Mapping[str, Any],
    current_evidence_blockers: Sequence[str],
    current_evidence_fingerprint: str,
    display_name_resolver: Callable[[str, str | None], str] | None = None,
) -> dict[str, Any]:
    """Project strict action authority plus lower-risk read-only presentation tiers."""

    decision_date = str(decision_payload.get("decision_date") or "")
    candidates = [
        dict(item)
        for item in decision_payload.get("candidates") or []
        if isinstance(item, Mapping)
    ]
    order_intents = [
        dict(item)
        for item in trading_plan.get("order_intents") or []
        if isinstance(item, Mapping)
    ]
    scan_status = str(promoted_scan.get("status") or "unavailable")
    scan_blockers = _strings(promoted_scan.get("blockers"))
    account_blocked_buys = [
        dict(item)
        for item in promoted_scan.get("account_blocked_buys") or []
        if isinstance(item, Mapping)
    ]
    current_blockers = _strings(current_evidence_blockers)
    if not _is_sha256(current_evidence_fingerprint):
        current_blockers.append("current_account_evidence_fingerprint_invalid")
    current_blockers = list(dict.fromkeys(current_blockers))
    plan_blockers = [
        str(item.get("reason") or item.get("code") or "")
        for item in trading_plan.get("blockers") or []
        if isinstance(item, Mapping)
        and str(item.get("reason") or item.get("code") or "")
    ]

    # `status` remains the strict authority state used by the manual-review path.
    # Read-only display tiers below never weaken these fail-closed checks.
    if promoted_scan.get("verified") is not True:
        status = "unavailable"
        reasons = [*scan_blockers, *current_blockers] or [
            "verified_promoted_strategy_scan_unavailable"
        ]
    elif scan_status == "blocked":
        status = "blocked"
        reasons = [*scan_blockers, *current_blockers] or [
            "promoted_strategy_scan_blocked"
        ]
    elif current_blockers:
        status = "blocked"
        reasons = current_blockers
    elif int(trading_plan.get("manual_ready_count") or 0) > 0:
        status = "manual_review_required"
        reasons = ["manual_confirmation_required"]
    elif int(trading_plan.get("paper_shadow_ready_count") or 0) > 0:
        status = "paper_shadow_required"
        reasons = ["paper_shadow_evaluation_required"]
    elif int(trading_plan.get("blocked_count") or 0) > 0:
        status = "blocked"
        reasons = plan_blockers or ["daily_trading_plan_blocked"]
    elif (
        scan_status == "completed_no_signal"
        and promoted_scan.get("normal_no_signal") is True
        and int(promoted_scan.get("selected_signal_count") or 0) == 0
        and not scan_blockers
        and not candidates
        and not order_intents
    ):
        status = "no_action"
        reasons = ["promoted_strategy_scan_completed_without_signal"]
    elif scan_status == "completed_no_signal" and account_blocked_buys:
        status = "blocked"
        reasons = list(
            dict.fromkeys(
                f"account_buy_blocked:{item.get('reason')}"
                for item in account_blocked_buys
                if item.get("reason")
            )
        ) or ["account_buy_candidates_ineligible"]
    elif candidates or order_intents:
        status = "blocked"
        reasons = ["decision_candidates_not_ready_for_manual_review"]
    else:
        status = "unavailable"
        reasons = scan_blockers or ["verified_promoted_strategy_scan_unavailable"]

    summary = _mapping(decision_payload.get("summary"))
    portfolio = _mapping(summary.get("portfolio"))
    account_truth = _mapping(summary.get("account_truth"))
    strategy_bindings = [
        {
            "strategy_id": item.get("strategy_id"),
            "promotion_binding_fingerprint": item.get(
                "order_generation_gate_fingerprint"
            ),
            "qualification_fingerprint": item.get("qualification_fingerprint"),
        }
        for item in promoted_scan.get("strategy_bindings") or []
        if isinstance(item, Mapping)
    ]
    actions = [
        _action_projection(item, display_name_resolver) for item in order_intents
    ]
    signal_actions = [
        _signal_projection(item, display_name_resolver)
        for item in promoted_scan.get("signals") or []
        if isinstance(item, Mapping)
    ]
    preview_blockers = _portfolio_preview_blockers(
        summary=summary,
        current_blockers=current_blockers,
    )
    signal_ready = (
        promoted_scan.get("verified") is True
        and scan_status == "completed"
        and int(promoted_scan.get("selected_signal_count") or 0) > 0
        and bool(signal_actions)
    )
    verified_no_signal = (
        promoted_scan.get("verified") is True
        and scan_status == "completed_no_signal"
        and promoted_scan.get("normal_no_signal") is True
        and int(promoted_scan.get("selected_signal_count") or 0) == 0
        and not scan_blockers
    )
    verified_account_blocked = (
        promoted_scan.get("verified") is True
        and scan_status == "completed_no_signal"
        and bool(account_blocked_buys)
    )
    if status == "manual_review_required":
        presentation_level = "manual_review"
    elif verified_no_signal:
        presentation_level = "no_action"
    elif signal_ready and not preview_blockers:
        presentation_level = "portfolio_preview"
    elif signal_ready:
        presentation_level = "signal"
    elif scan_status == "blocked" or verified_account_blocked:
        presentation_level = "blocked"
    else:
        presentation_level = "unavailable"

    configuration_blockers = [
        item
        for item in scan_blockers
        if item
        in {
            "promoted_strategy_not_configured",
            "promoted_daily_candidate_strategy_missing",
        }
    ]
    if (
        "promoted_daily_candidate_strategy_missing" in scan_blockers
        and "promoted_strategy_not_configured" not in configuration_blockers
    ):
        configuration_blockers.append("promoted_strategy_not_configured")
    source_action_task_ids = list(
        dict.fromkeys(
            [
                *_strings(promoted_scan.get("action_task_ids")),
                *[
                    str(item.get("action_id") or "")
                    for item in candidates
                    if str(item.get("action_id") or "")
                ],
            ]
        )
    )
    core = {
        "schema_version": ACCOUNT_ACTION_RECOMMENDATION_SCHEMA_VERSION,
        "decision_date": decision_date or None,
        "status": status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "source_action_task_ids": source_action_task_ids,
        "actions": actions,
        "presentation": {
            "level": presentation_level,
            "actions": actions
            if presentation_level == "manual_review"
            else signal_actions,
            "signal_status": (
                "ready"
                if signal_ready
                else "no_signal"
                if verified_no_signal
                else "account_blocked"
                if verified_account_blocked
                else "unavailable"
            ),
            "portfolio_preview_status": (
                "ready" if signal_ready and not preview_blockers else "blocked"
            ),
            "manual_review_status": (
                "ready" if status == "manual_review_required" else "blocked"
            ),
            "configuration_blockers": configuration_blockers,
            "signal_blockers": []
            if signal_ready or verified_no_signal
            else scan_blockers,
            "portfolio_preview_blockers": preview_blockers,
            "manual_review_blockers": (
                []
                if status == "manual_review_required"
                else list(dict.fromkeys([*reasons, *plan_blockers]))
            ),
            "read_only": True,
            "authorizes_execution": False,
        },
        "promoted_scan": {
            "run_id": promoted_scan.get("run_id"),
            "status": scan_status,
            "input_fingerprint": promoted_scan.get("input_fingerprint"),
            "output_fingerprint": promoted_scan.get("output_fingerprint"),
            "selected_signal_count": int(
                promoted_scan.get("selected_signal_count") or 0
            ),
            "raw_signal_count": int(promoted_scan.get("raw_signal_count") or 0),
            "account_blocked_buys": account_blocked_buys,
        },
        "current_evidence_fingerprint": current_evidence_fingerprint or None,
        "strategy_bindings": strategy_bindings,
        "account_evidence": {
            "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
            "ledger_cutoff_id": portfolio.get("ledger_cutoff_id"),
            "quote_set_fingerprint": portfolio.get("quote_set_fingerprint"),
            "valuation_status": portfolio.get("valuation_status") or "missing",
            "account_truth_status": account_truth.get("gate_status") or "blocked",
            "account_qualification_status": (
                "passed"
                if strategy_bindings
                and promoted_scan.get("verified") is True
                and not current_blockers
                else "blocked"
            ),
            "account_positions_evaluated": (
                promoted_scan.get("verified") is True
                and scan_status in {"completed", "completed_no_signal"}
                and not current_blockers
            ),
        },
        "read_only": True,
        "manual_confirmation_required": True,
        "creates_oms_order": False,
        "submits_broker_order": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": "sha256:" + content_fingerprint(core)}


def _portfolio_preview_blockers(
    *,
    summary: Mapping[str, Any],
    current_blockers: Sequence[str],
) -> list[str]:
    """Require coherent account structure, but not execution-grade clock freshness."""

    portfolio = _mapping(summary.get("portfolio"))
    account_truth = _mapping(summary.get("account_truth"))
    blockers: list[str] = []
    if str(portfolio.get("valuation_status") or "").lower() != "complete":
        blockers.append("portfolio_preview_valuation_not_complete")
    if str(account_truth.get("reconciliation_status") or "").lower() != "pass":
        blockers.append("portfolio_preview_reconciliation_not_pass")
    if _nonnegative_int(account_truth.get("unresolved_mismatch_count")) != 0:
        blockers.append("portfolio_preview_unresolved_mismatch")
    if _mapping(account_truth.get("ledger_coverage")).get("status") != "covered":
        blockers.append("portfolio_preview_ledger_coverage_not_complete")
    if not str(account_truth.get("import_run_id") or ""):
        blockers.append("portfolio_preview_import_run_missing")
    if not _is_sha256(account_truth.get("source_fingerprint")):
        blockers.append("portfolio_preview_source_fingerprint_invalid")

    structural_markers = (
        "contract_invalid",
        "fingerprint_invalid",
        "date_mismatch",
        "date_missing",
        "portfolio_changed",
        "unresolved_mismatch",
        "reconciliation_not_pass",
        "ledger_coverage_not_complete",
        "valuation_snapshot_not_complete",
        "ledger_cutoff_id_invalid",
        "after_decision_generation",
        "plan_generated_before_decision",
    )
    blockers.extend(
        blocker
        for blocker in current_blockers
        if any(marker in blocker for marker in structural_markers)
    )
    return list(dict.fromkeys(blockers))


def _action_display_name(
    item: Mapping[str, Any],
    resolver: Callable[[str, str | None], str] | None,
) -> str | None:
    symbol = str(item.get("symbol") or "")
    name = item.get("display_name") or item.get("name")
    if name and name != symbol:
        return str(name)
    if resolver is not None and symbol:
        return resolver(symbol, item.get("asset_class"))
    return str(name) if name else None


def _signal_projection(
    signal: Mapping[str, Any],
    display_name_resolver: Callable[[str, str | None], str] | None,
) -> dict[str, Any]:
    display_name = _action_display_name(signal, display_name_resolver)
    projected = {
        "action_id": None,
        "symbol": signal.get("symbol"),
        "display_name": display_name,
        "name": display_name,
        "asset_class": signal.get("asset_class") or "stock",
        "side": signal.get("direction"),
        "target_weight": signal.get("target_weight"),
        "estimated_quantity": None,
        "submission_status": "read_only_signal",
    }
    price = signal.get("frozen_close") or signal.get("price")
    if price is not None:
        projected["estimated_price"] = price
    return projected


def _action_projection(
    intent: Mapping[str, Any],
    display_name_resolver: Callable[[str, str | None], str] | None,
) -> dict[str, Any]:
    display_name = _action_display_name(intent, display_name_resolver)
    projected = {
        "action_id": intent.get("action_id"),
        "symbol": intent.get("symbol"),
        "display_name": display_name,
        "name": display_name,
        "asset_class": intent.get("asset_class"),
        "side": intent.get("side"),
        "target_weight": intent.get("target_weight"),
        "estimated_quantity": intent.get("estimated_quantity"),
        "submission_status": intent.get("submission_status"),
    }
    price = intent.get("estimated_price") or intent.get("market_quote_price")
    if price is not None:
        projected["estimated_price"] = price
    if intent.get("estimated_gross_amount") is not None:
        projected["estimated_gross_amount"] = intent.get("estimated_gross_amount")
    if intent.get("estimated_net_cash_impact") is not None:
        projected["estimated_net_cash_impact"] = intent.get("estimated_net_cash_impact")
    if intent.get("estimated_total_fee") is not None:
        projected["estimated_total_fee"] = intent.get("estimated_total_fee")
    return projected


def _scan_semantic_blockers(payload: Mapping[str, Any]) -> list[str]:
    status = str(payload.get("status") or "")
    blockers = _strings(payload.get("blockers"))
    selected_count = _nonnegative_int(payload.get("selected_signal_count"))
    raw_count = _nonnegative_int(payload.get("raw_signal_count"))
    blocked_buys = [
        item
        for item in payload.get("account_blocked_buys") or []
        if isinstance(item, Mapping)
    ]
    action_tasks = [
        item for item in payload.get("action_tasks") or [] if isinstance(item, Mapping)
    ]
    strategy_bindings = [
        item
        for item in payload.get("strategy_bindings") or []
        if isinstance(item, Mapping)
    ]
    portfolio_binding = _mapping(payload.get("portfolio_binding"))
    violations: list[str] = []
    if status not in {"blocked", "completed", "completed_no_signal"}:
        violations.append("promoted_strategy_scan_terminal_status_invalid")
    if status == "blocked" and (not blockers or action_tasks):
        violations.append("promoted_strategy_scan_blocked_shape_invalid")
    if status == "completed" and (
        blockers
        or selected_count is None
        or selected_count <= 0
        or len(action_tasks) != selected_count
    ):
        violations.append("promoted_strategy_scan_completed_shape_invalid")
    if status == "completed_no_signal" and (
        blockers
        or selected_count != 0
        or action_tasks
        or (payload.get("normal_no_signal") is True) != (raw_count == 0)
        or (raw_count is not None and raw_count > 0 and not blocked_buys)
        or not strategy_bindings
    ):
        violations.append("promoted_strategy_scan_no_action_shape_invalid")
    if status != "completed_no_signal" and payload.get("normal_no_signal") is True:
        violations.append("promoted_strategy_scan_no_action_flag_invalid")
    if raw_count is None:
        violations.append("promoted_strategy_scan_raw_signal_count_invalid")
    raw_signals = payload.get("raw_signals")
    if isinstance(raw_signals, list) and len(raw_signals) != raw_count:
        violations.append("promoted_strategy_scan_raw_signal_count_mismatch")
    if any(
        not str(item.get("symbol") or "")
        or str(item.get("reason") or "")
        not in {
            "board_permission_unknown",
            "board_permission_disabled",
            "unsupported_trade_unit",
            "cash_evidence_missing",
            "insufficient_cash_for_one_lot",
            "frozen_price_invalid",
        }
        for item in blocked_buys
    ):
        violations.append("promoted_strategy_scan_account_blocked_buy_invalid")
    if status in {"completed", "completed_no_signal"}:
        receipt_fingerprints = _strings(payload.get("receipt_fingerprints"))
        if (
            not str(payload.get("market_date") or "")
            or not str(payload.get("market_universe_snapshot_id") or "")
            or not receipt_fingerprints
            or any(not _is_prefixed_sha256(item) for item in receipt_fingerprints)
            or not _is_prefixed_sha256(payload.get("evaluation_policy_fingerprint"))
            or not _is_prefixed_sha256(payload.get("signal_selection_fingerprint"))
            or not _is_prefixed_sha256(payload.get("safety_gate_fingerprint"))
        ):
            violations.append("promoted_strategy_scan_market_binding_invalid")
        strategy_ids = [
            str(item.get("strategy_id") or "") for item in strategy_bindings
        ]
        if (
            not strategy_ids
            or any(not item for item in strategy_ids)
            or len(strategy_ids) != len(set(strategy_ids))
        ):
            violations.append("promoted_strategy_scan_strategy_bindings_invalid")
        for item in strategy_bindings:
            if (
                not _is_sha256(item.get("strategy_artifact_fingerprint"))
                or not _is_prefixed_sha256(
                    item.get("order_generation_gate_fingerprint")
                )
                or not _is_prefixed_sha256(item.get("universe_truth_fingerprint"))
                or (
                    item.get("qualification_fingerprint") is not None
                    and not _is_sha256(item.get("qualification_fingerprint"))
                )
            ):
                violations.append(
                    "promoted_strategy_scan_strategy_binding_fingerprint_invalid"
                )
                break
        if (
            portfolio_binding.get("valuation_status") != "complete"
            or not str(portfolio_binding.get("valuation_snapshot_id") or "")
            or not _is_prefixed_sha256(portfolio_binding.get("held_symbol_fingerprint"))
            or _nonnegative_int(portfolio_binding.get("held_stock_count")) is None
            or not _is_prefixed_sha256(
                portfolio_binding.get("capital_constraint_fingerprint")
            )
        ):
            violations.append("promoted_strategy_scan_portfolio_binding_invalid")
    if status == "completed" and any(
        _nonnegative_int(item.get("action_id")) in {None, 0} for item in action_tasks
    ):
        violations.append("promoted_strategy_scan_action_task_identity_invalid")
    return violations


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _unavailable_scan(
    reason: str,
    *,
    blockers: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "decision_date": None,
        "market_date": None,
        "status": "unavailable",
        "run_id": None,
        "started_at": None,
        "input_fingerprint": None,
        "output_fingerprint": None,
        "selected_signal_count": 0,
        "signals": [],
        "normal_no_signal": False,
        "raw_signal_count": 0,
        "raw_signals": [],
        "account_blocked_buys": [],
        "blockers": list(dict.fromkeys(blockers or [reason])),
        "strategy_bindings": [],
        "portfolio_binding": {},
        "market_universe_snapshot_id": None,
        "receipt_fingerprints": [],
        "safety_gate_fingerprint": None,
        "action_task_ids": [],
        "verified": False,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _scan_started_at_blockers(value: Any, decision_date: str) -> list[str]:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return ["promoted_strategy_scan_started_at_invalid"]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(ZoneInfo("Asia/Shanghai"))
    blockers: list[str] = []
    if local.date().isoformat() != decision_date:
        blockers.append("promoted_strategy_scan_started_at_date_mismatch")
    local_time = local.time().replace(tzinfo=None)
    if not time(9, 35) <= local_time < time(9, 45):
        blockers.append("promoted_strategy_scan_started_at_outside_reviewed_window")
    return blockers


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [str(item) for item in value if str(item)]


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "")
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized.lower()
    )


def _is_prefixed_sha256(value: Any) -> bool:
    normalized = str(value or "")
    return normalized.startswith("sha256:") and _is_sha256(
        normalized.removeprefix("sha256:")
    )


__all__ = [
    "ACCOUNT_ACTION_RECOMMENDATION_SCHEMA_VERSION",
    "build_account_action_recommendation",
    "resolve_latest_verified_promoted_strategy_scan",
]
