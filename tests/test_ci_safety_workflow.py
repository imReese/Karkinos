from __future__ import annotations

from pathlib import Path


def test_trading_safety_marker_covers_authority_and_integrity_boundaries() -> None:
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")
    expected = {
        "test_account_truth_gate.py",
        "test_automation_control.py",
        "test_controlled_broker_submission.py",
        "test_controlled_session_automatic_pause.py",
        "test_controlled_submission_reconciliation_clearance.py",
        "test_execution_batch_reconciliation.py",
        "test_oms_service.py",
        "test_paper_shadow_run_service.py",
        "test_strategy_broker_boundary.py",
        "test_trading_controls.py",
    }

    assert all(f'"{name}"' in conftest for name in expected)
    marker_block = conftest.split("def _is_trading_safety_test", maxsplit=1)[1]
    assert '"test_profit_discipline_smoke.py"' not in marker_block


def test_ci_has_incremental_python_quality_and_independent_trading_safety_jobs() -> (
    None
):
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Python changed-file quality" in workflow
    assert "uv run ruff check" in workflow
    assert "uv run black --check" in workflow
    assert "uv run isort --check-only" in workflow
    assert "uv run mypy" in workflow
    assert "uv run python tools/check_python_architecture.py" in workflow
    assert "Trading safety invariants" in workflow
    assert "python -m pytest -m trading_safety" in workflow
    assert "needs: [backend, frontend, trading-safety]" in workflow


def test_ci_pins_uv_and_requires_every_code_ci_job_to_pass() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    expected_results = {
        "python-quality": "PYTHON_QUALITY_RESULT",
        "backend": "BACKEND_RESULT",
        "dependency-audit": "DEPENDENCY_AUDIT_RESULT",
        "trading-safety": "TRADING_SAFETY_RESULT",
        "frontend": "FRONTEND_RESULT",
        "docker-runtime": "DOCKER_RUNTIME_RESULT",
        "browser-safety": "BROWSER_SAFETY_RESULT",
        "repository-acceptance-audit": "REPOSITORY_ACCEPTANCE_AUDIT_RESULT",
        "secret-scan": "SECRET_SCAN_RESULT",
        "hygiene": "HYGIENE_RESULT",
    }

    assert 'env:\n  UV_VERSION: "0.11.28"' in workflow
    pip_install_lines = {
        line.strip().removeprefix("run: ")
        for line in workflow.splitlines()
        if "python -m pip install" in line
    }
    assert pip_install_lines == {'python -m pip install "uv==${UV_VERSION}"'}

    code_ci_gate = workflow.partition("\n  code-ci-gate:\n")[2]
    assert code_ci_gate
    assert "    if: always()" in code_ci_gate
    required_jobs = {
        line.strip().removeprefix("- ")
        for line in code_ci_gate.splitlines()
        if line.startswith("      - ") and not line.startswith("      - name:")
    }
    assert required_jobs == set(expected_results)
    for job, result_variable in expected_results.items():
        assert (
            f"          {result_variable}: " f"${{{{ needs.{job}.result }}}}"
        ) in code_ci_gate
        assert f'          test "${{{result_variable}}}" = "success"' in code_ci_gate
