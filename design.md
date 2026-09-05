# Karkinos Product Design

本文定义最终产品的信息架构和 UI invariant。它不记录某次视觉审计、token 数量或页面改版清单；具体实现问题进入 issue/PR。

## 1. 产品界面要回答什么

Karkinos 首先是一个量化研究与投资操作系统，不是券商首页，也不是 AI 聊天壳。

用户进入产品后应快速回答：

1. 系统和数据现在是否可信、截至什么时间？
2. 当前账户/组合是什么状态？
3. 最近的研究 edge 是什么，证据有多强？
4. 目标组合与当前组合差在哪里？
5. shadow / 实际表现为什么偏离研究？
6. 现在有什么 blocker，下一步安全动作是什么？
7. 是否存在任何资本权限；如果有，它的边界是什么？

## 2. 最终信息架构

目标导航按投资工作流而不是后端模块组织：

```text
Today
  Overview

Data
  Data Health
  Datasets

Research
  Alpha Lab
  Experiments
  Backtests

Portfolio
  Construction
  Targets
  Attribution

Operate
  Shadow
  Account
  Risk
  Operations
  Trading Review (gated)

System
  Settings
```

当前页面可以渐进映射，不要求一次性重写 router。

## 3. Today

Today 是 operator summary，不是十几个 subsystem card。

优先级：

```text
System/Data readiness
Current valuation/account state
Research/portfolio change
Action blockers
Safe next action
```

若最新数据刷新失败但 last-good 仍可读，应显示：

```text
Valuation: verified as of <time>
Latest refresh: failed
Read: available
New decision: blocked
```

而不是把整个页面变成“加载失败”。

## 4. Research

Research 页面围绕 Experiment，而不是围绕“AI 生成一个策略”。

Alpha/Experiment 列表必须能看到：

- Dataset identity / as-of；
- Alpha/Model version；
- OOS status；
- after-cost diagnostics；
- exposure / turnover / capacity；
- parent/child experiment lineage；
- promoted / quarantined / retired state。

AI 入口只是“提出实验/解释证据”的辅助入口，不获得额外视觉 authority。

## 5. Portfolio

Portfolio UI 明确区分：

```text
Forecast
PortfolioTarget
Current holdings
RebalancePlan
```

任何 target weight 都必须能追溯到 Alpha/Model、风险约束和成本取舍。

复杂 optimizer 的结果要能与 simple baseline 并列比较，不能只显示“最优组合”。

## 6. Shadow / Attribution

Shadow 是 Profit Engine 的主运营页面之一。

至少展示：

- frozen target / plan identity；
- expected vs realized return；
- expected vs realized turnover/cost/slippage；
- untradable/partial/no-fill；
- exposure drift；
- Alpha health；
- attribution residual。

用户应该能从一次亏损一路 drill down 到“市场、风险暴露、Alpha、组合构建、执行成本或未解释残差”。

## 7. Account / Risk / Trading

Account 只展示 canonical financial facts。

Risk 明确区分：

- portfolio/exposure diagnostics；
- pre-trade/action blockers；
- runtime/authority blockers。

Trading Review 默认是 gated 的最终步骤，不是主导航中心。研究结果、AI output、shadow pass 都不能因为 UI 连贯性被表现成“已获授权”。

## 8. 状态语言

所有页面共享两类状态：

```text
Read availability:
ready | degraded/stale | unavailable

Action readiness:
ready | blocked
```

并共享：

```text
as_of
last_success
latest_attempt
blockers
safe_next_action
```

不要为每个页面发明不同的“正常/异常/未知”词汇。

## 9. Evidence UI

任何关键数值都应能回答：

- value；
- as-of；
- source/identity；
- quality/freshness；
- blocker；
- drill-down evidence。

身份和时间默认使用人类可读摘要；完整 fingerprint 放详情/drawer，不在主视图堆哈希。

## 10. Interaction hierarchy

- Query/read：无确认，不产生 side effect。
- Ingestion/refresh：显式 command，展示 run status。
- Research mutation：创建 experiment/artifact，不影响资本。
- Financial mutation：明确 preview / confirm / apply。
- Authority mutation：独立危险区、强确认、显示 scope/expiry。

相同按钮样式不能让这些行为看起来等价。

## 11. Layout

保留当前 Catppuccin Latte / Mocha 方向，但视觉系统服务于信息层级：

- 表格用于可比较记录；
- timeline 用于事件；
- gate matrix 用于证据和 blocker；
- chart 用于时间/分布关系；
- card 只用于真正独立对象或危险操作；
- 避免 card-in-card、装饰性 glow、大圆角和营销式留白；
- 财务数字使用 tabular numerals；
- 状态不能只靠颜色表达。

Desktop 默认有文字导航；mobile 按 operational priority 重排，不机械堆叠 desktop layout。

## 12. 页面性能与一致性

- 页面首次读取只消费 persisted projections，不隐式触发 provider。
- 同一 canonical value 在不同页面使用相同 formatter、status taxonomy 和 identity。
- 大数据表采用虚拟化/分页/服务端查询；不要把 full-market frame 传进浏览器。
- Research charts 消费已发布 artifact，不在浏览器重算 canonical metrics。
- Error boundary 必须保留其他可用 workspace，不让单 widget 故障吞掉整页。

## 13. 设计变更规则

只有长期信息架构、交互 authority、状态语言、视觉 invariant 改变时才更新本文。

组件 token、某页像素调整、审计计数、截图差异和一次性 cleanup 属于代码/issue/PR，不写回 master design。
