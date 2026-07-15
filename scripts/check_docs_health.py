"""Check stable documentation ownership without parsing prose as product state."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CORE_DOC_BUDGETS = {
    "README.md": 250,
    "docs/README.zh.md": 180,
    "docs/README.en.md": 180,
    "docs/KARKINOS_GOAL.md": 180,
    "docs/ROADMAP.md": 260,
    "docs/ROADMAP.zh.md": 240,
    "docs/ARCHITECTURE.md": 650,
    "docs/IMPLEMENTATION_LOG.md": 400,
    "docs/CONTROLLED_EXECUTION_PLAN.md": 350,
}

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _check_core_doc(path_text: str, line_budget: int) -> list[str]:
    path = REPO_ROOT / path_text
    if not path.is_file():
        return [f"missing core document: {path_text}"]

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    line_count = len(text.splitlines())
    if line_count > line_budget:
        errors.append(
            f"{path_text} has {line_count} lines; ownership budget is " f"{line_budget}"
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


def _check_tests_do_not_parse_roadmap() -> list[str]:
    errors: list[str] = []
    tests_root = REPO_ROOT / "tests"
    for path in tests_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "docs/ROADMAP.md" in text and "read_text" in text:
            errors.append(
                f"{path.relative_to(REPO_ROOT)} parses ROADMAP prose; "
                "use the acceptance registry instead"
            )
    return errors


def main() -> int:
    errors: list[str] = []
    for path_text, line_budget in CORE_DOC_BUDGETS.items():
        errors.extend(_check_core_doc(path_text, line_budget))
    errors.extend(_check_tests_do_not_parse_roadmap())

    if errors:
        print("Documentation health check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "Documentation health check passed: core ownership budgets, local "
        "links, and roadmap/test separation are valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
