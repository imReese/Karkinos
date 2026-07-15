"""Shared non-secret runtime configuration constraints."""

SUPPORTED_DATA_SOURCES = frozenset({"akshare", "tushare"})
SUPPORTED_NOTIFICATION_TYPES = frozenset({"console", "telegram", "wechat"})
MIN_LIVE_POLL_INTERVAL_SECONDS = 15
