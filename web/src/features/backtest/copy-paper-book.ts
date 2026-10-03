export const paperBookCopy = {
  zh: {
    title: '独立模拟账本',
    detail:
      '独立记录模拟现金、持仓、成交和净资产，与上方仅记录目标及价格观察的 shadow 并列。仅接收本账本创建之后实际发布的目标，不补造历史交易。',
    boundary:
      '仅手动结算，不继承观察的自动推进权限，不改变真实账本或资金授权。采用日线成交模型和服务商报告的税前分红送转，不代表实际成交、历史完整知情或保证收益。',
    initialCash: '初始模拟现金（元）',
    create: '创建独立模拟账本',
    createHint:
      '每条观察最多一个账本。初始资金和成本创建后冻结；更改配置或重新开始需另起观察。',
    costs:
      '这些成本仅用于新建的独立模拟账本；股票佣金、最低佣金和滑点可选覆盖，其余费用由服务端模型决定并冻结。',
    defaultCosts: '使用服务端内置成本与零滑点，创建后可查看冻结的有效费率。',
    unsupported:
      '独立模拟账本目前仅支持标准 A 股股票；所选观察包含不支持的品种。',
    refresh: '刷新模拟账本',
    loading: '正在读取已保存的模拟账本…',
    loadFailed:
      '无法读取模拟账本状态。请刷新后再操作；已显示的快照不是最新确认状态。',
    saving: '正在保存模拟账本…',
    saved: '模拟账本已保存。',
    active: '接收创建后发布的新目标',
    paused: '已停止接收新目标',
    pause: '停止接收新目标',
    pauseHint:
      '此操作不可恢复接收，不会清仓。已接收目标与已有持仓仍可手动结算；重新开始需另起观察。',
    dataset: '用于模拟账本结算的正式 Dataset',
    choose: '请选择已保存的数据集',
    refreshDatasets: '刷新账本可选 Dataset',
    datasetHint:
      '仅列出同一起始日、同一股票集合且标有双源核验和分红送转证据的 Dataset。服务端仍会检查最新已收盘日、完整历史前缀和证据；缺失时请通过现有研究数据准备流程补齐。',
    datasetFailed: '无法读取可选 Dataset，请刷新后再结算。',
    noDatasets:
      '没有匹配的正式 Dataset。请先在研究数据准备流程完成核验并绑定分红送转证据。',
    settle: '手动结算模拟账本',
    snapshot: '已保存账本快照',
    asOf: '截至已结算日',
    notSettled: '尚未结算，仅初始资金',
    unchanged:
      '本次操作未确认成功。下方仍显示上次保存的快照及其结算日期，请刷新确认后再操作。',
    cash: '现金（元）',
    equity: '净资产（元）',
    receivable: '应收税前分红（元）',
    income: '累计税前分红收入（元）',
    positions: '持仓',
    noPositions: '无持仓。',
    symbol: '标的',
    quantity: '总数量',
    available: '可用 / 冻结 / 未上市',
    marketValue: '市值（元）',
    averageCost: '平均成本',
    pnl: '已实现 / 未实现损益',
    fees: '累计成交费用',
    fills: '模拟成交与费用',
    noFills: '尚无模拟成交。',
    session: '交易日',
    side: '方向',
    buy: '买入',
    sell: '卖出',
    price: '成交价',
    fee: '成交费用（含税费）',
    slippage: '滑点成本',
    attempts: '逐次执行结果与阻断',
    noAttempts: '尚无执行尝试。',
    status: '结果',
    statuses: { filled: '已成交', blocked: '本次阻断', no_order: '未生成订单' },
    reason: '原因 / 稳定代码',
    publication: '来源目标发布',
    history: '结算记录与净资产',
    provenance: '账本来源、冻结成本与模型限制',
    frozenCosts: '本账本冻结的有效成本',
    corporateActions: '税前分红送转入账明细',
    started: '创建时间',
    evaluationStart: '开始评估日',
    limitations: '记录的模型限制',
  },
  en: {
    title: 'Independent paper book',
    detail:
      'Separate simulated cash, positions, fills and net asset value alongside the target-only shadow above. Only targets actually published after this book was created are eligible; no historical trades are invented.',
    boundary:
      'Manual settlement only. Observation automation grants no permission to this book; real account records and capital authority are unchanged. Daily-bar fills and provider-reported gross distributions do not establish actual execution, complete historical knowledge or guaranteed returns.',
    initialCash: 'Initial simulated cash (CNY)',
    create: 'Create independent paper book',
    createHint:
      'One book per observation. Initial cash and costs are frozen at creation; use a new observation to change them or start again.',
    costs:
      'Costs apply only to this new independent paper book. Stock commission, minimum commission and slippage may be overridden; the server freezes other fees from its model.',
    defaultCosts:
      'Use built-in server costs and zero slippage. Frozen effective rates are available after creation.',
    unsupported:
      'Independent paper books currently support standard A-share stocks only; this observation contains an unsupported instrument.',
    refresh: 'Refresh paper book',
    loading: 'Reading the saved paper book…',
    loadFailed:
      'Could not read the paper book. Refresh before acting; any displayed snapshot is not freshly confirmed.',
    saving: 'Saving paper book…',
    saved: 'Paper book saved.',
    active: 'Accepting newly published targets',
    paused: 'New target intake stopped',
    pause: 'Stop accepting new targets',
    pauseHint:
      'Intake cannot be resumed. This does not liquidate positions. Previously accepted targets and existing positions can still be settled manually; start a new observation to begin again.',
    dataset: 'Formal Dataset for paper settlement',
    choose: 'Choose a saved Dataset',
    refreshDatasets: 'Refresh paper Dataset choices',
    datasetHint:
      'Lists matching source start dates and stock universes marked with cross-source verification and distribution evidence. The server still checks the latest closed session, complete history prefix and evidence. Use the existing research data preparation flow to supply missing data.',
    datasetFailed: 'Could not read Dataset choices. Refresh before settlement.',
    noDatasets:
      'No matching formal Dataset. Prepare and verify research data, then bind distribution evidence through the existing flow.',
    settle: 'Settle paper book manually',
    snapshot: 'Saved book snapshot',
    asOf: 'As of settled session',
    notSettled: 'Not settled; initial cash only',
    unchanged:
      'This operation was not confirmed. The previous saved snapshot and its settlement date remain below. Refresh to confirm before acting again.',
    cash: 'Cash (CNY)',
    equity: 'Net asset value (CNY)',
    receivable: 'Gross dividends receivable (CNY)',
    income: 'Cumulative gross dividend income (CNY)',
    positions: 'Positions',
    noPositions: 'No positions.',
    symbol: 'Symbol',
    quantity: 'Total quantity',
    available: 'Available / frozen / unlisted',
    marketValue: 'Market value (CNY)',
    averageCost: 'Average cost',
    pnl: 'Realized / unrealized P&L',
    fees: 'Accumulated execution fees',
    fills: 'Simulated fills and costs',
    noFills: 'No simulated fills yet.',
    session: 'Session',
    side: 'Side',
    buy: 'Buy',
    sell: 'Sell',
    price: 'Fill price',
    fee: 'Execution fees (including taxes)',
    slippage: 'Slippage cost',
    attempts: 'Individual execution outcomes and blockers',
    noAttempts: 'No execution attempts yet.',
    status: 'Outcome',
    statuses: {
      filled: 'Filled',
      blocked: 'Attempt blocked',
      no_order: 'No order',
    },
    reason: 'Reason / stable code',
    publication: 'Source target publication',
    history: 'Settlements and net asset value',
    provenance: 'Book provenance, frozen costs and model limits',
    frozenCosts: 'Effective costs frozen for this book',
    corporateActions: 'Gross distribution accounting details',
    started: 'Created',
    evaluationStart: 'Evaluation start',
    limitations: 'Recorded model limits',
  },
};

export function paperAttemptReason(reason: string | null, locale: 'zh' | 'en') {
  const descriptions: Record<string, [string, string]> = {
    limit: [
      '涨跌停约束阻断本次成交，不自动补单。',
      'Price-limit constraint blocked this attempt; no automatic retry.',
    ],
    suspension: [
      '停牌或无成交量，本次不成交。',
      'Suspended or no trading volume; this attempt did not fill.',
    ],
    corporate_action_price_limit_reference_missing: [
      '除权日缺少官方涨跌停参考，阻断本次成交。',
      'Missing official ex-date price-limit reference; this attempt did not fill.',
    ],
    target_sizing_no_order: [
      '按目标及交易约束计算后未生成订单。',
      'Target sizing and trading constraints produced no order.',
    ],
  };
  return reason ? descriptions[reason]?.[locale === 'zh' ? 0 : 1] : undefined;
}

export function paperBookError(error: unknown, locale: 'zh' | 'en') {
  const code = error instanceof Error ? error.message : String(error);
  const zh = locale === 'zh';
  let message = zh
    ? '操作未确认成功，请刷新账本状态并检查数据与服务。'
    : 'The operation was not confirmed. Refresh the book and check the data and service.';
  if (/settled_prefix_conflict/.test(code))
    message = zh
      ? '新数据会改写已经结算的历史账务，本次结算已阻断。请检查数据或分红送转修订；已保存账本保留。'
      : 'New evidence would rewrite previously settled accounting. Settlement is blocked. Review data or distribution revisions; the saved book is retained.';
  else if (/version_conflict|request_conflict|already_exists/.test(code))
    message = zh
      ? '账本版本或历史记录已变化，本次操作不会自动重试。请刷新后确认。'
      : 'The book version or history changed. This operation will not retry automatically. Refresh to review it.';
  else if (/code.*changed|code.*mismatch/.test(code))
    message = zh
      ? '代码版本与冻结来源不同，当前账本不能继续结算。请核对版本后另起观察。'
      : 'Code differs from the frozen source. This book cannot continue settlement; review the version and start a new observation.';
  else if (/corporate_action|distribution/.test(code))
    message = zh
      ? '分红送转报告证据缺失、冲突或不可用。请通过研究数据准备流程检查报告并绑定可用证据后重试。'
      : 'Distribution evidence is missing, conflicting or unusable. Review and bind usable reports through research data preparation before retrying.';
  else if (/no_new|not_closed|latest_closed/.test(code))
    message = zh
      ? '没有新的可结算收盘交易日，或 Dataset 尚未覆盖最新已收盘日。请准备完整区间后再结算。'
      : 'No new closed session can be settled, or the Dataset does not reach the latest closed session. Prepare the complete range first.';
  else if (/dataset|verified|prefix|history/.test(code))
    message = zh
      ? '正式 Dataset、双源核验或历史账务前缀不满足要求。请在研究数据准备流程检查完整区间与证据；已保存账本保留。'
      : 'The formal Dataset, cross-source verification or accounting history prefix is not acceptable. Check the complete range and evidence in research data preparation; the saved book is retained.';
  else if (/instrument_unsupported/.test(code))
    message = paperBookCopy[locale].unsupported;
  return { message, code };
}
