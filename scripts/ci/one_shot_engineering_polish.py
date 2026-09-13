from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ensure_replace(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1 and new_count == 0:
        file.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if old_count == 0 and new_count >= 1:
        return
    raise SystemExit(
        f"{path}: unexpected migration state old={old_count} new={new_count}: {old[:80]!r}"
    )


def ensure_replace_all(path: str, old: str, new: str, *, minimum: int = 1) -> int:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count:
        if old_count < minimum:
            raise SystemExit(
                f"{path}: expected at least {minimum} old matches, got {old_count}"
            )
        file.write_text(text.replace(old, new), encoding="utf-8")
        return old_count
    if new_count >= minimum:
        return 0
    raise SystemExit(f"{path}: neither old nor desired state found: {old[:80]!r}")


def restore_product_design() -> None:
    source = ROOT / "design.md"
    target = ROOT / "docs/PRODUCT_DESIGN.md"
    if target.is_file():
        return
    if source.is_file():
        subprocess.run(
            ["git", "mv", "design.md", "docs/PRODUCT_DESIGN.md"],
            cwd=ROOT,
            check=True,
        )
        return

    history = subprocess.run(
        ["git", "rev-list", "HEAD", "--", "design.md"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    for revision in history:
        result = subprocess.run(
            ["git", "show", f"{revision}:design.md"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.startswith("# Karkinos Product Design"):
            target.write_text(result.stdout, encoding="utf-8")
            return
    raise SystemExit("could not recover canonical product design from repository history")


# 1. Complete the already-started canonical product-design migration.
restore_product_design()
ensure_replace(
    "docs/PRODUCT_DESIGN.md",
    "`design.md` is the product-level contract.",
    "`PRODUCT_DESIGN.md` is the product-level contract.",
)
ensure_replace(
    "docs/README.md",
    "| [ARCHITECTURE.md](ARCHITECTURE.md) | Domain ownership and system design |\n| [PLAN.md](PLAN.md) | Current development scope |",
    "| [ARCHITECTURE.md](ARCHITECTURE.md) | Domain ownership and system design |\n| [PRODUCT_DESIGN.md](PRODUCT_DESIGN.md) | Product model, information architecture, interaction, and UI invariants |\n| [PLAN.md](PLAN.md) | Current development scope |",
)
text = (ROOT / "docs/README.md").read_text(encoding="utf-8")
if "- [Product design](../design.md)\n" in text:
    (ROOT / "docs/README.md").write_text(
        text.replace("- [Product design](../design.md)\n", "", 1), encoding="utf-8"
    )
ensure_replace(
    "AGENTS.md",
    "For UI work, consult `design.md` when relevant.",
    "For UI work, consult `docs/PRODUCT_DESIGN.md` when relevant.",
)
ensure_replace(
    "scripts/ci/check_docs_integrity.py",
    '    "docs/ARCHITECTURE.md",\n    "docs/PLAN.md",',
    '    "docs/ARCHITECTURE.md",\n    "docs/PRODUCT_DESIGN.md",\n    "docs/PLAN.md",',
)

# 2. Pin the Linux runner major version across maintained workflows.
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

# 3. Pin image identities and remove misleading default release version.
ensure_replace(
    "Dockerfile",
    "FROM node:24.20.0-alpine3.24 AS frontend-build",
    "FROM node:24.20.0-alpine3.24@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS frontend-build",
)
ensure_replace(
    "Dockerfile",
    "FROM python:3.12.13-slim-trixie",
    "FROM python:3.12.13-slim-trixie@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36",
)
ensure_replace("Dockerfile", "ARG VERSION=0.3.2", "ARG VERSION=dev")
ensure_replace_all(
    ".github/workflows/ci.yml",
    "ghcr.io/gitleaks/gitleaks:v8.30.1",
    "ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f",
    minimum=2,
)

# 4. Add reproducible ShellCheck via the Python dev lock and enforce it in CI/local hooks.
ensure_replace(
    "pyproject.toml",
    '    "pip-audit==2.10.1",\n    "pre-commit>=4.6.2",',
    '    "pip-audit==2.10.1",\n    "shellcheck-py==0.11.0.1",\n    "pre-commit>=4.6.2",',
)
ensure_replace(
    ".pre-commit-config.yaml",
    "      - id: documentation-integrity\n        name: documentation integrity\n        entry: python scripts/ci/check_docs_integrity.py\n        language: system\n        pass_filenames: false\n        files: '(^|/).*\\.md$|^docs/|^scripts/ci/check_docs_integrity\\.py$'\n",
    "      - id: shellcheck-locked\n        name: ShellCheck (uv locked)\n        entry: uv run --locked --extra dev shellcheck\n        language: system\n        types: [shell]\n        require_serial: true\n      - id: documentation-integrity\n        name: documentation integrity\n        entry: python scripts/ci/check_docs_integrity.py\n        language: system\n        pass_filenames: false\n        files: '(^|/).*\\.md$|^docs/|^scripts/ci/check_docs_integrity\\.py$'\n",
)
ensure_replace(
    ".github/workflows/ci.yml",
    "      - name: Check public shell entrypoints\n        run: bash -n scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n",
    "      - name: Set up Python\n        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0\n        with:\n          python-version: \"3.12.13\"\n      - name: Set up uv\n        uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1\n        with:\n          version: ${{ env.UV_VERSION }}\n          enable-cache: true\n      - run: uv sync --locked --extra dev\n      - name: Check public shell entrypoints\n        run: bash -n scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n      - name: Check public shell entrypoints with ShellCheck\n        run: uv run --locked --extra dev shellcheck scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n",
)

# 5. Remove dormant coverage policy instead of pretending it is enforced by CI.
pyproject = ROOT / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
text = text.replace('    "pytest-cov>=7.1.0",\n', "")
coverage_block = '''\n[tool.coverage.run]\nsource = [\n    "core",\n    "domain",\n    "data",\n    "strategy",\n    "execution",\n    "risk",\n    "backtest",\n    "analytics",\n    "account_truth",\n    "notification",\n    "server",\n]\n\n[tool.coverage.report]\nfail_under = 85\nshow_missing = true\nskip_covered = true\n\n[tool.coverage.xml]\noutput = "reports/ci/coverage.xml"\n'''
if coverage_block in text:
    text = text.replace(coverage_block, "\n", 1)
if "pytest-cov" in text or "[tool.coverage." in text or "fail_under = 85" in text:
    raise SystemExit("coverage policy was not fully retired")
pyproject.write_text(text, encoding="utf-8")

# Keep engineering documentation aligned with the enforced state.
ensure_replace(
    "docs/ENGINEERING.md",
    "- Container base images and the Gitleaks container are version-tag pinned rather than digest pinned; third-party GitHub Actions are full-SHA pinned.\n",
    "- Container base images and the Gitleaks container are tag-and-digest pinned; third-party GitHub Actions are full-SHA pinned.\n",
)
ensure_replace(
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

if not (ROOT / "docs/PRODUCT_DESIGN.md").is_file():
    raise SystemExit("canonical product design is still missing")

print(f"updated {runner_replacements} Linux runner declarations")
