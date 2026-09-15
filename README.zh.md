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
| **源码运行** | 当前源码 checkout 或任意本地可用分支 | Python 3.12+、Node.js 24.x、`uv`、Git、POSIX shell |
| **Docker Compose** | 隔离运行 Web + API | Docker / Docker Compose |
| **Python / pip 源码安装** | 手动 Python/API 集成 | Python 3.12+；完整 Web 还需要 Node.js 24.x |
| **Native Release** | 使用经过验证的原生发布包 | 当前提供 macOS arm64 / x86_64 |

### 源码运行

启动稳定的 `main` 分支（默认）：

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
./scripts/start_server.sh
```

稳定的 `main` 在受管理的 Git worktree 中运行本地已获取的 `origin/main`，
在 `http://127.0.0.1:8000` 提供构建后的 Web 界面和 API。

启动当前 `dev` working tree：

```bash
git clone --branch dev https://github.com/imReese/Karkinos.git
cd Karkinos
uv sync --locked --extra server --extra dev
npm ci --prefix web
./scripts/start_server.sh dev
```

开发运行使用 Vite HMR 在 `http://127.0.0.1:5173` 提供 Web 界面，
后端带 reload 运行于 `http://127.0.0.1:8000`，使用当前源码
（包括尚未提交的修改）。

`./scripts/start_server.sh <branch>` 运行其他本地可用的分支。
启动器不会切换当前 checkout，也不会自动执行 `git fetch`；
需要更新远端分支时先显式运行 `git fetch origin`。

开发状态独立存放在 `~/.karkinos/development/`：

```text
config/config.json   # 首次启动创建安全默认配置
config/.env          # 可选的开发环境凭证
data/                # 开发数据库
logs/                # 开发日志
```

启动器不会复制现有账户数据，也不会读取仓库根目录的 `config.json` 或 `.env`。
现有开发数据库沿用应用的正常 migration，失败时阻止启动。
使用 `KARKINOS_DEV_HOME` 指定其他开发目录。

停止受管理的运行时：

```bash
./scripts/stop_server.sh
```

同一时间只能运行一个 Karkinos 源码运行时；运行期间重复启动会被拒绝。

生命周期说明见 [scripts/README.md](scripts/README.md)。

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

修改集成到 `dev`。安装上述锁定依赖后，`./scripts/start_server.sh dev`
使用独立开发状态运行当前源码。
贡献流程、测试、migration 规则和工程约束见 [CONTRIBUTING.md](CONTRIBUTING.md)
与 [docs/ENGINEERING.md](docs/ENGINEERING.md)。

## 资源

**产品** — [Goal](docs/GOAL.md) · [Architecture](docs/ARCHITECTURE.md) · [Plan](docs/PLAN.md)
**工程** — [Engineering](docs/ENGINEERING.md) · [Guides](docs/guides/) · [贡献](CONTRIBUTING.md)
**项目** — [Releases](https://github.com/imReese/Karkinos/releases) · [安全](SECURITY.md) · [MIT License](LICENSE)

---

<div align="center">
<sub>Python · FastAPI · SQLite · React · TypeScript · Vite · Docker</sub><br>
<sub>Karkinos 是量化研究与投资软件，不构成投资建议，也不保证任何收益。</sub>
</div>
