"""Formula-backtest repository operations for AI strategy research."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.strategy_research import (
    FormulaBacktestRequest,
    StrategyResearchRejected,
    backtest_evidence_blocker,
    validate_prior_diagnostic_exposure,
)
from server.persistence.backtest_results import (
    backtest_row_fingerprint,
    with_backtest_invalidation,
)
from server.persistence.strategy_research_events import (
    append_research_event,
    verify_research_events,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

_ACTUAL_COST_EVENT = "formula_backtest.actual_cost_exposure"
_COST_SCOPE_FIELDS = (
    "universe",
    "start_date",
    "end_date",
    "frequency",
    "cost_model_reference",
)


def _validated_actual_cost_fact(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    result_id: int,
    source_row_fingerprint: str,
    source_saved_row_sha256: str,
    exposure: JsonObject | None,
) -> tuple[JsonObject, JsonObject]:
    """Bind a disclosure to the original, complete cost list; never import scores."""
    run = conn.execute(
        "SELECT b.*,s.request_json,d.contract_json "
        "FROM ai_strategy_formula_backtests b "
        "JOIN ai_strategy_research_sessions s ON s.session_id=b.session_id "
        "JOIN ai_strategy_hypothesis_drafts d ON d.draft_id=b.draft_id "
        "WHERE b.backtest_run_id=?",
        (run_id,),
    ).fetchone()
    if run is None or run["status"] not in {"completed", "failed"}:
        raise StrategyResearchRejected("actual_cost_terminal_backtest_required")
    if run["canonical_backtest_result_id"] is None:
        raise StrategyResearchRejected("actual_cost_saved_result_required")
    if type(result_id) is not int or result_id != run["canonical_backtest_result_id"]:
        raise StrategyResearchRejected("actual_cost_result_identity_mismatch")
    saved = conn.execute(
        "SELECT * FROM backtest_results WHERE id=?", (result_id,)
    ).fetchone()
    if saved is None or backtest_row_fingerprint(dict(saved)) != source_row_fingerprint:
        raise StrategyResearchRejected("actual_cost_source_row_mismatch")
    if not isinstance(source_saved_row_sha256, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", source_saved_row_sha256
    ):
        raise StrategyResearchRejected("actual_cost_source_artifact_invalid")
    row = dict(saved)
    selected = json.loads(run["request_json"])["selection"]
    draft = json.loads(run["contract_json"])
    metrics = json.loads(row["metrics_json"])
    source_selection = metrics.get("source_selection")
    if "source_selection" not in metrics:
        # Legacy single-symbol replay stores this exact binding only in its
        # native diagnostic. Require that diagnostic to bind the same main path.
        diagnostic = metrics.get("native_diagnostic", {})
        if (
            isinstance(diagnostic, dict)
            and diagnostic.get("schema_version")
            == "karkinos.ai.native_formula_diagnostic.v1"
            and diagnostic.get("evidence_fingerprint")
            == content_fingerprint(
                {
                    key: value
                    for key, value in diagnostic.items()
                    if key != "evidence_fingerprint"
                }
            )
            and all(
                diagnostic.get(key) == metrics.get(key)
                for key in (
                    "formula_binding",
                    "formula_fingerprint",
                    "dataset_snapshot",
                    "cost_assumptions",
                )
            )
        ):
            source_selection = diagnostic.get("source_selection")
    if (
        source_selection != selected
        or metrics.get("formula_fingerprint") != run["formula_fingerprint"]
        or metrics.get("dataset_snapshot", {}).get("snapshot_id")
        != run["dataset_snapshot_id"]
        or metrics.get("formula_binding", {}).get("formula_ast")
        != draft.get("formula_ast")
        or metrics.get("formula_binding", {}).get("parameter_values")
        != draft.get("parameter_values")
        or metrics.get("formula_binding", {}).get("parameter_ranges")
        != draft.get("parameter_ranges")
    ):
        raise StrategyResearchRejected("actual_cost_source_binding_mismatch")
    costs = metrics.get("cost_sensitivity")
    try:
        if not isinstance(costs, list) or len(costs) > 2:
            raise ValueError
        json.dumps(costs, allow_nan=False)
        bps = [Decimal(item["slippage_bps"]) for item in costs]
        if any(not value.is_finite() or value <= 0 for value in bps) or len(
            set(bps)
        ) != len(bps):
            raise ValueError
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise StrategyResearchRejected("actual_cost_list_invalid") from exc
    if costs:
        validate_prior_diagnostic_exposure(exposure)
        assert exposure is not None  # established by the strict owner validator
        preimage = {
            "source_result_id": result_id,
            "source_saved_row_sha256": source_saved_row_sha256,
            "only_actual_cost_sensitivity": costs,
        }
        if (
            exposure["artifact_fingerprint"]
            != "sha256:" + content_fingerprint(preimage)
            or exposure["observed_trial_count"] != len(costs)
            or any(
                exposure[key] != selected[key]
                for key in (
                    "universe",
                    "start_date",
                    "end_date",
                    "frequency",
                    "cost_model_reference",
                )
            )
            or datetime.fromisoformat(exposure["observed_at"])
            < datetime.fromisoformat(run["updated_at"])
        ):
            raise StrategyResearchRejected("actual_cost_disclosure_mismatch")
    elif exposure is not None:
        raise StrategyResearchRejected("actual_cost_zero_paths_has_disclosure")
    # Withdrawal affects evidence readiness, not whether these paths were viewed.
    # The fingerprint covers the original row, excluding later invalidation facts.
    return {
        "backtest_run_id": run_id,
        "canonical_backtest_result_id": result_id,
        "source_row_fingerprint": source_row_fingerprint,
        "source_saved_row_sha256": source_saved_row_sha256,
        "cost_sensitivity_fingerprint": "sha256:" + content_fingerprint(costs),
        "actual_cost_count": len(costs),
        "terminal_at": run["updated_at"],
        "source_scope": {key: selected[key] for key in _COST_SCOPE_FIELDS},
        "exposure": exposure,
    }, row


class StrategyResearchBacktestRepositoryMixin:
    if TYPE_CHECKING:
        # Implemented by the existing audit-store unit of work/event mixins.
        def _connect(
            self, *, immediate: bool = False
        ) -> AbstractContextManager[sqlite3.Connection]: ...

        def _connect_readonly(self) -> AbstractContextManager[sqlite3.Connection]: ...

        def append_event(
            self,
            entity_id: str,
            event_type: str,
            payload: JsonObject,
            *,
            created_at: str,
        ) -> None: ...

    def create_or_get_backtest(
        self,
        request: FormulaBacktestRequest,
        *,
        formula_fingerprint: str,
        dataset_snapshot_id: str,
        cost_model_reference: str,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        request_fingerprint = content_fingerprint(
            {
                "requested_by": request.requested_by,
                "session_id": request.session_id,
                "draft_id": request.draft_id,
                "confirmation": request.confirmation,
                "formula_fingerprint": formula_fingerprint,
                "dataset_snapshot_id": dataset_snapshot_id,
                "cost_model_reference": cost_model_reference,
            }
        )
        run_id = (
            "ai-formula-backtest-"
            + content_fingerprint({"idempotency_key": request.idempotency_key})[:24]
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_strategy_formula_backtests WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if row["request_fingerprint"] != request_fingerprint:
                    raise IdempotencyConflict("formula backtest idempotency conflict")
                return row, True
            conn.execute(
                """
                INSERT INTO ai_strategy_formula_backtests
                (backtest_run_id, idempotency_key, request_fingerprint, session_id,
                 draft_id, formula_fingerprint, dataset_snapshot_id,
                 cost_model_reference, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    run_id,
                    request.idempotency_key,
                    request_fingerprint,
                    request.session_id,
                    request.draft_id,
                    formula_fingerprint,
                    dataset_snapshot_id,
                    cost_model_reference,
                    created_at,
                    created_at,
                ),
            )
        return self.get_backtest(run_id), False

    def finish_backtest(
        self,
        run_id: str,
        *,
        status: str,
        result_id: int | None,
        evidence_fingerprint: str | None,
        failure_code: str | None,
        updated_at: str,
    ) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_strategy_formula_backtests
                SET status=?, canonical_backtest_result_id=?, evidence_fingerprint=?,
                    failure_code=?, updated_at=? WHERE backtest_run_id=?
                """,
                (
                    status,
                    result_id,
                    evidence_fingerprint,
                    failure_code,
                    updated_at,
                    run_id,
                ),
            )
        self.append_event(
            run_id,
            f"formula_backtest.{status}",
            {
                "canonical_backtest_result_id": result_id,
                "failure_code": failure_code,
            },
            created_at=updated_at,
        )

    def get_backtest(self, run_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_strategy_formula_backtests WHERE backtest_run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"formula backtest not found: {run_id}")
        return dict(row)

    def record_actual_cost_exposure(
        self,
        run_id: str,
        *,
        result_id: int,
        source_row_fingerprint: str,
        saved_result_json: str,
        exposure: JsonObject | None,
        created_at: str,
    ) -> tuple[JsonObject, bool]:
        """Append one verified actual-cost fact on its original terminal run.

        The original serialized row supplies the existing disclosure identity.
        It is validated here, then only its hashes and exact prior disclosure are
        retained. Repeated calls cannot add events or trials for the same run.
        """
        try:
            if not isinstance(saved_result_json, str):
                raise ValueError
            saved_artifact = json.loads(saved_result_json)
            recorded_at = datetime.fromisoformat(created_at)
            if not isinstance(saved_artifact, dict) or recorded_at.utcoffset() is None:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise StrategyResearchRejected(
                "actual_cost_source_artifact_invalid"
            ) from exc
        artifact_sha = (
            "sha256:" + hashlib.sha256(saved_result_json.encode("utf-8")).hexdigest()
        )
        with self._connect(immediate=True) as conn:
            fact, row = _validated_actual_cost_fact(
                conn,
                run_id,
                result_id=result_id,
                source_row_fingerprint=source_row_fingerprint,
                source_saved_row_sha256=artifact_sha,
                exposure=exposure,
            )
            if recorded_at < datetime.fromisoformat(fact["terminal_at"]):
                raise StrategyResearchRejected("actual_cost_recorded_before_terminal")
            if not verify_research_events(conn, run_id)[0]:
                raise StrategyResearchRejected("actual_cost_event_chain_invalid")
            artifact_row = dict(saved_artifact)
            if (
                artifact_row.pop("evidence_invalidation", None) is not None
                or artifact_row != row
            ):
                raise StrategyResearchRejected(
                    "actual_cost_saved_row_artifact_mismatch"
                )
            if exposure is not None and recorded_at < datetime.fromisoformat(
                exposure["observed_at"]
            ):
                raise StrategyResearchRejected(
                    "actual_cost_recorded_before_observation"
                )
            prior = conn.execute(
                "SELECT payload_json FROM ai_strategy_research_events "
                "WHERE entity_id=? AND event_type=?",
                (run_id, _ACTUAL_COST_EVENT),
            ).fetchall()
            if prior:
                if len(prior) != 1 or json.loads(prior[0]["payload_json"]) != fact:
                    raise IdempotencyConflict("actual cost exposure source conflict")
                return fact, True
            append_research_event(
                conn, run_id, _ACTUAL_COST_EVENT, fact, created_at=created_at
            )
        return fact, False

    def research_trial_family(
        self,
        selection: Any,
        *,
        trial_cutoff: str | None = None,
        exposure_cutoff: str | None = None,
    ) -> JsonObject:
        """Count scored semantic tests, including local sweeps and rejected drafts.

        Replays of an identical formula/data/cost test count once. Related earlier
        windows enter the nominal family; this does not claim independence.
        """
        import json
        from datetime import datetime

        from server.ai_runtime.formula_parameter_sweep import (
            build_formula_parameter_variants,
        )
        from server.contracts.strategy_research import StrategyResearchRejected

        with self._connect_readonly() as conn:
            if selection.has_sealed_holdout:
                for session in conn.execute(
                    "SELECT request_json,created_at,run_claimed_at FROM ai_strategy_research_sessions "
                    "WHERE context_snapshot_id IS NOT NULL OR run_claimed_at IS NOT NULL"
                ).fetchall():
                    if (
                        exposure_cutoff
                        and (session["run_claimed_at"] or session["created_at"])
                        > exposure_cutoff
                    ):
                        continue
                    exposed = json.loads(session["request_json"]).get("selection", {})
                    if (
                        set(exposed.get("universe", [])) & set(selection.universe)
                        and exposed.get("start_date", "") <= selection.sealed_end_date
                        and exposed.get("end_date", "") > selection.end_date
                    ):
                        raise StrategyResearchRejected(
                            "sealed_window_exposed_to_research"
                        )
            rows = conn.execute(
                "SELECT b.*, s.request_json, d.contract_json, r.metrics_json "
                "FROM ai_strategy_formula_backtests b "
                "JOIN ai_strategy_research_sessions s ON s.session_id=b.session_id "
                "JOIN ai_strategy_hypothesis_drafts d ON d.draft_id=b.draft_id "
                "LEFT JOIN backtest_results r ON r.id=b.canonical_backtest_result_id "
                "ORDER BY b.created_at, b.backtest_run_id"
            ).fetchall()
            diagnostic_sessions = conn.execute(
                "SELECT request_json FROM ai_strategy_research_sessions"
            ).fetchall()
            actual_cost_facts = []
            actual_cost_runs: set[str] = set()
            for event in conn.execute(
                "SELECT entity_id,payload_json FROM ai_strategy_research_events "
                "WHERE event_type=? ORDER BY rowid",
                (_ACTUAL_COST_EVENT,),
            ).fetchall():
                payload = json.loads(event["payload_json"])
                if (
                    not isinstance(payload, dict)
                    or set(payload)
                    != {
                        "backtest_run_id",
                        "canonical_backtest_result_id",
                        "source_row_fingerprint",
                        "source_saved_row_sha256",
                        "cost_sensitivity_fingerprint",
                        "actual_cost_count",
                        "terminal_at",
                        "source_scope",
                        "exposure",
                    }
                    or not verify_research_events(conn, event["entity_id"])[0]
                    or not isinstance(payload["source_scope"], dict)
                    or set(payload["source_scope"]) != set(_COST_SCOPE_FIELDS)
                    or not isinstance(payload["source_scope"]["universe"], list)
                ):
                    raise StrategyResearchRejected("actual_cost_event_invalid")
                selected = payload["source_scope"]
                boundary = (
                    selection.sealed_end_date
                    if selection.has_sealed_holdout
                    else selection.end_date
                )
                if (
                    not set(selected["universe"]) & set(selection.universe)
                    or selected["frequency"] != selection.frequency
                    or selected["cost_model_reference"]
                    != selection.cost_model_reference
                    or selected["start_date"] > boundary
                    or selected["end_date"] < selection.start_date
                ):
                    continue  # Frozen event scope survives an unrelated missing source.
                if event["entity_id"] in actual_cost_runs:
                    raise StrategyResearchRejected("actual_cost_event_invalid")
                actual_cost_runs.add(event["entity_id"])
                fact, _ = _validated_actual_cost_fact(
                    conn,
                    event["entity_id"],
                    result_id=payload["canonical_backtest_result_id"],
                    source_row_fingerprint=payload["source_row_fingerprint"],
                    source_saved_row_sha256=payload["source_saved_row_sha256"],
                    exposure=payload["exposure"],
                )
                if fact != payload:
                    raise StrategyResearchRejected("actual_cost_event_invalid")
                actual_cost_facts.append(fact)
        trials: set[str] = set()
        sources: list[JsonObject] = []
        diagnostic_sources: dict[str, JsonObject] = {}
        disclosures: list[tuple[JsonObject, JsonObject | None]] = [
            (exposure, None)
            for session in diagnostic_sessions
            for exposure in json.loads(session["request_json"]).get(
                "prior_diagnostic_exposures", []
            )
        ]
        disclosures.extend(
            (fact["exposure"], fact)
            for fact in actual_cost_facts
            if fact["exposure"] is not None
        )
        actual_cost_sources: list[JsonObject] = []
        for exposure, actual_fact in disclosures:
            validate_prior_diagnostic_exposure(exposure)
            observed_at = datetime.fromisoformat(exposure["observed_at"])
            overlap = bool(set(exposure["universe"]) & set(selection.universe))
            if (
                selection.has_sealed_holdout
                and overlap
                and (
                    not exposure_cutoff
                    or observed_at <= datetime.fromisoformat(exposure_cutoff)
                )
                and exposure["start_date"] <= selection.sealed_end_date
                and exposure["end_date"] > selection.end_date
            ):
                raise StrategyResearchRejected("sealed_window_exposed_to_research")
            if (
                not overlap
                or exposure["frequency"] != selection.frequency
                or exposure["cost_model_reference"] != selection.cost_model_reference
                or exposure["start_date"] > selection.end_date
                or exposure["end_date"] < selection.start_date
                or exposure["end_date"] > selection.end_date
                or (trial_cutoff and observed_at > datetime.fromisoformat(trial_cutoff))
            ):
                continue
            # These are disclosed score exposures, not canonical results.
            # Artifact/ordinal identities deliberately cannot deduplicate away
            # an existing scored trial. Repeated disclosures count once;
            # larger disclosures of the same artifact can only add trials.
            artifact_fingerprint = exposure["artifact_fingerprint"]
            for ordinal in range(exposure["observed_trial_count"]):
                trials.add(
                    content_fingerprint(
                        {
                            "diagnostic_artifact_fingerprint": artifact_fingerprint,
                            "conservative_exposure_ordinal": ordinal,
                        }
                    )
                )
            if actual_fact is not None:
                actual_cost_sources.append(
                    {
                        "source_kind": "actual_cost_exposure",
                        "backtest_run_id": actual_fact["backtest_run_id"],
                        "artifact_fingerprint": artifact_fingerprint,
                        "observed_trial_count": exposure["observed_trial_count"],
                        "source_fingerprint": content_fingerprint(actual_fact),
                        "canonical_performance_admitted": False,
                    }
                )
                continue
            prior = diagnostic_sources.get(artifact_fingerprint)
            if prior is None or (
                prior["observed_trial_count"],
                prior["source_fingerprint"],
            ) < (exposure["observed_trial_count"], content_fingerprint(exposure)):
                diagnostic_sources[artifact_fingerprint] = {
                    "source_kind": "declared_prior_diagnostic_exposure",
                    "artifact_fingerprint": artifact_fingerprint,
                    "observed_trial_count": exposure["observed_trial_count"],
                    "source_fingerprint": content_fingerprint(exposure),
                    "canonical_performance_admitted": False,
                }
        sources.extend(diagnostic_sources[key] for key in sorted(diagnostic_sources))
        sources.extend(actual_cost_sources)
        for raw in rows:
            row = dict(raw)
            selected = json.loads(row["request_json"]).get("selection", {})
            if (
                selection.has_sealed_holdout
                and row["canonical_backtest_result_id"] is not None
                and (not exposure_cutoff or row["created_at"] <= exposure_cutoff)
                and set(selected.get("universe", [])) & set(selection.universe)
                and selected.get("start_date", "") <= selection.sealed_end_date
                and selected.get("end_date", "") > selection.end_date
            ):
                raise StrategyResearchRejected("sealed_window_exposed_to_research")
            if trial_cutoff and row["created_at"] > trial_cutoff:
                continue
            if (
                (
                    not (set(selected.get("universe", [])) & set(selection.universe))
                    if selection.deployment_scope
                    else sorted(selected.get("universe", []))
                    != sorted(selection.universe)
                )
                or selected.get("frequency") != selection.frequency
                or selected.get("cost_model_reference")
                != selection.cost_model_reference
                or selected.get("start_date", "") > selection.end_date
                or selected.get("end_date", "") < selection.start_date
                or selected.get("end_date", "") > selection.end_date
            ):
                continue
            if row["status"] == "running":
                raise StrategyResearchRejected("research_trial_family_incomplete")
            if row["canonical_backtest_result_id"] is None:
                continue  # No score was persisted or returned to the iteration.
            if not row["metrics_json"]:
                raise StrategyResearchRejected("research_trial_result_missing")
            metrics = json.loads(row["metrics_json"])
            draft = json.loads(row["contract_json"])
            ast = draft.get("formula_ast")
            if not isinstance(ast, dict):
                raise StrategyResearchRejected("research_trial_formula_missing")
            context = {
                "dataset_snapshot_id": row["dataset_snapshot_id"],
                "cost_model_reference": row["cost_model_reference"],
                "initial_cash": selected.get("initial_cash"),
                "asset_classes": selected.get("asset_classes"),
                "universe": selected.get("universe"),
                "start_date": selected["start_date"],
                "end_date": selected["end_date"],
                "execution_policy": metrics.get("signal_execution_evidence", {}).get(
                    "execution_policy", "legacy_unknown"
                ),
                "execution_timing_policy": metrics.get("execution_timing", {}).get(
                    "policy_id", "legacy_unknown"
                ),
                "availability_mode": metrics.get("execution_timing", {}).get(
                    "availability_mode", "legacy_unknown"
                ),
            }
            trials.add(content_fingerprint({**context, "formula_ast": ast}))
            tested = metrics.get("parameter_robustness", {}).get("tested_results", [])
            if tested:
                variants = build_formula_parameter_variants(
                    formula_ast=ast,
                    parameter_values=draft.get("parameter_values", {}),
                    parameter_ranges=draft.get("parameter_ranges", {}),
                )
                by_params = {
                    content_fingerprint(item.params): item for item in variants
                }
                for item in tested:
                    variant = by_params.get(content_fingerprint(item.get("params", {})))
                    if variant is None:
                        raise StrategyResearchRejected(
                            "research_trial_panel_binding_invalid"
                        )
                    trials.add(
                        content_fingerprint(
                            {**context, "formula_ast": variant.formula_ast}
                        )
                    )
            sources.append(
                {
                    "backtest_run_id": row["backtest_run_id"],
                    "source_fingerprint": content_fingerprint(
                        {
                            "contract": draft,
                            "selection": selected,
                            "metrics": metrics,
                            "result_id": row["canonical_backtest_result_id"],
                        }
                    ),
                }
            )
        scope = {
            "universe": sorted(selection.universe),
            "frequency": selection.frequency,
            "cost_model_reference": selection.cost_model_reference,
            "research_start": selection.start_date,
            "research_end": selection.end_date,
        }
        core = {
            "research_family_id": "research-family:" + content_fingerprint(scope),
            "scope": scope,
            "trial_fingerprints": sorted(trials),
            "nominal_trial_count": len(trials),
            "sources": sources,
            "trials_assumed_independent": False,
        }
        return {**core, "evidence_fingerprint": content_fingerprint(core)}

    def research_backtest_result(self, result_id: int) -> JsonObject:
        """Read the original scored result for final-evaluation source replay."""
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE id=?", (result_id,)
            ).fetchone()
            value = (
                with_backtest_invalidation(conn, dict(row)) if row is not None else None
            )
        if value is None:
            raise LookupError("research_backtest_result_missing")
        if blocker := backtest_evidence_blocker(value):
            raise StrategyResearchRejected(blocker)
        value.pop("evidence_invalidation")
        return value
