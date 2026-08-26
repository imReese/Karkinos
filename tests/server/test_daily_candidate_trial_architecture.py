from __future__ import annotations

import ast
import inspect
from pathlib import Path

from server.services.daily_candidate_trial import DailyCandidateTrialService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = PROJECT_ROOT / "server/services/daily_candidate_trial.py"
EVALUATION_PATH = PROJECT_ROOT / "server/services/daily_candidate_trial_evaluation.py"
TICKET_EVALUATION_PATH = (
    PROJECT_ROOT / "server/services/daily_candidate_trial_ticket_evaluation.py"
)
VALUES_PATH = PROJECT_ROOT / "server/services/daily_candidate_trial_values.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _called_attributes(path: Path) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_daily_candidate_trial_facade_preserves_public_service_contract() -> None:
    assert list(inspect.signature(DailyCandidateTrialService).parameters) == [
        "db",
        "clock",
        "strategy_gate_resolver",
        "execution_closure_resolver",
        "account_truth_replay_resolver",
    ]
    assert {
        "get_status",
        "record_review",
        "list_reviews",
    } <= set(vars(DailyCandidateTrialService))


def test_daily_candidate_trial_modules_have_single_directional_dependencies() -> None:
    facade_imports = _imports(SERVICE_PATH)
    evaluation_imports = _imports(EVALUATION_PATH)
    ticket_imports = _imports(TICKET_EVALUATION_PATH)

    assert "server.services.daily_candidate_trial_evaluation" in facade_imports
    assert "server.services.daily_candidate_trial_values" in facade_imports
    assert (
        "server.services.daily_candidate_trial_ticket_evaluation" in evaluation_imports
    )
    assert "server.services.daily_candidate_trial" not in evaluation_imports
    assert "server.services.daily_candidate_trial" not in ticket_imports
    assert "server.services.daily_candidate_trial_evaluation" not in ticket_imports


def test_daily_candidate_trial_replay_layers_are_read_only_and_non_authorizing() -> (
    None
):
    forbidden_calls = {
        "append_event_sync",
        "submit_order",
        "cancel_order",
        "save_order_sync",
        "save_fill_sync",
        "insert_ledger_entry_sync",
        "update_capital_authority",
    }
    for path in (EVALUATION_PATH, TICKET_EVALUATION_PATH, VALUES_PATH):
        assert _called_attributes(path).isdisjoint(forbidden_calls)


def test_daily_candidate_trial_modules_stay_reviewable() -> None:
    limits = {
        SERVICE_PATH: 550,
        EVALUATION_PATH: 600,
        TICKET_EVALUATION_PATH: 400,
        VALUES_PATH: 300,
    }
    for path, module_limit in limits.items():
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= module_limit
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert (node.end_lineno or node.lineno) - node.lineno + 1 <= 200
