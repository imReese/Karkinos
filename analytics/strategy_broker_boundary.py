"""Static guard for investment-domain broker authority boundaries."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "account_truth.broker_connector",
    "account_truth.broker_execution_edge_conformance",
    "account_truth.broker_order_lifecycle",
    "server.services.broker_connector_runtime",
    "server.services.broker_gateway",
    "server.services.controlled_broker_cancellation",
    "server.services.controlled_broker_submission",
    "server.services.controlled_broker_write_release",
    "server.services.controlled_session_automatic_pause",
    "server.services.controlled_session_budget_reservation",
    "server.services.controlled_session_live_gates",
    "server.services.controlled_session_runtime_authority",
    "server.routes.broker_gateway",
    "server.routes.controlled_broker_submission",
    "server.routes.controlled_broker_write_release",
    "server.routes.controlled_session_automatic_pause",
    "server.routes.controlled_session_budget_reservation",
    "server.routes.controlled_session_runtime_authority",
    "execution",
)

FORBIDDEN_CALL_NAMES: tuple[str, ...] = (
    "broker_cancel",
    "cancel",
    "cancel_order",
    "create_manual_ticket",
    "query_connector_snapshot",
    "query_order",
    "read_account_snapshot",
    "record_manual_ticket",
    "submit",
    "submit_live_order",
    "submit_order",
)

DEFAULT_PROTECTED_PATHS: tuple[str, ...] = (
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

RUNTIME_SESSION_AUTHORITY_PROTECTED_PATHS: tuple[str, ...] = (
    "server/services/controlled_session_*.py",
)

RUNTIME_SESSION_FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "account_truth.broker_connector",
    "account_truth.broker_execution_edge_conformance",
    "account_truth.broker_order_lifecycle",
    "server.services.broker_connector_runtime",
    "server.services.broker_gateway",
    "server.services.controlled_broker_cancellation",
    "server.services.controlled_broker_submission",
    "server.services.controlled_broker_write_release",
    "server.routes.broker_gateway",
    "server.routes.controlled_broker_submission",
    "server.routes.controlled_broker_write_release",
    "execution",
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
    """Return protected investment code that crosses broker authority directly.

    The default scope covers strategy and research code plus their deterministic
    risk, Decision, AI, promotion, and learning orchestration entry points. It
    also protects capital-authorization and capital-scaling evidence surfaces,
    where an eligible review must remain distinct from broker authority.
    Callers may still pass explicit paths or relative glob patterns for fixture
    or extension scans.
    """
    return _find_broker_boundary_violations(
        root=Path(root),
        paths=paths,
        default_paths=DEFAULT_PROTECTED_PATHS,
        forbidden_import_prefixes=FORBIDDEN_IMPORT_PREFIXES,
        forbidden_call_names=FORBIDDEN_CALL_NAMES,
    )


def find_runtime_session_broker_boundary_violations(
    root: str | Path = ".",
    *,
    paths: Iterable[str | Path] | None = None,
) -> tuple[StrategyBrokerBoundaryViolation, ...]:
    """Return controlled-session services that cross broker write authority.

    Controlled-session services may depend on one another and on persisted
    evidence readers. They must not import broker connectors, gateways, or
    controlled write services, nor call broker query or write methods. The
    actual controlled submission boundary remains outside this scan.
    """
    return _find_broker_boundary_violations(
        root=Path(root),
        paths=paths,
        default_paths=RUNTIME_SESSION_AUTHORITY_PROTECTED_PATHS,
        forbidden_import_prefixes=RUNTIME_SESSION_FORBIDDEN_IMPORT_PREFIXES,
        forbidden_call_names=FORBIDDEN_CALL_NAMES,
    )


def _find_broker_boundary_violations(
    *,
    root: Path,
    paths: Iterable[str | Path] | None,
    default_paths: tuple[str, ...],
    forbidden_import_prefixes: tuple[str, ...],
    forbidden_call_names: tuple[str, ...],
) -> tuple[StrategyBrokerBoundaryViolation, ...]:
    scan_paths = tuple(Path(path) for path in paths) if paths is not None else None
    source_files = _source_files(
        root_path=root,
        scan_paths=scan_paths,
        default_paths=default_paths,
    )
    violations: list[StrategyBrokerBoundaryViolation] = []
    for source_file in source_files:
        relative_path = _relative_posix_path(source_file, root)
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

        visitor = _StrategyBrokerBoundaryVisitor(
            relative_path,
            forbidden_import_prefixes=forbidden_import_prefixes,
            forbidden_call_names=forbidden_call_names,
        )
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
    def __init__(
        self,
        path: str,
        *,
        forbidden_import_prefixes: tuple[str, ...],
        forbidden_call_names: tuple[str, ...],
    ) -> None:
        self.path = path
        self.forbidden_import_prefixes = forbidden_import_prefixes
        self.forbidden_call_names = frozenset(forbidden_call_names)
        self.violations: list[StrategyBrokerBoundaryViolation] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            matched = _matched_forbidden_import(
                alias.name,
                self.forbidden_import_prefixes,
            )
            if matched is not None:
                self._add(node, "forbidden_import", matched)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        matched = _matched_forbidden_import(module, self.forbidden_import_prefixes)
        if matched is not None:
            self._add(node, "forbidden_import", matched)
        else:
            for alias in node.names:
                candidate = f"{module}.{alias.name}" if module else alias.name
                matched = _matched_forbidden_import(
                    candidate,
                    self.forbidden_import_prefixes,
                )
                if matched is not None:
                    self._add(node, "forbidden_import", matched)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _call_name(node.func)
        if call_name in self.forbidden_call_names:
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
    default_paths: tuple[str, ...],
) -> tuple[Path, ...]:
    targets = scan_paths or tuple(Path(path) for path in default_paths)
    files: list[Path] = []
    for target in targets:
        if not target.is_absolute() and _contains_glob_pattern(target):
            files.extend(
                item
                for item in root_path.glob(target.as_posix())
                if item.is_file()
                and _is_python_source(item)
                and "__pycache__" not in item.parts
            )
            continue
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
    return tuple(sorted(set(files)))


def _contains_glob_pattern(path: Path) -> bool:
    return any(character in path.as_posix() for character in "*?[")


def _is_python_source(path: Path) -> bool:
    return path.suffix == ".py" or path.name.endswith(".py.example")


def _matched_forbidden_import(
    module_name: str,
    forbidden_import_prefixes: tuple[str, ...],
) -> str | None:
    for prefix in forbidden_import_prefixes:
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
