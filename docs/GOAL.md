# Karkinos 目标

## 北极星

Karkinos 是面向中国市场的个人量化研究与投资系统。它的长期目标不是“功能很多”，也不是保证盈利，而是回答：

> Karkinos 能否持续把原始市场数据变成可复现、样本外有效、扣除真实成本后仍具有正期望的投资组合，并在优势消失时及时识别出来？

## 产品主链

```text
市场数据
-> point-in-time 数据集
-> Alpha 发现与验证
-> Alpha 组合
-> 组合构建
-> 真实约束下的回测 / 执行模拟
-> paper / shadow
-> 每日决策与风险门禁
-> 人工监督的受控执行
-> 归因、复盘、Alpha 衰减与淘汰
```

研究产生 edge；风险、审计和权限系统负责不把 edge 之外的错误放大成真实损失。

## 必须长期成立的边界

### 数据与研究

- 所有可用于研究的核心数据必须有明确时间语义、来源、版本和可重放身份。
- 回测必须绑定冻结数据、参数、成本、OOS 结果和限制，不能只展示漂亮收益。
- Alpha/策略首先是研究证据；没有通过数据、成本、风险和 shadow 验证前，不是交易权限。
- BUY/SELL 不是 Alpha 的基础输出。基础输出应优先是可比较的预测分数、目标收益或组合目标。

### 财务事实

- Portfolio、ledger、valuation、PnL、fees、orders、fills 和 reconciliation 各有唯一 canonical owner。
- Provider 响应和运行时缓存只是输入；只有验证并持久化后的事实可以进入 authoritative reads。
- 缺失、过期、partial、ambiguous、conflicting 或 unreconciled 的证据必须显式可见。

### 可用性与安全

- “新的写入失败”不得破坏已经验证成功的 last-known-good 读取状态。
- 需要最新证据的 Decision、Risk、Order 和 Execution 仍必须 fail closed。
- 真实资金提交默认关闭；live-like 流程默认逐单人工确认。
- AI、策略、研究结果和 UI 行为都不能自行授予交易或资本权限。
- Karkinos 不保存券商密码，不允许策略/AI 直接调用券商。

## 成功标准

Karkinos 的工程成功应能持续证明：

- 同一研究输入可以确定性重放并得到同一结果；
- Alpha 在严格 OOS、成本和容量约束下仍有统计证据；
- Portfolio Construction 能说明收益、风险、换手和成本之间的取舍；
- shadow 结果与回测假设的偏差可量化；
- live/paper PnL 可以归因到市场、风险暴露、Alpha 和执行成本；
- Alpha 失效能够被识别、降权、隔离或淘汰；
- 单个 provider、scheduler、worker 或 publication attempt 的失败不会无理由拖垮整个产品；
- 任何真实资金权限都可观察、可过期、可暂停、可撤销，并且不会自行扩大。

## 非目标

- 投资建议或保证收益。
- 高频、超低延迟或交易所级 tick 基础设施。
- 永久授权、无人值守的全账户自动交易。
- 策略或 AI 直连券商。
- 自动扩大资本。
- 近期建设机构级多账户 OMS、策略市场或社交平台。

当前优先级和实施顺序只在 [PLAN.md](PLAN.md) 维护。
