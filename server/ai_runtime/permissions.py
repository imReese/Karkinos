"""Fail-closed permission registry for AI research tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .contracts import AgentRole, EvidenceBoundContextSnapshot


class ToolEffect(StrEnum):
    READ_PERSISTED = "read_persisted"
    PURE_COMPUTE = "pure_compute"


@dataclass(frozen=True)
class ToolPermission:
    tool_name: str
    effect: ToolEffect
    requires_evidence_context: bool
    description: str


@dataclass(frozen=True)
class ToolAuthorization:
    allowed: bool
    reason: str
    permission: ToolPermission | None


class ToolAccessDenied(PermissionError):
    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(f"tool {tool_name} denied: {reason}")
        self.tool_name = tool_name
        self.reason = reason


_FORBIDDEN_PREFIXES = (
    "oms.",
    "ledger.",
    "risk.decision.",
    "kill_switch.",
    "capital_authority.",
    "broker.",
    "provider.",
)


class ToolPermissionRegistry:
    """Allow only explicitly registered read-only or pure tools."""

    def __init__(self, permissions: tuple[ToolPermission, ...] = ()) -> None:
        self._permissions: dict[str, ToolPermission] = {}
        for permission in permissions:
            self.register(permission)

    def register(self, permission: ToolPermission) -> None:
        if permission.tool_name.startswith(_FORBIDDEN_PREFIXES):
            raise ValueError(
                f"forbidden authority namespace cannot be registered: "
                f"{permission.tool_name}"
            )
        existing = self._permissions.get(permission.tool_name)
        if existing is not None and existing != permission:
            raise ValueError(f"conflicting tool permission: {permission.tool_name}")
        self._permissions[permission.tool_name] = permission

    def authorize(
        self,
        *,
        role: AgentRole,
        tool_name: str,
        context: EvidenceBoundContextSnapshot,
    ) -> ToolAuthorization:
        if tool_name.startswith(_FORBIDDEN_PREFIXES):
            return ToolAuthorization(False, "authority_namespace_forbidden", None)
        permission = self._permissions.get(tool_name)
        if permission is None:
            return ToolAuthorization(False, "tool_not_registered", None)
        if tool_name not in role.allowed_tools:
            return ToolAuthorization(False, "role_not_allowed", permission)
        if permission.effect not in {
            ToolEffect.READ_PERSISTED,
            ToolEffect.PURE_COMPUTE,
        }:
            return ToolAuthorization(False, "tool_effect_not_read_only", permission)
        if permission.requires_evidence_context and not context.persisted_facts_only:
            return ToolAuthorization(False, "context_not_persisted_facts", permission)
        return ToolAuthorization(True, "allowed", permission)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._permissions))


def default_tool_permission_registry() -> ToolPermissionRegistry:
    """Return the phase-one canonical read boundary; no adapters are attached."""
    return ToolPermissionRegistry(
        permissions=(
            ToolPermission(
                "portfolio_projection.read",
                ToolEffect.READ_PERSISTED,
                True,
                "Read a persisted canonical portfolio projection by evidence id.",
            ),
            ToolPermission(
                "account_state_projection.read",
                ToolEffect.READ_PERSISTED,
                True,
                "Read the canonical account-state projection bound to the context.",
            ),
            ToolPermission(
                "operations_summary.read",
                ToolEffect.READ_PERSISTED,
                True,
                "Read a persisted Operations summary without running automation.",
            ),
            ToolPermission(
                "research_evidence.read",
                ToolEffect.READ_PERSISTED,
                True,
                "Read a persisted research evidence bundle.",
            ),
            ToolPermission(
                "account_truth.read",
                ToolEffect.READ_PERSISTED,
                True,
                "Read staged and reconciled account-truth evidence.",
            ),
            ToolPermission(
                "paper_shadow_evidence.read",
                ToolEffect.READ_PERSISTED,
                True,
                "Read persisted paper/shadow evidence without starting a run.",
            ),
            ToolPermission(
                "calculator.evaluate",
                ToolEffect.PURE_COMPUTE,
                False,
                "Run deterministic arithmetic with no I/O or authority effect.",
            ),
        )
    )
