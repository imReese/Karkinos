"""Synthetic orchestration checks; no provider, native returns or account facts."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from server.contracts.ai_shadow_research_qualification import (
    manual_qualification_source_id,
)
from server.db import AppDatabase
from tests.server.test_ai_shadow_research_qualification_service import (
    FakeDatabase,
    _harness,
)

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


@pytest.mark.asyncio
async def test_manual_source_uses_one_exact_candidate_and_never_automatic_grant(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(FakeDatabase, "path", db.path, raising=False)
    service, store, capture, baseline, adapter, fees = _harness()
    batch, frozen = service._freeze_batch("source-run")
    source = frozen[0]
    refs = {
        k: source.source_candidate[k]
        for k in ("session_id", "draft_id", "backtest_run_id", "critique_id")
    }
    refs["canonical_backtest_result_id"] = source.source_candidate[
        "candidate_result_id"
    ]
    binding = {
        "source_kind": "manual_research",
        "manual_source_refs": refs,
        "manual_source_fingerprint": "a" * 64,
        "final_evaluation_id": "final",
        "final_evidence_fingerprint": "b" * 64,
    }
    identity = manual_qualification_source_id(binding)
    source = replace(
        source,
        verified={**source.verified, "source_binding": binding},
        source_candidate={
            **source.source_candidate,
            "candidate_id": identity,
            "run_id": identity,
        },
    )
    freeze_calls = []

    def freeze(**kwargs):
        assert kwargs["source_binding"] == binding
        freeze_calls.append(kwargs)
        return source

    monkeypatch.setattr(
        "server.services.ai_shadow.ai_shadow_research_qualification.freeze_manual_qualification_source",
        freeze,
    )
    from server.services.account.permissions import freeze_entry_board_policy

    entry = freeze_entry_board_policy(SimpleNamespace(), "2026-08-31")
    service._research_store.get_sealed_test = lambda _id: {
        "evidence": {
            "reservation": {"manual_source_refs": refs, "entry_board_policy": entry}
        }
    }

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "manual source cannot read a daily batch or standing grant"
        )

    service._freeze_batch = forbidden
    monkeypatch.setattr(
        "server.contracts.recommendation_publication.read_publication_grant", forbidden
    )

    async def consume(**kwargs):
        assert kwargs["frozen"] == [source]
        assert kwargs["batch"]["source_binding"] == binding
        assert kwargs["run"]["source_binding"] == binding
        assert (
            kwargs["fee_resolution"].cost_model_reference
            == store.run["reviewed_cost_model_reference"]
        )
        return {"status": "replay_dispatch_verified"}

    service._replay_and_finish = consume
    result = await service.run_once(manual_source_binding=binding)
    assert result["status"] == "replay_dispatch_verified", result
    assert len(freeze_calls) == 2  # Admission and immediately before persistence.
    assert capture.calls == 1 and baseline.calls == 1 and len(fees) == 1
    assert (
        not adapter.calls
    )  # Native execution is deliberately outside this pure caller test.


@pytest.mark.asyncio
async def test_manual_source_failure_blocks_before_account_capture(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(FakeDatabase, "path", db.path, raising=False)
    service, _, capture, baseline, adapter, fees = _harness()
    binding = {
        "source_kind": "manual_research",
        "manual_source_refs": {
            "session_id": "s",
            "draft_id": "d",
            "backtest_run_id": "b",
            "critique_id": "c",
            "canonical_backtest_result_id": 1,
        },
        "manual_source_fingerprint": "a" * 64,
        "final_evaluation_id": "f",
        "final_evidence_fingerprint": "b" * 64,
    }

    def rejected(**kwargs):
        raise ValueError("qualification_manual_final_binding_invalid")

    monkeypatch.setattr(
        "server.services.ai_shadow.ai_shadow_research_qualification.freeze_manual_qualification_source",
        rejected,
    )
    result = await service.run_once(manual_source_binding=deepcopy(binding))
    assert result["status"] == "blocked"
    assert result["blockers"] == ["qualification_manual_final_binding_invalid"]
    assert capture.calls == baseline.calls == 0
    assert not adapter.calls and not fees
