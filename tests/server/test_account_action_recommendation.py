from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.projections.account_action_recommendation import (
    build_account_action_recommendation,
    resolve_latest_verified_promoted_strategy_scan,
)
from server.routes.decision import _current_shadow_qualification_evidence
from server.services.daily_decision_policy_gates import (
    current_account_action_evidence_blockers,
)
from server.services.promoted_strategy_universe_scan import (
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
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def list_automation_runs_sync(self, **_: object) -> list[dict]:
        return self.rows


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
        "server.composition.ai_application_services."
        "build_shadow_research_read_service",
        lambda _state: SimpleNamespace(status=lambda: status),
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
        "server.composition.ai_application_services."
        "build_shadow_research_read_service",
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
