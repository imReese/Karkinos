from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    CAPTURE_TOOL_BY_TYPE,
    CapturedProjection,
    CaptureEvidenceType,
    CaptureRunStatus,
    CaptureSelectionError,
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

NOW = "2026-07-13T12:00:00+00:00"
VALUATION_ID = "valuation-capture-001"
LEDGER_CUTOFF_ID = 83
LEDGER_FINGERPRINT = "ledger-capture-fingerprint-001"


def _request(
    *,
    idempotency_key: str = "capture-primary-001",
    question: str = "What evidence needs review?",
    evidence_types: tuple[CaptureEvidenceType, ...] = (
        CaptureEvidenceType.PORTFOLIO,
        CaptureEvidenceType.ACCOUNT_STATE,
    ),
) -> HumanContextCaptureRequest:
    return HumanContextCaptureRequest(
        idempotency_key=idempotency_key,
        requested_by="human:reese",
        research_question=question,
        account_alias="primary",
        evidence_types=evidence_types,
        confirmation=CAPTURE_CONFIRMATION,
        backtest_result_id=(
            7 if CaptureEvidenceType.RESEARCH_EVIDENCE in evidence_types else None
        ),
        paper_shadow_run_id=(
            "paper-shadow-007"
            if CaptureEvidenceType.PAPER_SHADOW in evidence_types
            else None
        ),
    )


def _projection(
    evidence_type: CaptureEvidenceType,
    *,
    status: str = "complete",
) -> CapturedProjection:
    return CapturedProjection(
        tool_name=CAPTURE_TOOL_BY_TYPE[evidence_type],
        status=status,
        as_of=NOW,
        source_schema_version=f"karkinos.fixture.{evidence_type.value}.v1",
        payload={
            "fixture": evidence_type.value,
            "valuation_snapshot_id": VALUATION_ID,
            "ledger_cutoff_id": LEDGER_CUTOFF_ID,
            "ledger_fingerprint": LEDGER_FINGERPRINT,
            "persisted_facts_only": True,
        },
    )


def _batch(
    evidence_types: tuple[CaptureEvidenceType, ...],
    *,
    statuses: dict[CaptureEvidenceType, str] | None = None,
) -> CaptureSourceBatch:
    statuses = statuses or {}
    return CaptureSourceBatch(
        valuation_snapshot_id=VALUATION_ID,
        ledger_cutoff_id=LEDGER_CUTOFF_ID,
        ledger_fingerprint=LEDGER_FINGERPRINT,
        projections=tuple(
            _projection(item, status=statuses.get(item, "complete"))
            for item in evidence_types
        ),
    )


class FixtureCaptureSource:
    def __init__(self, batch: CaptureSourceBatch) -> None:
        self.batch = batch
        self.calls = 0

    async def load(self, request: HumanContextCaptureRequest) -> CaptureSourceBatch:
        self.calls += 1
        return self.batch


class ExplodingCaptureSource:
    async def load(self, request: HumanContextCaptureRequest) -> CaptureSourceBatch:
        raise AssertionError("completed capture must restore without source reads")


class FailingContextStore:
    def __init__(self, delegate: AiAuditStore) -> None:
        self.delegate = delegate

    def save_context(self, context) -> None:
        raise RuntimeError("fixture context persistence failure")

    def get_context(self, snapshot_id: str):
        return self.delegate.get_context(snapshot_id)


def _stores(db_path):
    evidence = CanonicalEvidenceRepository(db_path)
    contexts = AiAuditStore(db_path)
    captures = ContextCaptureAuditStore(db_path)
    evidence.init()
    contexts.init()
    captures.init()
    return evidence, contexts, captures


def _service(db_path, source, *, context_store=None):
    evidence, contexts, captures = _stores(db_path)
    return HumanResearchContextCaptureService(
        source=source,
        evidence_repository=evidence,
        context_store=context_store or contexts,
        capture_store=captures,
        now=lambda: NOW,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"confirmation": ""}, "explicit read-only capture confirmation"),
        ({"evidence_types": ()}, "at least one evidence type"),
        (
            {
                "evidence_types": (
                    CaptureEvidenceType.PORTFOLIO,
                    CaptureEvidenceType.PORTFOLIO,
                )
            },
            "must be unique",
        ),
        (
            {"evidence_types": (CaptureEvidenceType.RESEARCH_EVIDENCE,)},
            "backtest_result_id is required",
        ),
        (
            {"evidence_types": (CaptureEvidenceType.PAPER_SHADOW,)},
            "paper_shadow_run_id is required",
        ),
    ],
)
def test_capture_request_requires_explicit_bounded_selection(overrides, message):
    values = {
        "idempotency_key": "capture-validation",
        "requested_by": "human:reese",
        "research_question": "Review frozen facts",
        "account_alias": "primary",
        "evidence_types": (CaptureEvidenceType.PORTFOLIO,),
        "confirmation": CAPTURE_CONFIRMATION,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        HumanContextCaptureRequest(**values)


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.asyncio
async def test_capture_is_restartable_and_never_changes_financial_authority(tmp_path):
    db_path = tmp_path / "capture.db"
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

    request = _request()
    source = FixtureCaptureSource(_batch(request.evidence_types))
    first = await _service(db_path, source).capture(request)

    assert first.run.status == CaptureRunStatus.COMPLETED
    assert first.reused is False
    assert source.calls == 1
    assert first.context.valuation_snapshot_id == VALUATION_ID
    assert first.context.ledger_cutoff_id == LEDGER_CUTOFF_ID
    assert first.context.ledger_fingerprint == LEDGER_FINGERPRINT
    assert [record.tool_name for record in first.records] == list(
        request.requested_tools
    )
    assert first.to_dict()["model_invocation_count"] == 0
    assert first.to_dict()["workflow_started"] is False
    assert first.to_dict()["authority_effect"] == "none"

    restarted = await _service(db_path, ExplodingCaptureSource()).capture(request)
    assert restarted.reused is True
    assert restarted.context == first.context
    assert restarted.records == first.records

    capture_store = ContextCaptureAuditStore(db_path)
    late_failure = capture_store.mark_failed(
        first.run.capture_id,
        failure_code="late_concurrent_failure",
        updated_at=NOW,
    )
    assert late_failure.status == CaptureRunStatus.COMPLETED
    assert late_failure.context_snapshot_id == first.context.snapshot_id

    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_context_capture_runs").fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_canonical_evidence").fetchone()[0]
            == 2
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
async def test_capture_idempotency_key_rejects_changed_request(tmp_path):
    db_path = tmp_path / "capture.db"
    request = _request()
    await _service(
        db_path,
        FixtureCaptureSource(_batch(request.evidence_types)),
    ).capture(request)

    with pytest.raises(IdempotencyConflict, match="different input"):
        await _service(
            db_path,
            FixtureCaptureSource(_batch(request.evidence_types)),
        ).capture(_request(question="A different research question"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capture_retries_after_partial_audit_stage_without_duplication(tmp_path):
    db_path = tmp_path / "capture.db"
    request = _request()
    evidence, contexts, captures = _stores(db_path)
    source = FixtureCaptureSource(_batch(request.evidence_types))
    failing = HumanResearchContextCaptureService(
        source=source,
        evidence_repository=evidence,
        context_store=FailingContextStore(contexts),
        capture_store=captures,
        now=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="context persistence failure"):
        await failing.capture(request)

    with closing(sqlite3.connect(db_path)) as conn:
        failed = conn.execute(
            "SELECT status, failure_code, evidence_reference_ids_json "
            "FROM ai_context_capture_runs"
        ).fetchone()
        assert failed[:2] == ("failed", "capture_runtime_error")
        assert len(json.loads(failed[2])) == 2
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_canonical_evidence").fetchone()[0]
            == 2
        )

    retried = await _service(
        db_path,
        ExplodingCaptureSource(),
    ).capture(request)
    assert retried.reused is True
    assert retried.run.status == CaptureRunStatus.COMPLETED
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_canonical_evidence").fetchone()[0]
            == 2
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capture_fails_closed_on_wrong_tool_order_and_records_failure(tmp_path):
    db_path = tmp_path / "capture.db"
    request = _request()
    wrong_order = tuple(reversed(request.evidence_types))

    with pytest.raises(CaptureSelectionError, match="exact requested tool order"):
        await _service(
            db_path,
            FixtureCaptureSource(_batch(wrong_order)),
        ).capture(request)

    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute(
            "SELECT status, failure_code FROM ai_context_capture_runs"
        ).fetchone() == ("failed", "capture_selection_error")
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_canonical_evidence").fetchone()[0]
            == 0
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capture_exposes_noncomplete_evidence_as_nonauthoritative(tmp_path):
    db_path = tmp_path / "capture.db"
    evidence_types = (
        CaptureEvidenceType.PORTFOLIO,
        CaptureEvidenceType.ACCOUNT_TRUTH,
    )
    request = _request(evidence_types=evidence_types)
    source = FixtureCaptureSource(
        _batch(
            evidence_types,
            statuses={
                CaptureEvidenceType.PORTFOLIO: "stale",
                CaptureEvidenceType.ACCOUNT_TRUTH: "unreconciled",
            },
        )
    )

    result = await _service(db_path, source).capture(request)

    evidence = result.to_dict()["evidence"]
    assert [item["status"] for item in evidence] == ["stale", "unreconciled"]
    assert [item["authoritative"] for item in evidence] == [False, False]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_completed_capture_detects_tampered_evidence_on_replay(tmp_path):
    db_path = tmp_path / "capture.db"
    request = _request()
    result = await _service(
        db_path,
        FixtureCaptureSource(_batch(request.evidence_types)),
    ).capture(request)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE ai_canonical_evidence SET payload_json = ? "
            "WHERE reference_id = ?",
            ('{"tampered":true}', result.records[0].reference_id),
        )

    with pytest.raises(EvidenceIdentityMismatch, match="payload fingerprint drift"):
        await _service(db_path, ExplodingCaptureSource()).capture(request)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_completed_capture_detects_tampered_context_on_replay(tmp_path):
    db_path = tmp_path / "capture.db"
    request = _request()
    result = await _service(
        db_path,
        FixtureCaptureSource(_batch(request.evidence_types)),
    ).capture(request)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM ai_context_snapshots WHERE snapshot_id = ?",
                (result.context.snapshot_id,),
            ).fetchone()[0]
        )
        payload["account_alias"] = "tampered"
        conn.execute(
            "UPDATE ai_context_snapshots SET payload_json = ? WHERE snapshot_id = ?",
            (json.dumps(payload), result.context.snapshot_id),
        )

    with pytest.raises(EvidenceIdentityMismatch, match="context payload"):
        await _service(db_path, ExplodingCaptureSource()).capture(request)
