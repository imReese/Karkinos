"""Public projection API for the append-only legacy fund duplicate correction.

The repair is deliberately narrower than a general ledger deduplicator.  It
only compensates an exact ``manual`` fund-buy row that is paired one-to-one
with its migration-created ``portfolio_trade`` canonical owner.
"""

from server.projections.legacy_fund_trade_duplicate_contract import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE,
    LegacyFundTradeDuplicateCorrectionError,
    LegacyFundTradeDuplicateExclusionResolution,
)
from server.projections.legacy_fund_trade_duplicate_evidence import (
    legacy_fund_trade_duplicate_group_fingerprint,
    legacy_fund_trade_duplicate_repair_fingerprint,
    legacy_fund_trade_economic_identity,
    legacy_fund_trade_ledger_row_fingerprint,
)
from server.projections.legacy_fund_trade_duplicate_resolution import (
    build_legacy_fund_trade_duplicate_correction_plan,
    legacy_fund_trade_duplicate_source_ref,
    resolve_legacy_fund_trade_duplicate_exclusions,
)

__all__ = [
    "LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE",
    "LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION",
    "LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE",
    "LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE",
    "LegacyFundTradeDuplicateCorrectionError",
    "LegacyFundTradeDuplicateExclusionResolution",
    "build_legacy_fund_trade_duplicate_correction_plan",
    "legacy_fund_trade_duplicate_group_fingerprint",
    "legacy_fund_trade_duplicate_repair_fingerprint",
    "legacy_fund_trade_duplicate_source_ref",
    "legacy_fund_trade_economic_identity",
    "legacy_fund_trade_ledger_row_fingerprint",
    "resolve_legacy_fund_trade_duplicate_exclusions",
]
