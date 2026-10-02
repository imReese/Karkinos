import type { Locale } from '../../shared/locale';

export const cashDividendCopy = {
  zh: {
    mode: '公司行动收益处理',
    priceOnly: '仅价格（默认）',
    gross: '计入税前现金分红',
    requiresEvidence:
      '选中已采集分红送转证据的股票数据集后，可选择税前现金分红模式。',
    modeDetail:
      '税前现金模式按登记日持仓确认分红，除息日计入应收与权益，派息日才增加可用现金。仅支持日期完整的已实施现金分红；送转、缺失日期或未实施记录会阻止运行。',
    advancedDisabled:
      '参数扫描与策略对比目前仅支持价格模式。请切换为“仅价格”后使用，避免混用收益口径。',
    title: '本次税前现金分红核算',
    income: '已确认税前分红收入',
    paid: '已转为可用现金',
    receivable: '尚未支付的应收分红',
    cashDetail:
      '应收分红已计入权益，但尚不能用于买入；已付现金包含在分红收入中，不重复增加收益。',
    returns:
      '本次模拟权益已计入税前现金分红；未计入个人税负和送转，不代表完整税后经济收益。',
    limitations:
      '仅核算来源已报告的现金分红。个人税负、到账舍入和送转未建模；来源完整性与历史信息可得时间未核实。',
    exDate: (count: number) =>
      `除息日缺少官方涨跌停参考价，相关交易已阻止 ${count} 次。`,
    evidenceOnly: '这里展示来源记录；收益处理取决于本次回测选择的模式。',
    failed: '现金分红核算无法进行，请检查分红记录、交易日期与所选数据集。',
  },
  en: {
    mode: 'Corporate-action return treatment',
    priceOnly: 'Price only (default)',
    gross: 'Include gross cash dividends',
    requiresEvidence:
      'Select a stock dataset with collected corporate-action evidence to enable gross cash dividends.',
    modeDetail:
      'Gross cash mode uses record-date holdings, recognizes receivables and equity on the ex-date, and makes cash available on the pay date. Only implemented cash distributions with complete dates are supported; bonus shares, missing dates or unimplemented records block the run.',
    advancedDisabled:
      'Parameter sweeps and comparisons currently support price-only returns. Select “Price only” before using them.',
    title: 'Cash dividend accounting for this run',
    income: 'Recognized gross dividend income',
    paid: 'Paid into available cash',
    receivable: 'Unpaid dividend receivable',
    cashDetail:
      'Receivables are included in equity but cannot fund purchases. Paid cash is part of dividend income, not additional return.',
    returns:
      'Simulated equity includes gross cash dividends. Investor tax and bonus shares are excluded; this is not total after-tax economic return.',
    limitations:
      'Only provider-reported cash dividends are modeled. Investor tax, payment rounding and bonus shares are omitted; source completeness and historical information availability remain unverified.',
    exDate: (count: number) =>
      `${count} ex-date trades blocked because an official price-limit reference was unavailable.`,
    evidenceOnly:
      'These are source records. Return treatment depends on the mode selected for this run.',
    failed:
      'Cash dividend accounting is unavailable. Check the distribution records, trading dates and selected dataset.',
  },
};

const cashDividendErrors: Record<string, string> = {
  cash_dividend_dataset_required: '请先选择已采集分红证据的股票数据集。',
  cash_dividend_evidence_required: '所选数据集没有可用的现金分红证据。',
  cash_dividend_event_dates_incomplete:
    '分红记录缺少登记日、除息日或派息日，无法核算。',
  cash_dividend_implemented_stock_required:
    '仅支持已实施的股票现金分红；请检查记录的分配进度。',
  cash_dividend_share_terms_missing:
    '送转比例缺失，无法确认该记录仅含现金分红。',
  cash_dividend_share_distribution_unsupported:
    '本模式尚不支持送股或转增，请使用仅价格模式查看探索性结果。',
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
  const code = error.message.match(/\bcash_dividend_[a-z_]+\b/)?.[0];
  if (!code) return null;
  return locale === 'zh'
    ? (cashDividendErrors[code] ?? cashDividendCopy.zh.failed)
    : cashDividendCopy.en.failed;
}
