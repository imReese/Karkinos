from pathlib import Path

from tools.check_python_architecture import find_dependency_violations


def test_current_foundational_packages_follow_dependency_direction() -> None:
    assert find_dependency_violations(Path(".")) == ()


def test_dependency_boundary_reports_forbidden_first_party_imports(
    tmp_path: Path,
) -> None:
    source = tmp_path / "core" / "unsafe.py"
    source.parent.mkdir(parents=True)
    source.write_text("from server.db import AppDatabase\n")

    violations = find_dependency_violations(tmp_path)

    assert [
        (item.path, item.line, item.owner, item.dependency) for item in violations
    ] == [("core/unsafe.py", 1, "core", "server")]


def test_dependency_boundary_allows_declared_and_same_package_imports(
    tmp_path: Path,
) -> None:
    source = tmp_path / "domain" / "model.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from core.types import Symbol\n"
        "from domain.position import Position\n"
        "from decimal import Decimal\n"
    )

    assert find_dependency_violations(tmp_path) == ()


def test_backtest_must_not_depend_on_analytics(tmp_path: Path) -> None:
    source = tmp_path / "backtest" / "engine.py"
    source.parent.mkdir(parents=True)
    source.write_text("from analytics.backtest_metrics import BacktestMetrics\n")

    violations = find_dependency_violations(tmp_path)

    assert [
        (item.path, item.line, item.owner, item.dependency) for item in violations
    ] == [("backtest/engine.py", 1, "backtest", "analytics")]


def test_analytics_may_depend_on_backtest(tmp_path: Path) -> None:
    source = tmp_path / "analytics" / "report.py"
    source.parent.mkdir(parents=True)
    source.write_text("from backtest.result import BacktestResult\n")

    assert find_dependency_violations(tmp_path) == ()
