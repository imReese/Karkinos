"""Rebalance order generator for converting target weights to actionable orders.

Translates portfolio target weights into concrete buy/sell orders given current
holdings, latest market prices, and total equity. Enforces China A-share lot rules
(multiples of 100 shares for buys), order sequencing (sell before buy to release cash),
and provides standard export formats for broker terminals (QMT, PTrade, CSV).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Mapping, Sequence

from core.types import OrderSide, Symbol

_DEFAULT_SYMBOL_NAMES: dict[str, str] = {
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "512100": "中证1000ETF",
    "159915": "创业板ETF",
    "588000": "科创50ETF",
    "512890": "红利低波ETF",
    "518880": "黄金ETF",
    "511010": "国债ETF",
    "511990": "华宝添益货币ETF",
    "513100": "纳指100ETF",
    "513500": "标普500ETF",
    "159934": "黄金基金ETF",
    "512010": "医药ETF",
    "512690": "酒ETF",
    "512480": "半导体ETF",
    "515050": "5G通信ETF",
    "512760": "芯片ETF",
}


@dataclass(frozen=True)
class RebalanceOrderProposal:
    """Actionable order proposal derived from portfolio target differences."""

    symbol: Symbol
    name: str
    side: OrderSide
    quantity: int  # Shares to trade
    estimated_price: Decimal
    estimated_amount: Decimal
    target_weight: Decimal
    current_weight: Decimal
    reason: str


@dataclass(frozen=True)
class RebalancePlan:
    """Complete rebalance execution plan."""

    sell_orders: list[RebalanceOrderProposal]
    buy_orders: list[RebalanceOrderProposal]
    total_sell_amount: Decimal
    total_buy_amount: Decimal
    estimated_net_cash_flow: Decimal
    turnover_ratio: Decimal  # (Sell + Buy) / 2 / total_equity

    @property
    def all_orders(self) -> list[RebalanceOrderProposal]:
        """All orders in execution order: sells first, then buys."""
        return self.sell_orders + self.buy_orders

    def to_csv(self) -> str:
        """Generate standard broker-compatible CSV string (证券代码, 证券名称, 买卖方向, 委托数量, 委托价格)."""
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "证券代码",
                "证券名称",
                "买卖方向",
                "委托数量",
                "预估价格",
                "预估金额",
                "调仓说明",
            ]
        )
        for order in self.all_orders:
            side_str = "买入" if order.side == OrderSide.BUY else "卖出"
            writer.writerow(
                [
                    str(order.symbol),
                    order.name,
                    side_str,
                    order.quantity,
                    f"{order.estimated_price:.3f}",
                    f"{order.estimated_amount:.2f}",
                    order.reason,
                ]
            )
        return output.getvalue()

    def to_markdown_table(self) -> str:
        """Generate human-readable Markdown table."""
        if not self.all_orders:
            return "无需调仓（当前持仓与目标配置一致）。"

        lines = [
            f"### 调仓执行清单 (换手率: {self.turnover_ratio * 100:.2f}%)",
            f"- 预计卖出金额: ¥{self.total_sell_amount:,.2f}",
            f"- 预计买入金额: ¥{self.total_buy_amount:,.2f}",
            f"- 净现金流变动: ¥{self.estimated_net_cash_flow:,.2f}",
            "",
            "| 标的代码 | 标的名称 | 方向 | 数量(股) | 参考价 | 预估金额 | 目标权重 | 当前权重 | 说明 |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ]
        for o in self.all_orders:
            side_badge = "🔴 卖出" if o.side == OrderSide.SELL else "🟢 买入"
            lines.append(
                f"| `{o.symbol}` | **{o.name}** | {side_badge} | {o.quantity:,} | "
                f"¥{o.estimated_price:.3f} | ¥{o.estimated_amount:,.2f} | "
                f"{o.target_weight * 100:.1f}% | {o.current_weight * 100:.1f}% | {o.reason} |"
            )
        return "\n".join(lines)

    def to_miniqmt_script(self, account_id: str = "YOUR_ACCOUNT_ID") -> str:
        """Generate standalone MiniQMT (xtquant) Python draft reference template (read-only preview)."""
        lines = [
            "# ====================================================================",
            "# CAUTION: DRAFT REVIEW TEMPLATE ONLY — DO NOT EXECUTE DIRECTLY",
            "# This script is generated for manual inspection and protocol reference.",
            "# Direct automated broker order submission is intentionally DISABLED.",
            "# Real-money rebalancing requires polling order status callbacks (成交回报),",
            "# handling order rejections (废单), and confirming released cash balance",
            "# before placing buy orders. Never rely on blind time delays.",
            "# Please review orders via CSV and submit manually in your trading terminal.",
            "# ====================================================================",
            "# Reference protocol: xtquant (MiniQMT)",
            f'# Target Account: "{account_id}"',
            "from xtquant import xtconstant",
            "from xtquant.xttrader import XtQuantTrader",
            "from xtquant.xttype import StockAccount",
            "",
            f'ACCOUNT_ID = "{account_id}"',
            "account = StockAccount(ACCOUNT_ID)",
            "",
            "def print_rebalance_review_manifest():",
            '    print("=== ETF Rotation Rebalance Review Manifest ===")',
            f'    print("Account: {account_id}")',
            '    print("Execution mode: READ_ONLY_PREVIEW (No live orders placed)")',
            "",
            "    # 1. 计划卖出指令（释放可用资金 - 仅供人工核对）",
        ]
        for o in self.sell_orders:
            code = (
                f"{o.symbol}.SH" if str(o.symbol).startswith("5") else f"{o.symbol}.SZ"
            )
            lines.append(
                f'    print("  [SELL] {code} {o.quantity} 股 @ ¥{float(o.estimated_price):.3f} (预计释放: ¥{float(o.estimated_amount):,.2f})")'
            )

        lines.append("")
        lines.append("    # 2. 计划买入指令（需在资金确认后执行 - 仅供人工核对）")
        for o in self.buy_orders:
            code = (
                f"{o.symbol}.SH" if str(o.symbol).startswith("5") else f"{o.symbol}.SZ"
            )
            lines.append(
                f'    print("  [BUY]  {code} {o.quantity} 股 @ ¥{float(o.estimated_price):.3f} (预计占用: ¥{float(o.estimated_amount):,.2f})")'
            )

        lines.extend(
            [
                "",
                '    print("=== End of Manifest: Please inspect review CSV ===")',
                "",
                'if __name__ == "__main__":',
                "    print_rebalance_review_manifest()",
            ]
        )
        return "\n".join(lines)


def generate_rebalance_plan(
    *,
    target_weights: Mapping[Symbol, Decimal | float | int],
    current_holdings: Mapping[Symbol, int],
    latest_prices: Mapping[Symbol, Decimal | float | int],
    total_equity: Decimal | float | int,
    lot_size: int = 100,
    min_trade_amount: Decimal | float | int = 100,
    cash_buffer_ratio: Decimal | float | int = Decimal("0.005"),
    symbol_names: Mapping[Symbol, str] | None = None,
) -> RebalancePlan:
    """Calculate target order differences and produce a structured RebalancePlan.

    Args:
        target_weights: Target allocation percentage per symbol (0.0 to 1.0).
        current_holdings: Number of shares currently held.
        latest_prices: Latest traded price per symbol.
        total_equity: Total account equity (cash + holdings market value).
        lot_size: Minimum lot increment for buys (default: 100 for A-shares).
        min_trade_amount: Minimum transaction value (CNY) to trigger an order.
        cash_buffer_ratio: Reserved cash safety buffer to absorb slippage (default: 0.5%).
        symbol_names: Optional human-readable name lookup for symbols (e.g. 510300 -> 沪深300ETF).
    """
    total_eq = Decimal(str(total_equity))
    min_amount = Decimal(str(min_trade_amount))
    buffer_ratio = Decimal(str(cash_buffer_ratio))

    if total_eq <= 0:
        raise ValueError("rebalance_total_equity_must_be_positive")
    if lot_size <= 0:
        raise ValueError("rebalance_lot_size_invalid")

    # Collect all relevant symbols (either currently held or in target)
    all_symbols = sorted(
        set(target_weights.keys()) | set(current_holdings.keys()),
        key=lambda s: str(s),
    )

    sells: list[RebalanceOrderProposal] = []
    buys: list[RebalanceOrderProposal] = []

    # Effective investable equity after deducting slippage buffer
    effective_equity = total_eq * (Decimal(1) - buffer_ratio)

    for sym in all_symbols:
        raw_target_wt = Decimal(str(target_weights.get(sym, Decimal(0))))
        curr_shares = int(current_holdings.get(sym, 0))

        if sym not in latest_prices:
            if curr_shares > 0 or raw_target_wt > 0:
                raise ValueError(f"rebalance_price_missing:{sym}")
            continue

        price = Decimal(str(latest_prices[sym]))
        if price <= 0:
            raise ValueError(f"rebalance_price_invalid:{sym}")

        resolved_name = (
            symbol_names.get(sym) if symbol_names and sym in symbol_names else None
        )
        name: str = resolved_name or _DEFAULT_SYMBOL_NAMES.get(str(sym), str(sym))

        curr_value = Decimal(curr_shares) * price
        curr_weight = (curr_value / total_eq).quantize(Decimal("0.0001"))

        # Desired target value and target shares
        target_val = effective_equity * raw_target_wt
        # For buy orders, quantity must strictly be multiples of 100
        desired_shares = int((target_val / price) // Decimal(lot_size)) * lot_size

        diff_shares = desired_shares - curr_shares

        # Case 1: Target is 0, sell all existing holdings completely
        if raw_target_wt == 0 and curr_shares > 0:
            sell_amt = Decimal(curr_shares) * price
            sells.append(
                RebalanceOrderProposal(
                    symbol=sym,
                    name=name,
                    side=OrderSide.SELL,
                    quantity=curr_shares,
                    estimated_price=price,
                    estimated_amount=sell_amt,
                    target_weight=Decimal(0),
                    current_weight=curr_weight,
                    reason="清仓退出",
                )
            )
        # Case 2: Reduce position
        elif diff_shares < 0:
            # Round reduction to lot_size, but leave no odd fractional residue if possible
            sell_qty = abs(diff_shares)
            if sell_qty >= lot_size or sell_qty == curr_shares:
                sell_amt = Decimal(sell_qty) * price
                if sell_amt >= min_amount:
                    sells.append(
                        RebalanceOrderProposal(
                            symbol=sym,
                            name=name,
                            side=OrderSide.SELL,
                            quantity=sell_qty,
                            estimated_price=price,
                            estimated_amount=sell_amt,
                            target_weight=raw_target_wt,
                            current_weight=curr_weight,
                            reason="减仓调权",
                        )
                    )
        # Case 3: Increase or open position
        elif diff_shares > 0:
            buy_qty = diff_shares
            # Must be integer multiple of lot_size
            buy_qty = (buy_qty // lot_size) * lot_size
            buy_amt = Decimal(buy_qty) * price
            if buy_qty > 0 and buy_amt >= min_amount:
                buys.append(
                    RebalanceOrderProposal(
                        symbol=sym,
                        name=name,
                        side=OrderSide.BUY,
                        quantity=buy_qty,
                        estimated_price=price,
                        estimated_amount=buy_amt,
                        target_weight=raw_target_wt,
                        current_weight=curr_weight,
                        reason="加仓买入" if curr_shares > 0 else "建仓买入",
                    )
                )

    total_sell = sum((o.estimated_amount for o in sells), Decimal(0))
    total_buy = sum((o.estimated_amount for o in buys), Decimal(0))
    net_cash_flow = total_sell - total_buy
    turnover = (total_sell + total_buy) / (Decimal(2) * total_eq)

    return RebalancePlan(
        sell_orders=sells,
        buy_orders=buys,
        total_sell_amount=total_sell,
        total_buy_amount=total_buy,
        estimated_net_cash_flow=net_cash_flow,
        turnover_ratio=turnover.quantize(Decimal("0.0001")),
    )
