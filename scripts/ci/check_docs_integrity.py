"""Check that maintained Karkinos documentation is present and navigable."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CANONICAL_DOCS = (
    "docs/README.md",
    "docs/GOAL.md",
    "docs/ARCHITECTURE.md",
    "docs/PLAN.md",
    "docs/ENGINEERING.md",
    "docs/REFERENCES.md",
)

AGENT_ENTRYPOINTS = (
    "AGENTS.md",
    "CLAUDE.md",
)

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def tracked_markdown_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )

    return tuple(
        REPO_ROOT / path.decode("utf-8") for path in result.stdout.split(b"\0") if path
    )


def check_required_files() -> list[str]:
    errors: list[str] = []

    for path_text in (*CANONICAL_DOCS, *AGENT_ENTRYPOINTS):
        if not (REPO_ROOT / path_text).is_file():
            errors.append(f"missing documentation file: {path_text}")

    return errors


def check_local_links(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.strip().split("#", 1)[0]

        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue

        # Ignore optional Markdown link titles:
        # [label](path "title")
        target = target.split(" ", 1)[0].strip("<>")

        resolved = (path.parent / target).resolve()

        try:
            resolved.relative_to(REPO_ROOT)
        except ValueError:
            errors.append(
                f"{path.relative_to(REPO_ROOT)} links outside the repository: "
                f"{raw_target}"
            )
            continue

        if not resolved.exists():
            errors.append(
                f"{path.relative_to(REPO_ROOT)} has a broken local link: "
                f"{raw_target}"
            )

    return errors


def check_agent_routing() -> list[str]:
    agents_path = REPO_ROOT / "AGENTS.md"
    claude_path = REPO_ROOT / "CLAUDE.md"

    if not agents_path.is_file() or not claude_path.is_file():
        return []

    errors: list[str] = []

    agents = agents_path.read_text(encoding="utf-8")
    claude = claude_path.read_text(encoding="utf-8")

    for required in CANONICAL_DOCS:
        if required not in agents:
            errors.append(f"AGENTS.md must route agents to {required}")

    if "@AGENTS.md" not in claude:
        errors.append("CLAUDE.md must import AGENTS.md with @AGENTS.md")

    return errors


def main() -> int:
    errors = check_required_files()
    errors.extend(check_agent_routing())

    try:
        markdown_files = tracked_markdown_files()
    except subprocess.CalledProcessError as exc:
        print(f"Could not enumerate tracked Markdown files: {exc}")
        return 1

    for path in markdown_files:
        if path.is_file():
            errors.extend(check_local_links(path))

    if errors:
        print("Documentation integrity check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Documentation integrity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
