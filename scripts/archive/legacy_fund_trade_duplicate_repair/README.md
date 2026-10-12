# Historical Archive: Legacy Fund Trade Duplicate Repair

## Context and Purpose

In August 2026 (commit `5fd63088`), an issue was discovered where certain legacy fund purchase records imported into the SQLite ledger (`app.db`) had accidental duplicate pairs (simultaneously represented as both `manual` entry and `portfolio_trade` canonical entry).

A one-off, atomic, fingerprint-authorized deduplication slice was built to inspect, preview, and compensate these duplicate pairs by appending immutable projection correction entries.

## Status: Completed & Preserved

1. **Production Status**: The production database (`data/store/app.db`) has been verified to have 0 duplicate pairs and no active repair requirements.
2. **Archival Rationale**: In accordance with project engineering principles (`AGENTS.md`, `docs/ENGINEERING.md`), one-off repair tooling is removed from primary service and persistence trees (`server/services/`, `server/persistence/`, `server/legacy_fund_trade_duplicate_repair_cli.py`) once the live environment has reached a clean state.
3. **Ledger Integrity**: The pure projection read contracts (`server/projections/legacy_fund_trade_duplicate_*.py` and `server/projections/ledger_correction_read.py`) remain active in `server/projections/` to validate historical ledgers on read and maintain point-in-time financial semantics.
4. **Contents**:
   - `repair_legacy_fund_trade_duplicates.py`: Standalone CLI execution entrypoint.
   - `legacy_fund_trade_duplicate_repair_cli.py`: CLI arguments and output formatting.
   - `legacy_fund_trade_duplicate_repair_service.py`: Fingerprint validation and execution service.
   - `legacy_fund_trade_duplicate_repair_persistence.py`: Unit-of-work SQLite transaction layer.
   - `test_legacy_fund_trade_duplicate_repair.py`: Full historical test suite for the repair pipeline.
