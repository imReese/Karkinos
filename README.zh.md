<div align="center">

<h1>Karkinos</h1>

<p><strong>面向中国市场、本地优先的量化研究与投资平台。</strong></p>

<p><em>投资是一种慢性病。这是你的手术刀。</em></p>

<p>
  <a href="https://github.com/imReese/Karkinos/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/imReese/Karkinos/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/imReese/Karkinos/releases"><img alt="Latest Release" src="https://img.shields.io/github/v/release/imReese/Karkinos?display_name=tag"></a>
  <a href="pyproject.toml"><img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="web/package.json"><img alt="Node.js 24.x" src="https://img.shields.io/badge/Node.js-24.x-5FA04E?logo=nodedotjs&logoColor=white"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/imReese/Karkinos"></a>
</p>

<p>
  <a href="docs/README.md">文档</a> ·
  <a href="docs/ARCHITECTURE.md">架构</a> ·
  <a href="https://github.com/imReese/Karkinos/releases">Releases</a> ·
  <a href="README.md">English</a>
</p>

</div>

Karkinos 将 point-in-time 市场数据、可复现研究、组合构建、风险、模拟、会计和归因连接成一条本地优先的工作流。

**市场数据 → point-in-time 研究 → 组合决策 → 评估 → 持续反馈。**

## 核心能力

- **Point-in-time 数据** — 研究输入只使用建模决策时点真正可获得的信息。
- **Research** — 回测、交易成本建模、参数探索、样本外评估和稳健性分析。
- **Portfolio & Risk** — 已发布预测先形成组合目标，再经过明确的风险决策和再平衡计划进入执行。
- **Simulation & Evaluation** — backtest、paper 和 shadow 工作流连接研究预期与后续结果。
- **Accounting & Attribution** — 现金、持仓、费用、收益、对账和结果归因保持明确。
- **中国市场语义** — 交易日历、停牌、涨跌停、交易单位、费用和税费是一等约束。
- **AI-assisted Research** — 可选 AI 用于加速研究迭代，量化和金融结果由确定性代码持有。
- **Application** — FastAPI 后端、React / TypeScript 界面和本地优先的运行环境。

## 开发快速开始

环境要求：**Python 3.12+**、**Node.js 24.x**、**uv** 和 **Git**。

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch dev
./scripts/start_server.sh dev
```

打开 `http://127.0.0.1:5173`。

```bash
./scripts/stop_server.sh dev
```

发布版本：[Releases](https://github.com/imReese/Karkinos/releases) · 运行与维护命令：[scripts/README.md](scripts/README.md)

## 资源

**产品** — [Goal](docs/GOAL.md) · [Architecture](docs/ARCHITECTURE.md) · [Plan](docs/PLAN.md)  
**工程** — [Engineering](docs/ENGINEERING.md) · [Guides](docs/guides/) · [贡献](CONTRIBUTING.md)  
**项目** — [Releases](https://github.com/imReese/Karkinos/releases) · [安全](SECURITY.md) · [MIT License](LICENSE)

---

<div align="center">
<sub>Python · FastAPI · SQLite · React · TypeScript · Vite</sub><br>
<sub>Karkinos 是量化研究与投资软件，不构成投资建议，也不保证任何收益。</sub>
</div>
