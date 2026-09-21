# Karkinos 配置指南

[文档入口](../README.md)

## 本地 Workspace

`./scripts/start_server.sh dev` 运行当前 checkout，使用独立的开发 workspace：

```text
~/.karkinos/development/
├── config/
│   ├── config.json
│   └── .env
├── data/
└── logs/
```

在 `dev` checkout 上启动开发环境；首次使用时创建空开发配置：

```bash
git switch dev
./scripts/start_server.sh dev
```

可用 `KARKINOS_DEV_HOME` 指定另一份隔离的开发 workspace。分支选择、刷新与
单 runtime 约束见 [scripts/README.md](../../scripts/README.md)。

已安装的 macOS runtime 继续使用 `~/Library/Application Support/Karkinos`，由不可变 release 中的 `karkinosctl` 管理。开发与安装环境不共用账户数据库、迁移状态、配置或日志；此布局不会自动搬迁已有数据。

## 配置优先级

```text
命令行参数
> 已有进程环境变量
> .env
> config.json
> 程序默认值
```

| 环境变量 | 用途 |
| --- | --- |
| `KARKINOS_DEV_HOME` | `./scripts/start_server.sh dev` 使用的独立开发 workspace |
| `KARKINOS_WORKSPACE` | 手动运行服务时的显式绝对 workspace |
| `KARKINOS_CONFIG_PATH` | 高级覆盖：`config.json` 的绝对路径 |
| `KARKINOS_DATA_DIR` | 高级覆盖：本地运行数据绝对路径 |
| `KARKINOS_ENV_FILE` | 高级覆盖：环境文件绝对路径 |

`./scripts/start_server.sh dev` 通过内部 runner 清除继承的 `KARKINOS_*` 设置，再根据开发 workspace 固定配置、数据、报告和环境文件路径。开发专用设置与凭据放在自己的 `config/.env`，避免继承安装环境的路径或权限开关。手动执行 `python -m server` 或集成脚本时，应明确选择所需的配置和状态路径。

## `server`

```text
host
port
market_calendar_auto_sync
cors_allowed_origins
notification
```

非本机部署使用明确可信的 CORS origins。

## `data_source`

```text
provider = akshare | tushare
live_poll_interval
tushare_token_env
```

默认数据源是 AKShare，无需 Token。当前本地 workspace 可以交互配置：

```bash
uv run python scripts/data/configure_data_source.py \
  --config-path ~/.karkinos/development/config/config.json \
  --env-file ~/.karkinos/development/config/.env
```

使用自定义 `KARKINOS_DEV_HOME` 时，相应调整这两个配置路径。

TuShare Token 使用环境变量：

```text
KARKINOS_TUSHARE_TOKEN
```

Token 写入 `.env`，不写入 `config.json`。

## `ai`

```text
enabled
provider
model
base_url
adapter_kind
timeout_seconds
api_key_env
```

默认 API Key 环境变量：

```text
KARKINOS_AI_API_KEY
```

AI 配置不授予金融事实、Portfolio、Risk、Accounting 或资本权限。

开发 workspace 启用 `ai.enabled` 后，启动器会同时管理独立的 research worker。研究任务仍按已授权的 policy 和模型调用时段执行；停止开发服务时会一并停止该 worker。已安装的 macOS runtime 继续由独立的 LaunchAgent 管理研究进程。

## `broker_fee`

用于预期和模拟交易成本：

```text
佣金率 / 最低佣金
印花税
过户费
舍入规则
按市场 / 资产 / 买卖方向的细分规则
```

已确认的真实券商费用由 Accounting 记录，不被估算配置覆盖。

## 冻结的兼容配置

历史 account / broker / controlled-execution 配置可能仍存在于代码中，用于兼容已有数据和安全修复，但它们不是当前产品配置面，也不作为新功能继续扩展。当前范围以 [PLAN.md](../PLAN.md) 为准。

## 常用环境变量

| 环境变量 | 用途 |
| --- | --- |
| `KARKINOS_HOST` | API 监听地址 |
| `KARKINOS_PORT` | API 监听端口 |
| `KARKINOS_CORS_ALLOWED_ORIGINS` | 浏览器可信 origin |
| `KARKINOS_DATA_SOURCE` | 市场数据 provider |
| `KARKINOS_LIVE_POLL_INTERVAL` | 数据轮询间隔 |
| `KARKINOS_TUSHARE_TOKEN` | TuShare Token |
| `KARKINOS_AI_ENABLED` | 外部 AI 开关 |
| `KARKINOS_AI_PROVIDER` | AI provider |
| `KARKINOS_AI_MODEL` | AI model |
| `KARKINOS_AI_BASE_URL` | AI API base URL |
| `KARKINOS_AI_ADAPTER_KIND` | AI adapter |
| `KARKINOS_AI_TIMEOUT_SECONDS` | AI 请求超时 |
| `KARKINOS_AI_API_KEY` | AI API Key |
| `KARKINOS_TELEGRAM_BOT_TOKEN` | Telegram token |
| `KARKINOS_TELEGRAM_CHAT_ID` | Telegram 目标 |
| `KARKINOS_WECHAT_SENDKEY` | Server酱凭证 |

## 分支与持久化数据

开发与安装环境的状态相互隔离。任何涉及已有数据库 schema 的改动仍必须：

- 使用明确 migration；
- 保持升级边界可检测；
- 不让旧代码静默误读新 schema；
- 在破坏性变更前提供明确备份 / migration 路径。

持久化兼容规则见 [Engineering](../ENGINEERING.md)。

## 安全

- 不提交 `config.json`、真实 `.env`、API Key、券商凭证或私钥。
- 不在 CLI 参数传递 secret/token。
- 不保存真实账户导出、截图或运行数据库到 Git。
- 开发环境运行当前 working tree；安装环境运行不可变 release。
- 同一开发 workspace 同时只运行一个实例；并行开发使用独立状态目录。

## TDX 持久研究数据与回测

TDX 研究数据已经接入回测页面，不需要执行 `check_tdx_daily.py`。
在**当前 Server 启动时读取的** `.env` 中配置 `KARKINOS_TDX_DATA_SERVICE_KEY`，
必要时设置 `KARKINOS_TDX_USER`，再重启服务。不要把 Key 写进 JSON、命令行或 Git。
使用 `start_server.sh dev` 时，这是开发 workspace 的 `config/.env`，不是 checkout 根目录的 `.env`。

继续使用仓库根目录 `.env` 的手动启动方式如下；第二条是正常应用服务，不是测试程序：

```bash
npm --prefix web run build
uv run --locked --extra server --extra dev python -m server --env-file .env
```

首次构建前按 Web 开发说明安装锁定依赖。已有服务需先正常停止，避免端口冲突或同时运行。
启动本身不触发 TDX 历史行情采集，也不会自动刷新已发布 Dataset。

在回测页面输入一只股票或 ETF 和日期区间，展开 **TDX 研究数据 · 持久保存与离线回测**：

1. 点击 **从 TDX 准备并保存**。这是明确的联网动作，可能消耗积分；最多准备两年的数据。
   缺失年份的日历会复用已有的交易日历自动核验流程，核验未通过则停止，不用工作日猜测休市。
2. 成功后自动选择已发布的数据集，再点击原有的运行回测按钮。
   回测显式绑定 Dataset ID，只读取该数据集；损坏、缺失或标的/日期不匹配会失败，不偷偷换源。
3. 重启后仍可从下拉框选择已发布数据。重复准备默认复用完整区间或成功交易日的检查点；
   中途失败只保留已完成的交易日，下次显式准备时补采缺口。
4. 只有勾选重新获取历史数据才请求修订版并发布新 Dataset，旧数据集和旧回测记录保持不变。

数据保存在当前 `app.db` 同目录下的 `research/`，页面会显示绝对路径：

```text
<当前应用数据目录>/
├── app.db
└── research/
    ├── objects/                      # 原始采集、不可变行情与 Dataset 清单
    ├── catalog/datasets.sqlite3      # 正式发布的数据集索引
    ├── checkpoints/catalog/datasets.sqlite3  # 已完成交易日，供失败恢复
    └── serving/market.sqlite3        # 可重建的行情查询投影
```

这些是持久数据，不会像 smoke 临时目录一样自动删除，也不会迁移或覆盖旧行情库。
Key 的专用 INI 仍只存在于父进程管理的私有临时 SDK 目录，不进入研究数据目录。
一次准备在当前服务进程内串行，15 分钟超时后终止 SDK 子进程；不是分布式任务调度器。

绑定信息保存在回测配置、结果详情和导出的报告中。第一版接入**单次回测**；选择 Dataset 时
参数扫描/策略比较不显示，防止这些尚未接入的流程静默使用旧数据源。其他旧业务入口保留原行为。

TDX 原始日线不复权。没有历史发布时间证据的回填数据只保证固定快照可重放，不证明历史逐时点
可用性；公司行动现金流与总收益尚未在这条输入路径建模。结果明确带这些限制，不能据此自动升级策略。
