"""Stateful strategy promotion pipeline."""

from __future__ import annotations

import json
from typing import Any

STRATEGY_PROMOTION_SCHEMA_VERSION = "karkinos.strategy_promotion_pipeline.v1"


class StrategyPromotionPipeline:
    """Persist strategy promotion stage decisions with safety gates."""

    def __init__(self, *, db: Any) -> None:
        self._db = db

    def evaluate_readiness(
        self,
        readiness: dict[str, Any],
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        strategy_id = _strategy_id(readiness)
        missing = _missing_requirements(readiness)
        promotable = _is_promotable(readiness)
        state = self._db.upsert_strategy_promotion_state_sync(
            strategy_id=strategy_id,
            stage="research",
            gate_status="paper_shadow_ready" if promotable else "blocked",
            live_like_enabled=False,
            missing_requirements=missing,
            backtest_result_id=_int_or_none(readiness.get("backtest_result_id")),
            payload={
                "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
                "readiness": readiness,
            },
        )
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="readiness_evaluated",
            from_stage=None,
            to_stage="research",
            actor=actor,
            payload={"missing_requirements": missing, "is_promotable": promotable},
        )
        return self._normalize_state(state)

    def request_promotion(
        self,
        strategy_id: str,
        *,
        target_stage: str,
        readiness: dict[str, Any],
        actor: str | None = None,
    ) -> dict[str, Any]:
        target_stage = str(target_stage)
        if target_stage == "live_like":
            self._record_rejected_live_like(strategy_id, actor=actor)
            raise ValueError("live-like promotion is disabled by default")
        if target_stage != "paper_shadow":
            raise ValueError(f"unsupported promotion target: {target_stage}")
        if strategy_id != _strategy_id(readiness):
            raise ValueError("readiness strategy_id does not match promotion target")
        missing = _missing_requirements(readiness)
        if missing or not _is_promotable(readiness):
            raise ValueError(
                "missing readiness requirements: " + ", ".join(missing or ["unknown"])
            )
        current = self._db.get_strategy_promotion_state_sync(strategy_id)
        from_stage = str(current["stage"]) if current else "research"
        state = self._db.upsert_strategy_promotion_state_sync(
            strategy_id=strategy_id,
            stage="paper_shadow",
            gate_status="paper_shadow_enabled",
            live_like_enabled=False,
            missing_requirements=[],
            backtest_result_id=_int_or_none(readiness.get("backtest_result_id")),
            payload={
                "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
                "readiness": readiness,
                "live_like_enabled": False,
            },
        )
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="promoted_to_paper_shadow",
            from_stage=from_stage,
            to_stage="paper_shadow",
            actor=actor,
            payload={
                "manual_confirmation_required": True,
                "live_like_enabled": False,
            },
        )
        return self._normalize_state(state)

    def list_states(self) -> list[dict[str, Any]]:
        return [
            self._normalize_state(row)
            for row in self._db.list_strategy_promotion_states_sync()
        ]

    def list_events(self, strategy_id: str) -> list[dict[str, Any]]:
        return self._db.list_strategy_promotion_events_sync(strategy_id)

    def _record_rejected_live_like(
        self,
        strategy_id: str,
        *,
        actor: str | None,
    ) -> None:
        self._db.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type="live_like_promotion_rejected",
            from_stage=None,
            to_stage="live_like_blocked",
            actor=actor,
            payload={
                "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
                "reason": "live-like promotion is disabled by default",
            },
        )

    def _normalize_state(self, row: dict[str, Any]) -> dict[str, Any]:
        missing = _json_list(row.get("missing_requirements_json"))
        payload = _json_object(row.get("payload_json"))
        return {
            **row,
            "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
            "live_like_enabled": bool(row.get("live_like_enabled")),
            "missing_requirements": missing,
            "payload": payload,
        }


def _strategy_id(readiness: dict[str, Any]) -> str:
    strategy_id = str(readiness.get("strategy_id") or "").strip()
    if not strategy_id:
        raise ValueError("readiness strategy_id is required")
    return strategy_id


def _missing_requirements(readiness: dict[str, Any]) -> list[str]:
    value = readiness.get("missing_requirements") or []
    return [str(item) for item in value]


def _is_promotable(readiness: dict[str, Any]) -> bool:
    return bool(readiness.get("is_promotable")) and not _missing_requirements(readiness)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in {None, ""}:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in {None, ""}:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
