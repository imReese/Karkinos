# Karkinos 文档

这是一份“从哪里开始看”的索引，不是另一份产品说明。

## 只需要先读这四份

| 文档 | 只负责回答 |
| --- | --- |
| [GOAL.md](GOAL.md) | Karkinos 为什么存在，什么绝对不做？ |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统边界、数据所有权和故障语义是什么？ |
| [PLAN.md](PLAN.md) | 现在先做什么，之后按什么顺序做？ |
| [CODEBASE.md](CODEBASE.md) | 代码放在哪里，依赖方向怎么走？ |

日常安装、启动和使用看仓库根目录的 [README](../README.md)。

## 当前主线

```text
Reliability
-> Point-in-time Data
-> Alpha Factory
-> Portfolio Construction
-> Execution Simulation / Shadow
-> Attribution
-> Controlled Capital Pilot
```

任何与这条主线冲突的旧 roadmap、旧 milestone 或旧 AI/券商计划都不是当前优先级。

## 专题参考

这些文档只在处理对应专题时打开，不属于“入门必读”：

- [配置参考](config-reference.zh.md)
- [Account Truth 导入](account-truth-import.zh.md)
- [收益核算](return-accounting.zh.md)
- [券商适配器一致性](broker-adapter-conformance.zh.md)
- [券商适配器发布复核](broker-adapter-release-review.zh.md)
- [执行边界一致性](broker-execution-edge-conformance.zh.md)
- [订单生命周期证据导入](broker-order-lifecycle-ingestion.zh.md)
- [受控撤单](controlled-broker-cancellation.zh.md)
- [操作员签名](operator-approval-signing.zh.md)
- [策略专题](strategy/)

部分专题仍保留英文翻译用于外部协作；工程决策以当前 canonical 文档和代码契约为准。

## 旧链接兼容

`KARKINOS_GOAL*`、`ROADMAP*`、`IMPLEMENTATION_LOG*`、`README.zh/en`、
`CONTROLLED_EXECUTION_PLAN*` 等旧文件只保留很短的兼容入口，避免旧链接和验收注册表突然失效。
不要继续向这些文件添加内容。

历史实现细节由 Git commits、pull requests 和 Releases 保存，不再维护平行的 implementation log。

## 文档规则

1. 只允许一份当前计划：`PLAN.md`。
2. 只允许一份产品目标：`GOAL.md`。
3. `ARCHITECTURE.md` 只记录长期稳定的边界和 invariant，不记录版本流水账。
4. README 只写当前能力和使用方法，不承载 roadmap。
5. 工程文档默认使用中文；只有明确有外部读者价值的用户/专题文档才维护翻译。
6. 新设计优先写 ADR、代码契约和测试；不要再创建“第二份总设计”。
7. 完成记录进入 Git/Release，不创建新的实现日记。
