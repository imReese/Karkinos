# Karkinos 配置指南

[English](config-reference.en.md) | [中文文档](README.zh.md)

Karkinos 的“配置”包括程序默认值、`config.json`、进程环境变量和命令行参数。运行时资本授权、Account Truth、会话预算、风控证据和订单状态属于 SQLite 中的动态事实，不属于静态配置。

`config.json` 和 `.env` 默认都不应提交。前者保存普通本机参数，后者用于向进程提供部署覆盖和密钥。

## 快速开始

```bash
cp config.example.json config.json
# 可选：复制环境变量模板供 Docker Compose 或 python -m server 使用
cp .env.example .env
python -m server --check-config
python -m server
```

直接执行 `python -m server` 时会自动读取项目目录中的 `.env`。已有进程环境变量不会被 `.env` 覆盖。可通过 `--env-file PATH` 或进程变量 `KARKINOS_ENV_FILE` 指定其他文件；显式指定的文件不存在时会阻止启动。

`--check-config` 只完成 `.env`、JSON、环境覆盖和类型校验，然后退出；它不会启动 Web 服务、联系行情/AI/broker，也不会验证 API Key 是否可用。

## 配置来源与优先级

同一个配置项出现多次时，优先级为：

```text
命令行参数 > 已有进程环境变量 > .env > config.json > 程序默认值
```

| 来源 | 适用内容 | 是否提交 |
| --- | --- | --- |
| 程序默认值 | 安全默认、开发默认 | 代码内维护 |
| `config.json` | 本机运行参数、费用模型、脱敏 connector 配置 | 否 |
| 环境变量 / `.env` | 密钥、容器路径、部署覆盖 | 否 |
| CLI | 本次启动的 `--host`、`--port`、`--no-live` | 不保存 |
| SQLite | 账户事实、watchlist、授权、证据、会话和订单状态 | 运行时数据 |

`KARKINOS_CONFIG_PATH` 决定先读取哪个文件；`KARKINOS_DATA_DIR` 决定运行时数据目录。它们不是 `config.json` 内字段。

## config.json 结构

推荐配置只保留四个分组，完整安全示例见仓库根目录的 [`config.example.json`](../config.example.json)。

| 分组 | 用途 |
| --- | --- |
| `server` | Web 服务、CORS、调度器和通知 |
| `data_source` | 行情提供方和轮询间隔；凭证只能来自环境变量 |
| `broker_fee` | 券商费用建模 |
| `ai` | 外部模型连接参数；密钥默认来自环境变量 |

未知顶层字段、未知分组字段、同一字段同时使用新旧格式以及错误的字段类型都会阻止启动。这样可以避免拼写错误或无效值被静默忽略。配置文件只在启动时解析；路由复用同一个类型化配置对象，不会在请求期间重新读取 JSON。

### server

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | string | `0.0.0.0` | API 监听地址；本机开发可使用 `127.0.0.1`。 |
| `port` | integer | `8000` | API 监听端口。 |
| `live_auto_start` | boolean | `true` | 是否随 Web 服务启动内建行情调度器；不会自动授予下单权限。 |
| `cors_allowed_origins` | string[] | 本机前端地址 | 允许访问 API 的浏览器 origin。 |
| `notification` | object | `{"type":"console"}` | 通知器配置。 |

### data_source

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `provider` | string | `akshare` | `akshare` 或 `tushare`。 |
| `live_poll_interval` | integer | `60` | 行情和调度轮询间隔，单位秒。 |

交互式配置脚本会保留分组结构：

```bash
uv run python scripts/configure_data_source.py --provider akshare
uv run python scripts/configure_data_source.py --provider tushare
```

TuShare token 通过隐藏输入读取，不接受命令行参数。脚本只把 provider 和轮询参数写入已被 Git 忽略的 `config.json`，把 Token 写入权限为 `0600` 的 `.env`（或 `--env-file` / `KARKINOS_ENV_FILE` 指定文件）。Settings API 和 Web 页面不接收凭证，只展示是否已配置。`config.json` 中出现顶层或分组内 `tushare_token` 会阻止启动，配置脚本也会直接拒绝，不做自动凭证迁移。

### broker_fee

`broker_fee` 是本地费用估算输入，券商账单和 Account Truth 始终是最终事实来源。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `account_profile_id` | string | 脱敏账户 profile id，不能写完整资金账号。 |
| `broker_name` | string | 券商展示名称。 |
| `schedule_id` | string | 费用规则标识。 |
| `display_name` | string | 仅用于本地可读说明。 |
| `currency` | string | 费用模型币种说明，示例为 `CNY`。 |
| `source_type` | string | 费用输入的脱敏来源类型。 |
| `precedence` | string | 声明券商账单优先于配置估算。 |
| `stock_a_commission_rate` | number/string | A 股佣金率。 |
| `stock_a_min_commission` | number/string | A 股最低佣金。 |
| `fund_etf_commission_rate` | number/string | ETF/场内基金佣金率。 |
| `fund_etf_min_commission` | number/string | ETF/场内基金最低佣金。 |
| `stamp_tax_rate` | number/string | 股票卖出印花税率。 |
| `transfer_fee_rate` | number/string | 默认过户费率。 |
| `exchange_transfer_fee_rates` | object | 按交易所覆盖过户费率。 |
| `other_fee_rate` | number/string | 其他费用率。 |
| `rules` | array | 按资产、市场、方向和费用组件定义的细分规则。 |
| `limitations` | string[] | 当前费用模型的已知假设和待复核项。 |

`account_identifier_saved`、`screenshots_saved` 和 `private_exports_saved` 必须保持 `false`。完整账号、截图、交割单或真实导出不得写入配置。

解析器还接受 `profile_id`、`schema_version`、`source`、`effective_from`、`captured_at`、`rounding`、`rule_application`、`broker_absorbed_components`、`commission` 和 `taxes_and_fees` 作为结构化导入/归一化输入。它们不会成为独立账户事实；运行时只保留归一化后的费用条款、schedule/profile 标识和限制。

旧字段 `broker_fee_schedule`、`account_commission_rate` 和 `account_min_commission` 仅用于迁移读取；新写入统一使用 `broker_fee`。

### ai

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | 是否允许人工显式调用已配置的外部模型边界。 |
| `provider` | string | 空 | Provider id，例如 `deepseek` 或内部兼容服务标识。 |
| `model` | string | 空 | Provider 使用的模型名称。 |
| `base_url` | string | 空 | 无凭证的 HTTPS API 根地址。 |
| `adapter_kind` | string | `openai_compatible_https` | 当前已审核的 adapter 类型。 |
| `timeout_seconds` | number | `20` | 单次请求超时，必须在 0 到 60 秒之间。 |
| `api_key_env` | string | `KARKINOS_AI_API_KEY` | 保存密钥的环境变量名，不是密钥本身。 |

启用 `ai.enabled` 时必须显式设置 `provider`、`model` 和无凭证 HTTPS `base_url`。核心不会为 DeepSeek 或其他厂商猜测 endpoint。

`ai.api_keys` 不再接受；API Key 只能来自环境变量。继续在 JSON 中配置该字段会阻止启动。

`allow_financial_context` 已移除；继续配置它会带迁移提示并阻止启动。删除该字段即可。是否允许发送某一类证据由具体的人工确认、不可变证据范围和对应 API 契约决定，不能由一个全局布尔值放宽。

AI 凭证解析顺序为：

1. `KARKINOS_AI_API_KEY`；
2. `ai.api_key_env` 指向的环境变量；
3. 根据 provider 推导的 `<PROVIDER>_API_KEY`；

## 环境变量

### 运行时与数据

| 环境变量 | 覆盖字段 / 用途 |
| --- | --- |
| `KARKINOS_CONFIG_PATH` | `config.json` 路径，默认 `./config.json` |
| `KARKINOS_DATA_DIR` | 数据目录，默认 `./data/store` |
| `KARKINOS_ENV_FILE` | `python -m server` 使用的环境文件路径；也可用 `--env-file` |
| `KARKINOS_HOST` | `server.host` |
| `KARKINOS_PORT` | `server.port` |
| `KARKINOS_LIVE_AUTO_START` | `server.live_auto_start` |
| `KARKINOS_CORS_ALLOWED_ORIGINS` | `server.cors_allowed_origins`，逗号分隔 |
| `KARKINOS_DATA_SOURCE` | `data_source.provider` |
| `KARKINOS_LIVE_POLL_INTERVAL` | `data_source.live_poll_interval` |
| `TUSHARE_TOKEN` | TuShare 边缘适配器凭证；不会进入 `config.json` 或 Settings API |

运行时与 AI 覆盖由同一个启动加载器处理。布尔值接受 `true/false`、`1/0`、`yes/no` 和 `on/off`；拼写错误会阻止启动。Port、轮询间隔、AI timeout、HTTPS base URL 和 CORS 空列表同样会被校验。

### AI

| 环境变量 | 用途 |
| --- | --- |
| `KARKINOS_AI_ENABLED` | 覆盖 `ai.enabled` |
| `KARKINOS_AI_PROVIDER` | 覆盖 `ai.provider` |
| `KARKINOS_AI_MODEL` | 覆盖 `ai.model` |
| `KARKINOS_AI_BASE_URL` | 覆盖 `ai.base_url` |
| `KARKINOS_AI_ADAPTER_KIND` | 覆盖 `ai.adapter_kind` |
| `KARKINOS_AI_TIMEOUT_SECONDS` | 覆盖 `ai.timeout_seconds` |
| `KARKINOS_AI_API_KEY` | 推荐的 AI API Key 来源 |

## 高级与兼容配置

运行时仍接受以下高级顶层字段，但最小示例不会默认打开它们：

- `broker_connectors`：只读券商事实 connector；不得包含 password、secret、token 或 credential 字段。
- `controlled_bridge_policy`：受控桥接复核白名单；`per_order_confirmation_required` 必须为 `true`，`automation_allowed` 必须为 `false`。
- `trusted_operator_identities`：Ed25519 公钥白名单；只存公钥。
- 回测兼容字段：`initial_cash`、`start_date`、`end_date`、`assets`、`instruments`、`strategy`、`short_period`、`long_period` 和 `commission_rate`。

`assets` 和 `instruments` 只用于旧配置迁移或独立回测。实时 watchlist 与资产元数据应保存在 SQLite。

## 不属于静态配置的内容

以下内容不能通过 `config.json` 或环境变量授予：

- 券商提交、撤单或自动执行权限；
- 资本授权、会话预算或运行时 token；
- Account Truth、持仓、成交、对账和风控证据；
- AI 产物成为账户事实、Decision 输入或交易指令的资格。

这些边界由运行时数据库、人工确认和受控执行契约管理。详见 [`CONTROLLED_EXECUTION_PLAN.md`](CONTROLLED_EXECUTION_PLAN.md)。

## 安全规则

- 不提交 `config.json`、`.env`、API Key、券商凭证或私钥。
- 不在 CLI 参数中传递 token；命令历史可能泄露。
- 不在配置中保存完整账户号、截图、交割单、真实账户导出或运行数据库。
- 线上部署显式设置 CORS origin，不使用不受控的通配符。
- 配置错误应修复后再启动，不要通过捕获异常回退到默认值。
