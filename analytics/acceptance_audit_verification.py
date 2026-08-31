"""Verify acceptance manifests against repository and CI test evidence."""

from __future__ import annotations

import copy
import hashlib
import re
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_SUPPORTED_COMMAND_BASES = (
    "git ls-files",
    "npm --prefix web",
    "rg -n",
    "uv run pytest",
    "uv run python -m pytest",
    "uv run python scripts/ci/export_acceptance_audit.py",
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

    test_reports = {
        "backend": _verify_junit_report(backend_junit),
        "frontend": _verify_junit_report(frontend_junit),
    }
    required_report_kinds: set[str] = set()
    test_evidence_failures: list[dict[str, Any]] = []

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
            test_evidence = _verify_criterion_test_evidence(
                criterion["validation_commands"],
                test_reports=test_reports,
            )
            required_report_kinds.update(test_evidence["required_report_kinds"])
            criterion["declared_is_complete"] = declared_complete
            criterion["evidence_verification"] = {
                "verified": structurally_verified,
                "paths": evidence_checks,
                "commands": command_checks,
            }
            criterion["test_evidence_verification"] = test_evidence
            criterion["is_complete"] = (
                declared_complete
                and structurally_verified
                and test_evidence["verified"]
            )
            if not structurally_verified:
                structural_failures.append(
                    {"audit": audit["key"], "criterion": criterion["key"]}
                )
            if not test_evidence["verified"]:
                test_evidence_failures.append(
                    {
                        "audit": audit["key"],
                        "criterion": criterion["key"],
                        "required_report_kinds": test_evidence["required_report_kinds"],
                    }
                )

        audit["completed_count"] = sum(
            1 for criterion in audit["criteria"] if criterion["is_complete"]
        )
        audit["is_complete"] = (
            audit["required_count"] > 0
            and audit["completed_count"] == audit["required_count"]
        )

    supplied_report_kinds = {
        kind
        for kind, report in test_reports.items()
        if report["status"] != "not_supplied"
    }
    test_reports_verified = required_report_kinds.issubset(
        supplied_report_kinds
    ) and all(test_reports[kind]["verified"] for kind in required_report_kinds)
    structural_verified = not structural_failures
    public_test_reports = {
        kind: {key: value for key, value in report.items() if key != "_testcases"}
        for kind, report in test_reports.items()
    }
    verified["verification"] = {
        "schema_version": "karkinos.acceptance_evidence_verification.v2",
        "level": (
            "ci_test_reports" if supplied_report_kinds else "repository_structure"
        ),
        "structural_verified": structural_verified,
        "structural_failures": structural_failures,
        "test_reports_verified": test_reports_verified,
        "required_report_kinds": sorted(required_report_kinds),
        "test_evidence_failures": test_evidence_failures,
        "test_reports": public_test_reports,
    }
    verified["overall_is_complete"] = (
        structural_verified
        and test_reports_verified
        and all(audit["is_complete"] for audit in verified["audits"])
    )
    return verified


def _verify_criterion_test_evidence(
    commands: list[str],
    *,
    test_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    bindings: list[dict[str, Any]] = []
    for command in commands:
        report_kind = _test_report_kind(command)
        if report_kind is None:
            continue
        selectors = _test_selectors(command, report_kind=report_kind)
        report = test_reports[report_kind]
        matches = [
            _matching_testcases(selector, report.get("_testcases", ()))
            for selector in selectors
        ]
        name_pattern = _test_name_pattern(command, report_kind=report_kind)
        name_pattern_branches = (
            _test_name_pattern_branches(name_pattern, report_kind=report_kind)
            if name_pattern is not None
            else None
        )
        branch_name_matches = (
            [
                _matching_name_testcases(
                    selectors,
                    branch,
                    report_kind=report_kind,
                    testcases=report.get("_testcases", ()),
                )
                for branch in name_pattern_branches
            ]
            if name_pattern_branches is not None
            else []
        )
        name_matches = sorted(
            {
                match
                for branch_matches in branch_name_matches
                for match in branch_matches
            }
        )
        verified = (
            bool(report["verified"])
            and bool(selectors)
            and all(matches)
            and (
                name_pattern is None
                or (bool(name_pattern_branches) and all(branch_name_matches))
            )
        )
        bindings.append(
            {
                "command": command,
                "report_kind": report_kind,
                "selectors": selectors,
                "matched_testcase_counts": [len(items) for items in matches],
                "name_pattern": name_pattern,
                "name_pattern_branches": name_pattern_branches or [],
                "matched_name_testcase_counts": [
                    len(items) for items in branch_name_matches
                ],
                "matched_name_testcase_count": len(name_matches),
                "verified": verified,
            }
        )

    return {
        "verified": not bindings or all(binding["verified"] for binding in bindings),
        "required_report_kinds": sorted(
            {binding["report_kind"] for binding in bindings}
        ),
        "bindings": bindings,
    }


def _test_report_kind(command: str) -> str | None:
    normalized = command.strip()
    if normalized.startswith(("uv run pytest", "uv run python -m pytest")):
        return "backend"
    if normalized.startswith("npm --prefix web") and " test" in normalized:
        return "frontend"
    return None


def _test_selectors(command: str, *, report_kind: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if report_kind == "backend":
        backend_selectors = [
            token for token in tokens if token == "tests" or token.startswith("tests/")
        ]
        return list(dict.fromkeys(backend_selectors)) or ["backend-full-suite"]

    if "--" not in tokens:
        return ["web-full-suite"]
    tail = tokens[tokens.index("--") + 1 :]
    frontend_selectors: list[str] = []
    skip_next = False
    for token in tail:
        if skip_next:
            skip_next = False
            continue
        if token in {"-t", "--testNamePattern", "--reporter", "--outputFile"}:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        frontend_selectors.append(token)
    return list(dict.fromkeys(frontend_selectors)) or ["web-full-suite"]


def _matching_testcases(
    selector: str,
    testcases: tuple[dict[str, str], ...],
) -> list[str]:
    testcases = tuple(case for case in testcases if case["status"] == "passed")
    if selector == "backend-full-suite":
        return [f"{case['classname']}::{case['name']}" for case in testcases]
    if selector == "web-full-suite":
        return [
            f"{case['classname']}::{case['name']}"
            for case in testcases
            if case["classname"].startswith("src/")
        ]
    if selector == "tests":
        return [
            f"{case['classname']}::{case['name']}"
            for case in testcases
            if case["classname"].startswith("tests.")
        ]

    path_selector, separator, node_selector = selector.partition("::")
    if path_selector.endswith(".py") or path_selector.startswith("tests/"):
        module_selector = path_selector.removesuffix(".py").replace("/", ".")
        matches = [
            case
            for case in testcases
            if case["classname"] == module_selector
            or case["classname"].startswith(f"{module_selector}.")
        ]
        if separator:
            node_name = node_selector.split("[")[0]
            matches = [
                case
                for case in matches
                if node_name in case["name"]
                or node_name in f"{case['classname']}::{case['name']}"
            ]
    else:
        normalized = path_selector.removeprefix("web/")
        matches = [
            case
            for case in testcases
            if normalized in case["classname"] or normalized in case["name"]
        ]
    return [f"{case['classname']}::{case['name']}" for case in matches]


def _test_name_pattern(command: str, *, report_kind: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    names = (
        ("-k", "--keyword")
        if report_kind == "backend"
        else (
            "-t",
            "--testNamePattern",
        )
    )
    for index, token in enumerate(tokens):
        for name in names:
            if token == name:
                return tokens[index + 1] if index + 1 < len(tokens) else ""
            if token.startswith(f"{name}="):
                return token.split("=", 1)[1]
    return None


def _matching_name_testcases(
    selectors: list[str],
    pattern: str,
    *,
    report_kind: str,
    testcases: tuple[dict[str, str], ...],
) -> list[str]:
    eligible = {
        match
        for selector in selectors
        for match in _matching_testcases(selector, testcases)
    }
    matched: list[str] = []
    for case in testcases:
        identity = f"{case['classname']}::{case['name']}"
        if identity not in eligible:
            continue
        candidate = identity if report_kind == "backend" else case["name"]
        if pattern.casefold() in candidate.casefold():
            matched.append(identity)
    return sorted(matched)


def _test_name_pattern_branches(
    pattern: str,
    *,
    report_kind: str,
) -> list[str] | None:
    normalized = pattern.strip()
    if not normalized:
        return None
    if report_kind == "backend":
        branches = re.split(r"\s+or\s+", normalized, flags=re.IGNORECASE)
        if not all(re.fullmatch(r"[A-Za-z0-9_]+", branch) for branch in branches):
            return None
    else:
        branches = [branch.strip() for branch in normalized.split("|")]
        unsafe_characters = frozenset(".^$*+?{}[]()\\")
        if not all(
            branch and not any(char in unsafe_characters for char in branch)
            for branch in branches
        ):
            return None
    return list(dict.fromkeys(branches))


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
    testcases = tuple(
        {
            "classname": str(case.attrib.get("classname") or ""),
            "name": str(case.attrib.get("name") or ""),
            "status": _testcase_status(case),
        }
        for case in root.iter("testcase")
        if case.attrib.get("classname") and case.attrib.get("name")
    )
    passed_testcase_count = sum(case["status"] == "passed" for case in testcases)
    testcase_failures = sum(case["status"] == "failed" for case in testcases)
    testcase_errors = sum(case["status"] == "error" for case in testcases)
    testcase_skipped = sum(case["status"] == "skipped" for case in testcases)
    counts_match_testcases = (
        tests == len(testcases)
        and failures == testcase_failures
        and errors == testcase_errors
        and skipped == testcase_skipped
    )
    verified = (
        tests > 0
        and passed_testcase_count > 0
        and counts_match_testcases
        and failures == 0
        and errors == 0
    )
    return {
        "status": "passed" if verified else "failed",
        "path": str(path),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "verified": verified,
        "testcase_count": len(testcases),
        "passed_testcase_count": passed_testcase_count,
        "counts_match_testcases": counts_match_testcases,
        "_testcases": testcases,
    }


def _testcase_status(case: ET.Element) -> str:
    if case.find("error") is not None:
        return "error"
    if case.find("failure") is not None:
        return "failed"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"
