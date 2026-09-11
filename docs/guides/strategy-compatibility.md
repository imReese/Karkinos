# Karkinos Strategy 兼容说明

> Status: legacy compatibility guide.

当前 `strategy/` 仍承载已实现 backtest/runtime 的兼容能力。新的研究能力按照
[ARCHITECTURE.md](../ARCHITECTURE.md) 的 Dataset -> Research -> Published Forecast -> Portfolio 路径发展。

## 当前基线策略

现有 built-in strategies 主要用于 regression、研究 baseline 和现有 UI/runtime 兼容。它们不因为被内置就自动成为经过验证的 Alpha。

当前代码中的策略和参数以 `strategy/` 实现及其测试为准。

## 现有扩展契约

兼容策略仍可以通过现有 extension 机制加载。现有 `karkinos.strategy.v1` 是兼容 schema version，不是产品 roadmap 版本。

旧 Strategy 输出可能使用 signal 或 target-weight 语义；这些输出仍必须经过相应的研究评估、Portfolio、Risk 和 Simulation/Execution 边界，不能直接获得资本权限。

## 不再扩大的 Strategy 职责

新的研究能力不继续把以下职责塞进 Strategy class：

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

这些职责分别属于 Research、Portfolio、Risk、Simulation、Execution 和 Accounting 边界。

## 迁移方向

```text
Legacy Strategy
     |
     +-> predictive logic -> Research / Alpha / Model
     +-> research output  -> Published Forecast
     +-> sizing           -> Portfolio
     +-> trade planning   -> Rebalance Plan
     +-> execution        -> Simulation / Execution
```

迁移以真实产品价值和调用方为依据，不为目录整洁进行一次性重写。

## Evaluation standard

Strategy / Alpha 的价值不能用单次回测总收益判断。新的研究评估应关注 point-in-time 数据、OOS、after-cost、exposure、turnover、capacity 和 robustness 等证据。
