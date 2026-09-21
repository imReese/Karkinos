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

## 恢复旧版股票历史到 typed 存储

[`data/migrate_market_bars.py`](data/migrate_market_bars.py) 只使用已验证的旧版全市场
日线回执，将对应股票历史补入 `market_bars_v2`，不联网。先预检：

```bash
uv run --locked python scripts/data/migrate_market_bars.py --root ~/.karkinos/development/data
```

核对 `planned_bar_rows` 和 `blockers` 后，使用报告里的 `plan_fingerprint` 应用：

```bash
uv run --locked python scripts/data/migrate_market_bars.py \
  --root ~/.karkinos/development/data --apply --expected-plan 'sha256:<plan_fingerprint>'
```

应用前自动在该数据目录的 `backups/` 下保存包含已提交 WAL 页的 SQLite 快照。
源表和原回执保留；已有 typed 行价格冲突则事务回滚，已有来源元数据不覆盖。
缺少类型证据的行会留在旧表并报告为 blocker，因此迁移成功不表示全部历史或最新行情已齐全。

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
