"""Verify acceptance manifests against repository and CI test evidence."""

from __future__ import annotations

import copy
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_SUPPORTED_COMMAND_BASES = (
    "git ls-files",
    "npm --prefix web",
    "rg -n",
    "uv run pytest",
    "uv run python -m pytest",
    "uv run python scripts/export_acceptance_audit.py",
)


def verify_acceptance_audit_export(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    backend_junit: Path | None = None,
    frontend_junit: Path | None = None,
) -> dict[str, Any]:
    """Return a copy with repository evidence and optional CI reports verified."""
    root = repo_root.resolve()
    verified = copy.deepcopy(payload)
    structural_failures: list[dict[str, str]] = []

    for audit in verified["audits"]:
        for criterion in audit["criteria"]:
            declared_complete = bool(criterion["is_complete"])
            evidence_checks = [
                _verify_evidence_path(root, path)
                for path in criterion["evidence_paths"]
            ]
            command_checks = [
                _verify_validation_command(command)
                for command in criterion["validation_commands"]
            ]
            structurally_verified = bool(evidence_checks) and bool(command_checks)
            structurally_verified = structurally_verified and all(
                check["verified"] for check in (*evidence_checks, *command_checks)
            )
            criterion["declared_is_complete"] = declared_complete
            criterion["evidence_verification"] = {
                "verified": structurally_verified,
                "paths": evidence_checks,
                "commands": command_checks,
            }
            criterion["is_complete"] = declared_complete and structurally_verified
            if not structurally_verified:
                structural_failures.append(
                    {"audit": audit["key"], "criterion": criterion["key"]}
                )

        audit["completed_count"] = sum(
            1 for criterion in audit["criteria"] if criterion["is_complete"]
        )
        audit["is_complete"] = (
            audit["required_count"] > 0
            and audit["completed_count"] == audit["required_count"]
        )

    test_reports = {
        "backend": _verify_junit_report(backend_junit),
        "frontend": _verify_junit_report(frontend_junit),
    }
    supplied_reports = [
        report for report in test_reports.values() if report["status"] != "not_supplied"
    ]
    test_reports_verified = bool(supplied_reports) and all(
        report["verified"] for report in supplied_reports
    )
    structural_verified = not structural_failures
    verified["verification"] = {
        "schema_version": "karkinos.acceptance_evidence_verification.v1",
        "level": "ci_test_reports" if supplied_reports else "repository_structure",
        "structural_verified": structural_verified,
        "structural_failures": structural_failures,
        "test_reports_verified": test_reports_verified,
        "test_reports": test_reports,
    }
    verified["overall_is_complete"] = structural_verified and all(
        audit["is_complete"] for audit in verified["audits"]
    )
    if supplied_reports:
        verified["overall_is_complete"] = (
            verified["overall_is_complete"] and test_reports_verified
        )
    return verified


def _verify_evidence_path(root: Path, declared_path: str) -> dict[str, Any]:
    candidate = (root / declared_path).resolve()
    inside_repo = candidate == root or root in candidate.parents
    exists = inside_repo and candidate.exists()
    return {
        "path": declared_path,
        "inside_repository": inside_repo,
        "exists": exists,
        "verified": inside_repo and exists,
    }


def _verify_validation_command(command: str) -> dict[str, Any]:
    normalized = command.strip()
    supported = bool(normalized) and any(
        normalized == base or normalized.startswith(f"{base} ")
        for base in _SUPPORTED_COMMAND_BASES
    )
    return {
        "command": command,
        "supported": supported,
        "verified": supported,
    }


def _verify_junit_report(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "not_supplied", "verified": False}
    resolved = path.resolve()
    if not resolved.is_file():
        return {
            "status": "missing",
            "path": str(path),
            "verified": False,
        }

    try:
        root = ET.parse(resolved).getroot()
    except (ET.ParseError, OSError) as exc:
        return {
            "status": "invalid",
            "path": str(path),
            "error": type(exc).__name__,
            "verified": False,
        }

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
    skipped = sum(
        int(suite.attrib.get("skipped", suite.attrib.get("disabled", "0")))
        for suite in suites
    )
    verified = tests > 0 and failures == 0 and errors == 0
    return {
        "status": "passed" if verified else "failed",
        "path": str(path),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "verified": verified,
    }
