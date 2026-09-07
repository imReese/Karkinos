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

## 当前操作参考

这些文档解释仍在使用的配置、金融语义和操作，不定义产品方向：

- [配置参考](config-reference.zh.md)
- [收益核算](return-accounting.zh.md)
- [账户证据导入](account-truth-import.zh.md)
- [scripts 运行与发布](../scripts/README.md)

工程文档默认中文；不为没有翻译正文的文件保留语言切换入口。

## 冻结能力与旧 Strategy

Account Truth / broker / controlled-execution 方向在 [PLAN.md](PLAN.md) 解冻前不扩展；代码与安全测试继续保留。旧 milestone、`v1.8` 或 20-day soak 不代表当前 roadmap。

恢复真实执行前，应依据选定 provider 和当前架构重新审核操作流程、签名流程、conformance 与 recovery。Order/Fill 必须复用统一 lifecycle；撤单仍是独立的人审 command；签名不能授予超出代码所绑定 exact scope 的权限。旧 QMT adapter 只保留兼容，不代表已通过重新接入审核。

[Strategy 兼容说明](strategy/README.zh.md) 描述旧扩展体系。新研究能力按 `Dataset -> Alpha/Model -> Forecast -> Portfolio` 实现，不再扩大旧 Strategy 抽象。

## 暂留的验收兼容路径

以下占位页仍被现有 acceptance manifests 引用，暂不删除，也不增加正文：

- `README.zh.md`、`README.en.md`
- `ROADMAP.md`、`ROADMAP.zh.md`、`IMPLEMENTATION_LOG.md`、`CONTROLLED_EXECUTION_PLAN.md`
- `BROKER_CONNECTOR_SOAK_RUNBOOK.md`
- `broker-adapter-release-review.en.md`、`broker-adapter-release-review.zh.md`
- `broker-execution-edge-conformance.en.md`

这些文件不是操作手册，也不能单独证明文档交付已完成。删除前须迁移对应引用并核对验收声明，不能用 GOAL/PLAN 替换缺失证据来保持通过状态。其余无验收依赖的跳转、翻译和冻结占位页已移除，不新增 archive 或替代跳转页。

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
9. 只有明确外部协作价值且能维护实际正文时才增加翻译。
