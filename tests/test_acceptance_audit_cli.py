from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_acceptance_audit.py"


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd or REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_acceptance_audit_cli_outputs_parseable_stdout_json() -> None:
    result = _run_cli()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["generated_at"]
    assert payload["selected_audit"] == "all"
    assert payload["overall_is_complete"] is True
    assert payload["audits"]


def test_acceptance_audit_cli_research_evidence_filter_outputs_one_audit() -> None:
    result = _run_cli("--audit", "research_evidence")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["selected_audit"] == "research_evidence"
    assert [audit["key"] for audit in payload["audits"]] == ["research_evidence"]
    audit = payload["audits"][0]
    assert audit["required_count"] == 12
    assert audit["completed_count"] == audit["required_count"]
    assert audit["criteria"]


def test_acceptance_audit_cli_all_outputs_every_registered_audit() -> None:
    result = _run_cli("--audit", "all")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert [audit["key"] for audit in payload["audits"]] == [
        "profit_discipline",
        "strategy_lab",
        "research_evidence",
    ]
    assert all(audit["is_complete"] for audit in payload["audits"])


def test_acceptance_audit_cli_pretty_keeps_valid_json() -> None:
    result = _run_cli("--audit", "all", "--pretty")

    assert result.returncode == 0, result.stderr
    assert "\n  " in result.stdout
    payload = json.loads(result.stdout)
    assert payload["overall_is_complete"] is True


def test_acceptance_audit_cli_does_not_write_default_output_file(
    tmp_path: Path,
) -> None:
    result = _run_cli("--audit", "research_evidence", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["selected_audit"] == "research_evidence"
    assert list(tmp_path.iterdir()) == []
