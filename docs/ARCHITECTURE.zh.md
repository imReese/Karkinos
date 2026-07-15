# Karkinos 架构

[English](ARCHITECTURE.md) | [目标](KARKINOS_GOAL.zh.md) | [路线图](ROADMAP.zh.md) | [受控执行](CONTROLLED_EXECUTION_PLAN.zh.md)

## 架构原则

1. **先持久化事实，再展示。** API、Web、报告、告警与 AI 读取 canonical persisted
   projections，不独立重建财务真相。
2. **先有证据，再有权限。** 信号、报告、复核或批准都不是执行权限；只有专门门禁可以明确
   授予有界能力。
3. **Fail closed。** 缺失、过期、partial、ambiguous、conflicting 或 drifted 的证据会阻断
   受影响的操作。
4. **提议与修改分离。** Preview、review、approval、apply 与 reconciliation 是具有不同身份的
   独立命令。
5. **外部效果幂等。** 券商提交、取消、证据采集、对账与账本入账使用 canonical fingerprint
   和持久化 claim。
6. **人工监督扩展。** Runtime authority 可以自动过期、暂停、收窄或撤销，但不能自行放宽或
   续期。

## 系统分层

```text
Web UI / CLI
    |
FastAPI routes 与 application services
    |
Research | Decision | Risk | Operations | OMS | Reconciliation
    |
Canonical evidence、audit、ledger 与 valuation stores
    |
Market providers | local files | model edge | broker edge
```

### 展示层

React/Vite 产品界面与 CLI 承载操作员工作流。展示代码可以格式化 canonical values 与组织
导航，但不拥有组合计算、风控决策、权限或券商状态。

### 应用服务层

FastAPI routes 校验请求并委托给 application services。应用服务负责幂等性、事务边界、编排与
响应投影。GET 路径只读：不得隐式初始化 schema、刷新 provider、恢复 workflow 或联系券商。

### 领域层

核心领域彼此独立：

| 领域 | 负责内容 |
| --- | --- |
| 行情数据 | bars、quotes、cache/source health、snapshots、freshness |
| 组合与账本 | 现金、持仓、lots、成本基础、财务事件 |
| 研究 | 策略、实验、证据包、promotion readiness |
| 决策 | 每日候选、目标权重、阻断项、解释 |
| 风控 | 交易前与运行时风控决策、kill-switch 状态 |
| Operations | 定时运行、paper/shadow、告警、复核任务 |
| OMS | canonical order identity、生命周期、转换、成交 |
| 对账 | 券商/账户/订单/成交一致性与复核 |
| 受控执行 | 有界权限、预算、session、提交门禁 |
| AI 研究 | 证据上下文、workflow、artifact、review、memory lineage |

### 证据与持久化

SQLite 保存 append-oriented 的财务、运营、执行与 AI 审计事实。Canonical fingerprint 绑定
输入，使重启、重复处理、漂移检测与重放保持确定性。

外部 provider 都是边缘组件。其运行时响应只有经过校验并持久化后才成为证据，绝不会隐式成为
权限。

## Canonical 财务身份

一个估值视图绑定：

- valuation snapshot id 与 fingerprint；
- 已确认 quote/NAV observations 与 previous-close baselines；
- ledger cutoff 与 ledger fingerprint；
- source、cache、freshness 与 data-quality 证据；
- 在适用时明确标记 estimated 或 unavailable。

Holdings、Equity Curve、Overview、Decision、Account Truth 与 AI evidence 在声称描述同一时点
时必须引用同一个 canonical identity。历史重建不能使用未来价格或不相关的当前报价。

## 核心流程

### 研究

```text
策略定义
-> 冻结数据集快照
-> 确定性回测
-> 成本与 OOS 分析
-> 研究证据包
-> 人工复核与 promotion readiness
```

策略扩展使用有类型的 metadata 与参数。由 Web 触发的任意代码执行不在契约内。研究输出不能
绕过风控、journal、paper/shadow 或人工确认门禁。

### 每日决策

```text
组合 + 行情 + 策略 + 账户证据
-> 候选操作与目标权重
-> 批次构建与成本
-> 风控门禁
-> 买入 / 卖出 / 持有 / 再平衡 / 不行动 / 需要复核
```

每个公开操作都包含证据与阻断项。不行动是一等结果，不是错误或空响应。

### Paper/shadow 运营

```text
每日计划
-> 确定性 paper/shadow 运行
-> 模拟 OMS 订单与成交
-> 成本与偏差
-> 操作员复核与告警
```

Paper/shadow 事实绝不会变成真实成交或账本修改。Operations 负责 run identity、重试、状态、
限制与恢复任务。

### Account Truth 与对账

```text
候选 adapter release manifest
-> 人工 accept / reject / revoke review
-> 精确 live collector deployment binding
-> 显式券商导入或 collector 证据
-> preview 与校验
-> 已持久化券商事实
-> 账户/执行对账
-> 人工复核
-> 可选且单独确认的账本操作
```

原始 provider 事实保留来源身份。重复、序列、账户、数量与 schema 冲突必须 fail closed。

collector 自报的 release-status 字段不是权限。live callback/poll ingestion 会解析 append-only
adapter release review，并在 prepare 与 commit 两次绑定 collector、deployment fingerprint、
provider、gateway、account alias、authorization、capability matrix、进程边界以及 rollback/privacy
证据。release 证据缺失、rejected、revoked、被篡改或 drifted 时会阻断 ingestion。Acceptance
既不会注册 adapter，也不会授予券商写权限或资本权限。

### 受控执行

```text
已复核计划与 OMS 订单
-> 账户/风控/paper-shadow/gateway/对账门禁
-> 已签名资本评估与逐单批准
-> 一个持久化 controlled intent
-> 一个外部效果
-> lifecycle query/callback 证据
-> 对账
-> 明确确认后入账
```

策略代码不能接触 gateway。Prepared、accepted-but-unreconciled 或 unknown intent 会阻断不同
订单。Unknown 结果只能查询，绝不自动重提。

### AI 研究

```text
显式证据捕获
-> 不可变上下文
-> 人工创建研究任务
-> 权限检查后的只读工具
-> claim / debate / report
-> 人工复核
-> 可选、可撤销的历史 memory
```

Provider、model、role、prompt、workflow、tool、evidence、artifact、review 与 memory 身份保持
独立。每个模型阶段引用当前证据；历史 memory 标记为 non-current。外部调用不获得 provider
工具或交易权限，raw reasoning 与凭证不持久化。

证据绑定的公式研究流程更加狭窄：

```text
已保存 canonical backtest 与精确数据集快照
-> 人工确认假设导出
-> allowlisted Formula DSL 校验
-> 人工选择、具有 next-bar 语义的 canonical backtest
-> 可选且单独确认的证据批评
-> 人工接受 / 修订 / 拒绝
```

Formula DSL 是作用于已持久化 OHLCV 字段的 JSON AST，lookback 与 window 有界。任意代码、
未知 operator 或修改 universe/window/frequency/cost 输入都会被拒绝。受限适配器复用精确保存的
bars 与 canonical BacktestEngine；它不能注册生产策略、创建 Decision 或 trading plan，也不能
接触 OMS、ledger、risk、kill switch、broker、capital 或 authority state。

## 权限边界

| 能力 | Research/strategy | AI | Operator | Controlled runtime |
| --- | ---: | ---: | ---: | ---: |
| 读取已持久化证据 | scoped | scoped | yes | scoped |
| 提议目标权重或计划 | yes | 仅草稿 | yes | no |
| 决定风险 | no | no | policy/review | 确定性门禁 |
| 修改账本 | no | no | 单独确认 | no |
| 发布资本权限 | no | no | 已签名决定 | no |
| 提交一个券商订单 | no | no | 最终批准 | 仅限精确门禁内 |
| 取消一个券商订单 | no | no | 单独批准 | 仅限精确门禁内 |
| 放宽或续期权限 | no | no | 新决定 | never |

Execution gateway 与只读 evidence connector 是不同身份，不得静默共享权限。生产环境默认既不
注册 write adapter，也不注册 release provider。

## 受控权限模型

有效权限是所有适用限制的最小值：

```text
操作员授权
账户与策略 policy
标的与流动性限额
资本、现金、换手、损失与回撤预算
订单价值与订单速率限制
新鲜的账户、行情、gateway 与对账证据
kill-switch 与运营健康
```

Reservation 与 rate admission 串行化。Runtime session 已签名、短期、token-authenticated，并且
只能单向暂停。恢复时创建一个相同或更窄的新 session，而不是原地恢复旧 session。

## 失败语义

- **Rejected：** provider 明确拒绝命令；证据持久化后，恢复流程可以释放 interlock。
- **Unknown：** 外部效果可能已发生；使用相同 client identity 查询，绝不自动重提。
- **Partial：** 保留精确成交与剩余数量，不得归一化成成功或失败。
- **Drifted：** 复核后来源或 fingerprint 改变；使派生 eligibility 失效并要求重新复核。
- **Paused：** 硬门禁失败；后来出现明确证据也不会恢复同一 session。

告警与操作员视图派生自已持久化事实。它们可以指出问题与安全的下一步，但不能以读取副作用
刷新 provider 或修改权限。

## 部署与隐私

- 核心应用 local-first，使用 SQLite 保存持久状态。
- 券商与外部模型适配器保持为可替换边缘组件。
- 凭证在运行时提供给相应边缘组件，绝不保存到 canonical 财务表或审计表。
- 真实账户导出、运行数据库、日志、截图与 secrets 不进入源码控制。
- Adapter release、capability、deployment、authorization、health 与 rollback 证据均明确且有版本。

## 架构变更规则

只有持久组件、数据流、权限边界或 invariant 改变时才更新本文。版本进展、测试数量、逐 endpoint
实现说明与已完成阶段日志属于[实现记录](IMPLEMENTATION_LOG.zh.md)或 Git 历史。
