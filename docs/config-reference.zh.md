# config.json 配置字段参考

`config.json` 是本机运行配置，默认已被 Git 忽略。它不应该保存完整资金账号、券商密码、券商登录凭证、截图、交割单、真实账户导出或运行时数据库。

JSON 标准不支持注释，因此不要在 `config.json` 里写 `//` 或 `/* ... */`。字段说明放在本文档，安全示例放在项目根目录的 `config.example.json`。

## 顶层字段

| 字段 | 类型 | 是否建议手工改 | 说明 |
| --- | --- | --- | --- |
| `host` | string | 可改 | 后端服务监听地址。本机开发通常使用 `127.0.0.1`。 |
| `port` | number | 可改 | 后端服务监听端口，默认 `8000`。 |
| `live_auto_start` | boolean | 可改 | Web 服务启动时是否自动启动内建调度器。不会自动下单。 |
| `data_source` | string | 可改 | 行情数据源，例如 `akshare` 或 `tushare`。 |
| `tushare_token` | string | 建议用引导脚本 | TuShare token。推荐用 `uv run python scripts/configure_data_source.py` 写入，避免命令行和日志泄露。 |
| `broker_fee_schedule` | object | 可改 | 本机券商费用规则。只放费用建模参数和脱敏账户别名，不放完整账户号。 |
| `broker_connectors` | array | 谨慎 | 只读券商事实 connector 配置。不得保存密码、token、secret 或 credential。 |
| `notification` | object | 可改 | 通知配置，例如 `{"type": "console"}`。 |
| `live_poll_interval` | number | 可改 | 行情/调度轮询间隔，单位秒。 |
| `cors_allowed_origins` | array | 部署时可改 | 允许访问 API 的前端 origin。 |

不再建议使用顶层 `account_commission_rate` 和 `account_min_commission`。它们只作为老配置迁移输入读取；正式费用配置应写在 `broker_fee_schedule` 内。

## broker_fee_schedule

`broker_fee_schedule` 是账户费用规则的唯一正式配置入口。Karkinos 会用它估算手工交易的佣金、印花税、过户费、其他费用、总费用和净现金影响；券商交割单仍是最终权威来源。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | string | 配置结构版本，例如 `karkinos.broker_fee_schedule.v1`。 |
| `account_profile_id` | string | 机器读取的稳定配置档案 ID，例如 `primary-broker-account`。不要写完整资金账号。 |
| `broker_name` | string | 券商名称，例如 `中信证券` 或 `示例券商`。 |
| `schedule_id` | string | 费用规则 ID，用于账本审计引用。 |
| `display_name` | string | UI 可读名称，推荐使用脱敏账户别名，例如 `中信证券88**16账户费用规则`。 |
| `currency` | string | 币种，当前通常为 `CNY`。 |
| `source_type` | string | 规则来源，例如 `broker_app_commission_query`、`broker_statement` 或 `manual_profile`。 |
| `account_identifier_saved` | boolean | 是否保存完整账户标识。应保持 `false`；如果为 `true`，配置会被拒绝。 |
| `screenshots_saved` | boolean | 是否保存截图。应保持 `false`；如果为 `true`，配置会被拒绝。 |
| `private_exports_saved` | boolean | 是否保存私有导出文件。应保持 `false`；如果为 `true`，配置会被拒绝。 |
| `precedence` | string | 口径优先级。推荐 `broker_statement_overrides_config`，表示交割单优先于本地估算。 |
| `stock_a_commission_rate` | number/string | A 股佣金率，例如万 1.5 写作 `0.00015`。 |
| `stock_a_min_commission` | number/string | A 股最低佣金，例如 `5.0`。 |
| `fund_etf_commission_rate` | number/string | ETF/场内基金佣金率。 |
| `fund_etf_min_commission` | number/string | ETF/场内基金最低佣金。 |
| `stamp_tax_rate` | number/string | 股票卖出印花税率。 |
| `transfer_fee_rate` | number/string | 默认过户费率。 |
| `exchange_transfer_fee_rates` | object | 按交易所覆盖过户费率，例如 `{"shanghai": 0.00001, "shenzhen": 0.0}`。 |
| `other_fee_rate` | number/string | 其他费用率；未知或无则用 `0.0`。 |
| `rules` | array | 更细的费用规则表，可按资产类别、市场、方向、费用组件建模。解析器会从规则表派生运行时所需的佣金/税费摘要。 |
| `broker_absorbed_components` | array | 由券商吸收、不进入用户总费用的费用组件说明。 |
| `limitations` | array | 已知限制，例如监管费用是否假设由券商吸收、未知规则是否需要人工复核。 |

### rules[] 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 单条规则 ID。 |
| `component` | string | 费用组件，例如 `commission`、`stamp_tax`、`transfer_fee`。 |
| `asset_classes` | array | 适用资产类别，例如 `stock`、`fund`、`etf`、`bond`。 |
| `instrument_types` | array | 适用标的类型，例如 `a_share`、`etf`、`convertible_bond`。 |
| `markets` | array | 适用市场，例如 `SSE`、`SZSE`、`BSE`。 |
| `side` | string | 适用方向：`buy`、`sell` 或 `both`。 |
| `rate` | string/null | 费率。建议用字符串保留精度，例如 `"0.00015"`。 |
| `rate_base` | string | 计费基准，例如 `gross_amount`。 |
| `min_fee` | string/null | 最低费用；没有最低费用时用 `null`。 |
| `payer` | string | 支付方，例如 `account`、`seller` 或 `broker`。 |
| `included_in_total_fee` | boolean | 是否计入用户总费用。券商吸收项应为 `false`。 |
| `status` | string | 可选。未知规则可写 `unknown`。 |
| `required_action` | string | 可选。未知规则需要人工确认时填写。 |

## broker_connectors

`broker_connectors` 只用于只读券商事实同步的本地配置，不允许保存任何登录凭证。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `connector_id` | string | connector 本地 ID，例如 `local-qmt-readonly`。 |
| `connector_type` | string | connector 类型，例如 `qmt_readonly`。 |
| `enabled` | boolean | 是否启用。默认建议 `false`。 |
| `client_path` | string | 本机券商客户端路径。不得包含密码或 token。 |
| `account_alias` | string | 脱敏账户别名，例如 `中信证券88**16`。不要写完整资金账号。 |

## 不应写入 config.json 的内容

- 完整资金账号、客户号、券商登录号。
- 券商密码、token、secret、credential。
- 交割单、截图、真实账户导出。
- 运行时数据库、行情缓存、日志。
- 真实持仓样例、真实关注列表或资产元数据。

这些内容应分别进入 SQLite 运行库、受忽略的本地文件、手工导入流程或完全不保存。
