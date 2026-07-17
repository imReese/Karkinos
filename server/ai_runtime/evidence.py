"""Persisted, evidence-bound read adapters for canonical Karkinos projections.

This module does not calculate portfolio, account, risk, reconciliation, or
paper/shadow facts.  An explicit capture caller supplies an already-built
canonical projection together with its immutable valuation and ledger
identity.  AI tools may then read only that frozen record.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from .contracts import (
    EvidenceBoundContextSnapshot,
    EvidenceReference,
    JsonObject,
    canonical_json,
    content_fingerprint,
)


class EvidenceIdentityMismatch(ValueError):
    """Raised when evidence does not match its frozen financial context."""


class EvidenceReadDenied(PermissionError):
    """Raised when a read attempts to escape its bound evidence context."""


CANONICAL_EVIDENCE_KINDS: Mapping[str, str] = {
    "portfolio_projection.read": "canonical_portfolio_projection",
    "account_state_projection.read": "canonical_account_state_projection",
    "operations_summary.read": "canonical_operations_summary",
    "research_evidence.read": "research_evidence_bundle",
    "account_truth.read": "account_truth_evidence",
    "paper_shadow_evidence.read": "paper_shadow_evidence",
    "strategy_contribution.read": "strategy_contribution_evidence",
}

_EVIDENCE_STATUSES = frozenset(
    {
        "complete",
        "degraded",
        "partial",
        "blocked",
        "missing",
        "stale",
        "estimated",
        "unreconciled",
    }
)

_EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_canonical_evidence (
    reference_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    valuation_snapshot_id TEXT NOT NULL,
    ledger_cutoff_id INTEGER NOT NULL CHECK(ledger_cutoff_id >= 0),
    ledger_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    as_of TEXT NOT NULL,
    source_schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    record_fingerprint TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    persisted_facts_only INTEGER NOT NULL CHECK(persisted_facts_only = 1)
);

CREATE INDEX IF NOT EXISTS idx_ai_canonical_evidence_identity
ON ai_canonical_evidence(
    valuation_snapshot_id,
    ledger_cutoff_id,
    ledger_fingerprint,
    tool_name
);
"""


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True)
class CanonicalEvidenceRecord:
    """Immutable copy of one canonical projection at an exact fact identity."""

    reference_id: str
    tool_name: str
    kind: str
    valuation_snapshot_id: str
    ledger_cutoff_id: int
    ledger_fingerprint: str
    status: str
    as_of: str
    source_schema_version: str
    payload: JsonObject
    payload_fingerprint: str
    record_fingerprint: str
    captured_at: str
    persisted_facts_only: bool = True

    def __post_init__(self) -> None:
        for name in (
            "reference_id",
            "tool_name",
            "kind",
            "valuation_snapshot_id",
            "ledger_fingerprint",
            "status",
            "as_of",
            "source_schema_version",
            "payload_fingerprint",
            "record_fingerprint",
            "captured_at",
        ):
            _require_text(str(getattr(self, name)), name)
        if self.ledger_cutoff_id < 0:
            raise ValueError("ledger_cutoff_id must be non-negative")
        if not self.persisted_facts_only:
            raise ValueError("AI evidence must use persisted facts only")
        expected_kind = CANONICAL_EVIDENCE_KINDS.get(self.tool_name)
        if expected_kind is None:
            raise ValueError(f"unsupported canonical evidence tool: {self.tool_name}")
        if self.kind != expected_kind:
            raise ValueError("canonical evidence tool and kind do not match")
        if self.status not in _EVIDENCE_STATUSES:
            raise ValueError(f"unsupported evidence status: {self.status}")
        canonical_json(self.payload)
        _validate_payload_identity(self)
        expected_payload_fingerprint = content_fingerprint(self.payload)
        if self.payload_fingerprint != expected_payload_fingerprint:
            raise EvidenceIdentityMismatch(
                "canonical evidence payload fingerprint drift"
            )
        expected_record_fingerprint = content_fingerprint(
            _record_identity(self, expected_payload_fingerprint)
        )
        if self.record_fingerprint != expected_record_fingerprint:
            raise EvidenceIdentityMismatch(
                "canonical evidence record fingerprint drift"
            )
        if self.reference_id != f"ai-evidence-{expected_record_fingerprint[:24]}":
            raise EvidenceIdentityMismatch("canonical evidence reference id drift")

    @classmethod
    def capture(
        cls,
        *,
        tool_name: str,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
        status: str,
        as_of: str,
        source_schema_version: str,
        payload: Mapping[str, Any],
        captured_at: str,
    ) -> CanonicalEvidenceRecord:
        """Freeze an already-computed canonical payload; perform no calculation."""
        kind = CANONICAL_EVIDENCE_KINDS.get(tool_name)
        if kind is None:
            raise ValueError(f"unsupported canonical evidence tool: {tool_name}")
        frozen_payload = json.loads(canonical_json(dict(payload)))
        payload_fingerprint = content_fingerprint(frozen_payload)
        identity = _record_identity_fields(
            tool_name=tool_name,
            kind=kind,
            valuation_snapshot_id=valuation_snapshot_id,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            status=status,
            as_of=as_of,
            source_schema_version=source_schema_version,
            payload_fingerprint=payload_fingerprint,
        )
        record_fingerprint = content_fingerprint(identity)
        return cls(
            reference_id=f"ai-evidence-{record_fingerprint[:24]}",
            tool_name=tool_name,
            kind=kind,
            valuation_snapshot_id=valuation_snapshot_id,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            status=status,
            as_of=as_of,
            source_schema_version=source_schema_version,
            payload=frozen_payload,
            payload_fingerprint=payload_fingerprint,
            record_fingerprint=record_fingerprint,
            captured_at=captured_at,
        )

    @property
    def authoritative(self) -> bool:
        return self.status == "complete"

    def to_reference(self) -> EvidenceReference:
        return EvidenceReference(
            reference_id=self.reference_id,
            kind=self.kind,
            fingerprint=self.record_fingerprint,
            as_of=self.as_of,
            status=self.status,
            schema_version=self.source_schema_version,
        )

    def to_dict(self) -> JsonObject:
        return asdict(self)


class CanonicalEvidenceRepository:
    """SQLite store limited to immutable ``ai_canonical_evidence`` records."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(_EVIDENCE_SCHEMA)

    def persist(self, record: CanonicalEvidenceRecord) -> CanonicalEvidenceRecord:
        """Persist one content-addressed capture idempotently."""
        payload_json = canonical_json(record.payload)
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM ai_canonical_evidence WHERE reference_id = ?",
                (record.reference_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ai_canonical_evidence (
                        reference_id, tool_name, kind, valuation_snapshot_id,
                        ledger_cutoff_id, ledger_fingerprint, status, as_of,
                        source_schema_version, payload_json, payload_fingerprint,
                        record_fingerprint, captured_at, persisted_facts_only
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        record.reference_id,
                        record.tool_name,
                        record.kind,
                        record.valuation_snapshot_id,
                        record.ledger_cutoff_id,
                        record.ledger_fingerprint,
                        record.status,
                        record.as_of,
                        record.source_schema_version,
                        payload_json,
                        record.payload_fingerprint,
                        record.record_fingerprint,
                        record.captured_at,
                    ),
                )
                return record
            persisted = _record_from_row(existing)
            if persisted.record_fingerprint != record.record_fingerprint:
                raise EvidenceIdentityMismatch(
                    f"conflicting canonical evidence: {record.reference_id}"
                )
            return persisted

    def get(self, reference_id: str) -> CanonicalEvidenceRecord | None:
        """Read one exact record without refreshing or contacting any provider."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_canonical_evidence WHERE reference_id = ?",
                (reference_id,),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def list_for_identity(
        self,
        *,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
    ) -> tuple[CanonicalEvidenceRecord, ...]:
        """List captures for one exact valuation/ledger identity."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_canonical_evidence
                WHERE valuation_snapshot_id = ?
                  AND ledger_cutoff_id = ?
                  AND ledger_fingerprint = ?
                ORDER BY tool_name, reference_id
                """,
                (
                    valuation_snapshot_id,
                    ledger_cutoff_id,
                    ledger_fingerprint,
                ),
            ).fetchall()
        return tuple(_record_from_row(row) for row in rows)


class EvidenceContextBuilder:
    """Build one AI context only from records sharing an exact fact identity."""

    def build(
        self,
        *,
        account_alias: str,
        records: Sequence[CanonicalEvidenceRecord],
        created_at: str,
    ) -> EvidenceBoundContextSnapshot:
        if not records:
            raise ValueError("evidence context requires at least one record")
        reference_ids = [record.reference_id for record in records]
        if len(reference_ids) != len(set(reference_ids)):
            raise EvidenceIdentityMismatch("duplicate evidence reference")
        first = records[0]
        expected = _financial_identity(first)
        for record in records[1:]:
            if _financial_identity(record) != expected:
                raise EvidenceIdentityMismatch(
                    "canonical evidence valuation or ledger identity drift"
                )
        return EvidenceBoundContextSnapshot.create(
            account_alias=account_alias,
            valuation_snapshot_id=first.valuation_snapshot_id,
            ledger_cutoff_id=first.ledger_cutoff_id,
            ledger_fingerprint=first.ledger_fingerprint,
            evidence_references=tuple(
                record.to_reference()
                for record in sorted(records, key=lambda item: item.reference_id)
            ),
            created_at=created_at,
        )


class CanonicalEvidenceToolExecutors:
    """Create read-only tool executors bound to persisted evidence records."""

    def __init__(self, repository: CanonicalEvidenceRepository) -> None:
        self._repository = repository

    def as_mapping(
        self,
    ) -> dict[
        str,
        Callable[[JsonObject, EvidenceBoundContextSnapshot], JsonObject],
    ]:
        return {
            tool_name: self._executor(tool_name)
            for tool_name in CANONICAL_EVIDENCE_KINDS
        }

    def _executor(
        self, tool_name: str
    ) -> Callable[[JsonObject, EvidenceBoundContextSnapshot], JsonObject]:
        def execute(
            arguments: JsonObject,
            context: EvidenceBoundContextSnapshot,
        ) -> JsonObject:
            if set(arguments) != {"evidence_reference_id"}:
                raise EvidenceReadDenied(
                    "canonical evidence reads require only evidence_reference_id"
                )
            reference_id = str(arguments["evidence_reference_id"]).strip()
            if reference_id not in context.evidence_reference_ids:
                raise EvidenceReadDenied("evidence reference is outside context")
            record = self._repository.get(reference_id)
            if record is None:
                raise EvidenceReadDenied("persisted evidence record not found")
            if record.tool_name != tool_name:
                raise EvidenceReadDenied("evidence record belongs to another tool")
            if _financial_identity(record) != (
                context.valuation_snapshot_id,
                context.ledger_cutoff_id,
                context.ledger_fingerprint,
            ):
                raise EvidenceReadDenied("evidence record financial identity drift")
            context_reference = next(
                item
                for item in context.evidence_references
                if item.reference_id == reference_id
            )
            if context_reference != record.to_reference():
                raise EvidenceReadDenied("evidence reference fingerprint drift")
            blockers = (
                []
                if record.authoritative
                else [f"evidence_status_not_complete:{record.status}"]
            )
            return {
                "evidence_reference_id": record.reference_id,
                "persisted_facts_only": True,
                "authoritative": record.authoritative,
                "blocking_reasons": blockers,
                "kind": record.kind,
                "status": record.status,
                "as_of": record.as_of,
                "source_schema_version": record.source_schema_version,
                "valuation_snapshot_id": record.valuation_snapshot_id,
                "ledger_cutoff_id": record.ledger_cutoff_id,
                "ledger_fingerprint": record.ledger_fingerprint,
                "record_fingerprint": record.record_fingerprint,
                "payload": dict(record.payload),
            }

        return execute


def _financial_identity(record: CanonicalEvidenceRecord) -> tuple[str, int, str]:
    return (
        record.valuation_snapshot_id,
        record.ledger_cutoff_id,
        record.ledger_fingerprint,
    )


def _record_identity(
    record: CanonicalEvidenceRecord,
    payload_fingerprint: str,
) -> JsonObject:
    return _record_identity_fields(
        tool_name=record.tool_name,
        kind=record.kind,
        valuation_snapshot_id=record.valuation_snapshot_id,
        ledger_cutoff_id=record.ledger_cutoff_id,
        ledger_fingerprint=record.ledger_fingerprint,
        status=record.status,
        as_of=record.as_of,
        source_schema_version=record.source_schema_version,
        payload_fingerprint=payload_fingerprint,
    )


def _record_identity_fields(
    *,
    tool_name: str,
    kind: str,
    valuation_snapshot_id: str,
    ledger_cutoff_id: int,
    ledger_fingerprint: str,
    status: str,
    as_of: str,
    source_schema_version: str,
    payload_fingerprint: str,
) -> JsonObject:
    return {
        "tool_name": tool_name,
        "kind": kind,
        "valuation_snapshot_id": valuation_snapshot_id,
        "ledger_cutoff_id": ledger_cutoff_id,
        "ledger_fingerprint": ledger_fingerprint,
        "status": status,
        "as_of": as_of,
        "source_schema_version": source_schema_version,
        "payload_fingerprint": payload_fingerprint,
        "persisted_facts_only": True,
    }


def _validate_payload_identity(record: CanonicalEvidenceRecord) -> None:
    """Reject a payload that contradicts its immutable evidence envelope."""
    expected_values: tuple[tuple[str, Any], ...] = (
        ("valuation_snapshot_id", record.valuation_snapshot_id),
        ("ledger_cutoff_id", record.ledger_cutoff_id),
        ("ledger_fingerprint", record.ledger_fingerprint),
    )
    for field_name, expected in expected_values:
        actual = record.payload.get(field_name)
        if actual is not None and actual != expected:
            raise EvidenceIdentityMismatch(
                f"payload {field_name} contradicts evidence envelope"
            )
    if record.payload.get("persisted_facts_only") is False:
        raise EvidenceIdentityMismatch(
            "payload contradicts persisted-facts-only evidence envelope"
        )


def _record_from_row(row: sqlite3.Row) -> CanonicalEvidenceRecord:
    return CanonicalEvidenceRecord(
        reference_id=str(row["reference_id"]),
        tool_name=str(row["tool_name"]),
        kind=str(row["kind"]),
        valuation_snapshot_id=str(row["valuation_snapshot_id"]),
        ledger_cutoff_id=int(row["ledger_cutoff_id"]),
        ledger_fingerprint=str(row["ledger_fingerprint"]),
        status=str(row["status"]),
        as_of=str(row["as_of"]),
        source_schema_version=str(row["source_schema_version"]),
        payload=json.loads(str(row["payload_json"])),
        payload_fingerprint=str(row["payload_fingerprint"]),
        record_fingerprint=str(row["record_fingerprint"]),
        captured_at=str(row["captured_at"]),
        persisted_facts_only=bool(row["persisted_facts_only"]),
    )
