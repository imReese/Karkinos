# ETF 轮动：`etf_rotation`

[源码](../../strategy/builtins/etf_rotation.py) · [策略目录与执行约定](README.md)

在给定标的池中按动量评分排序，将固定的 Top-K 权重槽位分配给合格标的。该实现按日期等待池内所有标的行情，使用日线时应保证每个标的每个日期一根 bar。

## 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `lookback_period` | `20` | 动量回看 bar 数，至少为 1 |
| `volatility_window` | `20` | 波动率使用的收益率数量，至少为 2 |
| `top_k` | `2` | 最大入选数量及权重槽位数，至少为 1 |
| `rebalance_interval` | `5` | 每隔多少个已观察日期检查调仓，至少为 1 |
| `min_momentum` | `0.0` | 最低回看收益率，`0.05` 表示 5% |
| `trend_filter_period` | `0` | 收盘均线窗口；`0` 关闭过滤 |
| `use_risk_adjusted` | `True` | 是否用年化波动率调整动量评分 |
| `cash_proxy` | `"511010"` | 接收剩余目标权重的标的；`None` 表示留现金 |
| `strategy_id` | `"etf_rotation"` | 信号所属策略 ID |

## 评分和调仓

输入池必须非空且无重复。配置 `cash_proxy` 时，池内必须包含它，否则初始化报错；运行时也需要它的行情。该标的不参与动量排序；它仍是有价格风险和交易成本的资产。

每个观察日期池内行情到齐后，若日期计数可被 `rebalance_interval` 整除，就检查调仓。候选至少需要 `max(lookback_period, volatility_window if use_risk_adjusted else 1, trend_filter_period) + 1` 根收盘价；历史不足的候选跳过。

1. 动量为 `当前收盘价 / lookback_period 根之前的收盘价 - 1`。
2. 动量低于 `min_momentum` 时剔除；开启趋势过滤后，收盘价低于包含当期价格的均线时剔除。两项等于阈值均可通过。
3. 开启风险调整时，评分为 `动量 / max(年化波动率, 0.05)`。波动率基于简单收益率、总体标准差和 `sqrt(252)`；这不是扣除无风险利率后的 Sharpe。关闭时直接使用动量。
4. 按评分降序排列，同分按标的代码排序，最多选取 `top_k` 个。
5. 每个入选标的分配约 `1 / top_k`；权重保留四位小数，舍入余量给首个入选标的。未占用槽位分配给 `cash_proxy`，未配置则留现金。例如 `top_k=2` 仅一只合格时，该标的目标为 `0.5`。

每次调仓检查都会向全部标的发送新目标，包括未入选标的的零权重。组合层据实际持仓计算差额，因此下一次调仓可以再次尝试此前未完成的目标。历史不足也可能使全部权重转向 `cash_proxy`；预热数据与评价起点应在回测输入中明确。

## 初始化示例

```python
from core.event_bus import EventBus
from core.types import Symbol
from strategy.builtins.etf_rotation import EtfRotationStrategy

strategy = EtfRotationStrategy(
    EventBus(), lookback_period=20, top_k=2, cash_proxy="511010"
)
strategy.on_init([Symbol("510300"), Symbol("510500"), Symbol("511010")])
```

示例标的仅用于演示输入契约。构造函数不获取行情，也不保证入选标的能成交；执行与成本设置见[策略目录](README.md#信号与执行)。
