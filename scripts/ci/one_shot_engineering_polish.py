from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def restore_product_design() -> None:
    target = ROOT / "docs/PRODUCT_DESIGN.md"
    if target.is_file():
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
        if result.returncode != 0 or not result.stdout.startswith("# Karkinos Product Design"):
            continue
        content = result.stdout.replace(
            "`design.md` is the product-level contract.",
            "`PRODUCT_DESIGN.md` is the product-level contract.",
            1,
        )
        target.write_text(content, encoding="utf-8")
        return
    raise SystemExit("could not recover canonical product design from repository history")


def add_shellcheck_precommit() -> None:
    path = ROOT / ".pre-commit-config.yaml"
    text = path.read_text(encoding="utf-8")
    if "id: shellcheck" in text:
        return
    marker = "      - id: documentation-integrity\n"
    if text.count(marker) != 1:
        raise SystemExit("unexpected pre-commit documentation hook layout")
    hook = (
        "      - id: shellcheck\n"
        "        name: ShellCheck\n"
        "        entry: shellcheck\n"
        "        language: system\n"
        "        types: [shell]\n"
        "        require_serial: true\n"
    )
    path.write_text(text.replace(marker, hook + marker, 1), encoding="utf-8")


restore_product_design()
add_shellcheck_precommit()

if not (ROOT / "docs/PRODUCT_DESIGN.md").is_file():
    raise SystemExit("canonical product design is still missing")
