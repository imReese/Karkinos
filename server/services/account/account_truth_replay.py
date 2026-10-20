"""Privacy-minimized replay evidence for one historical Account Truth binding.

Backward-compatible facade for server.services.account.replay.
"""

from __future__ import annotations

from server.services.account.replay import (
    ACCOUNT_TRUTH_REPLAY_EVIDENCE_SCHEMA_VERSION,
    account_truth_replay_evidence_fingerprint,
    build_account_truth_replay_evidence,
    verify_account_truth_replay_evidence,
)

__all__ = [
    "ACCOUNT_TRUTH_REPLAY_EVIDENCE_SCHEMA_VERSION",
    "account_truth_replay_evidence_fingerprint",
    "build_account_truth_replay_evidence",
    "verify_account_truth_replay_evidence",
]
