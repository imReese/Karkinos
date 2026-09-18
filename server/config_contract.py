"""Shared non-secret runtime configuration constraints."""

from notification.contracts import SUPPORTED_NOTIFICATION_TYPES

LEGACY_DATA_SOURCE_PROVIDERS = frozenset({"akshare", "tushare"})
# Compatibility alias for HTTP models/tests while settings migrate to policy.
SUPPORTED_DATA_SOURCES = LEGACY_DATA_SOURCE_PROVIDERS
DEFAULT_MARKET_SOURCE_POLICY = "karkinos.market.source.cn_research.v1"
MIN_LIVE_POLL_INTERVAL_SECONDS = 15
