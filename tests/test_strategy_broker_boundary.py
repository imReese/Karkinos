from __future__ import annotations

from pathlib import Path

from analytics.strategy_broker_boundary import (
    DEFAULT_PROTECTED_PATHS,
    RUNTIME_SESSION_AUTHORITY_PROTECTED_PATHS,
    find_runtime_session_broker_boundary_violations,
    find_strategy_broker_boundary_violations,
)


def test_broker_boundary_scanner_covers_current_protected_investment_trees() -> None:
    assert DEFAULT_PROTECTED_PATHS == (
        "strategy",
        "risk",
        "server/ai_runtime",
        "server/routes/decision.py",
        "server/routes/ai_*.py",
        "server/routes/strategy_*.py",
        "server/services/strategy_*.py",
        "analytics/research_*.py",
        "analytics/strategy_*.py",
        "server/routes/capital_authorization.py",
        "server/routes/capital_scaling_*.py",
        "server/services/capital_authorization*.py",
        "server/services/capital_scaling_*.py",
    )
    assert find_strategy_broker_boundary_violations(Path(".")) == ()
    assert RUNTIME_SESSION_AUTHORITY_PROTECTED_PATHS == (
        "server/services/controlled_session_*.py",
    )
    assert find_runtime_session_broker_boundary_violations(Path(".")) == ()


def test_broker_boundary_scanner_detects_each_protected_domain(
    tmp_path: Path,
) -> None:
    sources = {
        "strategy/rogue.py": "from execution.gateway import ManualConfirmGateway\n",
        "risk/rogue.py": "def check(context):\n    context.broker.submit_order({})\n",
        "server/ai_runtime/rogue.py": (
            "from account_truth.broker_connector import ReadOnlyBrokerConnector\n"
        ),
        "server/routes/decision.py": "def decide(gateway):\n    gateway.submit({})\n",
        "server/routes/ai_research.py": (
            "from server.services.broker_gateway import BrokerGatewayService\n"
        ),
        "server/routes/strategy_promotion.py": (
            "def promote(gateway):\n    gateway.submit_order({})\n"
        ),
        "server/services/strategy_promotion_pipeline.py": (
            "from server.services.controlled_broker_submission import submit\n"
        ),
        "analytics/research_evidence.py": (
            "from server.routes.broker_gateway import router\n"
        ),
        "analytics/strategy_promotion_readiness.py": (
            "def evaluate(connector):\n    connector.query_order('unsafe')\n"
        ),
        "server/routes/capital_authorization.py": (
            "from server.services.broker_gateway import BrokerGatewayService\n"
        ),
        "server/routes/capital_scaling_review.py": (
            "def review(gateway):\n    gateway.submit_order({})\n"
        ),
        "server/services/capital_authorization_audit.py": (
            "from server.services.controlled_broker_submission import submit\n"
        ),
        "server/services/capital_scaling_review.py": (
            "def evaluate(connector):\n    connector.query_order('unsafe')\n"
        ),
    }
    for relative_path, source in sources.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    execution_boundary = tmp_path / "server/services/controlled_broker_submission.py"
    execution_boundary.write_text(
        "from execution.gateway import BrokerExecutionGateway\n"
    )

    violations = find_strategy_broker_boundary_violations(tmp_path)

    assert {(item.violation_type, item.detail) for item in violations} == {
        ("forbidden_import", "account_truth.broker_connector"),
        ("forbidden_import", "execution"),
        ("forbidden_import", "server.routes.broker_gateway"),
        ("forbidden_import", "server.services.broker_gateway"),
        ("forbidden_import", "server.services.controlled_broker_submission"),
        ("forbidden_call", "query_order"),
        ("forbidden_call", "submit"),
        ("forbidden_call", "submit_order"),
    }
    assert {item.path for item in violations} == set(sources)
    assert all(
        item.path != "server/services/controlled_broker_submission.py"
        for item in violations
    )


def test_explicit_scan_paths_remain_supported_for_extensions(tmp_path: Path) -> None:
    extension = tmp_path / "custom" / "extension.py"
    extension.parent.mkdir(parents=True)
    extension.write_text(
        "from server.services.broker_gateway import BrokerGatewayService\n"
    )

    violations = find_strategy_broker_boundary_violations(
        tmp_path,
        paths=("custom/*.py",),
    )

    assert [(item.path, item.detail) for item in violations] == [
        ("custom/extension.py", "server.services.broker_gateway")
    ]


def test_runtime_session_guard_allows_peer_evidence_dependencies_but_not_broker_edge(
    tmp_path: Path,
) -> None:
    session_service = (
        tmp_path / "server/services/controlled_session_runtime_authority.py"
    )
    session_service.parent.mkdir(parents=True)
    session_service.write_text(
        "from server.services.controlled_broker_submission import submit\n"
        "def bypass(gateway):\n    gateway.submit_order({})\n"
    )
    peer_service = tmp_path / "server/services/controlled_session_live_gates.py"
    peer_service.write_text(
        "from server.services.controlled_session_runtime_authority import "
        "ControlledSessionRuntimeAuthorityService\n"
    )
    execution_boundary = tmp_path / "server/services/controlled_broker_submission.py"
    execution_boundary.write_text(
        "from execution.gateway import BrokerExecutionGateway\n"
    )

    violations = find_runtime_session_broker_boundary_violations(tmp_path)

    assert [(item.path, item.violation_type, item.detail) for item in violations] == [
        (
            "server/services/controlled_session_runtime_authority.py",
            "forbidden_import",
            "server.services.controlled_broker_submission",
        ),
        (
            "server/services/controlled_session_runtime_authority.py",
            "forbidden_call",
            "submit_order",
        ),
    ]
