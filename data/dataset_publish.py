"""Publish an explicitly supplied, evidence-bound daily bundle to the local lake."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from data.dataset_catalog import DatasetCatalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="JSON containing universe, daily, cutoff and expected_sessions",
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    manifest = DatasetCatalog(args.data_dir).publish_daily(
        universe=payload["universe"],
        daily=payload["daily"],
        cutoff=payload["cutoff"],
        expected_sessions=payload["expected_sessions"],
        published_at=datetime.now(timezone.utc).isoformat(),
    )
    print(json.dumps(asdict(manifest), sort_keys=True))


if __name__ == "__main__":
    main()
