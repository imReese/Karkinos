"""Executable HTTP endpoint type-resolution boundaries."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from server.contracts.http import account_truth as account_truth_contracts
from server.routes import account_truth as account_truth_facade
from server.routes.account_truth import create_router as create_account_truth_router
from server.routes.backtest import create_router as create_backtest_router
from server.routes.market import create_router as create_market_router
from server.routes.portfolio import create_router as create_portfolio_router

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENDPOINT_ROOT = PROJECT_ROOT / "server/http"

BODY_OPERATIONS = {
    ("post", "/api/account-truth/broker-statement/import"),
    ("post", "/api/account-truth/broker-statement/preview"),
    ("post", "/api/account-truth/citic-history-xls/canonical-resolutions"),
    ("post", "/api/account-truth/citic-history-xls/canonical-resolutions/revoke"),
    ("post", "/api/account-truth/citic-history-xls/directory/intakes"),
    ("post", "/api/account-truth/citic-history-xls/directory/query-window-reviews"),
    ("post", "/api/account-truth/citic-history-xls/intakes"),
    ("post", "/api/account-truth/citic-history-xls/preview"),
    ("post", "/api/account-truth/citic-history-xls/query-window-reviews"),
    ("post", "/api/account-truth/citic-history-xls/query-window-reviews/revoke"),
    ("post", "/api/account-truth/citic-history-xls/source-scope-reviews"),
    ("post", "/api/account-truth/citic-history-xls/source-scope-reviews/revoke"),
    ("post", "/api/account-truth/evidence-scope/reviews"),
    ("post", "/api/account-truth/evidence-scope/reviews/revoke"),
    ("post", "/api/account-truth/fee-schedule/preview"),
    ("post", "/api/account-truth/fee-schedule/reviews"),
    ("post", "/api/account-truth/fee-schedule/reviews/revoke"),
    (
        "post",
        "/api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review",
    ),
    ("post", "/api/backtest/attribution-preview"),
    ("post", "/api/backtest/compare"),
    ("post", "/api/backtest/paper-shadow-preview"),
    ("post", "/api/backtest/risk-preview"),
    ("post", "/api/backtest/run"),
    ("post", "/api/backtest/signal-preview"),
    ("post", "/api/backtest/sweep"),
    ("post", "/api/market/bars/backfill"),
    ("post", "/api/market/calendar/sync"),
    ("post", "/api/market/fund-nav/confirmed/refresh"),
    ("post", "/api/market/instrument-metadata/backfill"),
    ("post", "/api/market/quotes/refresh"),
    ("post", "/api/market/research-notes"),
    ("post", "/api/market/watchlist"),
    ("put", "/api/market/calendar/verification"),
    ("put", "/api/market/research-notes/{note_id}"),
    ("post", "/api/portfolio/cash-flow"),
    ("post", "/api/portfolio/cash-flow/{flow_id}/corrections"),
    ("post", "/api/portfolio/pending-fund-orders/{order_id}/confirm"),
    ("post", "/api/portfolio/trade"),
    ("post", "/api/portfolio/trade/{trade_id}/corrections"),
    ("post", "/api/portfolio/trade/preview"),
}

pytestmark = pytest.mark.unit


def _endpoint_paths() -> list[Path]:
    return sorted(ENDPOINT_ROOT.glob("*_endpoints/*.py"))


def _dependency_assignment(node: ast.Assign) -> tuple[str, str] | None:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return None
    if not isinstance(node.value, ast.Call) or not isinstance(
        node.value.func, ast.Name
    ):
        return None
    if node.value.func.id != "dependency" or len(node.value.args) != 1:
        return None
    argument = node.value.args[0]
    if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
        return None
    return node.targets[0].id, argument.value


def _endpoint_type_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        annotations: list[ast.expr] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.extend(
                argument.annotation
                for argument in (*node.args.posonlyargs, *node.args.args)
                if argument.annotation is not None
            )
            annotations.extend(
                argument.annotation
                for argument in node.args.kwonlyargs
                if argument.annotation is not None
            )
            if node.args.vararg is not None and node.args.vararg.annotation is not None:
                annotations.append(node.args.vararg.annotation)
            if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
                annotations.append(node.args.kwarg.annotation)
            if node.returns is not None:
                annotations.append(node.returns)
        if isinstance(node, ast.Call):
            annotations.extend(
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "response_model"
            )
        for annotation in annotations:
            names.update(
                child.id
                for child in ast.walk(annotation)
                if isinstance(child, ast.Name)
            )
    return names


def test_endpoint_factories_never_resolve_types_from_route_facades() -> None:
    violations: list[str] = []
    for path in _endpoint_paths():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        endpoint_type_names = _endpoint_type_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            assignment = _dependency_assignment(node)
            if assignment is None:
                continue
            target, dependency_name = assignment
            if (
                target in endpoint_type_names
                or target[:1].isupper()
                or dependency_name[:1].isupper()
            ):
                violations.append(f"{path.name}:{node.lineno}:{target}")

    assert violations == []


def test_endpoint_modules_stay_bounded_and_never_import_route_modules() -> None:
    violations: list[str] = []
    for path in _endpoint_paths():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if len(source.splitlines()) > 800:
            violations.append(f"{path.name}:module_lines")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                if node.end_lineno - node.lineno + 1 > 350:
                    violations.append(f"{path.name}:{node.name}:function_lines")
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "server.routes"
            ):
                violations.append(f"{path.name}:{node.lineno}:route_import")

    assert violations == []


def test_account_truth_request_models_have_one_contract_owner() -> None:
    contract_path = Path(inspect.getsourcefile(account_truth_contracts) or "")
    contract_source = contract_path.read_text(encoding="utf-8")
    contract_tree = ast.parse(contract_source, filename=str(contract_path))

    assert len(contract_source.splitlines()) <= 800
    assert not [
        node
        for node in ast.walk(contract_tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("server.routes")
    ]

    owned_models = {
        name: value
        for name, value in vars(account_truth_contracts).items()
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value is not BaseModel
        and value.__module__ == account_truth_contracts.__name__
    }
    assert set(account_truth_contracts.__all__) == set(owned_models)
    for name, model in owned_models.items():
        assert getattr(account_truth_facade, name) is model

    facade_path = Path(inspect.getsourcefile(account_truth_facade) or "")
    facade_tree = ast.parse(
        facade_path.read_text(encoding="utf-8"),
        filename=str(facade_path),
    )
    assert not [node for node in facade_tree.body if isinstance(node, ast.ClassDef)]


def test_endpoint_request_models_remain_openapi_request_bodies() -> None:
    app = FastAPI()
    for create_router in (
        create_market_router,
        create_backtest_router,
        create_portfolio_router,
        create_account_truth_router,
    ):
        app.include_router(create_router())

    schema = app.openapi()
    actual_body_operations: set[tuple[str, str]] = set()
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"post", "put", "patch"}:
                continue
            if "requestBody" in operation:
                actual_body_operations.add((method, path))
            query_names = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter["in"] == "query"
            }
            assert query_names.isdisjoint({"body", "request"}), (method, path)

    assert actual_body_operations == BODY_OPERATIONS


def test_portfolio_trade_openapi_declares_manual_and_pending_fund_responses() -> None:
    app = FastAPI()
    app.include_router(create_portfolio_router())

    responses = app.openapi()["paths"]["/api/portfolio/trade"]["post"]["responses"]

    assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/TradeResponse"
    )
    assert responses["202"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/PendingFundTradeAcceptedResponse"
    )
