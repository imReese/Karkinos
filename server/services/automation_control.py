"""Controlled automation policy and run-state decisions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

DEFAULT_AUTOMATION_POLICY_ID = "default"
AUTOMATION_POLICY_SCHEMA_VERSION = "karkinos.automation_policy.v1"
AUTOMATION_RUN_SCHEMA_VERSION = "karkinos.automation_run.v1"
SAFE_EXECUTION_MODES = ("manual_confirmation", "paper_shadow", "dry_run")


class AutomationControlService:
    """Read and enforce Karkinos automation safety controls."""

    def __init__(self, *, db: Any, trading_controls: Any | None) -> None:
        self._db = db
        self._trading_controls = trading_controls

    def get_default_policy(self) -> dict[str, Any]:
        stored = self._db.get_automation_policy_sync(DEFAULT_AUTOMATION_POLICY_ID)
        if stored is not None:
            return self._normalize_policy(stored)
        return self._default_policy()

    def update_default_policy(
        self,
        patch: dict[str, Any],
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        policy = {
            **self.get_default_policy(),
            **{key: value for key, value in patch.items() if value is not None},
        }
        policy = self._normalize_policy(policy)
        self._validate_safe_policy(policy)
        return self._db.upsert_automation_policy_sync(
            policy_id=DEFAULT_AUTOMATION_POLICY_ID,
            payload=policy,
            updated_by=updated_by,
        )

    def get_status(self) -> dict[str, Any]:
        policy = self.get_default_policy()
        kill_switch = self._kill_switch_snapshot()
        kill_switch_enabled = bool(
            getattr(kill_switch, "kill_switch_enabled", False)
            if kill_switch is not None
            else False
        )
        latest_runs = self._db.list_automation_runs_sync(limit=10)
        automation_ready = (
            not kill_switch_enabled and not policy["broker_submission_enabled"]
        )
        next_action = (
            "resolve_kill_switch" if kill_switch_enabled else "paper_shadow_available"
        )
        return {
            "schema_version": "karkinos.automation_status.v1",
            "policy_id": policy["policy_id"],
            "default_execution_mode": policy["default_execution_mode"],
            "manual_confirmation_required": policy["manual_confirmation_required"],
            "broker_submission_enabled": policy["broker_submission_enabled"],
            "allowed_execution_modes": policy["allowed_execution_modes"],
            "kill_switch_enabled": kill_switch_enabled,
            "kill_switch_reason": getattr(kill_switch, "reason", "")
            if kill_switch is not None
            else "",
            "automation_ready": automation_ready,
            "next_action": next_action,
            "latest_runs": latest_runs,
        }

    def record_paper_shadow_run(
        self,
        *,
        run_date: str | None,
        source_ref: str | None,
        paper_shadow_run: dict[str, Any],
    ) -> dict[str, Any]:
        finished_at = datetime.now().isoformat()
        effective_run_date = (
            run_date
            or paper_shadow_run.get("plan_date")
            or date.today().isoformat()
        )
        return self._db.upsert_automation_run_sync(
            {
                "run_id": f"automation:daily-paper-shadow:{effective_run_date}",
                "run_type": "daily_paper_shadow",
                "run_date": effective_run_date,
                "status": str(paper_shadow_run.get("status") or "completed"),
                "execution_mode": "paper_shadow",
                "started_at": paper_shadow_run.get("created_at") or finished_at,
                "finished_at": finished_at,
                "source_ref": source_ref or paper_shadow_run.get("run_id"),
                "payload": {
                    "schema_version": AUTOMATION_RUN_SCHEMA_VERSION,
                    "paper_shadow_run_id": paper_shadow_run.get("run_id"),
                    "paper_shadow_status": paper_shadow_run.get("status"),
                    "does_not_submit_broker_order": True,
                    "does_not_mutate_production_ledger": True,
                },
            }
        )

    def _default_policy(self) -> dict[str, Any]:
        return {
            "schema_version": AUTOMATION_POLICY_SCHEMA_VERSION,
            "policy_id": DEFAULT_AUTOMATION_POLICY_ID,
            "default_execution_mode": "manual_confirmation",
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "allowed_execution_modes": list(SAFE_EXECUTION_MODES),
            "updated_at": "",
            "updated_by": None,
        }

    def _normalize_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        allowed_modes = policy.get("allowed_execution_modes") or SAFE_EXECUTION_MODES
        normalized = {
            **self._default_policy(),
            **policy,
            "policy_id": DEFAULT_AUTOMATION_POLICY_ID,
            "allowed_execution_modes": [str(mode) for mode in allowed_modes],
            "broker_submission_enabled": bool(
                policy.get("broker_submission_enabled", False)
            ),
            "manual_confirmation_required": bool(
                policy.get("manual_confirmation_required", True)
            ),
        }
        default_mode = str(
            normalized.get("default_execution_mode") or "manual_confirmation"
        )
        normalized["default_execution_mode"] = default_mode
        return normalized

    def _validate_safe_policy(self, policy: dict[str, Any]) -> None:
        if policy["broker_submission_enabled"]:
            raise ValueError("broker submission is disabled by default")
        modes = {str(mode).lower() for mode in policy["allowed_execution_modes"]}
        if "live" in modes:
            raise ValueError("live execution mode is disabled by default")
        unknown_modes = modes.difference(SAFE_EXECUTION_MODES)
        if unknown_modes:
            unknown = ", ".join(sorted(unknown_modes))
            raise ValueError(f"unsupported automation execution mode: {unknown}")
        if policy["default_execution_mode"] not in policy["allowed_execution_modes"]:
            raise ValueError("default execution mode must be allowed")
        if not policy["manual_confirmation_required"]:
            raise ValueError("manual confirmation must remain required by default")

    def _kill_switch_snapshot(self) -> Any | None:
        if self._trading_controls is None:
            return None
        snapshot = getattr(self._trading_controls, "snapshot", None)
        return snapshot() if callable(snapshot) else None
