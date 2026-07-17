from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    CaptureEvidenceType,
    CaptureSelectionError,
    HumanContextCaptureRequest,
)
from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.karkinos_source import PersistedKarkinosCaptureSource

NOW = "2026-07-13T12:30:00+00:00"
VALUATION_ID = "valuation-source-001"
LEDGER_CUTOFF_ID = 91
LEDGER_FINGERPRINT = "ledger-source-fingerprint-001"


class FixtureModel:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        for key, value in payload.items():
            setattr(self, key, value)

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return dict(self._payload)


class FixtureDatabase:
    def get_runtime_control_sync(self, key: str):
        assert key == "account_strategy_assignment"
        return None

    def get_valuation_snapshot_sync(self, snapshot_id: str):
        if snapshot_id != VALUATION_ID:
            return None
        return {
            "snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
            "as_of": NOW,
        }

    async def get_backtest_result(self, result_id: int):
        if result_id != 17:
            return None
        return {
            "id": 17,
            "created_at": NOW,
            "metrics_json": json.dumps(
                {
                    "research_evidence_bundle": {
                        "schema_version": "karkinos.research_evidence.v1",
                        "bundle_id": "research-17",
                        "gate_status": "degraded",
                    }
                }
            ),
        }

    def get_paper_shadow_run_sync(self, run_id: str):
        if run_id != "shadow-17":
            return None
        return {
            "run_id": "shadow-17",
            "input_fingerprint": "shadow-input-17",
            "status": "review_required",
            "created_at": NOW,
            "updated_at": NOW,
            "payload_json": json.dumps(
                {
                    "schema_version": "karkinos.paper_shadow_run.v1",
                    "execution_mode": "paper_shadow",
                }
            ),
            "limitations_json": json.dumps(["manual review required"]),
        }


def _request() -> HumanContextCaptureRequest:
    return HumanContextCaptureRequest(
        idempotency_key="source-all-001",
        requested_by="human:reese",
        research_question="Review all exact persisted sources",
        account_alias="primary",
        evidence_types=tuple(CaptureEvidenceType),
        confirmation=CAPTURE_CONFIRMATION,
        backtest_result_id=17,
        paper_shadow_run_id="shadow-17",
        strategy_id="dual_ma",
    )


def _portfolio() -> FixtureModel:
    return FixtureModel(
        {
            "cash": 1000.0,
            "total_equity": 3000.0,
            "positions": [],
            "allocation": [],
            "closed_positions": [],
            "position_review_items": [],
            "valuation_snapshot_id": VALUATION_ID,
            "valuation_as_of": NOW,
            "valuation_status": "complete",
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
        }
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_production_source_reuses_canonical_builders_and_exact_persisted_rows(
    monkeypatch,
):
    # Load the route before patching its source module so the route keeps its
    # real imported function after this test's monkeypatch is restored.
    import server.routes.account_truth  # noqa: F401

    portfolio = _portfolio()
    calls: list[str] = []

    async def build_portfolio(state):
        calls.append("portfolio")
        return portfolio

    async def build_account_state(state, *, snapshot):
        assert snapshot is portfolio
        calls.append("account_state")
        return FixtureModel(
            {
                "summary": {"positions_count": 0},
                "snapshot": portfolio.model_dump(mode="json"),
                "risks": [],
                "next_step": "manual review",
            }
        )

    async def build_operations(state):
        calls.append("operations")
        return {
            "schema_version": "karkinos.operations_today.v1",
            "generated_at": NOW,
            "conclusion_status": "degraded",
            "health": {"degraded": 1, "blocked": 0},
            "attention_items": [
                {
                    "schema_version": "karkinos.operations_attention_item.v1",
                    "subsystem_id": "strategy_candidates",
                    "status": "degraded",
                    "target": "decision",
                    "evidence": {"status": "0/1", "observed_at": NOW},
                    "next_action": "review_strategy_evidence",
                    "resolution_condition": "candidate_strategy_evidence_must_pass",
                    "task_fingerprint": "sha256:attention-fixture",
                    "manual_acknowledgement_clears_status": False,
                    "read_only_projection": True,
                    "provider_contacted": False,
                    "database_writes_performed": False,
                    "authorizes_execution": False,
                }
            ],
            "default_execution_mode": "manual_confirmation",
        }

    def build_contribution(db, assignment):
        assert assignment.strategy_id == "dual_ma"
        calls.append("strategy_contribution")
        return FixtureModel(
            {
                "schema_version": "karkinos.account_strategy_contribution.v2",
                "strategy_id": "dual_ma",
                "contribution_status": "evidence_bound_from_posted_fills",
                "evidence_binding_status": "bound",
                "valuation_scope_status": "complete",
                "blockers": [],
                "valuation_snapshot_id": VALUATION_ID,
                "valuation_as_of": NOW,
                "ledger_cutoff_id": LEDGER_CUTOFF_ID,
                "ledger_fingerprint": LEDGER_FINGERPRINT,
                "contribution_fingerprint": "contribution-source-001",
                "persisted_facts_only": True,
                "provider_contacted": False,
                "database_writes_performed": False,
                "authorizes_execution": False,
            }
        )

    monkeypatch.setattr(
        "server.routes.portfolio.build_portfolio_snapshot", build_portfolio
    )
    monkeypatch.setattr(
        "server.routes.portfolio.build_account_state_response", build_account_state
    )
    monkeypatch.setattr(
        "server.routes.portfolio._current_valuation_snapshot",
        lambda state: {
            "snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
        },
    )
    monkeypatch.setattr(
        "server.routes.operations.build_today_operations_payload", build_operations
    )
    monkeypatch.setattr(
        "server.routes.account_strategy._build_contribution_report",
        build_contribution,
    )
    monkeypatch.setattr(
        "server.account_truth_gate.build_latest_account_truth_score_payload",
        lambda state: {
            "schema_version": "karkinos.account_truth.score.v1",
            "status": "ready",
            "gate_status": "pass",
            "data_freshness_status": "fresh",
            "created_at": NOW,
        },
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    batch = await PersistedKarkinosCaptureSource(state).load(_request())

    assert batch.valuation_snapshot_id == VALUATION_ID
    assert batch.ledger_cutoff_id == LEDGER_CUTOFF_ID
    assert batch.ledger_fingerprint == LEDGER_FINGERPRINT
    assert calls == [
        "portfolio",
        "account_state",
        "operations",
        "strategy_contribution",
    ]
    assert [projection.tool_name for projection in batch.projections] == [
        "portfolio_projection.read",
        "account_state_projection.read",
        "operations_summary.read",
        "research_evidence.read",
        "account_truth.read",
        "paper_shadow_evidence.read",
        "strategy_contribution.read",
    ]
    assert [projection.status for projection in batch.projections] == [
        "complete",
        "complete",
        "degraded",
        "degraded",
        "complete",
        "complete",
        "complete",
    ]
    assert batch.projections[3].payload["backtest_result_id"] == 17
    operations_attention = batch.projections[2].payload["attention_items"][0]
    assert operations_attention["task_fingerprint"] == "sha256:attention-fixture"
    assert operations_attention["manual_acknowledgement_clears_status"] is False
    assert operations_attention["authorizes_execution"] is False
    assert batch.projections[5].payload["persisted_run"]["run_id"] == "shadow-17"
    contribution = batch.projections[6].payload
    assert contribution["strategy_id"] == "dual_ma"
    assert contribution["valuation_snapshot_id"] == VALUATION_ID
    assert (
        contribution["strategy_contribution_report"]["contribution_fingerprint"]
        == "contribution-source-001"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_source_blocks_valuation_or_ledger_drift(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.routes.portfolio.build_portfolio_snapshot", build_portfolio
    )
    monkeypatch.setattr(
        "server.routes.portfolio._current_valuation_snapshot",
        lambda state: {
            "snapshot_id": "valuation-drifted",
            "ledger_cutoff_id": LEDGER_CUTOFF_ID + 1,
            "ledger_fingerprint": "ledger-drifted",
        },
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-drift-001",
        requested_by="human:reese",
        research_question="Detect drift",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.PORTFOLIO,),
        confirmation=CAPTURE_CONFIRMATION,
    )

    with pytest.raises(EvidenceIdentityMismatch, match="drifted during"):
        await PersistedKarkinosCaptureSource(
            SimpleNamespace(db=FixtureDatabase())
        ).load(request)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_source_requires_replayable_persisted_valuation(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.routes.portfolio.build_portfolio_snapshot", build_portfolio
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-unpublished-001",
        requested_by="human:reese",
        research_question="Reject unpublished valuation",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.PORTFOLIO,),
        confirmation=CAPTURE_CONFIRMATION,
    )
    db = SimpleNamespace(get_valuation_snapshot_sync=lambda snapshot_id: None)

    with pytest.raises(EvidenceIdentityMismatch, match="not persisted"):
        await PersistedKarkinosCaptureSource(SimpleNamespace(db=db)).load(request)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_strategy_contribution_capture_rejects_assignment_drift(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.routes.portfolio.build_portfolio_snapshot", build_portfolio
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-strategy-drift-001",
        requested_by="human:reese",
        research_question="Reject a changed strategy selection",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.STRATEGY_CONTRIBUTION,),
        confirmation=CAPTURE_CONFIRMATION,
        strategy_id="not-the-current-strategy",
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    with pytest.raises(CaptureSelectionError, match="selected strategy changed"):
        await PersistedKarkinosCaptureSource(state).load(request)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_strategy_contribution_capture_rejects_financial_identity_drift(
    monkeypatch,
):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.routes.portfolio.build_portfolio_snapshot", build_portfolio
    )
    monkeypatch.setattr(
        "server.routes.account_strategy._build_contribution_report",
        lambda db, assignment: FixtureModel(
            {
                "strategy_id": assignment.strategy_id,
                "contribution_status": "evidence_bound_from_posted_fills",
                "evidence_binding_status": "bound",
                "valuation_scope_status": "complete",
                "blockers": [],
                "valuation_snapshot_id": "different-valuation",
                "valuation_as_of": NOW,
                "ledger_cutoff_id": LEDGER_CUTOFF_ID,
                "ledger_fingerprint": LEDGER_FINGERPRINT,
                "contribution_fingerprint": "contribution-drifted",
            }
        ),
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-contribution-identity-drift-001",
        requested_by="human:reese",
        research_question="Reject contribution identity drift",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.STRATEGY_CONTRIBUTION,),
        confirmation=CAPTURE_CONFIRMATION,
        strategy_id="dual_ma",
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    with pytest.raises(EvidenceIdentityMismatch, match="valuation_snapshot_id"):
        await PersistedKarkinosCaptureSource(state).load(request)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_incomplete_strategy_contribution_remains_blocked_evidence(monkeypatch):
    async def build_portfolio(state):
        return _portfolio()

    monkeypatch.setattr(
        "server.routes.portfolio.build_portfolio_snapshot", build_portfolio
    )
    monkeypatch.setattr(
        "server.routes.portfolio._current_valuation_snapshot",
        lambda state: {
            "snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
        },
    )
    monkeypatch.setattr(
        "server.routes.account_strategy._build_contribution_report",
        lambda db, assignment: FixtureModel(
            {
                "strategy_id": assignment.strategy_id,
                "contribution_status": "valuation_missing",
                "evidence_binding_status": "blocked",
                "valuation_scope_status": "blocked",
                "blockers": ["strategy_contribution_valuation_snapshot_missing"],
                "valuation_snapshot_id": None,
                "valuation_as_of": None,
                "ledger_cutoff_id": 0,
                "ledger_fingerprint": None,
                "contribution_fingerprint": None,
                "persisted_facts_only": True,
                "provider_contacted": False,
                "database_writes_performed": False,
                "authorizes_execution": False,
            }
        ),
    )
    request = HumanContextCaptureRequest(
        idempotency_key="source-contribution-blocked-001",
        requested_by="human:reese",
        research_question="Preserve incomplete outcome evidence as blocked",
        account_alias="primary",
        evidence_types=(CaptureEvidenceType.STRATEGY_CONTRIBUTION,),
        confirmation=CAPTURE_CONFIRMATION,
        strategy_id="dual_ma",
    )
    state = SimpleNamespace(
        db=FixtureDatabase(),
        config=SimpleNamespace(strategy="dual_ma"),
    )

    batch = await PersistedKarkinosCaptureSource(state).load(request)

    assert batch.projections[0].status == "blocked"
    assert batch.projections[0].payload["valuation_snapshot_id"] == VALUATION_ID
    report = batch.projections[0].payload["strategy_contribution_report"]
    assert report["contribution_status"] == "valuation_missing"
    assert report["authorizes_execution"] is False
