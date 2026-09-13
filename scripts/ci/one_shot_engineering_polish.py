from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, got {count}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, *, minimum: int = 1) -> int:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"{path}: expected at least {minimum} matches, got {count}: {old[:80]!r}")
    file.write_text(text.replace(old, new), encoding="utf-8")
    return count


# 1. Make product design a canonical document under docs/.
source = ROOT / "design.md"
target = ROOT / "docs/PRODUCT_DESIGN.md"
if not source.is_file() or target.exists():
    raise SystemExit("unexpected product design paths")
subprocess.run(["git", "mv", "design.md", "docs/PRODUCT_DESIGN.md"], cwd=ROOT, check=True)
replace_once(
    "docs/PRODUCT_DESIGN.md",
    "`design.md` is the product-level contract.",
    "`PRODUCT_DESIGN.md` is the product-level contract.",
)
replace_once(
    "docs/README.md",
    "| [ARCHITECTURE.md](ARCHITECTURE.md) | Domain ownership and system design |\n| [PLAN.md](PLAN.md) | Current development scope |",
    "| [ARCHITECTURE.md](ARCHITECTURE.md) | Domain ownership and system design |\n| [PRODUCT_DESIGN.md](PRODUCT_DESIGN.md) | Product information architecture, interaction hierarchy, and UI invariants |\n| [PLAN.md](PLAN.md) | Current development scope |",
)
replace_once(
    "docs/README.md",
    "- [Product design](../design.md)\n",
    "",
)
replace_once(
    "AGENTS.md",
    "For UI work, consult `design.md` when relevant.",
    "For UI work, consult `docs/PRODUCT_DESIGN.md` when relevant.",
)
replace_once(
    "scripts/ci/check_docs_integrity.py",
    '    "docs/ARCHITECTURE.md",\n    "docs/PLAN.md",',
    '    "docs/ARCHITECTURE.md",\n    "docs/PRODUCT_DESIGN.md",\n    "docs/PLAN.md",',
)

# 2. Pin Linux runner major version across workflows.
workflow_dir = ROOT / ".github/workflows"
runner_replacements = 0
for workflow in sorted(workflow_dir.glob("*.yml")):
    text = workflow.read_text(encoding="utf-8")
    count = text.count("runs-on: ubuntu-latest")
    if count:
        workflow.write_text(
            text.replace("runs-on: ubuntu-latest", "runs-on: ubuntu-24.04"),
            encoding="utf-8",
        )
        runner_replacements += count
if runner_replacements == 0:
    raise SystemExit("no ubuntu-latest runner references found")

# 3. Pin image identities and remove misleading default release version.
replace_once(
    "Dockerfile",
    "FROM node:24.20.0-alpine3.24 AS frontend-build",
    "FROM node:24.20.0-alpine3.24@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS frontend-build",
)
replace_once(
    "Dockerfile",
    "FROM python:3.12.13-slim-trixie",
    "FROM python:3.12.13-slim-trixie@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36",
)
replace_once("Dockerfile", "ARG VERSION=0.3.2", "ARG VERSION=dev")
replace_all(
    ".github/workflows/ci.yml",
    "ghcr.io/gitleaks/gitleaks:v8.30.1",
    "ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f",
    minimum=2,
)

# 4. Add reproducible ShellCheck via the Python dev lock and run it in repository integrity.
replace_once(
    "pyproject.toml",
    '    "pip-audit==2.10.1",\n    "pre-commit>=4.6.2",',
    '    "pip-audit==2.10.1",\n    "shellcheck-py==0.11.0.1",\n    "pre-commit>=4.6.2",',
)
replace_once(
    ".pre-commit-config.yaml",
    "      - id: documentation-integrity\n        name: documentation integrity\n        entry: python scripts/ci/check_docs_integrity.py\n        language: system\n        pass_filenames: false\n        files: '(^|/).*\\.md$|^docs/|^scripts/ci/check_docs_integrity\\.py$'\n",
    "      - id: shellcheck-locked\n        name: ShellCheck (uv locked)\n        entry: uv run --locked --extra dev shellcheck\n        language: system\n        types: [shell]\n        require_serial: true\n      - id: documentation-integrity\n        name: documentation integrity\n        entry: python scripts/ci/check_docs_integrity.py\n        language: system\n        pass_filenames: false\n        files: '(^|/).*\\.md$|^docs/|^scripts/ci/check_docs_integrity\\.py$'\n",
)
replace_once(
    ".github/workflows/ci.yml",
    "      - name: Check public shell entrypoints\n        run: bash -n scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n",
    "      - name: Set up Python\n        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0\n        with:\n          python-version: \"3.12.13\"\n      - name: Set up uv\n        uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1\n        with:\n          version: ${{ env.UV_VERSION }}\n          enable-cache: true\n      - run: uv sync --locked --extra dev\n      - name: Check public shell entrypoints\n        run: bash -n scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n      - name: Check public shell entrypoints with ShellCheck\n        run: uv run --locked --extra dev shellcheck scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n",
)

# 5. Remove dormant coverage policy instead of pretending it is enforced by CI.
replace_once("pyproject.toml", '    "pytest-cov>=7.1.0",\n', "")
pyproject = ROOT / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
coverage_block = '''\n[tool.coverage.run]\nsource = [\n    "core",\n    "domain",\n    "data",\n    "strategy",\n    "execution",\n    "risk",\n    "backtest",\n    "analytics",\n    "account_truth",\n    "notification",\n    "server",\n]\n\n[tool.coverage.report]\nfail_under = 85\nshow_missing = true\nskip_covered = true\n\n[tool.coverage.xml]\noutput = "reports/ci/coverage.xml"\n'''
if text.count(coverage_block) != 1:
    raise SystemExit("unexpected coverage configuration")
pyproject.write_text(text.replace(coverage_block, "\n", 1), encoding="utf-8")

# Keep engineering documentation aligned with the now-enforced state.
replace_once(
    "docs/ENGINEERING.md",
    "- Container base images and the Gitleaks container are version-tag pinned rather than digest pinned; third-party GitHub Actions are full-SHA pinned.\n",
    "- Container base images and the Gitleaks container are tag-and-digest pinned; third-party GitHub Actions are full-SHA pinned.\n",
)
replace_once(
    "docs/ENGINEERING.md",
    "- mypy is the CI type-checking authority.\n",
    "- mypy is the CI type-checking authority.\n- ShellCheck is the shell static-analysis authority for maintained public runtime/release entrypoints.\n",
)

# Guard against stale references and accidental rollback of the requested invariants.
checks = {
    "design.md reference": "design.md",
    "ubuntu-latest runner": "runs-on: ubuntu-latest",
    "unpinned gitleaks": "ghcr.io/gitleaks/gitleaks:v8.30.1 detect",
    "stale Docker version": "ARG VERSION=0.3.2",
    "dormant coverage threshold": "fail_under = 85",
}
for label, needle in checks.items():
    result = subprocess.run(
        ["git", "grep", "-n", "--fixed-strings", needle, "--", ":!uv.lock"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        raise SystemExit(f"{label} remains:\n{result.stdout}")
    if result.returncode not in {0, 1}:
        raise SystemExit(f"git grep failed for {label}: {result.stderr}")

print(f"updated {runner_replacements} Linux runner declarations")
