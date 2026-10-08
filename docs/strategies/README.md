# 内置策略使用说明

内置策略用于研究基线、回归验证和现有回测/runtime 兼容。下表说明当前源码的行为；注册成功或回测盈利均不代表已经验证投资优势。领域边界见 [Strategy 兼容说明](../guides/strategy-compatibility.md)。

## 策略目录

| 策略 ID | 当前逻辑 | 说明或源码 |
| --- | --- | --- |
| `dual_ma` | 收盘价短、长均线关系变化时发送目标权重 | [双均线](dual_ma.md) |
| `etf_rotation` | 按动量或风险调整动量排序，分配 Top-K 槽位 | [ETF 轮动](etf_rotation.md) |
| `bollinger` | 触及下轨进入，回到中轨退出 | [布林带](bollinger.md) |
| `donchian_breakout` | 收盘价突破此前高点进入，跌破此前低点退出 | [唐奇安通道](donchian_breakout.md) |
| `pairs_ratio_mean_reversion` | 根据两资产价格比率，在两条多头腿间切换 | [配对比率](pairs_ratio_mean_reversion.md) |
| `risk_parity_macro` | 历史协方差、风险预算及可选趋势过滤生成配置权重 | [风险预算配置](risk_parity_macro.md) |
| `time_series_momentum` | 回看收益率超过进入阈值时持有，降至退出阈值时退出 | [源码](../../strategy/builtins/time_series_momentum.py) |
| `volatility_target_trend` | 正向动量过滤后，以目标波动率/历史波动率计算受上限约束的权重 | [源码](../../strategy/builtins/volatility_target_trend.py) |
| `rsi` | RSI 向上离开超卖区时进入，向下离开超买区时退出 | [源码](../../strategy/builtins/rsi.py) |
| `monthly_rebalance` | 各标的首次收到行情及月份数变化时发送预设目标权重 | [源码](../../strategy/builtins/monthly_rebalance.py) |

注册入口见 [builtins](../../strategy/builtins/__init__.py)。没有单独说明页的策略，以链接的构造函数和 `on_data` 实现为准。

## 创建实例

在仓库 Python 环境中导入内置策略完成注册，再通过 [StrategyRegistry](../../strategy/registry.py) 校验参数并创建实例：

```python
import strategy.builtins
from core.event_bus import EventBus
from core.types import Symbol
from strategy.registry import StrategyRegistry

params = StrategyRegistry.validate_params(
    "dual_ma", {"short_period": 5, "long_period": 20}
)
strategy = StrategyRegistry.create("dual_ma", EventBus(), **params)
strategy.on_init([Symbol("510300")])
```

这段代码只创建并初始化策略。回测还需要行情、标的元数据、资金和执行配置，由 [BacktestEngine](../../backtest/engine.py) 驱动。各说明页的直接构造示例也只完成初始化；默认参数用于说明当前实现，不构成参数推荐。

## 信号与执行

策略发布 `SignalEvent` 目标权重，常用入口是 [Strategy.emit_signal](../../strategy/base.py)。权重 `1.0` 表示该标的目标占组合净值的 100%，`0.0` 表示退出目标；它们不是实际成交。逐标的独立策略不会自动把多个标的的目标归一化，组合、风险及执行层还会根据资金和交易约束处理目标。

回测引擎使用完成的 bar 生成信号，在该标的时间严格更晚的 bar 收盘价基础上尝试执行。一次尝试未成交的剩余数量取消；是否再次发出目标取决于策略自身逻辑。回测会启用实际持仓反馈，纯信号扫描没有成交，使用策略维护的信号状态。

[回测 API 成本参数](../../server/contracts/http/strategy_models.py) 默认使用 5 bps 滑点和单 bar 成交量 1% 的参与率上限；这些是[显式研究假设](../../backtest/costs.py)，不是成交实测。直接构造 `BacktestEngine` 而不传执行配置时，模拟器默认零滑点、无成交量参与率限制；可显式传入 `research_execution_config()` 使用研究默认值。手续费由成本模型与标的元数据决定，策略本身不定义税费规则。

研究结果应同时检查数据可用时间、样本外表现、基准净超额、成本敏感性和后续冻结观察。策略输出与 paper 结果均不授予真实资金权限。

## 研究工具

[研究工具使用说明](research-tools.md) 包含按明确时间选择财报观察、基准相对评价，以及已有人工订单的只读 CSV 导出。这些工具服务于研究和人工检查，使用契约与限制见该页。
