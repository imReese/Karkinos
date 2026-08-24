"""Executable ownership boundaries for the public HTTP model facade."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from pydantic import BaseModel

import server.models as facade
from server.contracts.http import (
    ledger_models,
    market_models,
    portfolio_models,
    settings_models,
    strategy_models,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACADE_PATH = PROJECT_ROOT / "server/models.py"
MODEL_MODULES = (
    market_models,
    portfolio_models,
    ledger_models,
    strategy_models,
    settings_models,
)

pytestmark = pytest.mark.unit


def _owned_models(module: object) -> dict[str, type[BaseModel]]:
    return {
        name: value
        for name, value in vars(module).items()
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value is not BaseModel
        and value.__module__ == module.__name__
    }


def test_http_model_facade_reexports_each_owned_model_exactly_once() -> None:
    owners: dict[str, type[BaseModel]] = {}
    for module in MODEL_MODULES:
        for name, model in _owned_models(module).items():
            assert name not in owners, name
            owners[name] = model

    assert len(owners) == 98
    assert set(facade.__all__) == set(owners)
    assert len(facade.__all__) == len(set(facade.__all__))
    for name, model in owners.items():
        assert getattr(facade, name) is model


def test_http_model_facade_is_only_a_stable_import_surface() -> None:
    source = FACADE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACADE_PATH))

    assert len(source.splitlines()) <= 250
    assert not [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module != "__future__"
    } == {
        "server.contracts.http.ledger_models",
        "server.contracts.http.market_models",
        "server.contracts.http.portfolio_models",
        "server.contracts.http.settings_models",
        "server.contracts.http.strategy_models",
    }


def test_http_model_modules_stay_bounded_and_avoid_private_imports() -> None:
    for module in MODEL_MODULES:
        path = Path(inspect.getsourcefile(module) or "")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        assert len(source.splitlines()) <= 800, path.name
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                assert node.end_lineno - node.lineno + 1 <= 350, (
                    path.name,
                    node.name,
                )
            if isinstance(node, ast.ImportFrom):
                assert not {
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("_") and not alias.name.startswith("__")
                }, path.name


def test_http_model_dependency_graph_is_acyclic_and_explicit() -> None:
    module_names = {module.__name__ for module in MODEL_MODULES}
    actual: dict[str, set[str]] = {}
    for module in MODEL_MODULES:
        path = Path(inspect.getsourcefile(module) or "")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        actual[module.__name__] = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module in module_names
        }

    assert actual == {
        "server.contracts.http.market_models": set(),
        "server.contracts.http.portfolio_models": {
            "server.contracts.http.strategy_models"
        },
        "server.contracts.http.ledger_models": set(),
        "server.contracts.http.strategy_models": {
            "server.contracts.http.ledger_models"
        },
        "server.contracts.http.settings_models": set(),
    }
