# Karkinos Product Design

## 1. Product model

Karkinos 的界面围绕量化研究与投资闭环组织，而不是围绕后端 package、券商功能或 AI 对话组织。

用户进入产品后应能够回答：

1. 数据和系统现在是否可信、截至什么时间？
2. 当前 Financial Book 和组合状态是什么？
3. 最近有哪些研究结果，哪些已经成为 Published Forecast？
4. 当前 Portfolio Target 与实际组合有什么差异？
5. Risk 是否允许当前计划继续？
6. Backtest / Paper / Shadow 的结果与研究预期为什么不同？
7. 哪些 Alpha / Model 正在增强、衰减或需要重新研究？

## 2. Information architecture

推荐的信息架构按投资工作流组织：

```text
Today

Data
  Health
  Datasets

Research
  Experiments
  Forecasts
  Backtests

Portfolio
  Current Book
  Targets
  Rebalance
  Risk

Evaluate
  Paper / Shadow
  Attribution
  Alpha Health

System
  Settings
  Operations
```

真实交易如果未来重新进入开发范围，应作为受限能力接入现有 Portfolio、Risk、Execution 和 Accounting 边界，而不是成为产品导航中心。

## 3. Today

Today 是整个投资工作流的摘要。

优先展示：

```text
Data readiness / freshness
Current financial book and valuation
Research changes
Published Forecast changes
Portfolio Target / Rebalance state
Risk blockers
Recent evaluation outcomes
```

页面应明确区分“数据仍可读”和“新动作不可继续”。最新刷新失败不应抹掉仍然有效的 last-known state。

## 4. Data

Data 页面展示市场数据和 Dataset 是否适合研究，而不是展示 provider 调用细节。

用户需要看到：

- 数据覆盖和 as-of；
- provider / source；
- freshness；
- revision 或质量异常；
- Dataset identity；
- point-in-time 可用性；
- blocker 和安全的下一步操作。

## 5. Research

Research 以 Experiment 和 evidence 为核心。

一个 Experiment 应能够关联：

```text
Dataset
Feature / Alpha / Model identity
parameters
Evaluation
Research Evidence
Published Forecast (if any)
```

AI 是研究入口之一，可以提出 hypothesis、创建实验和解释结果，但不获得额外的视觉或金融 authority。

Candidate experiment 和 Published Forecast 必须在界面上有明确区别。

## 6. Portfolio

Portfolio UI 明确区分：

```text
Published Forecast
Current Financial Book
Portfolio Target
Risk Decision
Rebalance Plan
```

Portfolio Target 应能够追溯到 forecast、portfolio policy、风险/暴露估计和成本假设。

Risk block 或要求重新计算时，界面不应悄悄展示一个被 Risk 改写过但来源不明的 target。

## 7. Evaluate

Backtest、Paper 和 Shadow 都属于评估研究和组合意图的环境，但它们不是同一种执行模式。

- Backtest：历史模拟；
- Paper：forward-time simulated execution；
- Shadow：观察 target / plan 的实际市场结果，可以不生成模拟订单；
- Attribution：解释 outcome 来自 Alpha、组合构建、风险暴露、成本、执行还是残差；
- Alpha Health：持续判断 edge 是否仍有证据支持。

用户应能够从一个 outcome 回到原始 Dataset、Experiment、Forecast 和 Portfolio Target。

## 8. Financial state

界面中的现金、持仓、费用、PnL 和估值来自明确的 Financial Book。

Backtest、Paper、Shadow 和实际账户状态不得在 UI 中混成一个看似统一但实际来源不同的账户视图。需要比较时，应明确 book / environment identity。

## 9. Status and evidence

关键状态至少表达：

```text
as_of
source / identity
freshness
quality or blocker
safe next action
```

关键数字应能从摘要进入更详细的 evidence，而不是在主视图堆完整 hash、原始 payload 或内部状态机字段。

## 10. Interaction hierarchy

不同操作的权威等级必须在交互上可区分：

```text
read / query
refresh / ingestion
research mutation
portfolio proposal
financial mutation
authority mutation
```

Research 或 AI 操作不能因为界面流程连贯而看起来等同于真实资金操作。

## 11. Visual system

继续使用 Catppuccin Latte / Mocha 方向，并优先服务信息层级：

- 表格用于可比较记录；
- timeline 用于事件；
- chart 用于时间或分布关系；
- card 用于真正独立的对象或操作；
- 避免 card-in-card、装饰性 glow 和营销式留白；
- 财务数字使用 tabular numerals；
- 状态不能只靠颜色表达。

Desktop 默认保留文字导航；移动端按任务优先级重新组织，不机械堆叠桌面布局。

## 12. Performance and consistency

- 页面读取优先消费已经持久化的 canonical / derived state，不在普通查询中隐式触发 provider 或 AI；
- 同一个金融或研究概念在不同页面使用一致的格式、identity 和 status semantics；
- 大数据表采用分页、虚拟化或服务端查询；
- Research chart 消费平台计算结果，不在浏览器重新计算 canonical metrics；
- 单个 widget 的失败不应吞掉其他仍然可用的页面状态。
