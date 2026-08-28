"""Runtime support seams for AI shadow research orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from core.types import AssetClass
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.provider_call_window import (
    ProviderCallDeferred,
    ProviderCallWindowDecision,
)
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_API_SCHEMA,
    SHADOW_RESEARCH_RUN_TYPE,
    SHADOW_RESEARCH_TIMEZONE,
    ShadowResearchPolicy,
    ShadowResearchRejected,
    shadow_research_json_list,
    shadow_research_json_object,
)
from server.services.reviewed_fee_schedule import ReviewedFeeScheduleRejected

logger = logging.getLogger(__name__)


class AiShadowResearchSupportMixin:
    def _provider_call_window_decision(
        self, *, require_full_batch_runway: bool
    ) -> ProviderCallWindowDecision | None:
        if self._provider_call_window_policy is None:
            return None
        runway = timedelta(
            seconds=(
                self._provider_runway_seconds
                if require_full_batch_runway
                else self._provider_call_runway_seconds
            )
        )
        return self._provider_call_window_policy.evaluate(
            self._now(), minimum_runway=runway
        )

    def _require_provider_call_window(self) -> None:
        decision = self._provider_call_window_decision(require_full_batch_runway=False)
        if decision is not None and not decision.allowed:
            raise ProviderCallDeferred(decision)

    def _provider_call_window_status(self) -> dict[str, Any] | None:
        decision = self._provider_call_window_decision(require_full_batch_runway=True)
        return decision.to_dict() if decision is not None else None

    def _provider_batch_window_admission(
        self,
    ) -> tuple[dict[str, Any] | None, datetime | None]:
        if self._provider_call_window_policy is None:
            return None, None
        observed_at = self._now()
        decision = self._provider_call_window_policy.evaluate(
            observed_at,
            minimum_runway=timedelta(seconds=self._provider_runway_seconds),
        )
        if not decision.allowed:
            return (
                self._record_preflight(
                    status="deferred_for_provider_off_peak",
                    failure_code=str(decision.failure_code),
                    evidence=decision.to_dict(),
                ),
                None,
            )
        return None, self._provider_call_window_policy.eligible_until(observed_at)

    def _batch_deadline_preflight(
        self, deadline_at: datetime | None
    ) -> dict[str, Any] | None:
        if deadline_at is None or self._now() < deadline_at:
            return None
        decision = self._provider_call_window_decision(require_full_batch_runway=True)
        if decision is None:
            return None
        return self._record_preflight(
            status="deferred_for_provider_off_peak",
            failure_code=str(
                decision.failure_code or "shadow_research_batch_deadline_elapsed"
            ),
            evidence={
                **decision.to_dict(),
                "batch_deadline_at": deadline_at.isoformat(),
                "batch_deadline_missed": True,
            },
        )

    def _require_provider_batch_deadline(self, deadline_at: datetime | None) -> None:
        if deadline_at is not None and self._now() >= deadline_at:
            raise ShadowResearchRejected("shadow_research_batch_deadline_elapsed")

    def _provider_window_input_evidence(
        self, deadline_at: datetime | None
    ) -> dict[str, Any]:
        return {
            "provider_call_window_policy": (
                self._provider_call_window_policy.to_dict()
                if self._provider_call_window_policy is not None
                else None
            ),
            "provider_batch_deadline_at": (
                deadline_at.isoformat() if deadline_at is not None else None
            ),
        }

    def _resolve_reviewed_fee_schedule(self, **kwargs: Any) -> Any:
        if self._reviewed_fee_schedule_resolver is None:
            raise ReviewedFeeScheduleRejected("reviewed_fee_schedule_resolver_missing")
        return self._reviewed_fee_schedule_resolver(**kwargs)

    def _build_research_service(self, *, external: bool) -> Any:
        if self._research_service_builder is None:
            raise ShadowResearchRejected("strategy_research_service_builder_missing")
        return self._research_service_builder(external)

    def _require_deepseek_provider(self) -> None:
        """Fail closed before export unless the configured edge is DeepSeek."""
        if self._research_service_builder is not None:
            return
        from server.ai_runtime.provider_connectivity import (
            load_provider_connectivity_settings,
        )

        settings = load_provider_connectivity_settings(self._state.config)
        host = (urlparse(settings.endpoint_origin).hostname or "").casefold()
        if settings.provider_id.strip().casefold() != "deepseek" or not (
            host == "deepseek.com" or host.endswith(".deepseek.com")
        ):
            raise ShadowResearchRejected("deepseek_provider_not_configured")

    def _fail_provider_call(self, call_id: str, failure_code: str) -> None:
        self._store.finish_provider_call(
            call_id,
            status="failed",
            actual_tokens=None,
            failure_code=failure_code,
            now=self._utc_now(),
        )

    def _kill_switch(self) -> dict[str, Any]:
        controls = getattr(self._state, "trading_controls", None)
        snapshot = controls.snapshot() if controls is not None else None
        return {
            "enabled": bool(getattr(snapshot, "kill_switch_enabled", False)),
            "reason": str(getattr(snapshot, "reason", "") or ""),
        }

    def _require_runtime_authorization(self, expected: ShadowResearchPolicy) -> None:
        if self._kill_switch()["enabled"]:
            raise ShadowResearchRejected("blocked_by_kill_switch")
        current = self.get_policy()
        if not current.enabled:
            raise ShadowResearchRejected("shadow_research_policy_paused")
        if content_fingerprint(current.to_dict()) != content_fingerprint(
            expected.to_dict()
        ):
            raise ShadowResearchRejected("shadow_research_policy_changed")

    def _record_preflight(
        self,
        *,
        status: str,
        failure_code: str,
        market_date: str | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_date = (
            market_date
            or self._now().astimezone(SHADOW_RESEARCH_TIMEZONE).date().isoformat()
        )
        now = self._utc_now()
        stable_evidence = {
            key: value
            for key, value in dict(evidence or {}).items()
            if key != "evaluated_at"
        }
        fingerprint = content_fingerprint(
            {
                "market_date": effective_date,
                "status": status,
                "failure_code": failure_code,
                "evidence": stable_evidence,
            }
        )
        row = self._db.upsert_automation_run_sync(
            {
                "run_id": f"automation:ai-shadow-research-preflight:{effective_date}:{fingerprint[:12]}",
                "run_type": SHADOW_RESEARCH_RUN_TYPE,
                "run_date": effective_date,
                "status": status,
                "execution_mode": "research_only",
                "started_at": now,
                "finished_at": now,
                "source_ref": None,
                "payload": {
                    "schema_version": SHADOW_RESEARCH_API_SCHEMA,
                    "failure_code": failure_code,
                    **({"provider_call_window": dict(evidence)} if evidence else {}),
                    "provider_call_performed": False,
                    "automatic_strategy_replacement_enabled": False,
                    "broker_submission_enabled": False,
                    "authority_effect": "none",
                },
            }
        )
        return {
            **self.status(),
            "run_status": status,
            "failure_code": failure_code,
            "preflight_run_id": row["run_id"],
            **({"provider_call_window": dict(evidence)} if evidence else {}),
            **(
                {"next_eligible_at": evidence.get("next_eligible_at")}
                if evidence and evidence.get("next_eligible_at")
                else {}
            ),
        }

    async def _notify(
        self,
        market_date: str,
        candidates: list[Mapping[str, Any]],
        daily_artifacts: Mapping[str, Any] | None,
    ) -> None:
        sender = getattr(getattr(self._state, "notifier", None), "send", None)
        if not callable(sender) or not candidates:
            return
        eligible = sum(
            item.get("recommendation") == "paper_shadow_review" for item in candidates
        )
        selection = (
            daily_artifacts.get("selection")
            if isinstance(daily_artifacts, Mapping)
            and isinstance(daily_artifacts.get("selection"), Mapping)
            else {}
        )
        backup = (
            daily_artifacts.get("backup")
            if isinstance(daily_artifacts, Mapping)
            and isinstance(daily_artifacts.get("backup"), Mapping)
            else {}
        )
        winner = selection.get("winner_candidate_id") or "无新优胜者"
        message = (
            f"DeepSeek 收盘后策略研究已完成（{market_date}）。\n"
            f"已完成串行迭代轮次: {len(candidates)}\n"
            f"建议进入人工 paper/shadow 复核: {eligible}\n"
            f"确定性新候选优胜者: {winner}\n"
            f"策略备份校验: {backup.get('verification_status') or 'missing'}\n"
            "无新优胜者只表示本批次不提出新晋级；当前已人工批准策略保持不变，"
            "当天是否交易仍由独立的 Decision、Account Truth、行情、费用与风险门决定。\n"
            "请在 Web 的 AI 研究页检查新旧指标、成本、OOS 与风险。"
            "系统没有替换生产策略，也没有创建或提交真实订单。"
        )
        try:
            await asyncio.to_thread(
                sender,
                title=f"Karkinos AI 策略研究: {market_date}",
                message=message,
            )
        except Exception:
            logger.warning("Shadow research notification failed", exc_info=True)

    def _utc_now(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat()


def is_after_shadow_research_close(
    market_date: str, now: datetime, after_close_time: str
) -> bool:
    evidence_date = datetime.fromisoformat(market_date).date()
    if evidence_date < now.date():
        return True
    if evidence_date > now.date():
        return False
    return now.time().replace(tzinfo=None) >= time.fromisoformat(after_close_time)


def shadow_research_market_close_as_of(
    market_date: str,
    after_close_time: str,
) -> datetime:
    try:
        return datetime.combine(
            datetime.fromisoformat(market_date).date(),
            time.fromisoformat(after_close_time),
            tzinfo=SHADOW_RESEARCH_TIMEZONE,
        )
    except ValueError as exc:
        raise ShadowResearchRejected("frozen_market_close_invalid") from exc


def shadow_research_asset_class(value: str) -> AssetClass:
    try:
        return AssetClass.FUND if value == "etf" else AssetClass(value)
    except ValueError as exc:
        raise ShadowResearchRejected("baseline_asset_class_invalid") from exc


def shadow_research_backtest_source_fingerprint(row: Mapping[str, Any]) -> str:
    return content_fingerprint(
        {
            "id": int(row.get("id") or 0),
            "initial_cash": row.get("initial_cash"),
            "final_equity": row.get("final_equity"),
            "total_return": row.get("total_return"),
            "sharpe": row.get("sharpe"),
            "max_drawdown": row.get("max_drawdown"),
            "equity_curve": shadow_research_json_list(row.get("equity_curve_json")),
            "metrics": shadow_research_json_object(row.get("metrics_json")),
            "cost_summary": shadow_research_json_object(row.get("cost_summary_json")),
        }
    )


def shadow_research_hypothesis_usage(session: Mapping[str, Any]) -> int | None:
    drafts = session.get("drafts")
    if not isinstance(drafts, list) or not drafts:
        return None
    provenance = (
        drafts[0].get("provider_provenance") if isinstance(drafts[0], dict) else None
    )
    return shadow_research_usage_tokens(provenance)


def shadow_research_critique_usage(critique: Mapping[str, Any]) -> int | None:
    artifact = critique.get("artifact")
    provenance = (
        artifact.get("provider_provenance") if isinstance(artifact, dict) else None
    )
    return shadow_research_usage_tokens(provenance)


def shadow_research_usage_tokens(provenance: Any) -> int | None:
    if not isinstance(provenance, Mapping):
        return None
    usage = provenance.get("usage")
    if not isinstance(usage, Mapping):
        return None
    value = usage.get("total_tokens")
    try:
        parsed = int(value) if value is not None else None
        return parsed if parsed is None or parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def shadow_research_failure_code(exc: Exception) -> str:
    value = str(exc).strip()
    if isinstance(exc, ValueError) and value.startswith(
        "conflicting role id: external.strategy_"
    ):
        return "ai_runtime_role_identity_conflict"
    if (
        value
        and len(value) <= 160
        and all(char.isalnum() or char in "_:-." for char in value)
    ):
        return value
    return type(exc).__name__


class NullShadowResearchEventBus:
    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        return None

    def publish(self, *args: Any, **kwargs: Any) -> None:
        return None
