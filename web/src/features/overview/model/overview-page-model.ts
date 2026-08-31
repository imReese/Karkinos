import { getErrorMessage } from '../../../shared/error-message';
import type { AppCopy } from '../../../shared/i18n/context';
import { explainMarketCalendarDate } from '../../../shared/market-calendar';
import type { MarketCalendarSnapshot } from '../overview-feature-boundary';

export type OverviewAnalysisView =
  'performance' | 'allocation' | 'attribution' | 'calendar';

export function formatShanghaiDateKey(value: Date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).formatToParts(value);
  const byType = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${byType.year ?? '0000'}-${byType.month ?? '00'}-${byType.day ?? '00'}`;
}

export function isTradingDayForOverviewPnl(
  calendar: Pick<MarketCalendarSnapshot, 'days'> | null | undefined,
  dateText: string,
) {
  const calendarDay = calendar?.days.find((day) => day.date === dateText);
  if (calendarDay) {
    return calendarDay.is_trading_day;
  }
  return explainMarketCalendarDate(dateText).isTradingDay;
}

export function getEquityCurveErrorDetail(error: unknown, copy: AppCopy) {
  const detail = getErrorMessage(error);
  if (
    detail.includes(
      'Current valuation facts have not been published as an immutable snapshot',
    )
  ) {
    return copy.overview.curveSnapshotPending;
  }
  return `${copy.overview.curveError} ${detail}`;
}
