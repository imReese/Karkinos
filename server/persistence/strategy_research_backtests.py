"""Formula-backtest repository operations for AI strategy research."""

from __future__ import annotations

from typing import Any

from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.strategy_research import FormulaBacktestRequest


class StrategyResearchBacktestRepositoryMixin:
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

    def research_trial_family(self, selection: Any) -> JsonObject:
        """Count scored semantic tests, including local sweeps and rejected drafts.

        Replays of an identical formula/data/cost test count once. Related earlier
        windows enter the nominal family; this does not claim independence.
        """
        import json

        from server.ai_runtime.formula_parameter_sweep import (
            build_formula_parameter_variants,
        )
        from server.contracts.strategy_research import StrategyResearchRejected

        with self._connect_readonly() as conn:
            if selection.has_sealed_holdout:
                for session in conn.execute(
                    "SELECT request_json FROM ai_strategy_research_sessions "
                    "WHERE context_snapshot_id IS NOT NULL OR run_claimed_at IS NOT NULL"
                ).fetchall():
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
        trials: set[str] = set()
        sources = []
        for raw in rows:
            row = dict(raw)
            selected = json.loads(row["request_json"]).get("selection", {})
            if (
                selection.has_sealed_holdout
                and row["canonical_backtest_result_id"] is not None
                and set(selected.get("universe", [])) & set(selection.universe)
                and selected.get("start_date", "") <= selection.sealed_end_date
                and selected.get("end_date", "") > selection.end_date
            ):
                raise StrategyResearchRejected("sealed_window_exposed_to_research")
            if (
                sorted(selected.get("universe", [])) != sorted(selection.universe)
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
        if row is None:
            raise LookupError("research_backtest_result_missing")
        return dict(row)
