import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatAmount,
  formatCurrency,
  formatPercent,
} from '../../../shared/format';
import type {
  BacktestRunRequest,
  BacktestSweepResponse,
  StrategyParameterSchema,
  StrategyParameterValue,
} from '../api';
import { useRunBacktestSweepMutation } from '../api';
import { chronologicalCopy } from '../copy-chronological';
import { ChronologicalSweepResult } from './chronological-sweep-result';

import {
  parameterInputError,
  parseParamValue,
  schemaDefaultValue,
} from './backtest-page-model';
import { backtestParameterError } from './backtest-universe';

function defaultGridValues(
  parameterSchema: StrategyParameterSchema[],
  parameterValues: Record<string, string>,
) {
  return Object.fromEntries(
    parameterSchema.map((param) => [
      param.name,
      parameterValues[param.name] ?? schemaDefaultValue(param),
    ]),
  );
}

function parseGridValue(
  param: StrategyParameterSchema,
  value: string,
): StrategyParameterValue[] {
  if (!value.trim()) return [parseParamValue(param, value)];
  if (param.type === 'dict') {
    const candidates: unknown[] = JSON.parse(`[${value}]`);
    return candidates.map((candidate) =>
      parseParamValue(param, JSON.stringify(candidate)),
    );
  }
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => parseParamValue(param, part));
}

function formatParamList(
  params: Record<string, StrategyParameterValue>,
  labels: Partial<Record<string, string>>,
) {
  return Object.entries(params)
    .map(
      ([name, value]) =>
        `${parameterLabel(labels, name)}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`,
    )
    .join(', ');
}

function parameterLabel(labels: Partial<Record<string, string>>, name: string) {
  return labels[name] ?? humanizeParameterName(name);
}

function humanizeParameterName(name: string) {
  return name
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function ParameterSweepPanel({
  startDate,
  endDate,
  initialCash,
  costAssumptions,
  corporateActionMode = 'price_only',
  strategy,
  parameterSchema,
  parameterValues,
  assets,
  datasetId,
  disabledReason,
}: {
  startDate: string;
  endDate: string;
  initialCash: string;
  costAssumptions?: BacktestRunRequest['cost_assumptions'];
  corporateActionMode?: BacktestRunRequest['corporate_action_mode'];
  strategy: string;
  parameterSchema: StrategyParameterSchema[];
  parameterValues: Record<string, string>;
  assets?: BacktestRunRequest['assets'];
  datasetId?: string;
  disabledReason?: string;
}) {
  const copy = useCopy();
  const labels = copy.backtest.sweep;
  const pageLabels = copy.backtest.page;
  const common = copy.common;
  const { locale } = usePreferences();
  const chronologicalLabels = chronologicalCopy[locale];
  const sweep = useRunBacktestSweepMutation();
  const [gridValues, setGridValues] = useState<Record<string, string>>(() =>
    defaultGridValues(parameterSchema, parameterValues),
  );
  const [rankBy, setRankBy] = useState('total_return');
  const [chronological, setChronological] = useState(false);
  const [testStartDate, setTestStartDate] = useState('');
  const chronologicalSupported =
    strategy === 'dual_ma' && /^sha256:[0-9a-f]{64}$/.test(datasetId ?? '');
  const chronologicalValid =
    !chronological ||
    (chronologicalSupported &&
      testStartDate > startDate &&
      testStartDate <= endDate);
  const [error, setError] = useState('');
  const [response, setResponse] = useState<BacktestSweepResponse | null>(null);

  useEffect(() => {
    setGridValues(defaultGridValues(parameterSchema, parameterValues));
  }, [parameterSchema, strategy]);

  const combinationCount = useMemo(() => {
    try {
      return parameterSchema.reduce((total, param) => {
        const count = parseGridValue(
          param,
          gridValues[param.name] ?? '',
        ).length;
        return total * Math.max(count, 1);
      }, 1);
    } catch {
      return 0;
    }
  }, [gridValues, parameterSchema]);

  const submitSweep = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (disabledReason || !chronologicalValid) return;
    const baseError = backtestParameterError(
      parameterSchema,
      parameterValues,
      locale === 'zh',
      pageLabels.parameterLabels,
    );
    if (baseError) {
      setError(baseError);
      return;
    }
    const paramGrid: Record<string, StrategyParameterValue[]> = {};
    for (const param of parameterSchema) {
      const value = gridValues[param.name] ?? '';
      try {
        paramGrid[param.name] = parseGridValue(param, value);
      } catch {
        setError(
          parameterInputError(
            param,
            value,
            locale === 'zh',
            pageLabels.parameterLabels,
          ) || common.genericSubmitError,
        );
        return;
      }
    }
    const invalid = Object.values(paramGrid).some(
      (values) => values.length === 0,
    );
    if (
      !startDate ||
      !endDate ||
      !Number.isFinite(Number(initialCash)) ||
      invalid
    ) {
      setError(common.mustBePositive);
      return;
    }
    setError('');
    try {
      const result = await sweep.mutateAsync({
        ...(datasetId ? { dataset_id: datasetId } : {}),
        ...(costAssumptions ? { cost_assumptions: costAssumptions } : {}),
        ...(chronological ? { test_start_date: testStartDate } : {}),
        corporate_action_mode: corporateActionMode,
        start_date: startDate,
        end_date: endDate,
        initial_cash: Number(initialCash),
        strategy,
        params: Object.fromEntries(
          parameterSchema.map((param) => [
            param.name,
            parseParamValue(param, parameterValues[param.name] ?? ''),
          ]),
        ),
        param_grid: paramGrid,
        assets,
        rank_by: rankBy,
        max_combinations: 25,
      });
      setResponse(result);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '';
      const chronologicalErrors: Record<string, string> = {
        chronological_sweep_requires_dual_ma_dataset:
          chronologicalLabels.requires,
        backtest_execution_window_dataset_required:
          chronologicalLabels.requires,
        chronological_sweep_window_invalid: chronologicalLabels.invalidDate,
        backtest_execution_window_invalid: chronologicalLabels.invalidDate,
        chronological_sweep_insufficient_sessions:
          chronologicalLabels.insufficientSessions,
        backtest_execution_window_empty:
          chronologicalLabels.insufficientSessions,
        chronological_sweep_score_unavailable:
          chronologicalLabels.scoreUnavailable,
      };
      setError(
        (chronological && chronologicalErrors[message]) ||
          message ||
          common.genericSubmitError,
      );
    }
  };

  return (
    <section className="mt-5 min-w-0 border-y border-[var(--app-divider)] py-4">
      <div className="app-kicker app-type-overline">{labels.kicker}</div>
      <h3 className="app-card-title mt-1.5">{labels.title}</h3>
      <p className="app-muted mt-2 text-sm leading-6">{labels.subtitle}</p>
      {disabledReason ? (
        <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
          {disabledReason}
        </p>
      ) : null}

      <form className="mt-4 grid gap-3" onSubmit={submitSweep}>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={chronological}
            disabled={
              sweep.isPending || (!chronologicalSupported && !chronological)
            }
            onChange={(event) => setChronological(event.target.checked)}
          />
          {chronologicalLabels.enable}
        </label>
        {!chronologicalSupported ? (
          <p className="app-muted text-xs leading-5">
            {chronologicalLabels.requires}
          </p>
        ) : null}
        {chronological ? (
          <>
            <label className="grid min-w-0 gap-2 text-sm font-medium">
              {chronologicalLabels.testStart}
              <input
                type="date"
                className="app-field min-h-11 min-w-0 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
                min={startDate}
                max={endDate}
                value={testStartDate}
                disabled={sweep.isPending}
                onChange={(event) => setTestStartDate(event.target.value)}
              />
            </label>
            <p className="app-muted text-xs leading-5">
              {chronologicalLabels.procedure}
            </p>
            <p className="app-muted text-xs leading-5">
              {chronologicalLabels.boundary}
            </p>
            {!chronologicalValid ? (
              <p role="alert" className="text-xs">
                {chronologicalLabels.invalidDate}
              </p>
            ) : null}
          </>
        ) : null}
        <div className="grid min-w-0 gap-3">
          {parameterSchema.map((param) => (
            <label
              key={param.name}
              className="grid min-w-0 gap-2 text-sm font-medium"
            >
              {labels.candidateLabel(
                parameterLabel(pageLabels.parameterLabels, param.name),
              )}
              <input
                className="app-field w-full min-w-0 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm tabular-nums"
                value={gridValues[param.name] ?? ''}
                onChange={(event) =>
                  setGridValues((current) => ({
                    ...current,
                    [param.name]: event.target.value,
                  }))
                }
                aria-label={labels.candidateLabel(
                  parameterLabel(pageLabels.parameterLabels, param.name),
                )}
              />
            </label>
          ))}
        </div>
        <div className="grid min-w-0 gap-3">
          <label className="grid min-w-0 gap-2 text-sm font-medium">
            {labels.rankBy}
            <select
              className="app-field w-full min-w-0 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
              value={rankBy}
              onChange={(event) => setRankBy(event.target.value)}
              aria-label={labels.rankBy}
            >
              <option value="total_return">{labels.rankTotalReturn}</option>
              <option value="sharpe">{labels.rankSharpe}</option>
              <option value="max_drawdown">{labels.rankMaxDrawdown}</option>
            </select>
          </label>
          <div className="flex items-end">
            <button
              type="submit"
              className="app-button-secondary rounded-[var(--app-radius-control)] px-4 py-2.5 text-sm font-semibold"
              disabled={
                sweep.isPending ||
                Boolean(disabledReason) ||
                !chronologicalValid
              }
            >
              {sweep.isPending
                ? labels.running
                : chronological
                  ? chronologicalLabels.run
                  : labels.run}
            </button>
          </div>
        </div>
        <span className="app-muted text-xs">
          {labels.gridHint(combinationCount)}
        </span>
        {error ? (
          <div
            className="border-l-2 border-[var(--app-danger-border)] py-2 pl-3 text-sm text-[var(--app-danger-text)]"
            role="alert"
          >
            {error}
          </div>
        ) : null}
      </form>

      {response ? <SweepResults response={response} /> : null}
    </section>
  );
}

function SweepResults({ response }: { response: BacktestSweepResponse }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const chronologicalLabels = chronologicalCopy[locale];
  const labels = copy.backtest.sweep;
  const pageLabels = copy.backtest.page;
  return (
    <div className="mt-5 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="app-kicker app-type-overline">
            {labels.resultsKicker}
          </div>
          <h4 className="text-base font-semibold">
            {response.chronological_validation
              ? chronologicalLabels.trainingTitle
              : labels.resultsTitle}
          </h4>
        </div>
        <span className="app-muted text-sm tabular-nums">
          {labels.tested(response.tested_count)}
        </span>
      </div>
      {response.chronological_validation ? (
        <p className="app-muted text-xs leading-5">
          {chronologicalLabels.trainingScores}
        </p>
      ) : null}
      <div className="overflow-x-auto border-y border-[var(--app-divider)]">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="app-type-overline bg-[color-mix(in_srgb,var(--app-surface-0)_35%,transparent)] text-[var(--app-muted)]">
            <tr>
              <th className="px-4 py-3 font-semibold">{labels.rank}</th>
              <th className="px-4 py-3 font-semibold">{labels.result}</th>
              <th className="px-4 py-3 font-semibold">{labels.params}</th>
              <th className="px-4 py-3 font-semibold">{labels.score}</th>
              <th className="px-4 py-3 font-semibold">{labels.sharpe}</th>
              <th className="px-4 py-3 font-semibold">{labels.cost}</th>
            </tr>
          </thead>
          <tbody>
            {response.results.map((result) => (
              <tr
                key={result.result_id}
                className="border-t border-[color-mix(in_srgb,var(--app-border)_18%,transparent)]"
              >
                <td className="px-4 py-3 font-semibold tabular-nums">
                  #{result.rank}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {labels.resultId(result.result_id)}
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {formatParamList(result.params, pageLabels.parameterLabels)}
                </td>
                <td className="px-4 py-3 font-semibold tabular-nums">
                  {response.rank_by === 'max_drawdown'
                    ? formatPercent(result.metrics.max_drawdown)
                    : response.rank_by === 'sharpe'
                      ? formatAmount(result.metrics.sharpe)
                      : formatPercent(result.metrics.total_return)}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatAmount(result.metrics.sharpe)}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatCurrency(
                    (result.metrics.total_commission ?? 0) +
                      (result.metrics.total_slippage ?? 0),
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ChronologicalSweepResult response={response} />
      {response.warnings.length ? (
        <div className="border-l-2 border-[var(--app-warning-border)] py-2 pl-3 text-sm leading-6 text-[var(--app-warning-text)]">
          {response.warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
