# 配对比率：`pairs_ratio_mean_reversion`

[源码](../../strategy/builtins/pairs_ratio_mean_reversion.py) · [策略目录与执行约定](README.md)

以两资产收盘价比率的滚动 z-score，在 A、B 两条多头腿间切换。当前实现不估计对冲比率、不做协整检验，也不持有空头腿。

## 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `symbol_a` | `""` | A 腿代码；为空时取初始化池的第一个标的 |
| `symbol_b` | `""` | B 腿代码；为空时取初始化池的第二个标的 |
| `lookback_period` | `60` | 比率均值和标准差的观察数 |
| `entry_z` | `2.0` | 向单腿切换的 z-score 阈值 |
| `exit_z` | `0.5` | 返回中性权重的绝对 z-score 阈值 |
| `pair_weight` | `1.0` | 单腿模式中该腿的目标权重 |
| `neutral_weight` | `0.5` | 中性模式中每一腿的目标权重 |
| `strategy_id` | `"pairs_ratio_mean_reversion"` | 信号所属策略 ID |

## 信号规则

两腿同一日期的行情均到达后，每日最多记录一次 `ratio = close_a / close_b`。两腿未确定或 B 腿价格非正时不计算。至少收集 `lookback_period` 个比率后，使用包含当期比率的窗口计算均值和总体标准差；标准差为零时不发布目标。

`z = (ratio - mean_ratio) / std` 的判断按以下顺序进行：

| 条件与模式变化 | A 目标 | B 目标 |
| --- | --- | --- |
| `z <= -entry_z`，当前不是 A 单腿模式 | `pair_weight` | `0.0` |
| `z >= entry_z`，当前不是 B 单腿模式 | `0.0` | `pair_weight` |
| `abs(z) <= exit_z`，当前不是中性模式 | `neutral_weight` | `neutral_weight` |

初始模式为中性，但初始化不发布中性目标。因此，首次在中性区间内不会自动买入两腿。模式可以直接从 A 单腿切换至 B 单腿，无需先经过中性区。

策略只在模式变化时尝试发布与上次不同的目标，记录的是已发信号，不是实际持仓。两腿目标分别执行，不保证同时成交；被阻止或部分成交后没有自动持续挂单。`neutral_weight` 是每腿权重，两腿合计为其两倍。

## 初始化示例

```python
from core.event_bus import EventBus
from core.types import Symbol
from strategy.builtins.pairs_ratio_mean_reversion import (
    PairsRatioMeanReversionStrategy,
)

strategy = PairsRatioMeanReversionStrategy(
    EventBus(), symbol_a="510300", symbol_b="510500", lookback_period=60
)
strategy.on_init([Symbol("510300"), Symbol("510500")])
```

示例只说明两腿输入方式，不表示这对资产满足均值回归假设。执行与成本设置见[策略目录](README.md#信号与执行)。
