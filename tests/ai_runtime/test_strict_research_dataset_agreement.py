"""Research rejects a conflicting primary even when a general Reader admits it."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from data.market.verification_evidence import MarketVerificationStatus
from server.services.research import research_observation_inputs as observations
from server.services.strategy_scan.universe import formula_inputs as exact
from tests.ai_runtime.test_exact_formula_account_inputs import fixture


def permissive_reader_inputs(monkeypatch, tmp_path, *, status):
    db, item, now, day, calls, entries, result, snapshot, original = fixture(
        monkeypatch, tmp_path
    )
    start, end = snapshot.start_date, snapshot.end_date
    parts = tuple(
        SimpleNamespace(partition_date=date, verification_id="same-proof")
        for date in (start, end)
    )
    snapshot.partitions = parts
    snapshot.cutoff = now
    original.snapshot.partitions = parts[:1]
    for member in snapshot.session_memberships:
        member.decision_at = datetime.combine(
            member.partition_date, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=8)
        member.available_at = member.decision_at
    for bar in result.bars:
        bar.event_time = datetime.combine(
            end, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=7)
        bar.available_at = bar.captured_at = bar.event_time
        bar.session_date = end
    result.corporate_action_evidence = None
    objects = SimpleNamespace(resolve_ref=lambda ref: ref)
    proof_reads = []
    proof = SimpleNamespace(
        status=status,
        checked_at=now,
        primary_materialization_id="primary",
        comparison_materialization_id="secondary",
        primary_quality_id="quality-a",
        comparison_quality_id="quality-b",
    )

    def read_proof(_objects, ref):
        proof_reads.append(ref)
        return proof

    monkeypatch.setattr(observations, "read_market_verification_evidence", read_proof)
    # This is the precise broader Reader contract under review: it supplies
    # complete primary bars irrespective of a retained cross-source CONFLICT.
    monkeypatch.setattr(observations, "_read", lambda *_a, **_kw: result)
    monkeypatch.setattr(
        observations,
        "_calendars",
        lambda *_a, **_kw: {2026: {start, end, end + timedelta(days=1)}},
    )
    monkeypatch.setattr(observations, "latest_closed_session", lambda *_a, **_kw: end)
    monkeypatch.setattr(observations, "_sessions_between", lambda *_a: (start, end))
    monkeypatch.setattr(
        observations,
        "read_market_revision_materialization",
        lambda *_a: SimpleNamespace(capture_ref="capture"),
    )
    monkeypatch.setattr(
        observations,
        "read_provider_capture",
        lambda *_a: SimpleNamespace(started_at=now, completed_at=now),
    )
    monkeypatch.setattr(
        observations,
        "read_market_quality_evidence",
        lambda *_a: SimpleNamespace(report=SimpleNamespace(checked_at=now)),
    )
    # Undo only the old account test's public-reader stub, so the actual shared
    # observation owner and its MATCHED guard run in the account path as well.
    monkeypatch.setattr(
        exact,
        "read_research_observation_dataset",
        observations.read_research_observation_dataset,
    )
    return db, item, now, day, result, objects, proof_reads


@pytest.mark.parametrize(
    "status", [MarketVerificationStatus.MATCHED, MarketVerificationStatus.CONFLICT]
)
def test_observation_owns_strict_agreement_independently_of_reader(
    monkeypatch, tmp_path, status
):
    db, item, now, day, result, objects, reads = permissive_reader_inputs(
        monkeypatch, tmp_path, status=status
    )
    kwargs = dict(
        instruments=result.snapshot.instruments,
        start_date=result.snapshot.start_date,
        now=now,
        calendar_rows=[],
        minimum_bars=2,
        deployment_scope=item["formula_dataset_anchor"]["deployment_scope"],
    )
    if status is MarketVerificationStatus.CONFLICT:
        with pytest.raises(
            observations.ResearchObservationInputError,
            match="observation_verification_not_matched",
        ):
            observations.read_research_observation_dataset(
                objects, "primary-admitted", **kwargs
            )
    else:
        assert (
            observations.read_research_observation_dataset(
                objects, "primary-admitted", **kwargs
            )
            is result
        )
    assert reads == ["same-proof"]  # shared verification remains one cold read
    assert not db.path.exists()


@pytest.mark.parametrize(
    "status", [MarketVerificationStatus.MATCHED, MarketVerificationStatus.CONFLICT]
)
def test_exact_account_input_path_inherits_strict_observation_owner(
    monkeypatch, tmp_path, status
):
    db, item, now, day, _result, _objects, reads = permissive_reader_inputs(
        monkeypatch, tmp_path, status=status
    )
    frames, contexts, bindings, blockers = exact.load_exact_formula_market_inputs(
        db, [item], market_date=day, decision_at=now
    )
    if status is MarketVerificationStatus.CONFLICT:
        assert not frames and not contexts and not bindings
        assert any(
            "observation_verification_not_matched" in value for value in blockers
        )
    else:
        assert blockers == [] and set(frames) == {"bk"} and set(bindings) == {"bk"}
    assert reads == ["same-proof"]
    assert not db.path.exists()
