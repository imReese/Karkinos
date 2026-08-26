from __future__ import annotations

from pathlib import Path

import pytest

from analytics.acceptance_audit_report import build_acceptance_audit_export
from analytics.acceptance_audit_verification import verify_acceptance_audit_export


def _write_junit(
    path: Path,
    *,
    testcases: list[tuple[str, str]],
    failures: int = 0,
) -> None:
    cases = "".join(
        f'<testcase classname="{classname}" name="{name}" />'
        for classname, name in testcases
    )
    path.write_text(
        (
            f'<testsuite tests="{len(testcases)}" failures="{failures}" '
            f'errors="0" skipped="0">{cases}</testsuite>'
        ),
        encoding="utf-8",
    )


def _payload_for_test_command(command: str) -> dict[str, object]:
    return {
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
                        "validation_commands": [command],
                        "is_complete": True,
                    }
                ],
                "limitations": [],
            }
        ],
    }


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

    assert verified["overall_is_complete"] is False
    assert verified["verification"]["level"] == "repository_structure"
    assert verified["verification"]["structural_verified"] is True
    assert verified["verification"]["test_reports_verified"] is False
    criterion = verified["audits"][0]["criteria"][0]
    assert criterion["declared_is_complete"] is True
    assert criterion["evidence_verification"]["verified"] is True
    assert criterion["test_evidence_verification"]["verified"] is False


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
    _write_junit(
        backend,
        testcases=[("tests.test_backend", "test_safe")],
    )
    _write_junit(
        frontend,
        testcases=[("src/features/safe.test.tsx", "renders safely")],
        failures=1,
    )
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
                        "validation_commands": [
                            "npm --prefix web test -- safe.test.tsx"
                        ],
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


def test_ci_evidence_requires_each_report_and_matching_testcase_selector(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.py"
    evidence.write_text("# evidence\n", encoding="utf-8")
    backend = tmp_path / "backend.xml"
    unrelated_frontend = tmp_path / "unrelated-frontend.xml"
    matching_frontend = tmp_path / "matching-frontend.xml"
    _write_junit(
        backend,
        testcases=[("tests.test_backend_contract", "test_safe_default")],
    )
    _write_junit(
        unrelated_frontend,
        testcases=[("src/features/unrelated.test.tsx", "unrelated")],
    )
    _write_junit(
        matching_frontend,
        testcases=[("src/features/activity/api.test.tsx", "reuses request id")],
    )
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
                        "validation_commands": [
                            "uv run python -m pytest tests/test_backend_contract.py",
                            "npm --prefix web test -- activity/api.test.tsx "
                            "-t 'reuses request id'",
                        ],
                        "is_complete": True,
                    }
                ],
                "limitations": [],
            }
        ],
    }

    backend_only = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
    )
    unrelated = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
        frontend_junit=unrelated_frontend,
    )
    matched = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
        frontend_junit=matching_frontend,
    )

    assert backend_only["overall_is_complete"] is False
    assert backend_only["verification"]["required_report_kinds"] == [
        "backend",
        "frontend",
    ]
    assert unrelated["overall_is_complete"] is False
    assert unrelated["verification"]["test_reports_verified"] is True
    assert unrelated["audits"][0]["criteria"][0]["is_complete"] is False
    assert matched["overall_is_complete"] is True
    bindings = matched["audits"][0]["criteria"][0]["test_evidence_verification"][
        "bindings"
    ]
    assert [binding["matched_testcase_counts"] for binding in bindings] == [[1], [1]]


def test_aggregate_only_junit_cannot_verify_any_test_command(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.py"
    evidence.write_text("# evidence\n", encoding="utf-8")
    aggregate = tmp_path / "aggregate.xml"
    aggregate.write_text(
        '<testsuite tests="397" failures="0" errors="0" skipped="0" />',
        encoding="utf-8",
    )
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
                        "validation_commands": [
                            "uv run python -m pytest tests/test_backend_contract.py"
                        ],
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
        backend_junit=aggregate,
    )

    assert verified["overall_is_complete"] is False
    assert verified["verification"]["test_reports"]["backend"]["verified"] is False


@pytest.mark.parametrize(
    ("case_result", "skipped_count", "counts_match"),
    [
        ("<skipped />", 1, True),
        ("<failure />", 0, False),
    ],
)
def test_nonpassing_testcase_cannot_verify_declared_test_evidence(
    tmp_path: Path,
    case_result: str,
    skipped_count: int,
    counts_match: bool,
) -> None:
    evidence = tmp_path / "evidence.py"
    evidence.write_text("# evidence\n", encoding="utf-8")
    backend = tmp_path / "backend.xml"
    backend.write_text(
        (
            f'<testsuite tests="1" failures="0" errors="0" skipped="{skipped_count}">'
            '<testcase classname="tests.test_backend_contract" name="test_required">'
            f"{case_result}"
            "</testcase></testsuite>"
        ),
        encoding="utf-8",
    )
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
                        "validation_commands": [
                            "uv run python -m pytest tests/test_backend_contract.py"
                        ],
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
    )

    assert verified["overall_is_complete"] is False
    assert verified["verification"]["test_reports"]["backend"]["verified"] is False
    assert (
        verified["verification"]["test_reports"]["backend"]["passed_testcase_count"]
        == 0
    )
    assert (
        verified["verification"]["test_reports"]["backend"]["counts_match_testcases"]
        is counts_match
    )


def test_pytest_keyword_must_match_a_passing_testcase_in_declared_path(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.py"
    evidence.write_text("# evidence\n", encoding="utf-8")
    backend = tmp_path / "backend.xml"
    _write_junit(
        backend,
        testcases=[("tests.test_backend_contract", "test_unrelated")],
    )
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
                        "validation_commands": [
                            "uv run python -m pytest tests/test_backend_contract.py "
                            "-k must_be_this_test"
                        ],
                        "is_complete": True,
                    }
                ],
                "limitations": [],
            }
        ],
    }

    unrelated = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
    )
    _write_junit(
        backend,
        testcases=[("tests.test_backend_contract", "test_must_be_this_test")],
    )
    matched = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
    )

    assert unrelated["overall_is_complete"] is False
    assert matched["overall_is_complete"] is True
    binding = matched["audits"][0]["criteria"][0]["test_evidence_verification"][
        "bindings"
    ][0]
    assert binding["name_pattern"] == "must_be_this_test"
    assert binding["matched_name_testcase_count"] == 1


def test_backend_full_suite_command_binds_to_nonempty_passing_report(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.py"
    evidence.write_text("# evidence\n", encoding="utf-8")
    backend = tmp_path / "backend.xml"
    _write_junit(backend, testcases=[("tests.test_backend", "test_passes")])
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
                        "key": "full_suite",
                        "checkbox_text": "full suite",
                        "evidence_paths": ["evidence.py"],
                        "validation_commands": ["uv run python -m pytest"],
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
    )

    assert verified["overall_is_complete"] is True
    binding = verified["audits"][0]["criteria"][0]["test_evidence_verification"][
        "bindings"
    ][0]
    assert binding["selectors"] == ["backend-full-suite"]


def test_pytest_simple_or_requires_a_passing_testcase_for_every_branch(
    tmp_path: Path,
) -> None:
    (tmp_path / "evidence.py").write_text("# evidence\n", encoding="utf-8")
    backend = tmp_path / "backend.xml"
    payload = _payload_for_test_command(
        "uv run pytest tests/test_submission.py "
        "-k 'signed_submit or explicit_rejection or unknown_submit'"
    )
    _write_junit(
        backend,
        testcases=[("tests.test_submission", "test_signed_submit")],
    )

    incomplete = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
    )
    incomplete_binding = incomplete["audits"][0]["criteria"][0][
        "test_evidence_verification"
    ]["bindings"][0]

    assert incomplete["overall_is_complete"] is False
    assert incomplete_binding["name_pattern_branches"] == [
        "signed_submit",
        "explicit_rejection",
        "unknown_submit",
    ]
    assert incomplete_binding["matched_name_testcase_counts"] == [1, 0, 0]

    _write_junit(
        backend,
        testcases=[
            ("tests.test_submission", "test_signed_submit"),
            ("tests.test_submission", "test_explicit_rejection"),
            ("tests.test_submission", "test_unknown_submit"),
        ],
    )
    complete = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        backend_junit=backend,
    )

    assert complete["overall_is_complete"] is True


def test_frontend_simple_alternation_requires_each_passing_testcase_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "evidence.py").write_text("# evidence\n", encoding="utf-8")
    frontend = tmp_path / "frontend.xml"
    payload = _payload_for_test_command(
        "npm --prefix web test -- trading.test.tsx "
        "-t 'exports confirmed ticket|shows reconciliation'"
    )
    _write_junit(
        frontend,
        testcases=[
            ("src/features/trading.test.tsx", "exports confirmed ticket"),
        ],
    )

    incomplete = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        frontend_junit=frontend,
    )
    incomplete_binding = incomplete["audits"][0]["criteria"][0][
        "test_evidence_verification"
    ]["bindings"][0]

    assert incomplete["overall_is_complete"] is False
    assert incomplete_binding["name_pattern_branches"] == [
        "exports confirmed ticket",
        "shows reconciliation",
    ]
    assert incomplete_binding["matched_name_testcase_counts"] == [1, 0]

    _write_junit(
        frontend,
        testcases=[
            ("src/features/trading.test.tsx", "exports confirmed ticket"),
            ("src/features/trading.test.tsx", "shows reconciliation"),
        ],
    )
    complete = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        frontend_junit=frontend,
    )

    assert complete["overall_is_complete"] is True


@pytest.mark.parametrize(
    ("command", "report_kind", "testcase"),
    [
        (
            "uv run pytest tests/test_contract.py -k 'safe and unsafe'",
            "backend",
            ("tests.test_contract", "test_safe_and_unsafe"),
        ),
        (
            "npm --prefix web test -- contract.test.tsx -t 'safe.*unsafe'",
            "frontend",
            ("src/contract.test.tsx", "safe and unsafe"),
        ),
    ],
)
def test_unparsed_test_name_expressions_fail_closed(
    tmp_path: Path,
    command: str,
    report_kind: str,
    testcase: tuple[str, str],
) -> None:
    (tmp_path / "evidence.py").write_text("# evidence\n", encoding="utf-8")
    report = tmp_path / f"{report_kind}.xml"
    _write_junit(report, testcases=[testcase])
    payload = _payload_for_test_command(command)
    kwargs = {f"{report_kind}_junit": report}

    verified = verify_acceptance_audit_export(
        payload,
        repo_root=tmp_path,
        **kwargs,
    )
    binding = verified["audits"][0]["criteria"][0]["test_evidence_verification"][
        "bindings"
    ][0]

    assert verified["overall_is_complete"] is False
    assert binding["name_pattern_branches"] == []
    assert binding["verified"] is False
