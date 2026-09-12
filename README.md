<div align="center">

<h1>Karkinos</h1>

<p><strong>Local-first quantitative research and investing platform for China markets.</strong></p>

<p><em>Investing is a chronic condition. Here is your scalpel.</em></p>

<p>
  <a href="https://github.com/imReese/Karkinos/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/imReese/Karkinos/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/imReese/Karkinos/releases"><img alt="Latest Release" src="https://img.shields.io/github/v/release/imReese/Karkinos?display_name=tag"></a>
  <a href="pyproject.toml"><img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white"></a>
  <a href="web/package.json"><img alt="Node.js 24.x" src="https://img.shields.io/badge/Node.js-24.x-5FA04E?logo=nodedotjs&logoColor=white"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/imReese/Karkinos"></a>
</p>

<p>
  <a href="docs/README.md">Documentation</a> ·
  <a href="docs/ARCHITECTURE.md">Architecture</a> ·
  <a href="https://github.com/imReese/Karkinos/releases">Releases</a> ·
  <a href="README.zh.md">简体中文</a>
</p>

</div>

Karkinos connects point-in-time market data, reproducible research, portfolio construction,
risk, simulation, accounting, and attribution in one local-first workflow.

**Market data → point-in-time research → portfolio decisions → evaluation → continuous feedback.**

## Capabilities

- **Point-in-time data** — research inputs reflect information available at the modeled decision time.
- **Research** — backtesting, transaction-cost modeling, parameter exploration, out-of-sample evaluation, and robustness analysis.
- **Portfolio & risk** — published forecasts become portfolio targets, explicit risk decisions, and rebalance plans before execution.
- **Simulation & evaluation** — backtest, paper, and shadow workflows connect research expectations with later outcomes.
- **Accounting & attribution** — cash, positions, fees, returns, reconciliation, and outcome attribution remain explicit.
- **China-market semantics** — trading calendars, suspensions, price limits, lot rules, fees, and taxes are first-class concerns.
- **AI-assisted research** — optional AI can accelerate research iteration while deterministic code owns quantitative and financial results.
- **Application** — FastAPI backend, React / TypeScript interface, and a local-first runtime.

## Using Karkinos

| Method | Best for | Requirements |
| --- | --- | --- |
| **Source runtime** | Normal local use and development | Python 3.12+, Node.js 24.x, `uv`, Git, POSIX shell |
| **Docker Compose** | Isolated Web + API runtime | Docker / Docker Compose |
| **Python / pip from source** | Manual Python/API integration | Python 3.12+; Node.js 24.x for the Web UI |
| **Native release** | Verified packaged runtime | Currently macOS arm64 / x86_64 |

### Source runtime

For the normal local workflow, the repository root owns the local Karkinos state. Source branches share the same `config.json`, `.env`, `data/store`, `logs`, and `exports`; selecting a branch only changes the code being run.

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
cp config.example.json config.json
cp .env.example .env
./scripts/start_server.sh --init
```

`main` is the default, so later starts are simply:

```bash
./scripts/start_server.sh
```

Open `http://127.0.0.1:8000`.

The launcher does **not** switch the current Git checkout. Stable branches are materialized as disposable code snapshots under `.run/<branch>/code` with `git archive`, while persistent local state stays in the repository root:

```text
Karkinos/
├── config.json
├── .env
├── data/store/          # databases and local data
├── logs/
├── exports/
└── .run/
    ├── source.lock      # one source backend at a time
    ├── main/
    │   └── code/        # cached main source snapshot + derived dependencies
    └── dev/             # dev PID / process state only
```

`config.json`, `.env`, runtime data, logs, exports, and `.run/` are ignored by Git.

You can stay on `dev` while running stable `main`:

```bash
git switch dev

# run the current dev working tree, including local uncommitted edits
./scripts/start_server.sh dev

# stop dev, then run the locally fetched main snapshot
./scripts/stop_server.sh dev
./scripts/start_server.sh
```

The current checkout remains on `dev`. `main` and other stable branch snapshots do not read uncommitted working-tree changes.

Run another committed branch without switching the checkout:

```bash
./scripts/start_server.sh feature/my-research-change
./scripts/stop_server.sh feature/my-research-change
```

To stop every Karkinos runtime the local launcher knows it owns—dev, tracked stable snapshots, and a legacy/native resident service when present—no mode argument is required:

```bash
./scripts/stop_server.sh
```

Pass `dev`, `main`, another branch name, or `prod` only when you want a targeted stop.

Snapshot branches use the latest branch ref already available locally. Run `git fetch origin` when you want to refresh `origin/main` or another remote branch. The cached snapshot is rebuilt only when that ref points to a new commit.

`dev` is intentionally special only in how code is selected: it runs the current `dev` working tree with backend reload and Vite on `5173`. Both dev and stable source backends use port `8000`; only one source backend may run against the shared workspace at a time.

Because branches share the same databases, schema-changing development must use explicit migrations and preserve the persisted-data compatibility rules in [docs/ENGINEERING.md](docs/ENGINEERING.md).

Lifecycle details: [scripts/README.md](scripts/README.md).

### Docker Compose

```bash
git clone --branch main --depth 1 https://github.com/imReese/Karkinos.git
cd Karkinos
cp config.example.json config.json
cp .env.example .env
docker compose up --build -d
```

Open `http://127.0.0.1:8000`.

Docker Compose keeps its database in the `karkinos-data` Docker volume and mounts `config.json` read-only into the container. Edit `.env` for optional TuShare, AI, or notification credentials before starting the service.

### Python / pip from source

Karkinos is installable as a Python package from this repository. The PyPI project named `karkinos` is unrelated to this repository, so **do not use `pip install karkinos`**.

```bash
python -m pip install ".[server]"
```

For the Web UI:

```bash
npm ci --prefix web
npm --prefix web run build
```

Then create local configuration and start from the repository root:

```bash
cp config.example.json config.json
cp .env.example .env
python -m server
```

Open `http://127.0.0.1:8000`. The default writable data directory is `data/store`.

### Native releases

Stable releases publish verified native archives and container images. Native archives are currently built for **macOS arm64** and **macOS x86_64**. See [Releases](https://github.com/imReese/Karkinos/releases) for available artifacts.

The standalone `bootstrap_installer.sh` asset is for the managed release/update handoff flow, not a generic cross-platform package manager. Linux and Windows users should currently prefer Docker or a source-based runtime.

### Configuration

The default market-data provider is **AKShare** and requires no token. TuShare, AI providers, notifications, fees, server settings, paths, and environment-variable precedence are documented in the [configuration guide](docs/guides/configuration.md).

## Development

`dev` is the persistent development branch. Switch to it yourself once and keep working there:

```bash
git switch dev
./scripts/start_server.sh dev
```

Development starts:

- Web app: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/health`

Development deliberately reuses the repository-local `config.json`, `.env`, and `data/store`. `.run/dev` contains only disposable process state. The default `./scripts/start_server.sh` can still run the cached `main` snapshot without changing or cleaning the dev checkout.

For contribution workflow, tests, migration rules, and engineering constraints, see [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ENGINEERING.md](docs/ENGINEERING.md).

## Resources

**Product** — [Goal](docs/GOAL.md) · [Architecture](docs/ARCHITECTURE.md) · [Plan](docs/PLAN.md)  
**Engineering** — [Engineering](docs/ENGINEERING.md) · [Guides](docs/guides/) · [Contributing](CONTRIBUTING.md)  
**Project** — [Releases](https://github.com/imReese/Karkinos/releases) · [Security](SECURITY.md) · [MIT License](LICENSE)

---

<div align="center">
<sub>Python · FastAPI · SQLite · React · TypeScript · Vite · Docker</sub><br>
<sub>Karkinos is research and investing software, not investment advice or a guarantee of returns.</sub>
</div>