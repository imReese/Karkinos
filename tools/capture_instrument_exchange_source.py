"""Capture one explicitly selected public SSE notice into an evidence directory."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from data.instrument_exchange_source import (
    SSE_LISTING_SOURCES,
    SseSourceCaptureRejected,
    capture_sse_listing_source,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=tuple(SSE_LISTING_SOURCES))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        capture = capture_sse_listing_source(
            SSE_LISTING_SOURCES[args.source], output_dir=args.output_dir
        )
    except SseSourceCaptureRejected as exc:
        print(json.dumps(dict(status="failed", reason=str(exc))))
        return 1
    print(
        json.dumps(
            dict(receipt_sha256=capture.receipt_sha256, **asdict(capture)),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
