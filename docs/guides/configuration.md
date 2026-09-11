# Karkinos 配置指南

[文档入口](../README.md)

## 本地 Workspace

源码运行默认把 Git checkout 根目录作为 Karkinos 的本地 workspace：

```text
Karkinos/
├── config.json
├── .env
├── data/store/
├── logs/
├── exports/
└── .run/
    ├── source.lock
    ├── main/
    └── dev/
```

`main`、`dev` 和其他源码分支共用同一份：

```text
config.json
.env
data/store/
logs/
exports/
```

`.run/<branch>` 只保存分支相关的 PID / control 等临时运行状态；`.run/source.lock` 防止两个 source backend 同时打开同一份本地数据。

创建本地配置：

```bash
cp config.example.json config.json
cp .env.example .env
uv run python -m server --check-config
```

启动默认 `main`：

```bash
./scripts/start_server.sh
```

启动 `dev`：

```bash
./scripts/start_server.sh dev
```

选择源码分支只改变代码，不切换配置和数据库。

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
| `KARKINOS_WORKSPACE` | 高级覆盖：显式绝对本地 workspace；默认是仓库根目录 |
| `KARKINOS_CONFIG_PATH` | 高级覆盖：`config.json` 的绝对路径 |
| `KARKINOS_DATA_DIR` | 高级覆盖：本地运行数据绝对路径 |
| `KARKINOS_ENV_FILE` | 高级覆盖：环境文件绝对路径 |

普通源码使用不需要设置这些路径变量。

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
uv run python scripts/data/configure_data_source.py
```

`dev` 和 `main` 使用同一份 `config.json` / `.env`，因此不再需要单独配置开发数据源。

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

## Maintenance-only

`account_truth` 及 broker / controlled-execution 配置默认关闭，当前仅维护兼容。

见 [Account Truth import](account-truth-import.md) 和 [PLAN.md](../PLAN.md)。

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

源码分支共享 `data/store`。因此涉及数据库 schema 的开发改动必须：

- 使用明确 migration；
- 保持升级边界可检测；
- 不让旧代码静默误读新 schema；
- 在破坏性变更前提供明确备份 / migration 路径。

持久化兼容规则见 [Engineering](../ENGINEERING.md)。

## 安全

- 不提交 `config.json`、真实 `.env`、API Key、券商凭证或私钥。
- 不在 CLI 参数传递 secret/token。
- 不保存真实账户导出、截图或运行数据库到 Git。
- 切换源码分支前停止当前 source runtime；启动脚本不会自动 reset、stash 或丢弃本地改动。
