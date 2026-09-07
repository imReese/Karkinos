"""Run the same incremental Python quality checks locally and in CI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_TIMEOUT_SECONDS = 300


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _commit(root: Path, ref: str) -> str:
    return (
        _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        .decode()
        .strip()
    )


def python_files(root: Path, *, base: str | None, head: str | None) -> list[str]:
    """Use NUL-delimited paths; a bad revision must never mean an empty diff.

    An explicit head checks a committed CI snapshot. Without it, include local
    staged, unstaged and untracked Python changes. A missing/zero base checks
    every tracked Python file, including files introduced by the root commit.
    """
    head_sha = _commit(root, head) if head else None
    if head_sha and _commit(root, "HEAD") != head_sha:
        raise ValueError("quality_head_does_not_match_checkout")
    if not base or base == "0" * 40:
        if head_sha:
            raw = _git(root, "ls-tree", "-r", "--name-only", "-z", head_sha)
        else:
            raw = _git(root, "ls-files", "--cached", "-z")
    else:
        refs = [_commit(root, base)]
        if head_sha:
            refs.append(head_sha)
        raw = _git(root, "diff", "--name-only", "--diff-filter=ACMR", "-z", *refs)
    if not head_sha:
        raw += _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    paths = {path.decode("utf-8") for path in raw.split(b"\0") if path}
    return sorted(
        path
        for path in paths
        if path.endswith(".py") and (head_sha is not None or (root / path).is_file())
    )


def run_checks(root: Path, files: list[str]) -> int:
    """Report all independent failures without weakening the aggregate exit code."""
    python = sys.executable
    checks = []
    if files:
        checks.extend(
            [
                ("Ruff", [python, "-m", "ruff", "check", "--", *files]),
                ("Black", [python, "-m", "black", "--check", "--diff", "--", *files]),
                (
                    "isort",
                    [python, "-m", "isort", "--check-only", "--diff", "--", *files],
                ),
            ]
        )
    else:
        print("No changed Python files; stable boundary checks still run.", flush=True)
    checks.extend(
        [
            ("mypy", [python, "-m", "mypy"]),
            ("Architecture", [python, "tools/check_python_architecture.py"]),
        ]
    )
    results = []
    for name, command in checks:
        print(f"::group::{name}", flush=True)
        try:
            result = subprocess.run(
                command, cwd=root, check=False, timeout=CHECK_TIMEOUT_SECONDS
            )
            passed = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"{name} could not complete: {exc}", file=sys.stderr, flush=True)
            passed = False
        finally:
            print("::endgroup::", flush=True)
        results.append((name, passed))
    print("Python quality summary:", flush=True)
    for name, passed in results:
        print(f"  {name}: {'PASS' if passed else 'FAIL'}", flush=True)
    return int(any(not passed for _, passed in results))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Base revision; omit to check all Python files")
    parser.add_argument("--head", help="Exact CI checkout; omit for local changes")
    args = parser.parse_args(argv)
    try:
        files = python_files(REPO_ROOT, base=args.base, head=args.head)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Cannot establish Python check scope: {exc}", file=sys.stderr)
        return 1
    return run_checks(REPO_ROOT, files)


if __name__ == "__main__":
    raise SystemExit(main())
