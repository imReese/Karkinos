"""Real CAS reads stay call-owned across the production daily composition.

Small scanner fixtures isolate scope behavior from investment validation. The
full deployment pipeline test separately uses the same composition helper with
real final evidence, qualification, policy publication and financial gates.
"""

from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from data.dataset.manifest import (
    publish_daily_bar_dataset_manifest,
    read_daily_bar_dataset_manifest,
)
from data.dataset.reader import read_daily_bar_dataset
from data.storage.objects import ContentAddressedObjectStore
from server.contracts.recommendation_publication import publication_source_blocker
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.services.decision.daily_decision_evidence_composition import (
    build_daily_decision_evidence_automation_service,
)
from tests.server.test_promoted_strategy_universe_scan import _service, _valuation_id
from tests.server.test_recommendation_publication import _grant
from tests.server.test_verified_interval_dataset import _verified_day


def _compose_reader(
    scanner, state, portfolio, decision_day, monkeypatch, *, on_quote=None
):
    """Bind actual scanner/freezer instances and synthetic external quote I/O."""
    from server.services.strategy_scan import daily_candidate_quote_freeze as quotes
    from server.services.strategy_scan import promoted_strategy_universe_scan as scans

    actual_freezer = quotes.DailyCandidateQuoteFreezeService
    monkeypatch.setattr(
        quotes, "preferred_legacy_provider", lambda *_: "synthetic_fixture"
    )
    monkeypatch.setattr(
        scans, "PromotedStrategyUniverseScanService", lambda **_: scanner
    )
    monkeypatch.setattr(
        quotes,
        "DailyCandidateQuoteFreezeService",
        lambda **kwargs: actual_freezer(**kwargs, clock=scanner._clock),
    )
    state.trading_controls = None
    state.notifier = None

    async def plan_reader(_state):
        return {
            "decision_date": decision_day,
            "summary": {"portfolio": dict(portfolio)},
            "candidates": [],
        }, {"plan_date": decision_day}

    async def refresh(_state, symbol, asset_class, *, fetch_run_id):
        from server.contracts.quote_ingestion import QuoteIngestionCommand

        if on_quote is not None:
            on_quote()
        instant = scanner._clock().isoformat()
        state.db.persist_quote_ingestion_sync(
            QuoteIngestionCommand(
                symbol=symbol,
                asset_type=asset_class.value,
                price=10,
                volume=123456,
                quote_timestamp=instant,
                captured_at=instant,
                quote_source="synthetic_fixture",
                provider_name="synthetic_fixture",
                quote_status="live",
                fetch_run_id=fetch_run_id,
            )
        )
        return {"symbol": symbol, "status": "refreshed", "quote_timestamp": instant}

    async def risk(_state):
        return {}

    return build_daily_decision_evidence_automation_service(
        state,
        plan_reader=plan_reader,
        risk_runner=risk,
        quote_refresher=refresh,
        service_type=lambda **kwargs: SimpleNamespace(**kwargs),
    ).plan_reader


@pytest.fixture
def scope_consumer(tmp_path, monkeypatch):
    import data.dataset.reader as reader

    db, scanner, _ = _service(tmp_path, produces_signals=True)
    objects = ContentAddressedObjectStore(tmp_path / "research" / "objects")
    first = _verified_day(tmp_path / "research", date(2026, 8, 21))
    snapshot = read_daily_bar_dataset_manifest(objects, first)
    second = publish_daily_bar_dataset_manifest(
        objects, replace(snapshot, cutoff=snapshot.cutoff + timedelta(seconds=1))
    )
    refs = (first, second)
    store = ShadowResearchStore(db.path)
    store.init()
    grant = _grant()
    store.configure_publication_grant(
        policy=grant, expected_generation=None, now="2026-08-24T01:35:00+00:00"
    )
    strategy_id = "ai_formula_shadow:fixture-winner"
    db.upsert_strategy_promotion_state_sync(
        strategy_id=strategy_id,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={
            "decision_source": "policy",
            "publication_decision": {
                "grant_id": grant["grant_id"],
                "generation": grant["generation"],
            },
        },
    )
    fixture_gate = scanner._strategy_gate_resolver
    gates, cold = [], []
    strict_read = reader._read_daily_bar_dataset

    def counted_read(store, ref):
        cold.append((store.root.resolve(), ref))
        return strict_read(store, ref)

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", counted_read)

    def gate(db, requested, *, as_of_date):
        gates.append(requested)
        row = db.get_strategy_promotion_state_sync(requested)
        blocker = publication_source_blocker(db, row)
        if blocker:
            return {"status": "blocked"}, [blocker]
        # The real provenance owner is deliberately called more than once by
        # this small source-binding fixture. No successful gate is cached.
        for ref in (*refs, *refs):
            read_daily_bar_dataset(objects, ref)
        projected, blockers = fixture_gate(db, requested, as_of_date=as_of_date)
        projected.update(
            persisted_facts_only=True,
            provider_contact_performed=False,
            does_not_create_order=True,
            does_not_authorize_execution=True,
            does_not_change_capital_authority=True,
            broker_submission_enabled=False,
        )
        return projected, blockers

    scanner._strategy_gate_resolver = gate
    portfolio = {
        "total_equity": 100000,
        "cash": 100000,
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "valuation_snapshot_id": _valuation_id(db),
        "symbols": [],
        "instrument_types": {},
    }
    state = SimpleNamespace(db=db, config=scanner._config)

    def revoke():
        store.configure_publication_grant(
            policy={**grant, "enabled": False},
            expected_generation=grant["generation"],
            now="2026-08-24T01:36:00+00:00",
        )

    return SimpleNamespace(
        db=db,
        scanner=scanner,
        state=state,
        portfolio=portfolio,
        cold=cold,
        gates=gates,
        gate=gate,
        revoke=revoke,
    )


@pytest.mark.asyncio
async def test_composed_plan_verifies_each_dataset_once_and_reopens_next_round(
    scope_consumer, monkeypatch
):
    fixture = scope_consumer
    read_plan = _compose_reader(
        fixture.scanner, fixture.state, fixture.portfolio, "2026-08-24", monkeypatch
    )
    first, _ = await read_plan()
    assert first["summary"]["promoted_strategy_universe_scan"]["status"] == "completed"
    assert len(fixture.cold) == 2 and len(fixture.gates) >= 4
    ids = {task["id"] for task in fixture.db.get_action_tasks_sync(limit=100)}
    assert len(ids) == 4
    second, _ = await read_plan()
    assert second["summary"]["promoted_strategy_universe_scan"]["status"] == "completed"
    assert len(fixture.cold) == 4
    fixture.revoke()
    refused, _ = await read_plan()
    assert refused["summary"]["promoted_strategy_universe_scan"]["status"] == "blocked"
    assert {task["id"] for task in fixture.db.get_action_tasks_sync(limit=100)} == ids


@pytest.mark.asyncio
async def test_quote_phase_revocation_blocks_writes_despite_joined_dataset_reads(
    scope_consumer, monkeypatch
):
    fixture = scope_consumer
    revoked = False

    def revoke_once():
        nonlocal revoked
        if not revoked:
            fixture.revoke()
            revoked = True

    read_plan = _compose_reader(
        fixture.scanner,
        fixture.state,
        fixture.portfolio,
        "2026-08-24",
        monkeypatch,
        on_quote=revoke_once,
    )
    refused, _ = await read_plan()
    assert revoked
    assert refused["summary"]["promoted_strategy_universe_scan"]["status"] == "blocked"
    assert len(fixture.cold) == 2
    assert fixture.db.get_action_tasks_sync(limit=100) == []
    assert fixture.db.list_signal_journal_sync(limit=100) == []


def test_independent_scan_validation_reopens_data_and_current_grant(scope_consumer):
    fixture = scope_consumer
    scan = fixture.scanner.run_once(
        decision_date="2026-08-24", portfolio_summary=fixture.portfolio
    )
    assert scan["status"] == "completed"
    assert len(fixture.cold) == 2
    for index in range(2):
        assert (
            fixture.scanner.current_input_blockers(
                scan=scan, portfolio_summary=fixture.portfolio
            )
            == []
        )
        assert len(fixture.cold) == 2 * (index + 2)
    ids = {task["id"] for task in fixture.db.get_action_tasks_sync(limit=100)}
    fixture.revoke()
    assert fixture.scanner.current_input_blockers(
        scan=scan, portfolio_summary=fixture.portfolio
    )
    assert len(fixture.cold) == 6
    assert {task["id"] for task in fixture.db.get_action_tasks_sync(limit=100)} == ids


def test_independent_preparation_reopens_data_and_current_grant(
    scope_consumer, monkeypatch
):
    from server.services.decision.daily_decision_preparation import (
        build_daily_candidate_preparation_check,
    )
    from server.services.research import strategy_promotion_pipeline as promotion

    fixture = scope_consumer
    monkeypatch.setattr(
        promotion, "resolve_strategy_order_generation_gate", fixture.gate
    )
    monkeypatch.setattr(
        "server.account_truth_gate.build_latest_account_truth_promotion_evidence",
        lambda _: {},
    )
    monkeypatch.setattr(
        "server.services.account.reviewed_fee_schedule.build_reviewed_fee_schedule_review_status",
        lambda *_, **__: {},
    )
    for index in range(2):
        result = build_daily_candidate_preparation_check(
            fixture.state, run_date="2026-08-24"
        )
        assert result["passing_strategy_count"] == 1
        assert len(fixture.cold) == 2 * (index + 1)
    fixture.revoke()
    refused = build_daily_candidate_preparation_check(
        fixture.state, run_date="2026-08-24"
    )
    assert refused["passing_strategy_count"] == 0
    assert "publication_grant_inactive_or_invalid" in refused["blockers"]
    assert len(fixture.cold) == 4
