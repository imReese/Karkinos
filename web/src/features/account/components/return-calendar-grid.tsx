import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import {
  explainMarketCalendarDate,
  type MarketCalendarDay,
} from '../../../shared/market-calendar';
import {
  buildReturnWeekSlots,
  formatCompactReturnCurrency,
  formatReturnCurrency,
  formatReturnPercent,
  formatReturnWeekHeading,
  type ReturnCalendarMetric,
  type ReturnCalendarPeriod,
  type ReturnCalendarRow,
} from './return-calendar-model';

export function ReturnCalendarGrid({
  rows,
  period,
  activeMonth,
  activeYear,
  metric,
  copy,
  compact,
  selectedLabel,
  onSelect,
  marketCalendarDays,
}: {
  rows: ReturnCalendarRow[];
  period: ReturnCalendarPeriod;
  activeMonth: string;
  activeYear: string;
  metric: ReturnCalendarMetric;
  copy: AppCopy;
  compact: boolean;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
  marketCalendarDays: Map<string, MarketCalendarDay>;
}) {
  const maxMagnitude = Math.max(
    ...rows.map((row) =>
      Math.abs(metric === 'amount' ? row.marketPnl : row.percentChange),
    ),
    0.0001,
  );

  if (period === 'day') {
    return (
      <ReturnMonthGrid
        rows={rows}
        activeMonth={activeMonth}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
        marketCalendarDays={marketCalendarDays}
      />
    );
  }

  if (period === 'week') {
    return (
      <ReturnWeekGrid
        rows={rows}
        activeYear={activeYear}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
      />
    );
  }

  if (period === 'month') {
    return (
      <ReturnYearGrid
        rows={rows}
        activeYear={activeYear}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
      />
    );
  }

  return (
    <ReturnYearsGrid
      rows={rows}
      metric={metric}
      compact={compact}
      maxMagnitude={maxMagnitude}
      selectedLabel={selectedLabel}
      onSelect={onSelect}
    />
  );
}

function ReturnMonthGrid({
  rows,
  activeMonth,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
  marketCalendarDays,
}: {
  rows: ReturnCalendarRow[];
  activeMonth: string;
  metric: ReturnCalendarMetric;
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
  marketCalendarDays: Map<string, MarketCalendarDay>;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  const firstDay = new Date(`${activeMonth}-01T00:00:00`);
  const month = firstDay.getMonth();
  const year = firstDay.getFullYear();
  const leadingBlanks = firstDay.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [
    ...Array.from({ length: leadingBlanks }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
  ];
  const gapClass = compact ? 'gap-1.5' : 'gap-2';
  const blankClass = compact
    ? 'min-h-[4.25rem] rounded-md'
    : 'min-h-[5.75rem] rounded-lg';

  return (
    <div className="min-w-0">
      <div
        className={`app-kicker app-type-overline grid grid-cols-7 ${gapClass} text-center`}
      >
        {copy.explainability.weekdays.map((day) => (
          <div key={day} data-testid="return-calendar-weekday">
            {day}
          </div>
        ))}
      </div>
      <div
        className={`mt-2 grid grid-cols-7 ${gapClass}`}
        data-testid="return-calendar-month-grid"
      >
        {cells.map((day, index) => {
          if (day === null) {
            return (
              <div
                key={`blank-${index}`}
                className={`${blankClass} border border-dashed border-[color-mix(in_srgb,var(--app-border)_44%,transparent)]`}
              />
            );
          }
          const label = `${activeMonth}-${String(day).padStart(2, '0')}`;
          const row = rowsByLabel.get(label);
          const calendarDay =
            marketCalendarDays.get(label) ?? explainMarketCalendarDate(label);
          return (
            <ReturnCalendarCell
              key={label}
              label={label}
              heading={String(day)}
              row={row}
              calendarDay={calendarDay}
              metric={metric}
              maxMagnitude={maxMagnitude}
              selected={selectedLabel === label}
              onSelect={onSelect}
              compact={compact}
            />
          );
        })}
      </div>
    </div>
  );
}

function ReturnWeekGrid({
  rows,
  activeYear,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  activeYear: string;
  metric: ReturnCalendarMetric;
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  const slots = buildReturnWeekSlots(activeYear);

  return (
    <div
      className={`grid ${compact ? 'max-h-[34rem] gap-1.5' : 'max-h-[38rem] gap-2'} overflow-y-auto overscroll-contain pr-1 sm:grid-cols-2 md:grid-cols-3`}
      data-testid="return-calendar-week-grid"
    >
      {slots.map((slot) => (
        <ReturnCalendarCell
          key={slot.label}
          label={slot.label}
          heading={formatReturnWeekHeading(slot.weekNumber, copy)}
          sublabel={slot.rangeLabel}
          row={rowsByLabel.get(slot.label)}
          metric={metric}
          maxMagnitude={maxMagnitude}
          selected={selectedLabel === slot.label}
          onSelect={onSelect}
          compact={compact}
        />
      ))}
    </div>
  );
}

function ReturnYearGrid({
  rows,
  activeYear,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  activeYear: string;
  metric: ReturnCalendarMetric;
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  return (
    <div
      className={`grid ${compact ? 'gap-1.5' : 'gap-2'} sm:grid-cols-3 xl:grid-cols-4`}
      data-testid="return-calendar-year-grid"
    >
      {Array.from({ length: 12 }, (_, index) => {
        const label = `${activeYear}-${String(index + 1).padStart(2, '0')}`;
        return (
          <ReturnCalendarCell
            key={label}
            label={label}
            heading={label.slice(5)}
            row={rowsByLabel.get(label)}
            metric={metric}
            maxMagnitude={maxMagnitude}
            selected={selectedLabel === label}
            onSelect={onSelect}
            sublabel={copy.explainability.month}
            compact={compact}
          />
        );
      })}
    </div>
  );
}

function ReturnYearsGrid({
  rows,
  metric,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  metric: ReturnCalendarMetric;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  return (
    <div
      className={`grid ${compact ? 'gap-1.5' : 'gap-2'} sm:grid-cols-2 xl:grid-cols-3`}
      data-testid="return-calendar-years-grid"
    >
      {rows
        .slice()
        .reverse()
        .map((row) => (
          <ReturnCalendarCell
            key={row.label}
            label={row.label}
            heading={row.label}
            row={row}
            metric={metric}
            maxMagnitude={maxMagnitude}
            selected={selectedLabel === row.label}
            onSelect={onSelect}
            compact={compact}
          />
        ))}
    </div>
  );
}

function formatReturnCalendarCellHeading(heading: string, sublabel?: string) {
  if (!sublabel) {
    return { headingText: heading, sublabelText: null };
  }
  if (/^\d{2}$/.test(heading)) {
    return {
      headingText:
        sublabel === '月' ? `${heading}${sublabel}` : `${heading} ${sublabel}`,
      sublabelText: null,
    };
  }
  return { headingText: heading, sublabelText: sublabel };
}

function ReturnCalendarCell({
  label,
  heading,
  row,
  calendarDay,
  metric,
  maxMagnitude,
  selected,
  onSelect,
  sublabel,
  compact,
}: {
  label: string;
  heading: string;
  row: ReturnCalendarRow | undefined;
  calendarDay?: MarketCalendarDay;
  metric: ReturnCalendarMetric;
  maxMagnitude: number;
  selected: boolean;
  onSelect: (label: string) => void;
  sublabel?: string;
  compact: boolean;
}) {
  const copy = useCopy();
  const hasMissingValuation =
    row !== undefined && row.valuationStatus === 'missing';
  const hasUnconfirmedValuation =
    row !== undefined && row.valuationStatus === 'partial';
  const value = row
    ? metric === 'amount'
      ? row.marketPnl
      : row.percentChange
    : 0;
  const displayValue = row
    ? hasMissingValuation
      ? copy.explainability.missingValuationShort
      : metric === 'amount'
        ? formatReturnCurrency(row.marketPnl)
        : formatReturnPercent(row.percentChange)
    : '--';
  const nonTradingLabel =
    !row && calendarDay && !calendarDay.isTradingDay
      ? formatMarketCalendarClosedLabel(calendarDay, copy)
      : null;
  const rowNonTradingLabel =
    row && calendarDay && !calendarDay.isTradingDay
      ? formatMarketCalendarClosedLabel(calendarDay, copy)
      : null;
  const cellDisplayValue =
    rowNonTradingLabel ??
    (compact && row && !hasMissingValuation && metric === 'amount'
      ? formatCompactReturnCurrency(row.marketPnl)
      : (nonTradingLabel ?? displayValue));
  const cellAccessibleValue =
    rowNonTradingLabel ?? nonTradingLabel ?? displayValue;
  const tone = row
    ? hasMissingValuation
      ? 'border-dashed border-[color-mix(in_srgb,var(--app-border)_72%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_64%,transparent)] text-[var(--app-muted)]'
      : getHeatmapTone(value, maxMagnitude)
    : 'border-[color-mix(in_srgb,var(--app-border)_54%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_42%,transparent)] text-[var(--app-muted)]';
  const cellClass = compact
    ? 'flex min-h-[4.25rem] min-w-0 flex-col overflow-hidden rounded-md px-1.5 py-2'
    : 'flex min-h-[5.75rem] min-w-0 flex-col overflow-hidden rounded-lg px-3 py-3';
  const valueClass = compact
    ? 'app-type-micro mt-auto self-end whitespace-nowrap text-right font-semibold'
    : 'mt-auto max-w-full self-end break-words text-right text-base font-semibold leading-tight';
  const metaClass = compact
    ? 'app-type-micro mt-1 self-end text-right opacity-80'
    : 'app-type-micro mt-2 self-end text-right opacity-80';
  const { headingText, sublabelText } = formatReturnCalendarCellHeading(
    heading,
    sublabel,
  );

  if (!row) {
    return (
      <div className={`${cellClass} border ${tone}`}>
        <div
          className="text-xs font-semibold"
          data-testid="return-calendar-cell-heading"
        >
          {headingText}
        </div>
        {sublabelText ? (
          <div className="app-muted app-type-micro mt-1">{sublabelText}</div>
        ) : null}
        <div className={valueClass} data-testid="return-calendar-cell-value">
          {cellDisplayValue}
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`${label} · ${cellAccessibleValue}`}
      data-motion="stable-fact"
      onClick={() => onSelect(label)}
      className={`${cellClass} border text-left transition-colors focus:outline-none focus:ring-2 focus:ring-[color-mix(in_srgb,var(--app-accent)_58%,transparent)] ${
        selected ? 'ring-2 ring-[var(--app-accent)]' : ''
      } ${tone}`}
    >
      <div
        className="text-xs font-semibold"
        data-testid="return-calendar-cell-heading"
      >
        {headingText}
      </div>
      {sublabelText ? (
        <div className="app-type-micro mt-1 opacity-70">{sublabelText}</div>
      ) : null}
      <div className={valueClass} data-testid="return-calendar-cell-value">
        {cellDisplayValue}
      </div>
      {hasMissingValuation && row.missingPriceSymbols.length > 0 ? (
        <div className={metaClass}>
          {row.missingPriceSymbols.slice(0, 2).join(', ')}
        </div>
      ) : null}
      {hasUnconfirmedValuation ? (
        <div className={metaClass}>
          {copy.explainability.unconfirmedValuationShort}
        </div>
      ) : null}
    </button>
  );
}

function formatMarketCalendarClosedLabel(
  day: MarketCalendarDay,
  copy: AppCopy,
) {
  if (day.dayType === 'holiday') {
    return isGenericMarketCalendarReason(day.reason)
      ? copy.explainability.marketHolidayShort
      : day.reason;
  }
  if (day.dayType === 'weekend') {
    return isGenericMarketCalendarReason(day.reason)
      ? copy.explainability.marketWeekendShort
      : day.reason;
  }
  return isGenericMarketCalendarReason(day.reason)
    ? copy.explainability.marketClosedShort
    : day.reason;
}

function isGenericMarketCalendarReason(reason: string | null | undefined) {
  const normalized = (reason ?? '').trim().toLowerCase();
  return (
    normalized === '' ||
    normalized === 'weekend' ||
    normalized === 'exchange closed'
  );
}

function getHeatmapTone(value: number, maxMagnitude: number) {
  const intensity = Math.min(Math.abs(value) / maxMagnitude, 1);

  if (value > 0) {
    if (intensity > 0.66) {
      return 'app-heat-positive-strong';
    }
    if (intensity > 0.33) {
      return 'app-heat-positive-medium';
    }
    return 'app-heat-positive-soft';
  }

  if (value < 0) {
    if (intensity > 0.66) {
      return 'app-heat-negative-strong';
    }
    if (intensity > 0.33) {
      return 'app-heat-negative-medium';
    }
    return 'app-heat-negative-soft';
  }

  return 'border-[var(--app-border)] bg-[var(--app-panel-strong)] text-[var(--app-foreground)]';
}
