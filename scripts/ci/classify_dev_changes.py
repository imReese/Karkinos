"""Select incremental CI domains from an exact diff, broadening unknown scopes safely."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS = ("backend", "frontend", "trading", "dependencies", "docker", "workflow")
DOCUMENTATION_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "design.md",
    "scripts/release/BOOTSTRAP_INSTALLER.md",
}


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def changed_paths(root: Path, *, base: str, head: str) -> tuple[str, list[str]]:
    def commit(ref: str) -> str:
        return (
            _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
            .decode()
            .strip()
        )

    base_sha, head_sha = commit(base), commit(head)
    if commit("HEAD") != head_sha:
        raise ValueError("classification_head_does_not_match_checkout")
    _git(root, "merge-base", "--is-ancestor", base_sha, head_sha)
    paths = _git(root, "diff", "--no-renames", "--name-only", "-z", base_sha, head_sha)
    return base_sha, [path.decode("utf-8") for path in paths.split(b"\0") if path]


def classify_paths(root: Path, paths: list[str]) -> dict[str, bool]:
    """Classify by product domain; never maintain a source-to-test selector graph."""

    checks = dict.fromkeys(CHECKS, False)
    for path in paths:
        name = PurePosixPath(path)
        if name.is_absolute() or ".." in name.parts or not name.parts:
            raise ValueError("invalid_changed_path")

        if (
            path == "LICENSE"
            or path in DOCUMENTATION_FILES
            or name.name == "README.md"
            or (path.startswith("docs/") and name.suffix == ".md")
        ):
            continue

        if path.startswith(".github/workflows/"):
            return dict.fromkeys(CHECKS, True)

        if path == ".github/dependabot.yml":
            checks["dependencies"] = True
            checks["workflow"] = True
            continue

        if path.startswith("web/"):
            checks["frontend"] = True
            if path in {"web/package.json", "web/package-lock.json"}:
                checks["dependencies"] = True
            continue

        if name.suffix == ".py" and not path.startswith("scripts/ci/"):
            checks["backend"] = True
            checks["trading"] = True
            if path.startswith("server/"):
                checks["docker"] = True
            continue

        if path in {"pyproject.toml", "uv.lock"}:
            checks["backend"] = True
            checks["trading"] = True
            checks["dependencies"] = True
            checks["docker"] = True
            continue

        if path == "Dockerfile" or path == ".dockerignore":
            checks["docker"] = True
            continue

        # Runtime/configuration, CI helpers, shared fixtures, deletions, and new
        # file types have no proven narrow impact boundary. Fail safe by running
        # every incremental domain instead of maintaining a brittle selector map.
        return dict.fromkeys(CHECKS, True)

    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        base_sha, paths = changed_paths(REPO_ROOT, base=args.base, head=args.head)
        scope = {"base_sha": base_sha, **classify_paths(REPO_ROOT, paths)}
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as output:
                for key, value in scope.items():
                    encoded = value if isinstance(value, str) else json.dumps(value)
                    output.write(f"{key}={encoded}\n")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Cannot establish dev check scope: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(scope, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
