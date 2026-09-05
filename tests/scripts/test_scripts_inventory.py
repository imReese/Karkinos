from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PYTHON_HELP_ENTRYPOINTS = (
    "broker/import_broker_order_lifecycle.py",
    "broker/ingest_broker_order_lifecycle_collector_batch.py",
    "broker/migrate_legacy_qmt_order_lifecycle.py",
    "broker/operator_signer.py",
    "broker/preview_citic_history_xls.py",
    "broker/review_broker_adapter_release.py",
    "broker/run_broker_adapter_conformance.py",
    "broker/run_broker_execution_edge_conformance.py",
    "ci/export_acceptance_audit.py",
    "ci/verify_docker_runtime.py",
    "data/configure_data_source.py",
    "data/sync_market_bars_to_db.py",
    "data/verify_market_bars.py",
    "service/audit_daily_candidate_production.py",
)


def test_scripts_readme_lists_every_supported_entrypoint() -> None:
    scripts_root = Path("scripts")
    readme = (scripts_root / "README.md").read_text(encoding="utf-8")
    entrypoints = sorted(
        path.relative_to(scripts_root).as_posix()
        for path in scripts_root.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".sh"}
        and not path.name.startswith("_")
    )

    missing = [name for name in entrypoints if name not in readme]

    assert missing == []
    assert "broker/import_qmt_order_lifecycle.py" not in entrypoints


def test_scripts_top_level_contains_only_daily_user_entrypoints() -> None:
    scripts_root = Path("scripts")
    visible_files = sorted(
        path.name
        for path in scripts_root.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )

    assert visible_files == ["README.md", "start_server.sh", "stop_server.sh"]


def test_production_runbooks_use_explicit_prod_stop() -> None:
    for path in (Path("scripts/README.md"),):
        runbook = path.read_text(encoding="utf-8")

        assert "`./scripts/stop_server.sh prod`" in runbook


@pytest.mark.parametrize("script_name", PYTHON_HELP_ENTRYPOINTS)
def test_python_entrypoint_help_runs_from_repository_root(script_name: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / script_name), "--help"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
