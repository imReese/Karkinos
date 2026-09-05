# Karkinos 目标

本文定义 Karkinos 的长期产品目标和不可跨越的边界。当前开发顺序只在 [PLAN.md](PLAN.md) 维护。

## 北极星

Karkinos 是面向中国市场的、本地优先的个人量化研究与投资系统。

它不承诺盈利；它要持续提高一个严肃个人投资者发现、验证、部署和淘汰投资 edge 的能力：

> Karkinos 能否把原始市场数据稳定地转化为可复现、样本外有效、扣除真实成本后仍具有正期望的组合，并在 edge 衰减时及时识别并停止继续依赖它？

## 最终闭环

```text
Market Data
-> Point-in-time Dataset
-> Feature / Alpha / Model
-> Forecast
-> Portfolio Target
-> Rebalance Plan
-> Risk
-> Simulation / Paper / Shadow
-> Human-supervised Execution
-> Accounting / Reconciliation
-> Attribution
-> Alpha Health / Retirement
```

研究负责产生 edge；组合构建负责把 edge 变成资本配置；执行、账本、风控、对账和权限负责避免把研究优势之外的错误放大成真实损失。

## 产品优先级

长期优先级固定为：

1. **Edge quality**：先证明预测与组合在严格样本外、成本和容量约束后仍有价值。
2. **Reproducibility**：同一数据、代码、参数和时间边界可以确定性重放。
3. **Reliability**：单一 provider、worker、任务或 candidate write 的失败不能无理由拖垮整个产品。
4. **Financial integrity**：账户、账本、估值、费用、订单、成交和对账只有一个 canonical owner。
5. **Capital safety**：真实资金权限默认关闭、人工监督、有界、可暂停、可撤销。
6. **Operator clarity**：用户必须知道系统看到了什么、相信什么、阻断什么，以及下一步能安全做什么。

## 数据与研究边界

- 所有核心研究数据必须有明确的 market/event time、可用时间、采集时间、来源和 revision identity。
- Universe、财务数据、复权、停牌和行业成分必须按 point-in-time 语义构建，禁止 survivorship 和 future leak。
- 回测必须绑定冻结数据集、代码/模型版本、参数、成本、OOS 结果和限制。
- Alpha 的基础输出优先是预测分数、预期收益或概率，不是 BUY/SELL。
- Strategy 不再作为一切研究的中心概念；最终部署对象由 Alpha/Model、Portfolio Policy、Risk/Execution Policy 和证据共同组成。
- AI 可以提出假设和实验，但 canonical 指标、回测、组合和风险结果必须由本地确定性代码计算。

## 财务与交易边界

- Provider 响应和运行时缓存只是输入；只有验证、持久化并发布后的事实可以进入 authoritative reads。
- Portfolio、ledger、valuation、PnL、fees、orders、fills 和 reconciliation 都有唯一 canonical owner。
- “最新尝试”与“最后一次成功状态”必须分开；失败的新写入不得破坏已验证的 last-good 读取。
- 需要最新证据的 Decision、Risk、Order 和 Execution 必须继续 fail closed。
- Backtest、paper、shadow 和未来 live 应共享 T+1、lot、fees、limits、suspension、order/fill 和 accounting 语义。
- 外部 side effect 必须有持久 idempotency identity、可恢复状态和后续 reconciliation。

## 权限与隐私边界

- 真实资金提交默认关闭，live-like 流程默认逐单人工确认。
- AI、策略、研究结果和 UI 操作都不能自行授予交易或资本权限。
- 权限可以自动暂停或收窄，但不能自行续期、恢复、放宽或扩大资本。
- Karkinos 不保存券商密码，不允许策略/AI 直接调用券商。
- 私有账户导出、凭证、运行数据库、日志和截图不得进入源码仓库。

## 成功标准

Karkinos 的工程成功应能持续证明：

- 研究数据和实验可以按 exact identity 重放；
- Alpha/Model 在多个 OOS 窗口、真实成本和容量敏感性下仍有稳定证据；
- Portfolio Construction 能解释收益、风险、换手、成本和约束之间的取舍；
- shadow 与研究假设的偏差可以量化；
- PnL 可以归因到市场/风格暴露、Alpha、组合构建和执行成本；
- edge 衰减可以被识别、降权、隔离或淘汰；
- 单个外部依赖或后台任务故障只影响对应功能域；
- 任何真实资金权限都可观察、可过期、可暂停、可撤销且不会自行扩大。

## 非目标

- 投资建议或保证收益。
- 高频、超低延迟或交易所级 tick 基础设施。
- 永久授权、无人值守的全账户自动交易。
- 近期建设机构级多账户 OMS、策略市场或社交平台。
- 为了架构审美进行微服务化、分布式化或全量语言重写。
- 把 broker integration、AI 对话或 UI 页面数量当成投资 edge。
