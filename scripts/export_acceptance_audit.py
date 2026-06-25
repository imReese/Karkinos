"""Export acceptance audit manifests as CI-friendly JSON."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analytics.acceptance_audit_report import (
    AUDIT_REGISTRY,
    build_acceptance_audit_export,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    payload = build_acceptance_audit_export(selected_audit=args.audit)
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    if args.pretty:
        text = f"{text}\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")

    return 0 if payload["overall_is_complete"] else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export Karkinos acceptance audit manifests as JSON.",
    )
    parser.add_argument(
        "--audit",
        choices=("all", *AUDIT_REGISTRY.keys()),
        default="all",
        help="Acceptance audit manifest to export.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional file path. Defaults to stdout and writes no artifact.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
