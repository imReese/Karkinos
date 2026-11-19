#!/usr/bin/env python3
"""Inspect or pause an exact durable job queue without executing its jobs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.persistence.jobs import SQLiteJobStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "pause", "resume"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--queue", required=True)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument(
        "--job-ids-file",
        type=Path,
        help='Optional exact existing jobs to assign, JSON {"jobs": ["<job_id>"]}.',
    )
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error("--db must identify an existing migrated app.db")
    store = SQLiteJobStore(args.db)
    if args.action == "status":
        if any(
            value is not None
            for value in (
                args.expected_revision,
                args.actor,
                args.reason,
                args.job_ids_file,
            )
        ):
            parser.error("status does not accept mutation arguments")
    else:
        if args.expected_revision is None or not args.actor or not args.reason:
            parser.error(
                "pause/resume requires --expected-revision, --actor and --reason"
            )
        identities = ()
        if args.job_ids_file is not None:
            payload = json.loads(args.job_ids_file.read_text())
            identities = payload["jobs"]
            if not isinstance(identities, list) or not all(
                isinstance(value, str) for value in identities
            ):
                parser.error("--job-ids-file must contain a jobs list of exact job IDs")
        store.set_queue_paused(
            args.queue,
            paused=args.action == "pause",
            expected_revision=args.expected_revision,
            actor=args.actor,
            reason=args.reason,
            now=datetime.now(timezone.utc),
            job_ids=identities,
        )
    print(json.dumps(store.queue_status(args.queue), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
