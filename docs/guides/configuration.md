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

## `market_data`

```text
source_policy
verification_source_policy
live_poll_interval
provider_config.tushare_token_env
```

两个策略的默认值均为：

```text
karkinos.market.source.free_cn_research.v1
```

`source_policy` 管理自动单源采集及现有行情、基金、交易日历等用途；`verification_source_policy` 只用于明确提交的研究日线核验任务。两者独立配置，因此改变核验来源不必重排实时行情或自动采集来源。策略按用途解析版本化来源候选，不表示首选 Provider 永远可信。默认后台任务按优先级采集一个可用来源的未复权日线，独立保存单源质量结果；质量阻断不会改选来源来掩盖问题，也不会发布 Dataset。

显式双源核验任务仍要求两个独立 upstream，只有匹配后才发布 verified Dataset v2：

```text
BaoStock（BaoStock 上游）
   + 腾讯日线（AKShare SDK，Tencent 上游）
   ↓
Quality + cross-source verification
   ↓
verified Dataset v2
```

`akshare_tencent` 与 `tencent` 的日线适配器均通过 AKShare SDK 调用腾讯接口，同属 Tencent 上游，不能算独立两票；`akshare` 日线使用 Eastmoney 上游。包名、SDK 和数据上游是不同身份。如果其中一个来源在本次请求中因网络、SDK/API 不可用或空响应而无法形成市场事实，核验任务可以按策略尝试下一组独立上游，例如 Tencent + Eastmoney。已经形成有效市场事实后的 Quality BLOCKED 或跨源冲突不会通过换源“洗绿”，而是 fail closed。

BaoStock + Tencent 日线使用已审阅的版本化对账规则：价格严格一致，成交量绝对差不超过 99 股、成交额绝对差不超过 99.99 元，以反映腾讯接口的数据粒度。其它来源组合仍严格比较；这些容差不允许单位映射错误。单源质量通过、双源一致、历史 PIT 可获得性和收益口径是不同结论；v2 的双源证据本身不授权策略晋级或总收益计算。

免费来源优先级后仍可使用可选增强来源：

- `akshare`：Eastmoney upstream，免费 fallback / diagnostic；
- `tushare`：配置 Token 后加入候选；
- `tdx`：配置数据服务凭据后可用于显式支持它的流程。

TuShare Token 使用环境变量：

```text
KARKINOS_TUSHARE_TOKEN
```

Token 写入 `.env`，不写入 `config.json`。

全市场股票池同步会冻结适配器实际返回的当前存续股票列表，同时记录采集
开始、完成和可用时间。股票池的 `trade_date` 只确定行情回补窗口，不能把
今天获取的列表当作该历史日期的股票池。同步结果显示这些时间及历史成员
资格未核验的限制。同一天的新观测保留为独立版本，研究重放读取原快照 ID；
旧快照没有时间证据时，其可用时间保持未知，不从数据库写入时间推测。

回测页选定股票 Dataset 后，可显式采集分红送转记录。该操作使用 TuShare
`dividend` 接口和上述 Token；需要对应的数据访问权限。也可调用
`POST /api/backtest/datasets/{dataset_id}/corporate-actions`，请求体为
`{"refresh": false}`。已有绑定时复用原记录；`refresh: true` 才重新观察来源。
采集成功返回新的 Dataset ID，原数据集和历史报告保留原始绑定。普通列表、
报告读取和重放不会访问 Provider。当前这条流程只支持股票，不把 ETF 当股票查询。

记录分别保留公告、实施公告、股权登记、除权除息、派息和红股上市日期。
今天取得的整行数据不能根据旧公告日期回填为“当时已知”；可用时间按实际
采集完成时间记录。接口返回空记录只表示此次查询未返回分红送转，不能证明
整个区间没有公司行动。详见 [TuShare 分红送股接口](https://tushare.pro/document/2?doc_id=103)。

回测报告显示本区间命中的记录及日期缺口。默认价格口径未计算股息应收、
派息现金、送转股份和相应税费；绑定记录不会自动切换收益口径或获得历史 PIT 准入。
正式 Dataset 与自动研究日线回执的这项限制一致；旧回执报告仍可重放，新的
资格和发布审核按当前口径阻断，探索研究本身仍可运行。

对已绑定分红证据的股票 Dataset，单次回测、参数扫描和策略对比共用所选公司行为口径。
选择税前现金分红核算时，
请求字段为 `corporate_action_mode: "cash_dividends_gross"`；默认
`"price_only"` 保留原有价格收益口径。每个子结果及其保存报告保留相同口径，
应收与到账分别显示，完整语义见
[收益与成本口径](return-accounting.md#研究回测的现金分红)。缺日期、未实施、
记录冲突或含尚不支持的送转时，该模式拒绝运行，可继续选择原价格口径进行探索。

同时核算现金与整股送转时，显式选择
`corporate_action_mode: "reported_distributions_gross"`。送转比例必须完整且一致，
登记、除权和新增股份上市日期必须齐全；按登记持仓算出的任一送股或转增
分项含零碎股时拒绝运行。报告分别展示股数、待上市股数和现金金额。
两种税前核算都不包含投资者税款，也不自动修复未复权策略特征。

单次回测、参数扫描和策略对比共用 `cost_assumptions`。可覆盖股票／ETF 的
`stock_commission_rate`、`etf_commission_rate`（小数费率），以及
`stock_min_commission`、`etf_min_commission`（每笔最低佣金）；未指定项保持
已有模型默认值，显式 `0` 是有效覆盖。`slippage_bps` 按基点计，买入提高、
卖出降低模拟成交价，默认 `0`。印花税、过户费仍由现有资产费用模型计算。
这些是研究假设，不是已核验的券商费率，也不是按历史日期还原的税费表。
每个结果保存实际采用的成本参数、完整成交费用和日线成交量参与率，扫描
及对比的子结果使用同一组成本设置。旧报告未记录的参数保持未知。

日线参与率仅作流动性诊断，固定比例滑点不模拟市场冲击或部分成交。

新配置应分别使用 `market_data.source_policy` 与 `market_data.verification_source_policy`。显式核验任务的响应包含其 `source_policy_id`；已提交任务保留原策略身份。如果排队任务的策略与当前核验策略不同，worker 会在请求 Provider 前拒绝该任务，需按新策略重新提交。旧 Dataset 的 ID 和离线重放语义不变。历史 `data_source.provider` / `KARKINOS_DATA_SOURCE` 仅保留兼容读取，不作为新数据飞轮的配置方式。

### 独立前向观察

在策略实验室的已保存回测报告中展开「独立前向观察」，设置观察跨度、
单标的和总权重上限，再开始观察。双均线来源需要绑定正式 Dataset；
Formula 来源保留原研究快照及冻结公式。观察冻结当前实现，不补认旧报告的
代码版本或历史 PIT 资格，且不需要 AI 配置或真实账户。

每次发布都需主动选择与冻结标的、历史起点一致，并延伸至最新已收盘交易日的
双源核验 Dataset。所用交易日历也需有明确的获取时间与官方复核时间；旧记录
的未知时间需要通过重新获取和复核解决。发布同时测量已有目标的到期结果。
暂停阻止新目标发布，仍允许使用后续数据测量已有目标；刷新或重启保留暂停状态。
实现版本改变后，应保留旧观察并从报告启动新的观察。

结果比较发布之后的两个固定收盘价端点，显示目标权重及价格贡献。它不建立
订单、成交或净值，未计交易成本、分红及送转，不能作为账户收益或交易授权。
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

AI 研究页面的站立授权可同时设置 `research_end_date`（研究截止日）和
`sealed_end_date`（最终检验结束日），也可通过
`PUT /api/ai/strategy-research/shadow-automation/policy` 保存。日期格式为
`YYYY-MM-DD`，只适用于 `normalized_notional`，检验结束日必须晚于研究截止日。
两项留空时保留探索研究，但缺少独立最终检验证据，不能取得新的账户发布资格。
沿用现有区间约束：检验日历天数须占研究与检验总日历天数的 5%～50%。
检验结束日可以是非交易日，但区间必须包含已验证交易日，并收齐至区间内
最后一个交易日的行情。

设置日期不会回溯性地把已经看过的数据变成未见样本。研究批次必须在截止日
当晚北京时间零点前完成并冻结一个优胜候选；次日起停止该批次的模型研究。
截止日之后至检验结束日的数据保留作一次最终检验。区间尚未结束、冻结输入
发生变化或检验证据不通过时，相关资格评估保持阻断。重试读取同一冻结结果，
不会用最终检验结果重新挑选候选。最终检验通过后，账户适用性和人工发布仍需
各自满足现有条件；这里不会自动修改本地授权或启用研究。

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
| `KARKINOS_MARKET_SOURCE_POLICY` | 版本化市场数据来源策略 |
| `KARKINOS_DATA_SOURCE` | 旧 provider 兼容覆盖；新配置不要使用 |
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

## 可选 TDX 持久研究数据与回测

TDX 是可选增强来源；默认 `free_cn_research_v1` 不依赖 TDX 凭据。TDX 研究数据仍保留显式回测准备流程，不需要执行 `check_tdx_daily.py`。
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
