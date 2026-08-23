"""Shared non-secret runtime configuration constraints."""

from notification.contracts import SUPPORTED_NOTIFICATION_TYPES

SUPPORTED_DATA_SOURCES = frozenset({"akshare", "tushare"})
MIN_LIVE_POLL_INTERVAL_SECONDS = 15
