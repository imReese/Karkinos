"""Operation-local immutable reuse preserves cold and historic evidence checks."""

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import read_daily_bar_dataset
from server.services.research.research_observation_automation import (
    configure_observation_automation,
    run_research_observation_automation_once,
)
from server.services.research.research_observation_inputs import (
    read_research_observation_dataset,
    require_observation_dataset_prefix,
)
from server.services.research.research_paper_books import ResearchPaperBookService
from tests.server.test_research_observation_automation import extend_calendar
from tests.server.test_research_observation_inputs import DAYS
from tests.server.test_research_observations_journey import journey  # noqa: F401
from tests.server.test_research_paper_books import bound_dataset


@pytest.fixture
def forward_book(journey, tmp_path):
    _, observations, current, seed, result_id = journey
    started = asyncio.run(
        observations.start(
            request_id=str(uuid4()),
            source_backtest_result_id=result_id,
            horizon_sessions=1,
            max_symbol_weight=Decimal("0.25"),
            max_gross_weight=Decimal("0.97"),
            forward_dataset_id=seed.dataset_id,
        )
    )
    identity = started["id"]
    paper = ResearchPaperBookService(observations.db, clock=lambda: current[0])
    paper.start(
        identity,
        request_id=str(uuid4()),
        initial_cash=Decimal("100000"),
        corporate_action_mode="reported_distributions_gross",
    )
    observations.advance(
        identity,
        request_id=str(uuid4()),
        expected_version=0,
        dataset_id=seed.dataset_id,
    )

    def next_input(index):
        current[0] = datetime.combine(
            DAYS[index], datetime.min.time(), tzinfo=timezone.utc
        ).replace(hour=8, minute=20)
        ref = bound_dataset(tmp_path, count=index + 1, now=current[0])
        DatasetCatalog(tmp_path / "research").register(
            observations.objects, ref, registered_at=current[0]
        )
        return ref

    return observations, paper, identity, seed, next_input


def test_settle_reuses_one_verified_seed_and_next_operation_is_cold(
    forward_book, monkeypatch
):
    import server.services.research.research_observation_inputs as inputs

    observations, paper, identity, seed, next_input = forward_book
    for index in (5, 6):
        ref = next_input(index)
        book = paper.get(identity)
        paper.settle(
            identity,
            request_id=str(uuid4()),
            expected_version=book["version"],
            dataset_id=ref.dataset_id,
        )
        observation = observations.repository.get(identity)
        observations.advance(
            identity,
            request_id=str(uuid4()),
            expected_version=observation["version"],
            dataset_id=ref.dataset_id,
        )
    read = inputs._read
    seeds = []

    def counted(objects, dataset_id, **kwargs):
        if dataset_id == seed.dataset_id:
            seeds.append(dataset_id)
        return read(objects, dataset_id, **kwargs)

    monkeypatch.setattr(inputs, "_read", counted)
    ref = next_input(7)
    before = paper.get(identity)
    result = paper.settle(
        identity,
        request_id=str(uuid4()),
        expected_version=before["version"],
        dataset_id=ref.dataset_id,
    )
    assert len(seeds) == 1
    assert result["steps"][:-1] == before["steps"]
    # A fresh operation must reopen the seed even if its current immutable
    # Dataset was successfully read by the previous operation.
    path = observations.objects._path_for(seed.dataset_id)
    content = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    try:
        blocked = observations.advance(
            identity,
            request_id=str(uuid4()),
            expected_version=observations.repository.get(identity)["version"],
            dataset_id=ref.dataset_id,
        )
        assert blocked["last_blocker"]["code"] == "observation_dataset_unreadable"
    finally:
        path.write_bytes(content)


@pytest.mark.parametrize("target", ["seed", "old_manifest", "old_action"])
def test_settle_reopens_historic_objects_and_recovers_without_partial_write(
    forward_book, target
):
    observations, paper, identity, seed, next_input = forward_book
    first = next_input(5)
    prior = paper.settle(
        identity,
        request_id=str(uuid4()),
        expected_version=0,
        dataset_id=first.dataset_id,
    )
    old_snapshot = read_daily_bar_dataset(observations.objects, first).snapshot
    ref = next_input(6)
    corrupted = {
        "seed": seed.dataset_id,
        "old_manifest": first.dataset_id,
        "old_action": old_snapshot.corporate_action_observation_ids[0],
    }[target]
    path = observations.objects._path_for(corrupted)
    content = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    request_id = str(uuid4())
    try:
        with pytest.raises(ValueError, match="(observation_dataset|corporate_action)"):
            paper.settle(
                identity,
                request_id=request_id,
                expected_version=prior["version"],
                dataset_id=ref.dataset_id,
            )
        assert paper.get(identity)["version"] == prior["version"]
        assert paper.get(identity)["steps"] == prior["steps"]
    finally:
        path.write_bytes(content)
    recovered = paper.settle(
        identity,
        request_id=request_id,
        expected_version=prior["version"],
        dataset_id=ref.dataset_id,
    )
    assert recovered["steps"][0] == prior["steps"][0]
    assert recovered["last_settled_session"] == DAYS[6].isoformat()


def test_verified_seed_reuse_requires_its_exact_identity(forward_book):
    observations, _, identity, _, next_input = forward_book
    ref = next_input(5)
    current = read_daily_bar_dataset(observations.objects, ref)
    with pytest.raises(ValueError, match="observation_dataset_frozen_prefix_changed"):
        require_observation_dataset_prefix(
            observations.objects,
            observations.repository.get(identity)["source"],
            current.snapshot,
            verified_source=current,
        )


def test_verified_parent_preserves_original_read_cutoff(forward_book):
    observations, paper, identity, _, next_input = forward_book
    first = next_input(5)
    prior = paper.settle(
        identity,
        request_id=str(uuid4()),
        expected_version=0,
        dataset_id=first.dataset_id,
    )
    cutoff = read_daily_bar_dataset(observations.objects, first).snapshot.cutoff
    ref = next_input(6)
    current = read_daily_bar_dataset(observations.objects, ref)
    with pytest.raises(ValueError, match="observation_dataset_cutoff_in_future"):
        read_research_observation_dataset(
            observations.objects,
            first.dataset_id,
            instruments=current.snapshot.instruments,
            start_date=current.snapshot.start_date,
            now=cutoff - timedelta(seconds=1),
            calendar_rows=prior["steps"][0]["input"]["calendar"],
            minimum_bars=1,
            verified_parent=current,
        )
    assert paper.get(identity)["version"] == prior["version"]


def test_one_automation_tick_reads_seed_and_current_once(forward_book, monkeypatch):
    import data.dataset.reader as reader

    observations, paper, identity, seed, next_input = forward_book
    extend_calendar(observations)
    configure_observation_automation(
        observations,
        identity,
        enabled=True,
        expected_generation=None,
        paper_settlement_enabled=True,
        dataset_preparation_enabled=True,
    )
    cold = reader._read_daily_bar_dataset
    reads = []

    def counted(objects, ref):
        reads.append(ref.dataset_id)
        return cold(objects, ref)

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", counted)
    first = next_input(5)
    reads.clear()  # Input publication is a different, already completed caller.
    reports = run_research_observation_automation_once(observations)
    assert reports[0]["last_blocker"] is None
    assert reports[0]["status"] == "completed", reports
    assert paper.get(identity)["last_settled_session"] == DAYS[5].isoformat()
    assert Counter(reads) == {seed.dataset_id: 1, first.dataset_id: 1}
    second = next_input(6)
    reads.clear()
    reports = run_research_observation_automation_once(observations)
    assert reports[0]["last_blocker"] is None
    assert reports[0]["status"] == "completed", reports
    assert paper.get(identity)["last_settled_session"] == DAYS[6].isoformat()
    assert Counter(reads) == {seed.dataset_id: 1, second.dataset_id: 1}
