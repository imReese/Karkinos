# 双均线：`dual_ma`

[源码](../../strategy/builtins/dual_ma.py) · [策略目录与执行约定](README.md)

对每个标的分别计算收盘价短、长简单移动平均线，均线关系变化时发布进入或退出目标。

## 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `short_period` | `5` | 短均线 bar 数 |
| `long_period` | `20` | 长均线 bar 数及预热长度 |
| `strategy_id` | `"dual_ma"` | 信号所属策略 ID |

## 信号规则

两个均线窗口均包含当前收盘价。收到 `long_period` 根 bar 后，首次只记录 `short_ma > long_ma` 是否成立，不立即建仓；从下一根 bar 起比较状态变化：

- 从“不高于”变为“高于”：发布目标权重 `1.0`。
- 从“高于”变为“不高于”：发布目标权重 `0.0`，两均线相等也属于该退出条件。
- 状态不变：不发布新目标。

该策略记录的是均线状态，不以成交结果判断是否再次发送目标。某次买入被阻止后，持续处于短均线高于长均线的状态不会自动重试。多个标的各自输出 `1.0` 时，也不表示组合已完成等权配置。

## 初始化示例

```python
from core.event_bus import EventBus
from core.types import Symbol
from strategy.builtins.dual_ma import DualMAStrategy

strategy = DualMAStrategy(EventBus(), short_period=5, long_period=20)
strategy.on_init([Symbol("510300")])
```

窗口长度按传入 bar 计数。使用日线时分别对应 5、20 根日线；更换频率会改变时间跨度。该示例不获取行情或运行回测，执行与成本设置见[策略目录](README.md#信号与执行)。
