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

| 方式 | 适合场景 | 环境要求 |
| --- | --- | --- |
| **源码运行** | 日常本地使用和开发 | Python 3.12+、Node.js 24.x、`uv`、Git、POSIX shell |
| **Docker Compose** | 隔离运行 Web + API | Docker / Docker Compose |
| **Python / pip 源码安装** | 手动 Python/API 集成 | Python 3.12+；完整 Web 还需要 Node.js 24.x |
| **Native Release** | 使用经过验证的原生发布包 | 当前提供 macOS arm64 / x86_64 |

### 源码运行

对于日常本地使用，Git 仓库根目录保存 Karkinos 的本地状态。不同源码分支共用同一份 `config.json`、`.env`、`data/store`、`logs` 和 `exports`；选择分支只决定运行哪一套代码。

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
cp config.example.json config.json
cp .env.example .env
./scripts/start_server.sh --init
```

默认运行 `main`，后续启动直接执行：

```bash
./scripts/start_server.sh
```

打开 `http://127.0.0.1:8000`。

启动脚本**不会切换当前 Git checkout**。稳定分支通过 `git archive` 物化成 `.run/<branch>/code` 下的可丢弃代码快照，长期本地状态始终留在仓库根目录：

```text
Karkinos/
├── config.json
├── .env
├── data/store/          # 数据库和本地数据
├── logs/
├── exports/
└── .run/
    ├── source.lock      # 同一时间只允许一个 source backend
    ├── main/
    │   └── code/        # 缓存的 main 源码快照及派生依赖
    └── dev/             # 仅保存 dev 的 PID / 进程状态
```

`config.json`、`.env`、运行数据、logs、exports 和 `.run/` 都被 Git 忽略。

你可以一直停留在 `dev` 上开发，同时运行稳定 `main`：

```bash
git switch dev

# 运行当前 dev working tree，包括本地未提交的开发改动
./scripts/start_server.sh dev

# 停止 dev，再运行本地已经 fetch 到的 main 快照
./scripts/stop_server.sh dev
./scripts/start_server.sh
```

当前 checkout 仍然保持在 `dev`。`main` 和其他稳定分支快照不会读取 dev working tree 中未提交的改动。

运行其他已经提交的分支也不需要切换 checkout：

```bash
./scripts/start_server.sh feature/my-research-change
./scripts/stop_server.sh feature/my-research-change
```

分支快照使用本地已经存在的最新 ref。需要刷新 `origin/main` 或其他远端分支时，先执行 `git fetch origin`；只有 ref 指向新的 commit 时才会重建缓存快照。

`dev` 是唯一特殊的源码模式：它直接运行当前 `dev` working tree，后端 reload 默认端口 `8001`，Vite 默认端口 `5173`。稳定分支快照在 `8000` 提供完整应用。所有源码模式仍然共用同一份本地配置和数据，同一时间只允许一个 source backend 打开这套状态。

由于不同分支共用同一份数据库，涉及 schema 的开发必须使用明确 migration，并遵守 [docs/ENGINEERING.md](docs/ENGINEERING.md) 中的持久化兼容规则。

生命周期细节见 [scripts/README.md](scripts/README.md)。

### Docker Compose

```bash
git clone --branch main --depth 1 https://github.com/imReese/Karkinos.git
cd Karkinos
cp config.example.json config.json
cp .env.example .env
docker compose up --build -d
```

打开 `http://127.0.0.1:8000`。

Docker Compose 将数据库保存在 `karkinos-data` Docker volume 中，并以只读方式挂载 `config.json`。如需 TuShare、AI 或通知凭证，在启动前编辑 `.env`。

### Python / pip 源码安装

Karkinos 可以从本仓库源码安装为 Python package。PyPI 上名为 `karkinos` 的项目与本仓库无关，因此**不要执行 `pip install karkinos`**。

```bash
python -m pip install ".[server]"
```

如果需要 Web UI：

```bash
npm ci --prefix web
npm --prefix web run build
```

然后从仓库根目录创建本地配置并启动：

```bash
cp config.example.json config.json
cp .env.example .env
python -m server
```

打开 `http://127.0.0.1:8000`。默认可写数据目录是 `data/store`。

### Native Release

稳定版本会发布经过验证的原生 archive 和 container image。当前原生 archive 提供 **macOS arm64** 和 **macOS x86_64**，可用产物见 [Releases](https://github.com/imReese/Karkinos/releases)。

发布资产中的 `bootstrap_installer.sh` 用于受管理的 release/update handoff，不是通用的跨平台包管理器。Linux 和 Windows 当前优先使用 Docker 或源码运行方式。

### 配置

默认行情数据源是 **AKShare**，无需 Token。TuShare、AI Provider、通知、费用、Server 设置、路径以及环境变量优先级见 [配置指南](docs/guides/configuration.md)。

## 开发 Karkinos

`dev` 是长期存在的开发分支。只需要手动切过去一次，然后一直留在这里开发：

```bash
git switch dev
./scripts/start_server.sh dev
```

开发环境启动：

- Web：`http://127.0.0.1:5173`
- API：`http://127.0.0.1:8001`
- Health：`http://127.0.0.1:8001/api/health`

开发模式有意复用仓库根目录下的 `config.json`、`.env` 和 `data/store`；`.run/dev` 只保存可丢弃的进程状态。即使 checkout 一直停在 `dev`，默认的 `./scripts/start_server.sh` 仍可以运行缓存的 `main` 快照，不会切分支、清理或覆盖 dev working tree。

贡献流程、测试、migration 规则和工程约束见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [docs/ENGINEERING.md](docs/ENGINEERING.md)。

## 资源

**产品** — [Goal](docs/GOAL.md) · [Architecture](docs/ARCHITECTURE.md) · [Plan](docs/PLAN.md)  
**工程** — [Engineering](docs/ENGINEERING.md) · [Guides](docs/guides/) · [贡献](CONTRIBUTING.md)  
**项目** — [Releases](https://github.com/imReese/Karkinos/releases) · [安全](SECURITY.md) · [MIT License](LICENSE)

---

<div align="center">
<sub>Python · FastAPI · SQLite · React · TypeScript · Vite · Docker</sub><br>
<sub>Karkinos 是量化研究与投资软件，不构成投资建议，也不保证任何收益。</sub>
</div>
