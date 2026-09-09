# Karkinos Strategy 兼容说明

> Status: legacy compatibility. 新的研究能力按 [ARCHITECTURE.md](../ARCHITECTURE.md) 的 `Dataset -> Alpha/Model -> Forecast -> Portfolio` 架构研发。

当前 `strategy/` 仍是已实现 backtest/runtime 的兼容层，不会立即删除。

## 当前内置基线

代码中保留的 built-in strategies 包括：

- `dual_ma`
- `monthly_rebalance`
- `bollinger`
- `rsi`
- `donchian_breakout`
- `time_series_momentum`
- `volatility_target_trend`
- `pairs_ratio_mean_reversion`

它们用于 regression、研究基线和现有 UI/runtime 兼容，不代表经过实盘验证的 Alpha。

## 当前扩展契约

私有兼容策略可以继续放在 `strategy/extensions/`，或使用 `KARKINOS_STRATEGY_EXTENSION_DIR`。

现有 manifest 使用 `karkinos.strategy.v1`，声明 strategy id、class path、typed parameters、asset/frequency scope 和验证信息。该 schema version 不是产品 roadmap 版本。

现有 Strategy 输出通常是 signal/target-weight 语义；后续仍经过 backtest、cost、risk、paper/shadow 和 human gate。

## 不再扩大的抽象

新研究功能不继续把下面内容塞进 Strategy class：

```text
feature engineering
alpha diagnostics
model training
portfolio optimization
execution simulation
capital authority
```

这些能力分别由 Research、Portfolio、Simulation/Execution 和 Financial Control contexts 拥有。

## 迁移方向

```text
Legacy Strategy
     |
     +-> extract signal logic -> AlphaSpec / ModelSpec
     +-> output               -> ForecastSet
     +-> sizing               -> Portfolio policy
     +-> trade planning       -> RebalancePlan
     +-> execution            -> shared simulation/execution
```

旧 Strategy 在迁移完成前继续通过 compatibility adapter 运行；不要为了目录整洁一次性重写现有策略。

## 验收原则

Strategy/Alpha 的价值不能用单次回测总收益判断。新的研究 gate 统一使用 point-in-time dataset、rolling OOS、after-cost、exposure、turnover、capacity 和 shadow evidence。

需要了解当前实现参数时直接查看 `strategy/builtins/` 和对应测试；不再在本文复制每个策略几十行说明。
