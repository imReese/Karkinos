function resolveLocale() {
  return typeof document !== 'undefined' &&
    document.documentElement.lang.startsWith('zh')
    ? 'zh-CN'
    : 'en-US';
}

function finiteNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function formatCurrency(
  value: number | null | undefined,
  options: Intl.NumberFormatOptions = {},
) {
  const normalized = finiteNumber(value);
  if (normalized === null) {
    return '--';
  }
  return new Intl.NumberFormat(resolveLocale(), {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    ...options,
  }).format(normalized);
}

export function formatAmount(value: number | null | undefined) {
  const normalized = finiteNumber(value);
  if (normalized === null) {
    return '--';
  }
  return new Intl.NumberFormat(resolveLocale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(normalized);
}

export function formatPrice(value: number | null | undefined) {
  const normalized = finiteNumber(value);
  if (normalized === null) {
    return '--';
  }
  return new Intl.NumberFormat(resolveLocale(), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(normalized);
}

export function formatQuantity(value: number | null | undefined) {
  const normalized = finiteNumber(value);
  if (normalized === null) {
    return '--';
  }
  return new Intl.NumberFormat(resolveLocale(), {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  }).format(normalized);
}

export function formatPercent(
  value: number | null | undefined,
  options: Intl.NumberFormatOptions = {},
) {
  const normalized = finiteNumber(value);
  if (normalized === null) {
    return '--';
  }
  return new Intl.NumberFormat(resolveLocale(), {
    style: 'percent',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    ...options,
  }).format(normalized);
}

export function formatTimestamp(value: string | null | undefined) {
  if (!value) {
    return '--';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(resolveLocale(), {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(date);
}
