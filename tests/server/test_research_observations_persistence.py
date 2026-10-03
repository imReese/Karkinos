"""Durable independent observation history, retries, and concurrent publication."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from server import db as db_module
from server.db import AppDatabase
from server.persistence import migrations
from server.persistence.research_observations import ResearchObservationsRepository

pytestmark = pytest.mark.api_contract
NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    return db


def _start(repo, observation_id="obs"):
    return repo.start(
        observation_id=observation_id,
        request_id="start",
        request_fingerprint="start-request",
        source_backtest_result_id=17,
        source={"strategy": "dual_ma", "params": {"short_period": 5}},
        code_binding={"sha256": "frozen"},
        policy={"horizon_sessions": 1},
        universe=[{"symbol": "600001", "instrument_type": "stock"}],
    )


def _publication(publication_id="pub", session="2026-09-21"):
    return {
        "id": publication_id,
        "decision_session": session,
        "dataset_id": "dataset-original",
        "payload": {"targets": {"600001": "0.5"}, "reference_session": "2026-09-22"},
    }


def test_report_filter_applies_before_history_limit(database):
    current = [NOW]
    repo = ResearchObservationsRepository(database.path, clock=lambda: current[0])
    _start(repo, "older-report")
    current[0] += timedelta(minutes=1)
    repo.start(
        observation_id="newer-report",
        request_id="start",
        request_fingerprint="second",
        source_backtest_result_id=18,
        source={"strategy": "dual_ma"},
        code_binding={"hash": "frozen"},
        policy={"horizon_sessions": 1},
        universe=[],
    )
    assert repo.list(limit=1)[0]["id"] == "newer-report"
    assert repo.list(limit=1, source_backtest_result_id=17)[0]["id"] == "older-report"
    assert repo.list(source_backtest_result_id=19) == []


def _advance(repo, **kwargs):
    arguments = {
        "observation_id": "obs",
        "request_id": "advance-a",
        "request_fingerprint": "advance-request-a",
        "expected_version": 0,
        "publication": _publication(),
        "publication_deadline": NOW + timedelta(days=1),
    }
    arguments.update(kwargs)
    return repo.advance(**arguments)


def test_retry_original_mutations_after_restart_and_later_pause(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    started = _start(repo)
    published = _advance(repo)
    blocked = _advance(
        repo,
        request_id="advance-b",
        request_fingerprint="request-b",
        expected_version=1,
        publication=None,
        blocker={"code": "awaiting_future_data"},
    )
    assert blocked["version"] == 2
    paused = repo.pause(
        observation_id="obs",
        request_id="pause",
        request_fingerprint="pause-request",
        expected_version=2,
    )
    assert paused["version"] == 3
    reopened = ResearchObservationsRepository(database.path)
    assert _start(reopened) == started
    assert _advance(reopened) == published
    assert (
        reopened.pause(
            observation_id="obs",
            request_id="pause",
            request_fingerprint="pause-request",
            expected_version=2,
        )
        == paused
    )
    assert (
        reopened.get_operation(
            observation_id="obs",
            request_id="advance-b",
            kind="advance",
            request_fingerprint="request-b",
        )
        == blocked
    )
    detail = reopened.get("obs")
    assert detail["lifecycle"] == "paused"
    assert detail["source"]["params"] == {"short_period": 5}
    assert detail["publications"][0]["published_at"] == NOW.isoformat()
    assert detail["publications"][0]["payload"]["published_at"] == NOW.isoformat()
    assert reopened.list() == [detail]
    assert reopened.get("missing") is None
    with sqlite3.connect(database.path) as conn:
        receipt = conn.execute(
            "SELECT result_json FROM research_observation_operations WHERE request_id='pause'"
        ).fetchone()[0]
        assert "publications" not in receipt


def test_request_identity_conflicts_are_checked_before_cas(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    _advance(repo)
    with pytest.raises(ValueError, match="request_conflict"):
        _advance(repo, request_fingerprint="different")
    with pytest.raises(ValueError, match="request_conflict"):
        repo.pause(
            observation_id="obs",
            request_id="advance-a",
            request_fingerprint="advance-request-a",
            expected_version=1,
        )
    with pytest.raises(ValueError, match="identity_conflict"):
        repo.start(
            observation_id="obs",
            request_id="new",
            request_fingerprint="new",
            source_backtest_result_id=17,
            source={},
            code_binding={},
            policy={},
            universe=[],
        )


def test_pause_prevents_stale_or_current_version_publication(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    repo.pause(
        observation_id="obs",
        request_id="pause",
        request_fingerprint="pause",
        expected_version=0,
    )
    with pytest.raises(ValueError, match="version_conflict"):
        _advance(repo)
    with pytest.raises(ValueError, match="paused"):
        _advance(repo, expected_version=1)
    assert repo.get("obs")["publications"] == []


def test_competing_versions_publish_only_once(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    barrier = threading.Barrier(2)

    def publish(request_id):
        barrier.wait(timeout=5)
        try:
            return _advance(repo, request_id=request_id)["version"]
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, ["a", "b"]))
    assert sorted(map(str, results)) == ["1", "research_observation_version_conflict"]
    assert len(repo.get("obs")["publications"]) == 1


def test_active_observation_limit_is_atomic_and_retries_do_not_consume_slots(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    barrier = threading.Barrier(2)

    def start_one(observation_id):
        barrier.wait(timeout=5)
        try:
            return repo.start(
                observation_id=observation_id,
                request_id="start",
                request_fingerprint="start",
                source_backtest_result_id=17,
                source={},
                code_binding={},
                policy={},
                universe=[],
                max_active_observations=1,
            )
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(start_one, ["a", "b"]))
    assert "research_observation_active_limit_reached" in results
    winner = next(result for result in results if isinstance(result, dict))
    assert (
        repo.start(
            observation_id=winner["id"],
            request_id="start",
            request_fingerprint="start",
            source_backtest_result_id=17,
            source={},
            code_binding={},
            policy={},
            universe=[],
            max_active_observations=1,
        )
        == winner
    )
    repo.pause(
        observation_id=winner["id"],
        request_id="pause",
        request_fingerprint="pause",
        expected_version=0,
    )
    assert (
        repo.start(
            observation_id="new",
            request_id="start",
            request_fingerprint="start",
            source_backtest_result_id=17,
            source={},
            code_binding={},
            policy={},
            universe=[],
            max_active_observations=1,
        )["lifecycle"]
        == "active"
    )


def test_lock_wait_cannot_backdate_publication_before_deadline(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    clock_called = threading.Event()
    worker_started = threading.Event()
    deadline = NOW + timedelta(minutes=1)

    def late_clock():
        clock_called.set()
        return deadline

    late_repo = ResearchObservationsRepository(database.path, clock=late_clock)

    def publish():
        worker_started.set()
        return _advance(late_repo, publication_deadline=deadline)

    with (
        sqlite3.connect(database.path) as locked,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        locked.execute("BEGIN IMMEDIATE")
        future = pool.submit(publish)
        assert worker_started.wait(timeout=2)
        assert not clock_called.wait(timeout=0.1)
        locked.commit()
        with pytest.raises(ValueError, match="publication_deadline_elapsed"):
            future.result(timeout=5)
    assert clock_called.is_set()
    assert repo.get("obs")["version"] == 0
    assert repo.get("obs")["publications"] == []
    assert (
        repo.get_operation(
            observation_id="obs",
            request_id="advance-a",
            kind="advance",
            request_fingerprint="advance-request-a",
        )
        is None
    )


def test_outcome_failure_rolls_back_publication_state_and_receipt(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    with pytest.raises(ValueError, match="outcome_publication_mismatch"):
        _advance(
            repo,
            outcomes=[
                {
                    "publication_id": "missing",
                    "horizon": 1,
                    "dataset_id": "future",
                    "payload": {},
                }
            ],
        )
    assert repo.get("obs")["version"] == 0
    assert repo.get("obs")["publications"] == []
    _advance(repo)


def test_exact_sessions_and_outcomes_are_immutable(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    _advance(repo)
    with pytest.raises(ValueError, match="session_already_published"):
        _advance(
            repo,
            request_id="revision",
            expected_version=1,
            publication={**_publication("revision"), "dataset_id": "revised"},
        )
    outcome = {
        "publication_id": "pub",
        "horizon": 1,
        "dataset_id": "future",
        "payload": {"weighted_price_response": "0.01"},
    }
    result = _advance(
        repo,
        request_id="measure",
        expected_version=1,
        publication=None,
        outcomes=[outcome],
    )
    assert result["outcome_keys"] == [{"publication_id": "pub", "horizon": 1}]
    assert repo.get("obs")["outcomes"][0]["measured_at"] == NOW.isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        _advance(
            repo,
            request_id="remeasure",
            expected_version=2,
            publication=None,
            outcomes=[{**outcome, "dataset_id": "revised"}],
        )
    assert repo.get("obs")["version"] == 2
    with sqlite3.connect(database.path) as conn:
        for table in (
            "research_observation_publications",
            "research_observation_outcomes",
            "research_observation_operations",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(f"DELETE FROM {table}")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE research_observations SET source_json='{}'")


def test_outcomes_cannot_cross_observation_identities(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    _advance(repo)
    _start(repo, "other")
    with pytest.raises(ValueError, match="outcome_publication_mismatch"):
        repo.advance(
            observation_id="other",
            request_id="measure",
            request_fingerprint="measure",
            expected_version=0,
            outcomes=[
                {
                    "publication_id": "pub",
                    "horizon": 1,
                    "dataset_id": "future",
                    "payload": {},
                }
            ],
        )


def test_paused_observation_can_measure_existing_targets_without_publication(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    _advance(repo)
    repo.pause(
        observation_id="obs",
        request_id="pause",
        request_fingerprint="pause",
        expected_version=1,
    )
    result = _advance(
        repo,
        request_id="measure",
        expected_version=2,
        publication=None,
        outcomes=[
            {
                "publication_id": "pub",
                "horizon": 1,
                "dataset_id": "future",
                "payload": {"weighted_price_response": "0.01"},
            }
        ],
    )
    assert result["lifecycle"] == "paused"
    assert result["publication_id"] is None
    detail = repo.get("obs")
    assert len(detail["outcomes"]) == 1
    assert len(detail["publications"]) == 1


def test_clock_reversal_and_caller_publication_time_fail_closed(database):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    reversed_repo = ResearchObservationsRepository(
        database.path,
        clock=lambda: NOW - timedelta(microseconds=1),
    )
    with pytest.raises(ValueError, match="clock_reversed"):
        _advance(reversed_repo)
    with pytest.raises(ValueError, match="publication_clock_owned"):
        _advance(
            repo,
            publication={
                **_publication(),
                "payload": {"published_at": NOW.isoformat()},
            },
        )
    assert repo.get("obs")["version"] == 0


@pytest.mark.parametrize("publishing", [True, False])
def test_clock_step_between_computation_and_lock_cannot_backdate_evidence(
    database, publishing
):
    repo = ResearchObservationsRepository(database.path, clock=lambda: NOW)
    _start(repo)
    _advance(repo)
    # The locked clock is later than the previous operation but earlier than
    # the current calculation's data-availability check.
    locked_at = NOW + timedelta(minutes=30)
    calculated_at = NOW + timedelta(hours=1)
    later_repo = ResearchObservationsRepository(database.path, clock=lambda: locked_at)
    with pytest.raises(ValueError, match="computation_clock_reversed"):
        _advance(
            later_repo,
            request_id="next",
            expected_version=1,
            publication=_publication("next", "2026-09-22") if publishing else None,
            computation_not_before=calculated_at,
            outcomes=[
                {
                    "publication_id": "pub",
                    "horizon": 1,
                    "dataset_id": "future",
                    "payload": {"evaluated_at": calculated_at.isoformat()},
                }
            ],
        )
    detail = repo.get("obs")
    assert detail["version"] == 1
    assert len(detail["publications"]) == 1
    assert detail["outcomes"] == []
    assert (
        repo.get_operation(
            observation_id="obs",
            request_id="next",
            kind="advance",
            request_fingerprint="advance-request-a",
        )
        is None
    )


def test_upgrade_v21_preserves_migration_history_and_reopens(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    registry = migrations.migration_registry()
    with sqlite3.connect(path) as conn:
        db_module._initialize_v1_baseline_schema(conn)
        with monkeypatch.context() as context:
            context.setattr(
                migrations,
                "_MIGRATIONS",
                tuple(item for item in registry if item.version <= 21),
            )
            migrations.apply_schema_migrations(
                conn,
                baseline_initializer=db_module._initialize_v1_baseline_schema,
            )
        old = conn.execute(
            "SELECT * FROM schema_migrations ORDER BY version"
        ).fetchall()
        migrations.apply_schema_migrations(
            conn,
            baseline_initializer=db_module._initialize_v1_baseline_schema,
        )
        current = conn.execute(
            "SELECT * FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert current[: len(old)] == old
        assert current[21][0:2] == (22, "persist_independent_research_observations")
        assert current[-1][0] == registry[-1].version
        migrations.apply_schema_migrations(
            conn,
            baseline_initializer=db_module._initialize_v1_baseline_schema,
        )
        assert (
            conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
            == current
        )
    repo = ResearchObservationsRepository(path, clock=lambda: NOW)
    _start(repo)
    assert repo.get("obs")["publications"] == []


def test_missing_immutable_history_guard_blocks_reopen(database):
    with sqlite3.connect(database.path) as conn:
        conn.execute("DROP TRIGGER research_observation_publications_update_guard")
    with pytest.raises(RuntimeError, match="schema contract mismatch"):
        database.init_sync()
