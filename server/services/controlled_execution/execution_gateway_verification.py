"""Short-lived, non-submitting runtime verification for execution gateways.

Backward-compatible facade for server.services.controlled_execution.gateway.
"""

from __future__ import annotations

from server.services.controlled_execution.gateway import (
    EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS,
    EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
    EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
    EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
    EXECUTION_GATEWAY_VERIFICATION_MAX_AGE_SECONDS,
    EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION,
    EXECUTION_GATEWAY_VERIFICATION_STATUS_SCHEMA_VERSION,
    ExecutionGatewayRuntimeProtocol,
    ExecutionGatewayVerificationRejected,
    ExecutionGatewayVerificationService,
)

__all__ = [
    "EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS",
    "EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT",
    "EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE",
    "EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE",
    "EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE",
    "EXECUTION_GATEWAY_VERIFICATION_MAX_AGE_SECONDS",
    "EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION",
    "EXECUTION_GATEWAY_VERIFICATION_STATUS_SCHEMA_VERSION",
    "ExecutionGatewayRuntimeProtocol",
    "ExecutionGatewayVerificationRejected",
    "ExecutionGatewayVerificationService",
]
