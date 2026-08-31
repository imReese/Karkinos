from __future__ import annotations

import io
import json

from server import daily_candidate_production_readiness_cli as readiness_cli
from server.ai_runtime.contracts import content_fingerprint

main = readiness_cli.main


def test_live_readiness_cli_reads_only_expected_loopback_endpoints() -> None:
    urls = []
    execution_evidence = {
        "schema_version": ("karkinos.daily_candidate_execution_evidence_summary.v1"),
        "status": "not_required",
        "current_execution_closure_fingerprint": "c" * 64,
        "population_scope": "all_current_non_paper_shadow_oms_orders",
        "production_order_count": 0,
        "clear_order_count": 0,
        "reconciled_actual_order_count": 0,
        "reconciled_no_fill_order_count": 0,
        "comparison_coverage_complete": True,
        "blockers": [],
        "actual_orders_attributed_to_trial": False,
        "actual_orders_count_toward_simulated_trial_threshold": False,
        "persisted_evidence_only": True,
        "provider_contact_performed": False,
        "manual_review_required": False,
        "authorizes_execution": False,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_change_capital_authority": True,
    }
    execution_evidence["evidence_fingerprint"] = content_fingerprint(execution_evidence)

    def fetch(url: str, timeout: float) -> dict:
        urls.append((url, timeout))
        if url.endswith("/api/automation/cockpit"):
            return {
                "schema_version": "karkinos.automation_cockpit.v4",
                "broker_submission_enabled": False,
                "daily_candidate_financial_preflight": {
                    "schema_version": (
                        "karkinos.daily_candidate_financial_preflight.v1"
                    ),
                    "run_date": "2026-08-21",
                    "financial_gate_status": "blocked",
                    "operational_gate_status": "blocked",
                    "eligible_to_start_manual_attempt": False,
                    "eligible_for_background_attempt": False,
                    "financial_blockers": ["account_truth_snapshot_stale"],
                    "no_action_reasons": ["account_truth_snapshot_stale"],
                    "next_safe_action": "resolve_named_financial_blockers",
                    "preflight_fingerprint": "a" * 64,
                    "operator_checklist": [
                        {
                            "step": 1,
                            "gate": "account_truth",
                            "action": "complete_current_account_truth_evidence_review",
                            "completion_mode": "human_review",
                            "blockers": ["account_truth_snapshot_stale"],
                            "evidence_contract_version": (
                                "karkinos.daily_candidate_operator_evidence.v1"
                            ),
                            "required_evidence": [
                                "current_cash_snapshot_with_aware_timestamp_and_cash_balance"
                            ],
                            "completion_criteria": [
                                "cash_and_position_snapshots_share_current_shanghai_date"
                            ],
                            "accepted_evidence_authority": (
                                "canonical_persisted_evidence_only"
                            ),
                            "owner_attestation_is_financial_fact": False,
                            "private_xls_rows_required": False,
                            "private_account_identifiers_required": False,
                            "automatic_action_performed": False,
                            "authorizes_execution": False,
                            "changes_capital_authority": False,
                        }
                    ],
                    "provider_contact_performed": False,
                    "database_writes_performed": False,
                    "broker_submission_enabled": False,
                    "authorizes_execution": False,
                    "changes_capital_authority": False,
                },
                "daily_candidate_runtime": {
                    "schema_version": "karkinos.daily_candidate_runtime_status.v1",
                    "background_monitor_running": True,
                    "schedule_status": "waiting_for_decision_window",
                    "operational_blockers": [],
                    "provider_contact_performed": False,
                    "database_writes_performed": False,
                    "broker_submission_enabled": False,
                    "authorizes_execution": False,
                    "changes_capital_authority": False,
                },
                "daily_candidate_trial": {
                    "schema_version": "karkinos.daily_candidate_trial.v2",
                    "qualifying_trading_day_count": 0,
                    "target_qualifying_trading_days": 20,
                    "simulated_order_count": 0,
                    "target_simulated_orders": 50,
                    "remaining_trading_days": 20,
                    "remaining_simulated_orders": 50,
                    "eligible_for_human_go_no_go_review": False,
                    "latest_review": None,
                    "current_execution_evidence": execution_evidence,
                    "background_schedule": {
                        "schema_version": (
                            "karkinos.daily_candidate_background_schedule.v3"
                        ),
                        "run_date": "2026-08-21",
                        "next_reviewed_window": {
                            "schema_version": (
                                "karkinos.daily_candidate_next_reviewed_window.v1"
                            ),
                            "status": "available",
                            "market_date": "2026-08-22",
                            "window_start": "2026-08-22T09:35:00+08:00",
                            "window_end": "2026-08-22T09:45:00+08:00",
                            "is_current_market_date": False,
                            "official_calendar_verified": True,
                            "blockers": [],
                            "provider_contact_performed": False,
                            "database_writes_performed": False,
                            "permits_retry_or_backfill": False,
                            "changes_attempt_eligibility": False,
                            "broker_submission_enabled": False,
                            "authorizes_execution": False,
                            "changes_capital_authority": False,
                        },
                    },
                    "blockers": ["qualifying_trading_days_insufficient"],
                    "run_scan_truncated": False,
                    "trial_fingerprint": "b" * 64,
                    "broker_submission_enabled": False,
                    "authorizes_execution": False,
                    "changes_capital_authority": False,
                },
            }
        return {
            "schema_version": "karkinos.ai.shadow_research_automation.v1",
            "policy": {
                "schema_version": "karkinos.ai.shadow_research_policy.v4",
                "enabled": False,
                "max_candidates_per_run": 1,
                "max_provider_calls_per_market_date": 2,
                "daily_token_budget": 451000,
                "token_budget_mode": "legacy_bounded_daily",
                "authorization": "",
                "research_capital_mode": "account_bound",
                "require_complete_account_evidence": True,
                "promotion_requires_complete_account_evidence": True,
            },
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
        }

    output = io.StringIO()
    exit_code = main(
        ["--base-url", "http://localhost:8000"],
        fetch_json=fetch,
        stdout=output,
    )
    payload = json.loads(output.getvalue())

    assert exit_code == 2
    assert urls == [
        ("http://localhost:8000/api/automation/cockpit", 30.0),
        (
            "http://localhost:8000/api/ai/strategy-research/shadow-automation/readiness",
            30.0,
        ),
    ]
    assert payload["status"] == "no_action_not_production_ready"
    assert payload["daily_operation"]["blockers"] == ["account_truth_snapshot_stale"]
    assert payload["daily_operation"]["first_blocking_gate"] == "account_truth"
    assert payload["daily_operation"]["first_safe_action"] == (
        "complete_current_account_truth_evidence_review"
    )
    assert payload["daily_operation"]["next_reviewed_window"]["market_date"] == (
        "2026-08-22"
    )
    assert payload["daily_operation"]["operator_checklist"][0]["blocker_summary"] == [
        {
            "code": "account_truth_snapshot_stale",
            "occurrence_count": 1,
            "affected_candidate_count": 0,
        }
    ]


def test_live_readiness_cli_rejects_external_hosts_without_contact() -> None:
    called = False

    def fetch(_url: str, _timeout: float) -> dict:
        nonlocal called
        called = True
        return {}

    output = io.StringIO()
    exit_code = main(
        ["--base-url", "https://example.com:443"],
        fetch_json=fetch,
        stdout=output,
    )
    payload = json.loads(output.getvalue())

    assert exit_code == 2
    assert called is False
    assert payload["source_contract_blockers"] == ["local_karkinos_service_unreachable"]
    assert payload["provider_contact_performed"] is False


def test_live_readiness_fetch_disables_environment_proxies(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b'{"status":"ok"}'

    class Opener:
        def open(self, request, *, timeout: float):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response()

    def build_opener(handler):
        captured["handler"] = handler
        return Opener()

    monkeypatch.setattr(readiness_cli, "build_opener", build_opener)

    assert readiness_cli._fetch_json("http://127.0.0.1:8000/api/health", 10) == {
        "status": "ok"
    }
    assert captured["handler"].proxies == {}
    assert captured["request"].full_url == "http://127.0.0.1:8000/api/health"
    assert captured["timeout"] == 10
