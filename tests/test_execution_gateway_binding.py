from server.services.execution_gateway_binding import build_execution_gateway_binding


def test_declared_execution_gateway_remains_runtime_unverified() -> None:
    binding, blockers = build_execution_gateway_binding(
        gateway_id="qmt-execution-1",
        health_status="healthy",
        can_submit_orders=True,
        account_binding_status="verified",
    )

    assert blockers == ["execution_gateway_runtime_not_verified"]
    assert binding["gateway_id"] == "qmt-execution-1"
    assert binding["declared_can_submit_orders"] is True
    assert binding["runtime_verification_status"] == "unverified"
    assert binding["broker_contacted"] is False
    assert binding["broker_submission_enabled"] is False
    assert binding["authorizes_execution"] is False


def test_execution_gateway_binding_fails_closed_for_missing_or_unbound_facts() -> None:
    binding, blockers = build_execution_gateway_binding(
        gateway_id="",
        health_status="degraded",
        can_submit_orders=False,
        account_binding_status="unverified",
    )

    assert blockers == [
        "execution_gateway_id_missing",
        "execution_gateway_not_healthy",
        "execution_gateway_submit_capability_unavailable",
        "connector_account_binding_not_verified",
        "execution_gateway_runtime_not_verified",
    ]
    assert binding["broker_submission_enabled"] is False
