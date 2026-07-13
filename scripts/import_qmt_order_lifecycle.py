#!/usr/bin/env python3
"""Retired entry point; use the explicitly named legacy migration command."""

from __future__ import annotations

import json


def main(argv: list[str] | None = None) -> int:
    del argv
    print(
        json.dumps(
            {
                "status": "blocked",
                "blockers": ["legacy_qmt_import_entrypoint_retired"],
                "migration_command": ("scripts/migrate_legacy_qmt_order_lifecycle.py"),
                "canonical_command": "scripts/import_broker_order_lifecycle.py",
                "qmt_runtime_supported": False,
                "provider_contacted": False,
                "broker_submission_enabled": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
