import type { ReactNode } from 'react';
import {
  BarChart3,
  CalendarDays,
  CircleDollarSign,
  Percent,
  Table2,
} from 'lucide-react';

import type { AppCopy } from '../../../shared/i18n/context';
import type {
  ReturnCalendarMetric,
  ReturnCalendarPeriod,
  ReturnCalendarViewMode,
} from './return-calendar-model';

export function ReturnCalendarToolbar({
  copy,
  compact,
  viewMode,
  period,
  metric,
  activeMonth,
  activeYear,
  monthOptions,
  yearOptions,
  valuationStatus,
  onViewModeChange,
  onPeriodChange,
  onMetricChange,
  onMonthChange,
  onYearChange,
}: {
  copy: AppCopy;
  compact: boolean;
  viewMode: ReturnCalendarViewMode;
  period: ReturnCalendarPeriod;
  metric: ReturnCalendarMetric;
  activeMonth: string;
  activeYear: string;
  monthOptions: string[];
  yearOptions: string[];
  valuationStatus: string;
  onViewModeChange: (value: ReturnCalendarViewMode) => void;
  onPeriodChange: (value: ReturnCalendarPeriod) => void;
  onMetricChange: (value: ReturnCalendarMetric) => void;
  onMonthChange: (value: string) => void;
  onYearChange: (value: string) => void;
}) {
  return (
    <div className={`${compact ? 'mt-3' : 'mt-4'} min-w-0`}>
      <div
        className="grid min-w-0 items-center gap-3 rounded-2xl bg-[color-mix(in_srgb,var(--app-surface-1)_62%,transparent)] p-1.5 shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-border)_36%,transparent)] sm:grid-cols-[auto_minmax(14rem,1fr)_auto] sm:rounded-full"
        data-testid="return-calendar-toolbar"
      >
        <ReturnCalendarSegmentedControl
          compactMode="icon"
          label={copy.explainability.viewMode}
          options={[
            {
              value: 'calendar',
              label: copy.explainability.calendarView,
              icon: <CalendarDays aria-hidden="true" size={18} />,
            },
            {
              value: 'curve',
              label: copy.explainability.curveView,
              icon: <BarChart3 aria-hidden="true" size={18} />,
            },
            {
              value: 'table',
              label: copy.explainability.tableView,
              icon: <Table2 aria-hidden="true" size={17} />,
            },
          ]}
          value={viewMode}
          onChange={(value) =>
            onViewModeChange(value as ReturnCalendarViewMode)
          }
        />
        <ReturnCalendarSegmentedControl
          compactMode="period"
          label={copy.explainability.periodMode}
          options={[
            { value: 'day', label: copy.explainability.day },
            { value: 'week', label: copy.explainability.week },
            { value: 'month', label: copy.explainability.month },
            { value: 'year', label: copy.explainability.year },
          ]}
          value={period}
          onChange={(value) => onPeriodChange(value as ReturnCalendarPeriod)}
        />
        <ReturnCalendarSegmentedControl
          compactMode="metric"
          label={copy.explainability.metricMode}
          options={[
            {
              value: 'amount',
              label: copy.explainability.amountMetric,
              icon: <CircleDollarSign aria-hidden="true" size={18} />,
            },
            {
              value: 'percent',
              label: copy.explainability.percentMetric,
              icon: <Percent aria-hidden="true" size={18} />,
            },
          ]}
          value={metric}
          onChange={(value) => onMetricChange(value as ReturnCalendarMetric)}
        />
      </div>
      <div className="mt-2 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        {period === 'day' ? (
          <select
            aria-label={copy.explainability.month}
            data-testid="return-calendar-period-select"
            value={activeMonth}
            onChange={(event) => onMonthChange(event.target.value)}
            className="app-field h-9 min-w-0 rounded-full px-3 text-sm sm:w-40"
          >
            {monthOptions.map((month) => (
              <option key={month} value={month}>
                {month}
              </option>
            ))}
          </select>
        ) : period === 'week' || period === 'month' ? (
          <select
            aria-label={copy.explainability.year}
            data-testid="return-calendar-period-select"
            value={activeYear}
            onChange={(event) => onYearChange(event.target.value)}
            className="app-field h-9 min-w-0 rounded-full px-3 text-sm sm:w-32"
          >
            {yearOptions.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        ) : (
          <div className="hidden sm:block" aria-hidden="true" />
        )}
        <ReturnCalendarDataStatus
          status={valuationStatus}
          copy={copy}
          compact={compact}
        />
      </div>
    </div>
  );
}

function ReturnCalendarSegmentedControl({
  compactMode = 'period',
  label,
  options,
  value,
  onChange,
}: {
  compactMode?: 'icon' | 'period' | 'metric';
  label: string;
  options: Array<{ value: string; label: string; icon?: ReactNode }>;
  value: string;
  onChange: (value: string) => void;
}) {
  const groupClass =
    compactMode === 'period'
      ? 'inline-flex w-full min-w-0 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_70%,transparent)] p-1 sm:justify-between'
      : 'inline-flex w-fit min-w-0 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_70%,transparent)] p-1';
  const buttonClass =
    compactMode === 'period'
      ? 'min-h-8 min-w-12 rounded-full px-4 py-1 text-base font-semibold transition sm:flex-1'
      : 'grid min-h-8 min-w-9 place-items-center rounded-full px-2 py-1 text-xs font-semibold transition';

  return (
    <div
      aria-label={label}
      className={`${groupClass} ${compactMode === 'metric' ? 'sm:justify-self-end' : ''}`}
      data-compact={compactMode}
      role="group"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            aria-label={option.label}
            onClick={() => onChange(option.value)}
            className={`${buttonClass} ${
              active
                ? 'bg-[var(--app-button)] text-[var(--app-button-text)] shadow-sm'
                : 'text-[color-mix(in_srgb,var(--app-muted)_78%,transparent)] hover:text-[var(--app-text)]'
            }`}
          >
            {option.icon ?? option.label}
            {option.icon ? (
              <span className="sr-only">{option.label}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function ReturnCalendarDataStatus({
  status,
  copy,
  compact,
}: {
  status: string;
  copy: AppCopy;
  compact: boolean;
}) {
  const detail =
    status === 'missing'
      ? copy.explainability.missingValuation
      : status === 'partial'
        ? copy.explainability.partialValuation
        : copy.explainability.confirmedValuation;
  const tone =
    status === 'missing'
      ? 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
      : status === 'partial'
        ? 'border-[color-mix(in_srgb,var(--app-accent-secondary)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-accent-secondary)_10%,transparent)] text-[var(--app-accent-secondary)]'
        : 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]';

  return (
    <div
      className={`${compact ? 'px-3 py-1.5' : 'px-3 py-2'} flex min-w-0 items-center gap-2 rounded-full border ${tone}`}
      data-testid="return-calendar-status-chip"
    >
      <div className="app-type-overline shrink-0">
        {copy.explainability.dataStatus}
      </div>
      <div className="min-w-0 truncate text-xs font-semibold">{detail}</div>
    </div>
  );
}
