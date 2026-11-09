"""Shared Dataset admission policy for research consumers.

Kept free of research-service imports so both the Dataset publisher and the
observation readers can validate a snapshot without importing each other.
"""

from __future__ import annotations

from data.dataset.model import DailyBarDatasetSnapshot
from data.dataset.resolver import DailyBarDatasetResolverPolicy
from data.market.quality import RESEARCH_STRICT_DAILY
from server.services.market.verified_daily_market_data import (
    is_verified_daily_resolver_policy,
)

LEGACY_TDX_RESOLVER_POLICY = DailyBarDatasetResolverPolicy(
    policy_id="karkinos.dataset.pit.strict.v1",
    provider_priority=("tdx",),
    required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
)
EXPLICIT_VERIFIED_SOURCE_UNION_POLICY_ID = (
    "karkinos.dataset.explicit_verified_source_union.v1"
)


class ResearchDatasetError(RuntimeError):
    """只包含可公开的错误码，不携带 SDK 自由文本或凭据。"""


def require_supported_snapshot(snapshot: DailyBarDatasetSnapshot) -> None:
    """Admit known replay policies; the strict Reader verifies their evidence."""

    legacy_tdx = (
        snapshot.resolver_policy_id == LEGACY_TDX_RESOLVER_POLICY.policy_id
        and all(partition.provider == "tdx" for partition in snapshot.partitions)
    )
    verified_bars = snapshot.verification_bound and is_verified_daily_resolver_policy(
        snapshot.resolver_policy_id
    )
    verified_union = (
        snapshot.resolver_policy_id == EXPLICIT_VERIFIED_SOURCE_UNION_POLICY_ID
        and snapshot.verification_bound
        and bool(snapshot.session_memberships)
        and all(item.source_observation_ids for item in snapshot.session_memberships)
        and all(partition.instruments for partition in snapshot.partitions)
    )
    if not legacy_tdx and not verified_bars and not verified_union:
        raise ResearchDatasetError("dataset_provider_or_policy_unsupported")


__all__ = [
    "EXPLICIT_VERIFIED_SOURCE_UNION_POLICY_ID",
    "LEGACY_TDX_RESOLVER_POLICY",
    "ResearchDatasetError",
    "require_supported_snapshot",
]
