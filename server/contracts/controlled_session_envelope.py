"""Stable contracts for non-executing controlled-session envelopes."""

from __future__ import annotations

CONTROLLED_SESSION_ENVELOPE_SCHEMA_VERSION = "karkinos.controlled_session_envelope.v5"
CONTROLLED_SESSION_STATUS_SCHEMA_VERSION = "karkinos.controlled_session_status.v5"
CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION = (
    "karkinos.controlled_session_attestation.v6"
)
CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE = "controlled_session.envelope_attested"
CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE = "controlled_session_attestation"
CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE = "controlled_session_envelope"
CONTROLLED_SESSION_ACKNOWLEDGEMENT = (
    "approve_exact_non_executing_session_envelope_for_review"
)
CONTROLLED_SESSION_MAX_DURATION_SECONDS = 30 * 60
CONTROLLED_SESSION_MAX_ORDER_COUNT = 50
CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS = 900
