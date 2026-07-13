"""Provider-neutral adapter protocol and deterministic fixture implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    ArtifactDraft,
    JsonObject,
    ToolExecutionResult,
    ToolRequest,
    content_fingerprint,
)


@dataclass(frozen=True)
class ProviderRequest:
    workflow_id: str
    stage_id: str
    role_id: str
    model_id: str
    context_snapshot_id: str
    context_fingerprint: str
    input_artifact_ids: tuple[str, ...]
    tool_results: tuple[ToolExecutionResult, ...]
    turn_index: int

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "workflow_id": self.workflow_id,
            "stage_id": self.stage_id,
            "role_id": self.role_id,
            "model_id": self.model_id,
            "context_snapshot_id": self.context_snapshot_id,
            "context_fingerprint": self.context_fingerprint,
            "input_artifact_ids": list(self.input_artifact_ids),
            "tool_results": [item.to_dict() for item in self.tool_results],
            "turn_index": self.turn_index,
        }


@dataclass(frozen=True)
class ProviderResponse:
    tool_requests: tuple[ToolRequest, ...] = ()
    artifacts: tuple[ArtifactDraft, ...] = ()
    partial: bool = False
    message: str = ""

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "tool_requests": [item.to_dict() for item in self.tool_requests],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "partial": self.partial,
            "message": self.message,
        }


class ProviderAdapter(Protocol):
    """Adapter protocol. Production adapters are intentionally absent."""

    @property
    def provider_id(self) -> str: ...

    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...


class DeterministicFixtureProvider:
    """A network-free provider whose turns come from immutable local fixtures."""

    def __init__(
        self,
        *,
        provider_id: str,
        responses: dict[str, tuple[ProviderResponse, ...]],
        failures: dict[tuple[str, int], Exception] | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._responses = {key: tuple(value) for key, value in responses.items()}
        self._failures = dict(failures or {})
        self._invocations: list[ProviderRequest] = []

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def invocations(self) -> tuple[ProviderRequest, ...]:
        return tuple(self._invocations)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self._invocations.append(request)
        failure = self._failures.get((request.stage_id, request.turn_index))
        if failure is not None:
            raise failure
        stage_responses = self._responses.get(request.stage_id)
        if stage_responses is None:
            raise LookupError(f"no fixture response for stage {request.stage_id}")
        if request.turn_index >= len(stage_responses):
            raise LookupError(
                f"no fixture response for stage {request.stage_id} "
                f"turn {request.turn_index}"
            )
        return stage_responses[request.turn_index]
