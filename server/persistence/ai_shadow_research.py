"""Persistence facade for AI shadow research evidence."""

from __future__ import annotations

from pathlib import Path

from server.persistence.ai_shadow_research_call_extensions import (
    ShadowResearchCallExtensionRepositoryMixin,
)
from server.persistence.ai_shadow_research_candidates import (
    ShadowResearchCandidateRepositoryMixin,
)
from server.persistence.ai_shadow_research_citation_resume import (
    ShadowResearchCitationResumeRepositoryMixin,
)
from server.persistence.ai_shadow_research_partial_resume import (
    ShadowResearchPartialResumeRepositoryMixin,
)
from server.persistence.ai_shadow_research_provider_calls import (
    ShadowResearchProviderCallRepositoryMixin,
)
from server.persistence.ai_shadow_research_retry_authorizations import (
    ShadowResearchRetryAuthorizationRepositoryMixin,
)
from server.persistence.ai_shadow_research_run_claims import (
    ShadowResearchRunClaimRepositoryMixin,
)
from server.persistence.ai_shadow_research_run_replacements import (
    ShadowResearchRunReplacementRepositoryMixin,
)
from server.persistence.ai_shadow_research_runs import ShadowResearchRunRepositoryMixin
from server.persistence.ai_shadow_research_schema import (
    ShadowResearchSchemaRepositoryMixin,
)
from server.persistence.ai_shadow_research_uow import ShadowResearchUnitOfWork


class ShadowResearchStore(
    ShadowResearchSchemaRepositoryMixin,
    ShadowResearchRunClaimRepositoryMixin,
    ShadowResearchRunReplacementRepositoryMixin,
    ShadowResearchRetryAuthorizationRepositoryMixin,
    ShadowResearchCallExtensionRepositoryMixin,
    ShadowResearchCitationResumeRepositoryMixin,
    ShadowResearchPartialResumeRepositoryMixin,
    ShadowResearchProviderCallRepositoryMixin,
    ShadowResearchRunRepositoryMixin,
    ShadowResearchCandidateRepositoryMixin,
):
    """Atomic run, provider budget, candidate, and promotion audit storage."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._uow = ShadowResearchUnitOfWork(self._path)

    def _connect(self, *, immediate: bool = False):
        return self._uow.write() if immediate else self._uow.connect()

    def _connect_readonly(self):
        return self._uow.read()
