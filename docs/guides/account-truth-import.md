# Account Truth 本地导入

> Status: maintenance reference. 本文解释现有导入能力，不定义当前 roadmap；产品方向见 [PLAN.md](PLAN.md)。

Account Truth 的目的，是把本地券商来源先变成可审计 evidence，再由显式 review/reconciliation 决定它能否影响 authoritative account state。

## 不变量

- 导入/预览本身不写 production ledger、不修改持仓、不创建或提交订单。
- 原始券商账号、密码、截图和真实导出不得进入源码仓库。
- Provider/source row 先标准化、验证、指纹化，再进入 staged evidence。
- 不完整、冲突或无法证明范围的来源保持 blocked。
- 任何 ledger/account mutation 都必须经过独立的 canonical transaction/reconciliation path。
- Account Truth evidence 不授予 execution 或 capital authority。

## 当前输入路径

### Canonical broker statement CSV

本地 CSV collector 可在 `config.json` 的 `account_truth.broker_statement_collector` 中显式启用。配置字段、轮询/稳定时间和路径规则见 [配置参考](config-reference.zh.md)。

Collector 只读取本地文件，等待文件稳定，按内容 fingerprint 幂等处理；文件缺失、写入中、schema 不兼容或超限时 fail closed。

### 中信历史成交 XLS

现有 UI/CLI 支持对 legacy `.xls` 历史成交做隐私最小化 preview。Preview 用于识别结构、事件和缺失证据，不会把 XLS 直接提升为 canonical Account Truth。

历史成交通常不能单独证明完整现金、持仓、逐项费用、查询范围和账户 scope，因此不能靠“成交金额差额”等方式猜测缺失事实。

特定的目录扫描、query-window/source-scope review、lineage assessment 等属于现有兼容实现细节。需要维护时以 `account_truth/`、对应 route/service 和 deterministic tests 为 executable contract，不再把这些细节复制到 master 文档。

### Legacy QMT lifecycle

仓库仍保留旧 QMT lifecycle adapter/导入兼容代码。它属于 later-stage execution/account evidence，不是当前研发主线；任何重新启用都需要重新按 [ARCHITECTURE.md](ARCHITECTURE.md) 的 execution/reconciliation boundary review。

## 推荐操作顺序

```text
local source
-> preview / validate
-> staged evidence
-> human review
-> reconciliation
-> explicit canonical apply (if supported)
```

不要通过 SQLite 手工编辑来“完成”导入。

## 隐私

真实来源文件应只存在于本机运行目录。测试和文档使用合成数据。

API/UI 应优先显示脱敏 alias、计数、fingerprint、status 和 blocker；不需要把原始账号、路径、文件名或逐行私有内容暴露给不相关页面。

## 当前优先级

Account Truth / broker 现有安全边界继续维护和修 bug，但在 [PLAN.md](PLAN.md) Phase G 之前冻结功能扩张。后续重新进入真实 broker 集成时，再基于当时选定 provider 和新的统一 Execution/Accounting architecture 重写 operator runbook。
