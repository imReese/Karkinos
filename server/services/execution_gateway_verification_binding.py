"""Shared exact binding for current non-submitting gateway verification.

Backward-compatible facade for server.services.controlled_execution.gateway.
"""

from __future__ import annotations

from server.services.controlled_execution.gateway import (
    EXECUTION_GATEWAY_VERIFICATION_BINDING_SCHEMA_VERSION,
    build_execution_gateway_order_contract,
    resolve_execution_gateway_verification_binding,
)

__all__ = [
    "EXECUTION_GATEWAY_VERIFICATION_BINDING_SCHEMA_VERSION",
    "build_execution_gateway_order_contract",
    "resolve_execution_gateway_verification_binding",
]
