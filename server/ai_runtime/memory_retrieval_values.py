"""Deterministic values for explicit reviewed-memory retrieval."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import ArtifactKind, JsonObject, StoredArtifact, content_fingerprint
from .evidence import EvidenceIdentityMismatch


def exact_memory_artifact(
    *,
    artifacts: Sequence[StoredArtifact],
    memory_artifact_id: str | None,
) -> StoredArtifact:
    matches = [
        artifact
        for artifact in artifacts
        if artifact.kind == ArtifactKind.MEMORY
        and artifact.artifact_id == memory_artifact_id
    ]
    if len(matches) != 1:
        raise EvidenceIdentityMismatch(
            "review must bind exactly one current memory artifact"
        )
    return matches[0]


def reviewed_memory_retrieval_event_hash(
    *,
    retrieval_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "retrieval_id": retrieval_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )
