"""Check dependency direction for Karkinos foundational Python packages."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

FIRST_PARTY_PACKAGES = frozenset(
    {
        "account_truth",
        "analytics",
        "backtest",
        "core",
        "data",
        "domain",
        "execution",
        "notification",
        "risk",
        "server",
        "strategy",
    }
)

# These packages already have a one-way dependency model. Keep that model
# explicit while the larger server and analytics boundaries are migrated
# separately instead of grandfathering their existing coupling here.
ALLOWED_DEPENDENCIES: dict[str, frozenset[str]] = {
    "core": frozenset(),
    "domain": frozenset({"core"}),
    "data": frozenset({"core", "domain"}),
    "strategy": frozenset({"core", "data"}),
    "risk": frozenset({"core", "domain"}),
    "execution": frozenset({"core"}),
    "account_truth": frozenset(),
    "notification": frozenset(),
    "backtest": frozenset({"core", "data", "domain", "execution", "risk", "strategy"}),
}


@dataclass(frozen=True)
class DependencyViolation:
    path: str
    line: int
    owner: str
    dependency: str


def find_dependency_violations(
    root: str | Path = ".",
) -> tuple[DependencyViolation, ...]:
    """Return forbidden first-party imports from protected packages."""
    root_path = Path(root)
    violations: list[DependencyViolation] = []
    for owner, allowed in ALLOWED_DEPENDENCIES.items():
        package_path = root_path / owner
        if not package_path.is_dir():
            continue
        for source_path in sorted(package_path.rglob("*.py")):
            if "__pycache__" in source_path.parts:
                continue
            tree = ast.parse(source_path.read_text(), filename=str(source_path))
            for dependency, line in _first_party_imports(tree):
                if dependency == owner or dependency in allowed:
                    continue
                violations.append(
                    DependencyViolation(
                        path=source_path.relative_to(root_path).as_posix(),
                        line=line,
                        owner=owner,
                        dependency=dependency,
                    )
                )
    return tuple(
        sorted(
            violations,
            key=lambda item: (item.path, item.line, item.owner, item.dependency),
        )
    )


def _first_party_imports(tree: ast.AST) -> tuple[tuple[str, int], ...]:
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            dependency = name.partition(".")[0]
            if dependency in FIRST_PARTY_PACKAGES:
                imports.append((dependency, node.lineno))
    return tuple(imports)


def main() -> int:
    violations = find_dependency_violations()
    if not violations:
        print("Python dependency boundaries passed.")
        return 0
    for item in violations:
        print(
            f"{item.path}:{item.line}: {item.owner} must not depend on "
            f"{item.dependency}"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
