"""BacktestViewer — matplotlib 资金曲线可视化。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from backtest.result import BacktestResult


class BacktestViewer:
    """回测结果可视化。"""

    @staticmethod
    def plot_equity_curve(result: BacktestResult, save_path: str | None = None) -> None:
        """绘制资金曲线。"""
        import matplotlib.pyplot as plt

        if not result.equity_curve:
            return

        timestamps = [t for t, _ in result.equity_curve]
        equities = [float(e) for _, e in result.equity_curve]

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(timestamps, equities, linewidth=1.5, label="Equity")
        ax.axhline(y=float(result.initial_cash), color="gray", linestyle="--", label="Initial Cash")
        ax.set_title("Backtest Equity Curve")
        ax.set_xlabel("Date")
        ax.set_ylabel("Equity (CNY)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150)
            plt.close(fig)
        else:
            plt.show()
