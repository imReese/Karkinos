import type { Locale } from '../../shared/locale';

export const cashDividendCopy = {
  zh: {
    mode: '公司行动收益处理',
    priceOnly: '仅价格（默认）',
    gross: '计入税前现金分红',
    reported: '计入税前现金与整股送转',
    requiresEvidence:
      '选中已采集分红送转证据的股票数据集后，可选择现金分红或整股送转模式。',
    modeDetail:
      '税前现金模式按登记日持仓确认分红，除息日计入应收与权益，派息日才增加可用现金。仅支持日期完整的已实施现金分红；送转、缺失日期或未实施记录会阻止运行。',
    reportedDetail:
      '按登记日持仓核算税前现金与整股送转；新增股份在除权日计入持仓，上市前不可卖。只支持条款完整的已实施分配，零碎股份会阻止运行。策略特征仍使用未复权价格，除权日缺少官方涨跌停参考价时阻止交易。',
    title: '本次税前现金分红核算',
    reportedTitle: '本次现金分红与送转核算',
    shares: '新增股份合计（股）',
    unlisted: '其中待上市股份（股）',
    sharesDetail:
      '新增股份是持仓数量变化，不是现金收入；待上市股份计入持仓价值，但暂不可卖。',
    shareRecords: '送转股份明细',
    symbol: '标的',
    sharesPerShare: '每股送转比例',
    shareQuantity: '新增股份（股）',
    recordDate: '登记日',
    exDateColumn: '除权日',
    listingDate: '上市日',
    shareStatus: '股份状态',
    listed: '已上市',
    notListed: '待上市 · 暂不可卖',
    unknown: '未知',
    income: '已确认税前分红收入',
    paid: '已转为可用现金',
    receivable: '尚未支付的应收分红',
    cashDetail:
      '应收分红已计入权益，但尚不能用于买入；已付现金包含在分红收入中，不重复增加收益。',
    returns:
      '本次模拟权益已计入税前现金分红；未计入个人税负和送转，不代表完整税后经济收益。',
    reportedReturns:
      '本次模拟权益已计入税前现金与整股送转；新增股份不作为现金收入，未计个人税负，不代表完整税后经济收益。',
    limitations:
      '仅核算来源已报告的现金分红。个人税负、到账舍入和送转未建模；来源完整性与历史信息可得时间未核实。',
    reportedLimitations:
      '仅核算来源已报告的现金与整股送转。个人税负、到账舍入和零碎股份分配未建模；来源完整性与历史信息可得时间未核实。策略特征仍使用未复权价格。',
    exDate: (count: number) =>
      `除权除息日缺少官方涨跌停参考价，相关交易已阻止 ${count} 次。`,
    evidenceOnly: '这里展示来源记录；收益处理取决于本次回测选择的模式。',
    failed: '分红送转核算无法进行，请检查分配条款、交易日期与所选数据集。',
  },
  en: {
    mode: 'Corporate-action return treatment',
    priceOnly: 'Price only (default)',
    gross: 'Include gross cash dividends',
    reported: 'Include gross cash and whole bonus shares',
    requiresEvidence:
      'Select a stock dataset with collected corporate-action evidence to enable cash dividends or whole bonus shares.',
    modeDetail:
      'Gross cash mode uses record-date holdings, recognizes receivables and equity on the ex-date, and makes cash available on the pay date. Only implemented cash distributions with complete dates are supported; bonus shares, missing dates or unimplemented records block the run.',
    reportedDetail:
      'Record-date holdings determine gross cash and whole bonus shares. Shares enter holdings on the ex-date and cannot be sold before listing. Only implemented distributions with complete terms are supported; fractional awards block the run. Strategy features still use unadjusted prices, and ex-date trades are blocked without an official price-limit reference.',
    title: 'Cash dividend accounting for this run',
    reportedTitle: 'Cash and bonus-share accounting for this run',
    shares: 'Total shares awarded (shares)',
    unlisted: 'Of which awaiting listing (shares)',
    sharesDetail:
      'Share awards change holdings, not cash income. Unlisted shares contribute to holding value but cannot be sold yet.',
    shareRecords: 'Bonus-share details',
    symbol: 'Symbol',
    sharesPerShare: 'Shares awarded per share',
    shareQuantity: 'Shares awarded',
    recordDate: 'Record date',
    exDateColumn: 'Ex-date',
    listingDate: 'Listing date',
    shareStatus: 'Share status',
    listed: 'Listed',
    notListed: 'Unlisted · not sellable',
    unknown: 'Unknown',
    income: 'Recognized gross dividend income',
    paid: 'Paid into available cash',
    receivable: 'Unpaid dividend receivable',
    cashDetail:
      'Receivables are included in equity but cannot fund purchases. Paid cash is part of dividend income, not additional return.',
    returns:
      'Simulated equity includes gross cash dividends. Investor tax and bonus shares are excluded; this is not total after-tax economic return.',
    reportedReturns:
      'Simulated equity includes gross cash and whole bonus shares. Share awards are not cash income, and investor tax is omitted; this is not total after-tax economic return.',
    limitations:
      'Only provider-reported cash dividends are modeled. Investor tax, payment rounding and bonus shares are omitted; source completeness and historical information availability remain unverified.',
    reportedLimitations:
      'Only provider-reported cash and whole bonus shares are modeled. Investor tax, payment rounding and fractional-share allocation are omitted; source completeness and historical information availability remain unverified. Strategy features still use unadjusted prices.',
    exDate: (count: number) =>
      `${count} ex-date trades blocked because an official price-limit reference was unavailable.`,
    evidenceOnly:
      'These are source records. Return treatment depends on the mode selected for this run.',
    failed:
      'Distribution accounting is unavailable. Check the distribution terms, trading dates and selected dataset.',
  },
};

const cashDividendErrors: Record<string, string> = {
  cash_dividend_dataset_required: '请先选择已采集分红证据的股票数据集。',
  cash_dividend_evidence_required: '所选数据集没有可用的现金分红证据。',
  cash_dividend_event_dates_incomplete:
    '分配记录缺少本模式所需的日期，请检查登记日、除权除息日及适用的派息或上市日。',
  cash_dividend_implemented_stock_required:
    '仅支持已实施的股票现金分红；请检查记录的分配进度。',
  cash_dividend_share_terms_missing: '分配记录缺少送转比例，无法核算。',
  cash_dividend_share_distribution_unsupported:
    '现金模式不支持送股或转增；可选择“计入税前现金与整股送转”并核对完整条款。',
  share_distribution_terms_conflicting:
    '送转总比例与送股、转增比例之和不一致，无法核算。',
  share_distribution_terms_invalid: '送转比例无效或为负数，无法核算。',
  portfolio_share_distribution_fractional_unsupported:
    '本次送转产生零碎股份，尚不支持其分配处理，回测已停止。',
  portfolio_share_distribution_quantity_invalid: '送转股份数量无效，无法核算。',
  cash_dividend_conflicting_implementation:
    '同一分配存在冲突的实施记录，无法重复计入。',
  cash_dividend_gross_amount_missing: '分红记录缺少每股税前现金金额。',
  cash_dividend_gross_amount_invalid: '分红记录的每股税前现金金额无效。',
  cash_dividend_terms_invalid: '分红条款或日期顺序无效，无法核算。',
  cash_dividend_duplicate_action: '存在重复的分红事件，无法重复计入收益。',
  cash_dividend_daily_close_required:
    '现金分红核算需要每日收盘数据及明确时区。',
  cash_dividend_bars_required: '现金分红核算缺少行情数据。',
  cash_dividend_symbol_missing: '分红标的与行情数据不匹配。',
  cash_dividend_required_session_missing:
    '登记日或除息日的行情缺失，无法核算。',
  cash_dividend_historical_availability_unverified:
    '无法证明分红条款在历史决策时已经可得。',
};

export function cashDividendErrorMessage(
  error: unknown,
  locale: Locale,
): string | null {
  if (!(error instanceof Error)) return null;
  const code = error.message.match(
    /\b(?:cash_dividend|share_distribution|portfolio_share_distribution)_[a-z_]+\b/,
  )?.[0];
  if (!code) return null;
  return locale === 'zh'
    ? (cashDividendErrors[code] ?? cashDividendCopy.zh.failed)
    : cashDividendCopy.en.failed;
}
