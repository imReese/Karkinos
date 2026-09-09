# Karkinos

> 投资是一种慢性病。这是你的手术刀。

[English](README.md)

Karkinos 是一个**面向中国市场、本地优先的量化研究与投资平台**。

它建立在一个简单的原则之上：投资研究应该可复现、可证伪、考虑真实成本，
并且能够自然地连接到组合决策，而不是最终演化成一个无人值守的自动交易机器人。

Karkinos 希望把市场数据逐步转化为研究证据、预测、组合决策、模拟结果和可解释的
投资动作，同时让金融状态和真实资金权限始终保持明确。

## 为什么做 Karkinos

很多量化工具很容易生成一个漂亮的回测，但更难回答真正重要的问题：

* 策略是否只使用了当时真正能够获得的信息？
* 结果能否经受样本外测试和真实交易成本？
* 所谓 Alpha 是否只是市场或风格暴露？
* 多个预测应该如何共同影响组合？
* 研究预期和模拟或实际结果为什么发生偏差？
* 一个 edge 什么时候应该被降权、隔离甚至淘汰？

Karkinos 围绕这整个研究生命周期设计，而不是围绕策略数量、基础设施复杂度或
券商连接数量设计。

## 核心闭环

```text
Market Data
-> Point-in-time Dataset
-> Research
-> Forecast
-> Portfolio Target
-> Rebalance Plan
-> Risk
-> Simulation / Paper / Shadow
-> Human-supervised Action
-> Accounting / Reconciliation
-> Attribution
-> Edge Monitoring / Retirement
```

产品的中心是：

> **从可信的数据走向可信的投资决策。**

自动交易不是 Karkinos 的产品目标。

## 当前能力

当前仓库已经包含以下方向的基础能力：

* 中国市场数据接入与本地行情数据持久化；
* 量化策略、回测、交易成本建模、参数探索和样本外评估；
* 可复现研究和 point-in-time 数据工作流；
* 组合、估值、费用、收益核算和对账能力；
* 经过风险约束的 simulation、paper 和 shadow 验证；
* 本地持有的金融状态和用户配置；
* 可选的 AI 辅助研究，但 AI 输出不具有金融事实或资本权限；
* FastAPI 后端和 React / TypeScript Web 应用。

当前代码库中的部分历史复杂度正在主动收缩。当前工程范围只由
[docs/PLAN.md](docs/PLAN.md) 定义。

## 设计原则

### 研究先于自动化

Alpha、模型、分数、排名、概率或预期收益表达的是一种投资观点。

它们不会直接变成订单。

研究证据、组合构建、风险、执行和会计核算是不同的职责。

### Point-in-time 是默认要求

研究必须区分：

> 事情什么时候发生？

和：

> 研究者什么时候真正能够知道这件事？

历史股票池、公司行为、停牌、涨跌停、交易日历以及其他中国市场约束，
都不能利用未来信息进行重建。

### 结果必须可复现

有意义的研究结果应该能够追溯到：

* 数据；
* 假设；
* 参数；
* 时间边界；
* 实现版本；
* 对结果有实质影响的金融假设。

只有输入和金融语义可信，回测才有资格成为研究证据。

### Local-first

核心研究、组合状态、金融状态和主要计算默认由用户本地拥有。

外部服务可以提供：

* 市场数据；
* 模型；
* 通知；
* 远程计算；
* 其他可选能力。

但它们不会自动成为 Karkinos 核心工作流的权威来源。

Local-first 不等于只能离线运行。

### 真实资金默认由人监督

真实资金自动执行不是默认模式。

研究代码、AI、Provider 或 UI 状态都不能自行获得资本权限，也不能绕过组合和风险边界。

## 快速开始

### 环境要求

* Python 3.12+
* Node.js 24.x
* [uv](https://docs.astral.sh/uv/)
* Git

### 本地开发

克隆仓库并切换到正常开发分支：

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch dev
```

启动开发环境：

```bash
./scripts/start_server.sh dev
```

浏览器打开：

```text
http://127.0.0.1:5173
```

开发环境使用独立的本地运行目录，不需要复用日常 Karkinos 账户。

停止：

```bash
./scripts/stop_server.sh dev
```

如果需要运行受管理的 `main`、查看日志和状态、使用已有账户，或者维护旧的
immutable-release 模式，请查看
[scripts/README.md](scripts/README.md)。

## 开发检查

安装锁定的开发依赖：

```bash
uv sync --locked --extra server --extra dev
```

运行后端测试：

```bash
uv run --locked python -m pytest
```

运行主要 Web 检查：

```bash
npm --prefix web run format:check
npm --prefix web run test
npm --prefix web run build
```

开发时优先执行和改动范围对应的最小检查；仓库 CI 是完整验证的权威路径。

## 文档

从 [docs/README.md](docs/README.md) 开始。

Karkinos 的 canonical engineering docs 有意保持精简：

* [Goal](docs/GOAL.md) — 产品为什么存在以及不可跨越的边界。
* [Architecture](docs/ARCHITECTURE.md) — 长期稳定的领域和 ownership 规则。
* [Plan](docs/PLAN.md) — 当前开发范围。
* [Engineering](docs/ENGINEERING.md) — 当前代码库现实、结构性债务和工程指导。
* [References](docs/REFERENCES.md) — 用于概念比较的成熟开源项目设计参考。

稳定的运行和金融语义说明位于
[docs/guides/](docs/guides/)。

实现历史属于 Git，不再维护平行 roadmap 或 implementation diary。

## 项目状态

Karkinos 仍在积极开发。

`dev` 是正常开发分支；经过验证的开发 commit 通过仓库 promotion workflow
进入 `main`。

README 不维护 roadmap。当前开发重点只看
[docs/PLAN.md](docs/PLAN.md)。

## 安全

Karkinos 是量化研究与投资软件，不构成投资建议，也不保证任何收益。

不要向源码仓库或公开 issue 提交：

* API Key 或其他凭证；
* 券商密码或私人认证材料；
* 真实账户导出和交易历史；
* 运行数据库；
* 包含私人金融信息的日志或截图。

测试和公开 bug report 使用经过脱敏的合成数据。

安全政策见 [SECURITY.md](SECURITY.md)。

## 贡献

修改仓库前请先阅读
[CONTRIBUTING.md](CONTRIBUTING.md)。

涉及重要量化领域或架构设计时，在创造新的 Karkinos-specific abstraction
之前也应查看
[docs/REFERENCES.md](docs/REFERENCES.md)。

## 技术栈

Python · FastAPI · SQLite · React · TypeScript · Vite

完整的数据、分析和前端依赖以 `pyproject.toml` 和 `web/package.json` 为准。

## License

Karkinos 使用 [MIT License](LICENSE)。
