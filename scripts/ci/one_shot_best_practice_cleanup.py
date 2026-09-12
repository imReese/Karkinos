from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

NODE_DIGEST = "sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf"
PYTHON_DIGEST = "sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36"
GITLEAKS_DIGEST = "sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: Path, old: str, new: str) -> int:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count:
        path.write_text(text.replace(old, new), encoding="utf-8")
    return count


# Canonical product design doc: keep all durable docs under docs/.
old_design = ROOT / "design.md"
new_design = ROOT / "docs/PRODUCT_DESIGN.md"
if not old_design.is_file() or new_design.exists():
    raise SystemExit("unexpected product-design document state")
old_design.rename(new_design)

replace_once(
    "docs/README.md",
    "| [ARCHITECTURE.md](ARCHITECTURE.md) | Domain ownership and system design |\n| [PLAN.md](PLAN.md) | Current development scope |",
    "| [ARCHITECTURE.md](ARCHITECTURE.md) | Domain ownership and system design |\n| [PRODUCT_DESIGN.md](PRODUCT_DESIGN.md) | Product model, information architecture, interaction, and UI invariants |\n| [PLAN.md](PLAN.md) | Current development scope |",
)
replace_once("docs/README.md", "- [Product design](../design.md)\n", "")
replace_once(
    "AGENTS.md",
    "For UI work, consult `design.md` when relevant.",
    "For UI work, consult `docs/PRODUCT_DESIGN.md` when relevant.",
)
replace_once(
    "docs/PRODUCT_DESIGN.md",
    "`design.md` is the product-level contract.",
    "`docs/PRODUCT_DESIGN.md` is the product-level contract.",
)
replace_once(
    "scripts/ci/check_docs_integrity.py",
    '    "docs/ARCHITECTURE.md",\n    "docs/PLAN.md",',
    '    "docs/ARCHITECTURE.md",\n    "docs/PRODUCT_DESIGN.md",\n    "docs/PLAN.md",',
)
replace_once(
    "scripts/ci/classify_dev_changes.py",
    '    "design.md",\n',
    "",
)

# Pin Linux hosted runner major version everywhere; macOS runners remain unchanged.
workflow_dir = ROOT / ".github/workflows"
latest_count = 0
for path in workflow_dir.glob("*.yml"):
    latest_count += replace_all(path, "runs-on: ubuntu-latest", "runs-on: ubuntu-24.04")
if latest_count == 0:
    raise SystemExit("expected at least one ubuntu-latest runner reference")

# Pin supply-chain container inputs while retaining human-readable tags.
replace_once(
    "Dockerfile",
    "FROM node:24.20.0-alpine3.24 AS frontend-build",
    f"FROM node:24.20.0-alpine3.24@{NODE_DIGEST} AS frontend-build",
)
replace_once(
    "Dockerfile",
    "FROM python:3.12.13-slim-trixie",
    f"FROM python:3.12.13-slim-trixie@{PYTHON_DIGEST}",
)
replace_once("Dockerfile", "ARG VERSION=0.3.2", "ARG VERSION=dev")

ci_path = ROOT / ".github/workflows/ci.yml"
ci = ci_path.read_text(encoding="utf-8")
gitleaks_tag = "ghcr.io/gitleaks/gitleaks:v8.30.1"
gitleaks_pinned = f"{gitleaks_tag}@{GITLEAKS_DIGEST}"
gitleaks_count = ci.count(gitleaks_tag)
if gitleaks_count != 2:
    raise SystemExit(f"expected two Gitleaks invocations, got {gitleaks_count}")
ci = ci.replace(gitleaks_tag, gitleaks_pinned)

# Shell syntax alone is insufficient for large lifecycle scripts.
shell_syntax = "      - name: Check public shell entrypoints\n        run: bash -n scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n"
shellcheck_step = shell_syntax + "      - name: Check public shell entrypoints with ShellCheck\n        run: shellcheck scripts/start_server.sh scripts/stop_server.sh scripts/service/manage_launch_agent.sh scripts/release/bootstrap_installer.sh\n"
if ci.count(shell_syntax) != 1:
    raise SystemExit("unexpected shell-entrypoint CI step")
ci = ci.replace(shell_syntax, shellcheck_step, 1)

# Coverage is a Full CI policy only. Incremental CI remains fast; full mode runs
# the complete suite so trading-safety-only paths still contribute to coverage.
backend_command = '      - run: uv run --locked python -m pytest -n 4 --dist loadfile --max-worker-restart=0 -m "not trading_safety"\n'
backend_full = '''      - name: Run backend test suite\n        env:\n          CI_MODE: ${{ needs.plan.outputs.mode }}\n        shell: bash\n        run: |\n          set -euo pipefail\n          if [[ "${CI_MODE}" == full ]]; then\n            mkdir -p reports/ci\n            uv run --locked python -m pytest -n 4 --dist loadfile --max-worker-restart=0 \\\n              --cov --cov-report=term --cov-report=xml\n          else\n            uv run --locked python -m pytest -n 4 --dist loadfile --max-worker-restart=0 \\\n              -m "not trading_safety"\n          fi\n'''
if ci.count(backend_command) != 1:
    raise SystemExit("unexpected backend pytest command")
ci = ci.replace(backend_command, backend_full, 1)
ci_path.write_text(ci, encoding="utf-8")

# Keep engineering docs truthful after the hardening changes.
replace_once(
    "docs/ENGINEERING.md",
    "The incremental classifier is a cost optimizer, not a correctness authority. These checks are mandatory on every dev commit:",
    "The incremental classifier is a cost optimizer, not a correctness authority. Full CI additionally runs the complete backend suite with coverage and enforces the configured coverage threshold. These checks are mandatory on every dev commit:",
)
replace_once(
    "docs/ENGINEERING.md",
    "- Container base images and the Gitleaks container are version-tag pinned rather than digest pinned; third-party GitHub Actions are full-SHA pinned.\n",
    "- Container base images and the Gitleaks container are tag-plus-digest pinned; third-party GitHub Actions are full-SHA pinned.\n",
)

# No stale product-design path or floating Linux runner may remain.
stale_design = []
for path in ROOT.rglob("*"):
    if not path.is_file() or ".git" in path.parts or "node_modules" in path.parts:
        continue
    if path.suffix not in {".md", ".py", ".yml", ".yaml", ".toml"}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if "design.md" in text:
        stale_design.append(str(path.relative_to(ROOT)))
if stale_design:
    raise SystemExit("stale design.md references: " + ", ".join(stale_design))

floating = []
for path in workflow_dir.glob("*.yml"):
    if "ubuntu-latest" in path.read_text(encoding="utf-8"):
        floating.append(path.name)
if floating:
    raise SystemExit("floating Ubuntu runner references: " + ", ".join(floating))

# Sanity-check the exact policy strings we intend to enforce.
final_ci = ci_path.read_text(encoding="utf-8")
for required in (
    gitleaks_pinned,
    "runs-on: ubuntu-24.04",
    "shellcheck scripts/start_server.sh",
    "--cov --cov-report=term --cov-report=xml",
):
    if required not in final_ci:
        raise SystemExit(f"missing final CI policy: {required}")

final_docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
for required in (NODE_DIGEST, PYTHON_DIGEST, "ARG VERSION=dev"):
    if required not in final_docker:
        raise SystemExit(f"missing Docker hardening: {required}")
