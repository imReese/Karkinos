"""Static guard for strategy-to-broker authority boundaries."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "account_truth.broker_connector",
    "server.services.broker_connector_runtime",
    "server.services.broker_gateway",
    "server.routes.broker_gateway",
    "execution.broker",
    "execution.gateway",
)

FORBIDDEN_CALL_NAMES: tuple[str, ...] = (
    "broker_cancel",
    "cancel_order",
    "create_manual_ticket",
    "query_connector_snapshot",
    "record_manual_ticket",
    "submit_live_order",
    "submit_order",
)


@dataclass(frozen=True)
class StrategyBrokerBoundaryViolation:
    path: str
    line: int
    column: int
    violation_type: str
    detail: str


def find_strategy_broker_boundary_violations(
    root: str | Path = ".",
    *,
    paths: Iterable[str | Path] | None = None,
) -> tuple[StrategyBrokerBoundaryViolation, ...]:
    """Return strategy files that try to cross the broker boundary directly."""
    root_path = Path(root)
    scan_paths = tuple(Path(path) for path in paths) if paths is not None else None
    source_files = _source_files(root_path=root_path, scan_paths=scan_paths)
    violations: list[StrategyBrokerBoundaryViolation] = []
    for source_file in source_files:
        relative_path = _relative_posix_path(source_file, root_path)
        try:
            tree = ast.parse(source_file.read_text(), filename=relative_path)
        except SyntaxError as exc:
            violations.append(
                StrategyBrokerBoundaryViolation(
                    path=relative_path,
                    line=exc.lineno or 0,
                    column=exc.offset or 0,
                    violation_type="syntax_error",
                    detail=exc.msg,
                )
            )
            continue

        visitor = _StrategyBrokerBoundaryVisitor(relative_path)
        visitor.visit(tree)
        violations.extend(visitor.violations)

    return tuple(
        sorted(
            violations,
            key=lambda item: (
                item.path,
                item.line,
                item.column,
                item.violation_type,
                item.detail,
            ),
        )
    )


class _StrategyBrokerBoundaryVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.violations: list[StrategyBrokerBoundaryViolation] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            matched = _matched_forbidden_import(alias.name)
            if matched is not None:
                self._add(node, "forbidden_import", matched)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        matched = _matched_forbidden_import(module)
        if matched is not None:
            self._add(node, "forbidden_import", matched)
        else:
            for alias in node.names:
                candidate = f"{module}.{alias.name}" if module else alias.name
                matched = _matched_forbidden_import(candidate)
                if matched is not None:
                    self._add(node, "forbidden_import", matched)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _call_name(node.func)
        if call_name in FORBIDDEN_CALL_NAMES:
            self._add(node, "forbidden_call", call_name)
        self.generic_visit(node)

    def _add(self, node: ast.AST, violation_type: str, detail: str) -> None:
        self.violations.append(
            StrategyBrokerBoundaryViolation(
                path=self.path,
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
                violation_type=violation_type,
                detail=detail,
            )
        )


def _source_files(
    *,
    root_path: Path,
    scan_paths: tuple[Path, ...] | None,
) -> tuple[Path, ...]:
    targets = scan_paths or (root_path / "strategy",)
    files: list[Path] = []
    for target in targets:
        path = target if target.is_absolute() else root_path / target
        if path.is_file() and _is_python_source(path):
            files.append(path)
        elif path.is_dir():
            files.extend(
                item
                for item in path.rglob("*")
                if item.is_file()
                and _is_python_source(item)
                and "__pycache__" not in item.parts
            )
    return tuple(sorted(files))


def _is_python_source(path: Path) -> bool:
    return path.suffix == ".py" or path.name.endswith(".py.example")


def _matched_forbidden_import(module_name: str) -> str | None:
    for prefix in FORBIDDEN_IMPORT_PREFIXES:
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            return prefix
    return None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _relative_posix_path(path: Path, root_path: Path) -> str:
    try:
        return path.relative_to(root_path).as_posix()
    except ValueError:
        return path.as_posix()
