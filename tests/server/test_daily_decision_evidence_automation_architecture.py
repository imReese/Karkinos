from __future__ import annotations

import ast
import inspect
from pathlib import Path

from server.services import daily_decision_evidence_automation as facade
from server.services import daily_decision_evidence_identity as identity
from server.services import daily_decision_policy_gates as policy_gates
from server.services import daily_decision_preparation as preparation
from server.services import daily_decision_strategy_gate as strategy_gate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "server" / "services"

MODULES = (
    "daily_decision_evidence_automation.py",
    "daily_decision_evidence_contracts.py",
    "daily_decision_evidence_collection.py",
    "daily_decision_evidence_values.py",
    "daily_decision_evidence_identity.py",
    "daily_decision_preflight_operator.py",
    "daily_decision_strategy_gate.py",
    "daily_decision_policy_gates.py",
    "daily_decision_preparation.py",
    "daily_decision_background_schedule.py",
    "daily_decision_production_outcome.py",
    "daily_decision_evidence_cycle.py",
    "daily_decision_evidence_orchestration.py",
    "daily_decision_evidence_composition.py",
)


def _tree(module: str) -> ast.Module:
    path = SERVICE_ROOT / module
    return ast.parse(path.read_text(encoding="utf-8"), filename=module)


def _imports(module: str) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_daily_decision_evidence_modules_and_functions_stay_bounded() -> None:
    violations: list[str] = []
    for module in MODULES:
        path = SERVICE_ROOT / module
        source = path.read_text(encoding="utf-8")
        if len(source.splitlines()) > 800:
            violations.append(f"{module}: module exceeds 800 lines")
        for node in ast.walk(ast.parse(source, filename=module)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if function_lines > 350:
                violations.append(
                    f"{module}:{node.lineno} {node.name} exceeds 350 lines"
                )

    assert violations == []


def test_original_module_remains_the_stable_public_facade() -> None:
    assert facade.DailyDecisionEvidenceAutomationService.__module__ == (
        "server.services.daily_decision_evidence_automation"
    )
    assert (
        facade.project_daily_candidate_financial_preflight
        is policy_gates.project_daily_candidate_financial_preflight
    )
    assert (
        facade.unavailable_daily_candidate_financial_preflight
        is policy_gates.unavailable_daily_candidate_financial_preflight
    )
    assert (
        facade.build_daily_candidate_preparation_check
        is preparation.build_daily_candidate_preparation_check
    )
    assert (
        facade.verify_daily_candidate_preparation_check
        is preparation.verify_daily_candidate_preparation_check
    )
    assert (
        facade.build_daily_candidate_strategy_gate_binding
        is strategy_gate.build_daily_candidate_strategy_gate_binding
    )
    assert (
        facade.daily_candidate_input_fingerprint
        is identity.daily_candidate_input_fingerprint
    )
    assert (
        facade.daily_candidate_record_fingerprint
        is identity.daily_candidate_record_fingerprint
    )
    assert (
        facade.manual_ticket_candidate_fingerprint
        is identity.manual_ticket_candidate_fingerprint
    )


def test_stable_facade_preserves_public_function_signatures() -> None:
    expected = {
        "build_daily_decision_evidence_automation_service": (
            "(state: 'Any', *, plan_reader: 'StatePlanReader', "
            "risk_runner: 'StateRiskRunner', quote_refresher: 'QuoteRefresher') "
            "-> 'DailyDecisionEvidenceAutomationService'"
        ),
        "project_daily_candidate_background_schedule": (
            "(*, db: 'Any', now: 'datetime | None' = None) -> 'dict[str, Any]'"
        ),
        "build_daily_candidate_preparation_check": (
            "(state: 'Any', *, run_date: 'str') -> 'dict[str, Any]'"
        ),
        "verify_daily_candidate_preparation_check": (
            "(value: 'Any', *, run_date: 'str') -> 'bool'"
        ),
        "daily_candidate_input_fingerprint": ("(payload: 'dict[str, Any]') -> 'str'"),
        "daily_candidate_record_fingerprint": ("(payload: 'dict[str, Any]') -> 'str'"),
        "manual_ticket_candidate_fingerprint": ("(payload: 'dict[str, Any]') -> 'str'"),
    }

    assert {
        name: str(inspect.signature(getattr(facade, name))) for name in expected
    } == expected


def test_production_outcome_is_structurally_partitioned() -> None:
    tree = _tree("daily_decision_production_outcome.py")
    functions = {
        node.name: (node.end_lineno or node.lineno) - node.lineno + 1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert functions["project_production_outcome"] <= 150
    assert functions["_collect_order_intent_evidence"] <= 200
    assert functions["_validate_account_truth_replay"] <= 80
    assert functions["_validate_terminal_evidence"] <= 80
    assert functions["_build_input_snapshot"] <= 150


def test_split_modules_do_not_reverse_import_facade_or_own_delivery_and_sqlite() -> (
    None
):
    facade_module = "server.services.daily_decision_evidence_automation"
    violations: list[str] = []
    for module in MODULES:
        imports = _imports(module)
        if module != "daily_decision_evidence_automation.py" and (
            facade_module in imports
        ):
            violations.append(f"{module}: reverse-imports stable facade")
        for imported in imports:
            if imported == "sqlite3" or imported.startswith("server.routes"):
                violations.append(f"{module}: imports {imported}")

    assert violations == []


def test_split_modules_use_only_public_cross_module_symbols() -> None:
    violations: list[str] = []
    for module in MODULES:
        owner = f"server.services.{Path(module).stem}"
        for node in ast.walk(_tree(module)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module == owner:
                continue
            for imported in node.names:
                if imported.name.startswith("_") and not imported.name.startswith("__"):
                    violations.append(
                        f"{module}: imports {node.module}.{imported.name}"
                    )

    assert violations == []
