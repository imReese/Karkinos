# Karkinos 配置指南

[文档入口](../README.md)

Karkinos 的本地配置来自程序默认值、`config.json`、环境变量和命令行参数。
运行时金融事实、研究结果和资本权限不属于静态配置。

## 快速开始

从仓库根目录创建本地配置：

```bash
cp config.example.json config.json
cp .env.example .env
uv run python -m server --check-config
```

`config.json` 和 `.env` 默认不应提交。完整安全示例见
[`config.example.json`](../../config.example.json) 和
[`.env.example`](../../.env.example)。

## 配置优先级

同一个配置项出现多次时：

```text
命令行参数
> 已有进程环境变量
> .env
> config.json
> 程序默认值
```

常用路径：

| 环境变量 | 用途 |
| --- | --- |
| `KARKINOS_CONFIG_PATH` | `config.json` 路径 |
| `KARKINOS_DATA_DIR` | 本地运行数据目录 |
| `KARKINOS_ENV_FILE` | 显式选择环境文件 |

## `server`

`server` 保存本地 API 的监听、CORS、交易日历同步和通知类型等普通运行参数。

常用字段包括：

```text
host
port
market_calendar_auto_sync
cors_allowed_origins
notification
```

部署到非本机环境时应配置明确的可信 CORS origin，而不是依赖不受控的通配符。

## `data_source`

`data_source` 选择市场数据 provider 和轮询配置。

当前示例支持：

```text
provider = akshare | tushare
live_poll_interval
tushare_token_env
```

TuShare Token 只通过环境变量提供。默认变量为：

```text
KARKINOS_TUSHARE_TOKEN
```

不要把真实 Token 写入 `config.json`。

## `ai`

AI 是可选的研究边界。典型配置包括：

```text
enabled
provider
model
base_url
adapter_kind
timeout_seconds
api_key_env
```

推荐把 API Key 放在：

```text
KARKINOS_AI_API_KEY
```

也可以通过 `ai.api_key_env` 指向另一个环境变量。

AI 配置只决定外部模型连接方式，不授予市场事实、研究结果、组合状态、金融事实或资本权限。

## `broker_fee`

`broker_fee` 描述本地交易成本模型，例如：

```text
佣金率和最低佣金
印花税
过户费
费用舍入规则
按市场 / 资产 / 买卖方向定义的细分规则
```

这些值用于估算和模拟。已导入并确认的真实券商费用属于金融事实，并不因为配置中的估算值而被覆盖。

完整示例以 [`config.example.json`](../../config.example.json) 为准。

## Maintenance-only configuration

`account_truth` 和其他 broker / controlled-execution 相关配置用于维护现有兼容能力，当前默认关闭，也不属于当前开发主线。

现有 Account Truth 本地导入说明见
[account-truth-import.md](account-truth-import.md)。除非
[`PLAN.md`](../PLAN.md) 明确重新纳入范围，否则不要围绕这些配置扩展新的 broker 或资本权限功能。

## 常用环境变量

| 环境变量 | 用途 |
| --- | --- |
| `KARKINOS_HOST` | API 监听地址 |
| `KARKINOS_PORT` | API 监听端口 |
| `KARKINOS_CORS_ALLOWED_ORIGINS` | 浏览器可信 origin，逗号分隔 |
| `KARKINOS_DATA_SOURCE` | 市场数据 provider |
| `KARKINOS_LIVE_POLL_INTERVAL` | 数据轮询间隔 |
| `KARKINOS_TUSHARE_TOKEN` | TuShare Token |
| `KARKINOS_AI_ENABLED` | 是否启用外部 AI |
| `KARKINOS_AI_PROVIDER` | AI provider |
| `KARKINOS_AI_MODEL` | AI model |
| `KARKINOS_AI_BASE_URL` | AI API base URL |
| `KARKINOS_AI_ADAPTER_KIND` | AI adapter 类型 |
| `KARKINOS_AI_TIMEOUT_SECONDS` | AI 请求超时 |
| `KARKINOS_AI_API_KEY` | AI API Key |
| `KARKINOS_TELEGRAM_BOT_TOKEN` | Telegram 通知凭证 |
| `KARKINOS_TELEGRAM_CHAT_ID` | Telegram 目标 |
| `KARKINOS_WECHAT_SENDKEY` | Server酱凭证 |

## 安全

- 不提交 `config.json`、真实 `.env`、API Key、券商凭证或私钥。
- 不在 CLI 参数中传递 secret 或 token。
- 不在配置中保存完整账户号、真实账户导出、截图或运行数据库。
- 配置错误应显式修复，不应通过静默回退产生一个看似正常但语义不同的运行状态。
