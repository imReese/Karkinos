import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../app/copy';
import {
  formatAmount,
  formatCurrency,
  formatPercent,
} from '../../../shared/format';
import type {
  BacktestCompareResponse,
  BacktestRunRequest,
  StrategyParameterSchema,
} from '../api';
import { useRunBacktestCompareMutation } from '../api';

type ParameterPrimitive = number | string | boolean | null;

function schemaDefaultValue(param: StrategyParameterSchema) {
  if (param.default === null || param.default === undefined) {
    return '';
  }
  return String(param.default);
}

function defaultCompareSets(parameterSchema: StrategyParameterSchema[]) {
  const defaults = parameterSchema
    .map((param) => `${param.name}=${schemaDefaultValue(param)}`)
    .join(', ');
  return [defaults, defaults].filter(Boolean).join('\n');
}

function parameterLabel(labels: Partial<Record<string, string>>, name: string) {
  return labels[name] ?? name;
}

function parseParamValue(
  param: StrategyParameterSchema,
  value: string,
): ParameterPrimitive {
  const trimmed = value.trim();
  if (trimmed === '') {
    return null;
  }
  if (param.type === 'int') {
    return Number.parseInt(trimmed, 10);
  }
  if (param.type === 'float') {
    return Number(trimmed);
  }
  if (param.type === 'bool') {
    return trimmed.toLowerCase() === 'true';
  }
  return trimmed;
}

function parseParameterSet(
  line: string,
  schemaByName: Map<string, StrategyParameterSchema>,
) {
  const params: Record<string, ParameterPrimitive> = {};
  for (const rawPart of line.split(',')) {
    const part = rawPart.trim();
    if (!part) {
      continue;
    }
    const separatorIndex = part.indexOf('=');
    if (separatorIndex === -1) {
      throw new Error('invalid');
    }
    const name = part.slice(0, separatorIndex).trim();
    const value = part.slice(separatorIndex + 1);
    const schema = schemaByName.get(name);
    if (!schema) {
      throw new Error('invalid');
    }
    params[name] = parseParamValue(schema, value);
  }
  if (Object.keys(params).length === 0) {
    throw new Error('invalid');
  }
  return params;
}

function hasInvalidNumbers(
  schemaByName: Map<string, StrategyParameterSchema>,
  params: Record<string, ParameterPrimitive>,
) {
  return Object.entries(params).some(([name, value]) => {
    const schema = schemaByName.get(name);
    if (!schema || (schema.type !== 'int' && schema.type !== 'float')) {
      return false;
    }
    return typeof value !== 'number' || !Number.isFinite(value);
  });
}

function formatParamList(
  params: Record<string, ParameterPrimitive>,
  labels: Partial<Record<string, string>>,
) {
  return Object.entries(params)
    .map(([name, value]) => `${parameterLabel(labels, name)}=${String(value)}`)
    .join(', ');
}

export function ParameterComparePanel({
  startDate,
  endDate,
  initialCash,
  strategy,
  parameterSchema,
  assets,
}: {
  startDate: string;
  endDate: string;
  initialCash: string;
  strategy: string;
  parameterSchema: StrategyParameterSchema[];
  assets?: BacktestRunRequest['assets'];
}) {
  const copy = useCopy();
  const labels = copy.backtest.compare;
  const common = copy.common;
  const compare = useRunBacktestCompareMutation();
  const [parameterSets, setParameterSets] = useState(() =>
    defaultCompareSets(parameterSchema),
  );
  const [error, setError] = useState('');
  const [response, setResponse] = useState<BacktestCompareResponse | null>(
    null,
  );
  const schemaByName = useMemo(
    () => new Map(parameterSchema.map((param) => [param.name, param])),
    [parameterSchema],
  );

  useEffect(() => {
    setParameterSets(defaultCompareSets(parameterSchema));
    setResponse(null);
  }, [parameterSchema, strategy]);

  const parsedRuns = useMemo(() => {
    try {
      const parsed = parameterSets
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => parseParameterSet(line, schemaByName));
      return { parsed, valid: true };
    } catch {
      return { parsed: [], valid: false };
    }
  }, [parameterSets, schemaByName]);

  const submitCompare = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !startDate ||
      !endDate ||
      !Number.isFinite(Number(initialCash)) ||
      parsedRuns.parsed.length < 2 ||
      !parsedRuns.valid ||
      parsedRuns.parsed.some((params) =>
        hasInvalidNumbers(schemaByName, params),
      )
    ) {
      setError(labels.invalidSets);
      return;
    }
    setError('');
    try {
      const result = await compare.mutateAsync({
        start_date: startDate,
        end_date: endDate,
        initial_cash: Number(initialCash),
        assets,
        runs: parsedRuns.parsed.map((params) => ({ strategy, params })),
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

      <form className="mt-4 grid gap-3" onSubmit={submitCompare}>
        <label className="grid gap-2 text-sm font-medium">
          {labels.parameterSets}
          <textarea
            className="app-field min-h-24 rounded-2xl px-4 py-3 font-mono text-sm tabular-nums"
            value={parameterSets}
            onChange={(event) => setParameterSets(event.target.value)}
            aria-label={labels.parameterSets}
          />
        </label>
        <span className="app-muted text-xs">
          {labels.setsHint(parsedRuns.parsed.length)}
        </span>
        {error ? (
          <div
            className="rounded-2xl border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-4 py-3 text-sm text-[var(--app-danger)]"
            role="alert"
          >
            {error}
          </div>
        ) : null}
        <div className="flex justify-end">
          <button
            type="submit"
            className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-semibold transition active:scale-[0.99]"
            disabled={compare.isPending}
          >
            {compare.isPending ? labels.running : labels.run}
          </button>
        </div>
      </form>

      {response ? <CompareResults response={response} /> : null}
    </section>
  );
}

function CompareResults({ response }: { response: BacktestCompareResponse }) {
  const copy = useCopy();
  const labels = copy.backtest.compare;
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
        <div className="text-right text-sm tabular-nums">
          <div className="font-semibold">
            {labels.compared(response.compared_count)}
          </div>
          {response.dataset_snapshot_id ? (
            <div className="app-muted text-xs">
              {response.dataset_snapshot_id}
            </div>
          ) : null}
        </div>
      </div>
      <div className="overflow-x-auto rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)]">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="bg-[color-mix(in_srgb,var(--app-surface-0)_35%,transparent)] text-xs uppercase tracking-[0.12em] text-[var(--app-muted)]">
            <tr>
              <th className="px-4 py-3 font-semibold">{labels.result}</th>
              <th className="px-4 py-3 font-semibold">{labels.params}</th>
              <th className="px-4 py-3 font-semibold">{labels.totalReturn}</th>
              <th className="px-4 py-3 font-semibold">{labels.drawdown}</th>
              <th className="px-4 py-3 font-semibold">{labels.sharpe}</th>
              <th className="px-4 py-3 font-semibold">{labels.cost}</th>
            </tr>
          </thead>
          <tbody>
            {response.results.map((result) => (
              <tr
                key={`${result.strategy}-${result.result_id}`}
                className="border-t border-[color-mix(in_srgb,var(--app-border)_18%,transparent)]"
              >
                <td className="px-4 py-3 tabular-nums">
                  {result.result_id
                    ? labels.resultId(result.result_id)
                    : result.strategy}
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {formatParamList(result.params, pageLabels.parameterLabels)}
                </td>
                <td className="px-4 py-3 font-semibold tabular-nums">
                  {formatPercent(result.metrics.total_return)}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatPercent(result.metrics.max_drawdown)}
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
