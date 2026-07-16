"""SQLite audit store scoped exclusively to ``ai_*`` tables.

The store may share an application database file, but it has no methods for
OMS, ledger, risk, capital-authority, kill-switch, or broker state.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    AgentRole,
    AgentRun,
    AgentRunStatus,
    ArtifactDraft,
    ArtifactKind,
    EvidenceBoundContextSnapshot,
    EvidenceReference,
    ModelRegistration,
    ProviderRegistration,
    ResearchWorkflow,
    StoredArtifact,
    ToolCall,
    ToolCallStatus,
    WorkflowDefinition,
    WorkflowStatus,
    canonical_json,
    content_fingerprint,
)


class IdempotencyConflict(ValueError):
    """Raised when an idempotency key is reused with different immutable input."""


@dataclass(frozen=True)
class AuditReplayResult:
    workflow_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


_AI_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_provider_registrations (
    provider_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_model_registrations (
    model_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(provider_id) REFERENCES ai_provider_registrations(provider_id)
);

CREATE TABLE IF NOT EXISTS ai_agent_roles (
    role_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_context_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    context_fingerprint TEXT NOT NULL UNIQUE,
    valuation_snapshot_id TEXT NOT NULL,
    ledger_cutoff_id INTEGER NOT NULL CHECK(ledger_cutoff_id >= 0),
    ledger_fingerprint TEXT NOT NULL,
    persisted_facts_only INTEGER NOT NULL CHECK(persisted_facts_only = 1),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_workflows (
    workflow_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    definition_id TEXT NOT NULL,
    definition_fingerprint TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage_index INTEGER NOT NULL DEFAULT 0,
    partial_result INTEGER NOT NULL DEFAULT 0,
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(context_snapshot_id) REFERENCES ai_context_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_workflows_status
ON ai_workflows(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_agent_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    response_json TEXT,
    response_fingerprint TEXT,
    error_code TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(workflow_id, stage_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS ai_tool_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_json TEXT,
    denial_reason TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id, call_id),
    FOREIGN KEY(run_id) REFERENCES ai_agent_runs(run_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS ai_artifacts (
    artifact_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    content_json TEXT NOT NULL,
    evidence_reference_ids_json TEXT NOT NULL,
    artifact_fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES ai_agent_runs(run_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_artifacts_workflow
ON ai_artifacts(workflow_id, artifact_kind, created_at);

CREATE TABLE IF NOT EXISTS ai_workflow_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(workflow_id, sequence_number),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);
"""


class AiAuditStore:
    """Durable append-oriented store for AI research runtime evidence."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(_AI_SCHEMA)

    def _register(
        self,
        *,
        table: str,
        id_column: str,
        identity: str,
        payload: dict[str, Any],
        created_at: str,
        extra_columns: dict[str, Any] | None = None,
    ) -> None:
        payload_json = canonical_json(payload)
        fingerprint = content_fingerprint(payload)
        with self._connection() as conn:
            columns = [id_column, *(extra_columns or {}), "payload_json"]
            columns.extend(["payload_fingerprint", "created_at"])
            values = [identity, *(extra_columns or {}).values(), payload_json]
            values.extend([fingerprint, created_at])
            placeholders = ", ".join("?" for _ in values)
            conn.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT({id_column}) DO NOTHING",
                values,
            )
            existing = conn.execute(
                f"SELECT payload_fingerprint FROM {table} WHERE {id_column} = ?",
                (identity,),
            ).fetchone()
            if existing is None or str(existing["payload_fingerprint"]) != fingerprint:
                raise IdempotencyConflict(f"conflicting registration: {identity}")

    def register_provider(
        self, registration: ProviderRegistration, *, created_at: str | None = None
    ) -> None:
        self._register(
            table="ai_provider_registrations",
            id_column="provider_id",
            identity=registration.provider_id,
            payload=registration.to_dict(),
            created_at=created_at or _utc_now(),
        )

    def register_model(
        self, registration: ModelRegistration, *, created_at: str | None = None
    ) -> None:
        self._register(
            table="ai_model_registrations",
            id_column="model_id",
            identity=registration.model_id,
            payload=registration.to_dict(),
            created_at=created_at or _utc_now(),
            extra_columns={"provider_id": registration.provider_id},
        )

    def register_role(self, role: AgentRole, *, created_at: str | None = None) -> None:
        self._register(
            table="ai_agent_roles",
            id_column="role_id",
            identity=role.role_id,
            payload=role.to_dict(),
            created_at=created_at or _utc_now(),
        )

    def list_providers(self) -> tuple[ProviderRegistration, ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM ai_provider_registrations "
                "ORDER BY provider_id"
            ).fetchall()
        return tuple(_provider_from_json(row["payload_json"]) for row in rows)

    def list_models(self) -> tuple[ModelRegistration, ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM ai_model_registrations ORDER BY model_id"
            ).fetchall()
        return tuple(_model_from_json(row["payload_json"]) for row in rows)

    def list_roles(self) -> tuple[AgentRole, ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM ai_agent_roles ORDER BY role_id"
            ).fetchall()
        return tuple(_role_from_json(row["payload_json"]) for row in rows)

    def save_context(self, context: EvidenceBoundContextSnapshot) -> None:
        payload_json = canonical_json(context.to_dict())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ai_context_snapshots (
                    snapshot_id, context_fingerprint, valuation_snapshot_id,
                    ledger_cutoff_id, ledger_fingerprint,
                    persisted_facts_only, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(snapshot_id) DO NOTHING
                """,
                (
                    context.snapshot_id,
                    context.fingerprint,
                    context.valuation_snapshot_id,
                    context.ledger_cutoff_id,
                    context.ledger_fingerprint,
                    payload_json,
                    context.created_at,
                ),
            )
            existing = conn.execute(
                "SELECT context_fingerprint FROM ai_context_snapshots "
                "WHERE snapshot_id = ?",
                (context.snapshot_id,),
            ).fetchone()
            if (
                existing is None
                or str(existing["context_fingerprint"]) != context.fingerprint
            ):
                raise IdempotencyConflict(
                    f"conflicting context snapshot: {context.snapshot_id}"
                )

    def get_context(self, snapshot_id: str) -> EvidenceBoundContextSnapshot:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM ai_context_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"AI context snapshot not found: {snapshot_id}")
        return _context_from_json(row["payload_json"])

    def create_or_get_workflow(
        self,
        *,
        definition: WorkflowDefinition,
        context: EvidenceBoundContextSnapshot,
        idempotency_key: str,
        created_at: str,
    ) -> tuple[ResearchWorkflow, bool]:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        self.save_context(context)
        workflow_identity = {
            "idempotency_key": idempotency_key,
            "definition_fingerprint": definition.fingerprint,
            "context_fingerprint": context.fingerprint,
        }
        workflow_id = f"ai-workflow-{content_fingerprint(workflow_identity)[:24]}"
        definition_json = canonical_json(definition.to_dict())
        with self._connection() as conn:
            insert = conn.execute(
                """
                INSERT INTO ai_workflows (
                    workflow_id, idempotency_key, definition_id,
                    definition_fingerprint, definition_json,
                    context_snapshot_id, context_fingerprint, status,
                    current_stage_index, partial_result, failure_code,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    workflow_id,
                    idempotency_key,
                    definition.definition_id,
                    definition.fingerprint,
                    definition_json,
                    context.snapshot_id,
                    context.fingerprint,
                    WorkflowStatus.PENDING.value,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_workflows WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if (
                row is None
                or str(row["definition_fingerprint"]) != definition.fingerprint
                or str(row["context_fingerprint"]) != context.fingerprint
            ):
                raise IdempotencyConflict(
                    "workflow idempotency key was reused with different input"
                )
        return _workflow_from_row(row), insert.rowcount == 0

    def get_workflow(self, workflow_id: str) -> ResearchWorkflow:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"AI workflow not found: {workflow_id}")
        return _workflow_from_row(row)

    def update_workflow(
        self,
        workflow_id: str,
        *,
        status: WorkflowStatus,
        current_stage_index: int,
        partial_result: bool,
        failure_code: str | None,
        updated_at: str,
    ) -> ResearchWorkflow:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_workflows
                SET status = ?, current_stage_index = ?, partial_result = ?,
                    failure_code = ?, updated_at = ?
                WHERE workflow_id = ?
                """,
                (
                    status.value,
                    current_stage_index,
                    int(partial_result),
                    failure_code,
                    updated_at,
                    workflow_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"AI workflow not found: {workflow_id}")
            row = conn.execute(
                "SELECT * FROM ai_workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        assert row is not None
        return _workflow_from_row(row)

    def start_agent_run(
        self,
        *,
        run_id: str,
        workflow_id: str,
        stage_id: str,
        role_id: str,
        model_id: str,
        provider_id: str,
        request: dict[str, Any],
        started_at: str,
    ) -> AgentRun:
        request_json = canonical_json(request)
        request_fingerprint = content_fingerprint(request)
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM ai_agent_runs WHERE workflow_id = ? AND stage_id = ?",
                (workflow_id, stage_id),
            ).fetchone()
            if existing is not None:
                if str(existing["request_fingerprint"]) != request_fingerprint:
                    raise IdempotencyConflict(
                        f"agent run input drift for {workflow_id}/{stage_id}"
                    )
                return _agent_run_from_row(existing)
            conn.execute(
                """
                INSERT INTO ai_agent_runs (
                    run_id, workflow_id, stage_id, role_id, model_id,
                    provider_id, status, request_json, request_fingerprint,
                    started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    stage_id,
                    role_id,
                    model_id,
                    provider_id,
                    AgentRunStatus.RUNNING.value,
                    request_json,
                    request_fingerprint,
                    started_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row is not None
        return _agent_run_from_row(row)

    def finish_agent_run(
        self,
        run_id: str,
        *,
        status: AgentRunStatus,
        response: dict[str, Any] | None,
        error_code: str | None,
        finished_at: str,
    ) -> AgentRun:
        response_json = canonical_json(response) if response is not None else None
        response_fingerprint = (
            content_fingerprint(response) if response is not None else None
        )
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_agent_runs
                SET status = ?, response_json = ?, response_fingerprint = ?,
                    error_code = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    response_json,
                    response_fingerprint,
                    error_code,
                    finished_at,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"AI agent run not found: {run_id}")
            row = conn.execute(
                "SELECT * FROM ai_agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row is not None
        return _agent_run_from_row(row)

    def list_agent_runs(self, workflow_id: str) -> tuple[AgentRun, ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_agent_runs WHERE workflow_id = ? "
                "ORDER BY started_at, stage_id",
                (workflow_id,),
            ).fetchall()
        return tuple(_agent_run_from_row(row) for row in rows)

    def record_tool_call(self, call: ToolCall) -> None:
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT status, arguments_json, result_json, denial_reason "
                "FROM ai_tool_calls WHERE call_id = ?",
                (call.call_id,),
            ).fetchone()
            arguments_json = canonical_json(call.arguments)
            result_json = (
                canonical_json(call.result) if call.result is not None else None
            )
            if existing is not None:
                expected = (
                    call.status.value,
                    arguments_json,
                    result_json,
                    call.denial_reason,
                )
                actual = tuple(existing)
                if actual != expected:
                    raise IdempotencyConflict(f"conflicting tool call: {call.call_id}")
                return
            conn.execute(
                """
                INSERT INTO ai_tool_calls (
                    call_id, run_id, workflow_id, stage_id, role_id,
                    tool_name, status, arguments_json, result_json,
                    denial_reason, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call.call_id,
                    call.run_id,
                    call.workflow_id,
                    call.stage_id,
                    call.role_id,
                    call.tool_name,
                    call.status.value,
                    arguments_json,
                    result_json,
                    call.denial_reason,
                    call.created_at,
                    call.completed_at,
                ),
            )

    def list_tool_calls(self, workflow_id: str) -> tuple[ToolCall, ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_tool_calls WHERE workflow_id = ? "
                "ORDER BY created_at, call_id",
                (workflow_id,),
            ).fetchall()
        return tuple(_tool_call_from_row(row) for row in rows)

    def record_artifact(
        self,
        *,
        workflow_id: str,
        run_id: str,
        stage_id: str,
        role_id: str,
        draft: ArtifactDraft,
        created_at: str,
    ) -> StoredArtifact:
        identity = {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "stage_id": stage_id,
            "role_id": role_id,
            **draft.to_dict(),
        }
        fingerprint = content_fingerprint(identity)
        artifact_id = f"ai-artifact-{fingerprint[:24]}"
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM ai_artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ai_artifacts (
                        artifact_id, workflow_id, run_id, stage_id, role_id,
                        artifact_kind, content_json,
                        evidence_reference_ids_json, artifact_fingerprint,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        workflow_id,
                        run_id,
                        stage_id,
                        role_id,
                        draft.kind.value,
                        canonical_json(draft.content),
                        canonical_json(list(draft.evidence_reference_ids)),
                        fingerprint,
                        created_at,
                    ),
                )
                existing = conn.execute(
                    "SELECT * FROM ai_artifacts WHERE artifact_id = ?", (artifact_id,)
                ).fetchone()
        assert existing is not None
        return _artifact_from_row(existing)

    def list_artifacts(self, workflow_id: str) -> tuple[StoredArtifact, ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_artifacts WHERE workflow_id = ? " "ORDER BY rowid",
                (workflow_id,),
            ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def append_event(
        self,
        workflow_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> str:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            last = conn.execute(
                """
                SELECT sequence_number, event_hash
                FROM ai_workflow_events
                WHERE workflow_id = ?
                ORDER BY sequence_number DESC
                LIMIT 1
                """,
                (workflow_id,),
            ).fetchone()
            sequence_number = int(last["sequence_number"]) + 1 if last else 1
            previous_hash = str(last["event_hash"]) if last else "0" * 64
            event_material = {
                "workflow_id": workflow_id,
                "sequence_number": sequence_number,
                "event_type": event_type,
                "payload": payload,
                "previous_hash": previous_hash,
                "created_at": created_at,
            }
            event_hash = content_fingerprint(event_material)
            conn.execute(
                """
                INSERT INTO ai_workflow_events (
                    workflow_id, sequence_number, event_type, payload_json,
                    previous_hash, event_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    sequence_number,
                    event_type,
                    canonical_json(payload),
                    previous_hash,
                    event_hash,
                    created_at,
                ),
            )
        return event_hash

    def list_events(self, workflow_id: str) -> tuple[dict[str, Any], ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_workflow_events WHERE workflow_id = ? "
                "ORDER BY sequence_number",
                (workflow_id,),
            ).fetchall()
        return tuple(
            {
                "sequence_number": int(row["sequence_number"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(row["payload_json"]),
                "previous_hash": str(row["previous_hash"]),
                "event_hash": str(row["event_hash"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        )

    def verify_replay(self, workflow_id: str) -> AuditReplayResult:
        events = self.list_events(workflow_id)
        previous_hash = "0" * 64
        errors: list[str] = []
        for expected_sequence, event in enumerate(events, start=1):
            if event["sequence_number"] != expected_sequence:
                errors.append(f"sequence_gap:{expected_sequence}")
            if event["previous_hash"] != previous_hash:
                errors.append(f"previous_hash_mismatch:{expected_sequence}")
            material = {
                "workflow_id": workflow_id,
                "sequence_number": event["sequence_number"],
                "event_type": event["event_type"],
                "payload": event["payload"],
                "previous_hash": event["previous_hash"],
                "created_at": event["created_at"],
            }
            calculated = content_fingerprint(material)
            if calculated != event["event_hash"]:
                errors.append(f"event_hash_mismatch:{expected_sequence}")
            previous_hash = event["event_hash"]
        return AuditReplayResult(
            workflow_id=workflow_id,
            valid=not errors,
            event_count=len(events),
            last_event_hash=events[-1]["event_hash"] if events else None,
            errors=tuple(errors),
        )


def _provider_from_json(payload_json: str) -> ProviderRegistration:
    payload = json.loads(payload_json)
    return ProviderRegistration(
        provider_id=str(payload["provider_id"]),
        display_name=str(payload["display_name"]),
        adapter_kind=str(payload["adapter_kind"]),
        enabled=bool(payload.get("enabled", False)),
        capabilities=tuple(str(item) for item in payload.get("capabilities", [])),
        config_schema_version=str(payload["config_schema_version"]),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _model_from_json(payload_json: str) -> ModelRegistration:
    payload = json.loads(payload_json)
    context_window = payload.get("context_window")
    return ModelRegistration(
        model_id=str(payload["model_id"]),
        provider_id=str(payload["provider_id"]),
        model_name=str(payload["model_name"]),
        enabled=bool(payload.get("enabled", False)),
        purposes=tuple(str(item) for item in payload.get("purposes", [])),
        context_window=int(context_window) if context_window is not None else None,
        config_schema_version=str(payload["config_schema_version"]),
    )


def _role_from_json(payload_json: str) -> AgentRole:
    payload = json.loads(payload_json)
    return AgentRole(
        role_id=str(payload["role_id"]),
        display_name=str(payload["display_name"]),
        purpose=str(payload["purpose"]),
        allowed_tools=tuple(str(item) for item in payload.get("allowed_tools", [])),
        allowed_artifact_kinds=tuple(
            ArtifactKind(str(item))
            for item in payload.get("allowed_artifact_kinds", [])
        ),
        instructions_version=str(payload["instructions_version"]),
    )


def _context_from_json(payload_json: str) -> EvidenceBoundContextSnapshot:
    payload = json.loads(payload_json)
    return EvidenceBoundContextSnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        account_alias=str(payload["account_alias"]),
        valuation_snapshot_id=str(payload["valuation_snapshot_id"]),
        ledger_cutoff_id=int(payload["ledger_cutoff_id"]),
        ledger_fingerprint=str(payload["ledger_fingerprint"]),
        evidence_references=tuple(
            EvidenceReference(**item) for item in payload["evidence_references"]
        ),
        created_at=str(payload["created_at"]),
        persisted_facts_only=bool(payload["persisted_facts_only"]),
        schema_version=str(payload["schema_version"]),
    )


def _workflow_from_row(row: sqlite3.Row) -> ResearchWorkflow:
    return ResearchWorkflow(
        workflow_id=str(row["workflow_id"]),
        idempotency_key=str(row["idempotency_key"]),
        definition=WorkflowDefinition.from_dict(json.loads(row["definition_json"])),
        context_snapshot_id=str(row["context_snapshot_id"]),
        context_fingerprint=str(row["context_fingerprint"]),
        status=WorkflowStatus(str(row["status"])),
        current_stage_index=int(row["current_stage_index"]),
        partial_result=bool(row["partial_result"]),
        failure_code=str(row["failure_code"]) if row["failure_code"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _agent_run_from_row(row: sqlite3.Row) -> AgentRun:
    return AgentRun(
        run_id=str(row["run_id"]),
        workflow_id=str(row["workflow_id"]),
        stage_id=str(row["stage_id"]),
        role_id=str(row["role_id"]),
        model_id=str(row["model_id"]),
        provider_id=str(row["provider_id"]),
        status=AgentRunStatus(str(row["status"])),
        request_fingerprint=str(row["request_fingerprint"]),
        response_fingerprint=(
            str(row["response_fingerprint"]) if row["response_fingerprint"] else None
        ),
        error_code=str(row["error_code"]) if row["error_code"] else None,
        started_at=str(row["started_at"]),
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
    )


def _tool_call_from_row(row: sqlite3.Row) -> ToolCall:
    return ToolCall(
        call_id=str(row["call_id"]),
        run_id=str(row["run_id"]),
        workflow_id=str(row["workflow_id"]),
        stage_id=str(row["stage_id"]),
        role_id=str(row["role_id"]),
        tool_name=str(row["tool_name"]),
        status=ToolCallStatus(str(row["status"])),
        arguments=json.loads(row["arguments_json"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        denial_reason=(str(row["denial_reason"]) if row["denial_reason"] else None),
        created_at=str(row["created_at"]),
        completed_at=(str(row["completed_at"]) if row["completed_at"] else None),
    )


def _artifact_from_row(row: sqlite3.Row) -> StoredArtifact:
    return StoredArtifact(
        artifact_id=str(row["artifact_id"]),
        workflow_id=str(row["workflow_id"]),
        run_id=str(row["run_id"]),
        stage_id=str(row["stage_id"]),
        role_id=str(row["role_id"]),
        kind=ArtifactKind(str(row["artifact_kind"])),
        content=json.loads(row["content_json"]),
        evidence_reference_ids=tuple(
            str(item) for item in json.loads(row["evidence_reference_ids_json"])
        ),
        fingerprint=str(row["artifact_fingerprint"]),
        created_at=str(row["created_at"]),
    )
