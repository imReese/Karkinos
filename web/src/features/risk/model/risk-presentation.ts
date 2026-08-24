import {
  formatCurrency as formatCurrencyValue,
  formatTimestamp,
} from '../../../shared/format';
import type { AppCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import {
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';

export function formatRiskCurrency(value: number) {
  return formatCurrencyValue(value);
}

export function formatRiskAuditTimestamp(timestamp: string) {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }

  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}

export function getRiskEventKindLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'cash_deposit':
      return copy.explainability.deposits;
    case 'cash_withdrawal':
      return copy.explainability.withdrawals;
    case 'dividend':
      return copy.explainability.dividends;
    case 'trade_buy':
      return copy.explainability.buys;
    case 'trade_sell':
      return copy.explainability.sells;
    case 'manual_adjustment':
      return copy.explainability.adjustments;
    default:
      return value;
  }
}

export function getRiskEventCategoryLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'capital':
      return copy.explainability.categoryCapital;
    case 'income':
      return copy.explainability.categoryIncome;
    case 'override':
      return copy.explainability.categoryOverride;
    case 'trade':
      return copy.explainability.categoryTrade;
    default:
      return value;
  }
}

export function getRiskImpactSourceLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'external':
      return copy.explainability.sourceExternal;
    case 'cash':
      return copy.explainability.sourceCash;
    case 'manual':
      return copy.explainability.sourceManual;
    case 'positioning':
      return copy.explainability.sourcePositioning;
    default:
      return value;
  }
}

export function getRiskMetricLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'current_drawdown':
      return copy.riskPage.currentDrawdown;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdown;
    case 'gross_exposure':
      return copy.riskPage.grossExposure;
    case 'cash_ratio':
      return copy.riskPage.cashRatio;
    case 'largest_weight':
      return copy.riskPage.largestPosition;
    case 'top3_weight':
      return copy.riskPage.top3Concentration;
    default:
      return value;
  }
}

export function getRiskMetricDetail(copy: AppCopy, value: string) {
  switch (value) {
    case 'current_drawdown':
      return copy.riskPage.currentDrawdownDetail;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdownDetail;
    case 'gross_exposure':
      return copy.riskPage.grossExposureDetail;
    case 'cash_ratio':
      return copy.riskPage.cashRatioDetail;
    case 'largest_weight':
      return copy.riskPage.largestPositionDetail;
    case 'top3_weight':
      return copy.riskPage.top3ConcentrationDetail;
    default:
      return value;
  }
}

export function getRiskAlertKindLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'risk':
      return copy.overview.risk.registerKicker;
    case 'cash_buffer':
      return copy.overview.risk.cashBuffer;
    case 'concentration':
    case 'largest_weight':
      return copy.overview.risk.concentration;
    case 'gross_exposure':
    case 'capital_deployment':
      return copy.overview.risk.deployment;
    case 'current_drawdown':
      return copy.riskPage.currentDrawdown;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdown;
    case 'market_data':
    case 'data':
      return copy.decision.marketData;
    case 'manual_confirmation':
      return copy.overview.risk.manualConfirmationRequired;
    default:
      return value;
  }
}

export function formatRiskAlertDetail(value: string, locale: Locale) {
  const concentration = /^(.+)\s+占总资产\s+([\d.]+%)$/u.exec(value.trim());
  if (concentration) {
    const [, instrument, weight] = concentration;
    return locale === 'zh'
      ? value
      : `${instrument} accounts for ${weight} of total equity.`;
  }
  const cashBuffer = /^当前现金占比\s+([\d.]+%)，可用调仓空间有限$/u.exec(
    value.trim(),
  );
  if (cashBuffer) {
    const [, ratio] = cashBuffer;
    return locale === 'zh'
      ? value
      : `Cash is ${ratio} of total equity; rebalance capacity is limited.`;
  }
  const quoteTimestamp = /^(\S+)\s+最新快照时间\s+(.+)$/u.exec(value.trim());
  if (quoteTimestamp) {
    const [, symbol, timestamp] = quoteTimestamp;
    return locale === 'zh'
      ? `${symbol} 最新行情截至 ${formatTimestamp(timestamp)}`
      : `${symbol} quote evidence as of ${formatTimestamp(timestamp)}`;
  }
  return formatPublicNote(value, locale);
}

export function formatRiskAlertTitle(value: string, locale: Locale) {
  if (locale === 'zh') {
    return value;
  }
  const labels: Record<string, string> = {
    仓位集中度偏高: 'Position concentration is elevated',
    现金缓冲偏低: 'Cash buffer is low',
    行情数据可能过旧: 'Market quote evidence may be stale',
    当前风险可控: 'Current risk is manageable',
  };
  return labels[value.trim()] ?? formatPublicNote(value, locale);
}

export function formatRiskNextStep(value: string, locale: Locale) {
  if (locale === 'zh') {
    return value;
  }
  const labels: Record<string, string> = {
    确认待执行建议: 'Review pending recommendations before any execution.',
    继续观察市场: 'Continue monitoring the market.',
  };
  return labels[value.trim()] ?? formatPublicNote(value, locale);
}

export function formatRiskAlertLevel(level: string, locale: Locale) {
  const normalized = level.trim().toLowerCase();
  if (normalized === 'medium') {
    return formatPublicStatus('warning', locale);
  }
  if (normalized === 'high') {
    return formatPublicStatus('blocked', locale);
  }
  if (normalized === 'low') {
    return formatPublicStatus('healthy', locale);
  }
  return formatPublicStatus(level, locale);
}

export function getRiskBucketLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'heavy':
      return copy.riskPage.bucketHeavy;
    case 'core':
      return copy.riskPage.bucketCore;
    case 'starter':
      return copy.riskPage.bucketStarter;
    case 'small':
      return copy.riskPage.bucketSmall;
    case 'cash':
      return copy.riskPage.bucketCash;
    default:
      return value;
  }
}
