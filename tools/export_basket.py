"""Export an existing manual-order API snapshot to a local review-only CSV.

    python -m tools.export_basket --input orders.json --output review.csv

No provider, account, database, strategy, or broker is called by this command.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from server.projections.manual_order_export import export_manual_order_review_csv


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("order_export_duplicate_json_key")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Export saved /api/trading/orders rows for human review only."
    )
    parser.add_argument("--input", type=Path, required=True, help="Saved JSON response")
    parser.add_argument("--output", type=Path, help="New CSV file; defaults to stdout")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(
            args.input.read_text(encoding="utf-8"),
            parse_float=Decimal,
            object_pairs_hook=_unique_object,
        )
        if not isinstance(payload, list) or not all(
            isinstance(row, dict) for row in payload
        ):
            raise ValueError("order_export_requires_manual_order_rows")
        content = export_manual_order_review_csv(payload)
        if args.output is None:
            sys.stdout.write(content)
        else:
            # Do not overwrite the source snapshot or an earlier review.
            with args.output.open("x", encoding="utf-8", newline="") as stream:
                stream.write(content)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"Order review export failed: {exc}\n")


if __name__ == "__main__":
    main()
