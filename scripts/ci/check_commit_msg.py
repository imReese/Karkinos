#!/usr/bin/env python3
"""Check commit message conventions.

Enforces:
1. Conventional Commits format: `<type>(<scope>): <subject>` or `<type>: <subject>`
   Allowed types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert.
2. Max subject length: <= 72 characters (including type, scope, punctuation, spaces).
3. No project management, stage, milestone, or code review identifiers
   (e.g., P0-4C, Task A, CR #1, Checkpoint 1, Milestone 1).
4. Does not falsely flag legitimate technical terms (e.g., 'execution phase', 'stage').
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([a-zA-Z0-9_./-]+\))?"
    r"(!)?"
    r": "
    r"[a-z0-9].*$"
)

FORBIDDEN_LABELS_RE = re.compile(
    r"\b(P\d+-\d+[A-Za-z]?|CR\s*#?\d+|Task\s+[A-Za-z0-9]|Checkpoint\s*\d+|Milestone\s*\d+)\b",
    re.IGNORECASE,
)


def validate_commit_subject(subject: str) -> list[str]:
    """Validate a single commit subject line. Returns a list of error strings."""
    errors: list[str] = []
    clean = subject.strip()
    if not clean:
        errors.append("Commit subject cannot be empty.")
        return errors

    if len(clean) > 72:
        errors.append(
            f"Commit subject exceeds 72 characters ({len(clean)} > 72): {clean!r}"
        )

    if not clean.isascii():
        errors.append(
            f"Commit subject must be in English (ASCII characters only): {clean!r}"
        )

    if not CONVENTIONAL_COMMIT_RE.match(clean):
        errors.append(
            f"Commit subject does not follow Conventional Commits format '<type>(<scope>): <subject>' or '<type>: <subject>': {clean!r}"
        )

    forbidden_match = FORBIDDEN_LABELS_RE.search(clean)
    if forbidden_match:
        errors.append(
            f"Commit subject contains forbidden project management / review label {forbidden_match.group(0)!r}: {clean!r}"
        )

    return errors


def extract_subject_from_message(content: str) -> str:
    """Extract first non-comment line from a commit message."""
    for line in content.splitlines():
        trimmed = line.strip()
        if trimmed and not trimmed.startswith("#"):
            return trimmed
    return ""


def check_commit_range(base_sha: str, head_sha: str) -> int:
    """Validate all commits in the range base_sha..head_sha."""
    cmd = ["git", "log", "--format=%H %s", f"{base_sha}..{head_sha}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"Error running git log: {exc.stderr}\n")
        return 1

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return 0

    has_errors = False
    for line in lines:
        parts = line.split(" ", 1)
        sha = parts[0]
        subject = parts[1] if len(parts) > 1 else ""
        errors = validate_commit_subject(subject)
        if errors:
            has_errors = True
            sys.stderr.write(
                f"\n[INVALID COMMIT MESSAGE] Commit {sha[:8]}: {subject}\n"
            )
            for err in errors:
                sys.stderr.write(f"  - {err}\n")

    return 1 if has_errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check commit message conventions.")
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="Path to commit message file (e.g. .git/COMMIT_EDITMSG).",
    )
    parser.add_argument(
        "--range",
        nargs=2,
        metavar=("BASE", "HEAD"),
        help="Validate all commits in git rev range BASE..HEAD.",
    )

    args = parser.parse_args(argv)

    if args.range:
        base_sha, head_sha = args.range
        return check_commit_range(base_sha, head_sha)

    if args.file:
        if not args.file.is_file():
            sys.stderr.write(f"Error: Commit message file '{args.file}' not found.\n")
            return 1
        content = args.file.read_text(encoding="utf-8")
        subject = extract_subject_from_message(content)
        errors = validate_commit_subject(subject)
        if errors:
            sys.stderr.write("\n[INVALID COMMIT MESSAGE]\n")
            for err in errors:
                sys.stderr.write(f"  - {err}\n")
            sys.stderr.write(
                "\nConventions:\n"
                "  1. Conventional Commits: <type>(<scope>): <subject> or <type>: <subject>\n"
                "     Allowed types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert\n"
                "  2. Total first line length <= 72 characters.\n"
                "  3. No task / review / stage identifiers (e.g. P0-4C, Task A, CR #1).\n"
            )
            return 1
        return 0

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
