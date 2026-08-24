from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _module_name(path: Path, *, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


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
    route_modules = {
        _module_name(path, root=root) for path in paths if path.name != "__init__.py"
    }
    edges: set[tuple[str, str]] = set()
    for path in paths:
        if path.name == "__init__.py":
            continue
        owner = _module_name(path, root=root)
        for imported in _imported_modules(path, root=root):
            candidates = [
                module
                for module in route_modules
                if imported == module or imported.startswith(f"{module}.")
            ]
            if not candidates:
                continue
            dependency = max(candidates, key=len)
            if dependency != owner:
                edges.add((owner, dependency))
    return edges


def _is_private_symbol(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _cross_module_private_imports(
    paths: list[Path],
    *,
    root: Path = PROJECT_ROOT,
) -> set[str]:
    violations: set[str] = set()
    for path in paths:
        relative = path.relative_to(root)
        package = list(relative.with_suffix("").parts[:-1])
        owner = _module_name(path, root=root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
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
            if not base or base == owner:
                continue
            for alias in node.names:
                if _is_private_symbol(alias.name):
                    violations.add(f"{relative.as_posix()} -> {base}.{alias.name}")
    return violations


def _server_import_graph(
    paths: list[Path],
    *,
    root: Path = PROJECT_ROOT,
) -> dict[str, set[str]]:
    modules = {_module_name(path, root=root): path for path in paths}
    graph = {module: set() for module in modules}
    for owner, path in modules.items():
        for imported in _imported_modules(path, root=root):
            candidates = [
                module
                for module in modules
                if imported == module or imported.startswith(f"{module}.")
            ]
            if not candidates:
                continue
            dependency = max(candidates, key=len)
            if dependency != owner:
                graph[owner].add(dependency)
    return graph


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[tuple[str, ...]]:
    next_index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal next_index
        indices[node] = next_index
        lowlinks[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)

        for dependency in graph[node]:
            if dependency not in indices:
                visit(dependency)
                lowlinks[node] = min(lowlinks[node], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[dependency])

        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            dependency = stack.pop()
            on_stack.remove(dependency)
            component.append(dependency)
            if dependency == node:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for node in graph:
        if node not in indices:
            visit(node)
    return sorted(components)


def test_application_and_ai_runtime_do_not_import_http_routes() -> None:
    paths = sorted((PROJECT_ROOT / "server/services").rglob("*.py"))
    paths.extend(sorted((PROJECT_ROOT / "server/ai_runtime").rglob("*.py")))

    assert _violations(paths, forbidden_prefix="server.routes") == []


def test_app_uses_composition_instead_of_http_route_use_cases() -> None:
    assert (
        _violations(
            [PROJECT_ROOT / "server/app.py"],
            forbidden_prefix="server.routes",
        )
        == []
    )


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


def test_http_routes_have_zero_route_to_route_dependencies() -> None:
    paths = sorted((PROJECT_ROOT / "server/routes").rglob("*.py"))

    assert _route_import_edges(paths) == set()

    delivery_paths = sorted((PROJECT_ROOT / "server/http").rglob("*.py"))
    assert _violations(delivery_paths, forbidden_prefix="server.routes") == []


def test_http_delivery_does_not_own_sqlite_connections() -> None:
    paths = sorted((PROJECT_ROOT / "server/routes").rglob("*.py"))
    paths.extend(sorted((PROJECT_ROOT / "server/http").rglob("*.py")))

    assert _violations(paths, forbidden_prefix="sqlite3") == []


def test_http_delivery_modules_and_factories_stay_bounded() -> None:
    paths = sorted((PROJECT_ROOT / "server/routes").rglob("*.py"))
    paths.extend(sorted((PROJECT_ROOT / "server/http").rglob("*.py")))
    violations: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        line_count = len(source.splitlines())
        if line_count > 800:
            violations.append(f"{relative}: module has {line_count} lines")
        tree = ast.parse(source, filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if function_lines > 350:
                violations.append(
                    f"{relative}:{node.lineno} {node.name} has {function_lines} lines"
                )

    assert violations == []


def test_routes_and_app_have_zero_cross_module_private_imports() -> None:
    paths = sorted((PROJECT_ROOT / "server/routes").rglob("*.py"))
    paths.extend(sorted((PROJECT_ROOT / "server/http").rglob("*.py")))
    paths.append(PROJECT_ROOT / "server/app.py")

    assert _cross_module_private_imports(paths) == set()


def test_server_has_zero_cross_module_private_imports() -> None:
    paths = sorted((PROJECT_ROOT / "server").rglob("*.py"))

    assert _cross_module_private_imports(paths) == set()


def test_server_module_graph_has_no_dependency_cycles() -> None:
    paths = sorted((PROJECT_ROOT / "server").rglob("*.py"))

    assert _strongly_connected_components(_server_import_graph(paths)) == []


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
    assert _cross_module_private_imports([service], root=tmp_path) == {
        "server/services/rogue.py -> server.db._private_helper"
    }


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
        ("server.routes.market", "server.routes.decision"),
        ("server.routes.market", "server.routes.portfolio"),
        ("server.routes.portfolio", "server.routes.market"),
    }


def test_scc_scanner_reports_only_real_cycles(tmp_path: Path) -> None:
    package = tmp_path / "server"
    package.mkdir()
    first = package / "first.py"
    second = package / "second.py"
    third = package / "third.py"
    first.write_text("from server import second\n", encoding="utf-8")
    second.write_text("from server.first import value\n", encoding="utf-8")
    third.write_text("from server import first\n", encoding="utf-8")

    graph = _server_import_graph([first, second, third], root=tmp_path)

    assert _strongly_connected_components(graph) == [("server.first", "server.second")]
