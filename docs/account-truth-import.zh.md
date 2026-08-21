# Account Truth 导入预览

[English](account-truth-import.en.md) | [中文文档](README.zh.md)

Account Truth 用于把本地券商交割单、资金流水或持仓快照先转换成可审计的
broker evidence，再由后续对账流程决定是否需要人工处理。当前实现提供
canonical broker statement CSV 的只读导入预览，以及 staged broker evidence
本地持久化；它不会写入生产 ledger，不会修改持仓，不会提交券商订单，也不会
保存券商登录信息。

## 隐私边界

- 不要提交真实券商导出、账户截图、交易流水、资金流水或运行时数据库。
- 文档和测试只能使用合成数据。真实 CSV 应只保留在本机运行环境。
- 导入预览会计算文件级 SHA-256 指纹和行级 SHA-256 指纹，用于审计和去重。
- 预览和 staged broker evidence 是审计材料，不是投资建议，也不是自动交易授权。

## 中信历史成交 XLS 预览

中信证券客户端导出的 legacy `.xls` `历史成交` 可以先在本机执行隐私最小化预览：

- 在账户事实页面展开**暂存新的券商证据**，在**按月检查中信历史成交**中一次选择最多
  24 个文件，再点击**预览所选中信 XLS 文件**。浏览器按选择顺序逐份读取和请求；任一时刻
  只处理一个文件，完成或失败后立即清除该次 base64 请求状态，并继续下一份。选择器中的
  本地文件名只在当前浏览器界面显示，不会发送给 API。
- 批量汇总按返回的 SHA-256 文件指纹去重，重复文件保留可见但不重复累计行数和事件数；
  单份读取或请求失败不会把其他文件伪装成成功。所有成功预览仍保持 `blocked`。本地 API
  响应只包含计数、校验问题和文件指纹，不包含事件、账户、证券、金额、文件名或路径明细；
  这个预览动作本身不做任何持久化。
- 预览完成后，可以针对一份非重复文件打开二次确认，将其记录为**待补证来源**，或明确拒绝。
  确认时服务端重新读取同一个浏览器 `File` 并核对完整 SHA-256；请求结束后立即清除 base64。
  页面只在记录、拒绝或清除该批次前保留原始 `File` 引用。本地文件名仍不会发送给 API。
- 待补证来源只持久化文件指纹、校验计数、错误代码、缺失证据清单和人工处置；不会保存解析
  事件、账户、证券、金额、文件名或路径，也不会写入 `broker_evidence_events`。结构不可用的
  文件不能标为待补证，只能拒绝；拒绝是终态，内容变化后必须按新指纹重新预览。
- 等价的命令行入口是：

```bash
uv run python scripts/preview_citic_history_xls.py \
  --path /absolute/private/directory
```

这个命令接受单个 `.xls` 或只扫描指定目录的直接子文件。标准输出只包含文件名哈希、
文件指纹、行数、状态、错误代码和限制；不会输出证券名称、证券代码、成交时间、数量、
金额、备注、账户标识或绝对路径，也不会写数据库、账本、持仓、OMS、风控、kill switch
或资本授权。

当前已审查的资金事件映射只包括 A 股 `证券买入`、`证券卖出` 和 `股息入账`。精确匹配
`799999 / 指定交易 / 指定 / 上海A股 / 数量与金额全零` 且日期、申请编号、委托编号均
有效的 `指定交易` 行，只会计为待人工复核的非资金活动，不生成券商事件；任一字段漂移
仍按无效行 fail closed。其他未知业务、市场、代码、金额关系、现金方向、日期或订单身份
同样都会 fail closed。导出中的股东代码、资金账号、客户代码和股东姓名只参与 provider schema
完整性检查，绝不会进入标准事件、错误、备注、事件身份或行指纹。

`历史成交` 给出了成交总额和带符号的清算金额，但没有逐项佣金、印花税和过户费，也
没有现金余额或持仓快照。解析器会把可确认字段投影成 canonical event 供本地预览，
但始终返回 `blocked`，不会暂存这些事件。待补证来源也不属于 authoritative Account
Truth，不能参与对账、分数、风控或执行门禁。不得用清算金额与成交金额的差额猜测费用
分项。完成 Account Truth 仍需分别导出并审查交割单或资金流水，以及当前资金和持仓快照。

每份预览还会返回
`karkinos.account_truth.citic_broker_soak_candidate.v1`，用确定性、fail-closed 的方式评估
v1.8 只读连接器边界。仅有“历史成交”永远不是版本化连接器快照，不能启动或计入 20 个交易日
券商 soak。评估会列出缺失的来源契约：已复核账户别名绑定、券商来源采集时间、连接器与部署
健康身份、当前资金/持仓/订单快照，以及逐项成交费用和税；adapter release、券商交易日历与
无未解决项的执行对账仍是独立运营前置条件。该评估不注册连接器、不记录 soak 证据、不联系
券商，也不授予执行或资本权限。

### 已配置本地目录扫描

为了避免反复选择相同的月度文件，可以在被 Git 忽略的本机 `config.json` 中显式启用一个
私有绝对目录：

```json
{
  "account_truth": {
    "citic_history_xls_directory": {
      "enabled": true,
      "path": "/absolute/private/account-exports",
      "max_files": 120,
      "max_file_bytes": 10485760,
      "max_total_bytes": 67108864
    }
  }
}
```

该配置不会启动 watcher。Account Truth 页面先读取脱敏配置状态，只有操作员点击
**扫描已配置目录** 后才扫描。命令只检查目录直属 `.xls` 文件，拒绝符号链接、读取中变化
的文件和超限输入，按完整内容指纹去重，并且不返回路径、文件名、事件、账户、证券或金额
明细。扫描本身不做持久化。

脱敏扫描响应还会返回
`karkinos.account_truth.citic_history_xls_batch_assessment.v1`：检测文件内重复、跨文件重复
事件、事件身份冲突、无效事件时间和没有已识别资金事件的来源，并且只报告聚合计数、观察到
事件的月份、阻断项和确定性指纹。`integrity_status: clear` 只表示本次检查的文件集合没有发现
结构或事件身份冲突；观察到的月份绝不证明每份导出的查询区间或整月覆盖完整。仍需人工复核
每份查询区间，并补充逐项结算或资金流水、当前资金与持仓快照及账户绑定。因此该评估始终保持
`status: blocked`，不持久化事件，也不能进入 Account Truth 或对账。

显式目录扫描还会返回
`karkinos.account_truth.citic_history_canonical_lineage_assessment.v1`。这一只读运行时投影只会
比较 XLS 批次可证明的金融语义与当前选中的 canonical import，并返回语义匹配、来源/canonical
未匹配事件、保留下来的券商委托身份和精确事件身份等脱敏计数；它不返回事件、账户、来源名称或
路径明细，也不持久化比对结果。财务语义匹配但事件与券商委托身份未保持一致，只是部分线索，
不构成 canonical 来源证明。即使事件来源链精确一致，也不能证明查询区间完整、逐项结算、当前
快照或整账户覆盖，因此该评估不能把 XLS 批次提升为 Account Truth 或对账证据。

记录待补证或拒绝仍需要第二次单独确认。服务端会重新扫描配置目录，并且必须找到预览时
同一 SHA-256；文件缺失或内容变化会 fail closed。最终仍只保存同样的脱敏来源复核元数据。
目录未启用或不可用时，浏览器文件选择继续作为 fallback。

### 单份来源的显式查询区间复核

每份已持久化的 `follow_up_required` 来源仍缺少已证明的券商查询区间。owner 需要按券商查询
界面实际显示的起止日期手工填写，并显式确认这两个日期适用于当前这份精确导出；系统绝不会
根据观察到的事件月份反推查询区间。服务端同时绑定当前文件 fingerprint 与脱敏来源预览
fingerprint，拒绝未来日期、超过 31 个自然日（含首尾）的区间，以及任何落在声明区间之外的
已识别资金事件。没有已识别资金事件的来源也可以复核其查询区间，但它仍是非 canonical 的
不完整来源。

该复核为 append-only 且幂等。若要修改已生效区间，必须先显式撤销；撤销会绑定当前 review id
与 fingerprint，因此过期页面状态会 fail closed。记录只包含来源/复核 fingerprint、intake id、
日期、决定、复核人和审计时间，不包含来源名称或路径、账户、交易、证券、金额或解析事件。列表
读取只会严格只读地打开现有 SQLite；缺失 schema 表示没有复核，部分、不兼容或损坏状态会在
不修复的前提下 fail closed。

显式目录扫描还会把当前仍生效、且与扫描来源 fingerprint 精确一致的复核投影成
`karkinos.account_truth.citic_query_window_batch_assessment.v1`。该纯只读评估只检查声明日期的
自然日并集、缺口和重叠；复核身份参与确定性 assessment fingerprint，但响应不返回 intake id、
review fingerprint、来源名称或路径。`integrity_status: clear` 只表示当前全部来源都已复核，且
这些 owner 声明的日期连续、无重叠；它仍固定保持 `status: blocked`，不能证明更早或更晚日期、
完整账户或资产范围、逐项结算、当前资金或持仓，也不能获得 Account Truth、对账、执行或资本权限。

全部完成后，只会清除查询区间阻断；在每个当前来源都完成精确的来源范围复核前，Operations 中
的来源级待补证仍保持 blocked。查询区间复核不证明完整时段覆盖、不绑定账户、不把事件提升为
Account Truth，也不满足结算、当前快照或对账门禁，不联系券商、不开放提交、不改变资本权限。
撤销后查询区间阻断会立即重新打开。

### 单份来源的显式来源范围复核

每个当前有效的查询区间复核还必须由 owner 单独声明：本地账户别名、账户类型、市场范围、资产
类别、账户规模区间代码和业务类型。owner 还需要明确证明：这一精确导出没有使用其他券商查询
筛选条件、文件包含该精确查询返回的全部记录，并且所声明的账户与范围确实适用于该文件。所有
代码列表与规模区间代码都必须非空。原始券商账户标识只在浏览器内计算带 domain separation 的
SHA-256；原值不会发送给 API，也不会持久化，服务端只接收账户绑定哈希。账户规模区间仅是脱敏
查询范围元数据，不是当前余额、订单额度或资本授权，绝不能用于扩大任何授权。

该 append-only 复核同时绑定当前 intake id、文件 fingerprint、来源预览 fingerprint，以及当前
有效查询区间复核的 id 与 fingerprint。来源或查询绑定过期、已拒绝或发生变化都会 fail closed；
相同动作幂等，存在冲突的有效声明必须先显式撤销。读取路径保持 zero-write：schema 缺失表示尚无
复核，部分、不兼容或损坏状态会在不修复的前提下 fail closed。界面撤销查询区间时，会先撤销依赖
它的有效来源范围复核，保持依赖顺序。

目录扫描只把与当前来源精确匹配的有效声明投影成
`karkinos.account_truth.citic_source_scope_batch_assessment.v2`。只有全部当前来源都已复核、账户引用
哈希完全一致、包括账户规模区间在内的各类声明范围完全一致，并且“无额外筛选”和“完整返回
结果”证明都存在时，批次 `integrity_status` 才能为 `clear`。响应只显示安全的声明代码与确定性
assessment fingerprint，不暴露账户引用哈希、intake/review 身份、来源名称、路径、事件或交易
明细。旧 v1 记录保持只读兼容，但在显式撤销并追加含规模区间的 v2 复核前仍视为不完整。即使
声明为 clear，
legacy 历史成交 XLS 仍固定保持 `status: blocked`：它不能证明完整账户覆盖、逐项结算、当前资金/
持仓、对账、执行权限或资本权限。

只有查询区间与来源范围两个批次都精确且一致时，Operations 来源待补证才可推进到“补充 canonical
Account Truth 证据或显式拒绝该 legacy 来源”。它仍不能提升事件、联系券商、提交/撤销订单或扩展
资本授权。

目录扫描只会从文件名中提取唯一、格式严格的 `YYYYMM` 作为运行时脱敏月份提示，完整文件名和
路径仍不会返回。该提示只帮助 owner 区分同批来源，不进入 scan/review fingerprint、不持久化、
不自动填写日期，也不是查询区间证据。若文件名没有唯一月份标记，目录模式会禁止记录或拒绝该
来源；owner 必须改用浏览器选择精确文件后再复核，不能根据目录顺序猜测。

已复核来源的列表是严格只读路径。构造 intake repository 或调用 GET/list 投影不会创建数据库、
目录、表或索引。intake schema 不存在表示尚无来源复核记录；schema 只存在一部分或不兼容时会
fail closed，读取路径不会静默修复。

canonical broker evidence 和 reconciliation review decision 采用相同边界：构造 repository
以及所有 GET/list 只会以只读方式打开已有 SQLite；相关表完全不存在表示尚无证据，schema
部分存在、不兼容或持久化记录损坏时会 fail closed。只有显式 broker import 或人工 review
命令可以创建或迁移这些表。

持久化的 `follow_up_required` 复核还会通过
`karkinos.account_truth.citic_source_follow_up.v1` 出现在 Operations 证据队列中。该投影只包含
数量、缺失证据/错误代码、已复核查询区间完整性、最近复核时间和确定性指纹，不包含来源路径、
文件名、交易明细或账户事实。其有界读取在来源扫描达到 200 条时 fail closed，已复核区间存在缺口
或重叠时也保持 blocked。它仍位于 canonical Operations health 之外，但其脱敏 follow-up fingerprint
会绑定到受控执行消费的 Account Truth promotion evidence；来源待处理、扫描截断、读取失败、日期缺口
或重叠只会把 clear 降为 blocked。拒绝来源只会关闭对应的来源复核任务，不会生成 Account Truth
证据，也不会授予对账、风控、执行或资本权限。

Account Truth 页面会把上述来源复核与 canonical score 投影到
`karkinos.account_truth.evidence_readiness.v2`。其中
`karkinos.account_truth.evidence_scope.v1` 只报告精确持久化导入中观察到的日期跨度、资产类别、
币种和快照日期，绝不把首末记录冒充完整账户或完整时段覆盖。账户绑定、声明覆盖窗口和资产范围
完整性会保持阻断，直到 owner 对该精确导入执行显式复核。晋级与就绪门禁取最新现金快照和最新
持仓快照时间中更早者作为 Account Truth 的实际采集时间；仓库导入时间另记为 `imported_at`，今天
重新导入旧账单不能把账户状态变新。缺少快照、两类快照跨日、快照后仍有财务事件或实际采集已
过期都会 fail closed。嵌套的
`karkinos.account_truth.citic_source_resolution_stage.v1` 会把“查询区间待复核”“来源范围待复核”和
“历史声明均已完成、仍需 canonical 证据或显式拒绝”分开显示；最后一种状态不要求重做 XLS 声明，
但也绝不把 legacy 来源提升为 Account Truth、对账或执行证据。

显式复核只在浏览器中对券商账户标识计算哈希；原始标识不会发送给 API，也不会持久化。追加式
记录绑定导入 fingerprint、观察范围 fingerprint、provider、本地别名、账户引用哈希、复核日期和
资产类别；相同动作幂等，后续复核继续追加，撤销或来源漂移会 fail closed。该动作不修改券商证据、
账本或对账结果，也不授予执行或资本权限。

就绪清单会直接展示持久化查询区间完整性与缺口/重叠天数，并逐项展示当前现金/持仓快照、逐项结算费用与税、成本价、新鲜度和 ledger coverage、
reconciliation gate 及仍待补证的已知来源。只有 Account Truth gate 与每一项要求都为 `pass` 时
才显示 `ready`；缺失 schema 视为没有证据，部分/不兼容 schema 或损坏记录则 fail closed。该 GET
不扫描私有目录、不联系 provider、不写数据库，也不获得 reconciliation、submit/cancel 或资本权限。

## 本地自动读取

日常本机运行可以显式启用只读 collector，避免每次在浏览器重新选择同一文件：

```json
{
  "account_truth": {
    "broker_statement_collector": {
      "enabled": true,
      "daily_snapshot_roll_forward_enabled": false,
      "path": "broker_statement.csv",
      "poll_interval_seconds": 5,
      "stability_delay_seconds": 2,
      "max_file_bytes": 10485760
    }
  }
}
```

collector 只在启动配置明确开启后运行。它等待 size/mtime 稳定，再完整读取、校验并按文件
fingerprint 暂存证据；相同内容的重复轮询和进程重启复用同一个 import run。文件消失、写入中、
且保留首次 `created_at`，重放不能把旧证据伪装成新鲜证据。文件消失、写入中、超限、编码错误
或 schema 阻断时保持 fail closed，并保留此前已暂存证据。状态由
`GET /api/account-truth/broker-statement/collector` 只读返回。

这不是自动入账：collector 不联系 provider，不修改生产 ledger、持仓、OMS、风控、kill switch
或资本授权。差异仍需在 Account Truth 中人工复核，手工上传继续作为 fallback。

Owner 可将 `daily_snapshot_roll_forward_enabled` 显式改为 `true`。准备阶段会以最后完整现金锚点
加其后的净流水重算现金，并从每个已知标的的最后完整状态派生持仓快照，统一写为当日上海时间
08:45。旧的 Karkinos 派生行会先被移除，因此文件不会逐日累积；同日重复运行不改文件。任何源
事件晚于决策前时点、账本更新未被源文件覆盖、缺失/冲突/非有限状态或并发文件变化都会阻断。
它不把“无活动”推断成新交易事实，也不接触券商、生产账本、OMS 或资本授权。

账户范围与费用复核绑定 `karkinos.account_truth.source_fact_lineage.v1`：它对全部非派生、
标准化原始行做与行顺序无关的完整指纹。只有该 lineage、已复核账户/窗口/资产范围以及从复核
导入到当前导入之间的每一次 import 都完全一致时，当日派生快照才可继承复核。任何新增、修订、
删除、损坏或中途短暂出现的不同原始事实都会立即使继承失效；之后把文件恢复成旧内容也不会让
旧复核复活。当天快照仍保留独立的精确 import/promotion identity；继承仍可撤销，也不授予订单、
账本、执行或资本权限。

## Canonical CSV 列

CSV 必须包含以下列。未涉及的字段保留为空字符串，不要删除列。

| 列名                | 说明                                                       |
| ------------------- | ---------------------------------------------------------- |
| `event_id`          | 券商侧或导入侧稳定事件编号；同一文件内应唯一               |
| `event_type`        | 事件类型，见下方枚举                                       |
| `occurred_at`       | 业务发生时间，推荐 ISO-8601，含时区                        |
| `settled_at`        | 结算日期或时间                                             |
| `symbol`            | 标的代码；交易、分红和持仓快照事件必填                     |
| `instrument_name`   | 标的名称；展示和人工复核使用                               |
| `asset_class`       | 资产类别，例如 `stock`、`fund`、`cash`                     |
| `currency`          | 币种，例如 `CNY`                                           |
| `quantity`          | 发生数量；现金类事件填 `0`                                 |
| `price`             | 成交价、净值或快照价；不适用时填 `0`                       |
| `gross_amount`      | 税费前金额                                                 |
| `fee`               | 手续费、佣金或其他费用                                     |
| `tax`               | 税费                                                       |
| `net_amount`        | 现金净影响；买入通常为负，卖出或入金通常为正               |
| `cash_balance`      | 事件后现金余额；未知可空                                   |
| `position_quantity` | 事件后持仓数量；未知可空                                   |
| `cost_basis`        | 事件后成本价或成本基准；未知可空                           |
| `note`              | 仅放可公开解释的备注，不放账号、手机号、券商凭证或私密信息 |

CSV 也可以包含以下可选列。旧文件不需要补列；如果存在，导入预览会保留它们用于
更细的费用、成本价和订单身份对账。

| 列名                | 说明                                                                  |
| ------------------- | --------------------------------------------------------------------- |
| `transfer_fee`      | 过户费或券商单独列出的转让/过户费用；未知可空，默认 `0`               |
| `cost_basis_method` | 券商成本价口径，例如 `broker_remaining_cost`；仅用于人工复核解释      |
| `broker_order_id`   | 券商订单号证据；仅允许字母、数字及 `._:-`，最长 128 字符；未知可空    |
| `client_order_id`   | Karkinos 提交时使用的幂等客户订单号证据；同样限制字符和长度；未知可空 |

订单号字段只是导入证据，不会授予券商写权限。旧文件可以继续留空，但缺少任一订单号的
trade row 不能用于受控提交的全量成交清算；该门禁还要求两个订单号都与持久化 submit
intent 精确一致、来自同一已验证导入并覆盖完整 OMS 数量。

支持的 `event_type`：

- `trade_buy`
- `trade_sell`
- `dividend`
- `fee`
- `tax`
- `transfer_in`
- `transfer_out`
- `position_snapshot`
- `cash_snapshot`

## 安全合成样例

下面的样例使用合成符号和合成名称，不对应真实账户或真实交易。

```csv
event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row,0.00,broker_remaining_cost,BROKER-SYN-001,KARK-SYN-001
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,SYN001,合成样例股票A,stock,CNY,20,10.50,210.00,5.00,0.21,204.79,9176.79,80,10.28,synthetic sell row,0.00,broker_remaining_cost,BROKER-SYN-002,KARK-SYN-002
synthetic-dividend-001,dividend,2026-01-12T15:30:00+08:00,2026-01-12,SYN001,合成样例股票A,stock,CNY,80,0,12.50,0.00,0.00,12.50,9189.29,80,10.28,synthetic dividend row,,
synthetic-fee-001,fee,2026-01-13T15:30:00+08:00,2026-01-13,,,,CNY,0,0,0.00,1.25,0.00,-1.25,9188.04,,,,,
synthetic-tax-001,tax,2026-01-14T15:30:00+08:00,2026-01-14,,,,CNY,0,0,0.00,0.00,0.75,-0.75,9187.29,,,,,
synthetic-transfer-in-001,transfer_in,2026-01-15T08:45:00+08:00,2026-01-15,,,,CNY,0,0,500.00,0.00,0.00,500.00,9687.29,,,,,
synthetic-transfer-out-001,transfer_out,2026-01-15T09:45:00+08:00,2026-01-15,,,,CNY,0,0,-300.00,0.00,0.00,-300.00,9387.29,,,,,
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,合成样例股票A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,9387.29,80,10.28,synthetic position snapshot,,broker_remaining_cost
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,9387.29,,,,,
```

## 导入预览行为

当前 Python 入口：

```python
from account_truth.broker_statement import parse_broker_statement_csv

preview = parse_broker_statement_csv(csv_text)
```

预览结果包含：

- `schema_version = "karkinos.broker_statement.v2"`
- `source_type = "canonical_broker_statement_csv"`
- `file_fingerprint`
- `row_count`
- `valid_row_count`
- `invalid_row_count`
- `duplicate_row_count`
- `validation_status`：`pass`、`warning` 或 `blocked`
- `events[]`：标准化后的 broker evidence events
- `errors[]`：阻断或校验错误
- `limitations[]`：当前导入边界说明

重复检测是确定性的：完全相同的标准化行会得到相同 `row_fingerprint`，后出现
的行会标记 `is_duplicate=true` 并记录 `duplicate_of_row_number`。

## Staged broker evidence

当前 Python 入口：

```python
from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv

preview = parse_broker_statement_csv(csv_text)
repository = BrokerEvidenceRepository("data/store/app.db")
import_run = repository.save_preview(preview, source_name="local-statement.csv")
```

`save_preview()` 会写入：

- `broker_import_runs`：`import_run_id`、schema version、source type、source name、
  file fingerprint、row counts、validation status、row duplicate count、
  file duplicate count、limitations、created timestamp。
- `broker_evidence_events`：每一条合法 broker evidence event 的 event type、
  row fingerprint、数量、价格、税费前金额、佣金/费用、税费、过户费、现金净影响、
  快照字段、券商成本价口径、可选 broker/client order identity 和行级重复信息。

如果同一 `file_fingerprint` 已经导入过，会复用原 `import_run_id`，并且不会再次写入
broker evidence events，也不会刷新其证据年龄。这个阶段仍然不会写入或修改
`ledger_entries`；后续对账
和人工确认流程会决定哪些差异需要处理。

## Reconciliation report

较早发生的券商分红，只能在代码、净现金金额完全匹配、同一 import 含有分红之后的现金快照、
且该券商事件尚未覆盖其他账本行时，覆盖同一上海交易日稍后录入的账本事实。金额或代码冲突、
缺少事后现金快照以及本地重复录入仍保持 stale/blocked。

当前 reconciliation 核心入口：

```python
from account_truth.reconciliation import (
    KarkinosLedgerFact,
    KarkinosPositionFact,
    build_reconciliation_report,
)

report = build_reconciliation_report(
    import_run_id=import_run.import_run_id,
    broker_events=repository.list_events(import_run.import_run_id),
    ledger_facts=[
        KarkinosLedgerFact(
            event_type="trade_buy",
            symbol="SYN001",
            quantity=Decimal("100"),
            price=Decimal("10.23"),
            fee=Decimal("5.00"),
            tax=Decimal("0.00"),
            net_amount=Decimal("-1028.00"),
        )
    ],
    cash_balance=Decimal("8970.00"),
    positions=[
        KarkinosPositionFact(
            symbol="SYN001",
            quantity=Decimal("100"),
            cost_basis=Decimal("10.28"),
        )
    ],
)
```

报告 schema version 为 `karkinos.account_truth.reconciliation.v1`，当前会比较：

- broker cash snapshot vs Karkinos cash balance；
- broker position snapshot vs Karkinos position quantity；
- broker trade gross amount vs Karkinos trade gross amount；
- broker signed net cash impact vs Karkinos ledger cash impact；
- broker fees vs Karkinos ledger fees；
- broker taxes vs Karkinos ledger taxes；
- broker transfer fees vs Karkinos ledger transfer fees；
- broker cost basis vs Karkinos position cost basis。

报告状态为 `pass`、`warning`、`mismatch` 或 `blocked`。快照证据不足时会输出
`provide_cash_snapshot`、`provide_position_snapshot` 等补证建议；有差异时会输出
`review_cash_difference`、`review_position_difference`、
`review_trade_gross_amount_difference`、`review_net_cash_impact_difference`、
`review_fee_difference`、`review_tax_difference`、
`review_transfer_fee_difference`、`review_cost_basis_difference` 等建议复核动作。
当前报告只是差异证据，不会自动生成 ledger entry，也不会修改现金、持仓或成本基础。

## Manual review decisions

当前 manual review 入口：

```python
from account_truth.manual_review import ManualReviewRepository

review_repository = ManualReviewRepository("data/store/app.db")
decision = review_repository.record_decision(
    import_run_id=import_run.import_run_id,
    item_key="cash",
    category="cash",
    review_status="needs_investigation",
    note="需要核对券商资金余额快照",
    reviewer="local",
)
```

支持的 `review_status`：

- `accepted`
- `ignored`
- `known_difference`
- `ledger_candidate`
- `needs_investigation`

同一个 `import_run_id` + `item_key` 会更新当前复核状态，同时把每次决定追加到复核
历史表。每条复核决定绑定当时 reconciliation item 的事实指纹；券商值、本地值、差额、
状态或口径上下文发生变化后，旧复核保留用于审计，但会标记为失效。`ledger_candidate`
只是人工复核标记，不会自动创建或修改 `ledger_entries`；真正写入生产账本仍需要后续
显式确认流程。

## 策略研究使用的已审查费用表

运行配置中的 `broker_fee_schedule` 在与当前精确 Account Truth 导入完成比对并由人工
明确复核前，只是候选口径。人工闭环为：

```text
POST /api/account-truth/fee-schedule/preview
GET  /api/account-truth/fee-schedule/review
POST /api/account-truth/fee-schedule/reviews
POST /api/account-truth/fee-schedule/reviews/revoke
```

预览要求 Account Truth readiness 为 ready、promotion projection 为 clear、费用配置的
账户别名与已审查账户一致、来源/范围 fingerprint 有效，并且持久化的 stock/ETF 买卖
成交同时覆盖。佣金与其他费用、印花税、过户费必须分别落在 reconciliation tolerance
内。canonical `fund`/`fund_etf` 仅在费用审查中归一为 ETF；差异按资产类别、买卖方向和
费用分项聚合。股票与 ETF 过户费率分别审查；ETF 条款未填时继承旧版股票条款。
旧版已接受审查仅保留可读审计能力，必须重新计算并人工接受后才能供下游使用。
响应和复核表只保留汇总数量、最大差异、安全费用条款与 fingerprint，
不复制券商事件行、symbol、私有账户标识、文件名或来源明细。

批准会重新计算预览，并要求精确 preview fingerprint、reviewer 和确认语句
`approve_reconciled_account_fee_schedule_for_research_only_without_execution_or_capital_authority`。
复核是 append-only 且可撤销；撤销须绑定当前 review id/fingerprint，并使用
`revoke_reconciled_account_fee_schedule_without_execution_or_capital_authority`。GET 只读打开
已有表，不会初始化或修复 schema。

Account Truth Review Center 以显式人工流程提供同一顺序：选择已审查证据窗口、重新计算预览、
检查买卖覆盖和汇总分项匹配，再输入复核人及完整确认短语。预览被阻断或已过期时不能接受。
一条已接受记录只有在只读重算仍与其预览 fingerprint 一致时才显示为 `active`。v2 预览绑定
稳定原始事实 lineage 与范围复核 binding，而不是每天被替换的派生快照行；当前 Account Truth、
费用证据或任一中间 import 漂移仍会显示 `blocked`，恢复旧文件也不能绕过。旧记录仍保留供审计，
并且仍可被人工明确撤销。

生效复核会生成版本化 cost-model reference。同一解析后的计算器（包括交易所覆盖和
逐费用分项的金额舍入）同时用于刷新基准、每个 Formula 候选和参数变体。Critique、晋级
和每张保留策略票据都会重新解析当前复核；Account Truth 漂移、篡改、撤销、reference
不一致，或回测/动作日期不在有效区间时一律 no-action。内置估算与缺失复核均不能晋级；
该复核不能提交订单、注册生产策略或改变资本权限。

## 券商结算确认

当交易明细或交割单已经给出实际佣金、印花税、过户费和净现金影响时，可以通过显式
接口确认一条已有交易流水：

```text
POST /api/ledger/trades/{entry_id}/settlement
```

该接口不会下单，也不会从 Account Truth 导入时自动调用。它会先校验净现金影响与
成交总额、费用分项是否一致，然后在同一事务中：

- 首次保存原始估算佣金、费用分项、净现金影响和费用规则；
- 将交易流水的有效费用和净现金影响更新为券商实际结算值；
- 记录结算来源、证据引用、确认时间和备注；
- 追加 `portfolio.trade_settlement.confirmed` 审计事件，保留调整前后值和现金差额；
- 对同一个 `source` + `source_ref` 幂等处理，冲突值会被拒绝。

因此，交易前费用模型仍可用于预估和回测；成交后的现金、成本和 Account Truth 对账
则使用券商确认值。来源必须是交易明细、交割单或等价的结算证据，不能仅凭首页汇总
展示反推每笔费用。

## Account Truth Score

当前 score 入口：

```python
from account_truth.score import build_account_truth_score

score = build_account_truth_score(
    report=report,
    review_decisions=review_repository.list_decisions(report.import_run_id),
    data_freshness_status="fresh",
)
```

`AccountTruthScore` schema version 为 `karkinos.account_truth.score.v1`，包含：

- `score`：0-100 的确定性账户事实分；
- `gate_status`：`pass`、`degraded` 或 `blocked`；
- `cash_status`、`position_status`、`fee_status`、`cost_basis_status`；
- `data_freshness_status`：`fresh`、`stale` 或 `missing`；
- `unresolved_mismatch_count` 与 `resolved_review_count`；
- `required_actions`、`blocking_reasons` 和 `limitations`。

人工复核状态只记录审计处置，不覆盖仍然存在的 `mismatch` 或 `blocked`。物质性差异
必须通过更新券商证据、显式纠正账本，或由 reconciliation 的明确数值容差重新归类后
才能解除门禁。最新券商导入若早于最新本地账本事实，score 会标为 `stale` 并附加
`account_truth_evidence_predates_latest_ledger` 阻断。Score 只是 cockpit、promotion
gate 和报告可消费的账户事实信号，不会自动修改账本或提交订单。
