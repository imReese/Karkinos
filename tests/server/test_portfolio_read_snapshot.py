from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from server.dependencies import AppState
from server.projections.portfolio_read_snapshot import (
    PortfolioReadIdentityMismatch,
    PortfolioReadPortResult,
    PortfolioReadSnapshotIdentity,
    PortfolioReadSnapshotPorts,
    PortfolioReadSnapshotRejected,
    PortfolioReadSnapshotService,
)


def _fingerprint(seed: str) -> str:
    return (seed * 64)[:64]


def _identity(seed: str) -> PortfolioReadSnapshotIdentity:
    return PortfolioReadSnapshotIdentity(
        valuation_snapshot_id=f"valuation-{seed}",
        ledger_cutoff_id=2,
        ledger_fingerprint=_fingerprint(f"l{seed}"),
        market_generation_id=f"market-generation-{seed}",
        market_receipt_fingerprint=_fingerprint(f"r{seed}"),
        market_content_fingerprint=_fingerprint(f"m{seed}"),
        policy_version="karkinos.persisted_valuation.v4",
    )


class _FixtureReadPorts:
    def __init__(
        self,
        *,
        valuation_entered: threading.Event | None = None,
        valuation_release: threading.Event | None = None,
    ) -> None:
        self.calls: Counter[tuple[str, PortfolioReadSnapshotIdentity]] = Counter()
        self.valuation_entered = valuation_entered
        self.valuation_release = valuation_release
        self.source_values: dict[str, object] = {}

    def ports(self) -> PortfolioReadSnapshotPorts:
        return PortfolioReadSnapshotPorts(
            read_published_valuation=self.read_published_valuation,
            read_ledger_rows=self.read_ledger_rows,
            read_price_matrix=self.read_price_matrix,
        )

    def read_published_valuation(
        self,
        identity: PortfolioReadSnapshotIdentity,
    ) -> PortfolioReadPortResult[dict[str, object]]:
        self.calls[("valuation", identity)] += 1
        if self.valuation_entered is not None:
            self.valuation_entered.set()
        if self.valuation_release is not None:
            assert self.valuation_release.wait(timeout=3)
        value: dict[str, object] = {
            "snapshot_id": identity.valuation_snapshot_id,
            "ledger_cutoff_id": identity.ledger_cutoff_id,
            "ledger_fingerprint": identity.ledger_fingerprint,
            "valuation_policy": identity.policy_version,
            "status": "complete",
            "quotes": [{"symbol": "600001", "price": 11.0}],
            "generation": identity.market_generation_id,
        }
        self.source_values["valuation"] = value
        return PortfolioReadPortResult(
            identity=identity,
            value=value,
            query_count=1,
            rows_read=1,
        )

    def read_ledger_rows(
        self,
        identity: PortfolioReadSnapshotIdentity,
    ) -> PortfolioReadPortResult[list[dict[str, object]]]:
        self.calls[("ledger", identity)] += 1
        value = [
            {
                "id": 1,
                "entry_type": "cash_deposit",
                "amount": 1000.0,
                "generation": identity.market_generation_id,
            },
            {
                "id": 2,
                "entry_type": "trade_buy",
                "symbol": "600001",
                "quantity": 10.0,
                "generation": identity.market_generation_id,
            },
        ]
        self.source_values["ledger"] = value
        return PortfolioReadPortResult(
            identity=identity,
            value=value,
            query_count=1,
            rows_read=len(value),
        )

    def read_price_matrix(
        self,
        identity: PortfolioReadSnapshotIdentity,
        ledger_rows,
    ) -> PortfolioReadPortResult[list[dict[str, object]]]:
        self.calls[("matrix", identity)] += 1
        assert [row["id"] for row in ledger_rows] == [1, 2]
        value = [
            {
                "symbol": "600001",
                "trade_date": "2026-08-28",
                "price": 10.0,
                "generation": identity.market_generation_id,
            },
            {
                "symbol": "600001",
                "trade_date": "2026-08-29",
                "price": 11.0,
                "generation": identity.market_generation_id,
            },
        ]
        self.source_values["matrix"] = value
        return PortfolioReadPortResult(
            identity=identity,
            value=value,
            query_count=1,
            rows_read=len(value),
        )


def test_snapshot_build_reads_each_port_once_and_deep_freezes_inputs() -> None:
    identity = _identity("a")
    fixture = _FixtureReadPorts()
    service = PortfolioReadSnapshotService(max_entries=2)

    snapshot = service.get_or_build(identity, fixture.ports())

    assert fixture.calls == Counter(
        {
            ("valuation", identity): 1,
            ("ledger", identity): 1,
            ("matrix", identity): 1,
        }
    )
    assert snapshot.identity == identity
    assert snapshot.published_valuation["snapshot_id"] == "valuation-a"
    assert [row["id"] for row in snapshot.ledger_rows] == [1, 2]
    assert [row["price"] for row in snapshot.price_matrix_rows] == [10.0, 11.0]
    assert snapshot.build_metrics.query_count == 3
    assert snapshot.build_metrics.rows_read == 5
    assert snapshot.build_metrics.build_latency_ms >= 0
    assert snapshot.persisted_facts_only is True
    assert snapshot.provider_contact_performed is False
    assert snapshot.write_performed is False
    assert snapshot.authorizes_execution is False
    assert snapshot.changes_trading_authority is False
    assert snapshot.changes_capital_authority is False

    valuation = fixture.source_values["valuation"]
    ledger = fixture.source_values["ledger"]
    matrix = fixture.source_values["matrix"]
    assert isinstance(valuation, dict)
    assert isinstance(ledger, list)
    assert isinstance(matrix, list)
    valuation["snapshot_id"] = "mutated"
    ledger[0]["id"] = 99
    matrix[0]["price"] = 99.0

    assert snapshot.published_valuation["snapshot_id"] == "valuation-a"
    assert snapshot.ledger_rows[0]["id"] == 1
    assert snapshot.price_matrix_rows[0]["price"] == 10.0
    with pytest.raises(TypeError):
        snapshot.ledger_rows[0]["id"] = 3

    metrics = service.metrics()
    assert metrics.cache_hits == 0
    assert metrics.cache_misses == 1
    assert metrics.builds == 1
    assert metrics.query_count == 3
    assert metrics.rows_read == 5
    assert metrics.cache_entries == 1


def test_warm_same_identity_is_the_same_immutable_object_and_reads_nothing() -> None:
    identity = _identity("warm")
    fixture = _FixtureReadPorts()
    service = PortfolioReadSnapshotService(max_entries=2)

    first = service.get_or_build(identity, fixture.ports())
    before = service.metrics()
    second = service.get_or_build(identity, fixture.ports())
    after = service.metrics()

    assert second is first
    assert sum(fixture.calls.values()) == 3
    assert after.cache_hits == before.cache_hits + 1
    assert after.cache_misses == before.cache_misses
    assert after.query_count == before.query_count
    assert after.rows_read == before.rows_read
    assert after.builds == before.builds


def test_identity_change_is_a_miss_and_records_logical_invalidation() -> None:
    first_identity = _identity("old")
    second_identity = _identity("new")
    fixture = _FixtureReadPorts()
    service = PortfolioReadSnapshotService(max_entries=2)

    old = service.get_or_build(first_identity, fixture.ports())
    assert service.get_or_build(first_identity, fixture.ports()) is old
    new = service.get_or_build(second_identity, fixture.ports())

    assert new.identity == second_identity
    assert new is not old
    metrics = service.metrics()
    assert metrics.cache_hits == 1
    assert metrics.cache_misses == 2
    assert metrics.cache_invalidations == 1
    assert metrics.builds == 2
    assert metrics.query_count == 6


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("valuation_snapshot_id", "valuation-replaced"),
        ("ledger_cutoff_id", 3),
        ("ledger_fingerprint", _fingerprint("changed-ledger")),
        ("market_generation_id", "market-generation-replaced"),
        ("market_receipt_fingerprint", _fingerprint("changed-receipt")),
        ("market_content_fingerprint", _fingerprint("changed-content")),
        ("policy_version", "karkinos.persisted_valuation.v5"),
    ),
)
def test_every_identity_component_participates_in_the_cache_key(
    field_name: str,
    replacement: object,
) -> None:
    original = _identity("identity-key")
    changed = replace(original, **{field_name: replacement})
    fixture = _FixtureReadPorts()
    service = PortfolioReadSnapshotService(max_entries=2)

    first = service.get_or_build(original, fixture.ports())
    second = service.get_or_build(changed, fixture.ports())

    assert first.identity != second.identity
    assert service.metrics().cache_misses == 2
    assert service.metrics().cache_invalidations == 1
    assert fixture.calls[("valuation", original)] == 1
    assert fixture.calls[("valuation", changed)] == 1


def test_build_latency_uses_the_injected_monotonic_clock() -> None:
    ticks = iter((1_000_000, 4_250_000))
    identity = _identity("latency")
    service = PortfolioReadSnapshotService(
        max_entries=1,
        monotonic_ns=lambda: next(ticks),
    )

    snapshot = service.get_or_build(identity, _FixtureReadPorts().ports())

    assert snapshot.build_metrics.build_latency_ms == pytest.approx(3.25)
    metrics = service.metrics()
    assert metrics.last_build_latency_ms == pytest.approx(3.25)
    assert metrics.total_build_latency_ms == pytest.approx(3.25)
    assert metrics.max_build_latency_ms == pytest.approx(3.25)
    assert metrics.average_build_latency_ms == pytest.approx(3.25)


def test_cache_is_bounded_and_uses_lru_eviction() -> None:
    identities = [_identity(seed) for seed in ("one", "two", "three")]
    fixture = _FixtureReadPorts()
    service = PortfolioReadSnapshotService(max_entries=2)

    one = service.get_or_build(identities[0], fixture.ports())
    service.get_or_build(identities[1], fixture.ports())
    assert service.get_or_build(identities[0], fixture.ports()) is one
    service.get_or_build(identities[2], fixture.ports())
    service.get_or_build(identities[1], fixture.ports())

    assert fixture.calls[("valuation", identities[0])] == 1
    assert fixture.calls[("valuation", identities[1])] == 2
    assert fixture.calls[("valuation", identities[2])] == 1
    assert service.metrics().cache_entries == 2
    assert service.metrics().cache_evictions == 2


def test_same_identity_build_is_single_flight() -> None:
    identity = _identity("single-flight")
    entered = threading.Event()
    release = threading.Event()
    fixture = _FixtureReadPorts(
        valuation_entered=entered,
        valuation_release=release,
    )
    service = PortfolioReadSnapshotService(max_entries=2)
    workers = 8
    start = threading.Barrier(workers)

    def read_snapshot():
        start.wait(timeout=3)
        return service.get_or_build(identity, fixture.ports())

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(read_snapshot) for _ in range(workers)]
        assert entered.wait(timeout=3)
        deadline = time.monotonic() + 3
        while (
            service.metrics().singleflight_waits < workers - 1
            and time.monotonic() < deadline
        ):
            time.sleep(0.001)
        assert service.metrics().singleflight_waits == workers - 1
        release.set()
        snapshots = [future.result(timeout=3) for future in futures]

    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert fixture.calls[("valuation", identity)] == 1
    assert fixture.calls[("ledger", identity)] == 1
    assert fixture.calls[("matrix", identity)] == 1
    metrics = service.metrics()
    assert metrics.builds == 1
    assert metrics.cache_misses == workers
    assert metrics.query_count == 3
    assert metrics.rows_read == 5


def test_concurrent_old_and_new_identity_never_publish_a_hybrid_snapshot() -> None:
    old_identity = _identity("old-generation")
    new_identity = _identity("new-generation")
    fixture = _FixtureReadPorts()
    service = PortfolioReadSnapshotService(max_entries=2)
    start = threading.Barrier(2)

    def build(identity: PortfolioReadSnapshotIdentity):
        start.wait(timeout=3)
        return service.get_or_build(identity, fixture.ports())

    with ThreadPoolExecutor(max_workers=2) as executor:
        old_future = executor.submit(build, old_identity)
        new_future = executor.submit(build, new_identity)
        old = old_future.result(timeout=3)
        new = new_future.result(timeout=3)

    for snapshot in (old, new):
        generation = snapshot.identity.market_generation_id
        assert snapshot.published_valuation["generation"] == generation
        assert {row["generation"] for row in snapshot.ledger_rows} == {generation}
        assert {row["generation"] for row in snapshot.price_matrix_rows} == {generation}
    assert {old.identity, new.identity} == {old_identity, new_identity}
    assert service.metrics().builds == 2


def test_late_old_build_cannot_evict_the_new_active_identity() -> None:
    old_identity = _identity("slow-old")
    new_identity = _identity("fast-new")
    old_entered = threading.Event()
    release_old = threading.Event()
    old_fixture = _FixtureReadPorts(
        valuation_entered=old_entered,
        valuation_release=release_old,
    )
    new_fixture = _FixtureReadPorts()
    service = PortfolioReadSnapshotService(max_entries=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        old_future = executor.submit(
            service.get_or_build,
            old_identity,
            old_fixture.ports(),
        )
        assert old_entered.wait(timeout=3)
        new = service.get_or_build(new_identity, new_fixture.ports())
        release_old.set()
        old = old_future.result(timeout=3)

    assert old.identity == old_identity
    assert new.identity == new_identity
    assert service.get_or_build(new_identity, new_fixture.ports()) is new
    assert new_fixture.calls[("valuation", new_identity)] == 1


def test_mixed_identity_port_result_fails_closed_and_is_not_cached() -> None:
    requested = _identity("requested")
    drifted = _identity("drifted")
    fixture = _FixtureReadPorts()
    original = fixture.read_price_matrix

    def drifted_matrix(identity, ledger_rows):
        result = original(identity, ledger_rows)
        return PortfolioReadPortResult(
            identity=drifted,
            value=result.value,
            query_count=result.query_count,
            rows_read=result.rows_read,
        )

    ports = PortfolioReadSnapshotPorts(
        read_published_valuation=fixture.read_published_valuation,
        read_ledger_rows=fixture.read_ledger_rows,
        read_price_matrix=drifted_matrix,
    )
    service = PortfolioReadSnapshotService(max_entries=2)

    with pytest.raises(PortfolioReadIdentityMismatch):
        service.get_or_build(requested, ports)

    assert service.metrics().build_failures == 1
    assert service.metrics().cache_entries == 0
    assert fixture.calls[("valuation", requested)] == 1
    assert fixture.calls[("ledger", requested)] == 1
    assert fixture.calls[("matrix", requested)] == 1


def test_intraday_quote_port_is_identity_bound_and_not_cached_on_drift() -> None:
    requested = _identity("requested-intraday")
    drifted = _identity("drifted-intraday")
    fixture = _FixtureReadPorts()

    def drifted_intraday(identity, ledger_rows):
        assert [row["id"] for row in ledger_rows] == [1, 2]
        return PortfolioReadPortResult(
            identity=drifted,
            value=[{"symbol": "600001", "price": 11.0}],
            query_count=1,
            rows_read=1,
        )

    ports = PortfolioReadSnapshotPorts(
        read_published_valuation=fixture.read_published_valuation,
        read_ledger_rows=fixture.read_ledger_rows,
        read_price_matrix=fixture.read_price_matrix,
        read_intraday_quote_rows=drifted_intraday,
    )
    service = PortfolioReadSnapshotService(max_entries=2)

    with pytest.raises(PortfolioReadIdentityMismatch):
        service.get_or_build(requested, ports)

    assert service.metrics().build_failures == 1
    assert service.metrics().cache_entries == 0


def test_published_valuation_must_match_the_complete_requested_identity() -> None:
    identity = _identity("valuation-drift")
    fixture = _FixtureReadPorts()

    def wrong_valuation(requested):
        result = fixture.read_published_valuation(requested)
        value = dict(result.value)
        value["ledger_fingerprint"] = _fingerprint("wrong")
        return PortfolioReadPortResult(
            identity=requested,
            value=value,
            query_count=1,
            rows_read=1,
        )

    service = PortfolioReadSnapshotService(max_entries=1)
    ports = PortfolioReadSnapshotPorts(
        read_published_valuation=wrong_valuation,
        read_ledger_rows=fixture.read_ledger_rows,
        read_price_matrix=fixture.read_price_matrix,
    )

    with pytest.raises(PortfolioReadSnapshotRejected, match="ledger_fingerprint"):
        service.get_or_build(identity, ports)

    assert fixture.calls[("ledger", identity)] == 0
    assert fixture.calls[("matrix", identity)] == 0
    assert service.metrics().cache_entries == 0


def test_app_state_wiring_is_optional_and_grants_no_authority() -> None:
    state = AppState()

    assert state.portfolio_read_snapshot_service is None
    assert state.trading_controls is None
    assert state.controlled_broker_release_evidence_provider is None
