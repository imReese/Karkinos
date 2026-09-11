<div align="center">

# Karkinos

**面向中国市场、本地优先的量化研究与投资平台。**

*投资是一种慢性病。这是你的手术刀。*

[English](README.md) · [文档](docs/README.md) · [Releases](https://github.com/imReese/Karkinos/releases)

[![Dev CI](https://github.com/imReese/Karkinos/actions/workflows/dev-ci.yml/badge.svg?branch=dev)](https://github.com/imReese/Karkinos/actions/workflows/dev-ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/imReese/Karkinos?display_name=tag)](https://github.com/imReese/Karkinos/releases)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-24.x-5FA04E?logo=nodedotjs&logoColor=white)](web/package.json)
[![License](https://img.shields.io/github/license/imReese/Karkinos)](LICENSE)

</div>

Karkinos 把中国市场数据、Point-in-Time 研究、组合构建、风险、模拟、会计、归因和可选的 AI 辅助研究连接成一个本地优先的完整工作流。

## 最新状态

| | |
| --- | --- |
| **最新 Release** | [GitHub Releases](https://github.com/imReese/Karkinos/releases) |
| **当前重点** | [Engineering Reset 与平台可靠性](docs/PLAN.md) |
| **开发分支** | `dev` 持续开发；验证通过的 commit 晋级到 `main` |

## 当前可用能力

| 领域 | 当前能力 |
| --- | --- |
| **Data** | 中国市场数据源接入、本地持久化、交易日历和 Point-in-Time 研究输入 |
| **Research** | 策略研究、回测、交易成本建模、参数探索、样本外和稳健性评估 |
| **Portfolio & Accounting** | 组合视图、估值、费用、收益核算、本地金融状态和对账工作流 |
| **Evaluation** | Backtest、Paper、Shadow 和经过风险约束的模拟工作流 |
| **AI-assisted Research** | 可选的 API 辅助研究；量化和金融结果仍由确定性代码产生 |
| **Web App** | FastAPI 后端、React / TypeScript 界面和本地运行环境 |

## Karkinos 如何工作

```text
Market Data
    |
    v
PIT Dataset
    |
    v
Research / Evaluation
    |
    v
Published Forecast
    |
    v
Portfolio Target
    |
    v
Risk Decision
    |
    v
Rebalance Plan
   /            \
  v              v
Simulation /    Human-supervised
Paper / Shadow   Execution
  |              |
  v              v
Outcome      Fills / Financial Events
   \            /
    v          v
 Accounting / Attribution
          |
          v
   Alpha / Model Health
          |
          +--------------------> Research
```

## 为什么 Karkinos 不一样

- **Point-in-Time 研究** — 只使用决策时点真正可获得的信息。
- **可复现证据** — 结果绑定数据、假设、参数和时间边界。
- **After-cost 评估** — 在有实质影响时纳入费用、税费、换手、流动性和执行假设。
- **Portfolio before orders** — 预测先形成组合意图，再进入执行意图。
- **中国市场语义** — 交易日历、停牌、涨跌停、手数规则等约束是一等公民。
- **持续反馈** — 结果通过归因和 Alpha / Model Health 回到研究环节。
- **AI 辅助而非 AI 权威** — AI 可以加速研究迭代，但不拥有市场事实、金融状态或资本权限。
- **Local-first** — 核心研究产物、组合状态和主要计算默认由本地拥有。

## 快速开始

环境要求：**Python 3.12+**、**Node.js 24.x**、**uv**、**Git**。

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch dev
./scripts/start_server.sh dev
```

浏览器打开：

```text
http://127.0.0.1:5173
```

停止开发环境：

```bash
./scripts/stop_server.sh dev
```

运行和维护命令：[scripts/README.md](scripts/README.md)

## 文档

- [Goal](docs/GOAL.md) — 产品方向和边界
- [Architecture](docs/ARCHITECTURE.md) — 领域 ownership 和系统设计
- [Plan](docs/PLAN.md) — 当前开发重点
- [Engineering](docs/ENGINEERING.md) — 当前代码库和工程约束
- [Guides](docs/guides/) — 配置和金融语义
- [References](docs/REFERENCES.md) — 上游量化项目设计参考

## 项目

**技术栈：** Python · FastAPI · SQLite · React · TypeScript · Vite

**贡献：** [CONTRIBUTING.md](CONTRIBUTING.md)

**安全：** [SECURITY.md](SECURITY.md)

**License：** [MIT](LICENSE)

Karkinos 是量化研究与投资软件，不构成投资建议，也不保证任何收益。
