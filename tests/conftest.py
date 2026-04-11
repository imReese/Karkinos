"""pytest 共享配置。"""

from __future__ import annotations

import pytest
from datetime import datetime
from decimal import Decimal

from core.types import Symbol


@pytest.fixture
def symbol_600519() -> Symbol:
    return Symbol("600519")


@pytest.fixture
def symbol_510300() -> Symbol:
    return Symbol("510300")


@pytest.fixture
def now() -> datetime:
    return datetime(2024, 1, 15, 10, 0, 0)


@pytest.fixture
def decimal_close() -> Decimal:
    return Decimal("1850.00")
