"""Quarantined live execution, broker adapters, and reconciliation infrastructure.

DURABLE INVARIANT (AGENTS.md & docs/PLAN.md):
- Real-money authority remains default-off, bounded, observable, pausable, revocable, and human-supervised.
- Live-trading safety constraints are durable boundaries, not current implementation scope.
- Strategy and research code never call a broker directly.
- All modules within this package are frozen under docs/PLAN.md.
"""
