# 外部项目参考笔记

[English](BENCHMARKS.md) | [中文文档](README.zh.md)

Karkinos 可以学习成熟的开源金融与量化系统，但不能复制其代码或稀释自身安全边界。本文只记录
架构与产品设计参考。

## 学习边界

可以学习架构、接口、测试纪律、可审计性、风控、数据导入/对账和 UX 模式。

不要复制代码、厂商内部实现、券商凭证、券商登录流程、默认订单提交行为或盈利声明。

## 参考项目

- **OpenBB：** 学习模块化研究 terminal/workspace、清晰的数据 provider 边界与可发现命令。
  Karkinos 应提供明确的本地数据与报告界面，避免隐藏的 provider 调用。
- **Microsoft Qlib：** 学习数据准备、特征生成、模型/策略执行、回测、评估与报告复核的研究
  流程纪律。Karkinos 应保留 point-in-time dataset manifest、feature manifest 与可复现实验记录。
- **QuantConnect LEAN：** 学习数据、券商 adapter、indicator、report、optimizer 与研究工具彼此
  独立的 engine 边界。Karkinos 用 run manifest 与安全 adapter interface 表达，而不是券商自动化。
- **backtrader：** 学习 strategy/analyzer/broker/feed 分离与本地研究体验。成本、风控与
  Account Truth 证据必须明确，不能隐藏在策略代码里。
- **vectorbt：** 学习快速参数探索和向量化研究 UX。Sweep 必须配合稳定性证据、OOS 复核和
  过拟合警告。
- **Freqtrade：** 学习配置校验、resolved-config 检查、数据命令、保存的回测分析、dry-run-first
  运营以及 lookahead/recursive-formula 诊断。
- **RQAlpha：** 学习 A 股、ETF/基金日历、T+1、交易成本与资产特定约束等中国市场假设。
- **VeighNa / vn.py：** 学习 gateway/app/datafeed/database 分离、本地 paper account、数据管理、
  风控、组合管理与 RPC 路由纪律。近期只用于只读券商证据和对账，不用于券商下单。
- **Ghostfolio：** 学习组合跟踪、资产配置、持仓与个人金融 dashboard UX。
- **rotki：** 学习 local-first 隐私、账户历史导入、资产历史、审计与对账式会计纪律。
- **Portfolio Performance：** 学习本地组合会计、statement import、transaction taxonomy、
  绩效归因与可解释持仓视图。
- **第三方 QMT/miniQMT/xtquant adapter 示例：** 只学习只读账户快照、position/order/fill state、
  callback order event、connector health 与 gateway 分离。这些项目只是研究参考；Karkinos 不依赖、
  捆绑、注册或声称官方支持。真实 adapter 需要独立审查和用户明确授权。
- **PTrade 类外部策略平台：** 学习 lifecycle、strategy context、data helper、scheduled 或
  bar/tick callback，以及 backtest/simulation/live-like 一致性。Karkinos 的 Strategy Runtime
  只让策略产生可审计信号和候选操作，不产生直接券商订单。

## 可借鉴的设计主题

- Provider 与 broker-evidence import 应明确、本地、带 fingerprint 且可复现。
- 研究输出携带 dataset、feature、parameter、cost、OOS、analyzer 与 limitation 证据。
- Account Truth 应阻断决策与 promotion，不自动修改生产账本。
- Dry-run、paper/shadow 与 manual-confirmation 边界在 UI 和 API 中可见。
- 诊断优先使用确定性本地测试与合成样例，而不是依赖实时 provider。

## 不形成产品绑定的外部平台经验

第三方券商平台只能作为券商事实和有状态执行 plumbing 的示例，不能成为产品依赖、默认路径或
自动交易许可。可用经验包括：

- 明确的 connector capability 与 health；
- 只读 asset、cash、position、order 与 fill snapshot；
- 从券商 callback 到本地 evidence event 的确定性映射；
- 为未来 paper 或受控 execution bridge 准备的幂等 order/fill correlation id；
- connector 配置、券商证据、账本修改与用户复核的清晰分离。

第三方策略平台只能用于学习 runtime 体验，不能成为策略代码绕过门禁的理由。可用经验包括：

- initialization、pre-market、bar/tick handling 与 after-market review 等 lifecycle hook；
- 提供数据、组合事实、参数与 run metadata 的 strategy context；
- 可运行在 backtest、replay、paper 与 shadow 模式的一套 strategy API；
- 明确 parameter schema 与策略文档；
- 进入 evidence、risk、Account Truth、paper/shadow 与 manual-confirmation 工作流的标准化策略输出。

最终的 Professional Quant Platform track 由[路线图](ROADMAP.zh.md)维护，并继续遵守 local-first
隐私、可审计、非投资建议、默认不自动化与人工复核边界。
