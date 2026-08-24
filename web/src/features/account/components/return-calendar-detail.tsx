import type { AppCopy } from '../../../shared/i18n/context';
import {
  formatReturnCalendarDetailTitle,
  formatReturnCurrency,
  formatReturnPercent,
  type ReturnCalendarBreakdownItem,
  type ReturnCalendarMetric,
  type ReturnCalendarPeriod,
  type ReturnCalendarRow,
} from './return-calendar-model';

export function ReturnCalendarDetail({
  row,
  period,
  metric,
  copy,
  compact,
}: {
  row: ReturnCalendarRow | null;
  period: ReturnCalendarPeriod;
  metric: ReturnCalendarMetric;
  copy: AppCopy;
  compact: boolean;
}) {
  const detailClass = compact
    ? 'rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-3'
    : 'rounded-lg border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-4';

  if (row === null) {
    return (
      <div
        className={`${compact ? 'rounded-md p-3' : 'rounded-lg p-4'} border border-dashed border-[var(--app-border)] text-sm text-[var(--app-muted)]`}
      >
        {copy.explainability.timelineEmpty}
      </div>
    );
  }

  const hasMissingValuation = row.valuationStatus === 'missing';
  const hasUnconfirmedValuation = row.valuationStatus === 'partial';
  const returnValue = hasMissingValuation
    ? copy.explainability.missingValuationShort
    : metric === 'amount'
      ? formatReturnCurrency(row.delta)
      : formatReturnPercent(row.percentChange);
  const marketValue = hasMissingValuation
    ? copy.explainability.missingValuationShort
    : formatReturnCurrency(row.marketPnl);
  const detailTitle = formatReturnCalendarDetailTitle(row, period, copy);
  const netChangeLabel =
    period === 'day'
      ? copy.explainability.netChangeDaily
      : period === 'week'
        ? copy.explainability.netChangeWeekly
        : period === 'month'
          ? copy.explainability.netChangeMonthly
          : copy.explainability.netChangeAnnual;

  return (
    <div className={detailClass}>
      <div className="app-kicker app-type-overline">
        {copy.explainability.selectedPeriod}
      </div>
      <div
        className={`${compact ? 'mt-1 text-base' : 'mt-2 text-lg'} font-semibold`}
      >
        {detailTitle}
      </div>
      <div
        className={`${compact ? 'mt-3 space-y-2' : 'mt-4 space-y-3'} text-sm`}
      >
        <CalendarDetailMetric label={netChangeLabel} value={returnValue} />
        <CalendarDetailMetric
          label={copy.explainability.marketPnl}
          value={marketValue}
        />
        {row.marketBreakdown.length > 0 ? (
          <CalendarDetailBreakdown
            items={row.marketBreakdown}
            labelForKey={(item) =>
              copy.explainability.marketBreakdownLabels[
                item.key as keyof typeof copy.explainability.marketBreakdownLabels
              ] ?? item.label
            }
          />
        ) : null}
        <CalendarDetailMetric
          label={copy.explainability.externalFlow}
          value={formatReturnCurrency(row.externalFlow)}
        />
        {row.externalFlowBreakdown.length > 0 ? (
          <CalendarDetailBreakdown
            items={row.externalFlowBreakdown}
            labelForKey={(item) =>
              copy.explainability.externalFlowBreakdownLabels[
                item.key as keyof typeof copy.explainability.externalFlowBreakdownLabels
              ] ?? item.label
            }
          />
        ) : null}
        {hasMissingValuation || hasUnconfirmedValuation ? (
          <CalendarDetailMetric
            label={copy.explainability.valuationCoverage}
            value={
              hasMissingValuation && row.missingPriceSymbols.length > 0
                ? `${copy.explainability.missingHistoricalPrices}: ${row.missingPriceSymbols.join(', ')}`
                : copy.explainability.partialValuation
            }
          />
        ) : null}
      </div>
    </div>
  );
}

function CalendarDetailMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-[var(--app-border)] pt-3 first:border-t-0 first:pt-0">
      <span className="app-muted">{label}</span>
      <span className="text-right font-semibold">{value}</span>
    </div>
  );
}

function CalendarDetailBreakdown({
  items,
  labelForKey,
}: {
  items: ReturnCalendarBreakdownItem[];
  labelForKey: (item: ReturnCalendarBreakdownItem) => string;
}) {
  return (
    <div className="space-y-2 border-t border-[var(--app-border)] pt-3">
      {items.map((item) => (
        <div
          key={item.key}
          className="flex items-center justify-between gap-3 text-xs"
        >
          <span className="app-muted">{labelForKey(item)}</span>
          <span className="text-right font-semibold">
            {formatReturnCurrency(item.value)}
          </span>
        </div>
      ))}
    </div>
  );
}
