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

## 使用 Karkinos

根据你的运行方式选择入口：

| 方式 | 适合场景 | 环境要求 |
| --- | --- | --- |
| **Docker Compose** | 隔离运行完整 Web + API | Docker / Docker Compose |
| **源码运行** | 从 Git checkout 直接运行完整本地应用 | Python 3.12+、Node.js 24.x、`uv`、Git、POSIX shell |
| **Python / pip 源码安装** | 手动 Python/API 运行和本地集成 | Python 3.12+；完整 Web 还需要 Node.js 24.x |
| **Native Release** | 使用经过验证的原生发布包 | 当前提供 macOS arm64 / x86_64 |

### Docker Compose

克隆稳定分支，并从模板创建本地配置：

```bash
git clone --branch main --depth 1 https://github.com/imReese/Karkinos.git
cd Karkinos
cp config.example.json config.json
cp .env.example .env
```

启动应用：

```bash
docker compose up --build -d
```

打开 `http://127.0.0.1:8000`。

Docker Compose 将数据库保存在 `karkinos-data` Docker volume 中，并以只读方式挂载 `config.json`。如需 TuShare、AI 或通知凭证，在启动前编辑 `.env`。

### 源码运行

适合不使用 Docker、希望直接从 checkout 运行完整应用的场景。先选择一个明确的持久化运行目录：

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch main

export KARKINOS_HOME="/absolute/path/to/your/karkinos-workspace"
mkdir -p "$KARKINOS_HOME/config"
cp config.example.json "$KARKINOS_HOME/config/config.json"
cp .env.example "$KARKINOS_HOME/config/.env"

./scripts/start_server.sh main --init
```

打开 `http://127.0.0.1:8000`。

`--init` 只用于创建新的空运行环境。后续启动使用：

```bash
./scripts/start_server.sh main
```

当前源码运行模式会把配置、数据库、日志以及受管理的 source state 保存在所选择的 `KARKINOS_HOME` 下。生命周期命令见 [scripts/README.md](scripts/README.md)。

### Python / pip 源码安装

Karkinos 可以从本仓库源码安装为 Python package。PyPI 上名为 `karkinos` 的项目与本仓库无关，因此**不要执行 `pip install karkinos`**。

在 Karkinos 源码 checkout 中安装：

```bash
python -m pip install ".[server]"
```

如果需要完整 Web 应用，再构建一次前端：

```bash
npm ci --prefix web
npm --prefix web run build
```

创建本地运行配置，并从仓库根目录启动：

```bash
cp config.example.json config.json
cp .env.example .env
python -m server
```

打开 `http://127.0.0.1:8000`。这种直接 Python 运行方式默认把本地数据写入 `data/store`，除非显式设置 `KARKINOS_DATA_DIR`。

### Native Release

稳定版本会发布经过验证的原生 archive 和 container image。当前原生 archive 提供 **macOS arm64** 和 **macOS x86_64**，可用产物见 [Releases](https://github.com/imReese/Karkinos/releases)。

发布资产中的 `bootstrap_installer.sh` 用于受管理的 release/update handoff，不是通用的跨平台包管理器。Linux 和 Windows 当前优先使用 Docker 或源码运行方式。

### 配置

默认行情数据源是 **AKShare**，无需 Token。TuShare、AI Provider、通知、费用、Server 设置、路径以及环境变量优先级见 [配置指南](docs/guides/configuration.md)。

用户配置和金融 / 研究状态属于需要长期保留的本地数据。源码开发状态与用户运行环境分离，不能拿开发沙箱存放真实 Karkinos 数据。

## 开发 Karkinos

开发流程和普通使用分开。源码开发使用长期存在的 `dev` 分支，以及可丢弃的独立开发沙箱。

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch dev
./scripts/start_server.sh dev
```

开发启动器创建 `.run/dev-home`，并启动：

- Web：`http://127.0.0.1:5173`
- API：`http://127.0.0.1:8001`
- Health：`http://127.0.0.1:8001/api/health`

开发配置和数据全部留在 `.run/dev-home`。该目录是可丢弃的开发沙箱，绝不能指向真实用户运行目录。

贡献流程、测试和工程约束见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [docs/ENGINEERING.md](docs/ENGINEERING.md)。

## 资源

**产品** — [Goal](docs/GOAL.md) · [Architecture](docs/ARCHITECTURE.md) · [Plan](docs/PLAN.md)  
**工程** — [Engineering](docs/ENGINEERING.md) · [Guides](docs/guides/) · [贡献](CONTRIBUTING.md)  
**项目** — [Releases](https://github.com/imReese/Karkinos/releases) · [安全](SECURITY.md) · [MIT License](LICENSE)

---

<div align="center">
<sub>Python · FastAPI · SQLite · React · TypeScript · Vite · Docker</sub><br>
<sub>Karkinos 是量化研究与投资软件，不构成投资建议，也不保证任何收益。</sub>
</div>
