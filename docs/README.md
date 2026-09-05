# Karkinos 文档

这里是唯一文档入口。先看 canonical docs；其他文件只有在处理对应实现时才打开。

## Canonical

| 文档 | 负责回答 |
| --- | --- |
| [GOAL.md](GOAL.md) | 最终要做成什么，什么绝对不做？ |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 最终系统边界、数据/进程/状态模型是什么？ |
| [PLAN.md](PLAN.md) | 从当前代码迁到最终形态按什么顺序做？ |
| [CODEBASE.md](CODEBASE.md) | 当前结构性债务和代码 ownership 如何迁移？ |
| [../design.md](../design.md) | 最终产品信息架构和 UI invariant 是什么？ |

根目录 [README](../README.md) 只描述当前可用能力、安装和运行，不承载 roadmap。

## 当前主线

```text
Reliability
-> Architecture Seams
-> Point-in-time Data
-> Research / Alpha
-> Portfolio / Simulation
-> Shadow / Attribution
-> Controlled Capital
```

## 文档 review 结论

### 当前操作参考

这些描述仍在使用的配置/金融语义，可以按需查阅，但不定义产品方向：

- [配置参考](config-reference.zh.md)
- [收益核算](return-accounting.zh.md)
- [scripts 运行与发布](../scripts/README.md)

中文是 canonical operational reference；同名英文文件只是翻译，不作为架构 source of truth。

### Frozen / later-stage reference

以下文档对应已经实现或曾计划的 Account Truth / broker / controlled-execution 能力。代码和安全测试继续保留，但该方向在 [PLAN.md](PLAN.md) 解冻前不扩展；其中出现的 `v1.8`、20-day soak 或旧 milestone 不代表当前 roadmap：

- `BROKER_CONNECTOR_SOAK_RUNBOOK.md`
- `account-truth-import.*`
- `broker-adapter-conformance.*`
- `broker-adapter-release-review.*`
- `broker-execution-edge-conformance.*`
- `broker-order-lifecycle-ingestion.*`
- `controlled-broker-cancellation.*`
- `operator-approval-signing.*`
- `qmt-order-lifecycle-import.zh.md`

需要修改这些能力时，以当前代码契约、测试、GOAL/ARCHITECTURE 的安全边界为准，不从旧 milestone 推导需求。

### Legacy Strategy reference

`strategy/README.*` 描述旧 Strategy 扩展体系。现有功能继续兼容；新的盈利研究能力按 `Dataset -> Alpha/Model -> Forecast -> Portfolio` 架构实现，不再扩大旧 Strategy 抽象。

### Compatibility stubs

以下旧名字只为历史链接/acceptance registry 保留，不能增加正文：

- `README.zh/en`
- `KARKINOS_GOAL*`
- `ROADMAP*`
- `ARCHITECTURE.zh.md`
- `IMPLEMENTATION_LOG*`
- `CONTROLLED_EXECUTION_PLAN*`

实现历史属于 Git commits、PRs、Releases，不再维护第二份 implementation diary。

## 文档写作规则

1. 产品目标只改 `GOAL.md`。
2. 长期架构 invariant 只改 `ARCHITECTURE.md`。
3. 优先级/exit gate 只改 `PLAN.md`。
4. package ownership/refactor 只改 `CODEBASE.md`。
5. UI/信息架构只改 `design.md`。
6. Topic docs 只解释稳定接口或操作，不写 roadmap。
7. 新的窄架构决策可以写 ADR；不要再建“XX 总设计”。
8. 研究/交易契约优先落在 typed code + deterministic tests，文档不成为可执行 acceptance 数据源。
9. 工程文档默认中文；只有明确外部协作价值时维护翻译。
