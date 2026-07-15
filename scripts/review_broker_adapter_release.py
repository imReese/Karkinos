#!/usr/bin/env python3
"""Preview or explicitly record a broker-neutral adapter release review."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseRejected,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or record a provider-neutral adapter release review. "
            "This never registers an adapter or grants broker authority."
        )
    )
    parser.add_argument("--file", required=True, help="Release manifest JSON file.")
    parser.add_argument("--db", required=True, help="Karkinos evidence database.")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Persist an explicit accept, reject, or revoke decision.",
    )
    parser.add_argument("--review-id", default="")
    parser.add_argument(
        "--decision",
        choices=("accepted", "rejected", "revoked"),
        default="rejected",
    )
    parser.add_argument("--reviewer-ref", default="")
    parser.add_argument("--reviewed-at", default="")
    parser.add_argument("--reason-ref", default="")
    parser.add_argument("--acknowledgement", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.file)
    try:
        content = source.read_bytes()
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "blockers": [
                        f"broker_adapter_release_manifest_read_failed:{type(exc).__name__}"
                    ],
                    "provider_contacted": False,
                    "adapter_registered": False,
                    "broker_submission_enabled": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    preview = preview_broker_adapter_release_manifest(
        content,
        source_name=source.name,
    )
    if not args.record:
        print(json.dumps(preview, ensure_ascii=False, sort_keys=True))
        return 0 if preview["validation_status"] == "pass" else 2

    reviewed_at = args.reviewed_at or datetime.now(UTC).isoformat()
    try:
        result = BrokerAdapterReleaseReviewRepository(Path(args.db)).record_review(
            preview,
            review_id=args.review_id,
            decision=args.decision,
            reviewer_ref=args.reviewer_ref,
            reviewed_at=reviewed_at,
            reason_ref=args.reason_ref,
            acknowledgement=args.acknowledgement,
        )
    except BrokerAdapterReleaseRejected as exc:
        print(json.dumps(exc.evidence, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT",
    "main",
    "parse_args",
]
