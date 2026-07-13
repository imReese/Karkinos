"""Provider, model, and agent-role registration independent of adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import AgentRole, ModelRegistration, ProviderRegistration

if TYPE_CHECKING:
    from .store import AiAuditStore


class AiRuntimeRegistry:
    """Fail-closed registry for runtime identities and role capabilities."""

    def __init__(self, store: AiAuditStore | None = None) -> None:
        self._store = store
        self._providers: dict[str, ProviderRegistration] = {}
        self._models: dict[str, ModelRegistration] = {}
        self._roles: dict[str, AgentRole] = {}
        if store is not None:
            self.reload()

    def reload(self) -> None:
        if self._store is None:
            return
        self._providers = {
            item.provider_id: item for item in self._store.list_providers()
        }
        self._models = {item.model_id: item for item in self._store.list_models()}
        self._roles = {item.role_id: item for item in self._store.list_roles()}

    def register_provider(self, registration: ProviderRegistration) -> None:
        existing = self._providers.get(registration.provider_id)
        if existing is not None and existing != registration:
            raise ValueError(f"conflicting provider id: {registration.provider_id}")
        if self._store is not None:
            self._store.register_provider(registration)
        self._providers[registration.provider_id] = registration

    def register_model(self, registration: ModelRegistration) -> None:
        provider = self._providers.get(registration.provider_id)
        if provider is None:
            raise ValueError(f"unknown provider: {registration.provider_id}")
        existing = self._models.get(registration.model_id)
        if existing is not None and existing != registration:
            raise ValueError(f"conflicting model id: {registration.model_id}")
        if self._store is not None:
            self._store.register_model(registration)
        self._models[registration.model_id] = registration

    def register_role(self, role: AgentRole) -> None:
        existing = self._roles.get(role.role_id)
        if existing is not None and existing != role:
            raise ValueError(f"conflicting role id: {role.role_id}")
        if self._store is not None:
            self._store.register_role(role)
        self._roles[role.role_id] = role

    def require_provider(self, provider_id: str) -> ProviderRegistration:
        registration = self._providers.get(provider_id)
        if registration is None:
            raise LookupError(f"provider is not registered: {provider_id}")
        if not registration.enabled:
            raise PermissionError(f"provider is disabled: {provider_id}")
        return registration

    def require_model(self, model_id: str) -> ModelRegistration:
        registration = self._models.get(model_id)
        if registration is None:
            raise LookupError(f"model is not registered: {model_id}")
        if not registration.enabled:
            raise PermissionError(f"model is disabled: {model_id}")
        self.require_provider(registration.provider_id)
        return registration

    def require_role(self, role_id: str) -> AgentRole:
        role = self._roles.get(role_id)
        if role is None:
            raise LookupError(f"agent role is not registered: {role_id}")
        return role
