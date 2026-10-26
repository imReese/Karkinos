from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.persistence.backtest_results import V25_BACKTEST_INVALIDATIONS
from server.projections.account_action_recommendation import (
    build_account_action_recommendation,
    resolve_account_strategy_context,
    resolve_latest_verified_promoted_strategy_scan,
)
from server.routes.decision import _current_shadow_qualification_evidence
from server.services.decision.daily_decision_policy_gates import (
    current_account_action_evidence_blockers,
)
from server.services.strategy_scan.promoted_strategy_universe_scan import (
    PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
    PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
)


def _persisted_no_signal_scan() -> dict:
    portfolio_binding = {
        "valuation_snapshot_id": "valuation-1",
        "valuation_status": "complete",
        "held_symbol_fingerprint": "sha256:" + "d" * 64,
        "held_stock_count": 1,
        "capital_constraint_fingerprint": "sha256:"
        + content_fingerprint(
            {
                "valuation_snapshot_id": "valuation-1",
                "valuation_status": "complete",
                "total_equity": 100_000.0,
            }
        ),
    }
    input_core = {
        "schema_version": PROMOTED_STRATEGY_UNIVERSE_SCAN_SCHEMA_VERSION,
        "decision_date": "2026-09-01",
        "market_date": "2026-08-31",
        "market_universe_snapshot_id": "market-snapshot",
        "receipt_fingerprints": ["sha256:" + "9" * 64],
        "strategy_bindings": [
            {
                "strategy_id": "ai_formula_shadow:candidate-1",
                "strategy_artifact_fingerprint": "a" * 64,
                "order_generation_gate_fingerprint": "sha256:" + "b" * 64,
                "universe_truth_fingerprint": "sha256:" + "c" * 64,
            }
        ],
        "portfolio_binding": portfolio_binding,
        "evaluation_policy_fingerprint": "sha256:" + "6" * 64,
        "signal_selection_policy": (
            "exits_first_then_20d_median_amount_desc_then_symbol_asc"
        ),
        "signal_selection_fingerprint": "sha256:" + "8" * 64,
        "safety_gate_fingerprint": "sha256:" + "7" * 64,
    }
    input_fingerprint = "sha256:" + content_fingerprint(input_core)
    payload_core = {
        **input_core,
        "status": "completed_no_signal",
        "input_fingerprint": input_fingerprint,
        "blockers": [],
        "raw_signal_count": 0,
        "selected_signal_count": 0,
        "selected_signals": [],
        "action_tasks": [],
        "full_market_truths": [],
        "normal_no_signal": True,
        "preview_only": False,
        "manual_confirmation_required": True,
        "creates_oms_order": False,
        "submits_broker_order": False,
        "mutates_account_ledger": False,
        "changes_strategy_promotion": False,
        "changes_capital_authority": False,
        "finished_at": "2026-09-01T01:35:00+00:00",
    }
    payload = {
        **payload_core,
        "output_fingerprint": "sha256:" + content_fingerprint(payload_core),
    }
    return {
        "run_id": (
            "automation:promoted-strategy-universe-scan:2026-09-01:"
            + input_fingerprint.removeprefix("sha256:")[:16]
        ),
        "run_type": PROMOTED_STRATEGY_UNIVERSE_SCAN_RUN_TYPE,
        "run_date": "2026-09-01",
        "status": "completed_no_signal",
        "started_at": "2026-09-01T09:35:00+08:00",
        "payload_json": json.dumps(payload),
    }


class _Db:
    def __init__(
        self,
        rows: list[dict],
        promotion_states: list[dict] | None = None,
    ) -> None:
        self.rows = rows
        self.promotion_states = promotion_states

    def list_automation_runs_sync(self, **_: object) -> list[dict]:
        return self.rows

    def get_automation_run_sync(self, run_id: str) -> dict | None:
        return next((row for row in self.rows if row["run_id"] == run_id), None)

    def list_strategy_promotion_states_sync(self) -> list[dict]:
        return list(self.promotion_states or [])


def _current_gate_inputs() -> tuple[dict, dict]:
    decision = {
        "decision_date": "2026-09-01",
        "generated_at": "2026-09-01T15:00:00+08:00",
        "candidates": [],
        "summary": {
            "portfolio": {
                "valuation_snapshot_id": "valuation-1",
                "ledger_cutoff_id": 7,
                "valuation_status": "complete",
                "position_count": 1,
            },
            "account_truth": {
                "schema_version": "karkinos.account_truth.promotion_evidence.v1",
                "promotion_status": "clear",
                "gate_status": "pass",
                "data_freshness_status": "fresh",
                "unresolved_mismatch_count": 0,
                "import_run_id": "import-1",
                "source_fingerprint": "a" * 64,
                "captured_at": "2026-09-01T14:55:00+08:00",
                "current_age_seconds": 300,
                "max_age_seconds": 86_400,
                "reconciliation_status": "pass",
                "ledger_coverage": {"status": "covered"},
            },
            "market_data": {
                "source_health": "confirmed",
                "latest_quote_timestamp": "2026-09-01T14:59:00+08:00",
            },
        },
    }
    plan = {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-09-01",
        "generated_at": decision["generated_at"],
        "order_intents": [],
        "blockers": [],
    }
    return decision, plan


@pytest.mark.unit
@pytest.mark.trading_safety
def test_missing_scan_distinguishes_no_promoted_strategy_from_automation_gap() -> None:
    no_strategy = resolve_latest_verified_promoted_strategy_scan(
        _Db([], promotion_states=[]),
        decision_date="2026-09-18",
    )
    assert no_strategy["status"] == "unavailable"
    assert no_strategy["blockers"] == ["promoted_strategy_not_configured"]

    scan_gap = resolve_latest_verified_promoted_strategy_scan(
        _Db(
            [],
            promotion_states=[
                {
                    "strategy_id": "ai_formula_shadow:candidate-1",
                    "stage": "paper_shadow",
                }
            ],
        ),
        decision_date="2026-09-18",
    )
    assert scan_gap["status"] == "unavailable"
    assert scan_gap["blockers"] == ["promoted_strategy_scan_missing"]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_bound_scan_is_verified_by_exact_run_id_even_if_newer_scan_exists() -> None:
    bound = _persisted_no_signal_scan()
    unrelated = {**bound, "run_id": "later-unbound-scan"}
    db = _Db([unrelated, bound])

    latest = resolve_latest_verified_promoted_strategy_scan(
        db, decision_date="2026-09-01"
    )
    exact = resolve_latest_verified_promoted_strategy_scan(
        db, decision_date="2026-09-01", expected_run_id=bound["run_id"]
    )

    assert latest["verified"] is False
    assert exact["verified"] is True
    assert exact["run_id"] == bound["run_id"]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_verified_completed_no_signal_is_first_class_account_no_action() -> None:
    scan = resolve_latest_verified_promoted_strategy_scan(
        _Db([_persisted_no_signal_scan()]),
        decision_date="2026-09-01",
    )
    recommendation = build_account_action_recommendation(
        decision_payload={
            "decision_date": "2026-09-01",
            "candidates": [],
            "summary": {
                "portfolio": {
                    "valuation_snapshot_id": "valuation-1",
                    "ledger_cutoff_id": 7,
                    "quote_set_fingerprint": "sha256:quotes",
                    "valuation_status": "complete",
                },
                "account_truth": {"gate_status": "pass"},
            },
        },
        trading_plan={
            "manual_ready_count": 0,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [],
        },
        promoted_scan=scan,
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert scan["verified"] is True
    assert recommendation["status"] == "no_action"
    assert recommendation["reason_codes"] == [
        "promoted_strategy_scan_completed_without_signal"
    ]
    assert recommendation["account_evidence"]["account_qualification_status"] == (
        "passed"
    )
    assert recommendation["creates_oms_order"] is False
    assert recommendation["submits_broker_order"] is False
    assert recommendation["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_verified_account_ineligible_buy_is_blocked_not_no_action() -> None:
    row = _persisted_no_signal_scan()
    payload = json.loads(row["payload_json"])
    payload.update(
        {
            "raw_signal_count": 1,
            "raw_signals": [
                {
                    "strategy_id": "ai_formula_shadow:candidate-1",
                    "symbol": "301251",
                    "direction": "buy",
                }
            ],
            "account_blocked_buys": [
                {
                    "strategy_id": "ai_formula_shadow:candidate-1",
                    "symbol": "301251",
                    "board": "chinext",
                    "reason": "board_permission_unknown",
                }
            ],
            "normal_no_signal": False,
        }
    )
    payload.pop("output_fingerprint")
    payload["output_fingerprint"] = "sha256:" + content_fingerprint(payload)
    row["payload_json"] = json.dumps(payload)

    scan = resolve_latest_verified_promoted_strategy_scan(
        _Db([row]), decision_date="2026-09-01"
    )
    recommendation = build_account_action_recommendation(
        decision_payload={"decision_date": "2026-09-01", "candidates": []},
        trading_plan={
            "manual_ready_count": 0,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [],
        },
        promoted_scan=scan,
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert scan["verified"] is True
    assert recommendation["status"] == "blocked"
    assert recommendation["presentation"]["signal_status"] == "account_blocked"
    assert recommendation["reason_codes"] == [
        "account_buy_blocked:board_permission_unknown"
    ]
    assert (
        recommendation["promoted_scan"]["account_blocked_buys"][0]["symbol"] == "301251"
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_missing_or_tampered_scan_never_degrades_to_no_action() -> None:
    missing = resolve_latest_verified_promoted_strategy_scan(
        _Db([]), decision_date="2026-09-01"
    )
    tampered_row = _persisted_no_signal_scan()
    tampered = json.loads(tampered_row["payload_json"])
    tampered["normal_no_signal"] = False
    tampered_row["payload_json"] = json.dumps(tampered)
    drifted = resolve_latest_verified_promoted_strategy_scan(
        _Db([tampered_row]), decision_date="2026-09-01"
    )

    for scan in (missing, drifted):
        recommendation = build_account_action_recommendation(
            decision_payload={"decision_date": "2026-09-01", "candidates": []},
            trading_plan={
                "manual_ready_count": 0,
                "paper_shadow_ready_count": 0,
                "blocked_count": 0,
                "blockers": [],
                "order_intents": [],
            },
            promoted_scan=scan,
            current_evidence_blockers=[],
            current_evidence_fingerprint="e" * 64,
        )
        assert scan["verified"] is False
        assert recommendation["status"] == "unavailable"
        assert recommendation["status"] != "no_action"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_manual_review_projection_preserves_display_name_for_overview() -> None:
    recommendation = build_account_action_recommendation(
        decision_payload={
            "decision_date": "2026-09-01",
            "candidates": [{"action_id": 7, "symbol": "600519"}],
            "summary": {
                "portfolio": {"valuation_status": "complete"},
                "account_truth": {"gate_status": "pass"},
            },
        },
        trading_plan={
            "manual_ready_count": 1,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [
                {
                    "action_id": 7,
                    "symbol": "600519",
                    "display_name": "贵州茅台",
                    "asset_class": "stock",
                    "side": "buy",
                    "target_weight": 0.12,
                    "estimated_quantity": 100,
                    "submission_status": "manual_confirmation_required",
                }
            ],
        },
        promoted_scan={
            "verified": True,
            "status": "completed",
            "blockers": [],
            "strategy_bindings": [],
            "selected_signal_count": 1,
        },
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "manual_review_required"
    assert recommendation["actions"] == [
        {
            "action_id": 7,
            "symbol": "600519",
            "display_name": "贵州茅台",
            "name": "贵州茅台",
            "asset_class": "stock",
            "side": "buy",
            "target_weight": 0.12,
            "estimated_quantity": 100,
            "submission_status": "manual_confirmation_required",
            "strategy_id": None,
            "frozen_market_date": None,
        }
    ]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_stale_execution_evidence_keeps_verified_signal_as_portfolio_preview() -> None:
    decision, plan = _current_gate_inputs()
    decision["candidates"] = [{"action_id": 7, "symbol": "600519"}]
    current_blockers = [
        "account_truth_not_fresh",
        "account_truth_not_bound_to_plan_date",
        "account_truth_age_exceeds_reviewed_limit",
        "account_truth_too_old_for_decision",
        "market_quote_too_old_for_decision",
        "decision_generation_time_not_bound_to_plan_date",
        "plan_generation_time_not_bound_to_plan_date",
    ]
    recommendation = build_account_action_recommendation(
        decision_payload=decision,
        trading_plan=plan,
        promoted_scan={
            "verified": True,
            "status": "completed",
            "blockers": [],
            "selected_signal_count": 1,
            "signals": [
                {
                    "strategy_id": "ai_formula_shadow:one",
                    "symbol": "600519",
                    "direction": "buy",
                    "target_weight": 0.12,
                }
            ],
            "strategy_bindings": [
                {
                    "strategy_id": "ai_formula_shadow:one",
                    "order_generation_gate_fingerprint": "sha256:" + "a" * 64,
                }
            ],
        },
        current_evidence_blockers=current_blockers,
        current_evidence_fingerprint="e" * 64,
        display_name_resolver=lambda symbol, asset_class: (
            "贵州茅台" if (symbol, asset_class) == ("600519", None) else symbol
        ),
    )

    assert recommendation["status"] == "blocked"
    assert recommendation["presentation"]["level"] == "portfolio_preview"
    assert recommendation["presentation"]["portfolio_preview_status"] == "ready"
    assert recommendation["presentation"]["manual_review_status"] == "blocked"
    assert recommendation["presentation"]["actions"][0]["symbol"] == "600519"
    assert recommendation["presentation"]["actions"][0]["display_name"] == ("贵州茅台")
    assert recommendation["presentation"]["actions"][0]["target_weight"] == 0.12
    assert recommendation["presentation"]["actions"][0]["estimated_quantity"] is None
    assert recommendation["presentation"]["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_structural_account_mismatch_downgrades_preview_to_signal_only() -> None:
    decision, plan = _current_gate_inputs()
    decision["summary"]["account_truth"]["unresolved_mismatch_count"] = 1
    recommendation = build_account_action_recommendation(
        decision_payload=decision,
        trading_plan=plan,
        promoted_scan={
            "verified": True,
            "status": "completed",
            "blockers": [],
            "selected_signal_count": 1,
            "signals": [
                {
                    "strategy_id": "ai_formula_shadow:one",
                    "symbol": "600519",
                    "direction": "sell",
                    "target_weight": 0.0,
                }
            ],
            "strategy_bindings": [],
        },
        current_evidence_blockers=["account_truth_unresolved_mismatch"],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "blocked"
    assert recommendation["presentation"]["level"] == "signal"
    assert recommendation["presentation"]["signal_status"] == "ready"
    assert (
        "portfolio_preview_unresolved_mismatch"
        in (recommendation["presentation"]["portfolio_preview_blockers"])
    )
    assert recommendation["presentation"]["manual_review_status"] == "blocked"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_missing_promoted_strategy_is_configuration_readiness_not_action_authority() -> (
    None
):
    recommendation = build_account_action_recommendation(
        decision_payload={"decision_date": "2026-09-01", "candidates": []},
        trading_plan={
            "manual_ready_count": 0,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [],
        },
        promoted_scan={
            "verified": False,
            "status": "unavailable",
            "blockers": ["promoted_strategy_not_configured"],
            "selected_signal_count": 0,
            "signals": [],
            "strategy_bindings": [],
        },
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "unavailable"
    assert recommendation["presentation"]["level"] == "unavailable"
    assert recommendation["presentation"]["configuration_blockers"] == [
        "promoted_strategy_not_configured"
    ]
    assert recommendation["presentation"]["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_missing_promoted_daily_candidate_strategy_populates_configuration_blockers() -> (
    None
):
    recommendation = build_account_action_recommendation(
        decision_payload={"decision_date": "2026-09-01", "candidates": []},
        trading_plan={
            "manual_ready_count": 0,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [],
        },
        promoted_scan={
            "verified": True,
            "status": "blocked",
            "blockers": ["promoted_daily_candidate_strategy_missing"],
            "selected_signal_count": 0,
            "signals": [],
            "strategy_bindings": [],
        },
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "blocked"
    assert recommendation["presentation"]["level"] == "blocked"
    assert (
        "promoted_strategy_not_configured"
        in recommendation["presentation"]["configuration_blockers"]
    )
    assert (
        "promoted_daily_candidate_strategy_missing"
        in recommendation["presentation"]["configuration_blockers"]
    )
    assert recommendation["presentation"]["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_unverified_scan_cannot_borrow_manual_ready_plan_authority() -> None:
    recommendation = build_account_action_recommendation(
        decision_payload={
            "decision_date": "2026-09-01",
            "candidates": [{"action_id": 7, "symbol": "600519"}],
        },
        trading_plan={
            "manual_ready_count": 1,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [{"action_id": 7, "symbol": "600519"}],
        },
        promoted_scan={
            "verified": False,
            "status": "unavailable",
            "blockers": ["promoted_strategy_scan_input_fingerprint_mismatch"],
            "strategy_bindings": [],
        },
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "unavailable"
    assert recommendation["reason_codes"] == [
        "promoted_strategy_scan_input_fingerprint_mismatch"
    ]
    assert recommendation["account_evidence"]["account_qualification_status"] == (
        "blocked"
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_unverified_scan_explains_exact_current_qualification_blocker() -> None:
    recommendation = build_account_action_recommendation(
        decision_payload={"decision_date": "2026-09-01", "candidates": []},
        trading_plan={
            "manual_ready_count": 0,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [],
        },
        promoted_scan={
            "verified": False,
            "status": "unavailable",
            "blockers": ["promoted_strategy_scan_missing"],
            "strategy_bindings": [],
        },
        current_evidence_blockers=["qualification_valuation_snapshot_stale"],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "unavailable"
    assert recommendation["reason_codes"] == [
        "promoted_strategy_scan_missing",
        "qualification_valuation_snapshot_stale",
    ]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_current_qualification_attempt_is_explanatory_only(monkeypatch) -> None:
    attempt = {
        "status": "blocked",
        "failure_code": "qualification_valuation_or_ledger_not_complete",
        "blockers": ["qualification_valuation_or_ledger_not_complete"],
        "evidence_fingerprint": "a" * 64,
    }
    status = {
        "latest_qualification_attempt": attempt,
        "research_outcome": {"account_qualification_status": "blocked"},
        "qualification_runs": [],
    }
    monkeypatch.setattr(
        "server.composition.ai_application_services.build_shadow_research_read_service",
        lambda _state: SimpleNamespace(
            qualification_status=lambda: status,
            status=lambda: pytest.fail(
                "account explanation must not read full research/publication status"
            ),
        ),
    )

    blockers, fingerprint = _current_shadow_qualification_evidence(
        SimpleNamespace(db=SimpleNamespace()),
        promoted_scan={"verified": False, "strategy_bindings": []},
    )

    assert blockers == ["qualification_valuation_or_ledger_not_complete"]
    assert fingerprint == "a" * 64


@pytest.mark.unit
@pytest.mark.trading_safety
def test_new_qualification_failure_does_not_override_active_promoted_strategy(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "server.composition.ai_application_services.build_shadow_research_read_service",
        lambda _state: pytest.fail("current research must not replace active strategy"),
    )
    db = SimpleNamespace(
        list_strategy_promotion_states_sync=lambda: [
            {
                "strategy_id": "ai_formula_shadow:already-promoted",
                "stage": "paper_shadow",
            }
        ]
    )

    assert _current_shadow_qualification_evidence(
        SimpleNamespace(db=db),
        promoted_scan={"verified": False, "strategy_bindings": []},
    ) == ([], None)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_current_evidence_drift_blocks_verified_no_signal() -> None:
    scan = resolve_latest_verified_promoted_strategy_scan(
        _Db([_persisted_no_signal_scan()]),
        decision_date="2026-09-01",
    )

    recommendation = build_account_action_recommendation(
        decision_payload={"decision_date": "2026-09-01", "candidates": []},
        trading_plan={
            "manual_ready_count": 0,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [],
        },
        promoted_scan=scan,
        current_evidence_blockers=["promoted_strategy_scan_current_portfolio_changed"],
        current_evidence_fingerprint="f" * 64,
    )

    assert recommendation["status"] == "blocked"
    assert recommendation["reason_codes"] == [
        "promoted_strategy_scan_current_portfolio_changed"
    ]
    assert (
        recommendation["account_evidence"]["account_qualification_status"] == "blocked"
    )
    assert recommendation["account_evidence"]["account_positions_evaluated"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["strategy_bindings"].append(
            dict(payload["strategy_bindings"][0])
        ),
        lambda payload: payload["strategy_bindings"][0].pop(
            "universe_truth_fingerprint"
        ),
        lambda payload: payload.__setitem__("portfolio_binding", {}),
        lambda payload: payload.pop("evaluation_policy_fingerprint"),
    ],
)
def test_malformed_scan_binding_is_not_verified(mutation) -> None:
    row = _persisted_no_signal_scan()
    payload = json.loads(row["payload_json"])
    mutation(payload)
    input_core = {
        key: payload.get(key)
        for key in (
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
    }
    payload["input_fingerprint"] = "sha256:" + content_fingerprint(input_core)
    payload_without_output = dict(payload)
    payload_without_output.pop("output_fingerprint", None)
    payload["output_fingerprint"] = "sha256:" + content_fingerprint(
        payload_without_output
    )
    row["run_id"] = (
        "automation:promoted-strategy-universe-scan:2026-09-01:"
        + payload["input_fingerprint"].removeprefix("sha256:")[:16]
    )
    row["payload_json"] = json.dumps(payload)

    scan = resolve_latest_verified_promoted_strategy_scan(
        _Db([row]), decision_date="2026-09-01"
    )

    assert scan["verified"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_current_account_gate_ignores_read_time_window_but_not_fact_drift() -> None:
    decision, plan = _current_gate_inputs()

    assert (
        current_account_action_evidence_blockers(
            decision_payload=decision,
            trading_plan=plan,
        )
        == []
    )

    decision["summary"]["account_truth"]["data_freshness_status"] = "stale"
    decision["summary"]["account_truth"]["reconciliation_status"] = "blocked"
    decision["summary"]["portfolio"]["valuation_status"] = "degraded"
    decision["summary"]["market_data"]["source_health"] = "stale"
    blockers = current_account_action_evidence_blockers(
        decision_payload=decision,
        trading_plan=plan,
    )

    assert "decision_generated_outside_reviewed_window" not in blockers
    assert "plan_generated_outside_reviewed_window" not in blockers
    assert "account_truth_not_fresh" in blockers
    assert "account_truth_reconciliation_not_pass" in blockers
    assert "valuation_snapshot_not_complete" in blockers
    assert "market_data_not_trusted" in blockers


@pytest.mark.unit
@pytest.mark.trading_safety
def test_manual_review_projection_preserves_price_and_cost_estimates() -> None:
    recommendation = build_account_action_recommendation(
        decision_payload={
            "decision_date": "2026-09-01",
            "candidates": [{"action_id": 1, "symbol": "600519"}],
            "summary": {
                "portfolio": {"valuation_status": "complete"},
                "account_truth": {"gate_status": "pass"},
            },
        },
        trading_plan={
            "manual_ready_count": 1,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [
                {
                    "action_id": 1,
                    "symbol": "600519",
                    "display_name": "贵州茅台",
                    "asset_class": "stock",
                    "side": "buy",
                    "target_weight": 0.15,
                    "estimated_quantity": 200,
                    "estimated_price": 1800.5,
                    "estimated_gross_amount": 360100.0,
                    "estimated_net_cash_impact": -360180.0,
                    "estimated_total_fee": 80.0,
                    "submission_status": "manual_confirmation_required",
                }
            ],
        },
        promoted_scan={
            "verified": True,
            "status": "completed",
            "blockers": [],
            "strategy_bindings": [],
            "selected_signal_count": 1,
        },
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "manual_review_required"
    assert len(recommendation["actions"]) == 1
    action = recommendation["actions"][0]
    assert action["symbol"] == "600519"
    assert action["estimated_price"] == 1800.5
    assert action["estimated_gross_amount"] == 360100.0
    assert action["estimated_net_cash_impact"] == -360180.0
    assert action["estimated_total_fee"] == 80.0


@pytest.mark.unit
@pytest.mark.trading_safety
def test_blocked_decision_window_still_presents_read_only_signals_when_verified() -> (
    None
):
    recommendation = build_account_action_recommendation(
        decision_payload={
            "decision_date": "2026-09-01",
            "candidates": [],
            "summary": {
                "portfolio": {"valuation_status": "complete"},
                "account_truth": {"gate_status": "pass"},
            },
        },
        trading_plan={
            "manual_ready_count": 0,
            "paper_shadow_ready_count": 0,
            "blocked_count": 0,
            "blockers": [],
            "order_intents": [],
        },
        promoted_scan={
            "verified": True,
            "status": "blocked",
            "blockers": ["strategy_scan_outside_reviewed_decision_window"],
            "strategy_bindings": [],
            "selected_signal_count": 1,
            "signals": [
                {
                    "strategy_id": "ai_formula_shadow:candidate-1",
                    "symbol": "603659",
                    "direction": "sell",
                    "target_weight": 0.0,
                    "frozen_close": 18.5,
                }
            ],
        },
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )

    assert recommendation["status"] == "blocked"
    assert recommendation["authorizes_execution"] is False
    assert recommendation["presentation"]["level"] == "signal"
    assert recommendation["presentation"]["signal_status"] == "ready"
    assert recommendation["presentation"]["manual_review_status"] == "blocked"
    assert (
        "strategy_scan_outside_reviewed_decision_window"
        in (recommendation["presentation"]["manual_review_blockers"])
    )
    assert len(recommendation["presentation"]["actions"]) == 1
    action = recommendation["presentation"]["actions"][0]
    assert action["symbol"] == "603659"
    assert action["side"] == "sell"
    assert action["target_weight"] == 0.0
    assert action["estimated_price"] == 18.5


@pytest.fixture
def frozen_strategy_context(monkeypatch, tmp_path):
    from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
        DailyStrategyArtifactStore,
    )

    identity = "ai_formula_shadow:candidate-1"
    strategy = {
        "formula_ast": {
            "entry": {
                "op": "gt",
                "left": {"op": "field", "name": "close"},
                "right": {
                    "op": "rolling_mean",
                    "input": {"op": "field", "name": "close"},
                    "window": 20,
                },
            },
            "exit": {
                "op": "lt",
                "left": {"op": "field", "name": "close"},
                "right": {"op": "constant", "value": 10},
            },
        }
    }
    artifact_fingerprint = content_fingerprint(strategy)
    loaded = {
        "candidate_id": "candidate-1",
        "run_id": "research-run-1",
        "strategy_artifact_fingerprint": artifact_fingerprint,
        "strategy": strategy,
    }
    gate = {
        "status": "pass",
        "promotion": {
            "stage": "paper_shadow",
            "backtest_result_id": 17,
            "daily_strategy_artifact_binding": {
                "winner_candidate_id": "candidate-1",
                "run_id": "research-run-1",
                "operating_constraints": {
                    "strategy_artifact_fingerprint": artifact_fingerprint,
                    "economic_hypothesis": "冻结的趋势假设",
                    "risk_impact": "震荡时可能反复亏损",
                    "failure_conditions": ["趋势失效"],
                },
            },
        },
    }
    scan = {
        "verified": True,
        "decision_date": "2026-09-01",
        "strategy_bindings": [
            {
                "strategy_id": identity,
                "strategy_artifact_fingerprint": artifact_fingerprint,
                "order_generation_gate_fingerprint": "sha256:"
                + content_fingerprint(gate),
            }
        ],
    }
    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline."
        "resolve_strategy_order_generation_gate",
        lambda _db, strategy_id, *, as_of_date: (gate, []),
    )
    monkeypatch.setattr(
        DailyStrategyArtifactStore,
        "load_verified_winner_strategy",
        lambda _self, **_: loaded,
    )
    monkeypatch.setattr(
        "server.persistence.research_observations.ResearchObservationsRepository.list",
        lambda _self, **_: [
            {"lifecycle": "active", "publications": [{}], "outcomes": []}
        ],
    )
    return SimpleNamespace(
        db=SimpleNamespace(path=tmp_path / "app.db"),
        scan=scan,
        gate=gate,
        loaded=loaded,
        identity=identity,
    )


@pytest.mark.unit
def test_account_context_uses_exact_frozen_strategy_and_independent_forward_status(
    frozen_strategy_context,
) -> None:
    fixture = frozen_strategy_context
    context = resolve_account_strategy_context(fixture.db, fixture.scan)[
        fixture.identity
    ]

    assert context["entry_conditions"] == "gt(close, rolling_mean(close, 20))"
    assert context["exit_conditions"] == "lt(close, 10)"
    assert context["condition_basis"] == "formula_ast_summary"
    assert context["economic_hypothesis"] == "冻结的趋势假设"
    assert context["risk_impact"] == "震荡时可能反复亏损"
    assert context["failure_conditions"] == ["趋势失效"]
    assert context["strategy_stage"] == "paper_shadow"
    assert context["candidate_id"] == "candidate-1"
    assert context["run_id"] == "research-run-1"
    assert context["saved_backtest_id"] == 17
    assert context["historical_comparison"] is None
    assert context["forward"] == {
        "status": "recorded",
        "observation_count": 1,
        "lifecycles": ["active"],
        "publication_count": 1,
        "outcome_count": 0,
        "list_limit": 100,
        "qualification_assessed": False,
    }
    assert context["read_only"] is True
    assert context["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    "drift",
    ["unverified", "duplicate", "gate", "promotion", "candidate", "run", "strategy"],
)
def test_account_context_rejects_unbound_or_changed_strategy_sources(
    frozen_strategy_context,
    drift,
) -> None:
    fixture = frozen_strategy_context
    if drift == "unverified":
        fixture.scan["verified"] = False
    elif drift == "duplicate":
        fixture.scan["strategy_bindings"] *= 2
    elif drift == "gate":
        fixture.scan["strategy_bindings"][0]["order_generation_gate_fingerprint"] = (
            "sha256:" + "f" * 64
        )
    elif drift == "promotion":
        fixture.gate["promotion"]["daily_strategy_artifact_binding"][
            "operating_constraints"
        ]["strategy_artifact_fingerprint"] = "f" * 64
    elif drift == "candidate":
        fixture.loaded["candidate_id"] = "new-unpublished-candidate"
    elif drift == "run":
        fixture.loaded["run_id"] = "other-run"
    else:
        fixture.loaded["strategy"]["formula_ast"]["entry"]["op"] = "lt"

    assert resolve_account_strategy_context(fixture.db, fixture.scan) == {}


@pytest.mark.unit
def test_account_context_reuses_canonical_candidate_loader_and_missing_forward(
    frozen_strategy_context,
    monkeypatch,
) -> None:
    from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
        DailyStrategyArtifactRejected,
        DailyStrategyArtifactStore,
    )

    fixture = frozen_strategy_context

    def reject_winner(*_, **__):
        raise DailyStrategyArtifactRejected("candidate_is_not_the_daily_winner")

    def unavailable_forward(*_, **__):
        raise sqlite3.OperationalError("observations_unavailable")

    monkeypatch.setattr(
        DailyStrategyArtifactStore, "load_verified_winner_strategy", reject_winner
    )
    monkeypatch.setattr(
        DailyStrategyArtifactStore,
        "require_verified_research_candidate",
        lambda _self, **_: fixture.loaded,
    )
    monkeypatch.setattr(
        "server.persistence.research_observations.ResearchObservationsRepository.list",
        unavailable_forward,
    )
    context = resolve_account_strategy_context(fixture.db, fixture.scan)[
        fixture.identity
    ]
    assert context["forward"] == {
        "status": "unavailable",
        "qualification_assessed": False,
    }
    assert context["saved_backtest_id"] == 17


@pytest.mark.unit
def test_account_context_keeps_frozen_text_and_does_not_invent_backtest_binding(
    frozen_strategy_context,
    monkeypatch,
) -> None:
    fixture = frozen_strategy_context
    fixture.loaded["strategy"].update(
        entry_conditions="冻结的入场条件", exit_conditions="冻结的离场条件"
    )
    fingerprint = content_fingerprint(fixture.loaded["strategy"])
    fixture.loaded["strategy_artifact_fingerprint"] = fingerprint
    fixture.gate["promotion"]["backtest_result_id"] = None
    fixture.gate["promotion"]["daily_strategy_artifact_binding"][
        "operating_constraints"
    ]["strategy_artifact_fingerprint"] = fingerprint
    fixture.scan["strategy_bindings"][0].update(
        strategy_artifact_fingerprint=fingerprint,
        order_generation_gate_fingerprint="sha256:" + content_fingerprint(fixture.gate),
    )
    monkeypatch.setattr(
        "server.persistence.research_observations.ResearchObservationsRepository.list",
        lambda *_a, **_k: pytest.fail(
            "missing backtest must not borrow observation evidence"
        ),
    )
    context = resolve_account_strategy_context(fixture.db, fixture.scan)[
        fixture.identity
    ]
    assert context["condition_basis"] == "frozen_strategy_text"
    assert context["entry_conditions"] == "冻结的入场条件"
    assert context["exit_conditions"] == "冻结的离场条件"
    assert context["saved_backtest_id"] is None
    assert context["historical_comparison"] is None
    assert context["forward"] == {
        "status": "unavailable",
        "qualification_assessed": False,
    }


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize("match", ["unique", "ambiguous", "opposite_side", "unbound"])
def test_manual_action_context_requires_unique_bound_actual_signal(
    frozen_strategy_context,
    match,
) -> None:
    fixture = frozen_strategy_context
    contexts = resolve_account_strategy_context(fixture.db, fixture.scan)
    signal = {
        "strategy_id": fixture.identity,
        "symbol": "600519",
        "direction": "buy",
        "frozen_market_date": "2026-08-31",
        "target_weight": 0.1,
    }
    scan = {
        **deepcopy(fixture.scan),
        "status": "completed",
        "blockers": [],
        "selected_signal_count": 1,
        "signals": [signal],
    }
    if match == "ambiguous":
        scan["signals"].append(dict(signal, strategy_id="ai_formula_shadow:other"))
    elif match == "opposite_side":
        signal["direction"] = "sell"
    elif match == "unbound":
        contexts = {}
    decision, plan = _current_gate_inputs()
    decision["candidates"] = [{"action_id": 7, "symbol": "600519"}]
    plan["order_intents"] = [{"action_id": 7, "symbol": "600519", "side": "buy"}]
    baseline = build_account_action_recommendation(
        decision_payload=decision,
        trading_plan=plan,
        promoted_scan=scan,
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )
    result = build_account_action_recommendation(
        decision_payload=decision,
        trading_plan=plan,
        promoted_scan=scan,
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
        strategy_context=contexts,
    )
    assert result["actions"][0]["strategy_id"] == (
        fixture.identity if match == "unique" else None
    )
    assert result["actions"][0]["frozen_market_date"] == (
        "2026-08-31" if match == "unique" else None
    )
    assert result["status"] == baseline["status"]
    assert result["authorizes_execution"] is baseline["authorizes_execution"] is False
    assert result["reason_codes"] == baseline["reason_codes"]
    assert (
        result["presentation"]["manual_review_status"]
        == baseline["presentation"]["manual_review_status"]
    )


@pytest.mark.unit
def test_signal_projection_keeps_actual_identity_without_borrowing_other_context() -> (
    None
):
    decision, plan = _current_gate_inputs()
    result = build_account_action_recommendation(
        decision_payload=decision,
        trading_plan=plan,
        promoted_scan={
            "verified": True,
            "status": "blocked",
            "blockers": [],
            "strategy_bindings": [],
            "selected_signal_count": 1,
            "signals": [
                {
                    "symbol": "600519",
                    "direction": "buy",
                    "strategy_id": "ai_formula_shadow:real",
                    "frozen_market_date": "2026-08-31",
                }
            ],
        },
        strategy_context={
            "ai_formula_shadow:unpublished": {
                "strategy_id": "ai_formula_shadow:unpublished",
                "strategy_artifact_fingerprint": "a" * 64,
                "read_only": True,
                "authorizes_execution": False,
            }
        },
        current_evidence_blockers=[],
        current_evidence_fingerprint="e" * 64,
    )
    assert result["strategy_context"] == {}
    action = result["presentation"]["actions"][0]
    assert action["strategy_id"] == "ai_formula_shadow:real"
    assert action["frozen_market_date"] == "2026-08-31"


@pytest.fixture
def historical_comparison_rows(frozen_strategy_context):
    """Real readonly repository queries over sanitized persisted research rows."""
    from analytics.dataset_snapshot import backtest_dataset_snapshot_content_id

    fixture = frozen_strategy_context
    dataset_id = "sha256:" + "a" * 64
    snapshot = {
        "schema_version": "karkinos.dataset_snapshot.v1",
        "date_range": {"start": "2020-01-02", "end": "2026-10-16"},
        "immutable_dataset_id": dataset_id,
        "point_in_time_verified": False,
        "row_count": 2,
        "symbol_universe": [{"symbol": "fixture-a"}, {"symbol": "fixture-b"}],
    }
    snapshot["snapshot_id"] = backtest_dataset_snapshot_content_id(snapshot)
    config = {
        "dataset_id": dataset_id,
        "start_date": "2020-01-02",
        "end_date": "2026-10-16",
        "initial_cash": 1000,
        "corporate_action_mode": "price_only",
    }
    provenance = {
        "historical_formula_source_result_id": 17,
        "actual_comparison_baseline_result_id": None,
        "dataset_id": dataset_id,
        "source_files": {"analytics/example.py": "b" * 64},
        "runner_sha256": "c" * 64,
        "candidate_2_frozen_sha256": "d" * 64,
        "frozen_input_sha256": {"frozen-input.json": "e" * 64},
        "historical_pit_claimed": False,
        "scope_is_deployment_admitted": False,
        "independent_final_evaluation": False,
        "authority_effect": "none",
    }
    rows = {
        17: {
            "id": 17,
            "metrics_json": {
                "formula_binding": {
                    "formula_ast": deepcopy(fixture.loaded["strategy"]["formula_ast"])
                }
            },
            "config_json": "{}",
        }
    }
    for result_id, role, net_return in ((18, "gen7", 0.2), (19, "candidate2", 0.3)):
        metadata = deepcopy(provenance)
        metadata.update(
            role=role,
            actual_comparison_baseline_result_id=18 if result_id == 19 else None,
        )
        metrics = {
            "historical_comparison": metadata,
            "dataset_snapshot": deepcopy(snapshot),
            "formula_binding": {
                "formula_ast": deepcopy(fixture.loaded["strategy"]["formula_ast"]),
                "dataset_snapshot_id": snapshot["snapshot_id"],
                "cost_model_reference": "sanitized-reviewed-cost-model",
            },
            "annual_return": 0.1 if result_id == 18 else 0.15,
        }
        rows[result_id] = {
            "id": result_id,
            "config_json": deepcopy(config),
            "metrics_json": metrics,
            "initial_cash": 1000,
            "final_equity": 1000 * (1 + net_return),
            "total_return": net_return,
            "sharpe": 0.9 if result_id == 18 else 1.1,
            "max_drawdown": 0.2 if result_id == 18 else 0.15,
            "equity_curve_json": json.dumps([{"equity": 1000 * (1 + net_return)}]),
            "cost_summary_json": "{}",
        }

    def persist():
        with sqlite3.connect(fixture.db.path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY, config_json TEXT, metrics_json TEXT,
                initial_cash REAL, final_equity REAL, total_return REAL,
                sharpe REAL, max_drawdown REAL, equity_curve_json TEXT,
                cost_summary_json TEXT)""")
            if (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='backtest_result_invalidations'"
                ).fetchone()
                is None
            ):
                for statement in V25_BACKTEST_INVALIDATIONS:
                    conn.execute(statement)
            conn.execute("DELETE FROM backtest_results")
            columns = (
                "id",
                "config_json",
                "metrics_json",
                "initial_cash",
                "final_equity",
                "total_return",
                "sharpe",
                "max_drawdown",
                "equity_curve_json",
                "cost_summary_json",
            )
            for row in rows.values():
                conn.execute(
                    f"INSERT INTO backtest_results ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [
                        json.dumps(row[name])
                        if name in {"config_json", "metrics_json"}
                        and isinstance(row.get(name), dict)
                        else row.get(name)
                        for name in columns
                    ],
                )

    return SimpleNamespace(context=fixture, rows=rows, persist=persist)


@pytest.mark.unit
def test_account_context_reads_bound_complete_research_pair_without_mutations(
    historical_comparison_rows,
):
    fixture = historical_comparison_rows
    fixture.persist()
    before = fixture.context.db.path.read_bytes()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    comparison = context["historical_comparison"]
    assert comparison["baseline"]["result_id"] == 18
    assert comparison["candidate"]["result_id"] == 19
    assert comparison["baseline"]["total_return"] == 0.2
    assert comparison["candidate"]["annual_return"] == 0.15
    assert comparison["start_date"] == "2020-01-02"
    assert comparison["end_date"] == "2026-10-16"
    assert comparison["instrument_count"] == 2
    assert comparison["bar_row_count"] == 2
    assert comparison["point_in_time_verified"] is False
    assert comparison["independent_final_evaluation"] is False
    assert comparison["authority_effect"] == "none"
    assert "source_files" not in comparison
    assert context["saved_backtest_id"] == 17
    assert context["forward"]["qualification_assessed"] is False
    assert context["authorizes_execution"] is False
    assert fixture.context.db.path.read_bytes() == before


@pytest.mark.unit
@pytest.mark.parametrize(
    "drift",
    [
        "missing_source",
        "missing_baseline",
        "wrong_source",
        "wrong_role",
        "wrong_baseline",
        "dataset",
        "snapshot",
        "source_files",
        "runner_sha256",
        "frozen_input_sha256",
        "candidate_2_frozen_sha256",
        "date_range",
        "cash",
        "cost_model",
        "formula",
        "mode",
        "authority",
        "final_evaluation",
        "pit_claim",
        "malformed_json",
    ],
)
def test_account_context_inconsistent_pair_only_hides_comparison(
    historical_comparison_rows, drift
):
    fixture = historical_comparison_rows
    candidate = fixture.rows[19]
    metrics = candidate["metrics_json"]
    provenance = metrics["historical_comparison"]
    if drift == "missing_source":
        del fixture.rows[17]
    elif drift == "missing_baseline":
        del fixture.rows[18]
    elif drift == "wrong_source":
        provenance["historical_formula_source_result_id"] = 999
    elif drift == "wrong_role":
        provenance["role"] = "comparator"
    elif drift == "wrong_baseline":
        provenance["actual_comparison_baseline_result_id"] = 17
    elif drift == "dataset":
        provenance["dataset_id"] = "sha256:" + "f" * 64
    elif drift == "snapshot":
        metrics["dataset_snapshot"]["row_count"] += 1
    elif drift in {"source_files", "frozen_input_sha256"}:
        provenance[drift] = {"different-input": "f" * 64}
    elif drift in {"runner_sha256", "candidate_2_frozen_sha256"}:
        provenance[drift] = "f" * 64
    elif drift == "date_range":
        candidate["config_json"]["start_date"] = "2026-01-05"
    elif drift == "cash":
        candidate["config_json"]["initial_cash"] = 500
    elif drift == "cost_model":
        metrics["formula_binding"]["cost_model_reference"] = "another-cost-model"
    elif drift == "formula":
        fixture.rows[18]["metrics_json"]["formula_binding"]["formula_ast"] = {
            "entry": "other"
        }
    elif drift == "mode":
        candidate["config_json"]["corporate_action_mode"] = (
            "reported_distributions_gross"
        )
    elif drift == "authority":
        provenance["authority_effect"] = "promote"
    elif drift == "final_evaluation":
        provenance["independent_final_evaluation"] = True
    elif drift == "pit_claim":
        provenance["historical_pit_claimed"] = True
    else:
        candidate["metrics_json"] = "not-json"
    fixture.persist()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    assert context["historical_comparison"] is None
    assert context["saved_backtest_id"] == 17
    assert context["forward"]["status"] == "recorded"
    assert context["read_only"] is True
    assert context["authorizes_execution"] is False


@pytest.mark.unit
def test_account_comparison_pairs_by_saved_identity_not_returns(
    historical_comparison_rows,
):
    fixture = historical_comparison_rows
    newer_baseline = deepcopy(fixture.rows[18])
    newer_baseline["id"] = 20
    fixture.rows[20] = newer_baseline  # No candidate references this partial run.
    fixture.rows[19]["total_return"] = -0.1
    fixture.rows[19]["final_equity"] = 900
    fixture.rows[19]["equity_curve_json"] = '[{"equity":900}]'
    fixture.persist()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    assert context["historical_comparison"]["baseline"]["result_id"] == 18
    assert context["historical_comparison"]["candidate"]["total_return"] == -0.1


def _bind_comparison_context(fixture, result_id):
    """Bind the existing frozen artifact fixture to its exact saved result."""
    context = fixture.context
    context.gate["promotion"]["backtest_result_id"] = result_id
    context.loaded["strategy"]["formula_ast"] = deepcopy(
        fixture.rows[result_id]["metrics_json"]["formula_binding"]["formula_ast"]
    )
    fingerprint = content_fingerprint(context.loaded["strategy"])
    context.loaded["strategy_artifact_fingerprint"] = fingerprint
    context.gate["promotion"]["daily_strategy_artifact_binding"][
        "operating_constraints"
    ]["strategy_artifact_fingerprint"] = fingerprint
    binding = context.scan["strategy_bindings"][0]
    binding["strategy_artifact_fingerprint"] = fingerprint
    binding["order_generation_gate_fingerprint"] = "sha256:" + content_fingerprint(
        context.gate
    )


@pytest.mark.unit
@pytest.mark.parametrize("anchor_id", [18, 19])
def test_account_comparison_accepts_exact_new_baseline_or_candidate_context(
    historical_comparison_rows, anchor_id
):
    fixture = historical_comparison_rows
    candidate_ast = fixture.rows[19]["metrics_json"]["formula_binding"]["formula_ast"]
    candidate_ast["entry"]["right"]["window"] = 40
    assert (
        candidate_ast
        != fixture.rows[18]["metrics_json"]["formula_binding"]["formula_ast"]
    )
    _bind_comparison_context(fixture, anchor_id)
    fixture.persist()
    before = fixture.context.db.path.read_bytes()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    pair = context["historical_comparison"]
    assert pair["baseline"]["result_id"] == 18
    assert pair["candidate"]["result_id"] == 19
    assert context["saved_backtest_id"] == anchor_id
    assert context["forward"]["qualification_assessed"] is False
    assert context["read_only"] is True and context["authorizes_execution"] is False
    assert fixture.context.db.path.read_bytes() == before


@pytest.mark.unit
@pytest.mark.parametrize("anchor_id", [18, 19])
def test_account_comparison_cannot_substitute_newer_same_family_pair(
    historical_comparison_rows, anchor_id
):
    fixture = historical_comparison_rows
    for result_id, original_id in ((20, 18), (21, 19)):
        row = deepcopy(fixture.rows[original_id])
        row["id"] = result_id
        if result_id == 21:
            row["metrics_json"]["historical_comparison"][
                "actual_comparison_baseline_result_id"
            ] = 20
        fixture.rows[result_id] = row
    _bind_comparison_context(fixture, anchor_id)
    fixture.persist()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    assert context["historical_comparison"]["baseline"]["result_id"] == 18
    assert context["historical_comparison"]["candidate"]["result_id"] == 19


@pytest.mark.unit
@pytest.mark.parametrize("anchor_id", [18, 19])
def test_account_comparison_does_not_borrow_family_pair_when_exact_pair_missing(
    historical_comparison_rows, anchor_id
):
    fixture = historical_comparison_rows
    for result_id, original_id in ((20, 18), (21, 19)):
        row = deepcopy(fixture.rows[original_id])
        row["id"] = result_id
        if result_id == 21:
            row["metrics_json"]["historical_comparison"][
                "actual_comparison_baseline_result_id"
            ] = 20
        fixture.rows[result_id] = row
    _bind_comparison_context(fixture, anchor_id)
    del fixture.rows[19 if anchor_id == 18 else 18]
    fixture.persist()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    assert context["historical_comparison"] is None
    assert context["saved_backtest_id"] == anchor_id
    assert context["forward"]["status"] == "recorded"
    assert context["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.parametrize("anchor_id", [18, 19])
@pytest.mark.parametrize(
    "drift",
    [
        "missing_source",
        "missing_ancestor",
        "wrong_ancestor",
        "self_ancestor",
        "nonpositive_ancestor",
        "string_ancestor",
        "wrong_role",
        "wrong_formula",
    ],
)
def test_account_comparison_rejects_broken_exact_anchor_ancestry_or_identity(
    historical_comparison_rows, anchor_id, drift
):
    fixture = historical_comparison_rows
    _bind_comparison_context(fixture, anchor_id)
    metrics = fixture.rows[anchor_id]["metrics_json"]
    provenance = metrics["historical_comparison"]
    if drift == "missing_source":
        del fixture.rows[17]
    elif drift == "missing_ancestor":
        del provenance["historical_formula_source_result_id"]
    elif drift == "wrong_ancestor":
        fixture.rows[999] = {"id": 999, "metrics_json": "{}", "config_json": "{}"}
        provenance["historical_formula_source_result_id"] = 999
    elif drift == "self_ancestor":
        for result_id in (18, 19):
            fixture.rows[result_id]["metrics_json"]["historical_comparison"][
                "historical_formula_source_result_id"
            ] = anchor_id
    elif drift == "nonpositive_ancestor":
        provenance["historical_formula_source_result_id"] = 0
    elif drift == "string_ancestor":
        provenance["historical_formula_source_result_id"] = "17"
    elif drift == "wrong_role":
        provenance["role"] = "comparator"
    else:
        metrics["formula_binding"]["formula_ast"] = {"entry": "other"}
    fixture.persist()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    assert context["historical_comparison"] is None
    assert context["saved_backtest_id"] == anchor_id
    assert context["forward"]["qualification_assessed"] is False
    assert context["read_only"] is True and context["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.parametrize("anchor_id", [17, 18, 19])
@pytest.mark.parametrize(
    "drift",
    [
        "baseline_formula",
        "missing_seed_binding",
        "missing_seed_formula",
        "empty_seed_formula",
        "nonmapping_seed_formula",
    ],
)
def test_account_comparison_requires_baseline_to_match_persisted_seed_ast(
    historical_comparison_rows, anchor_id, drift
):
    fixture = historical_comparison_rows
    fixture.rows[19]["metrics_json"]["formula_binding"]["formula_ast"]["entry"][
        "right"
    ]["window"] = 40
    if drift == "baseline_formula":
        fixture.rows[18]["metrics_json"]["formula_binding"]["formula_ast"]["entry"][
            "right"
        ]["window"] = 60
    # The N/C context still matches its exact saved row, so only the original
    # persisted Gen7 source can establish whether N remains a Gen7 comparison.
    _bind_comparison_context(fixture, anchor_id)
    source_metrics = fixture.rows[17]["metrics_json"]
    if drift == "missing_seed_binding":
        del source_metrics["formula_binding"]
    elif drift == "missing_seed_formula":
        del source_metrics["formula_binding"]["formula_ast"]
    elif drift == "empty_seed_formula":
        source_metrics["formula_binding"]["formula_ast"] = {}
    elif drift == "nonmapping_seed_formula":
        source_metrics["formula_binding"]["formula_ast"] = ["unverified"]
    fixture.persist()
    before = fixture.context.db.path.read_bytes()
    context = resolve_account_strategy_context(
        fixture.context.db, fixture.context.scan
    )[fixture.context.identity]
    assert context["historical_comparison"] is None
    assert context["saved_backtest_id"] == anchor_id
    assert context["forward"]["qualification_assessed"] is False
    assert context["read_only"] is True and context["authorizes_execution"] is False
    assert fixture.context.db.path.read_bytes() == before
