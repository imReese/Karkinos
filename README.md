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

Choose the runtime that matches how you want to operate Karkinos:

| Method | Best for | Requirements |
| --- | --- | --- |
| **Docker Compose** | Isolated full Web + API runtime | Docker / Docker Compose |
| **Source runtime** | Full local runtime from a Git checkout | Python 3.12+, Node.js 24.x, `uv`, Git, POSIX shell |
| **Python / pip from source** | Manual Python/API runtime and local integration | Python 3.12+; Node.js 24.x for the Web UI |
| **Native release** | Verified packaged runtime | Currently macOS arm64 / x86_64 |

### Docker Compose

Clone the stable branch and create local configuration from the templates:

```bash
git clone --branch main --depth 1 https://github.com/imReese/Karkinos.git
cd Karkinos
cp config.example.json config.json
cp .env.example .env
```

Then start the application:

```bash
docker compose up --build -d
```

Open `http://127.0.0.1:8000`.

Docker Compose keeps the database in the `karkinos-data` Docker volume and mounts `config.json` read-only into the container. Edit `.env` for optional TuShare, AI, or notification credentials before starting the service.

### Source runtime

Use this when you want the full application directly from a checkout without Docker. Choose an explicit persistent runtime directory first:

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

Open `http://127.0.0.1:8000`.

`--init` is only for creating a new empty runtime. Subsequent starts use:

```bash
./scripts/start_server.sh main
```

The current source runtime stores configuration, databases, logs, and managed source state below the selected `KARKINOS_HOME`. Runtime lifecycle commands are documented in [scripts/README.md](scripts/README.md).

### Python / pip from source

Karkinos is installable as a Python package from this repository. The PyPI project named `karkinos` is unrelated to this repository, so **do not use `pip install karkinos`**.

From a Karkinos source checkout:

```bash
python -m pip install ".[server]"
```

For the full Web application, build the frontend once:

```bash
npm ci --prefix web
npm --prefix web run build
```

Create local runtime configuration and run the server from the repository root:

```bash
cp config.example.json config.json
cp .env.example .env
python -m server
```

Open `http://127.0.0.1:8000`. In this plain Python mode, the default local data directory is `data/store` unless `KARKINOS_DATA_DIR` is set explicitly.

### Native releases

Stable releases publish verified native archives and container images. Native archives are currently built for **macOS arm64** and **macOS x86_64**. See [Releases](https://github.com/imReese/Karkinos/releases) for available artifacts.

The standalone `bootstrap_installer.sh` asset is for the managed release/update handoff flow, not a generic cross-platform package manager. Linux and Windows users should currently prefer Docker or a source-based runtime.

### Configuration

The default market-data provider is **AKShare** and requires no token. TuShare, AI providers, notifications, fees, server settings, paths, and environment-variable precedence are documented in the [configuration guide](docs/guides/configuration.md).

User configuration and financial/research state are persistent local data. Source-development state is separate and must not be used as the user's real Karkinos runtime.

## Development

Development is separate from ordinary Karkinos usage. It uses the persistent `dev` branch and a disposable isolated sandbox.

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
git switch dev
./scripts/start_server.sh dev
```

The development launcher creates `.run/dev-home` and starts:

- Web app: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8001`
- Health: `http://127.0.0.1:8001/api/health`

Development configuration and data stay inside `.run/dev-home`; the directory is disposable and must never be pointed at a real user runtime.

For contribution workflow, tests, and engineering constraints, see [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ENGINEERING.md](docs/ENGINEERING.md).

## Resources

**Product** — [Goal](docs/GOAL.md) · [Architecture](docs/ARCHITECTURE.md) · [Plan](docs/PLAN.md)  
**Engineering** — [Engineering](docs/ENGINEERING.md) · [Guides](docs/guides/) · [Contributing](CONTRIBUTING.md)  
**Project** — [Releases](https://github.com/imReese/Karkinos/releases) · [Security](SECURITY.md) · [MIT License](LICENSE)

---

<div align="center">
<sub>Python · FastAPI · SQLite · React · TypeScript · Vite · Docker</sub><br>
<sub>Karkinos is research and investing software, not investment advice or a guarantee of returns.</sub>
</div>
