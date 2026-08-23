from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# Existing route-to-route imports are migration debt, not an approved direction
# for new code. Keep the baseline exact so edges may be removed without allowing
# a replacement edge or a new dependency cycle to enter unnoticed.
LEGACY_ROUTE_IMPORT_EDGES = frozenset(
    {
        ("ai_external_analysis_reviews", "ai_external_memory_informed_analyses"),
        ("ai_external_memory_informed_analyses", "ai_external_analysis_reviews"),
        ("ai_external_memory_informed_analyses", "ai_external_reviewed_memory"),
        ("ai_external_memory_informed_analyses", "ai_reviewed_memory_retrievals"),
        (
            "ai_external_promoted_analysis_memory",
            "ai_external_promoted_analysis_memory_retrievals",
        ),
        (
            "ai_external_promoted_analysis_memory",
            "ai_external_promoted_memory_analysis_reviews",
        ),
        (
            "ai_external_promoted_analysis_memory_retrievals",
            "ai_external_promoted_analysis_memory",
        ),
        (
            "ai_external_promoted_analysis_memory_retrievals",
            "ai_reviewed_memory_retrievals",
        ),
        (
            "ai_external_promoted_memory_analyses",
            "ai_external_promoted_memory_analysis_reviews",
        ),
        (
            "ai_external_promoted_memory_analyses",
            "ai_external_reviewed_memory_retrievals",
        ),
        (
            "ai_external_promoted_memory_analysis_reviews",
            "ai_external_analysis_reviews",
        ),
        (
            "ai_external_promoted_memory_analysis_reviews",
            "ai_external_promoted_analysis_memory",
        ),
        (
            "ai_external_promoted_memory_analysis_reviews",
            "ai_external_promoted_memory_analyses",
        ),
        ("ai_external_research", "ai_research"),
        ("ai_external_research", "ai_strategy_research"),
        ("ai_external_reviewed_memory", "ai_external_analysis_reviews"),
        (
            "ai_external_reviewed_memory",
            "ai_external_reviewed_memory_retrievals",
        ),
        (
            "ai_external_reviewed_memory_retrievals",
            "ai_external_promoted_memory_analyses",
        ),
        (
            "ai_external_reviewed_memory_retrievals",
            "ai_external_reviewed_memory",
        ),
        (
            "ai_external_reviewed_memory_retrievals",
            "ai_reviewed_memory_retrievals",
        ),
        (
            "ai_memory_informed_analyses",
            "ai_external_memory_informed_analyses",
        ),
        ("ai_memory_informed_analyses", "ai_reviewed_memory_retrievals"),
        ("ai_research", "account_strategy"),
        ("ai_research", "operations"),
        ("ai_research", "portfolio"),
        ("ai_research_task_analysis_reviews", "ai_research_task_analyses"),
        ("ai_reviewed_memory_retrievals", "ai_research_task_analyses"),
        ("ai_strategy_research", "ai_research"),
        ("automation", "decision"),
        ("automation", "market"),
        ("automation", "operations"),
        ("backtest", "account_strategy"),
        ("controlled_broker_submission", "controlled_broker_write_release"),
        ("controlled_broker_submission", "per_order_confirmation"),
        ("controlled_broker_write_release", "broker_connector_soak"),
        (
            "controlled_session_automatic_pause",
            "controlled_session_budget_reservation",
        ),
        ("controlled_session_automatic_pause", "controlled_session_envelope"),
        (
            "controlled_session_automatic_pause",
            "controlled_session_runtime_authority",
        ),
        ("controlled_session_budget_reservation", "controlled_session_envelope"),
        (
            "controlled_session_runtime_authority",
            "controlled_session_budget_reservation",
        ),
        ("controlled_session_runtime_authority", "controlled_session_envelope"),
        (
            "controlled_session_runtime_rate_limiter",
            "controlled_session_automatic_pause",
        ),
        (
            "controlled_session_runtime_rate_limiter",
            "controlled_session_runtime_authority",
        ),
        ("decision", "account_strategy"),
        ("decision", "portfolio"),
        ("market", "portfolio"),
        ("operations", "controlled_broker_write_release"),
        ("operations", "decision"),
        ("portfolio", "market"),
        ("trading", "decision"),
    }
)


def _imported_modules(path: Path, *, root: Path) -> tuple[str, ...]:
    relative = path.relative_to(root)
    package = list(relative.with_suffix("").parts[:-1])
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            keep = max(0, len(package) - node.level + 1)
            base_parts = package[:keep]
            if node.module:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
        else:
            base = node.module or ""
        if base:
            imported.append(base)
        imported.extend(
            f"{base}.{alias.name}" if base else alias.name
            for alias in node.names
            if alias.name != "*"
        )
    return tuple(imported)


def _violations(
    paths: list[Path],
    *,
    forbidden_prefix: str,
    root: Path = PROJECT_ROOT,
) -> list[str]:
    violations: list[str] = []
    for path in paths:
        for imported in _imported_modules(path, root=root):
            if imported == forbidden_prefix or imported.startswith(
                f"{forbidden_prefix}."
            ):
                violations.append(f"{path.relative_to(root).as_posix()} -> {imported}")
    return sorted(set(violations))


def _private_import_violations(
    paths: list[Path],
    *,
    module: str,
    root: Path = PROJECT_ROOT,
) -> list[str]:
    prefix = f"{module}._"
    violations: list[str] = []
    for path in paths:
        for imported in _imported_modules(path, root=root):
            if imported.startswith(prefix):
                violations.append(f"{path.relative_to(root).as_posix()} -> {imported}")
    return sorted(set(violations))


def _route_import_edges(
    paths: list[Path],
    *,
    root: Path = PROJECT_ROOT,
) -> set[tuple[str, str]]:
    route_names = {path.stem for path in paths if path.name != "__init__.py"}
    edges: set[tuple[str, str]] = set()
    for path in paths:
        owner = path.stem
        if owner == "__init__":
            continue
        for imported in _imported_modules(path, root=root):
            parts = imported.split(".")
            if parts[:2] != ["server", "routes"] or len(parts) < 3:
                continue
            dependency = parts[2]
            if dependency in route_names and dependency != owner:
                edges.add((owner, dependency))
    return edges


def test_application_and_ai_runtime_do_not_import_http_routes() -> None:
    paths = sorted((PROJECT_ROOT / "server/services").rglob("*.py"))
    paths.extend(sorted((PROJECT_ROOT / "server/ai_runtime").rglob("*.py")))

    assert _violations(paths, forbidden_prefix="server.routes") == []


def test_non_composition_modules_do_not_import_server_app() -> None:
    paths = [
        path
        for path in sorted((PROJECT_ROOT / "server").rglob("*.py"))
        if path.relative_to(PROJECT_ROOT).as_posix()
        not in {"server/app.py", "server/__main__.py"}
        and not path.is_relative_to(PROJECT_ROOT / "server/routes")
    ]

    assert _violations(paths, forbidden_prefix="server.app") == []


def test_services_do_not_import_private_server_db_symbols() -> None:
    paths = sorted((PROJECT_ROOT / "server/services").rglob("*.py"))

    assert _private_import_violations(paths, module="server.db") == []


def test_http_routes_do_not_add_route_to_route_dependencies() -> None:
    paths = sorted((PROJECT_ROOT / "server/routes").glob("*.py"))

    unexpected = _route_import_edges(paths) - LEGACY_ROUTE_IMPORT_EDGES

    assert unexpected == set(), (
        "Move reusable behavior behind a service or another public application "
        f"contract instead of adding route-to-route imports: {sorted(unexpected)}"
    )


def test_boundary_scanner_resolves_absolute_and_relative_imports(
    tmp_path: Path,
) -> None:
    service = tmp_path / "server/services/rogue.py"
    service.parent.mkdir(parents=True)
    service.write_text(
        "from server.routes.market import refresh\n"
        "from ..routes import decision\n"
        "from server import app\n"
        "from server.db import AppDatabase, _private_helper\n",
        encoding="utf-8",
    )

    assert _violations(
        [service],
        forbidden_prefix="server.routes",
        root=tmp_path,
    ) == [
        "server/services/rogue.py -> server.routes",
        "server/services/rogue.py -> server.routes.decision",
        "server/services/rogue.py -> server.routes.market",
        "server/services/rogue.py -> server.routes.market.refresh",
    ]
    assert _violations(
        [service],
        forbidden_prefix="server.app",
        root=tmp_path,
    ) == ["server/services/rogue.py -> server.app"]
    assert _private_import_violations(
        [service],
        module="server.db",
        root=tmp_path,
    ) == ["server/services/rogue.py -> server.db._private_helper"]


def test_route_edge_scanner_normalizes_symbols_and_relative_imports(
    tmp_path: Path,
) -> None:
    routes = tmp_path / "server/routes"
    routes.mkdir(parents=True)
    market = routes / "market.py"
    portfolio = routes / "portfolio.py"
    decision = routes / "decision.py"
    market.write_text(
        "from .portfolio import _quote_status\n"
        "from server.routes.decision import run_batch\n",
        encoding="utf-8",
    )
    portfolio.write_text("from server.routes.market import refresh\n", encoding="utf-8")
    decision.write_text("", encoding="utf-8")

    assert _route_import_edges(
        [decision, market, portfolio],
        root=tmp_path,
    ) == {
        ("market", "decision"),
        ("market", "portfolio"),
        ("portfolio", "market"),
    }
