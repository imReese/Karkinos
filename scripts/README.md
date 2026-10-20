# Karkinos Scripts

Run commands from the repository root.

## Start

Run the stable `main` branch:

```bash
./scripts/start_server.sh
```

Equivalent to:

```bash
./scripts/start_server.sh main
```

Run the current `dev` working tree:

```bash
./scripts/start_server.sh dev
```

Run another locally available branch:

```bash
./scripts/start_server.sh <branch>
```

Behavior:

* `main` runs the locally available `origin/main`, falling back to local `main`.
* `dev` runs the current `dev` working tree, including uncommitted changes.
* Other branches run from managed Git worktrees.
* The launcher never switches the current checkout.
* The launcher never runs `git fetch`.
* Only one Karkinos source runtime may run at a time.
* Background runtimes start in an independent session so closing the launcher
  session does not terminate the runtime manager.

Source startup waits up to 180 seconds for readiness by default. Override
`KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS` for a measured local startup need
(development accepts at most 300 seconds). Database preparation checks whole-file
integrity before starting writers; ordinary DataStore attachments recheck schema
and provenance constraints without repeating that scan for every consumer.

Refresh a remote branch explicitly when needed:

```bash
git fetch origin
./scripts/start_server.sh main
```

`main` uses the repository-local stable configuration and data.

`dev` and other non-`main` branches use development state under:

```text
~/.karkinos/development/
```

The default development directory continues to copy newer repository `config.json`
and `.env` files. Set `KARKINOS_DEV_HOME` to a different directory for an independent
workspace. Its configuration is never copied from the repository: existing files,
including an empty `.env`, are preserved. A new custom workspace starts with AI and
automatic market-data synchronization disabled and an empty `.env`; configure its
`config/config.json` and `config/.env` explicitly before enabling those features.

Development runs the Web UI with Vite HMR and the backend with reload:

```text
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000
```

Stable `main` serves the built Web application and API from:

```text
http://127.0.0.1:8000
```

## Stop

Stop the currently running Karkinos source runtime:

```bash
./scripts/stop_server.sh
```

`stop_server.sh` takes no arguments; it stops the currently managed runtime
regardless of which branch started it.

The stop script only stops processes owned by the launcher and does not
terminate unrelated processes based on port usage. It verifies the recorded
process identity before signaling the runtime PID.

A missing or exited manager PID does not prove its children have stopped. If
startup reports an occupied port, inspect its owner with the printed `lsof`
command. Development supervisor lifecycle records (PIDs, signals, and child exit
codes) are written to `logs/dev-server.log`; an uncatchable `SIGKILL` cannot write
its own final log entry.

## Dependencies

Install Python dependencies:

```bash
uv sync --locked --extra server --extra dev
```

Install frontend dependencies:

```bash
npm ci --prefix web
```

Specialized tooling is grouped under `broker/`, `ci/`, `data/`, `release/`, and `service/`.

## 市场数据统一同步与历史回补

行情同步在底层由 [`server/services/market/sync.py`](../server/services/market/sync.py) 统筹，支持交易日历、基准指数、主流ETF、公募基金净值与个股日K线全量/增量同步，以及最新行情快照原子发布。

- **后台自动化（生产与日常运行）**：
  - 收盘后（15:00 ~ 16:00），`TradingScheduler` 自动同步并补齐基准指数日K、自选池日K与收盘快照；
  - 晚间（21:30），自动同步场外公募基金最新净值并触发核算；
  - 零点，`data_worker` 自动核验并更新交易日历。
- **Web API（管理端一键触发）**：
  - `POST /api/market/sync`：触发指定宇宙或标的的后台同步任务；
  - `GET /api/market/sync/status`：查询最近一次同步结果与执行状态。
- **CLI 脚本（冷启动与深度历史回溯）**：
  [`data/sync_market_history.py`](data/sync_market_history.py) 作为统一服务的命令行门面，用于离线部署、首次冷启动及任意标的深度回补：

```bash
# 同步核心宇宙（基准指数 + 主流ETF + 持仓基金 + 自选股）从 2020 至今的所有历史与今日收盘
uv run --locked python scripts/data/sync_market_history.py --universe core --start 2020-01-01

# 沪深全市场历史：自动截至可采集的收盘日，默认不包含北交所
uv run --locked python scripts/data/sync_market_history.py --universe full-market --start 2020-01-01

# 指定任意股票代码高速拉取完整历史并沉淀至本地
uv run --locked python scripts/data/sync_market_history.py --symbols 600519,300750 --start 2015-01-01
```

`full-market` 与 HTTP `/api/market/sync` 共用市场同步服务，复用现有
`market_daily_verified` 队列和 data worker。需要已有、带观测时间和上市日期的完整证券主数据快照，
以及请求区间内逐年经过核验的交易日历；缺失时明确失败，不访问另一个工作区的数据库作为回退。
使用正常运行的 data worker（`python -m server --data-worker`）执行采集、双源核对和发布；
不另设补数 worker。任务在 `app.db` 中持久化，验证数据和原始证据在 `research/` 中持久化，
发布后登记 Dataset Catalog。旧 SQLite 回执和已冻结研究输入保持原值，新的研究可使用已有
verified Dataset supplement 机制补足旧回执缺失的股票。

退出码 `0` 表示全部任务的 Dataset 已登记且可离线重放；`2` 表示任务仍在排队或运行；
`1` 表示失败。重复同一范围会复用任务；通过输出中的快照 ID 配合
`--universe-snapshot-id` 固定证券主数据，`GET /api/market/sync/status` 会读取持久任务状态。
`--exchanges SSE,SZSE,BSE` 可显式加入北交所。当前存续股票及其观测到的上市/退市日期
只定义研究范围，不等于完整历史 PIT 成分。缺少行情不能自动解释成停牌。
`--force` 创建新的观测轮次而不覆盖旧证据；`--throttle` 仅为兼容旧命令保留，节流和额度由 worker 管理。
`full-market` 不支持仅复制 `meta.db` 的 `--mirror-to-repo`，迁移应保留整个数据目录。

## 数据源安全配置

[`data/configure_data_source.py`](data/configure_data_source.py) 交互式配置本地数据源（AkShare / TuShare）凭据，安全写入本地未被 Git 跟踪的 `config.json` 与 `.env`，避免凭据泄漏至命令行参数或版本库：

```bash
uv run --locked python scripts/data/configure_data_source.py
```

## 本地行情数据核验

[`data/verify_market_bars.py`](data/verify_market_bars.py) 将本地 `meta.db` 中的日线数据与远程数据源独立对比，核验行情价格与成交量的一致性（只读检查，不修改本地缓存）：

```bash
uv run --locked python scripts/data/verify_market_bars.py \
  --symbol 600519 --start 2024-01-01 --end 2024-12-31 --provider akshare
```

分钟线使用 `--frequency 1m` 或 `5m`，逐根比较完整时间。`--start` 和 `--end` 支持日期或 ISO datetime；日期型 `--end` 包含当天全部时间，完整 datetime 保持精确的 inclusive 边界。

`--instrument-type` 选择本地缓存的精确身份，例如 `etf` 或 `open_end_fund`。ETF 与开放式基金都使用 `--asset-class fund`，此时必须同时指定精确类型；两者冲突时会在读取数据前拒绝。省略资产大类时可由精确类型确定；两者均省略则沿用股票。

## 离线数字签名工具

[`broker/operator_signer.py`](broker/operator_signer.py) 为高敏感度人工复核操作（如撤销会话、结算冲正、对账放行等）生成离线分离式数字签名。私钥由操作员在离线受控环境保存，签名载荷通过界面提交，私钥永不进入 Karkinos 运行时或浏览器：

```bash
# 生成操作员 Ed25519 签名密钥对
uv run --locked python scripts/broker/operator_signer.py generate-keypair

# 离线签署操作载荷
uv run --locked python scripts/broker/operator_signer.py sign \
  --key-path operator.key --payload-file payload.json \
  --expected-action revoke_controlled_session \
  --expected-artifact-type controlled_session_revocation
```

## macOS 后台服务受管守护

[`service/manage_launch_agent.sh`](service/manage_launch_agent.sh) 管理 macOS 原生 `launchd` 用户级守护进程（自动随系统自启、日志轮转与保活）：

```bash
# 查询当前 LaunchAgent 运行状态
./scripts/service/manage_launch_agent.sh status

# 安装并启动受管服务
./scripts/service/manage_launch_agent.sh install

# 停止并卸载受管服务
./scripts/service/manage_launch_agent.sh uninstall
```

## TDX 日线手动检查

[`data/check_tdx_daily.py`](data/check_tdx_daily.py) 检查一只股票、一个已经收盘的交易日。
脚本不扫描股票池、不自动重试、不启动服务，也不会写入现有业务数据库。

先安装锁文件中的依赖，再做不联网的预检查：

```bash
uv sync --locked --extra dev
uv run --locked --extra dev python scripts/data/check_tdx_daily.py \
  --symbol 600000 --date 2026-09-14
```

`status=preflight` 表示参数和配置文件可以解析，且能找到 `tdxaidata` 包。
`credential_configured` 表示本次配置中是否有非空 Key，`env_file_loaded` 表示是否加载了环境文件。
预检查不会加载原生库、调用行情接口或创建数据目录；这些结果不代表认证已经通过。

### 统一配置与认证

在仓库根目录的 `.env` 中维护 `KARKINOS_TDX_DATA_SERVICE_KEY` 即可，不需要手工复制到 INI。
`KARKINOS_TDX_USER` 是可选用户标识，仅在数据服务要求时填写。不要把真实值放进命令行、
Git、日志或 Issue；`.env.example` 只提供空模板。

Server 和本脚本共用 `server/runtime_environment.py` 的文件选择、解析和合并逻辑。
文件路径选择：`--env-file` > 进程中的 `KARKINOS_ENV_FILE` > 入口的默认 `.env`。
本脚本的默认文件固定在仓库根目录；Server 继续使用其运行目录，受管启动器可以显式指定文件。
显式选择的文件不存在会报错，不静默回退到别处的配置。已有非空进程环境变量覆盖文件值，
可选凭据的空字符串沿用 Server 的“未配置”约定。Server 的普通配置仍按
显式参数 > 环境 > config.json > 默认值合并，不把实际 Key 复制到 config.json。

本脚本生成只读环境快照，再提取不可变的 `TdxRuntimeSettings`；组件不重复读文件，
也不在导入时创建全局 client 或缓存 Key。更换 Key 后重新执行命令或重启服务即可。
指定其他文件时，在原命令上添加 `--env-file /absolute/path/to/credentials.env`。
离线预检查允许缺少 Key，真正调用前会以 `tdx_data_service_key_missing` 提前拒绝。

已静态核对锁定的 `tdxaidata 1.0.2` 发行包 Python 封装和随包 INI：
SDK 支持通过 `TDX_AI_DATA_LIB` 指定原生库，并切换到库目录读取 `TdxAiData.ini` 的
`[Token] token`（以及可选 `user`）。它的全局单例和工作目录副作用必须留在子进程。
Karkinos 因此在父进程管理的临时目录中复制所需库、生成专用 INI，再把库路径仅传给子进程。
不会改写安装包或已有 SDK 配置，也不需要虚构 `initialize()` / `set_token()` 接口。
此桥接目前只接受已核对的 1.0.2 布局；更新 SDK 后需重新验证，不静默套用旧假设。

临时目录在 POSIX 上为 `0700`，INI 为 `0600`；Windows 使用用户临时目录的访问控制。
正常退出、SDK 崩溃或超时后由父进程清理；即使指定 `--output-dir`，认证文件也不保留在数据目录中。
强制杀死父进程或断电可能留下临时目录；权限限制不能代替系统安全，也不能保证抹除磁盘内容。
子进程不继承其他 `KARKINOS_` 凭据，SDK 原始日志和异常自由文本仍不会返回终端。

明确允许真实调用后执行：

```bash
uv run --locked --extra dev python scripts/data/check_tdx_daily.py \
  --symbol 600000 --date 2026-09-14 --allow-network
```

这会调用一次 SDK 日线接口，可能消耗数据服务积分，不能承诺其内部的请求次数或计费数。
默认 60 秒超时，可用 `--timeout 120` 调整，允许范围为 1 到 300 秒。
原生库在子进程运行；脚本不转发 SDK 的 stdout、stderr 或异常链，避免认证信息意外出现在终端。

### 检查范围与结果

检查使用真实的 TDX Adapter、Ingestion、质量评估、ObjectStore、Parquet、Resolver、Manifest、
Catalog 和 Reader。只有质量通过、发布成功、重新打开存储后的读取一致，才返回 `status=ok`。
输出为 JSON，包含版本、数据集 ID、质量状态、离线重放结果和标准化后的单条日线数值。

Adapter 固定不复权、禁止自动填充；按
[官方 K 线接口说明](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhthaq5qmg/mindoc-1h10g60jt68sc.html)
将成交额从万元转为元，成交量保留接口的最小数量单位。
这一步验证真实返回值能否通过当前转换及落盘路径，并非与第二数据源独立核对数值，
因此结果明确包含 `independent_market_accuracy_check=false`。
没有源端发布时间证据时，`available_at` 使用本次采集完成时间；历史回填不等于历史当时可用。

默认数据只保存在临时目录，结束后删除，输出中的 ID 不能在删除后独立重放。
需要保留检查数据时，显式指定仓库外的全新目录：

```bash
uv run --locked --extra dev python scripts/data/check_tdx_daily.py \
  --symbol 600000 --date 2026-09-14 --allow-network \
  --output-dir "$HOME/.karkinos/checks/tdx-20260914"
```

已有目录会被拒绝，避免覆盖数据；失败时这个显式目录可能留有部分检查对象，但不会报告成功。
退出码：`0` 表示预检查或真实检查成功，`1` 表示检查失败，`2` 表示参数错误。
`no_data` 或 `tdx_response_empty` 不能直接解释为休市或认证失败，应核对日期、数据权限和凭据。
SDK 的空字典现在明确标记为 `tdx_response_empty`，不再错误提示缺少 `Open`；不会补零或绕过检查。

普通 CI 只使用隔离的 SDK 替身，不运行真实 TDX 调用。执行脚本测试：

```bash
uv run --locked --extra dev python -m pytest tests/scripts/test_check_tdx_daily.py -q
```
