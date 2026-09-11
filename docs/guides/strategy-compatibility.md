# Karkinos Strategy 兼容说明

> Status: legacy compatibility.

## 当前角色

`strategy/` 保留现有 backtest/runtime 兼容。

新研究路径：

```text
Dataset
-> Research
-> Published Forecast
-> Portfolio
```

Built-in strategies 主要用于 regression、baseline 和现有 UI/runtime 兼容，不自动代表经过验证的 Alpha。

## Extension contract

- 现有 extension mechanism 继续兼容。
- `karkinos.strategy.v1` 是 schema version，不是 roadmap 版本。
- Legacy signal / target-weight 输出仍必须经过 Research、Portfolio、Risk、Simulation/Execution 边界。
- Strategy output 不授予 capital authority。

## Strategy 不再扩大的职责

```text
feature engineering
experiment evaluation
model training
portfolio optimization
risk authorization
execution simulation
accounting
capital authority
```

## 迁移映射

```text
Legacy Strategy
     |
     +-> predictive logic -> Research / Alpha / Model
     +-> research output  -> Published Forecast
     +-> sizing           -> Portfolio
     +-> trade planning   -> Rebalance Plan
     +-> execution        -> Simulation / Execution
```

## Evaluation

关注：

```text
point-in-time
OOS
after-cost
exposure
turnover
capacity
robustness
```
