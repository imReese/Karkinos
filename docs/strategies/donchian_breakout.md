# 唐奇安通道：`donchian_breakout`

[源码](../../strategy/builtins/donchian_breakout.py) · [策略目录与执行约定](README.md)

使用此前 bar 的最高价、最低价构造通道，以当前收盘价判断突破或退出。

## 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `entry_window` | `55` | 进入通道使用的此前 bar 数 |
| `exit_window` | `20` | 退出通道使用的此前 bar 数 |
| `target_weight` | `1.0` | 进入时发布的目标权重 |
| `strategy_id` | `"donchian_breakout"` | 信号所属策略 ID |

## 信号规则

判断时不将当前 bar 的高低价纳入通道；完成判断后才把它们加入历史：

- 未持有，且已有 `entry_window` 根历史 bar：当前收盘价严格高于这些 bar 的最高价时，发布 `target_weight`。
- 已持有，且已有 `exit_window` 根历史 bar：当前收盘价严格低于这些 bar 的最低价时，发布 `0.0`。
- 等于通道边界不触发。

默认进入信号最早出现在第 56 根 bar。回测启用持仓反馈后，“持有”由实际持仓数量是否大于零决定；纯信号扫描使用内部信号状态。该实现不包含 ATR 仓位计算、加仓或做空。

## 初始化示例

```python
from core.event_bus import EventBus
from core.types import Symbol
from strategy.builtins.donchian_breakout import DonchianBreakoutStrategy

strategy = DonchianBreakoutStrategy(
    EventBus(), entry_window=55, exit_window=20, target_weight=1.0
)
strategy.on_init([Symbol("510300")])
```

示例只初始化策略。通道退出是收盘后生成的目标，不能保证在通道价成交；执行与成本设置见[策略目录](README.md#信号与执行)。
