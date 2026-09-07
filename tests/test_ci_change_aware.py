from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/ci.yml")


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_docs_only_classifier_is_narrow_and_main_stays_full() -> None:
    workflow = _workflow()

    assert "name: Change classification" in workflow
    assert "git diff --name-only" in workflow
    assert "*.md|docs/*|AGENTS.md|CLAUDE.md|LICENSE" in workflow
    assert 'GITHUB_REF}" == "refs/heads/main"' in workflow
    assert 'GITHUB_EVENT_NAME}" == "workflow_dispatch"' in workflow
    assert "docs_only=false" in workflow


def test_heavy_jobs_skip_only_for_docs_only_changes() -> None:
    workflow = _workflow()

    for job in (
        "backend",
        "dependency-audit",
        "trading-safety",
        "frontend",
        "docker-runtime",
        "browser-safety",
    ):
        block = workflow.split(f"  {job}:\n", 1)[1].split("\n  ", 1)[0]
        assert "if: ${{ needs.changes.outputs.docs_only != 'true' }}" in block
        assert "changes" in block.split("needs:", 1)[1].split("\n", 1)[0]


def test_docs_only_acceptance_does_not_forge_test_evidence() -> None:
    workflow = _workflow()
    block = workflow.split("  repository-acceptance-audit:\n", 1)[1].split(
        "\n  secret-scan:\n", 1
    )[0]

    assert "Run repository acceptance audit report for docs-only changes" in block
    assert "Run repository acceptance audit report with test evidence" in block
    docs_step = block.split(
        "      - name: Run repository acceptance audit report for docs-only changes\n",
        1,
    )[1].split(
        "      - name: Run repository acceptance audit report with test evidence\n",
        1,
    )[0]
    full_step = block.split(
        "      - name: Run repository acceptance audit report with test evidence\n",
        1,
    )[1].split("      - name: Upload acceptance evidence\n", 1)[0]
    assert "--verify-evidence" not in docs_step
    assert "--backend-junit" not in docs_step
    assert "--frontend-junit" not in docs_step
    assert "--verify-evidence" in full_step
    assert "--backend-junit" in full_step
    assert "--frontend-junit" in full_step


def test_code_gate_allows_heavy_skips_only_when_classifier_says_docs_only() -> None:
    workflow = _workflow()
    block = workflow.split("  code-ci-gate:\n", 1)[1]

    assert 'docs_only = outputs.get("docs_only") == "true"' in block
    assert 'if docs_only and name in skippable_for_docs:' in block
    assert 'result not in {"success", "skipped"}' in block
    assert 'elif result != "success":' in block
    assert '"repository-acceptance-audit"' not in block.split(
        "skippable_for_docs = {", 1
    )[1].split("}", 1)[0]
