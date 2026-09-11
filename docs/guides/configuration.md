# Karkinos 配置指南

[文档入口](../README.md)

## 快速开始

```bash
cp config.example.json config.json
cp .env.example .env
uv run python -m server --check-config
```

示例：[`config.example.json`](../../config.example.json) · [`.env.example`](../../.env.example)

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
| `KARKINOS_CONFIG_PATH` | `config.json` 路径 |
| `KARKINOS_DATA_DIR` | 本地运行数据目录 |
| `KARKINOS_ENV_FILE` | 环境文件路径 |

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

TuShare Token：

```text
KARKINOS_TUSHARE_TOKEN
```

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

## 安全

- 不提交 `config.json`、真实 `.env`、API Key、券商凭证或私钥。
- 不在 CLI 参数传递 secret/token。
- 不保存真实账户导出、截图或运行数据库到仓库。
