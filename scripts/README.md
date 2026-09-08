# Karkinos scripts

Run repository commands from the repository root. The top-level scripts are the
ordinary lifecycle interface:

```bash
./scripts/start_server.sh       # source development
./scripts/start_server.sh main  # background main source with the existing account
./scripts/start_server.sh prod  # selected immutable production release
./scripts/stop_server.sh        # stop exact tracked development services
./scripts/stop_server.sh main   # stop the main source supervisor
./scripts/stop_server.sh prod   # stop the supervised production service
./scripts/stop_server.sh all    # stop dev, main, and prod
```

Everything below a subdirectory is a specialized owner/operator, maintenance,
CI, or internal implementation command. Canonical financial and safety logic
remains in application packages such as `data`, `account_truth`, `analytics`,
and `server`.

## Main source startup (no tag)

日常主服务可以从任意开发分支启动；开发目录有未提交修改也不影响它：

```bash
./scripts/start_server.sh main
```

入口 `service/source_main.py` 从调用仓库的 `origin` 获取远端 `main`，记录
exact SHA，在 `$KARKINOS_HOME/source` 下的独立 checkout 安装锁定依赖并构建。
`.python-version` 选择与 CI 相同的 Python 3.12 系列，兼容本机已有的 pyenv 补丁版本；
uv 为运行环境选择兼容解释器，缺少时自动安装，避免随宿主机默认值升级到其他 Python 系列。
开发目录的分支、源码、`.venv` 和 `web/dist` 不参与 main 的运行。
已准备好的同一版本可以复用；运行中的版本不会被原地更新。

更新先完成获取和构建，再停止受控 main 实例并启动新版本。获取、构建或准备被取消时，
已有实例继续运行。切换后的启动检查若失败，命令返回失败并保留版本信息供排查；
不会自动恢复数据库，也不会假定旧代码兼容已经变化的持久化状态。
新旧 API/worker 不同时访问同一套账户数据。若 `--status` 显示未完成的 activation，
离线启动与重启会拒绝；检查日志后重新运行默认更新入口完成恢复。

```bash
./scripts/start_server.sh main --status       # 查看运行状态、版本及路径
./scripts/start_server.sh main --no-update    # 启动已准备版本，无需联网或重新构建
./scripts/start_server.sh main --restart      # 重启已准备版本，不更新代码
./scripts/start_server.sh main --logs         # 最近的服务日志
./scripts/start_server.sh main --logs --follow
./scripts/stop_server.sh main
```

更新与启动在内部是分开的阶段。默认入口提供一键更新体验；普通重启使用已准备版本。
首次使用和更新需要 Git origin 的访问权限，不需要 tag、GitHub Actions 凭据、Docker
或已安装的不可变发布包。只读状态、日志和停止操作不要求开发目录 clean 或联网。
托管目录由脚本管理，不要在里面编辑、切分支或运行开发构建。

API、数据库及当前 research/data worker 就绪后，后台启动命令才返回成功；
这只证明服务启动，不代表金融决策就绪。关闭终端不会停止已启动服务。
启动期间按 Ctrl+C 会取消本次尝试并清理其进程。
`service/run_main.py` 继续负责 supervisor、账户状态检查与生命周期锁；
`service/main_background.py`、`service/main_logs.py`、`service/main_readiness.py`
分别负责后台启动、日志轮转和就绪检查，`service/main_control.py` 负责安全停止，
`service/source_state.py` 负责准备版本与运行身份的本地记录。

服务日志写入 `$KARKINOS_HOME/logs/main.log`，运行中按 20 MiB 轮转并保留三个归档。
默认路径是 `~/Library/Application Support/Karkinos/logs/main.log`。
使用 `./scripts/start_server.sh main --foreground` 可以在终端跟随服务日志，
Ctrl+C 停止该服务；日志仍然落盘并轮转。普通后台模式不需要 `nohup`、重定向或 `&`。
此模式不安装登录启动，也不自动重启崩溃的服务。

默认监听 `127.0.0.1:8000`，`KARKINOS_MAIN_PORT` 可以选择其他端口。
未知端口占用会报错，不会杀进程。账户数据和配置继续原地使用：

| 环境变量 | 默认值 |
| --- | --- |
| `KARKINOS_HOME` | `~/Library/Application Support/Karkinos` |
| `KARKINOS_DATA_DIR` | `$KARKINOS_HOME/data` |
| `KARKINOS_CONFIG_PATH` | `$KARKINOS_HOME/config/config.json` |
| `KARKINOS_ENV_FILE` | `$KARKINOS_HOME/config/.env` |

覆盖值必须是绝对路径。启动要求已有 `app.db`、`meta.db` 和两个配置文件；
缺失时明确报错，不会默默换成空账户。更换开发分支或更新 main 不复制、重建这些文件。
不要为了修复缺失路径使用 `--init`。

仅首次创建新账户时，显式准备配置并初始化空数据目录：

```bash
export KARKINOS_HOME="${HOME}/Library/Application Support/Karkinos"
mkdir -p "$KARKINOS_HOME/config"
test -e "$KARKINOS_HOME/config/config.json" || cp config.example.json "$KARKINOS_HOME/config/config.json"
test -e "$KARKINOS_HOME/config/.env" || cp .env.example "$KARKINOS_HOME/config/.env"
./scripts/start_server.sh main --init
```

执行 `--init` 前检查配置。已有文件不覆盖，非空数据目录拒绝初始化。
后续启动不带 `--init`。main 的 home/data 生命周期锁、恢复 journal 和
LaunchAgent 互斥仍然生效。已加载的包服务应先用 `./scripts/stop_server.sh prod`
停止；恢复保护不会由启动脚本清除。

从旧版“直接运行当前 main checkout”的服务迁移时，先在旧运行目录执行
`python3 scripts/service/run_main.py --stop`，再调用新版默认 main 入口。
旧版监督进程不会被模糊进程匹配或端口扫描清理。

开发服务用 `./scripts/start_server.sh dev`，默认 backend `8001`、Vite `5173`。
`service/run_dev.py` 固定可识别的源码入口，保留重载并支持精确停止。
`service/dev_environment.py` 为它选择 `.run/dev-home` 下独立的空开发账户；
专用开发配置在 `config/config.json` 与 `config/.env`，数据在 `data/`。
可以设置绝对路径 `KARKINOS_DEV_HOME`；该路径不能复用日常或发布账户。
不会复制原有私人配置或数据库，也不会继承 main 的账户路径和 Python 环境。
需要的数据源配置应写入专用开发配置，`--env-file` 也必须指向该开发环境的配置文件。

## Service lifecycle

| Command | Purpose | Boundary |
| --- | --- | --- |
| `./scripts/start_server.sh` or `./scripts/start_server.sh dev` | Start the current source tree: reloadable backend on `127.0.0.1:8001` plus Vite on `127.0.0.1:5173`. | Uses a dedicated development account and locked backend dependencies; refreshes frontend dependencies with `npm ci` when the lockfile, package metadata, or npm configuration changes. Failed startup cleans up the processes created by that attempt. |
| `./scripts/start_server.sh main` | Fetch main, prepare its exact SHA in an isolated checkout, and start in the background with the existing account; return after service readiness. | Logs rotate under `$KARKINOS_HOME/logs/`. Uses the original runtime data and configuration under lifetime locks; missing account files, loaded managed services, or pending recovery fail closed. |
| `./scripts/start_server.sh main --foreground` | Start the same managed main service and follow its logs in the terminal. | Ctrl+C stops it; logs also remain in the rotating log files. |
| `./scripts/start_server.sh prod` | Start the supervised API and isolated research worker from the immutable release already selected by `~/Library/Application Support/Karkinos/current`. | Never builds from the checkout, copies source into a release, updates `current`, or falls back to source execution. It requires both processes to belong to the exact current release and fails closed when either is unavailable. |
| `./scripts/stop_server.sh` or `./scripts/stop_server.sh dev` | Stop only the exact tracked development processes. | Symmetric with the default development start and never touches production. |
| `./scripts/stop_server.sh main` | Ask the running main supervisor to stop its API and research worker. | Uses the managed home control endpoint without Git checks or a release controller. |
| `./scripts/stop_server.sh prod` | Stop only the exact supervised production service. | Uses the packaged controller and persisted service port; it does not kill unknown listeners or sweep ports. |
| `./scripts/stop_server.sh all` | Explicitly stop development, main, and production, attempting each even if another stop fails. | Validates recorded PID, process command, and start identity for every target. |

Bootstrap records the production port once in the private managed-runtime
receipt (`.service-config.json`), defaulting to 8000. Updates, rollback,
recovery, status, start, and stop reuse that value automatically. The wrappers
only pass `KARKINOS_BACKEND_PORT` when it is explicitly set; a value that does
not match the receipt fails closed instead of silently moving the service to a
different port. To bootstrap on a non-default port, pass `--service-port` once
or set `KARKINOS_BACKEND_PORT` for that bootstrap command.

Development passes its effective host and port to the backend explicitly;
`--host` and `--port` override the development defaults. In Docker Compose,
`KARKINOS_PORT` selects the published host port; the container listener and
health check remain on port 8000.

The live scheduler always starts with every backend and has no service-level off
switch. Its liveness is required before startup succeeds. Automatic trading is
a different, default-off runtime gate on the Trading page; an operator can open
or close it without restarting the service. That gate grants no capital or
broker authority by itself, and automatic broker submission is not implemented.
For AI research, the API scheduler performs provider-free qualification and
durable enqueue only. A separate `com.karkinos.research-worker` LaunchAgent owns
automatic AI provider access. Stable activation checks both agents. The standard
server entrypoint also supervises a separate `--data-worker` child for calendar
ingestion when calendar auto-sync is enabled; an exited child is restarted.
Initial spawn failure leaves the API available and retries in the supervisor.
An inherited lifetime pipe terminates the child after abrupt parent death. Calendar
execution has a 120-second deadline; lease loss or release activation ends the
worker, and the final publication transaction rejects stale or guarded writes.
Calendar jobs use persisted owner/attempt/expiry fencing at publication. Other
market polling loops are still hosted by the API. Neither readiness nor worker
heartbeat grants trading authority. Candidate runs never install LaunchAgents;
the state replay probe suppresses provider work using the release guard.

`GET /api/health` remains liveness only. `GET /api/health/readiness` reads persisted
worker heartbeats and publication state; a readable last-good valuation can coexist
with an unresolved refresh failure. Exact decision/risk/human authority gates must
still be evaluated for the requested action.
This projection covers account valuation inputs, not research dataset readiness.
Refresh success does not resolve old publication incidents: a fact-bound repair
receipt/resolver remains required and is not implemented in this slice.

Set `KARKINOS_LOG_MAX_BYTES` to a positive byte count to change the default
20 MiB development-log archive threshold. Archives remain under `logs/`; the
start script does not delete them.

## Immutable native release workflow

The production runtime has one mutable root and immutable release directories:

```text
~/Library/Application Support/Karkinos/
  current  -> releases/sha-<40-hex-commit>
  previous -> releases/sha-<40-hex-commit>
  releases/
  data/
  config/
  logs/
  .service-config.json  # private persisted production-port receipt
```

The native macOS artifact is built by CI with a locked Python runtime and
`web/dist`. Downloaded bytes are accepted only after architecture, checksum,
manifest identity, Release metadata/digest where applicable, and GitHub
build-provenance attestation agree. Native production neither requires nor uses
a local Docker service, local `web/dist`, or a build from the source checkout.

For the companion container image, the candidate manifest's OCI digest is the
authoritative immutable identity. SemVer and `sha-*` tags are treated as
write-once by the release workflow, but GHCR does not expose repository-owned
tag-immutability enforcement here; access to package-write credentials remains
an external administrative control.

After the one-time bootstrap, use the packaged controller. These commands do
not require a source checkout:

```bash
KARKINOS_CTL="$HOME/Library/Application Support/Karkinos/current/bin/karkinosctl"
"$KARKINOS_CTL" status
"$KARKINOS_CTL" service-start
"$KARKINOS_CTL" service-stop
```

The repository wrappers are convenience adapters: `./scripts/start_server.sh
prod` delegates to `service-start`, and `./scripts/stop_server.sh prod`
delegates to `service-stop`. `status` probes the persisted port and reports the
exact HTTP release identity, scheduler state, and any retained recovery journal;
it does not claim financial readiness.

### Test an exact candidate without a tag

When managed `data/app.db` exists, the candidate runner first checks a disposable
SQLite-consistent state copy with the candidate's `--replay-state` entrypoint.
It exercises migrations, guarded application startup/read/shutdown, durable jobs,
a second candidate process, and the previous release's state checker on a restored
baseline. The managed macOS candidate entry denies network access for the process
tree with `sandbox-exec`; Python socket hooks also detect attempts. A direct gate
call without OS isolation explicitly reports `network_isolation=not_checked`.
Failed checks stop the candidate; the
production files and pointers are not replaced. The read probe uses ASGI in process;
TCP, launchd, and live worker readiness remain separate release checks. A live
backup is consistent per SQLite database, not a coordinated cross-store snapshot.
Ledger identity, unresolved incidents, response snapshot/cutoff identity and
zero app.db writes during GET are asserted. The old release's restored-baseline
preflight does not prove rollback startup/read/shutdown; `release_eligible=false`
keeps this component check separate from full release acceptance.
The historical `data/backups/` archive is excluded from this runtime-state probe.
For a closed WAL database that cannot be opened read-only without sidecars, the
probe copies it only while no WAL/journal exists and file identity, size and
timestamps remain unchanged, then verifies SQLite integrity in the copy.

Before the first stable bootstrap there is no packaged `current` controller.
From the repository checkout, the supported pre-bootstrap candidate entry is:

```bash
SHA=0123456789abcdef0123456789abcdef01234567
UV_CACHE_DIR=.uv-cache uv run python scripts/release/manage_release.py \
  candidate --commit-sha "$SHA"
```

This source command is only a verifier/launcher for disposable candidate bytes;
it cannot select a production pointer. After bootstrap, use the packaged
controller instead. Authenticate `gh` (or provide `GH_TOKEN` without putting it
in an argument), then pass the full lowercase 40-hex commit from the candidate
CI run:

```bash
SHA=0123456789abcdef0123456789abcdef01234567
"$KARKINOS_CTL" candidate --commit-sha "$SHA"
```

The command fetches and verifies that exact Actions artifact, stages it, and
runs it in the foreground on `127.0.0.1:18000` by default with disposable `data/`,
`config/`, and `logs/`. It never points `current` or `previous` at the candidate
and discards the staged candidate when the run exits or fails. A Git tag is not
required for this validation. If production itself is configured on 18000, the
implicit candidate port becomes 18001; an explicit `--port` equal to the
persisted production port fails closed. If the same commit has been rebuilt or rerun, the
fetcher selects the latest completed successful official `main` Release
Candidate run attempt, then binds its run id, run attempt, artifact id, artifact digest,
and manifest identity in `candidate-selection.json`; artifacts from older
attempts do not make the result ambiguous. A changing or incomplete Actions
listing fails closed. Manual dispatch must use the exact commit selected as the
workflow ref because GitHub provenance binds that immutable workflow SHA.

### Install a published stable release

A stable update requires authenticated GitHub CLI access and a published,
non-draft, non-prerelease strict SemVer tag such as `v0.3.2`; tags are stable
release markers, not candidate-test prerequisites:

```bash
TAG=v0.3.2
"$KARKINOS_CTL" update --tag "$TAG" --confirm "UPDATE $TAG"
```

The update verifies that the tag, Release, asset digest, archive, checksum,
manifest, attested workflow, and exact commit agree. It then locks the runtime,
probes the artifact with disposable state, stops production, snapshots the real
mutable state, runs the target's provider-free state preflight on a clone,
atomically switches `current`, starts the service, and verifies exact version,
commit SHA, artifact fingerprint, process health, and scheduler liveness.
It then keeps the durable journal and unsafe HTTP guard in place, opens only the
scheduler gate in an explicit readiness phase, and requires at least one
completed loop iteration or initialized-idle pass before committing. A failed
post-guard iteration therefore rolls back instead of being discovered after
the journal has already been cleared.

`v0.3.2` is the activation-protocol floor for this managed updater. Releases
through `v0.3.6` bind `release_control_protocol=1`; two-process releases bind
`release_control_protocol=2`. An installed protocol-1 controller rejects a
protocol-2 target before activation. For that first transition, obtain the
target tag's attested standalone installer and let the target controller own
the update in the same explicit operation:

```bash
TAG=v0.3.7
"$BOOTSTRAP_DOWNLOAD_DIR/bootstrap_installer.sh" \
  --tag "$TAG" \
  --confirm "UPDATE $TAG"
```

The protocol-2 manager accepts a validated protocol-1 installed release only
as the rollback source, while requiring protocol 2 for the newly staged target.
It therefore installs and proves both the API and research worker on success,
but can restore the old single-process release if activation fails. Later
protocol-2 updates use the normal `karkinosctl update` command above.
An activation failure restores the saved mutable state and old pointers before
restarting the old release. If recovery itself is inconclusive, the durable
journal is retained and later mutations fail closed for explicit recovery.

`status` reports `recovery.required=true` and the retained phase. Recover with
the exact fixed acknowledgement:

```bash
"$KARKINOS_CTL" recover --confirm "RECOVER RELEASE STATE"
```

If an interrupted switch left `current` absent, execute the same command with
the still-validated `previous/bin/karkinosctl`. If neither pointer provides an
executable controller, stop and retrieve the exact attested controller for the
journal's release; do not guess a release directory or clear the journal.

After a successful update, only `current` and `previous` remain under
`releases/`; older versions remain downloadable from GitHub. `current` is the
running stable version and `previous` is the single local rollback target.
Restarting with `./scripts/start_server.sh prod` never changes either pointer.

Inspect `previous` with `status`, then roll back with its exact SHA:

```bash
"$KARKINOS_CTL" rollback \
  --confirm "ROLLBACK <previous-40-hex-commit>"
```

### Standalone migration entry points

For either the protocol transition above or an old source-based service with no
managed `current`/`previous`, obtain and externally verify the target stable
Release asset `bootstrap_installer.sh`. Its tracked source is
`scripts/release/bootstrap_installer.sh`; obtain and verify the published copy
as described in
[`scripts/release/BOOTSTRAP_INSTALLER.md`](release/BOOTSTRAP_INSTALLER.md).
For a source-based service, run the one-time handoff without executing release
tooling from the source checkout:

```bash
TAG=v0.3.6
"$BOOTSTRAP_DOWNLOAD_DIR/bootstrap_installer.sh" \
  --tag "$TAG" \
  --legacy-workdir "/absolute/path/to/Karkinos" \
  --legacy-plist "$HOME/Library/LaunchAgents/com.karkinos.daily-candidate.plist" \
  --confirm "BOOTSTRAP $TAG"
```

The standalone entry point validates the local path shape before retrieving its
attested packaged controller. Before that controller performs the complete
release verification, bootstrap validates the exact owner-selected LaunchAgent,
legacy source state, managed-root layout, and the old `releases/prod` inventory.
It verifies the stable artifact, snapshots `.env`, `config.json`, and
`data/store`, checks them with the new runtime, moves mutable state into the
managed `config/` and `data/` directories, switches to immutable `current`, and
requires exact production health and scheduler identity. Any ordinary failure
restores the legacy files, plist, service, and release layout. A successful
bootstrap uses the same journaled scheduler-readiness proof before commit and
deliberately retains an exact legacy quarantine for rollback review.

After observing the new service and checking the production audit, delete only
that validated quarantine with:

```bash
"$KARKINOS_CTL" finalize-bootstrap \
  --confirm "FINALIZE LEGACY BOOTSTRAP"
```

Finalization is explicit and irreversible; it first requires the exact current
release to remain healthy. Do not finalize merely because bootstrap returned
success.

### Internal release and service mechanics

`scripts/service/manage_launch_agent.sh` is the locked two-process
service-manager backend.
Do not call its `install`, `restart`, or `uninstall` mutations directly; use
`./scripts/start_server.sh prod`, `./scripts/stop_server.sh prod`, or the packaged
controller so release locking and exact identity checks cannot be bypassed.

`scripts/release/manage_release.py` is the controller. Its public workflows are
`candidate`, `update`, `bootstrap`, `rollback`, `recover`,
`finalize-bootstrap`, `status`, `service-start`, and `service-stop`. Local
`stage`, `discard`, `promote`, `prune`, `adopt-legacy`, `bootstrap-legacy`,
`run-candidate`, and `download` helpers are Python implementation details and
are deliberately not CLI commands: a self-consistent local archive is not
stable-release authorization and cannot enter production through the packaged
controller.
`scripts/release/update_workflow.py` and
`scripts/release/bootstrap_legacy.py` are internal modules and are not invoked
directly.

## Owner/operator helpers

| Command | Purpose | Local writes or external contact |
| --- | --- | --- |
| `uv run python scripts/service/audit_daily_candidate_production.py --pretty` | Read the running local service's exact financial preflight, monitor, five-round research policy, 20-day / 50-order trial, and compact dependency-ordered operator checklist into one sanitized readiness report. | Loopback GET only; no provider/broker contact or database write. Exit `0` means ready to continue bounded forward paper/shadow collection, not GO, profit, execution, or capital authority; exit `2` is fail-closed non-ready. |
| `uv run python scripts/data/configure_data_source.py` | Owner-facing, occasional local setup helper for selecting AKShare or Tushare. It is not an internal service hook and is not needed for routine start/stop. | Updates the explicitly selected ignored `config.json` and `.env`; Tushare tokens are entered interactively and never accepted as CLI arguments. It does not restart the service. |
| `python scripts/service/repair_legacy_fund_trade_duplicates.py` | Exceptional legacy-data repair, not an ordinary user command. Preview first and use only for the narrowly scoped duplicate correction. | Requires its explicit acknowledgement; remains provider-free and does not submit orders, change capital authority, or silently rewrite unrelated ledger facts. |

For managed production paths, pass them explicitly to the setup helper and then
restart only if the changed configuration requires it:

```bash
uv run python scripts/data/configure_data_source.py \
  --config-path "$HOME/Library/Application Support/Karkinos/config/config.json" \
  --env-file "$HOME/Library/Application Support/Karkinos/config/.env"
```

## Market-data maintenance

| Command | Purpose | Safety boundary |
| --- | --- | --- |
| `uv run python scripts/data/sync_market_bars_to_db.py` | Import existing Parquet bar mirrors into `data/store/meta.db.market_bars`. | Does not fetch remote data. It updates the selected local `DataStore`. |
| `uv run python scripts/data/verify_market_bars.py --symbol SYMBOL --start YYYY-MM-DD --end YYYY-MM-DD` | Fetch one provider range and compare it with persisted local bars. | Contacts the selected market-data provider but does not overwrite local bars. |
| `uv run python -m tools.capture_instrument_exchange_source --source stock-688802 --output-dir reports/public-sse` | Capture one allowlisted public SSE listing announcement; `etf-530380` selects the other supported sample. | Writes immutable public evidence objects and a final capture receipt only inside the explicit output directory. No application database, metadata upsert, historical qualification or automatic application. |

The SSE command verifies the live HTTPS connection, rejects redirects and bounds
response size and time. Objects live at `objects/<sha256>`; successful receipts
live at `captures/<receipt-sha256>.json`. Use
`data.instrument_exchange_source.read_sse_source_object(output_dir, digest)` to
read the original bytes with an expected digest. A later response with different
bytes retains the old object and sets `differs_from_prior_capture`; failure can
leave unreferenced objects, but does not publish a complete successful receipt.
The normalized date interval selects only the announced listing event day. It
does not establish a delisting date, actual trading or continuous historical
affiliation. Capture records preserve `qualification=blocked`, empty verified
dates, `available_at=null` and `human_verification_status=not_performed`.

These commands maintain or verify historical bars. They do not start the live
quote scheduler.

To publish an explicitly prepared PIT daily bundle into a selected local catalog:

```bash
uv run python -m data.dataset_publish --input /path/to/bundle.json --data-dir /path/to/research-data
```

The JSON contains `universe`, `daily`, `cutoff`, and `expected_sessions`. Both row
types require `symbol`, `instrument_type`, `session_date`, `event_time`,
`available_at`, `captured_at`, `source_revision`, `availability_evidence_ref`, and
boolean `suspended`. Universe rows additionally require `membership_status=member`,
`listed_on`, and optional `delisted_on`. Daily rows require `open/high/low/close`,
`volume`, `amount`, and `adjustment_factor`. Timestamps include timezones; the daily
and historical membership keys must cover the exact supplied sessions and symbols.
Unknown fields, duplicates, invalid prices, or availability after cutoff reject
the candidate without replacing the current manifest. Published Parquet bytes are
content addressed; use the printed `DatasetRef` with `DatasetCatalog.read` or
`read_as_of` for explicit replay. The publisher never fetches or estimates missing
source evidence. Its `provider_coverage_verified=false` quality marker means real
historical coverage and availability provenance still require separate review.

## Broker evidence and compatibility

| Command | Purpose |
| --- | --- |
| `uv run python scripts/broker/preview_citic_history_xls.py --path FILE_OR_DIRECTORY` | Privacy-minimized, read-only schema and evidence-gap preview for local CITIC `历史成交` legacy XLS exports. It never prints event/account values or persists evidence. |
| `uv run python scripts/broker/import_broker_order_lifecycle.py --file FILE` | Validate one broker-neutral exact-order lifecycle export. |
| `uv run python scripts/broker/ingest_broker_order_lifecycle_collector_batch.py --file FILE` | Validate one broker-neutral collector batch and its cursor transition. |
| `uv run python scripts/broker/migrate_legacy_qmt_order_lifecycle.py --file FILE` | Explicitly convert the retired QMT v1 export schema into the canonical broker-neutral schema. It does not import the QMT SDK or contact a broker. |

The CITIC history command is preview-only and deliberately remains blocked
until itemized settlement components plus cash and position snapshots are
supplied through separately reviewed evidence. Preview is the default for the
other three commands. Persistence requires `--record`
and the exact acknowledgement printed by the command contract. Recording only
stores validated evidence; it does not submit or cancel orders, mutate the
production ledger, or grant execution authority.

The retired `scripts/broker/import_qmt_order_lifecycle.py` compatibility entry point
was removed. Use the explicit migration command for old QMT exports or the
canonical import command for current broker-neutral exports.

## Broker release validation and operator approval

| Command | Purpose |
| --- | --- |
| `uv run python scripts/broker/review_broker_adapter_release.py --file FILE --db DB` | Preview or explicitly record an adapter release decision. |
| `uv run python scripts/broker/run_broker_adapter_conformance.py --file FILE --db DB --run-id ID` | Run deterministic provider-neutral adapter fixtures. |
| `uv run python scripts/broker/run_broker_execution_edge_conformance.py --file FILE --db DB --run-id ID` | Run deterministic submit/query/cancel boundary fixtures without contacting a broker. |
| `uv run python scripts/broker/operator_signer.py init ...` | Create a local Ed25519 private key and print its public configuration fragment. |
| `uv run python scripts/broker/operator_signer.py sign ...` | Validate and sign one short-lived canonical challenge read from standard input. |

`operator_signer.py` never calls the Karkinos API or edits `config.json`. Keep
the private key outside the repository with permissions `0600` or stricter.

## CI and release checks

CI 的目标是保留一次可信的晋级前全量验证，并让晋级后的同一提交复用这份结果。
复用只减少已被证明完成的检查；main 仍产生独立的 `Code CI gate`，供候选制品和
发布源校验使用。是否允许复用由代码检查 GitHub 的 run/job 记录决定，调用者不能
通过一个布尔输入声明“已经测过”。

### 阶段与职责

```text
dev 提交 C
  -> Dev CI：按变更分类，提供快速反馈
  -> 旧 main 的可信晋级工作流 W：对 C 执行一次完整 ci.yml
  -> 无 checkout 的独立 job：Verified source <C>
  -> 再核对验证身份，非强制 fast-forward main 到 C
  -> main CI：校验晋级证据 + 当次安全检查 -> Code CI gate
  -> 候选制品构建和原有发布验证
```

| 阶段 | 必须执行 | 可以省去的工作 |
| --- | --- | --- |
| `dev-ci.yml` | 现有保守分类、对应测试和 `Dev CI gate` | 只有明确独立的测试变更或文档范围按原分类减量 |
| `promote-dev.yml` 晋级前 | 在可信旧 main 工作流下，对候选 C 运行全部检查和验收证据校验 | 无；增量 Dev CI 成功不能替代这一轮 |
| 晋级后的 `ci.yml`，有效复用 | 复用计划、仓库卫生、秘密扫描、依赖审计、上游验收证据复核、最终 gate | Python quality、仓库契约、后端、前端、交易安全、Docker runtime、浏览器安全的重复执行 |
| main 无有效复用证据 | 原完整检查集、JUnit/coverage 和验收证据校验 | 无 |
| Candidate / Release | 原有 exact-main CI gate、构建、制品与 provenance 校验 | 本设计不省略制品检查，也不改变发布身份 |

Dev CI 的分类保持不变：独立 test-only 修改可以只跑变更测试；跨模块引用、源码、
共享 fixture、删除测试或未知范围扩大后端检查。每个后端范围继续执行交易安全套件，
依赖变化同时审计 Python 和 npm。缺失分类或不符合计划的 skipped job 均失败。
源码变化仍可能在 dev 和晋级前各测一次：前者用于快速反馈，后者建立由旧 main
工作流控制的权威完整验证。这里去掉的是同一候选晋级后的第三轮重复计算。

`ci.yml` 是唯一完整验证实现，通过 `workflow_call` 被可信晋级工作流复用，也接受
main push/手动 dispatch。dev 上的显式完整 CI dispatch 保留，必须使用精确提交、
祖先 base 和 `pre_promotion=false`。它只提供验证，不移动 main。

### 证据身份与信任边界

记候选提交为 C，发起晋级的受保护旧 main 提交为 W。晋级完整检查成功后，独立
job 的名称由 `needs.select.outputs.commit_sha` 绑定为 `Verified source <C>`。
该 job 只比较选择结果与完整检查返回的 `verified_sha`；不 checkout，不执行候选
脚本，不下载候选 artifact，并使用 `permissions: {}`。只有它成功后，写分支 job
才可以继续。GitHub 支持在 job 名称中使用 `needs`，名称在 runner 执行之前由工作流
求值。[GitHub contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)

这份 receipt 指 GitHub Actions 控制面中这次 run/attempt 的成功 job 记录。普通
commit status、候选测试生成的 JSON、同名 artifact、缓存命中或可编辑日志都不能
单独授予复用资格。`Main promotion gate` 仍服务于现有分支规则；复用验证不将其
当作完整检查证据。候选代码可以运行在测试 job 中，但不能通过写文件或 step output
伪造独立 receipt job 的候选身份。

可信根是受保护 main 的工作流/验证器，以及 GitHub 对仓库、工作流、run 和 job
身份的记录。此设计不承诺抵御已控制 GitHub 控制面、仓库管理员或可信 main 的攻击者。
测试通过、CI gate 和 receipt 都不授予交易、资金或 broker 权限。

写分支 job 继续只执行可信 main 代码，拥有晋级所需的 contents/actions/statuses
写权限；读取复用证据的 job 仅获取必要的读权限，完整测试 job 不获得晋级写权限。
权限按 job 声明，不为复用扩大全工作流权限。
[GitHub workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions)

### 复用计划与策略指纹

main 的 `verification-plan` 首先 checkout `github.sha` 并校验本次仓库、事件、
分支、checkout、输入 SHA 和 base 的一致性，之后才处理复用提示。dispatch 的
`promotion_run_id`、`promotion_run_attempt` 只是定位提示；它们不是授权证据，
不能改变实际 checkout，也不能使 dev 或晋级前调用进入复用。

允许复用必须同时满足以下条件：

1. 本次确为允许的 main CI 上下文，C 是本次精确 checkout；未指定 `force_full`。
2. 提示指向本仓库的可信晋级 workflow ID 和精确 workflow path，分支是 main，
   事件为 `schedule`、`push` 或 `workflow_dispatch`；不能借用 fork、PR、dev 或
   另一条同名工作流的成功结果。
3. 上游 run 已完成且成功；指定 attempt 是该 run 当前最新 attempt。必须按 attempt
   查询 jobs，不能把旧成功 attempt 与当前失败或运行中的 attempt 混在一起。
4. 所有要求的完整检查、完整 gate 和唯一的 `Verified source <C>` job 都成功，
   没有缺失、重复、失败、取消或被跳过的必需 job。
5. W 是 C 的严格祖先；W 与当前 C 的 CI 策略指纹一致，证明上游采用的验证规则仍适用。
6. 所有必需 job 的完成时间合法且距今不超过 24 小时；读取 jobs 后再次读取 run，确认
   run/attempt/完成状态未在查询过程中改变。

GitHub 为特定 run attempt 提供独立 jobs API；本项目使用这种精确身份绑定，避免
默认查询范围掩盖重跑。[GitHub workflow jobs API](https://docs.github.com/en/rest/actions/workflow-jobs)

策略指纹从 Git tree 的路径、文件模式、对象类型和 blob 身份计算，不读取工作区
未提交内容。非普通文件被拒绝。具体范围由 `tools/ci_reuse.py` 的 `_policy_path`
维护，新增策略依赖时必须同时更新集合和契约测试：

| 范围 | 指纹覆盖 |
| --- | --- |
| 工作流与检查入口 | `.github/workflows/`、`.github/actions/`、`scripts/ci/` 下所有文件 |
| 验证与晋级 | `tools/ci_reuse.py`、`tools/verify_release_source_ci.py`、`tools/check_python_architecture.py`、`tools/promote_dev*.py` |
| 验收规则 | `analytics/` 下路径含 `acceptance` 的文件 |
| Python 与容器配置 | `pyproject.toml`、`uv.lock`、`.python-version`、`.pre-commit-config.yaml`、`Dockerfile`、`.dockerignore`、`pytest.ini`、根目录及 `tests/` 的 `conftest.py` |
| 前端配置 | `web/package.json`、`web/package-lock.json`、`web/.npmrc`，以及 `web/` 根级名称含 `config`、`prettier`、`eslint` 或 `npm` 的文件 |

`ci.yml`、`promote-dev.yml` 和 `tools/ci_reuse.py` 必须存在于两侧策略集合。
候选 SHA 已绑定完整代码、依赖锁文件与测试输入，
指纹另行回答“旧 main 使用的验证规则是否仍是当前规则”。不能仅比较 workflow 名称
或 runner 日志中的版本字符串。策略变化时，晋级前旧规则和晋级后新规则分别完整执行，
不得把旧规则下的成功直接升级为新规则下的通过。

24 小时是复用资格的上限，不是漏洞数据库、runner 镜像或外部工具不会变化的保证。
所以 main 每次仍运行仓库卫生、秘密扫描和依赖审计；依赖锁定也不能代替当次漏洞审计。
该上限不提供跨提交测试缓存，同一代码树的不同 SHA 也不能互相冒用 receipt。

### 完整路径、复用路径与最终门禁

完整路径保留现有测试命令、JUnit/coverage 上传、验收清单及测试证据绑定，不降低
断言、覆盖率要求、类型检查、生命周期或交易安全检查。复用路径不复制或伪造当次
JUnit：`Repository acceptance audit` 再次验证上游完整验收检查的精确身份，成功后
输出 `evidence_rechecked`，明确表示证据已复核，而非测试在本次重新执行。

`Code CI gate` 校验精确的 `needs` 集合与两套允许状态：完整模式下所有检查成功；
复用模式下仅列入复用集合的计算 job 必须是 skipped，其余检查及验收复核必须成功。
额外或缺失依赖、任意 skipped、复核输出缺失、取消与失败都不能变成绿色。即使初始
复用计划成功，结束前发现上游已重跑、过期或身份变化，也必须使 main gate 失败。

| 情形 | 行为 | 运维含义 |
| --- | --- | --- |
| 无提示、旧晋级器没有 receipt、记录过期或策略指纹变化 | 选择完整模式 | 可正常完成 CI，不要求手工伪造证据 |
| 初次读取 API 失败、记录不匹配或复用资格不完整 | 选择完整模式并输出原因 | 外部查询失败只增加计算，不能减少验证 |
| `force_full=true`、dev dispatch、晋级前调用 | 强制完整模式 | 保留排障和人工完整验证入口 |
| 本地 checkout/输入/事件身份非法 | 立即失败 | 不在错误代码身份上继续测试 |
| 已选择复用后，验收复核失败或 run/attempt 改变 | gate 失败 | 此时已跳过重任务，不能静默当作完整验证成功 |
| main 已晋级但 CI/candidate dispatch 缺失 | 原有 repair-followup 补发缺失 run | 不改写 main，不自动重跑已有失败检查 |

操作时先查看 `verification-plan` 的模式与原因；需要排除复用因素时，在 main 的
完整 CI dispatch 中提供精确 `commit_sha`、祖先 `base_sha` 和 `force_full=true`。
复核失败后重新 dispatch 可以重新选择安全路径，不能通过编辑 artifact、status 或
修改必需检查来“修复”证据。候选构建和 release-source verifier 继续要求精确 main
run 及原有命名 gate；候选 manifest schema 和分支规则不因 CI 去重而变化。

例如，用 GitHub CLI 强制重跑远端当前 main，以其第一父提交作为质量检查的 diff base：

```bash
ci_repository='imReese/Karkinos'
ci_commit_sha="$(gh api "repos/${ci_repository}/commits/main" --jq '.sha')"
ci_base_sha="$(gh api "repos/${ci_repository}/commits/${ci_commit_sha}" --jq '.parents[0].sha')"
gh workflow run ci.yml --repo "$ci_repository" --ref main \
  -f commit_sha="$ci_commit_sha" \
  -f base_sha="$ci_base_sha" \
  -F force_full=true
gh run list --repo "$ci_repository" --workflow ci.yml --branch main \
  --event workflow_dispatch --commit "$ci_commit_sha" \
  --json databaseId,attempt,createdAt,status,conclusion,url
```

使用 dispatch 返回的新 run URL；如果未返回 URL，在列表中核对 SHA 和新建时间后取
`databaseId`，再执行 `gh run watch RUN_ID --repo imReese/Karkinos --exit-status`。
不要把更早的同 SHA run 当成此次结果。若读取 SHA 后 main 已前进，身份检查会拒绝
旧输入，重新读取并 dispatch 即可。`base_sha` 只影响增量 Python quality 的差异范围，
完整测试仍执行原集合；无需改分支或填写晋级证据提示。

### 迁移、验证与成本

引入复用逻辑的首次晋级由旧 main 工作流执行。它没有新 receipt 或新 dispatch 提示，
所以新 main 必须走完整路径。这同时验证新规则，不能为了演示去重而跳过这次迁移检查。
随后使用一个不修改策略指纹的正常变更，验证真实的 dev -> 晋级全量 -> main 复用链路，
并核对 candidate 仍能接受 main gate。上线验证应分别记录真实 run ID/attempt 与 SHA；
本地模拟测试不能替代 GitHub 的工作流调度、权限和 job 名称验证。

确定性测试覆盖正确复用，以及错误仓库/工作流/事件/分支/SHA/receipt、缺失或重复 job、
skipped/失败 job、过期或未来时间、旧 attempt、查询期间重跑、策略改变、API 错误、
强制完整和最终 gate 状态矩阵。工作流契约测试同时约束独立 receipt 的无 checkout/
无权限边界、精确 job 集合、完整模式证据命令和稳定 gate 名称。

预期节省来自省去晋级后第二次完整后端、前端、契约、容器和浏览器执行。main 增加
只读 API 校验与当次安全检查，仍有调度开销；实际耗时由 GitHub 队列和 runner 决定，
不承诺固定加速倍数。策略修改、过期证据或 GitHub API 故障会主动退回完整成本。
维护这套验证协议的成本由一个共享验证器及契约测试承担，不建立第二份测试实现。

Changing `.github/rulesets/main.json` does not apply it to GitHub. For any future,
owner-approved gate migration, first obtain a complete check accepted by the
currently enforced rule for the exact candidate. A successful manually
dispatched run alone does not prove protected-branch eligibility. Install the
trusted main automation under the existing protection, explicitly apply the
new GitHub rule, and verify a real candidate through full verification, its
required status, and a non-forced fast-forward. Any temporary trigger used for
that migration must be removed, with its cleanup commit verified through the
trusted promotion path. Release-source verification continues to require a
main run. Never relax the rule or use a force push to perform a gate migration.

| Command | Purpose |
| --- | --- |
| `uv run --locked --extra dev python scripts/ci/check_python_quality.py --base origin/main` | Run incremental Ruff, Black, isort, and stable type/architecture checks without rewriting files; use `--base HEAD~1 --head HEAD` for the exact committed diff. |
| `python scripts/ci/classify_dev_changes.py --base BASE --head HEAD` | Classify an exact ancestor-to-checkout diff for dev CI; unknown scopes broaden checks rather than silently skipping tests. |
| `uv run python scripts/ci/check_docs_health.py` | Check core documentation budgets, local links, language pairs, and roadmap/test separation. |
| `uv run python scripts/ci/export_acceptance_audit.py --audit all` | Export acceptance manifests and optionally bind deterministic test evidence. |
| `uv run python scripts/ci/verify_docker_runtime.py` | Confirm a built container starts with the live scheduler running while broker and capital authority remain disabled. |

Do not delete or rename CI entry points without updating their workflow,
acceptance-registry, documentation, and test consumers.
