import { useMemo, useState } from 'react';

import {
  aggregateReturnTimeline,
  buildMarketCalendarDayMap,
  summarizeReturnCalendarStatus,
  type ReturnCalendarMarketCalendar,
  type ReturnCalendarMetric,
  type ReturnCalendarPeriod,
  type ReturnCalendarTimelinePoint,
  type ReturnCalendarViewMode,
} from './return-calendar-model';

export function useReturnCalendarController(
  timeline: ReturnCalendarTimelinePoint[],
  marketCalendar?: ReturnCalendarMarketCalendar | null,
) {
  const dailyRows = aggregateReturnTimeline(timeline, 'day');
  const weeklyRows = aggregateReturnTimeline(timeline, 'week');
  const monthlyRows = aggregateReturnTimeline(timeline, 'month');
  const yearlyRows = aggregateReturnTimeline(timeline, 'year');
  const monthOptions = Array.from(
    new Set(dailyRows.map((row) => row.label.slice(0, 7))),
  ).sort();
  const yearOptions = Array.from(
    new Set(monthlyRows.map((row) => row.label.slice(0, 4))),
  ).sort();
  const initialMonth = monthOptions[monthOptions.length - 1] ?? '';
  const initialYear = yearOptions[yearOptions.length - 1] ?? '';
  const [viewMode, setViewMode] = useState<ReturnCalendarViewMode>('calendar');
  const [period, setPeriod] = useState<ReturnCalendarPeriod>('day');
  const [metric, setMetric] = useState<ReturnCalendarMetric>('amount');
  const [selectedMonth, setSelectedMonth] = useState(initialMonth);
  const [selectedYear, setSelectedYear] = useState(initialYear);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);

  const activeMonth = monthOptions.includes(selectedMonth)
    ? selectedMonth
    : initialMonth;
  const activeYear = yearOptions.includes(selectedYear)
    ? selectedYear
    : initialYear;
  const aggregated =
    period === 'day'
      ? dailyRows.filter((row) => row.label.startsWith(activeMonth))
      : period === 'week'
        ? weeklyRows.filter((row) => row.label.startsWith(activeYear))
        : period === 'month'
          ? monthlyRows.filter((row) => row.label.startsWith(activeYear))
          : yearlyRows;
  const selectedRow =
    aggregated.find((row) => row.label === selectedLabel) ??
    aggregated[aggregated.length - 1] ??
    null;
  const marketCalendarDays = useMemo(
    () => buildMarketCalendarDayMap(marketCalendar),
    [marketCalendar],
  );

  return {
    activeMonth,
    activeYear,
    aggregated,
    hasTimeline: timeline.length > 0,
    marketCalendarDays,
    metric,
    monthOptions,
    period,
    selectedRow,
    valuationStatus: summarizeReturnCalendarStatus(aggregated),
    viewMode,
    yearOptions,
    selectLabel: setSelectedLabel,
    selectMetric: setMetric,
    selectMonth(value: string) {
      setSelectedMonth(value);
      setSelectedLabel(null);
    },
    selectPeriod(value: ReturnCalendarPeriod) {
      setPeriod(value);
      setSelectedLabel(null);
    },
    selectViewMode: setViewMode,
    selectYear(value: string) {
      setSelectedYear(value);
      setSelectedLabel(null);
    },
  };
}

export type ReturnCalendarController = ReturnType<
  typeof useReturnCalendarController
>;
