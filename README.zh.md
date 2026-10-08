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

稳定的 `main` 在 `http://127.0.0.1:8000` 提供构建后的 Web 界面和 API。

启动当前 `dev` working tree：

```bash
git clone --branch dev https://github.com/imReese/Karkinos.git
cd Karkinos
uv sync --locked --extra server --extra dev
npm ci --prefix web
./scripts/start_server.sh dev
```

开发运行使用 Vite HMR 在 `http://127.0.0.1:5173` 提供 Web 界面，
后端带 reload 运行于 `http://127.0.0.1:8000`。

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

分支选择、刷新与单 runtime 规则见 [scripts/README.md](scripts/README.md)。

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

默认 `market_data.source_policy` 是 **`free_cn_research_v1`**：后台自动采集一个日线来源并保存单源质量证据，不因此发布 Dataset。独立的 `market_data.verification_source_policy` 默认使用同一版本化策略，只约束显式研究核验。首选组合是 BaoStock 与通过 AKShare SDK 取得的腾讯日线：两者上游不同；`tencent` 和 `akshare_tencent` 同属腾讯上游，不能算两票。研究需要固定区间时，通过 `POST /api/backtest/datasets/verified-jobs` 为已核验且已收盘的 SSE 交易日明确提交双源核验，并取得每个任务的 `source_policy_id`；`GET /api/backtest/datasets/verified-jobs/{job_id}` 可查看状态与策略。任务成功后，通过 `POST /api/backtest/datasets/verified-interval` 用指定的任务 ID 组成带核验证据的 Dataset。回测、比较和参数扫描明确绑定其 `dataset_id`。跨源一致不证明严格历史 PIT 或总收益，也不授予策略晋级资格；原有 Dataset ID 与重放语义不变。TuShare 与 TDX 是可选增强来源。AI Provider、通知、费用、Server 设置、路径以及环境变量优先级见 [配置指南](docs/guides/configuration.md)。

### 启动一个持续观察的研究实验

1. 在回测页面打开已保存的双均线、ETF 轮动或 Formula 报告，也可从 AI 研究候选页面进入。
2. 为新观察选择独立预热数据；可选择已有匹配数据集，或为策略的完整标的篮子提交双源核验，区间应覆盖足够预热并截至最近已收盘交易日。全部任务成功后即可发布并选择 Dataset。
3. 启动独立观察，冻结策略定义、预热数据、预测周期和目标风险限额；原报告保留。再创建独立模拟账本，冻结资金、成本、基准和健康规则。
4. 在观察面板分别启用“观察数据自动准备”“自动推进”和“账本自动结算”。数据工作进程为冻结篮子准备新增交易日；发布和结算只读取完整本地数据。服务和工作进程需要持续运行。
5. 每日检查数据准备、发布和结算状态，以及模拟净收益、相对基准表现和回撤。缺失数据会等待，错过次日开盘的目标不会补发；关闭数据准备会撤销旧任务的后续发布权限。

旧报告可以在观察面板中选择或准备新的已核验预热数据。系统复用原报告的策略定义与完整类型化资产篮子，显示所需预热长度，并在启动时核验数据完整性与可用时间；原研究报告保留，新观察从所选预热起点重新计算策略状态。AI 候选页面可直接使用同一观察与模拟账本面板，查看成本后净收益、基准、回撤和费用。

自动数据准备保留冻结的已核验 Dataset 前缀，每批最多追加 366 个日历日，支持最多 32 个标的，并遵守冻结的数据行数上限及供应商预算。重启后继续已完成批次，不补发错过的目标。ETF 模拟结果当前使用价格收益口径。这个工作流产生可复核的前瞻实验记录，账户资格和人工发布仍需各自的证据。

## 开发 Karkinos

修改集成到 `dev`。安装上述锁定依赖后，用 `./scripts/start_server.sh dev`
启动源码运行时。
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
