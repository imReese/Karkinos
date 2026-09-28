# 自动化、多来源行情与研究数据设计

本文件细化 [架构中的数据边界](../docs/ARCHITECTURE.md)，不另设项目目标。
开发顺序和未交付项由 [PLAN](../docs/PLAN.md) 管理。

## 1. 目标与非目标

一次配置后，后台对授权范围内的标的和已收盘交易日持续执行有界的单源采集、
规范化与单源质量检查。跨源核验由明确的研究需求提交为持久任务；核验通过后
可以发布带核验证据的固定 Dataset。研究显式绑定 DatasetRef，不因后台采集或
核验成功而静默更换输入。关闭浏览器不影响已提交任务；停机后按持久任务恢复。
自动市场数据维护与实盘交易授权无关，不得启用交易、修改账户事实或接入新券商。

“来源成功”“格式正确”“多源一致”“历史时点可用”“适合收益回测”是不同结论。
第一批落实沪深股票、ETF 的未复权日线闭环；不宣称支持所有市场、分钟线、财务数据、
严格历史 PIT 或完整公司行动收益。尚未支持的语义必须明确阻断或标记，不用默认值冒充。

## 2. 现状与复用边界

- 保留 `providers -> market -> dataset` 及 domain-neutral `storage`。
- 复用 Capture、Revision、Materialization、质量、reconciliation、Dataset reader/catalog。
- 复用受管 data worker、`SQLiteJobStore` 的幂等键、租约、心跳和重试。
- 复用应用交易日历及 watchlist；不维护第二份证券或交易日历真相。
- 现有单源 Dataset 保持原 ID、原字节与重放语义；升级不自动补上“已核验”标签。
- 新适配器不调用旧适配器的自动回退、复权或重试流程，避免捕获与实际请求不一致。
- 不引入 Airflow、Dagster、Redis、配置中心、消息总线或验收框架。

## 3. 正常运行与应用边界

```text
启动入口：合并配置，校验，准备持久目录，启动受管 worker
    ↓
默认计划：watchlist 中受支持的标的与最近已收盘交易日
    ↓
持久任务：缺口 -> 排队 -> 租约领取 -> 心跳 -> 有限重试
    ↓
首个可用 Provider 捕获 -> normalize -> Revision/Materialization -> 单源质量
    ↓
采集健康与质量状态；不自动发布 Dataset

明确提交核验需求 -> 持久的逐日双源任务
    ↓
两源分别捕获与检查 -> 跨源 reconciliation -> 不可变 Verification
    ↓
匹配后发布带 VerificationRef 的单日 v2 Dataset；冲突阻断发布
    ↓
明确组合完整交易日区间并绑定 DatasetRef；重放只用原引用
```

HTTP 明确提交双源任务和读取状态；普通回测只绑定已发布的 Dataset，不偷偷发起下载。
任务未完成时不能先用旧缓存运行再补一个 Dataset ID。长采集不在一个 HTTP 请求中等待
完成，不使用内存 Lock 冒充跨进程任务归属。

## 4. 配置与采集授权

凭据沿用统一启动加载器：进程环境优先于所选 `.env`；不可在模块 import 时读取。
配置对象按应用实例持有，Provider 只接收自己的凭据。TDX 使用已有私有临时 INI 与
隔离 SDK 子进程，不修改安装目录；日志、任务载荷、报告和研究目录禁止保存 Key。

自动维护使用有界默认值，而不是有 Key 就拉全市场：

| 配置 | 规则 |
| --- | --- |
| 启用 | 默认启用自动维护；凭据缺失只停相关能力，离线读取不受影响 |
| 标的范围 | 当前 watchlist 中明确标为 stock/etf 的受支持证券；空集合不采集 |
| 首次历史范围 | 默认最近 30 个自然日内的已完成交易日；扩大范围是一次配置修改 |
| 采集来源 | 使用 `market_data.source_policy` 的日线候选顺序取首个可用源；默认策略优先 BaoStock |
| 核验来源 | 显式任务独立使用 `market_data.verification_source_policy`，其策略 ID 固化在任务中；只选择不同上游的两源，当前运行时不调用 TDX 参与双源任务 |
| 数据就绪 | 上海时区 16:00 后才把当日纳入后台日线计划 |
| 限流 | 当前 worker 串行领取任务；尚无跨重启持久的来源调用预算 |
| 限额 | 显式核验一次最多提交 366 个自然日的交易日任务；这不是 SDK 调用或费用上限 |
| 重试 | 持久任务有有限次数和退避；来源不可用不能无限重试 |
| 修订窗口 | 相同任务身份幂等复用；当前尚未自动创建新的修订观察轮次，旧 Dataset 永不改写 |

范围、轮次、接口、规则摘要进入任务身份；秘密值不进入身份。
当前相同任务身份幂等复用。后续接入持久调用预算时，定时与显式任务必须共用
原子预留，不能通过重复点击或重启绕过。

## 5. 来源身份、能力与独立性

至少记录 provider、endpoint、adapter_version、声明的 upstream_group、原始单位、
价格口径、交易时段、支持资产、调用与可用时间。包名不是独立来源证明。

| 适配器 | 股票日线 | ETF 日线 | 声明的数据链路 |
| --- | --- | --- | --- |
| BaoStock | query_history_k_data_plus，未复权 | 同接口 | BaoStock |
| AKShare 腾讯日线 | stock_zh_a_hist_tx，adjust="" | 同接口 | AKShare SDK → 腾讯 |
| AKShare 东方财富日线 | stock_zh_a_hist，adjust="" | fund_etf_hist_em，adjust="" | AKShare SDK → 东方财富 |
| TuShare | daily | fund_daily | TuShare Pro |
| TDX | get_market_data，未复权且不补齐 | 同接口的已支持 ETF | TDX Data Service |

不同供应商可能共享上游，所以结果称为“跨来源一致”，不称为“独立真值认证”。
`tencent` 与 `akshare_tencent` 的日线适配器调用同一 AKShare 腾讯接口，同属腾讯上游，不能算两票；AKShare 东方财富接口和直接东方财富接口也不能算两票；上游不明时记录未知。
故障切换和交叉核验分别建模：主源失败，不让核验源顶替主源并核验自己。
新增来源须完成口径映射和适配器检查，再进入允许配置集合。

`data/providers/` 按实际数据上游组织：`eastmoney.py`、`tencent.py`、`tushare.py`、
`tdx.py`、`baostock.py`、`sina.py`、`sge.py`。AKShare 只是多个上游接口的
SDK，`akshare_sdk.py` 仅保留通用调用辅助；旧多资产 `DataSource` 分发类在
`data/legacy_sources/`，自身不拥有上游请求。TuShare SDK 的 `dc` 实时报价归
东方财富模块。模块位置不改变已持久化的 provider ID、adapter_version、
payload_format 或 Dataset 引用。新报价在 metadata 中记录实际
`upstream_group` 和适用的 `transport_sdk`；TuShare `dc` 报价的值分别是
`eastmoney` 和 `tushare`。原有 `provider_name`、`quote_source` 保持不变，
供历史读取与盘后规则使用。

## 6. 数据与质量语义

统一使用证券类型+代码、明确交易所映射、交易日、UTC 时刻、CNY、股/份、元。
拒绝复权与未复权混比。未复权保存原始事实，不代表无需公司行动建模。
单源检查覆盖字段、NaN/Inf、OHLC、唯一键、预期标的、时间与物理完整性。
不会填零、平均、静默丢行或把每个空响应都解释为停牌。
空表捕获仍保存；请求失败保留脱敏错误，不拿缓存冒充本次响应。
原始表格注明是 SDK DataFrame 的序列化表示，不谎称保存 HTTP wire bytes。

证券状态应区分正常交易、已证实停牌、未上市、退市、交易所休市、供应商未就绪、
未知缺失。交易所开市不等于每个证券必须有一行。
证券级状态证据接入前，未知缺失阻断受影响的完整区间，不猜测、不合成停牌 K 线。

## 7. 跨来源判定

比较同一证券/交易日/频率/口径，覆盖 OHLC、volume、amount、event_time、suspended。
默认绝对容差为 0。已审阅的 BaoStock + 腾讯日线规则保持价格严格一致，仅容许成交量绝对差 99 股、成交额绝对差 99.99 元，反映腾讯接口的数据粒度。单位换算在适配器完成，不能靠容差掩盖 100 倍或 1000 倍错误；规则需版本化，不能反复调大阈值让数据变绿。
盘后成交、集合竞价等统计范围不确定时记录不可比较或冲突，不自动删除字段。

| 状态 | 结果 |
| --- | --- |
| 两源单源检查通过且逐字段一致 | matched，可发布带核验证据的研究快照；不证明严格历史 PIT 或总收益 |
| 两源有值但不同 | conflict，保存差异和版本，阻断该分区新发布 |
| 第二源未就绪或请求失败 | pending/unavailable，有限重试，不是 matched |
| 口径不同或来源未审阅 | incompatible，不进入数值表决 |
| 证券状态未知或缺记录 | incomplete，先解决覆盖证据 |
| 物理对象损坏 | integrity_error，禁止换源、覆盖原 ID 或降级读取 |

机器规则决定正常发布，无人工审批。第三来源用于诊断，不简单多数表决。

## 8. 不可变证据与发布

Market Data 拥有核验事实：两个 revision/materialization/capture、来源与接口、
适配器及 normalizer 版本、完整规则与规则摘要、预期标的、逐字段差异、单源质量、checked_at。
成功和冲突均内容寻址落盘。日志不能代替可重放证据。

Dataset 每个已验证分区绑定 verification_id。新清单使用 v2；v1 原有字节不变。
有证据与无证据的分区不能混合作为完整已核验 Dataset。
Reader 检查引用、两源物化完整性和实际结论，不只是相信 JSON 的 matched。
证据缺失、错绑日期/标的/版本、改写规则、第二源损坏均阻断相关重放。
同一规则解释必须固定；规则改变新增版本，不让新代码重解释旧证据。

发布顺序：内容对象 -> 验证候选 -> Dataset manifest -> Catalog。
Catalog/Serving 是可重建投影，不是研究输入真相。
丢失租约的 worker 可以留下孤立不可变对象，但不能更新任务成功、当前发布或 Serving。
跨 SQLite/文件不宣称有分布式事务；恢复时校验对象并幂等登记，不改写原事实。

## 9. PIT 与研究消费

分别保留 event_time、available_at、captured_at、checked_at。
缺少历史发布时间证据时 available_at 使用捕获时间；次日核验只能声明次日已核验。
选数 cutoff 与证据可用时间都受检查。自动核验不把回填升级为严格历史 PIT。

研究准备明确选择 universe、日期、价格口径、规则及 cutoff，固定 DatasetRef。
旧研究重放固定原引用，不查 latest/Serving，不在网络恢复后换新版。
结果分开展示完整性、跨源一致性、历史可用性与公司行动/收益口径限制。
仅有原始未复权日线时，不声明总收益正确或允许策略自动升级。
参数扫描与比较已可明确传入同一 Dataset ID；研究预览尚未接入这条输入链，
不能声称与它们使用同一份数据。

| 用途 | 当前准入与结论 |
| --- | --- |
| 自动采集健康 | 保存 Capture、Revision 和单源质量；不发布研究 Dataset |
| 探索回测 | 明确绑定可离线重放的 v1 单源或 v2 核验 Dataset；保留历史 PIT 未证实与未复权收益限制 |
| 参数扫描、候选比较 | 使用 Dataset 时，每次运行传同一 `dataset_id`、区间和标的；结果只作研究排序，不能自动晋级 |
| 策略晋级与前瞻发布 | 仍需独立证明历史可用性、动态 universe、公司行动收益、样本外与成本等既有门槛；当前 Dataset 不满足即阻断 |
| 账户收益与归因 | 由已入账的交易和估值计算，不能从未复权价格变动或回测名次推定 |

## 10. 任务与故障恢复

复用 job_runs：queued -> running -> succeeded / queued(退避) / failed。
实际粒度先为一个标的、一个交易日、一个核验规则、一个采集轮次；组合区间复用分区。
可直接统计完成数、待核验与失败日期，不另建进度数据库。
任务载荷只含数据范围、规则、轮次，不含凭据或任意文件覆盖权限。

租约含 owner+attempt；心跳与最终登记均校验 fencing。取消、超时、主管退出必须先终止
并等待原生 SDK 子进程，再允许新 worker 领取；取消 await 不等于线程已停止。
断电或父进程 SIGKILL 后按租约恢复，不把尚未验证的子进程清理写成绝对保证。
停用或修改计划后，旧队列不能继续越权采集。启动/健康检查不重置预算或无限回填。

## 11. 可观察性、备份和恢复

状态接口/页面逐步展示配置来源（不显示秘密）、来源健康、任务进度、覆盖日历、
最近核验时间、冲突分区、价格口径和已发布数据集；额度展示须等持久预算接通。
失败含稳定错误码与证据引用。
未知与零记录区分，一处坏分区不应阻断其他证券或旧数据集。

备份包括研究 objects、manifests、Catalog/Serving/任务状态；SQLite 使用 backup API
或停写副本，不能只复制运行中的 WAL 主文件。恢复到新目录验证后才明确切换，不自动覆盖。
账户数据库备份不等于研究数据备份。清理必须保留全部已发布 Dataset、证据、失败诊断和
在途任务可达对象，首版不自动 GC。

## 12. 兼容与验证要求

默认单源采集只发布质量证据；显式双源核验成功才发布带 VerificationRef 的 v2
Dataset。v1 Dataset 的 ID、字节和读取含义不变。区间组合只引用明确选定的已核验
单日分区，缺少交易日、证据或物理对象均阻断发布；不查找 latest 来替换输入。
探索性研究可以使用固定 Dataset；严格 PIT、公司行动收益和策略晋级各自保留独立门槛。

产品验证走真实应用入口：采集失败保留 Capture，一源失败不能降级冒充双源成功，
冲突可追溯，旧回测在修订后仍使用原输入，无 Key 仍能离线读取。
开发检查由开发者与 CI 执行，不让用户日常重复跑 smoke。
本地、CI、真实供应商验证分开报告，不把替身成功当作真实权限或双源实测成功。

## 13. 参考依据

- [QLib Data Layer](https://qlib.readthedocs.io/en/latest/component/data.html)：采集、校验、存储与研究读取分层，不复制整体框架。
- [TuShare daily](https://tushare.pro/document/2?doc_id=27)：原始价格、手、千元，停牌不返回日线。
- [TuShare fund_daily](https://tushare.pro/document/2?doc_id=127)：场内基金价格、手、千元。
- [AKShare 股票](https://akshare.akfamily.xyz/data/stock/stock.html)：东方财富接口、未复权参数与单位。
- [AKShare 基金](https://akshare.akfamily.xyz/data/fund/fund_public.html)：ETF 东方财富历史行情。

公开文档是映射依据，不是正确性担保。升级 SDK 时核对字段、单位和统计范围，
按行为与真实小样本复核，不仅依赖版本号或包名。
