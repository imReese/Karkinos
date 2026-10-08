# 布林带：`bollinger`

[源码](../../strategy/builtins/bollinger.py) · [策略目录与执行约定](README.md)

对每个标的分别计算收盘价滚动均值和标准差，触及下轨时发布进入目标，回到中轨时发布退出目标。

## 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `bb_period` | `20` | 均值和标准差窗口的 bar 数 |
| `num_std` | `2.0` | 下轨偏离均值的标准差倍数 |
| `strategy_id` | `"bollinger"` | 信号所属策略 ID |

## 信号规则

收到至少 `bb_period` 根 bar 后，用包含当前收盘价的窗口计算中轨 `ma`。标准差使用总体方差，分母为窗口长度；下轨为 `ma - num_std * std`。

- 未持有且收盘价 `<=` 下轨：发布目标权重 `1.0`。
- 已持有且收盘价 `>=` 中轨：发布目标权重 `0.0`。
- 其余情况不发布目标。上轨不参与当前进出场判断。

回测启用持仓反馈后，“持有”由实际持仓数量是否大于零决定；纯信号扫描使用内部信号状态。因此，未成交时的再次触发行为可能不同。策略没有独立的止损条件，也不根据波动率调整进入权重。

## 初始化示例

```python
from core.event_bus import EventBus
from core.types import Symbol
from strategy.builtins.bollinger import BollingerStrategy

strategy = BollingerStrategy(EventBus(), bb_period=20, num_std=2.0)
strategy.on_init([Symbol("510300")])
```

示例只初始化策略。下轨条件是计算规则，不代表价格随后会回归中轨；回测需同时检查持仓期间的损失、成本及样本外表现。执行与成本设置见[策略目录](README.md#信号与执行)。
