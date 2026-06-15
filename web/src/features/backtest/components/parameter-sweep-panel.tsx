import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../app/copy';
import {
  formatAmount,
  formatCurrency,
  formatPercent,
} from '../../../shared/format';
import type {
  BacktestRunRequest,
  BacktestSweepResponse,
  StrategyParameterSchema,
} from '../api';
import { useRunBacktestSweepMutation } from '../api';

type ParameterPrimitive = number | string | boolean | null;

function defaultGridValues(
  parameterSchema: StrategyParameterSchema[],
  parameterValues: Record<string, string>,
) {
  return Object.fromEntries(
    parameterSchema.map((param) => [
      param.name,
      parameterValues[param.name] || String(param.default ?? ''),
    ]),
  );
}

function parseGridValue(
  param: StrategyParameterSchema,
  value: string,
): ParameterPrimitive[] {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      if (param.type === 'int') {
        return Number.parseInt(part, 10);
      }
      if (param.type === 'float') {
        return Number(part);
      }
      if (param.type === 'bool') {
        return part.toLowerCase() === 'true';
      }
      return part;
    });
}

function hasInvalidNumbers(
  param: StrategyParameterSchema,
  values: ParameterPrimitive[],
) {
  if (param.type !== 'int' && param.type !== 'float') {
    return false;
  }
  return values.some(
    (value) => typeof value !== 'number' || !Number.isFinite(value),
  );
}

function formatParamList(
  params: Record<string, ParameterPrimitive>,
  labels: Partial<Record<string, string>>,
) {
  return Object.entries(params)
    .map(([name, value]) => `${parameterLabel(labels, name)}=${String(value)}`)
    .join(', ');
}

function parameterLabel(labels: Partial<Record<string, string>>, name: string) {
  return labels[name] ?? name;
}

export function ParameterSweepPanel({
  startDate,
  endDate,
  initialCash,
  strategy,
  parameterSchema,
  parameterValues,
  assets,
}: {
  startDate: string;
  endDate: string;
  initialCash: string;
  strategy: string;
  parameterSchema: StrategyParameterSchema[];
  parameterValues: Record<string, string>;
  assets?: BacktestRunRequest['assets'];
}) {
  const copy = useCopy();
  const labels = copy.backtest.sweep;
  const pageLabels = copy.backtest.page;
  const common = copy.common;
  const sweep = useRunBacktestSweepMutation();
  const [gridValues, setGridValues] = useState<Record<string, string>>(() =>
    defaultGridValues(parameterSchema, parameterValues),
  );
  const [rankBy, setRankBy] = useState('total_return');
  const [error, setError] = useState('');
  const [response, setResponse] = useState<BacktestSweepResponse | null>(null);

  useEffect(() => {
    setGridValues(defaultGridValues(parameterSchema, parameterValues));
  }, [parameterSchema, strategy]);

  const combinationCount = useMemo(
    () =>
      parameterSchema.reduce((total, param) => {
        const count = parseGridValue(
          param,
          gridValues[param.name] ?? '',
        ).length;
        return total * Math.max(count, 1);
      }, 1),
    [gridValues, parameterSchema],
  );

  const submitSweep = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const paramGrid = Object.fromEntries(
      parameterSchema.map((param) => [
        param.name,
        parseGridValue(param, gridValues[param.name] ?? ''),
      ]),
    );
    const invalid = parameterSchema.some((param) => {
      const values = paramGrid[param.name];
      return values.length === 0 || hasInvalidNumbers(param, values);
    });
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
        start_date: startDate,
        end_date: endDate,
        initial_cash: Number(initialCash),
        strategy,
        params: Object.fromEntries(
          parameterSchema.map((param) => [
            param.name,
            parseGridValue(param, parameterValues[param.name] ?? '')[0] ?? null,
          ]),
        ),
        param_grid: paramGrid,
        assets,
        rank_by: rankBy,
        max_combinations: 25,
      });
      setResponse(result);
    } catch (caught) {
      setError(
        caught instanceof Error && caught.message
          ? caught.message
          : common.genericSubmitError,
      );
    }
  };

  return (
    <section className="mt-5 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
      <div className="app-kicker text-xs uppercase tracking-[0.16em]">
        {labels.kicker}
      </div>
      <h3 className="app-card-title mt-1.5">{labels.title}</h3>
      <p className="app-muted mt-2 text-sm leading-6">{labels.subtitle}</p>

      <form className="mt-4 grid gap-3" onSubmit={submitSweep}>
        <div className="grid gap-3 sm:grid-cols-2">
          {parameterSchema.map((param) => (
            <label key={param.name} className="grid gap-2 text-sm font-medium">
              {labels.candidateLabel(
                parameterLabel(pageLabels.parameterLabels, param.name),
              )}
              <input
                className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
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
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <label className="grid gap-2 text-sm font-medium">
            {labels.rankBy}
            <select
              className="app-field rounded-2xl px-4 py-3 text-sm"
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
              className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-semibold transition active:scale-[0.99]"
              disabled={sweep.isPending}
            >
              {sweep.isPending ? labels.running : labels.run}
            </button>
          </div>
        </div>
        <span className="app-muted text-xs">
          {labels.gridHint(combinationCount)}
        </span>
        {error ? (
          <div
            className="rounded-2xl border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-4 py-3 text-sm text-[var(--app-danger)]"
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
  const labels = copy.backtest.sweep;
  const pageLabels = copy.backtest.page;
  return (
    <div className="mt-5 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
            {labels.resultsKicker}
          </div>
          <h4 className="text-base font-semibold">{labels.resultsTitle}</h4>
        </div>
        <span className="app-muted text-sm tabular-nums">
          {labels.tested(response.tested_count)}
        </span>
      </div>
      <div className="overflow-x-auto rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)]">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="bg-[color-mix(in_srgb,var(--app-surface-0)_35%,transparent)] text-xs uppercase tracking-[0.12em] text-[var(--app-muted)]">
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
      {response.warnings.length ? (
        <div className="rounded-2xl border border-[color-mix(in_srgb,#f9e2af_34%,var(--app-border))] bg-[color-mix(in_srgb,#f9e2af_8%,transparent)] px-4 py-3 text-sm leading-6 text-[color-mix(in_srgb,#f9e2af_88%,white)]">
          {response.warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
