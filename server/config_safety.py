"""Canonical recursive screening for sensitive local configuration keys."""

from __future__ import annotations

SENSITIVE_CONFIG_KEY_PARTS = ("password", "secret", "token", "credential")


def contains_sensitive_config_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in SENSITIVE_CONFIG_KEY_PARTS)
            or contains_sensitive_config_key(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(contains_sensitive_config_key(item) for item in value)
    return False


__all__ = ["contains_sensitive_config_key"]
