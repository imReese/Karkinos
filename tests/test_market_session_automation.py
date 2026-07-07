from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from server.db import AppDatabase
import server.services.market_session_automation as market_session_automation
from server.services.market_session_automation import MarketSessionAutomationService
from server.services.trading_controls import TradingControlState


def _service(
    tmp_path,
) -> tuple[AppDatabase, TradingControlState, MarketSessionAutomationService]:
    db = AppDatabase(tmp_path / "market-session.db")
    db.init_sync()
    controls = TradingControlState(db=db)
    return (
        db,
        controls,
        MarketSessionAutomationService(
            db=db,
            trading_controls=controls,
        ),
    )


def _trading_plan() -> dict:
    return {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T09:35:00+08:00",
        "order_intents": [
            {
                "intent_id": "intent-1",
                "strategy_id": "dual_ma",
                "symbol": "600519",
                "side": "buy",
                "asset_class": "stock",
                "estimated_quantity": 100,
                "estimated_price": 1688.0,
            }
        ],
    }


def test_market_session_run_skips_outside_trading_session(tmp_path) -> None:
    db, _, service = _service(tmp_path)

    result = service.run_session(
        trading_plan=_trading_plan(),
        now=datetime(2026, 7, 4, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["status"] == "skipped_non_trading_session"
    assert result["broker_submission_enabled"] is False
    assert result["does_not_submit_broker_order"] is True
    assert db.list_automation_runs_sync(run_type="market_session")[0]["status"] == (
        "skipped_non_trading_session"
    )


def test_market_session_run_blocks_when_kill_switch_is_enabled(tmp_path) -> None:
    db, controls, service = _service(tmp_path)
    controls.set_kill_switch(True, "operator pause")

    result = service.run_session(
        trading_plan=_trading_plan(),
        now=datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["status"] == "blocked_by_kill_switch"
    assert result["kill_switch_enabled"] is True
    assert db.list_automation_runs_sync(run_type="market_session")[0]["status"] == (
        "blocked_by_kill_switch"
    )


def test_market_session_run_triggers_paper_shadow_in_trading_session(tmp_path) -> None:
    db, _, service = _service(tmp_path)

    result = service.run_session(
        trading_plan=_trading_plan(),
        now=datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["status"] == "paper_shadow_completed"
    assert result["paper_shadow_run"]["status"] == "within_expectations"
    assert result["does_not_submit_broker_order"] is True
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is not None


def test_market_session_run_records_scheduler_input_snapshot_and_retry_state(
    tmp_path,
) -> None:
    db, _, service = _service(tmp_path)
    trading_plan = _trading_plan()
    run_at = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = service.run_session(trading_plan=trading_plan, now=run_at)
    second = service.run_session(trading_plan=trading_plan, now=run_at)

    assert first["run_id"] == second["run_id"]
    runs = db.list_automation_runs_sync(run_type="market_session")
    assert len(runs) == 1
    payload = json.loads(runs[0]["payload_json"])
    assert payload["input_snapshot"] == {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-07-02",
        "generated_at": "2026-07-02T09:35:00+08:00",
        "order_intent_count": 1,
        "manual_ready_count": 0,
        "blocked_count": 0,
    }
    assert len(payload["input_fingerprint"]) == 64
    assert payload["idempotency_key"] == (
        f"market_session:2026-07-02:{payload['input_fingerprint'][:12]}"
    )
    assert payload["retry_state"] == {
        "attempt": 1,
        "max_attempts": 1,
        "retryable": False,
    }
    assert payload["trigger"] == "market_session"
    assert payload["broker_submission_enabled"] is False
    assert payload["does_not_submit_broker_order"] is True


def test_market_session_run_is_idempotent_for_same_plan_fingerprint_across_times(
    tmp_path,
) -> None:
    db, _, service = _service(tmp_path)
    trading_plan = _trading_plan()

    first = service.run_session(
        trading_plan=trading_plan,
        now=datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    second = service.run_session(
        trading_plan=trading_plan,
        now=datetime(2026, 7, 2, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert first["run_id"] == second["run_id"]
    runs = db.list_automation_runs_sync(run_type="market_session")
    assert len(runs) == 1
    payload = json.loads(runs[0]["payload_json"])
    assert runs[0]["started_at"] == "2026-07-02T10:05:00+08:00"
    assert payload["session_time"] == "2026-07-02T10:05:00+08:00"
    assert runs[0]["run_id"] == payload["idempotency_key"]


def test_market_session_run_creates_new_run_when_plan_fingerprint_changes(
    tmp_path,
) -> None:
    db, _, service = _service(tmp_path)
    base_plan = _trading_plan()
    changed_plan = {
        **base_plan,
        "order_intents": [
            {
                **base_plan["order_intents"][0],
                "estimated_quantity": 200,
            }
        ],
    }

    first = service.run_session(
        trading_plan=base_plan,
        now=datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    second = service.run_session(
        trading_plan=changed_plan,
        now=datetime(2026, 7, 2, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert first["run_id"] != second["run_id"]
    runs = db.list_automation_runs_sync(run_type="market_session")
    assert len(runs) == 2
    payloads = [json.loads(run["payload_json"]) for run in runs]
    assert {
        payload["input_snapshot"]["order_intent_count"] for payload in payloads
    } == {1}
    assert len({payload["input_fingerprint"] for payload in payloads}) == 2
    assert {run["run_id"] for run in runs} == {
        payload["idempotency_key"] for payload in payloads
    }


def test_market_session_run_records_paper_shadow_failure_as_automation_run(
    tmp_path,
    monkeypatch,
) -> None:
    db, _, service = _service(tmp_path)

    def fail_paper_shadow(**_: object) -> dict:
        raise RuntimeError("simulated paper shadow failure")

    monkeypatch.setattr(
        market_session_automation,
        "run_paper_shadow_from_trading_plan",
        fail_paper_shadow,
    )

    result = service.run_session(
        trading_plan=_trading_plan(),
        now=datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["status"] == "paper_shadow_failed"
    assert result["paper_shadow_run"] is None
    assert db.latest_paper_shadow_run_sync(plan_date="2026-07-02") is None
    run = db.list_automation_runs_sync(run_type="market_session")[0]
    assert run["status"] == "paper_shadow_failed"
    payload = json.loads(run["payload_json"])
    assert payload["error"] == {
        "type": "RuntimeError",
        "message": "simulated paper shadow failure",
    }
    assert payload["retry_state"] == {
        "attempt": 1,
        "max_attempts": 1,
        "retryable": True,
    }
    assert payload["broker_submission_enabled"] is False
    assert payload["does_not_submit_broker_order"] is True


def test_market_session_run_increments_retry_attempt_for_same_failed_run(
    tmp_path,
    monkeypatch,
) -> None:
    db, _, service = _service(tmp_path)

    def fail_paper_shadow(**_: object) -> dict:
        raise RuntimeError("simulated paper shadow failure")

    monkeypatch.setattr(
        market_session_automation,
        "run_paper_shadow_from_trading_plan",
        fail_paper_shadow,
    )

    first = service.run_session(
        trading_plan=_trading_plan(),
        now=datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    second = service.run_session(
        trading_plan=_trading_plan(),
        now=datetime(2026, 7, 2, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert first["run_id"] == second["run_id"]
    runs = db.list_automation_runs_sync(run_type="market_session")
    assert len(runs) == 1
    payload = json.loads(runs[0]["payload_json"])
    assert payload["retry_state"] == {
        "attempt": 2,
        "max_attempts": 2,
        "retryable": True,
        "previous_attempts": 1,
    }
    assert payload["error"]["message"] == "simulated paper shadow failure"
    assert payload["does_not_submit_broker_order"] is True
