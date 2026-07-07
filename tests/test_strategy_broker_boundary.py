from __future__ import annotations

from pathlib import Path

from analytics.strategy_broker_boundary import (
    find_strategy_broker_boundary_violations,
)


def test_strategy_broker_boundary_scanner_allows_current_strategy_tree() -> None:
    assert find_strategy_broker_boundary_violations(Path(".")) == ()


def test_strategy_broker_boundary_scanner_detects_forbidden_imports_and_calls(
    tmp_path: Path,
) -> None:
    strategy_file = tmp_path / "strategy" / "rogue.py"
    strategy_file.parent.mkdir()
    strategy_file.write_text(
        "\n".join(
            (
                "from server.services.broker_gateway import BrokerGatewayService",
                "",
                "class RogueStrategy:",
                "    def on_bar(self, context):",
                "        context.broker.submit_order({'symbol': '000001.SZ'})",
            )
        )
    )

    violations = find_strategy_broker_boundary_violations(tmp_path)

    assert {(item.violation_type, item.detail) for item in violations} == {
        (
            "forbidden_import",
            "server.services.broker_gateway",
        ),
        ("forbidden_call", "submit_order"),
    }
    assert {item.path for item in violations} == {"strategy/rogue.py"}
