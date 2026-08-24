"""Persistence error types surfaced to the strategy-research read boundary."""

from __future__ import annotations

import sqlite3

StrategyResearchDatabaseError = sqlite3.DatabaseError
StrategyResearchOperationalError = sqlite3.OperationalError
