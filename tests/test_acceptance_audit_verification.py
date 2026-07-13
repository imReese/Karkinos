from __future__ import annotations

from pathlib import Path

from analytics.acceptance_audit_report import build_acceptance_audit_export
from analytics.acceptance_audit_verification import verify_acceptance_audit_export


def _write_junit(path: Path, *, tests: int = 3, failures: int = 0) -> None:
    path.write_text(
        f'<testsuite tests="{tests}" failures="{failures}" errors="0" skipped="0" />',
        encoding="utf-8",
    )


def test_repository_evidence_verification_checks_every_declared_path_and_command(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.py"
    evidence.write_text("# deterministic evidence\n", encoding="utf-8")
    payload = {
        "generated_at": "2026-07-13T00:00:00Z",
        "selected_audit": "sample",
        "overall_is_complete": True,
        "audits": [
            {
                "key": "sample",
                "required_count": 1,
                "completed_count": 1,
                "is_complete": True,
                "criteria": [
                    {
                        "key": "safe_default",
                        "checkbox_text": "manual confirmation remains required",
                        "evidence_paths": ["evidence.py"],
                        "validation_commands": ["uv run python -m pytest tests"],
                        "is_complete": True,
                    }
                ],
                "limitations": [],
            }
        ],
    }

    verified = verify_acceptance_audit_export(payload, repo_root=tmp_path)

    assert verified["overall_is_complete"] is True
    assert verified["verification"]["level"] == "repository_structure"
    assert verified["verification"]["structural_verified"] is True
    criterion = verified["audits"][0]["criteria"][0]
    assert criterion["declared_is_complete"] is True
    assert criterion["evidence_verification"]["verified"] is True


def test_verification_fails_closed_for_missing_or_escaping_evidence(
    tmp_path: Path,
) -> None:
    payload = build_acceptance_audit_export(selected_audit="profit_discipline")
    payload["audits"][0]["criteria"][0]["evidence_paths"] = [
        "missing.py",
        "../outside.py",
    ]

    verified = verify_acceptance_audit_export(payload, repo_root=tmp_path)

    assert verified["overall_is_complete"] is False
    assert verified["verification"]["structural_verified"] is False
    checks = verified["audits"][0]["criteria"][0]["evidence_verification"]["paths"]
    assert checks[0]["exists"] is False
    assert checks[1]["inside_repository"] is False


def test_ci_report_verification_requires_nonempty_failure_free_reports(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.py"
    evidence.write_text("# evidence\n", encoding="utf-8")
    backend = tmp_path / "backend.xml"
    frontend = tmp_path / "frontend.xml"
    _write_junit(backend, tests=4)
    _write_junit(frontend, tests=2, failures=1)
    payload = {
        "generated_at": "2026-07-13T00:00:00Z",
        "selected_audit": "sample",
        "overall_is_complete": True,
        "audits": [
            {
                "key": "sample",
                "required_count": 1,
                "completed_count": 1,
                "is_complete": True,
                "criteria": [
                    {
                        "key": "safe_default",
                        "checkbox_text": "safe",
                        "evidence_paths": ["evidence.py"],
                        "validation_commands": ["npm --prefix web run test"],
                        "is_complete": True,
                    }
                ],
                "limitations": [],
            }
        ],
    }

    verified = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
        frontend_junit=frontend,
    )

    assert verified["overall_is_complete"] is False
    assert verified["verification"]["level"] == "ci_test_reports"
    assert verified["verification"]["test_reports"]["backend"]["verified"] is True
    assert verified["verification"]["test_reports"]["frontend"]["verified"] is False
