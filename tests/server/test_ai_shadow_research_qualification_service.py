from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
    FormulaBinding,
)
from server.ai_runtime.strategy_research_privacy import (
    NORMALIZED_RESEARCH_NOTIONAL,
    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
)
from server.contracts.ai_shadow_research_qualification import (
    public_qualification_candidate_projection,
    public_qualification_run_projection,
    qualification_formula_semantic_fingerprint,
)
from server.contracts.strategy_research import StrategyResearchSelection
from server.services.account_qualification_reuse import (
    select_oldest_retryable_source_run_id,
)
from server.services.ai_shadow_research_qualification import (
    AiShadowResearchQualificationService,
)

MARKET_DATE = "2026-08-31"
DATASET_ID = "sha256:" + "d" * 64
VALUATION_ID = "valuation-" + "a" * 64
LEDGER_FINGERPRINT = "b" * 64
REVIEWED_COST = (
    "karkinos.backtest.reviewed_account_fee_schedule.v1:"
    + "fee_review_"
    + "c" * 32
    + ":"
    + "d" * 64
)


def _formula() -> dict[str, Any]:
    average = {
        "op": "rolling_mean",
        "input": {"op": "field", "name": "close"},
        "window": 3,
    }
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "cross",
            "left": {"op": "field", "name": "close"},
            "right": average,
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": average,
        },
        "position_size": {"op": "equal_weight"},
    }


def _source_selection() -> StrategyResearchSelection:
    return StrategyResearchSelection(
        saved_backtest_result_id=10,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id=DATASET_ID,
        start_date="2026-01-02",
        end_date=MARKET_DATE,
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
    )


def _draft(ordinal: int, selection: StrategyResearchSelection) -> dict[str, Any]:
    draft = {
        "draft_id": f"draft-{ordinal}",
        "economic_hypothesis": f"Frozen hypothesis {ordinal}",
        "risk_impact": "The strategy can lose capital.",
        "failure_conditions": ["OOS excess return turns non-positive."],
        "limitations": ["Historical evidence only."],
        "anti_lookahead_assumptions": ["Signals use completed daily bars."],
        "formula_ast": _formula(),
        "parameter_values": {},
        "parameter_ranges": {},
        "selected_universe": list(selection.universe),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": selection.frequency,
        "cost_model_reference": selection.cost_model_reference,
        "validation": {"status": "valid", "errors": []},
    }
    draft["formula_fingerprint"] = FormulaBinding(
        formula_ast=draft["formula_ast"],
        universe=selection.universe,
        dataset_snapshot_id=selection.dataset_snapshot_id,
        start_date=selection.start_date,
        end_date=selection.end_date,
        frequency=selection.frequency,
        cost_model_reference=selection.cost_model_reference,
        anti_lookahead_assumptions=tuple(draft["anti_lookahead_assumptions"]),
        parameter_values={},
        parameter_ranges={},
        initial_cash=selection.initial_cash,
    ).fingerprint
    return draft


class FakeDailyArtifactStore:
    def __init__(self, batch: dict[str, Any]) -> None:
        self.batches = {str(batch["run_id"]): deepcopy(batch)}

    def publish(self, batch: dict[str, Any]) -> None:
        self.batches[str(batch["run_id"])] = deepcopy(batch)

    def supersede(self, run_id: str) -> None:
        self.batches.pop(run_id, None)

    def list_verified_research_artifact_pairs(self) -> list[dict[str, Any]]:
        return sorted(
            [
                {
                    "run_id": batch["run_id"],
                    "market_date": batch["market_date"],
                    "selection_id": batch["selection_id"],
                    "selection_fingerprint": batch["selection_fingerprint"],
                    "backup_artifact_fingerprint": batch["backup_artifact_fingerprint"],
                }
                for batch in self.batches.values()
            ],
            key=lambda item: (item["market_date"], item["run_id"]),
        )

    def load_verified_research_candidate_strategies(
        self, *, run_id: str
    ) -> dict[str, Any]:
        return deepcopy(self.batches[run_id])


class FakeResearchStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.drafts: dict[tuple[str, str], dict[str, Any]] = {}
        self.backtests: dict[str, dict[str, Any]] = {}
        self.critiques: dict[str, dict[str, Any]] = {}

    def get_session(self, session_id: str) -> dict[str, Any]:
        return deepcopy(self.sessions[session_id])

    def get_draft(self, session_id: str, draft_id: str) -> dict[str, Any]:
        return deepcopy(self.drafts[(session_id, draft_id)])

    def get_backtest(self, backtest_run_id: str) -> dict[str, Any]:
        return deepcopy(self.backtests[backtest_run_id])

    def get_critique(self, critique_id: str) -> dict[str, Any]:
        return deepcopy(self.critiques[critique_id])


def _result_row(result_id: int, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": result_id,
        "initial_cash": result["initial_cash"],
        "final_equity": result["final_equity"],
        "total_return": result["total_return"],
        "sharpe": result["sharpe"],
        "max_drawdown": result["max_drawdown"],
        "equity_curve_json": json.dumps(result["equity_curve"]),
        "metrics_json": json.dumps(result["metrics_json"]),
        "cost_summary_json": json.dumps(result["cost_summary_json"]),
    }


class FakeDatabase:
    def __init__(self, valuation: dict[str, Any]) -> None:
        self.valuation = valuation
        self.rows: dict[int, dict[str, Any]] = {}
        self.next_id = 100
        self.automation_runs: dict[str, dict[str, Any]] = {}

    def get_valuation_snapshot_sync(self, snapshot_id: str) -> dict[str, Any] | None:
        return deepcopy(self.valuation) if snapshot_id == VALUATION_ID else None

    def insert_result(self, result: dict[str, Any]) -> int:
        result_id = self.next_id
        self.next_id += 1
        self.rows[result_id] = _result_row(result_id, result)
        return result_id

    def insert_backtest_values(self, values: dict[str, Any]) -> int:
        result_id = self.next_id
        self.next_id += 1
        self.rows[result_id] = {
            "id": result_id,
            "initial_cash": values["initial_cash"],
            "final_equity": values["final_equity"],
            "total_return": values["total_return"],
            "sharpe": values["sharpe"],
            "max_drawdown": values["max_dd"],
            "equity_curve_json": values["equity_curve_json"],
            "metrics_json": values["metrics_json"],
            "cost_summary_json": values["cost_summary_json"],
        }
        return result_id

    async def get_backtest_result(self, result_id: int) -> dict[str, Any] | None:
        row = self.rows.get(result_id)
        return deepcopy(row) if row else None

    def claim_automation_run_once_sync(self, **values: Any) -> dict[str, Any]:
        run_id = str(values["run_id"])
        existing = self.automation_runs.get(run_id)
        if existing is not None:
            return {"claimed": False, "run": deepcopy(existing)}
        row = {
            "run_id": run_id,
            "run_type": values["run_type"],
            "run_date": values["run_date"],
            "status": "claimed",
            "execution_mode": values["execution_mode"],
            "started_at": values["claimed_at"],
            "finished_at": None,
            "source_ref": None,
            "payload": deepcopy(values["payload"]),
            "created_at": values["claimed_at"],
        }
        self.automation_runs[run_id] = row
        return {"claimed": True, "run": deepcopy(row)}

    def upsert_automation_run_sync(self, values: dict[str, Any]) -> dict[str, Any]:
        existing = self.automation_runs.get(str(values["run_id"]), {})
        row = {
            **existing,
            **deepcopy(values),
            "created_at": existing.get("created_at", values["started_at"]),
        }
        self.automation_runs[str(values["run_id"])] = row
        return deepcopy(row)

    def list_automation_runs_sync(self, **filters: Any) -> list[dict[str, Any]]:
        rows = list(reversed(list(self.automation_runs.values())))
        return [
            deepcopy(row)
            for row in rows
            if (
                filters.get("run_type") is None
                or row["run_type"] == filters["run_type"]
            )
            and (
                filters.get("run_date") is None
                or row["run_date"] == filters["run_date"]
            )
        ][: int(filters.get("limit", 20))]


class FakeShadowStore:
    def __init__(self, db: FakeDatabase) -> None:
        self.db = db
        self.source_run = {
            "run_id": "source-run",
            "market_date": MARKET_DATE,
            "status": "completed",
        }
        self.sources: dict[str, dict[str, Any]] = {}
        self.run: dict[str, Any] | None = None
        self.candidates: list[dict[str, Any]] = []
        self.baseline_by_fingerprint: dict[str, int] = {}

    def get_run(self, run_id: str) -> dict[str, Any]:
        assert run_id == "source-run"
        return deepcopy(self.source_run)

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        return deepcopy(self.sources[candidate_id])

    def save_baseline(self, **values: Any) -> int:
        fingerprint = values["baseline_fingerprint"]
        if fingerprint not in self.baseline_by_fingerprint:
            self.baseline_by_fingerprint[fingerprint] = self.db.insert_result(
                values["result"]
            )
        return self.baseline_by_fingerprint[fingerprint]

    def create_or_get_qualification_run(self, **values: Any):
        if self.run is not None:
            return deepcopy(self.run), True
        self.run = {
            "qualification_run_id": "qualification-run",
            **{key: value for key, value in values.items() if key != "now"},
            "status": "running",
            "selection": None,
            "blockers": [],
            "failure_code": None,
            "created_at": values["now"],
            "updated_at": values["now"],
        }
        return deepcopy(self.run), False

    def list_qualification_runs(
        self, *, limit: int, source_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = (
            [self.run]
            if self.run is not None
            and (source_run_id is None or self.run["source_run_id"] == source_run_id)
            else []
        )
        return deepcopy(rows[:limit])

    def list_qualification_candidates(self, qualification_run_id: str):
        assert qualification_run_id == "qualification-run"
        return deepcopy(self.candidates)

    def save_qualification_candidate(self, **values: Any) -> dict[str, Any]:
        existing = next(
            (
                item
                for item in self.candidates
                if item["source_candidate_id"] == values["source_candidate_id"]
            ),
            None,
        )
        if existing is not None:
            return deepcopy(existing)
        candidate = {
            "qualification_candidate_id": (
                "qualified-" + values["source_candidate_id"]
            ),
            **values,
            "created_at": values["now"],
            "comparison_fingerprint": content_fingerprint(values["comparison"]),
        }
        self.candidates.append(candidate)
        return deepcopy(candidate)

    def save_qualification_candidate_with_backtest(
        self,
        *,
        backtest_values: dict[str, Any],
        candidate_evidence_builder,
        **values: Any,
    ) -> dict[str, Any]:
        existing = next(
            (
                item
                for item in self.candidates
                if item["source_candidate_id"] == values["source_candidate_id"]
            ),
            None,
        )
        if existing is not None:
            return deepcopy(existing)
        result_id = self.db.insert_backtest_values(backtest_values)
        try:
            comparison, status, recommendation = candidate_evidence_builder(
                self.db.rows[result_id]
            )
            return self.save_qualification_candidate(
                **values,
                candidate_result_id=result_id,
                comparison=comparison,
                status=status,
                recommendation=recommendation,
            )
        except Exception:
            self.db.rows.pop(result_id, None)
            raise

    def finish_qualification_run(self, qualification_run_id: str, **values: Any):
        assert self.run is not None
        assert qualification_run_id == self.run["qualification_run_id"]
        self.run.update(values)
        self.run["updated_at"] = values["now"]
        return deepcopy(self.run)

    def get_public_qualification_run(self, qualification_run_id: str):
        assert self.run is not None
        return public_qualification_run_projection(self.run)

    def list_public_qualification_candidates(self, qualification_run_id: str):
        return [
            public_qualification_candidate_projection(item) for item in self.candidates
        ]


class FakeCaptureRecord:
    def __init__(self, *, total_equity: str) -> None:
        self.reference_id = "ai-evidence-account"
        self.tool_name = "account_state_projection.read"
        self.status = "complete"
        self.authoritative = True
        self.persisted_facts_only = True
        self.valuation_snapshot_id = VALUATION_ID
        self.ledger_cutoff_id = 42
        self.ledger_fingerprint = LEDGER_FINGERPRINT
        self.record_fingerprint = "e" * 64
        identity = {
            "valuation_snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": 42,
            "valuation_status": "complete",
            "total_equity": total_equity,
        }
        self.payload = {"summary": dict(identity), "snapshot": dict(identity)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "persisted_facts_only": True,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "ledger_cutoff_id": self.ledger_cutoff_id,
            "ledger_fingerprint": self.ledger_fingerprint,
            "record_fingerprint": self.record_fingerprint,
            "payload": deepcopy(self.payload),
        }


class FakeCaptureService:
    def __init__(self) -> None:
        self.calls = 0
        self.record = FakeCaptureRecord(total_equity="750000")

    async def capture(self, request: Any, *, write_guard: Any | None = None) -> Any:
        if callable(write_guard):
            write_guard()
        self.calls += 1
        return SimpleNamespace(
            context=SimpleNamespace(
                valuation_snapshot_id=VALUATION_ID,
                ledger_cutoff_id=42,
                ledger_fingerprint=LEDGER_FINGERPRINT,
                persisted_facts_only=True,
            ),
            records=(self.record,),
        )


class FakeRequest:
    def model_dump_json(self) -> str:
        return "{}"


def _backtest_result(*, cash: float, score: float) -> dict[str, Any]:
    return {
        "initial_cash": cash,
        "final_equity": cash * (1 + score),
        "total_return": score,
        "annual_return": score,
        "sharpe": 1 + score,
        "sortino": 1 + score,
        "max_drawdown": 0.1,
        "win_rate": 0.5,
        "duration_days": 100,
        "equity_curve": [],
        "metrics_json": {
            "evidence_bundle": {"total_cost": 0},
            "dataset_snapshot": {
                "snapshot_id": DATASET_ID,
                "data_quality": {"status": "ok", "issues": []},
            },
            "fee_component_evidence": {
                "cost_model_reference": REVIEWED_COST,
                "fee_schedule_fingerprint": "3" * 64,
                "account_specific": True,
                "broker_statement_reconciled": True,
                "fee_schedule_binding": {
                    "account_truth_source_fingerprint": "4" * 64,
                    "account_truth_scope_fingerprint": "5" * 64,
                },
            },
        },
        "cost_summary_json": {
            "total_commission": 0,
            "total_slippage": 0,
            "total_trades": 0,
            "gross_turnover": 0,
        },
    }


class FakeBaselinePreparer:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, policy: Any, **values: Any) -> Any:
        self.calls += 1
        assert values["initial_cash_override"] == 750000
        return SimpleNamespace(
            market_date=MARKET_DATE,
            snapshot={"snapshot_id": DATASET_ID},
            cost_model_reference=REVIEWED_COST,
            result=_backtest_result(cash=750000, score=0),
            request=FakeRequest(),
            fingerprint="baseline-qualification-fingerprint",
        )


class FakeBacktestAdapter:
    def __init__(self) -> None:
        self.calls: list[StrategyResearchSelection] = []

    def run(self, *, selection: StrategyResearchSelection, draft: dict, **_: Any):
        self.calls.append(selection)
        ordinal = int(str(draft["draft_id"]).rsplit("-", maxsplit=1)[1])
        return (
            _backtest_result(cash=selection.initial_cash, score=ordinal / 100),
            FakeRequest(),
        )


@dataclass(frozen=True)
class FakeGate:
    score: float

    @property
    def passed(self) -> bool:
        return True

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": "pass",
            "blockers": [],
            "checks": [
                {
                    "name": "after_tax_excess_return",
                    "status": "pass",
                    "evidence": {"after_tax_excess_return": self.score},
                },
                {
                    "name": "after_cost_oos_excess",
                    "status": "pass",
                    "evidence": {
                        "mean_oos_excess_return": self.score,
                        "worst_oos_excess_return": self.score / 2,
                    },
                },
                {
                    "name": "drawdown",
                    "status": "pass",
                    "evidence": {"candidate_max_drawdown": 0.1},
                },
                {
                    "name": "turnover",
                    "status": "pass",
                    "evidence": {"candidate_turnover_to_initial_cash": 0.1},
                },
            ],
            "evidence_fingerprint": "f" * 64,
        }


def _gate_builder(*, candidate: dict[str, Any], **_: Any) -> FakeGate:
    return FakeGate(score=float(candidate["total_return"]))


def _harness(
    *,
    valuation_trade_date: str = MARKET_DATE,
    valuation_as_of: str | None = None,
    latest_closed_market_date: str = MARKET_DATE,
    now: str = "2026-08-31T16:00:00+08:00",
):
    selection = _source_selection()
    source_selection = {
        "schema_version": "karkinos.ai.normalized_source_selection_binding.v1",
        "universe": list(selection.universe),
        "asset_classes": list(selection.asset_classes),
        "asset_class_policy": "daily_candidate_stock_only",
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "start_date": selection.start_date,
        "end_date": selection.end_date,
        "frequency": selection.frequency,
        "initial_cash": selection.initial_cash,
        "notional_policy_id": NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
        "cost_model_reference": selection.cost_model_reference,
        "account_fact_binding": "not_applicable_strategy_only_research",
        "saved_backtest_result_id": None,
        "saved_backtest_result_id_status": ("not_present_in_privacy_minimized_backup"),
        "contains_private_account_identifiers": False,
        "authority_effect": "research_only",
    }
    valuation = {
        "snapshot_id": VALUATION_ID,
        "as_of": valuation_as_of or f"{valuation_trade_date}T15:00:00+08:00",
        "trade_date": valuation_trade_date,
        "status": "complete",
        "ledger_cutoff_id": 42,
        "ledger_fingerprint": LEDGER_FINGERPRINT,
        "quote_set_fingerprint": "c" * 64,
        "valuation_policy": "persisted-close-v1",
    }
    db = FakeDatabase(valuation)
    store = FakeShadowStore(db)
    research = FakeResearchStore()
    verified_candidates = []
    for ordinal in range(1, 6):
        draft = _draft(ordinal, selection)
        session_id = f"session-{ordinal}"
        backtest_id = f"backtest-{ordinal}"
        critique_id = f"critique-{ordinal}"
        source_comparison = {
            "research_capital_mode": "normalized_notional",
            "account_qualification_status": "not_evaluated",
            "iteration_lineage": {
                "iteration_number": ordinal,
                "total_iterations": 5,
                "formula_fingerprint": draft["formula_fingerprint"],
            },
        }
        source_candidate_id = f"source-candidate-{ordinal}"
        store.sources[source_candidate_id] = {
            "candidate_id": source_candidate_id,
            "run_id": "source-run",
            "session_id": session_id,
            "draft_id": draft["draft_id"],
            "backtest_run_id": backtest_id,
            "critique_id": critique_id,
            "baseline_result_id": 10,
            "candidate_result_id": 10 + ordinal,
            "status": "evaluated_research_only",
            "recommendation": "formula_research_candidate",
            "comparison": source_comparison,
        }
        research.sessions[session_id] = {
            "status": "completed",
            "request_json": canonical_json({"selection": selection.to_dict()}),
            "selection_fingerprint": selection.fingerprint,
        }
        research.drafts[(session_id, draft["draft_id"])] = {
            "contract": draft,
            "artifact_fingerprint": content_fingerprint(draft),
            "formula_fingerprint": draft["formula_fingerprint"],
        }
        research.backtests[backtest_id] = {
            "status": "completed",
            "session_id": session_id,
            "draft_id": draft["draft_id"],
            "formula_fingerprint": draft["formula_fingerprint"],
            "canonical_backtest_result_id": 10 + ordinal,
        }
        critique_artifact = {"summary": f"Frozen critique {ordinal}"}
        research.critiques[critique_id] = {
            "critique_id": critique_id,
            "status": "completed",
            "session_id": session_id,
            "draft_id": draft["draft_id"],
            "backtest_run_id": backtest_id,
            "artifact": critique_artifact,
            "artifact_fingerprint": content_fingerprint(critique_artifact),
        }
        verified_candidates.append(
            {
                "candidate_id": source_candidate_id,
                "draft_id": draft["draft_id"],
                "formula_fingerprint": draft["formula_fingerprint"],
                "source_comparison_fingerprint": content_fingerprint(source_comparison),
                "strategy_artifact_fingerprint": content_fingerprint(draft),
                "strategy": draft,
                "iteration_number": ordinal,
            }
        )
    batch = {
        "run_id": "source-run",
        "market_date": MARKET_DATE,
        "selection_id": "source-selection",
        "selection_fingerprint": "1" * 64,
        "backup_artifact_fingerprint": "2" * 64,
        "source_research_selection": source_selection,
        "expected_candidate_count": 5,
        "candidate_strategies": verified_candidates,
        "provider_contact_performed": False,
        "changes_capital_authority": False,
    }
    capture = FakeCaptureService()
    baseline = FakeBaselinePreparer()
    adapter = FakeBacktestAdapter()
    fee = SimpleNamespace(
        cost_model_reference=REVIEWED_COST,
        commission_calc=object(),
        fee_evidence={
            "account_specific": True,
            "broker_statement_reconciled": True,
            "fee_schedule_reviewed_asset_classes": ["stock"],
            "fee_notional_covered_asset_classes": ["stock"],
            "fee_schedule_fingerprint": "3" * 64,
            "account_truth_source_fingerprint": "4" * 64,
            "account_truth_scope_fingerprint": "5" * 64,
        },
    )
    fee_calls: list[dict[str, Any]] = []

    def resolve_fee_schedule(**values: Any) -> Any:
        fee_calls.append(values)
        return fee

    service = AiShadowResearchQualificationService(
        db=db,
        store=store,
        daily_artifact_store=FakeDailyArtifactStore(batch),
        research_store=research,
        data_store=object(),
        capture_service=capture,
        account_identity_reader=lambda: deepcopy(valuation),
        account_evidence_reader=lambda reference_id: (
            capture.record if reference_id == capture.record.reference_id else None
        ),
        reviewed_fee_identity_reader=lambda _selection: {
            "status": "active",
            "review": {
                "review_id": "fee_review_" + "c" * 32,
                "decision": "accepted",
                "review_fingerprint": "sha256:" + "d" * 64,
                "schedule_fingerprint": "3" * 64,
                "account_truth_source_fingerprint": "4" * 64,
                "account_truth_scope_fingerprint": "5" * 64,
                "effective_start_date": "2026-01-01",
                "effective_end_date": "2026-12-31",
                "preview": {"reviewed_asset_classes": ["stock"]},
            },
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": False,
        },
        dataset_snapshot_replay_reader=lambda snapshot: {
            "status": "pass",
            "snapshot_id": snapshot.get("snapshot_id"),
            "provider_contacted": False,
        },
        reviewed_fee_schedule_resolver=resolve_fee_schedule,
        now=lambda: now,
        latest_closed_trading_date_reader=(lambda _db, _now: latest_closed_market_date),
        baseline_preparer=baseline,
        backtest_adapter=adapter,
        advancement_gate_builder=_gate_builder,
    )
    return service, store, capture, baseline, adapter, fee_calls


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
async def test_provider_free_qualification_replays_all_five_and_is_idempotent():
    service, store, capture, baseline, adapter, fee_calls = _harness()

    first = await service.run_once()
    second = await service.run_once()

    assert first["status"] == "completed"
    assert first["run"]["winner_qualification_candidate_id"] == (
        "qualified-source-candidate-5"
    )
    assert len(first["candidates"]) == 5
    assert second["reused"] is True
    assert len(adapter.calls) == 5
    assert all(item.initial_cash == 750000 for item in adapter.calls)
    assert all(item.cost_model_reference == REVIEWED_COST for item in adapter.calls)
    assert capture.calls == 1
    assert baseline.calls == 1
    assert len(store.candidates) == 5
    assert len(fee_calls) == 1
    assert all(call["account_truth_as_of"] is None for call in fee_calls)
    public_json = json.dumps(first, ensure_ascii=False)
    assert "research_initial_cash" not in public_json
    assert "750000" not in public_json
    assert first["provider_call_performed"] is False
    assert first["broker_order_created"] is False
    assert first["capital_authority_granted"] is False


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    ("clock", "deferred"),
    [
        ("2026-09-01T08:59:00+08:00", False),
        ("2026-09-01T09:00:00+08:00", True),
        ("2026-09-01T09:35:00+08:00", True),
        ("2026-09-01T10:00:00+08:00", False),
    ],
)
async def test_qualification_market_open_blackout_boundaries(
    clock: str,
    deferred: bool,
) -> None:
    service, store, capture, baseline, adapter, fee_calls = _harness(
        now=clock,
        valuation_trade_date=MARKET_DATE,
        latest_closed_market_date=MARKET_DATE,
    )

    result = await service.run_once()

    if deferred:
        assert result["status"] == "deferred"
        assert result["deferred_reason"] == "qualification_market_open_blackout"
        assert result["terminal"] is False
        assert result["retryable"] is True
        assert "qualification_attempt" not in result
        assert store.run is None
        assert service._db.automation_runs == {}
        assert capture.calls == 0
        assert baseline.calls == 0
        assert adapter.calls == []
        assert fee_calls == []
    else:
        assert result["status"] == "completed"
        assert capture.calls == 1
        assert baseline.calls == 1
        assert len(adapter.calls) == 5
        assert len(fee_calls) == 1


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
async def test_0859_admission_crossing_0900_defers_without_capture_or_attempt() -> None:
    service, store, capture, baseline, adapter, fee_calls = _harness(
        now="2026-09-01T08:59:00+08:00",
    )
    instants = iter(
        (
            "2026-09-01T08:59:00+08:00",
            "2026-09-01T08:59:30+08:00",
            "2026-09-01T09:00:00+08:00",
        )
    )
    last = "2026-09-01T09:00:00+08:00"

    def crossing_clock() -> str:
        nonlocal last
        last = next(instants, last)
        return last

    service._now = crossing_clock

    result = await service.run_once()

    assert result["status"] == "deferred"
    assert result["terminal"] is False
    assert result["retryable"] is True
    assert "qualification_attempt" not in result
    assert store.run is None
    assert service._db.automation_runs == {}
    assert capture.calls == 0
    assert baseline.calls == 0
    assert adapter.calls == []
    assert fee_calls == []


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
async def test_oldest_retryable_source_catches_up_after_newer_publication() -> None:
    service, store, _capture, _baseline, _adapter, _fee_calls = _harness(
        now="2026-09-01T10:00:00+08:00",
    )
    daily = service._daily_artifact_store
    original_identity_reader = service._account_identity_reader

    def unavailable_account_truth() -> None:
        raise RuntimeError("qualification_account_truth_unavailable")

    service._account_identity_reader = unavailable_account_truth
    blocked = await service.run_once()
    assert blocked["status"] == "blocked"
    assert blocked["qualification_attempt"]["source_run_id"] == "source-run"
    assert store.run is None

    newer = deepcopy(daily.batches["source-run"])
    newer.update(
        {
            "run_id": "source-run-2",
            "market_date": "2026-09-01",
            "selection_id": "source-selection-2",
            "selection_fingerprint": "6" * 64,
            "backup_artifact_fingerprint": "7" * 64,
        }
    )
    daily.publish(newer)
    assert select_oldest_retryable_source_run_id(daily, store) == "source-run"

    service._account_identity_reader = original_identity_reader
    caught_up = await service.run_once()
    assert caught_up["status"] == "completed"
    assert caught_up["run"]["source_run_id"] == "source-run"
    assert select_oldest_retryable_source_run_id(daily, store) == "source-run-2"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_newer_terminal_state_supersedes_stale_running_history_for_backlog() -> None:
    class Daily:
        @staticmethod
        def list_verified_research_artifact_pairs() -> list[dict[str, str]]:
            return [
                {"run_id": "D1"},
                {"run_id": "D2"},
            ]

    class Qualifications:
        @staticmethod
        def list_qualification_runs(*, limit: int, source_run_id: str):
            assert limit == 200
            if source_run_id == "D1":
                return [
                    {
                        "qualification_run_id": "d1-terminal",
                        "status": "completed",
                        "updated_at": "2026-09-02T11:00:00+08:00",
                    },
                    {
                        "qualification_run_id": "d1-stale-running",
                        "status": "running",
                        "updated_at": "2026-09-01T11:00:00+08:00",
                    },
                ]
            return []

    assert select_oldest_retryable_source_run_id(Daily(), Qualifications()) == "D2"


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    "drift",
    [
        "candidate_count",
        "candidate_result",
        "candidate_source_identity",
        "comparison_gate",
        "baseline_result",
        "final_selection",
    ],
)
async def test_terminal_reuse_revalidates_all_five_evidence_layers(
    drift: str,
) -> None:
    service, store, capture, baseline, adapter, _fee_calls = _harness()
    assert (await service.run_once())["status"] == "completed"
    assert store.run is not None
    if drift == "candidate_count":
        store.candidates.pop()
    elif drift == "candidate_result":
        result_id = int(store.candidates[0]["candidate_result_id"])
        service._db.rows[result_id]["final_equity"] += 1
    elif drift == "candidate_source_identity":
        store.candidates[0]["source_formula_fingerprint"] = "sha256:" + "9" * 64
    elif drift == "comparison_gate":
        comparison = store.candidates[0]["comparison"]
        comparison["promotion_gate"] = {
            **comparison["promotion_gate"],
            "status": "blocked",
        }
        store.candidates[0]["comparison_fingerprint"] = content_fingerprint(comparison)
    elif drift == "baseline_result":
        result_id = int(store.run["baseline_result_id"])
        service._db.rows[result_id]["final_equity"] += 1
    else:
        store.run["selection"] = {
            **store.run["selection"],
            "winner_qualification_candidate_id": "qualified-source-candidate-1",
        }

    result = await service.run_once()

    assert result["status"] == "blocked"
    assert result["failure_code"] == (
        "qualification_terminal_evidence_revalidation_failed"
    )
    assert capture.calls == 2
    assert baseline.calls == 2
    assert len(adapter.calls) == 5


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
async def test_terminal_reuse_falls_back_and_blocks_on_current_fee_drift() -> None:
    service, _store, capture, baseline, adapter, fee_calls = _harness()
    assert (await service.run_once())["status"] == "completed"

    service._reviewed_fee_identity_reader = lambda _selection: {
        "status": "blocked",
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
    }

    def reject_drifted_fee(**values: Any) -> None:
        fee_calls.append(values)
        raise RuntimeError("qualification_reviewed_fee_schedule_drift")

    service._reviewed_fee_schedule_resolver = reject_drifted_fee
    drifted = await service.run_once()

    assert drifted["status"] == "blocked"
    assert drifted["failure_code"] == "qualification_reviewed_fee_schedule_drift"
    assert capture.calls == 2
    assert baseline.calls == 1
    assert len(adapter.calls) == 5
    assert len(fee_calls) == 2


@pytest.mark.unit
@pytest.mark.trading_safety
def test_superseded_retryable_source_is_not_selected() -> None:
    service, store, *_ = _harness()
    daily = service._daily_artifact_store
    newer = deepcopy(daily.batches["source-run"])
    newer.update(
        {
            "run_id": "source-run-2",
            "market_date": "2026-09-01",
            "selection_id": "source-selection-2",
            "selection_fingerprint": "6" * 64,
            "backup_artifact_fingerprint": "7" * 64,
        }
    )
    daily.publish(newer)
    daily.supersede("source-run")

    assert store.run is None
    assert select_oldest_retryable_source_run_id(daily, store) == "source-run-2"


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
async def test_resume_retains_a_previously_persisted_candidate_failure():
    service, store, _capture, _baseline, adapter, _fee_calls = _harness()

    class FailFirstCandidate:
        def __init__(self) -> None:
            self.failed_calls = 0

        def run(self, *, selection, draft, **values):
            if draft["draft_id"] == "draft-1":
                self.failed_calls += 1
                raise RuntimeError("qualification_first_replay_failed")
            return adapter.run(selection=selection, draft=draft, **values)

    failing_adapter = FailFirstCandidate()
    service._backtest_adapter = failing_adapter
    first = await service.run_once()
    assert first["status"] == "failed"
    assert failing_adapter.failed_calls == 1
    assert len(store.candidates) == 5

    assert store.run is not None
    store.run.update(
        {
            "status": "running",
            "selection": None,
            "blockers": [],
            "failure_code": None,
        }
    )
    second = await service.run_once()

    assert second["status"] == "failed"
    assert second["run"]["failure_code"] == (
        "qualification_candidate_replay_incomplete"
    )
    assert failing_adapter.failed_calls == 1
    assert len(adapter.calls) == 4


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
async def test_qualification_allows_current_valuation_after_source_market_date():
    service, store, capture, baseline, adapter, fee_calls = _harness(
        valuation_trade_date="2026-09-01",
        latest_closed_market_date="2026-09-01",
        now="2026-09-01T16:00:00+08:00",
    )

    result = await service.run_once()

    assert result["status"] == "completed"
    assert result["run"]["market_date"] == MARKET_DATE
    assert result["run"]["valuation_snapshot_id"] == VALUATION_ID
    assert len(adapter.calls) == 5
    assert capture.calls == 1
    assert baseline.calls == 1
    assert fee_calls[0]["account_truth_as_of"] is None


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    (
        "valuation_trade_date",
        "valuation_as_of",
        "latest_closed_market_date",
        "failure_code",
    ),
    [
        (
            "2026-09-02",
            None,
            "2026-09-01",
            "qualification_valuation_snapshot_future_dated",
        ),
        (
            "2026-08-31",
            None,
            "2026-09-01",
            "qualification_valuation_snapshot_stale",
        ),
        (
            "2026-09-01",
            "2026-09-01T16:06:00+08:00",
            "2026-09-01",
            "qualification_valuation_snapshot_future_dated",
        ),
    ],
)
async def test_qualification_blocks_future_or_stale_current_valuation_before_capture(
    valuation_trade_date: str,
    valuation_as_of: str | None,
    latest_closed_market_date: str,
    failure_code: str,
):
    service, store, capture, baseline, adapter, fee_calls = _harness(
        valuation_trade_date=valuation_trade_date,
        valuation_as_of=valuation_as_of,
        latest_closed_market_date=latest_closed_market_date,
        now="2026-09-01T16:00:00+08:00",
    )

    result = await service.run_once()
    replay = await service.run_once()

    assert result["status"] == "blocked"
    assert result["failure_code"] == failure_code
    assert result["blockers"] == [failure_code]
    assert result["run"] is None
    attempt = result["qualification_attempt"]
    assert attempt["source_run_id"] == "source-run"
    assert attempt["status"] == "blocked"
    assert attempt["failure_code"] == failure_code
    assert attempt["blockers"] == [failure_code]
    assert attempt["provider_call_performed"] is False
    assert attempt["broker_order_created"] is False
    assert attempt["ledger_mutation_performed"] is False
    assert attempt["capital_authority_granted"] is False
    assert attempt["private_account_values_redacted"] is True
    assert replay["qualification_attempt"] == attempt
    assert len(service._db.automation_runs) == 1
    assert "750000" not in json.dumps(attempt)
    assert "ai-evidence-account" not in json.dumps(attempt)
    assert store.run is None
    assert capture.calls == 0
    assert baseline.calls == 0
    assert adapter.calls == []
    assert fee_calls == []


@pytest.mark.unit
def test_formula_semantic_identity_excludes_only_account_cost_rebinding():
    source = _draft(1, _source_selection())
    rebound = deepcopy(source)
    rebound["cost_model_reference"] = REVIEWED_COST

    assert qualification_formula_semantic_fingerprint(source) == (
        qualification_formula_semantic_fingerprint(rebound)
    )
    rebound["dataset_snapshot_id"] = "sha256:" + "9" * 64
    assert qualification_formula_semantic_fingerprint(source) != (
        qualification_formula_semantic_fingerprint(rebound)
    )
