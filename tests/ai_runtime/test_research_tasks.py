from __future__ import annotations

import sqlite3
from contextlib import closing

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


def _service(db_path):
    evidence, contexts, captures, tasks = _stores(db_path)
    return HumanResearchTaskService(
        evidence_repository=evidence,
        context_store=contexts,
        capture_store=captures,
        task_store=tasks,
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
