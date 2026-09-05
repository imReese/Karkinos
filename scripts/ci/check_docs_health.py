"""Keep Karkinos documentation small, canonical, and link-safe."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CORE_DOC_BUDGETS = {
    "README.md": 180,
    "docs/README.md": 120,
    "docs/GOAL.md": 140,
    "docs/ARCHITECTURE.md": 400,
    "docs/PLAN.md": 460,
    "docs/CODEBASE.md": 180,
    "design.md": 240,
    "AI_COLLABORATION.md": 180,
    "AGENTS.md": 80,
    "CLAUDE.md": 80,
}

COMPATIBILITY_STUB_BUDGETS = {
    "docs/README.zh.md": 12,
    "docs/README.en.md": 12,
    "docs/KARKINOS_GOAL.md": 12,
    "docs/KARKINOS_GOAL.zh.md": 12,
    "docs/ROADMAP.md": 12,
    "docs/ROADMAP.zh.md": 12,
    "docs/ARCHITECTURE.zh.md": 12,
    "docs/IMPLEMENTATION_LOG.md": 12,
    "docs/IMPLEMENTATION_LOG.zh.md": 12,
    "docs/CONTROLLED_EXECUTION_PLAN.md": 12,
    "docs/CONTROLLED_EXECUTION_PLAN.zh.md": 12,
    "docs/config-reference.en.md": 12,
    "docs/return-accounting.en.md": 12,
    "docs/account-truth-import.en.md": 12,
    "docs/strategy/README.en.md": 12,
}

MAINTENANCE_DOC_BUDGETS = {
    "docs/account-truth-import.zh.md": 100,
    "docs/strategy/README.zh.md": 100,
}

FROZEN_REFERENCE_STUB_BUDGETS = {
    "docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md": 14,
    "docs/broker-adapter-conformance.en.md": 14,
    "docs/broker-adapter-conformance.zh.md": 14,
    "docs/broker-adapter-release-review.en.md": 14,
    "docs/broker-adapter-release-review.zh.md": 14,
    "docs/broker-execution-edge-conformance.en.md": 14,
    "docs/broker-execution-edge-conformance.zh.md": 14,
    "docs/broker-order-lifecycle-ingestion.en.md": 14,
    "docs/broker-order-lifecycle-ingestion.zh.md": 14,
    "docs/controlled-broker-cancellation.en.md": 14,
    "docs/controlled-broker-cancellation.zh.md": 14,
    "docs/operator-approval-signing.md": 14,
    "docs/operator-approval-signing.zh.md": 14,
    "docs/qmt-order-lifecycle-import.zh.md": 14,
}

REMOVED_TOP_LEVEL_DOCS = (
    "docs/AI_STRATEGY_RESEARCH_DESIGN.zh.md",
    "docs/BENCHMARKS.md",
    "docs/BENCHMARKS.zh.md",
    "docs/DAILY_CANDIDATE_PRODUCTION_RUNBOOK.md",
    "docs/DAILY_CANDIDATE_PRODUCTION_RUNBOOK.zh.md",
    "docs/PROFIT_ENGINE_PLAN.zh.md",
)

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _check_document(path_text: str, line_budget: int) -> list[str]:
    path = REPO_ROOT / path_text
    if not path.is_file():
        return [f"missing documentation file: {path_text}"]

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    line_count = len(text.splitlines())
    if line_count > line_budget:
        errors.append(
            f"{path_text} has {line_count} lines; documentation budget is {line_budget}"
        )

    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.strip().split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        target = target.split(" ", 1)[0]
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(REPO_ROOT)
        except ValueError:
            errors.append(f"{path_text} links outside the repository: {raw_target}")
            continue
        if not resolved.exists():
            errors.append(f"{path_text} has a broken local link: {raw_target}")

    return errors


def _check_removed_docs_stay_removed() -> list[str]:
    return [
        f"superseded top-level document returned: {path_text}"
        for path_text in REMOVED_TOP_LEVEL_DOCS
        if (REPO_ROOT / path_text).exists()
    ]


def _check_tests_do_not_parse_plan() -> list[str]:
    errors: list[str] = []
    tests_root = REPO_ROOT / "tests"
    for path in tests_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "docs/PLAN.md" in text and "read_text" in text:
            errors.append(
                f"{path.relative_to(REPO_ROOT)} parses PLAN prose; use executable "
                "acceptance contracts instead"
            )
    return errors


def main() -> int:
    errors: list[str] = []
    budgets = {
        **CORE_DOC_BUDGETS,
        **COMPATIBILITY_STUB_BUDGETS,
        **MAINTENANCE_DOC_BUDGETS,
        **FROZEN_REFERENCE_STUB_BUDGETS,
    }
    for path_text, line_budget in budgets.items():
        errors.extend(_check_document(path_text, line_budget))
    errors.extend(_check_removed_docs_stay_removed())
    errors.extend(_check_tests_do_not_parse_plan())

    if errors:
        print("Documentation health check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "Documentation health check passed: canonical docs are bounded, frozen "
        "references stay small, local links resolve, and superseded master docs "
        "stay removed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
