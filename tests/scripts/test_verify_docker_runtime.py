from __future__ import annotations

import pytest

from scripts.ci.verify_docker_runtime import _assert_fail_closed_defaults


def _safe_statuses() -> dict:
    return {
        "settings": {},
        "live_status": {"running": True},
        "automatic_trading": {
            "enabled": False,
            "configured_enabled": False,
            "status": "disabled",
        },
        "capital_authority": {
            "runtime_authority_status": "disabled",
            "execution_authority_enabled": False,
            "broker_submission_enabled": False,
        },
        "controlled_bridge": {
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "live_gateway_implemented": False,
        },
        "controlled_submission": {
            "default_broker_submission_enabled": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "recovery_resubmission_enabled": False,
            "registered_gateway_ids": [],
        },
    }


def test_docker_runtime_smoke_accepts_always_on_scheduler_and_fail_closed_authority() -> (
    None
):
    _assert_fail_closed_defaults(_safe_statuses())


@pytest.mark.parametrize(
    ("section", "field", "unsafe_value"),
    [
        ("live_status", "running", False),
        ("automatic_trading", "enabled", True),
        ("capital_authority", "runtime_authority_status", "enabled"),
        ("controlled_bridge", "broker_submission_enabled", True),
        ("controlled_submission", "automatic_submission_enabled", True),
        ("controlled_submission", "registered_gateway_ids", ["production"]),
    ],
)
def test_docker_runtime_smoke_rejects_stopped_scheduler_or_authority_enablement(
    section: str,
    field: str,
    unsafe_value: object,
) -> None:
    statuses = _safe_statuses()
    statuses[section][field] = unsafe_value

    with pytest.raises(AssertionError, match="runtime invariants failed"):
        _assert_fail_closed_defaults(statuses)
