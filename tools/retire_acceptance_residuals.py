"""One-shot migration removing residual milestone acceptance-audit contracts."""

from __future__ import annotations

import re
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str = "") -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{path}: expected one regex match, got {count}: {pattern!r}")
    write(path, updated)


def remove_exact(path: str, fragment: str, *, expected_count: int = 1) -> None:
    text = read(path)
    count = text.count(fragment)
    if count != expected_count:
        raise SystemExit(
            f"{path}: expected {expected_count} exact fragment(s), got {count}: {fragment!r}"
        )
    write(path, text.replace(fragment, ""))


def main() -> int:
    regex_once(
        "tests/test_server_routes.py",
        r"\ndef test_acceptance_audit_route_returns_single_instrument_loop_manifest\(\):\n.*?(?=\ndef test_app_registers_execution_reconciliation_route\(\):)",
        "\n\ndef test_app_does_not_register_retired_acceptance_audit_route():\n"
        "    from server.app import create_app\n\n"
        "    app = create_app({\"live_auto_start\": False})\n\n"
        "    assert all(\n"
        "        not (\n"
        "            isinstance(route, APIRoute)\n"
        "            and route.path.startswith(\"/api/acceptance-audits\")\n"
        "        )\n"
        "        for route in registered_app_routes(app)\n"
        "    )\n\n",
    )
    regex_once(
        "tests/test_operations_today.py",
        r"\ndef test_operations_today_acceptance_audit_subsystem_uses_audit_export\(\) -> None:\n.*?(?=\ndef test_operations_today_surfaces_broker_adapter_evidence_without_activation\(\) -> None:)",
        "\n\ndef test_operations_today_excludes_retired_acceptance_audit_subsystem() -> None:\n"
        "    summary = build_operations_today_summary(\n"
        "        decision_payload=_decision(),\n"
        "        trading_plan={\n"
        "            **_plan(order_intent_count=0),\n"
        "            \"manual_ready_count\": 0,\n"
        "            \"conclusion_status\": \"no_manual_action\",\n"
        "        },\n"
        "        daily_operations=_operations(manual_ready_count=0),\n"
        "        order_facts=[],\n"
        "        fill_facts=[],\n"
        "        generated_at=\"2026-07-01T09:32:00+08:00\",\n"
        "    )\n\n"
        "    assert all(\n"
        "        item[\"id\"] != \"acceptance_audit\" for item in summary[\"subsystems\"]\n"
        "    )\n\n",
    )

    regex_once(
        "server/services/operations_today_subsystems.py",
        r"\n\ndef _acceptance_audit_subsystem\(.*?(?=\n\ncitic_source_follow_up_attention =)",
        "\n",
    )
    for fragment in (
        "acceptance_audit_subsystem = _acceptance_audit_subsystem\n",
        "acceptance_audit_export_subsystem = _acceptance_audit_export_subsystem\n",
        "acceptance_audit_detail_status = _acceptance_audit_detail_status",
    ):
        remove_exact("server/services/operations_today_subsystems.py", fragment)

    for fragment in (
        '        "review_acceptance_audit_gaps": "complete_acceptance_audit_evidence_required",\n',
        '        "export_acceptance_audit": "complete_acceptance_audit_evidence_required",\n',
        '        "acceptance_audit": "complete_acceptance_audit_evidence_required",\n',
    ):
        remove_exact("server/services/operations_today_values.py", fragment)

    regex_once(
        "web/src/features/backtest/api-governance-contracts.ts",
        r"\nexport type AcceptanceAuditCriterion = \{.*?\n\};\n\nexport type AcceptanceAuditSummary = \{.*?\n\};\n\nexport type AcceptanceAuditExport = \{.*?\n\};\n",
        "\n",
    )
    for fragment in (
        "  AcceptanceAuditCriterion,\n",
        "  AcceptanceAuditExport,\n",
        "  AcceptanceAuditSummary,\n",
    ):
        remove_exact("web/src/features/backtest/api-contracts.ts", fragment)

    architecture = "web/src/features/backtest/backtest-architecture.test.ts"
    for fragment in (
        "AcceptanceAuditCriterion\n",
        "AcceptanceAuditExport\n",
        "AcceptanceAuditSummary\n",
        "useSingleInstrumentStrategyLoopAcceptanceAuditQuery\n",
        "      '/api/acceptance-audits/single_instrument_strategy_loop',\n",
        "      \"['acceptance-audit', 'single_instrument_strategy_loop']\",\n",
    ):
        remove_exact(architecture, fragment)

    page_test = "web/src/features/backtest/components/backtest-page.test.tsx"
    regex_once(
        page_test,
        r"\nconst singleInstrumentAcceptanceAudit = \{.*?\n\};\n",
        "\n",
    )
    for fragment in (
        "  acceptanceAudit = singleInstrumentAcceptanceAudit,\n",
        "  acceptanceAudit?: unknown;\n",
        "  expect(await screen.findByText('Acceptance audit coverage')).toBeTruthy();\n",
        "  expect(await screen.findByText('10/10 criteria verified')).toBeTruthy();\n",
        "  expect(\n    await screen.findByText('single_instrument_strategy_loop'),\n  ).toBeTruthy();\n",
        "  await waitFor(() =>\n    expect(fetchMock).toHaveBeenCalledWith(\n      expect.stringContaining(\n        '/api/acceptance-audits/single_instrument_strategy_loop',\n      ),\n      expect.any(Object),\n    ),\n  );\n",
        "    '/api/acceptance-audits/single_instrument_strategy_loop',\n",
        "      if (\n        url.includes('/api/acceptance-audits/single_instrument_strategy_loop')\n      ) {\n        return jsonResponse(acceptanceAudit);\n      }\n",
    ):
        remove_exact(page_test, fragment)

    forbidden = (
        "AcceptanceAudit",
        "acceptance_audit",
        "/api/acceptance-audits/",
        "useSingleInstrumentStrategyLoopAcceptanceAuditQuery",
    )
    residuals: list[str] = []
    for root in (Path("analytics"), Path("server"), Path("web/src/features/backtest")):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            if ".test." in path.name or path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in forbidden):
                residuals.append(str(path))
    if residuals:
        raise SystemExit(
            "retired acceptance audit remains in production sources: "
            + ", ".join(sorted(residuals))
        )

    for path in (
        architecture,
        page_test,
        "web/src/features/backtest/api-contracts.ts",
        "web/src/features/backtest/api-governance-contracts.ts",
    ):
        text = read(path)
        for token in forbidden + ("singleInstrumentAcceptanceAudit", "acceptanceAudit"):
            if token in text:
                raise SystemExit(f"{path}: stale token remains: {token}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
