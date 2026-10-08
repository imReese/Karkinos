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
| **Source runtime** | Current source checkout or any locally available branch | Python 3.12+, Node.js 24.x, `uv`, Git, POSIX shell |
| **Docker Compose** | Isolated Web + API runtime | Docker / Docker Compose |
| **Python / pip from source** | Manual Python/API integration | Python 3.12+; Node.js 24.x for the Web UI |
| **Native release** | Verified packaged runtime | Currently macOS arm64 / x86_64 |

### Source runtime

Start the stable `main` branch (the default):

```bash
git clone https://github.com/imReese/Karkinos.git
cd Karkinos
./scripts/start_server.sh
```

Stable `main` serves the built Web UI and API at `http://127.0.0.1:8000`.

Start the current `dev` working tree:

```bash
git clone --branch dev https://github.com/imReese/Karkinos.git
cd Karkinos
uv sync --locked --extra server --extra dev
npm ci --prefix web
./scripts/start_server.sh dev
```

Development serves the Web UI with Vite HMR at `http://127.0.0.1:5173` and
the API with backend reload at `http://127.0.0.1:8000`.

Development state is isolated under `~/.karkinos/development/`:

```text
config/config.json   # created with safe defaults on first start
config/.env          # optional development credentials
data/                # development databases
logs/                # development logs
```

The launcher never copies existing account data or reads the repository's
`config.json` or `.env`. Existing development databases use the application's
normal migrations; a failed migration blocks startup. Set `KARKINOS_DEV_HOME`
for another development directory.

Stop the managed runtime:

```bash
./scripts/stop_server.sh
```

Branch selection, refresh, and single-runtime rules:
[scripts/README.md](scripts/README.md).

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

The default `market_data.source_policy` is **`free_cn_research_v1`**. The data worker automatically captures one daily-bar source and persists its quality result; this alone does not publish a Dataset or establish historical point-in-time availability. The separate `market_data.verification_source_policy` defaults to the same versioned policy and applies only to explicit two-source research verification. Its preferred pair is BaoStock and Tencent daily bars through the AKShare SDK: these are different upstreams, while `tencent` and `akshare_tencent` share the Tencent upstream and cannot count as two sources. For a fixed research interval, `POST /api/backtest/datasets/verified-jobs` enqueues checks for verified, closed SSE sessions and returns each job's `source_policy_id`; `GET /api/backtest/datasets/verified-jobs/{job_id}` reports its status and policy. After those jobs succeed, `POST /api/backtest/datasets/verified-interval` freezes their exact job IDs into one verification-bound Dataset. Backtests, comparisons, and parameter sweeps bind its `dataset_id` explicitly. Cross-source agreement does not establish historical point-in-time availability or total returns, and does not grant strategy promotion. Existing Dataset IDs and replay semantics remain unchanged. TuShare and TDX are optional enhancement sources. AI providers, notifications, fees, server settings, paths, and environment-variable precedence are documented in the [configuration guide](docs/guides/configuration.md).

### Start a continuing research observation

1. Choose a strategy, dates and the full stock/ETF basket in Backtest. The ETF sample basket demonstrates the controls.
2. Submit two-source verification jobs, publish the Dataset after every session succeeds, then run the backtest against that exact Dataset.
3. Start an independent observation from the saved report, freezing parameters, horizon and target limits. Separately create a paper book to freeze cash, costs, benchmark and optional health rules.
4. Enable data preparation, automatic advance and paper settlement separately in the observation panel. Keep the service and data worker running.
5. Inspect each stage's status and modeled net performance, benchmark-relative return and drawdown. Missing data waits; targets missed before the next opening are never backfilled.

Automatic preparation preserves the original verified immutable Dataset and appends subsequent verified sessions. Its scope is at most 32 instruments and 366 calendar days from the original start, within existing provider budgets. Revocation fences old queued work. Sources without a verified immutable prefix cannot reconstruct one automatically. ETF paper results currently use price-only returns. Observation evidence does not grant account qualification or publication authority.

## Development

Changes integrate on `dev`. Start the source runtime with
`./scripts/start_server.sh dev` after installing the locked dependencies above.
For contribution workflow, tests, migration rules, and engineering constraints,
see [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ENGINEERING.md](docs/ENGINEERING.md).

## Resources

**Product** — [Goal](docs/GOAL.md) · [Architecture](docs/ARCHITECTURE.md) · [Plan](docs/PLAN.md)
**Engineering** — [Engineering](docs/ENGINEERING.md) · [Guides](docs/guides/) · [Contributing](CONTRIBUTING.md)
**Project** — [Releases](https://github.com/imReese/Karkinos/releases) · [Security](SECURITY.md) · [MIT License](LICENSE)

---

<div align="center">
<sub>Python · FastAPI · SQLite · React · TypeScript · Vite · Docker</sub><br>
<sub>Karkinos is research and investing software, not investment advice or a guarantee of returns.</sub>
</div>
