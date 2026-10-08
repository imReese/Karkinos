# 有界宏观风险预算

策略 ID：`risk_parity_macro`。实现见 [策略](../../strategy/builtins/risk_parity_macro.py) 和 [数值函数](../../strategy/risk_budget.py)。它是供回测的多头资产配置基线，不是宏观预测模型。

## 计算与数据要求

策略在同一时间戳的完整日线篮子上计算简单收益率的样本协方差。默认需要 61 根完整日线，每 20 个完整截面检查一次调仓，因此首次目标还取决于调仓周期。日内数据、重复、乱序、时间戳不一致或不完整截面会报错；不会用另一交易日的价格补齐当前截面。

风险预算求解使用循环坐标下降，要求有限、对称、半正定协方差、正方差和正风险预算。相对风险贡献满足指定误差后才返回权重；零方差、无法求解或未收敛会失败，不隐藏添加正则项或改用等权。算法依据 [Griveau-Billion、Richard、Roncalli 的风险预算论文](https://arxiv.org/abs/1311.4057)。

若开启趋势过滤，低于均线的非 `cash_proxy` 资产风险预算乘以 0.2，随后重新归一化。`cash_proxy` 只是篮子内豁免过滤的普通资产，仍有价格风险；本策略没有合成现金仓位，也不保证资金流向债券。

最后将权重作有界单纯形投影，满足每个资产的资本权重上下限与总和 1。这个约束步骤可能改变原风险贡献，不能把最终配置称为精确等风险贡献。舍入调整也必须留在上下限内。

## 参数与运行

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `lookback_period` | 60 | 协方差使用的日收益率数量 |
| `rebalance_interval` | 20 | 从输入起点计数的完整日截面间隔 |
| `trend_filter` | true | 是否降低跌破均线资产的风险预算 |
| `trend_ma_period` | 60 | 趋势均线的完整日线数量 |
| `min_asset_weight` | 0.05 | 单资产资本权重下限 |
| `max_asset_weight` | 0.60 | 单资产资本权重上限 |
| `cash_proxy` | `511010` | 篮子中豁免趋势过滤的标的；null 关闭豁免 |
| `risk_budgets` | null | 覆盖完整篮子的正风险预算字典；null 为相等预算 |

至少需要两个不同标的，且上下限必须容许满仓组合。配置了 `cash_proxy` 时必须在输入篮子中提供该标的；自定义预算必须完整覆盖篮子，不接受部分字典和未声明标的。

通过回测页面选择该策略，配置完整股票/ETF 篮子、已发布 Dataset、成本和成交量参与率，再运行并保存报告。HTTP 回测严格传播该策略的行情与求解错误，并在每个交易日结束时检查篮子完整性，失败不会保存成成功的空仓报告。失败前已产生的模拟订单和成交可能按现有引擎语义保留，执行模式标为 `backtest`，不代表实际账户交易。独立前向观察目前仍只支持 PLAN 中列出的策略，新策略尚未进入该能力范围。

Python 研究可按现有注册表创建实例：

```python
from core.event_bus import EventBus
from core.types import Symbol
from strategy.registry import StrategyRegistry
import strategy.builtins  # 注册内置策略

strategy = StrategyRegistry.create(
    "risk_parity_macro",
    EventBus(),
    lookback_period=60,
    rebalance_interval=20,
    cash_proxy="511010",
    min_asset_weight=0.05,
    max_asset_weight=0.60,
)
strategy.on_init([Symbol("510300"), Symbol("511010"), Symbol("518880")])
```

直接驱动事件时，每日全部 bar 后调用 `strategy.require_complete_session(session_date)`，包括最后一日。使用 `BacktestEngine` 时应启用 `strict_event_errors=True` 并把该方法传给 `session_completed`；否则事件总线的默认容错可能隐藏策略错误。策略输出仍是目标权重，后续组合、风控和模拟成交负责把目标转成实际持仓。

## 研究限制

协方差变化、股债相关性上升和成交成本可能破坏历史配置效果。价格收益与总收益口径、分红处理、标的池历史成员、费用和滑点须由输入和回测配置明确。用冻结参数、独立样本和相同成本的简单配置基准比较净收益与回撤；本文参数是实现默认值，不是收益最优推荐。
