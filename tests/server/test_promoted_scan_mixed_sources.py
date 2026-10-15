"""Independent human and policy sources share the actual account budget."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from execution.commission import StockACommission
from server.db import AppDatabase
from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.account_board_permissions import freeze_entry_board_policy
from server.services.market_universe_truth import MarketUniversePolicy
from server.services.promoted_strategy_universe_scan_support import (
    account_eligible_signals,
)

POLICY = "ai_formula_shadow:policy"
HUMAN = "ai_formula_shadow:human"


def _signal(source, symbol, *, direction="buy", rank=100):
    return {
        "strategy_id": source,
        "symbol": symbol,
        "direction": direction,
        "ranking_liquidity": rank,
        "frozen_close": 10,
        "target_weight": 0 if direction == "sell" else 0.25,
        **(
            {"portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID}
            if source == POLICY
            else {}
        ),
    }


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_strategy_promotion_state_sync(
        strategy_id=POLICY,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={
            "readiness": {
                "deployment_validation": {
                    "final_evaluation_id": "sealed-fixture",
                    "initial_cash": "40000",
                    "entry_board_policy": freeze_entry_board_policy(None, "2026-08-24"),
                }
            }
        },
    )
    monkeypatch.setattr(
        StrategyResearchAuditStore,
        "get_sealed_test",
        lambda *args: {
            "evidence": {
                "reservation": {
                    "fee_schedule": {},
                    "publication_grant": {
                        "risk_limits": {
                            "max_positions": 4,
                            "max_gross_weight": "0.97",
                            "max_symbol_weight": "0.30",
                        },
                    },
                }
            },
        },
    )
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.resolve_frozen_deployment_fee_schedule",
        lambda *args: SimpleNamespace(
            commission_calc=StockACommission(min_commission=Decimal("7")),
            review=SimpleNamespace(
                effective_start_date="2026-01-01", effective_end_date="2026-12-31"
            ),
        ),
    )
    # Capture real allocator results; source bindings are isolated above, while
    # cash, quantities, fees, global ranking and slot arithmetic remain real.
    import domain.research_targets as targets

    allocate = targets.allocate_formula_targets
    allocations = []

    def tracked(**kwargs):
        result = allocate(**kwargs)
        allocations.append((kwargs, result))
        return result

    monkeypatch.setattr(targets, "allocate_formula_targets", tracked)
    inputs = {
        "db": db,
        "config": SimpleNamespace(account_commission_rate="0.02"),
        "decision_date": "2026-08-24",
        "policy": MarketUniversePolicy(fee_buffer_rate=Decimal(0)),
        "cash_buffer_ratio": Decimal("0.03"),
    }
    return inputs, allocations


def _portfolio(*, cash=30000, held=None):
    values = held or {}
    return {
        "fact_authority": "persisted_valuation_snapshot",
        "total_equity": 100000,
        "cash": cash,
        "stock_position_market_values": values,
        "stock_symbols": list(values),
    }


def test_policy_exit_does_not_change_unrelated_human_buy(mixed):
    inputs, _ = mixed
    human = _signal(HUMAN, "600000")
    exit_signal = _signal(POLICY, "600010", direction="sell")
    portfolio = _portfolio(held={"600010": 2000})
    alone, blockers = account_eligible_signals([human], portfolio=portfolio, **inputs)
    together, more = account_eligible_signals(
        [human, exit_signal], portfolio=portfolio, **inputs
    )
    assert blockers == more == []
    assert together == [exit_signal, *alone]


def test_mixed_buys_share_cash_once_and_keep_source_capital_and_fees(mixed):
    inputs, allocations = mixed
    selected, blocked = account_eligible_signals(
        [_signal(HUMAN, "600001", rank=90), _signal(POLICY, "600000", rank=100)],
        portfolio=_portfolio(held={"600010": 2000}),
        **inputs,
    )
    assert blocked == []
    assert [row["strategy_id"] for row in selected] == [POLICY, HUMAN]
    assert selected[0]["target_weight"] == 0.1  # 25% of policy's own 40,000.
    assert selected[1]["target_weight"] > 0.1  # Human is not bound to that grant.
    spent = sum(
        (sum(result["purchase_costs"].values()) for _, result in allocations),
        Decimal(0),
    )
    assert spent <= Decimal(30000) - Decimal(100000) * Decimal("0.03")
    assert all(kwargs["cash_buffer_ratio"] == 0 for kwargs, _ in allocations)
    policy_order, human_order = allocations
    assert policy_order[0]["equity"] == 40000
    assert human_order[0]["equity"] == 100000
    assert human_order[0]["cash"] == Decimal(27000) - sum(
        policy_order[1]["purchase_costs"].values()
    )
    human_quantity = human_order[1]["entry_quantities"]["600001"]
    assert human_order[1]["purchase_costs"]["600001"] >= human_quantity * Decimal(
        10
    ) * Decimal("1.02")


def test_small_policy_grant_does_not_shrink_higher_ranked_human_target(mixed):
    inputs, _ = mixed
    selected, blocked = account_eligible_signals(
        [_signal(POLICY, "600000", rank=90), _signal(HUMAN, "600001", rank=100)],
        portfolio=_portfolio(cash=50000),
        **inputs,
    )
    assert selected == [{**_signal(HUMAN, "600001", rank=100), "target_weight": 0.25}]
    assert blocked == [
        {
            "strategy_id": POLICY,
            "symbol": "600000",
            "reason": "current_portfolio_exceeds_publication_risk_bounds",
        }
    ]


@pytest.mark.parametrize("policy_first", [True, False])
def test_actual_holdings_and_reserved_entries_share_one_slot_limit(mixed, policy_first):
    inputs, allocations = mixed
    selected, _ = account_eligible_signals(
        [
            _signal(POLICY, "600000", rank=100 if policy_first else 90),
            _signal(HUMAN, "600001", rank=90 if policy_first else 100),
        ],
        portfolio=_portfolio(
            cash=50000, held={"600010": 2000, "600011": 2000, "600012": 2000}
        ),
        **inputs,
    )
    assert len(selected) == 1
    assert selected[0]["strategy_id"] == (POLICY if policy_first else HUMAN)
    assert sum(len(result["entry_quantities"]) for _, result in allocations) == 1


def test_same_symbol_uses_one_ranked_source_and_opposite_direction_never_rebuys(mixed):
    inputs, _ = mixed
    selected, blocked = account_eligible_signals(
        [
            _signal(POLICY, "600000", rank=100),
            _signal(HUMAN, "600000", rank=90),
            _signal(HUMAN, "600001", rank=80),
        ],
        portfolio=_portfolio(),
        **inputs,
    )
    assert blocked == []
    assert [(row["strategy_id"], row["symbol"]) for row in selected] == [
        (POLICY, "600000"),
        (HUMAN, "600001"),
    ]
    exit_signal = _signal(POLICY, "600010", direction="sell")
    selected, blocked = account_eligible_signals(
        [
            exit_signal,
            _signal(HUMAN, "600010", rank=100),
            _signal(POLICY, "600000", rank=90),
        ],
        portfolio=_portfolio(cash=10000, held={"600010": 2000}),
        **inputs,
    )
    assert exit_signal in selected
    assert not any(
        row["direction"] == "buy" and row["symbol"] == "600010" for row in selected
    )
    assert {
        "strategy_id": HUMAN,
        "symbol": "600010",
        "reason": "account_exit_signal_conflict",
    } in blocked
    assert (
        sum(row["target_weight"] for row in selected) < 0.1
    )  # No exit proceeds anticipated.


def test_frozen_entry_universe_combines_with_human_before_global_ranking(mixed):
    inputs, _ = mixed
    selected, blocked = account_eligible_signals(
        [
            _signal(POLICY, "688001", rank=105),
            *[_signal(POLICY, f"60000{index}", rank=104 - index) for index in range(3)],
            _signal(HUMAN, "600004", rank=90),
        ],
        portfolio=_portfolio(cash=100000),
        **inputs,
    )
    assert [row["symbol"] for row in selected] == [
        "600000",
        "600001",
        "600002",
        "600004",
    ]
    assert {row["symbol"]: row["reason"] for row in blocked} == {
        "688001": "frozen_entry_board_policy",
    }


@pytest.mark.parametrize(
    "permissions",
    [
        None,
        {
            "status": "current",
            "resolved_for_date": "2026-08-21",
            "boards": {"chinext": "enabled"},
        },
    ],
)
def test_missing_current_frozen_board_access_blocks_only_policy_entries(
    mixed, permissions
):
    inputs, _ = mixed
    db = inputs["db"]
    row = db.get_strategy_promotion_state_sync(POLICY)
    payload = json.loads(row["payload_json"])
    payload["readiness"]["deployment_validation"]["entry_board_policy"] = (
        freeze_entry_board_policy(
            SimpleNamespace(
                account_board_permissions={
                    "source": "self_reported_broker_account",
                    "reviewed_by": "human:fixture",
                    "reviewed_at": "2026-08-24T09:00:00+08:00",
                    "boards": {"chinext": "enabled"},
                }
            ),
            "2026-08-24",
        )
    )
    db.upsert_strategy_promotion_state_sync(
        strategy_id=POLICY,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload=payload,
    )
    exit_signal = _signal(POLICY, "600010", direction="sell")
    selected, blocked = account_eligible_signals(
        [exit_signal, _signal(POLICY, "600000"), _signal(HUMAN, "600001")],
        portfolio={
            **_portfolio(held={"600010": 1000}),
            "board_buy_permissions": permissions,
        },
        **inputs,
    )
    assert [row["strategy_id"] for row in selected] == [POLICY, HUMAN]
    assert selected[0] == exit_signal
    assert blocked == [
        {
            "strategy_id": POLICY,
            "symbol": "600000",
            "reason": "deployment_entry_board_permissions_not_current",
        }
    ]
