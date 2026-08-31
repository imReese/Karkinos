"""Executable ownership boundaries for typed runtime configuration."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import server.config as facade
import server.config_types as value_types

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "server.config": PROJECT_ROOT / "server/config.py",
    "server.config_loading": PROJECT_ROOT / "server/config_loading.py",
    "server.config_fee_schedule": PROJECT_ROOT / "server/config_fee_schedule.py",
    "server.config_safety": PROJECT_ROOT / "server/config_safety.py",
    "server.config_types": PROJECT_ROOT / "server/config_types.py",
}
LEAF_TYPE_NAMES = {
    "AIProviderConfig",
    "BrokerConnectorConfig",
    "BrokerFeeScheduleConfig",
    "BrokerStatementCollectorConfig",
    "CiticHistoryXlsDirectoryConfig",
    "ControlledBridgePolicyConfig",
    "DataSourceProviderConfig",
    "TrustedOperatorIdentityConfig",
}

pytestmark = pytest.mark.unit


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_config_facade_keeps_public_class_identity_and_only_owns_root_configs() -> None:
    for name in LEAF_TYPE_NAMES:
        assert getattr(facade, name) is getattr(value_types, name)

    classes = {
        node.name
        for node in _tree(MODULES["server.config"]).body
        if isinstance(node, ast.ClassDef)
    }
    assert classes == {"BacktestConfig", "ServerConfig"}
    assert set(facade.__all__) == LEAF_TYPE_NAMES | {
        "BacktestConfig",
        "ServerConfig",
    }


def test_config_modules_stay_bounded_and_avoid_private_imports() -> None:
    for module, path in MODULES.items():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert len(source.splitlines()) <= 800, module
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno is not None
                assert node.end_lineno - node.lineno + 1 <= 350, (
                    module,
                    node.name,
                )
            if isinstance(node, ast.ImportFrom):
                assert not {
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("_") and not alias.name.startswith("__")
                }, module


def test_config_dependency_graph_is_explicit_and_acyclic() -> None:
    module_names = set(MODULES)
    actual = {
        module: {
            node.module
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ImportFrom) and node.module in module_names
        }
        for module, path in MODULES.items()
    }
    assert actual == {
        "server.config": {"server.config_loading", "server.config_types"},
        "server.config_loading": {
            "server.config_fee_schedule",
            "server.config_safety",
            "server.config_types",
        },
        "server.config_fee_schedule": {
            "server.config_safety",
            "server.config_types",
        },
        "server.config_safety": set(),
        "server.config_types": set(),
    }


def test_sensitive_key_recursion_has_one_canonical_owner() -> None:
    owners = {
        module
        for module, path in MODULES.items()
        if "def contains_sensitive_config_key(" in path.read_text(encoding="utf-8")
    }
    assert owners == {"server.config_safety"}

    for module in ("server.config_loading", "server.config_fee_schedule"):
        source = MODULES[module].read_text(encoding="utf-8")
        assert "contains_sensitive_config_key(" in source
