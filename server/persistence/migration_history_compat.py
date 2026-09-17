"""Narrow compatibility helpers for exact known migration-history variants."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeVar


class MigrationIdentity(Protocol):
    version: int
    name: str

    @property
    def checksum(self) -> str: ...


MigrationT = TypeVar("MigrationT", bound=MigrationIdentity)
AppliedHistory = dict[int, tuple[str, str]]


def normalize_known_history(
    applied: AppliedHistory,
    migrations: Sequence[MigrationT],
    legacy_variants: Mapping[int, MigrationT],
) -> AppliedHistory:
    """Map exact known legacy identities to canonical identities for validation."""

    normalized = dict(applied)
    registered = {migration.version: migration for migration in migrations}
    for version, legacy in legacy_variants.items():
        if applied.get(version) == (legacy.name, legacy.checksum):
            canonical = registered[version]
            normalized[version] = (canonical.name, canonical.checksum)
    return normalized


def migrations_for_applied_history(
    applied: AppliedHistory,
    migrations: Sequence[MigrationT],
    legacy_variants: Mapping[int, MigrationT],
) -> tuple[MigrationT, ...]:
    """Use exact legacy definitions only while verifying their persisted schema."""

    replacements = {
        version: legacy
        for version, legacy in legacy_variants.items()
        if applied.get(version) == (legacy.name, legacy.checksum)
    }
    return tuple(replacements.get(item.version, item) for item in migrations)
