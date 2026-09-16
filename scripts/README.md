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

## TDX 日线手动检查

[`data/check_tdx_daily.py`](data/check_tdx_daily.py) 检查一只股票、一个已经收盘的交易日。
脚本不扫描股票池、不自动重试、不启动服务，也不会写入现有业务数据库。

先安装锁文件中的依赖，再做不联网的预检查：

```bash
uv sync --locked --extra dev
uv run --locked --extra dev python scripts/data/check_tdx_daily.py \
  --symbol 600000 --date 2026-09-14
```

`status=preflight` 只表示参数检查通过且能找到 `tdxaidata` 包；此时没有加载原生动态库、
请求行情或创建数据文件，不能据此判断认证有效或该日期一定开市。

### 认证准备

独立 SDK 的入口是 `from tdxaidata import tqs`。按
[通达信官方说明](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hjbgqpdhv114.html)，
后台模式需要在 SDK 使用的 `TdxAiData.ini` 中配置数据服务 Key。
请遵循当前安装版本的配置说明；脚本不推断配置文件位置、不读取配置内容，也不改写它。

**仅把 Key 放在 Karkinos 的 `.env` 中，目前不会自动传给这个 SDK。**
本检查入口没有 `.env -> TdxAiData.ini` 的桥接，不接受命令行 Key，也不把认证信息放入 Capture。
不要提交 SDK 配置文件或在 Issue 中粘贴 Key。

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
`no_data` 不能直接解释为休市或认证失败，应核对日期、数据权限和 SDK 配置。

普通 CI 只使用隔离的 SDK 替身，不运行真实 TDX 调用。执行脚本测试：

```bash
uv run --locked --extra dev python -m pytest tests/scripts/test_check_tdx_daily.py -q
```
