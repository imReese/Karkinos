from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from threading import Barrier

import pytest

from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    CAPTURE_TOOL_BY_TYPE,
    CapturedProjection,
    CaptureEvidenceType,
    CaptureSourceBatch,
    ContextCaptureAuditStore,
    HumanContextCaptureRequest,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.evidence import (
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.ai_runtime.tasks import (
    REVIEW_CONFIRMATION,
    TASK_CONFIRMATION,
    HumanResearchTaskRequest,
    HumanResearchTaskReviewRequest,
    HumanResearchTaskService,
    ResearchTaskRejected,
    ResearchTaskReviewDecision,
    ResearchTaskStatus,
    ResearchTaskStore,
)

NOW = "2026-07-13T14:00:00+00:00"
VALUATION_ID = "valuation-research-task-001"
LEDGER_CUTOFF_ID = 144
LEDGER_FINGERPRINT = "ledger-research-task-fingerprint-001"


class FixtureSource:
    def __init__(self, statuses: dict[CaptureEvidenceType, str] | None = None):
        self.statuses = statuses or {}

    async def load(self, request: HumanContextCaptureRequest) -> CaptureSourceBatch:
        return CaptureSourceBatch(
            valuation_snapshot_id=VALUATION_ID,
            ledger_cutoff_id=LEDGER_CUTOFF_ID,
            ledger_fingerprint=LEDGER_FINGERPRINT,
            projections=tuple(
                CapturedProjection(
                    tool_name=CAPTURE_TOOL_BY_TYPE[item],
                    status=self.statuses.get(item, "complete"),
                    as_of=NOW,
                    source_schema_version=f"karkinos.fixture.{item.value}.v1",
                    payload={
                        "fixture": item.value,
                        "valuation_snapshot_id": VALUATION_ID,
                        "ledger_cutoff_id": LEDGER_CUTOFF_ID,
                        "ledger_fingerprint": LEDGER_FINGERPRINT,
                        "persisted_facts_only": True,
                    },
                )
                for item in request.evidence_types
            ),
        )


def _stores(db_path):
    evidence = CanonicalEvidenceRepository(db_path)
    contexts = AiAuditStore(db_path)
    captures = ContextCaptureAuditStore(db_path)
    tasks = ResearchTaskStore(db_path)
    evidence.init()
    contexts.init()
    captures.init()
    tasks.init()
    return evidence, contexts, captures, tasks


async def _capture(db_path, *, statuses=None):
    evidence, contexts, captures, _ = _stores(db_path)
    request = HumanContextCaptureRequest(
        idempotency_key="task-context-capture-001",
        requested_by="human:reese",
        research_question="Which persisted facts require human review?",
        account_alias="primary",
        evidence_types=(
            CaptureEvidenceType.PORTFOLIO,
            CaptureEvidenceType.ACCOUNT_STATE,
            CaptureEvidenceType.ACCOUNT_TRUTH,
        ),
        confirmation=CAPTURE_CONFIRMATION,
    )
    result = await HumanResearchContextCaptureService(
        source=FixtureSource(statuses),
        evidence_repository=evidence,
        context_store=contexts,
        capture_store=captures,
        now=lambda: NOW,
    ).capture(request)
    return result


def _service(db_path, *, task_store=None):
    evidence, contexts, captures, tasks = _stores(db_path)
    return HumanResearchTaskService(
        evidence_repository=evidence,
        context_store=contexts,
        capture_store=captures,
        task_store=tasks if task_store is None else task_store,
        now=lambda: NOW,
    )


def _task_request(capture_id: str, *, title="Review current account evidence"):
    return HumanResearchTaskRequest(
        idempotency_key="human-research-task-001",
        capture_id=capture_id,
        created_by="human:reese",
        title=title,
        research_question="What claims are supported by this frozen evidence?",
        confirmation=TASK_CONFIRMATION,
    )


def _review_request(
    decision=ResearchTaskReviewDecision.CONTEXT_ACCEPTED,
    *,
    key="human-research-review-001",
    note="The bound evidence identity is suitable for later analysis.",
):
    return HumanResearchTaskReviewRequest(
        idempotency_key=key,
        reviewed_by="human:reese",
        decision=decision,
        note=note,
        confirmation=REVIEW_CONFIRMATION,
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_task_is_restartable_and_has_no_financial_or_execution_authority(
    tmp_path,
):
    db_path = tmp_path / "research-task.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for table in (
            "oms_orders",
            "ledger_entries",
            "risk_decisions",
            "runtime_controls",
            "capital_authorizations",
        ):
            conn.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
            )
            conn.execute(f"INSERT INTO {table} (marker) VALUES ('protected')")

    capture = await _capture(db_path)
    request = _task_request(capture.run.capture_id)
    first = _service(db_path).create(request)

    assert first.reused is False
    assert first.task.status == ResearchTaskStatus.AWAITING_HUMAN_REVIEW
    assert first.task.context_snapshot_id == capture.context.snapshot_id
    assert first.task.valuation_snapshot_id == VALUATION_ID
    assert first.task.ledger_cutoff_id == LEDGER_CUTOFF_ID
    assert first.task.ledger_fingerprint == LEDGER_FINGERPRINT
    assert first.task.all_evidence_authoritative is True
    assert first.to_dict()["model_execution_enabled"] is False
    assert first.to_dict()["workflow_started"] is False
    assert first.to_dict()["authority_effect"] == "none"

    restarted = _service(db_path).create(request)
    assert restarted.reused is True
    assert restarted.task == first.task

    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_research_tasks").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_research_task_events").fetchone()[0]
            == 1
        )
        for table in (
            "oms_orders",
            "ledger_entries",
            "risk_decisions",
            "runtime_controls",
            "capital_authorizations",
        ):
            assert conn.execute(f"SELECT marker FROM {table}").fetchone()[0] == (
                "protected"
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_task_and_review_idempotency_reject_changed_input(tmp_path):
    db_path = tmp_path / "research-task.db"
    capture = await _capture(db_path)
    service = _service(db_path)
    task = service.create(_task_request(capture.run.capture_id)).task

    with pytest.raises(IdempotencyConflict, match="different input"):
        service.create(
            _task_request(capture.run.capture_id, title="Changed research task")
        )

    first = service.review(task.task_id, _review_request())
    repeated = _service(db_path).review(task.task_id, _review_request())
    assert first.reused is False
    assert repeated.reused is True
    assert repeated.review == first.review

    with pytest.raises(IdempotencyConflict, match="different input"):
        service.review(
            task.task_id,
            _review_request(
                ResearchTaskReviewDecision.CLOSED_WITHOUT_ANALYSIS,
                note="Changed decision with the same key.",
            ),
        )


@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize("changed_request", (False, True))
async def test_concurrent_task_creation_preserves_idempotency(
    tmp_path, changed_request
):
    db_path = tmp_path / "concurrent-task-create.db"
    capture = await _capture(db_path)
    both_read_missing = Barrier(2)

    class MissingTaskCursor:
        def __init__(self, cursor, connection):
            self.cursor, self.connection = cursor, connection

        def fetchone(self):
            row = self.cursor.fetchone()
            if row is None and not self.connection.in_transaction:
                both_read_missing.wait(timeout=5)
            return row

    class InterleavedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, *args):
            cursor = self.connection.execute(sql, *args)
            if "SELECT * FROM ai_research_tasks WHERE idempotency_key = ?" in sql:
                return MissingTaskCursor(cursor, self.connection)
            return cursor

        def __getattr__(self, name):
            return getattr(self.connection, name)

    class InterleavedStore(ResearchTaskStore):
        @contextmanager
        def _connection(self):
            with super()._connection() as connection:
                yield InterleavedConnection(connection)

    first = _task_request(capture.run.capture_id)
    second = (
        _task_request(capture.run.capture_id, title="A different research task")
        if changed_request
        else first
    )
    services = [
        _service(db_path, task_store=InterleavedStore(db_path)) for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.create, request)
            for service, request in zip(services, (first, second), strict=True)
        ]
        results, errors = [], []
        for future in futures:
            try:
                results.append(future.result(timeout=10))
            except Exception as exc:
                errors.append(exc)

    if changed_request:
        assert len(results) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], IdempotencyConflict)
    else:
        assert not errors
        assert sorted(result.reused for result in results) == [False, True]
        assert results[0].task == results[1].task
    winner = next(result for result in results if not result.reused)
    winner_request = (
        first if winner.task.request_fingerprint == first.fingerprint else second
    )
    reopened = _service(db_path)
    reused = reopened.create(winner_request)
    assert reused.reused is True
    assert reused.task == winner.task
    assert reused.task.status == ResearchTaskStatus.AWAITING_HUMAN_REVIEW
    assert reused.task.context_snapshot_id == capture.context.snapshot_id
    replay = reopened.replay(winner.task.task_id)
    assert replay.valid is True
    assert replay.event_count == 1
    assert replay.replayed_status == ResearchTaskStatus.AWAITING_HUMAN_REVIEW
    with closing(sqlite3.connect(db_path)) as connection:
        for table, count in (
            ("ai_research_tasks", 1),
            ("ai_research_task_events", 1),
            ("ai_research_task_reviews", 0),
            ("ai_workflows", 0),
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                == count
            )


@pytest.mark.trading_safety
@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_request", ("different_key", "exact", "changed"))
async def test_concurrent_task_reviews_persist_one_final_decision(
    tmp_path, concurrent_request
):
    db_path = tmp_path / "concurrent-task-review.db"
    capture = await _capture(db_path)
    task = _service(db_path).create(_task_request(capture.run.capture_id)).task
    both_read_pending = Barrier(2)

    class InterleavedStore(ResearchTaskStore):
        active_connection = None

        @contextmanager
        def _connection(self):
            with super()._connection() as connection:
                self.active_connection = connection
                try:
                    yield connection
                finally:
                    self.active_connection = None

        def _task_from_row(self, row):
            current = super()._task_from_row(row)
            connection = self.active_connection
            # Synchronize only unprotected reads, fixing a legal stale-read
            # interleaving without changing SQLite rows or blocking a writer
            # that already owns the transaction. An optimistic CAS also passes.
            if (
                current.status == ResearchTaskStatus.AWAITING_HUMAN_REVIEW
                and connection is not None
                and not connection.in_transaction
            ):
                both_read_pending.wait(timeout=5)
            return current

    first = _review_request(key="concurrent-review")
    second = (
        first
        if concurrent_request == "exact"
        else _review_request(
            ResearchTaskReviewDecision.CLOSED_WITHOUT_ANALYSIS,
            key=(
                "another-review"
                if concurrent_request == "different_key"
                else first.idempotency_key
            ),
            note="This request independently closes the same frozen task.",
        )
    )
    services = [
        _service(db_path, task_store=InterleavedStore(db_path)) for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.review, task.task_id, request)
            for service, request in zip(services, (first, second), strict=True)
        ]
        results, errors = [], []
        for future in futures:
            try:
                results.append(future.result(timeout=10))
            except Exception as exc:
                errors.append(exc)

    if concurrent_request == "exact":
        assert not errors
        assert sorted(result.reused for result in results) == [False, True]
        assert results[0].review == results[1].review
    else:
        assert len(results) == 1
        assert len(errors) == 1
        expected_error = (
            ResearchTaskRejected
            if concurrent_request == "different_key"
            else IdempotencyConflict
        )
        assert isinstance(errors[0], expected_error)
    winner = next(result for result in results if not result.reused)
    reopened = _service(db_path)
    persisted = reopened.get(task.task_id)
    assert persisted.status.value == winner.review.decision.value
    assert persisted.context_snapshot_id == capture.context.snapshot_id
    assert persisted.evidence == task.evidence
    replay = reopened.replay(task.task_id)
    assert replay.valid is True
    assert replay.event_count == 2
    assert replay.replayed_status == persisted.status
    winner_request = first if winner.review.decision == first.decision else second
    reused = reopened.review(task.task_id, winner_request)
    assert reused.reused is True
    assert reused.review == winner.review
    assert reused.to_dict()["model_execution_enabled"] is False
    assert reused.to_dict()["workflow_started"] is False
    assert reused.to_dict()["authority_effect"] == "none"
    with closing(sqlite3.connect(db_path)) as connection:
        for table, count in (
            ("ai_research_task_reviews", 1),
            ("ai_research_task_events", 2),
            ("ai_workflows", 0),
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                == count
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_authoritative_evidence_blocks_acceptance_but_allows_revision(
    tmp_path,
):
    db_path = tmp_path / "research-task.db"
    capture = await _capture(
        db_path,
        statuses={CaptureEvidenceType.ACCOUNT_TRUTH: "unreconciled"},
    )
    service = _service(db_path)
    task = service.create(_task_request(capture.run.capture_id)).task

    assert task.status == ResearchTaskStatus.BLOCKED_BY_EVIDENCE
    assert task.all_evidence_authoritative is False
    assert task.blockers == (
        "evidence_not_authoritative:account_truth.read:unreconciled",
    )
    with pytest.raises(ResearchTaskRejected, match="cannot be accepted"):
        service.review(task.task_id, _review_request())

    result = service.review(
        task.task_id,
        _review_request(
            ResearchTaskReviewDecision.CONTEXT_REVISION_REQUESTED,
            note="Reconcile account truth before any analysis.",
        ),
    )
    assert result.task.status == ResearchTaskStatus.CONTEXT_REVISION_REQUESTED
    assert result.to_dict()["model_execution_enabled"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_review_fails_closed_when_bound_evidence_drifted(tmp_path):
    db_path = tmp_path / "research-task.db"
    capture = await _capture(db_path)
    service = _service(db_path)
    task = service.create(_task_request(capture.run.capture_id)).task
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? WHERE reference_id = ?",
            ('{"tampered":true}', capture.records[0].reference_id),
        )

    with pytest.raises(EvidenceIdentityMismatch, match="payload fingerprint drift"):
        service.review(task.task_id, _review_request())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_review_and_audit_chain_replay_deterministically(tmp_path):
    db_path = tmp_path / "research-task.db"
    capture = await _capture(db_path)
    service = _service(db_path)
    task = service.create(_task_request(capture.run.capture_id)).task
    reviewed = service.review(task.task_id, _review_request())

    replay = _service(db_path).replay(task.task_id)
    assert replay.valid is True
    assert replay.event_count == 2
    assert replay.replayed_status == ResearchTaskStatus.CONTEXT_ACCEPTED
    assert replay.final_event_hash
    assert reviewed.task.status == ResearchTaskStatus.CONTEXT_ACCEPTED

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_research_task_events SET payload_json = ? "
            "WHERE task_id = ? AND sequence = 2",
            ('{"status":"closed_without_analysis"}', task.task_id),
        )
    with pytest.raises(EvidenceIdentityMismatch, match="event hash drifted"):
        _service(db_path).replay(task.task_id)


@pytest.mark.unit
def test_task_requires_explicit_human_confirmations():
    with pytest.raises(ValueError, match="model-free research task confirmation"):
        HumanResearchTaskRequest(
            idempotency_key="task-invalid",
            capture_id="capture-invalid",
            created_by="human:reese",
            title="Invalid task",
            research_question="Should not persist",
            confirmation="",
        )
    with pytest.raises(ValueError, match="model-free research review confirmation"):
        HumanResearchTaskReviewRequest(
            idempotency_key="review-invalid",
            reviewed_by="human:reese",
            decision=ResearchTaskReviewDecision.CLOSED_WITHOUT_ANALYSIS,
            note="Should not persist",
            confirmation="",
        )


@pytest.mark.unit
def test_empty_task_reads_do_not_initialize_or_change_database_schema(tmp_path):
    db_path = tmp_path / "research-task-read.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE existing_financial_fact (id INTEGER PRIMARY KEY)")
        before = conn.execute("PRAGMA schema_version").fetchone()[0]

    store = ResearchTaskStore(db_path)

    assert store.list() == ()
    with pytest.raises(LookupError, match="research task not found"):
        store.get("missing-task")
    with closing(sqlite3.connect(db_path)) as conn:
        after = conn.execute("PRAGMA schema_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert after == before
    assert tables == {"existing_financial_fact"}
