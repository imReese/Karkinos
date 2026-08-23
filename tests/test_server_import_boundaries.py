from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
