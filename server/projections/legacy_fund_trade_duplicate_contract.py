"""Dependency-neutral contract for the legacy fund duplicate correction."""

from __future__ import annotations

from dataclasses import dataclass

LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE = (
    "legacy_fund_trade_duplicate_projection_correction"
)
LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE = "legacy_fund_trade_duplicate_repair"
LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION = (
    "karkinos.legacy_fund_trade_duplicate_correction_plan.v1"
)
LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE = "manual"


class LegacyFundTradeDuplicateCorrectionError(ValueError):
    """Raised when correction evidence is incomplete, ambiguous, or drifted."""

    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


@dataclass(frozen=True, slots=True)
class LegacyFundTradeDuplicateExclusionResolution:
    """Validated original rows that a trade-component reader may exclude."""

    excluded_manual_entry_ids: frozenset[int]
    correction_entry_ids: tuple[int, ...]
    repair_fingerprints: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.blockers


def legacy_fund_trade_duplicate_error(
    suffix: str,
) -> LegacyFundTradeDuplicateCorrectionError:
    return LegacyFundTradeDuplicateCorrectionError(
        f"legacy_fund_trade_duplicate_{suffix}"
    )


__all__ = [
    "LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE",
    "LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION",
    "LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE",
    "LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE",
    "LegacyFundTradeDuplicateCorrectionError",
    "LegacyFundTradeDuplicateExclusionResolution",
]
