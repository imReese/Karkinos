from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PYTHON_HELP_ENTRYPOINTS = (
    "configure_data_source.py",
    "export_acceptance_audit.py",
    "import_broker_order_lifecycle.py",
    "ingest_broker_order_lifecycle_collector_batch.py",
    "migrate_legacy_qmt_order_lifecycle.py",
    "operator_signer.py",
    "review_broker_adapter_release.py",
    "run_broker_adapter_conformance.py",
    "run_broker_execution_edge_conformance.py",
    "sync_market_bars_to_db.py",
    "verify_docker_runtime.py",
    "verify_market_bars.py",
)


def test_scripts_readme_lists_every_supported_entrypoint() -> None:
    scripts_root = Path("scripts")
    readme = (scripts_root / "README.md").read_text(encoding="utf-8")
    entrypoints = sorted(
        path.name
        for path in scripts_root.iterdir()
        if path.is_file()
        and path.suffix in {".py", ".sh"}
        and not path.name.startswith("_")
    )

    missing = [name for name in entrypoints if name not in readme]

    assert missing == []
    assert "import_qmt_order_lifecycle.py" not in entrypoints


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
