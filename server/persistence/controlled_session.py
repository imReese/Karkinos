"""Aggregate controlled-session repository compatibility boundary."""

from __future__ import annotations

from server.persistence.controlled_session_authority_queries import (
    ControlledSessionAuthorityQueryRepositoryMixin,
)
from server.persistence.controlled_session_budgets import (
    ControlledSessionBudgetRepositoryMixin,
)
from server.persistence.controlled_session_gate_snapshots import (
    ControlledSessionGateSnapshotRepositoryMixin,
)
from server.persistence.controlled_session_issuance_uow import (
    ControlledSessionIssuanceUnitOfWorkMixin,
)
from server.persistence.controlled_session_pause_uow import (
    ControlledSessionPauseUnitOfWorkMixin,
)
from server.persistence.controlled_session_rate_admission_uow import (
    ControlledSessionRateAdmissionUnitOfWorkMixin,
)
from server.persistence.controlled_session_replacement_uow import (
    ControlledSessionReplacementUnitOfWorkMixin,
)
from server.persistence.controlled_session_revocation_uow import (
    ControlledSessionRevocationUnitOfWorkMixin,
)


class ControlledSessionRepository(
    ControlledSessionBudgetRepositoryMixin,
    ControlledSessionIssuanceUnitOfWorkMixin,
    ControlledSessionReplacementUnitOfWorkMixin,
    ControlledSessionRevocationUnitOfWorkMixin,
    ControlledSessionAuthorityQueryRepositoryMixin,
    ControlledSessionGateSnapshotRepositoryMixin,
    ControlledSessionRateAdmissionUnitOfWorkMixin,
    ControlledSessionPauseUnitOfWorkMixin,
):
    """Compose transactionally cohesive controlled-session capabilities."""
