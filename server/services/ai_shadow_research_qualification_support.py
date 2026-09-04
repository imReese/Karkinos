"""Internal deterministic helpers for account qualification replay."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from server.ai_runtime.formula_dsl import FormulaBinding
from server.ai_runtime.strategy_research_privacy import NORMALIZED_RESEARCH_NOTIONAL
from server.contracts.ai_shadow_research_qualification import (
    SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_RUN_TYPE,
    SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_SCHEMA,
    SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
    ShadowResearchQualificationRejected,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.strategy_research import StrategyResearchSelection
from server.projections.daily_strategy_artifacts import ranking_metrics
from server.services.ai_shadow_research_baseline import AiShadowResearchBaselineMixin
from server.services.market_hours import get_shanghai_now
from server.services.valuation_snapshot import valuation_snapshot_from_row

_FINGERPRINT = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
_FAILURE_CODE = re.compile(r"^[A-Za-z0-9_-]+$")
QUALIFICATION_MARKET_OPEN_BLACKOUT_CODE = "qualification_market_open_blackout"
QUALIFICATION_NOTIONAL_POLICY_ID = (
    "karkinos.ai.account_qualification_notional.min_normalized_or_equity.v1"
)
QUALIFICATION_COMPARISON_SCHEMA = "karkinos.ai.shadow_research_comparison.v1"


@dataclass(frozen=True)
class FrozenQualificationSource:
    """One exact source candidate and all persisted audit dependencies."""

    verified: dict[str, Any]
    source_candidate: dict[str, Any]
    source_selection: StrategyResearchSelection
    source_draft: dict[str, Any]
    source_critique: dict[str, Any]
    source_backtest: dict[str, Any]
    semantic_fingerprint: str


class QualificationBaselinePreparer(AiShadowResearchBaselineMixin):
    def __init__(self, *, db: Any, data_store: Any) -> None:
        self._db = db
        self._data_store = data_store

    def _resolve_reviewed_fee_schedule(self, **_: Any) -> Any:
        raise ShadowResearchQualificationRejected(
            "qualification_reviewed_fee_resolution_not_bound"
        )


def formula_binding(
    selection: StrategyResearchSelection,
    draft: Mapping[str, Any],
) -> FormulaBinding:
    return FormulaBinding(
        formula_ast=dict(draft["formula_ast"]),
        universe=selection.universe,
        dataset_snapshot_id=selection.dataset_snapshot_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        frequency=selection.frequency,
        cost_model_reference=selection.cost_model_reference,
        anti_lookahead_assumptions=tuple(
            str(item) for item in draft.get("anti_lookahead_assumptions") or []
        ),
        parameter_values=dict(draft.get("parameter_values") or {}),
        parameter_ranges=dict(draft.get("parameter_ranges") or {}),
        initial_cash=selection.initial_cash,
    )


def qualification_backtest_values(
    request: Any,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the canonical row values for the qualification persistence UoW."""

    return {
        "config_json": request.model_dump_json(),
        "initial_cash": float(result["initial_cash"]),
        "final_equity": float(result["final_equity"]),
        "total_return": float(result["total_return"]),
        "sharpe": float(result["sharpe"]),
        "max_dd": float(result["max_drawdown"]),
        "equity_curve_json": json.dumps(result["equity_curve"], ensure_ascii=False),
        "annual_return": float(result.get("annual_return") or 0),
        "sortino": float(result.get("sortino") or 0),
        "win_rate": float(result.get("win_rate") or 0),
        "duration_days": int(result.get("duration_days") or 0),
        "metrics_json": json.dumps(result["metrics_json"], ensure_ascii=False),
        "cost_summary_json": json.dumps(
            result["cost_summary_json"], ensure_ascii=False
        ),
    }


def require_complete_valuation(value: Any, db: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_snapshot_missing"
        )
    snapshot = dict(value)
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    cutoff = snapshot.get("ledger_cutoff_id")
    if (
        snapshot.get("status") != "complete"
        or not snapshot_id.startswith("valuation-")
        or not valid_fingerprint(snapshot_id.removeprefix("valuation-"))
        or isinstance(cutoff, bool)
        or int(cutoff or 0) <= 0
        or not valid_fingerprint(snapshot.get("ledger_fingerprint"))
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_or_ledger_not_complete"
        )
    persisted = db.get_valuation_snapshot_sync(snapshot_id)
    if isinstance(persisted, Mapping) and "quotes_json" in persisted:
        try:
            persisted = valuation_snapshot_from_row(dict(persisted))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ShadowResearchQualificationRejected(
                "qualification_valuation_snapshot_not_persisted"
            ) from exc
    for field in (
        "snapshot_id",
        "as_of",
        "trade_date",
        "status",
        "ledger_cutoff_id",
        "ledger_fingerprint",
        "quote_set_fingerprint",
        "valuation_policy",
    ):
        if not isinstance(persisted, Mapping) or persisted.get(field) != snapshot.get(
            field
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_valuation_snapshot_not_persisted"
            )
    return snapshot


def qualification_clock_time(clock: Callable[[], datetime | str]) -> datetime:
    """Read one timezone-aware qualification clock instant."""

    value = clock()
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ShadowResearchQualificationRejected(
                "qualification_clock_invalid"
            ) from exc
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ShadowResearchQualificationRejected("qualification_clock_invalid")
    return value


def qualification_market_open_blackout(value: datetime) -> bool:
    """Keep account qualification outside the Shanghai 09:00-10:00 window."""

    current = get_shanghai_now(value)
    return (current.hour, current.minute, current.second, current.microsecond) >= (
        9,
        0,
        0,
        0,
    ) and current.hour < 10


def require_current_valuation_trade_date(
    snapshot: Mapping[str, Any],
    *,
    source_market_date: Any,
    latest_closed_market_date_reader: Callable[[Any, datetime], str | None],
    db: Any,
    clock: Callable[[], datetime | str],
) -> None:
    """Require current closed-session valuation while allowing source catch-up."""

    current_time = qualification_clock_time(clock)
    latest_closed_market_date = latest_closed_market_date_reader(db, current_time)
    try:
        source_date = date.fromisoformat(str(source_market_date or ""))
        valuation_date = date.fromisoformat(str(snapshot.get("trade_date") or ""))
    except ValueError as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_trade_date_invalid"
        ) from exc
    if not latest_closed_market_date:
        raise ShadowResearchQualificationRejected(
            "qualification_current_market_date_unavailable"
        )
    try:
        current_market_date = date.fromisoformat(str(latest_closed_market_date))
    except ValueError as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_current_market_date_invalid"
        ) from exc
    if source_date > current_market_date:
        raise ShadowResearchQualificationRejected(
            "qualification_source_market_date_future"
        )
    if valuation_date > current_market_date:
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_snapshot_future_dated"
        )
    if valuation_date < current_market_date or valuation_date < source_date:
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_snapshot_stale"
        )
    try:
        valuation_as_of = datetime.fromisoformat(
            str(snapshot.get("as_of") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_as_of_invalid"
        ) from exc
    if valuation_as_of.tzinfo is None or valuation_as_of.utcoffset() is None:
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_as_of_invalid"
        )
    if valuation_as_of > current_time + timedelta(minutes=5):
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_snapshot_future_dated"
        )
    if get_shanghai_now(valuation_as_of).date() < valuation_date:
        raise ShadowResearchQualificationRejected(
            "qualification_valuation_snapshot_stale"
        )


def account_total_equity(
    payload: Any,
    valuation: Mapping[str, Any],
) -> Decimal:
    if not isinstance(payload, Mapping):
        raise ShadowResearchQualificationRejected(
            "qualification_account_payload_invalid"
        )
    summary = payload.get("summary")
    snapshot = payload.get("snapshot")
    if not isinstance(summary, Mapping) or not isinstance(snapshot, Mapping):
        raise ShadowResearchQualificationRejected(
            "qualification_account_total_equity_invalid"
        )
    try:
        summary_equity = Decimal(str(summary["total_equity"]))
        snapshot_equity = Decimal(str(snapshot["total_equity"]))
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_account_total_equity_invalid"
        ) from exc
    if (
        not summary_equity.is_finite()
        or summary_equity <= 0
        or snapshot_equity != summary_equity
        or summary.get("valuation_status") != "complete"
        or snapshot.get("valuation_status") != "complete"
        or summary.get("valuation_snapshot_id") != valuation["snapshot_id"]
        or snapshot.get("valuation_snapshot_id") != valuation["snapshot_id"]
        or int(summary.get("ledger_cutoff_id") or 0) != valuation["ledger_cutoff_id"]
        or int(snapshot.get("ledger_cutoff_id") or 0) != valuation["ledger_cutoff_id"]
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_account_total_equity_invalid"
        )
    return summary_equity


def qualification_initial_cash(total_equity: Decimal) -> Decimal:
    return min(Decimal(str(NORMALIZED_RESEARCH_NOTIONAL)), total_equity)


def qualification_selection(
    *,
    qualification_run_id: str,
    source_run_id: str,
    market_date: str,
    candidates: Sequence[Mapping[str, Any]],
    replay_failed: bool,
) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for candidate in candidates:
        gate = candidate.get("comparison", {}).get("promotion_gate", {})
        metrics = ranking_metrics(gate) if isinstance(gate, Mapping) else None
        outcome = {
            "qualification_candidate_id": candidate.get("qualification_candidate_id"),
            "source_candidate_id": candidate.get("source_candidate_id"),
            "status": candidate.get("status"),
            "recommendation": candidate.get("recommendation"),
            "promotion_gate_status": gate.get("status"),
            "promotion_gate_fingerprint": gate.get("evidence_fingerprint"),
            "ranking_metrics": (
                {key: format(value, "f") for key, value in metrics.items()}
                if metrics is not None
                else None
            ),
        }
        outcomes.append(outcome)
        if candidate.get("status") == "qualified" and metrics is not None:
            ranked.append(
                (
                    (
                        -metrics["after_tax_excess_return"],
                        -metrics["mean_oos_excess_return"],
                        -metrics["worst_oos_excess_return"],
                        metrics["candidate_max_drawdown"],
                        metrics["candidate_turnover_to_initial_cash"],
                        str(candidate["qualification_candidate_id"]),
                    ),
                    outcome,
                )
            )
    ranked.sort(key=lambda item: item[0])
    selection = {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "qualification_run_id": qualification_run_id,
        "source_run_id": source_run_id,
        "market_date": market_date,
        "status": (
            "failed"
            if replay_failed
            else ("winner_selected" if ranked else "no_selection")
        ),
        "winner_qualification_candidate_id": (
            ranked[0][1]["qualification_candidate_id"]
            if ranked and not replay_failed
            else None
        ),
        "ranking_method": {
            "type": "hard_gate_then_lexicographic",
            "priority": [
                "after_tax_excess_return_desc",
                "mean_oos_excess_return_desc",
                "worst_oos_excess_return_desc",
                "candidate_max_drawdown_asc",
                "candidate_turnover_to_initial_cash_asc",
                "qualification_candidate_id_asc",
            ],
            "weighted_average_used": False,
            "provider_selects_winner": False,
        },
        "ranked_eligible_candidates": [
            dict(outcome) | {"rank": rank}
            for rank, (_, outcome) in enumerate(ranked, start=1)
        ],
        "candidate_outcomes": sorted(
            outcomes, key=lambda item: str(item["source_candidate_id"])
        ),
        "provider_call_performed": False,
        "broker_order_created": False,
        "capital_authority_granted": False,
    }
    if replay_failed:
        return {
            "run_status": "failed",
            "selection": selection,
            "blockers": [],
            "failure_code": "qualification_candidate_replay_incomplete",
        }
    if ranked:
        return {
            "run_status": "completed",
            "selection": selection,
            "blockers": [],
            "failure_code": None,
        }
    return {
        "run_status": "blocked",
        "selection": selection,
        "blockers": ["no_candidate_passed_account_qualification"],
        "failure_code": None,
    }


def classify_qualification_resume_candidates(
    frozen: Sequence[FrozenQualificationSource],
    candidates: Sequence[Mapping[str, Any]],
    *,
    require_complete: bool,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Index only exact persisted replay members and retain any prior failure."""

    expected = {str(item.source_candidate["candidate_id"]): item for item in frozen}
    indexed = {
        str(candidate.get("source_candidate_id") or ""): dict(candidate)
        for candidate in candidates
    }
    invalid = len(indexed) != len(candidates) or bool(indexed.keys() - expected.keys())
    for candidate_id, source in expected.items():
        candidate = indexed.get(candidate_id)
        if candidate is None:
            invalid = invalid or require_complete
            continue
        if (
            candidate.get("source_draft_id") != source.source_candidate.get("draft_id")
            or candidate.get("source_formula_fingerprint")
            != source.source_draft.get("formula_fingerprint")
            or candidate.get("source_formula_semantic_fingerprint")
            != source.semantic_fingerprint
            or candidate.get("qualified_formula_semantic_fingerprint")
            != source.semantic_fingerprint
            or int(candidate.get("rank") or 0)
            != int(source.verified.get("iteration_number") or 0)
            or candidate.get("status") == "failed"
        ):
            invalid = True
    return indexed, invalid


async def call_maybe_async(callable_value: Callable[[], Any]) -> Any:
    result = callable_value()
    return await result if inspect.isawaitable(result) else result


def valuation_fingerprint(snapshot_id: str) -> str:
    return "sha256:" + snapshot_id.removeprefix("valuation-")


def money_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def now_text(clock: Callable[[], datetime | str]) -> str:
    value = clock()
    return value.isoformat() if isinstance(value, datetime) else str(value)


def valid_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and _FINGERPRINT.fullmatch(value.lower()) is not None


def failure_code(exc: Exception) -> str:
    value = str(exc).strip().split(":", maxsplit=1)[0]
    if value and all(char.isalnum() or char in "_-" for char in value):
        return value
    return (
        "qualification_" + re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
    )


def blocked_result(blocker: str) -> dict[str, Any]:
    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "status": "blocked",
        "failure_code": blocker,
        "run": None,
        "candidates": [],
        "blockers": [blocker],
        "provider_call_performed": False,
        "automatic_strategy_replacement_enabled": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "capital_authority_granted": False,
        "human_paper_shadow_approval_required": True,
        "private_account_values_redacted": True,
    }


def deferred_result(reason: str) -> dict[str, Any]:
    """Return a non-terminal, non-persisted provider-free retry signal."""

    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "status": "deferred",
        "failure_code": None,
        "deferred_reason": reason,
        "run": None,
        "candidates": [],
        "blockers": [reason],
        "terminal": False,
        "retryable": True,
        "provider_call_performed": False,
        "automatic_strategy_replacement_enabled": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "capital_authority_granted": False,
        "human_paper_shadow_approval_required": True,
        "private_account_values_redacted": True,
    }


def record_blocked_qualification_attempt(
    db: Any,
    *,
    batch: Mapping[str, Any],
    blocker: str,
    recorded_at: str,
) -> dict[str, Any]:
    """Persist one redacted terminal pre-run attempt for an exact source batch."""

    source = {
        "source_run_id": str(batch.get("run_id") or "").strip(),
        "market_date": str(batch.get("market_date") or "").strip(),
        "source_selection_id": str(batch.get("selection_id") or "").strip(),
        "source_selection_fingerprint": str(
            batch.get("selection_fingerprint") or ""
        ).strip(),
        "source_backup_fingerprint": str(
            batch.get("backup_artifact_fingerprint") or ""
        ).strip(),
    }
    if (
        not all(source.values())
        or not valid_fingerprint(source["source_selection_fingerprint"])
        or not valid_fingerprint(source["source_backup_fingerprint"])
        or not blocker
        or _FAILURE_CODE.fullmatch(blocker) is None
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_attempt_source_identity_invalid"
        )
    payload_core = {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_SCHEMA,
        **source,
        "status": "blocked",
        "failure_code": blocker,
        "blockers": [blocker],
        "provider_call_performed": False,
        "automatic_strategy_replacement_enabled": False,
        "production_strategy_mutation_enabled": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "ledger_mutation_performed": False,
        "capital_authority_granted": False,
        "contains_private_account_values": False,
        "contains_private_account_identifiers": False,
        "contains_account_reference": False,
        "contains_backup_path": False,
        "authority_effect": "none",
    }
    evidence_fingerprint = content_fingerprint(payload_core)
    payload = {**payload_core, "evidence_fingerprint": evidence_fingerprint}
    run_id = (
        "automation:ai-shadow-research-account-qualification-attempt:"
        + evidence_fingerprint
    )
    claim = db.claim_automation_run_once_sync(
        run_id=run_id,
        run_type=SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_RUN_TYPE,
        run_date=source["market_date"],
        claimed_at=recorded_at,
        execution_mode="research_only",
        payload=payload,
    )
    row = claim["run"]
    if claim["claimed"] or row.get("status") == "claimed":
        row = db.upsert_automation_run_sync(
            {
                "run_id": run_id,
                "run_type": SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_RUN_TYPE,
                "run_date": source["market_date"],
                "status": "blocked",
                "execution_mode": "research_only",
                "started_at": row.get("started_at") or recorded_at,
                "finished_at": recorded_at,
                "source_ref": source["source_run_id"],
                "payload": payload,
            }
        )
    projected = public_qualification_attempt(
        row,
        expected_source_run_id=source["source_run_id"],
    )
    if projected is None:
        raise ShadowResearchQualificationRejected(
            "qualification_attempt_persistence_conflict"
        )
    return projected


def latest_qualification_attempt(
    db: Any,
    *,
    source_run_id: str,
    market_date: str | None = None,
    source_selection_id: str | None = None,
    source_selection_fingerprint: str | None = None,
    source_backup_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Read the newest verified, redacted attempt for one exact source run."""

    normalized_source_run_id = str(source_run_id or "").strip()
    if not normalized_source_run_id:
        return None
    reader = getattr(db, "list_automation_runs_sync", None)
    if not callable(reader):
        return None
    kwargs: dict[str, Any] = {
        "run_type": SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_RUN_TYPE,
        "limit": 50,
    }
    if market_date:
        kwargs["run_date"] = str(market_date)
    try:
        rows = reader(**kwargs)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    for row in rows:
        projected = public_qualification_attempt(
            row,
            expected_source_run_id=normalized_source_run_id,
            expected_source_selection_id=source_selection_id,
            expected_source_selection_fingerprint=source_selection_fingerprint,
            expected_source_backup_fingerprint=source_backup_fingerprint,
        )
        if projected is not None:
            return projected
    return None


def public_qualification_attempt(
    row: Mapping[str, Any],
    *,
    expected_source_run_id: str | None = None,
    expected_source_selection_id: str | None = None,
    expected_source_selection_fingerprint: str | None = None,
    expected_source_backup_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Validate and allow-list one operational attempt for public projections."""

    try:
        payload_value = row.get("payload")
        payload = (
            dict(payload_value)
            if isinstance(payload_value, Mapping)
            else json.loads(str(row.get("payload_json") or ""))
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    evidence_fingerprint = str(payload.get("evidence_fingerprint") or "")
    payload_core = dict(payload)
    payload_core.pop("evidence_fingerprint", None)
    source_run_id = str(payload.get("source_run_id") or "")
    source_selection_id = str(payload.get("source_selection_id") or "")
    source_selection_fingerprint = str(
        payload.get("source_selection_fingerprint") or ""
    )
    source_backup_fingerprint = str(payload.get("source_backup_fingerprint") or "")
    market_date = str(payload.get("market_date") or "")
    blocker = str(payload.get("failure_code") or "")
    expected_run_id = (
        "automation:ai-shadow-research-account-qualification-attempt:"
        + evidence_fingerprint
    )
    if (
        payload.get("schema_version") != SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_SCHEMA
        or not source_run_id
        or not source_selection_id
        or not valid_fingerprint(source_selection_fingerprint)
        or not valid_fingerprint(source_backup_fingerprint)
        or (
            expected_source_run_id is not None
            and source_run_id != expected_source_run_id
        )
        or (
            expected_source_selection_id is not None
            and source_selection_id != expected_source_selection_id
        )
        or (
            expected_source_selection_fingerprint is not None
            and source_selection_fingerprint != expected_source_selection_fingerprint
        )
        or (
            expected_source_backup_fingerprint is not None
            and source_backup_fingerprint != expected_source_backup_fingerprint
        )
        or not market_date
        or not blocker
        or _FAILURE_CODE.fullmatch(blocker) is None
        or payload.get("status") != "blocked"
        or payload.get("blockers") != [blocker]
        or content_fingerprint(payload_core) != evidence_fingerprint
        or row.get("run_id") != expected_run_id
        or row.get("run_type") != SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_RUN_TYPE
        or row.get("run_date") != market_date
        or row.get("status") != "blocked"
        or row.get("execution_mode") != "research_only"
        or row.get("source_ref") != source_run_id
        or any(
            payload.get(field) != expected
            for field, expected in (
                ("provider_call_performed", False),
                ("automatic_strategy_replacement_enabled", False),
                ("production_strategy_mutation_enabled", False),
                ("broker_order_created", False),
                ("broker_submission_enabled", False),
                ("ledger_mutation_performed", False),
                ("capital_authority_granted", False),
                ("contains_private_account_values", False),
                ("contains_private_account_identifiers", False),
                ("contains_account_reference", False),
                ("contains_backup_path", False),
                ("authority_effect", "none"),
            )
        )
    ):
        return None
    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_SCHEMA,
        "attempt_id": expected_run_id,
        "source_run_id": source_run_id,
        "market_date": market_date,
        "status": "blocked",
        "failure_code": blocker,
        "blockers": [blocker],
        "evidence_fingerprint": evidence_fingerprint,
        "created_at": row.get("created_at"),
        "finished_at": row.get("finished_at"),
        "provider_call_performed": False,
        "automatic_strategy_replacement_enabled": False,
        "production_strategy_mutation_enabled": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "ledger_mutation_performed": False,
        "capital_authority_granted": False,
        "private_account_values_redacted": True,
        "authority_effect": "none",
    }


def public_result(store: Any, run: Mapping[str, Any], reused: bool) -> dict[str, Any]:
    run_id = str(run["qualification_run_id"])
    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "status": run["status"],
        "run": store.get_public_qualification_run(run_id),
        "candidates": store.list_public_qualification_candidates(run_id),
        "reused": reused,
        "provider_call_performed": False,
        "automatic_strategy_replacement_enabled": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "capital_authority_granted": False,
        "human_paper_shadow_approval_required": True,
    }


__all__ = [
    "FrozenQualificationSource",
    "QualificationBaselinePreparer",
    "QUALIFICATION_MARKET_OPEN_BLACKOUT_CODE",
    "account_total_equity",
    "blocked_result",
    "call_maybe_async",
    "classify_qualification_resume_candidates",
    "deferred_result",
    "failure_code",
    "formula_binding",
    "latest_qualification_attempt",
    "money_text",
    "now_text",
    "public_qualification_attempt",
    "qualification_backtest_values",
    "qualification_clock_time",
    "qualification_initial_cash",
    "qualification_market_open_blackout",
    "qualification_selection",
    "public_result",
    "record_blocked_qualification_attempt",
    "require_complete_valuation",
    "require_current_valuation_trade_date",
    "valid_fingerprint",
    "valuation_fingerprint",
]
