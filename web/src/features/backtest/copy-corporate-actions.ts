export const corporateActionCopy = {
  zh: {
    title: '分红送转证据',
    observed: '已采集 · 覆盖未核实',
    notEvaluated: '未评估',
    missing: '尚无可用的分红送转证据；不能据此判断区间内没有公司行动。',
    collect: '采集分红送转证据',
    refresh: '重新采集分红送转证据',
    pending: '正在采集分红送转证据…',
    actionScope:
      '仅在点击后请求 Tushare，可能消耗数据积分。采集后选中新数据集，原数据集和已有回测结果保留。',
    unsupported: '目前仅支持股票数据集；ETF 等品种的分红送转证据尚不支持。',
    success: '分红送转证据已采集，已选中新数据集。请重新运行回测查看对应报告。',
    reused: '已选择包含现有分红送转证据的数据集。',
    total: '供应商返回记录',
    matched: '区间命中记录',
    undated: '日期不足的记录',
    source: '证据来源',
    observedAt: '本次采集可用时间',
    details: (count: number) => `查看记录明细（${count}）`,
    events: '分红送转记录明细',
    eventBoundary:
      '分配进度保留来源原文，事件日期不代表已到账。未知字段不会被补成已实施或已支付。',
    unknown: '未知',
    symbol: '标的',
    progress: '分配进度（原文）',
    announcement: '公告日',
    implementation: '实施公告日',
    recordDate: '登记日',
    exDate: '除权除息日',
    payDate: '派息日',
    listingDate: '红股上市日',
    cashBeforeTax: '每股现金（税前）',
    bonusTotal: '每股送转',
    bonusShares: '每股送股',
    capitalizedShares: '每股转增',
    coverage:
      '仅覆盖供应商返回的现金分红与送转记录，尚未证明区间事件完整，配股等其他公司行动不在本次范围内。',
    zeroMatches: '本次没有命中区间的记录；这不证明区间内没有公司行动。',
    availability:
      '公告日和实施公告日不证明整条记录当时已知；本次采集不补足历史时点可用性。',
    returns:
      '证据尚未计入现金派息、送转持仓或总收益；回测仍是未复权价格下的模拟权益收益。',
  },
  en: {
    title: 'Dividend and bonus-share evidence',
    observed: 'Collected · coverage unverified',
    notEvaluated: 'Not evaluated',
    missing:
      'No usable dividend or bonus-share evidence is attached. This does not establish that the interval had no corporate actions.',
    collect: 'Collect dividend and bonus-share evidence',
    refresh: 'Refresh dividend and bonus-share evidence',
    pending: 'Collecting dividend and bonus-share evidence…',
    actionScope:
      'Only this action contacts Tushare and may use data credits. It selects a new dataset while preserving the original and existing backtest results.',
    unsupported:
      'Only stock datasets are supported. Dividend and bonus-share evidence for ETFs and other instruments is not supported yet.',
    success:
      'Evidence collected and the new dataset selected. Run the backtest again to view its report.',
    reused:
      'The dataset with existing dividend and bonus-share evidence is selected.',
    total: 'Provider records',
    matched: 'Records matching the interval',
    undated: 'Records with insufficient dates',
    source: 'Evidence source',
    observedAt: 'Available from this collection',
    details: (count: number) => `View record details (${count})`,
    events: 'Dividend and bonus-share records',
    eventBoundary:
      'Distribution progress is shown as reported. Event dates do not confirm receipt; unknown fields are not treated as implemented or paid.',
    unknown: 'Unknown',
    symbol: 'Symbol',
    progress: 'Progress (as reported)',
    announcement: 'Announcement date',
    implementation: 'Implementation announcement',
    recordDate: 'Record date',
    exDate: 'Ex-dividend date',
    payDate: 'Pay date',
    listingDate: 'Bonus-share listing date',
    cashBeforeTax: 'Cash per share (before tax)',
    bonusTotal: 'Bonus shares per share',
    bonusShares: 'Stock dividend per share',
    capitalizedShares: 'Capitalization per share',
    coverage:
      'Only provider-reported cash dividends and bonus shares are covered. Completeness is unverified; rights issues and other corporate actions are outside this scope.',
    zeroMatches:
      'No records matched this interval. This does not establish that no corporate actions occurred.',
    availability:
      'Announcement dates do not establish when every field was known. This collection does not verify historical point-in-time availability.',
    returns:
      'Cash dividends, bonus-share holdings and total return are not modeled. Backtest returns remain simulated equity returns using unadjusted prices.',
  },
};
