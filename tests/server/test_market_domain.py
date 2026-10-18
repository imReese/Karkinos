"""Verification tests for the consolidated server.services.market domain."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from server.services.market.calendar import validate_verified_market_calendar

pytestmark = pytest.mark.unit


def test_cold_hours_import_does_not_load_calendar_automation() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import sys
from datetime import datetime, timezone
from server.services.market.hours import get_shanghai_now, is_cn_trading_session

unexpected = {
    "server.services.market.calendar",
    "server.services.market.calendar_automation",
    "server.services.market.indices",
    "data.market_calendar",
    "pandas",
}.intersection(sys.modules)
assert not unexpected, sorted(unexpected)

opening = datetime(2026, 10, 19, 1, 30, tzinfo=timezone.utc)
assert get_shanghai_now(opening).isoformat() == "2026-10-19T09:30:00+08:00"
assert is_cn_trading_session(opening)
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_market_calendar_validation_fails_closed_on_none() -> None:
    """Missing calendar row must fail closed with explicit blockers."""
    validation = validate_verified_market_calendar(None)
    assert not validation.verified
    assert "market_calendar_missing" in validation.blockers
    assert validation.evidence_ref is None
