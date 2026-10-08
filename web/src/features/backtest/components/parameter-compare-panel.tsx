import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatAmount,
  formatCurrency,
  formatPercent,
} from '../../../shared/format';
import type {
  BacktestCompareResponse,
  BacktestRunRequest,
  StrategyParameterSchema,
  StrategyParameterValue,
} from '../api';
import { useRunBacktestCompareMutation } from '../api';

import {
  humanizeParameterName,
  parameterInputError,
  parseParamValue,
  schemaDefaultValue,
} from './backtest-page-model';

function parameterLabel(labels: Partial<Record<string, string>>, name: string) {
  return labels[name] ?? humanizeParameterName(name);
}

function defaultCompareSets(
  parameterSchema: StrategyParameterSchema[],
  labels: Partial<Record<string, string>>,
) {
  const defaults = parameterSchema.some((param) => param.type === 'dict')
    ? JSON.stringify(
        Object.fromEntries(
          parameterSchema
            .filter((param) => param.default != null)
            .map((param) => [param.name, param.default]),
        ),
      )
    : parameterSchema
        .map(
          (param) =>
            `${parameterLabel(labels, param.name)}=${schemaDefaultValue(param)}`,
        )
        .join(', ');
  return [defaults, defaults].filter(Boolean).join('\n');
}

function comparisonExample(
  parameterSchema: StrategyParameterSchema[],
  labels: Partial<Record<string, string>>,
) {
  if (!parameterSchema.length) {
    return '';
  }
  if (parameterSchema.some((param) => param.type === 'dict')) {
    return defaultCompareSets(parameterSchema, labels).split('\n')[0];
  }
  const exampleValues: Record<string, string> = {
    long_period: '9',
    short_period: '3',
  };
  return parameterSchema
    .map(
      (param) =>
        `${parameterLabel(labels, param.name)}=${
          exampleValues[param.name] ?? schemaDefaultValue(param)
        }`,
    )
    .join(', ');
}

function parseParameterSet(
  line: string,
  schemaByName: Map<string, StrategyParameterSchema>,
  schemaByAlias: Map<string, StrategyParameterSchema>,
  zh: boolean,
  labels: Record<string, string>,
) {
  const params: Record<string, StrategyParameterValue> = {};
  const jsonLine = line.trim().startsWith('{');
  let entries: [string, unknown][];
  if (jsonLine) {
    const object: unknown = JSON.parse(line);
    if (!object || typeof object !== 'object' || Array.isArray(object)) {
      throw new Error('invalid');
    }
    entries = Object.entries(object);
  } else {
    entries = line
      .split(',')
      .filter((part) => part.trim())
      .map((part) => {
        const separatorIndex = part.indexOf('=');
        if (separatorIndex === -1) throw new Error('invalid');
        return [
          part.slice(0, separatorIndex).trim(),
          part.slice(separatorIndex + 1),
        ];
      });
  }
  for (const [name, rawValue] of entries) {
    const schema = schemaByName.get(name) ?? schemaByAlias.get(name);
    if (!schema) throw new Error('invalid');
    const value =
      jsonLine && schema.type === 'dict'
        ? JSON.stringify(rawValue)
        : jsonLine && rawValue === null
          ? ''
          : String(rawValue);
    const error = parameterInputError(schema, value, zh, labels);
    if (error) throw new Error(error);
    params[schema.name] = parseParamValue(schema, value);
  }
  if (Object.keys(params).length === 0) throw new Error('invalid');
  return params;
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

export function ParameterComparePanel({
  startDate,
  endDate,
  initialCash,
  costAssumptions,
  corporateActionMode = 'price_only',
  strategy,
  parameterSchema,
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
  assets?: BacktestRunRequest['assets'];
  datasetId?: string;
  disabledReason?: string;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.backtest.compare;
  const pageLabels = copy.backtest.page;
  const common = copy.common;
  const compare = useRunBacktestCompareMutation();
  const [parameterSets, setParameterSets] = useState(() =>
    defaultCompareSets(parameterSchema, pageLabels.parameterLabels),
  );
  const [error, setError] = useState('');
  const [response, setResponse] = useState<BacktestCompareResponse | null>(
    null,
  );
  const schemaByName = useMemo(
    () => new Map(parameterSchema.map((param) => [param.name, param])),
    [parameterSchema],
  );
  const schemaByAlias = useMemo(
    () =>
      new Map(
        parameterSchema.flatMap((param) => [
          [parameterLabel(pageLabels.parameterLabels, param.name), param],
          [humanizeParameterName(param.name), param],
        ]),
      ),
    [pageLabels.parameterLabels, parameterSchema],
  );
  const exampleSet = useMemo(
    () => comparisonExample(parameterSchema, pageLabels.parameterLabels),
    [pageLabels.parameterLabels, parameterSchema],
  );

  useEffect(() => {
    setParameterSets(
      defaultCompareSets(parameterSchema, pageLabels.parameterLabels),
    );
    setResponse(null);
  }, [pageLabels.parameterLabels, parameterSchema, strategy]);

  const parsedRuns = useMemo(() => {
    try {
      const parsed = parameterSets
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) =>
          parseParameterSet(
            line,
            schemaByName,
            schemaByAlias,
            locale === 'zh',
            pageLabels.parameterLabels,
          ),
        );
      return { parsed, error: '' };
    } catch (caught) {
      return {
        parsed: [],
        error:
          caught instanceof Error &&
          caught.message !== 'invalid' &&
          !(caught instanceof SyntaxError)
            ? caught.message
            : labels.invalidSets,
      };
    }
  }, [
    parameterSets,
    schemaByAlias,
    schemaByName,
    locale,
    pageLabels.parameterLabels,
    labels.invalidSets,
  ]);

  const submitCompare = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (disabledReason) return;
    if (
      !startDate ||
      !endDate ||
      !Number.isFinite(Number(initialCash)) ||
      parsedRuns.parsed.length < 2 ||
      Boolean(parsedRuns.error)
    ) {
      setError(parsedRuns.error || labels.invalidSets);
      return;
    }
    setError('');
    try {
      const result = await compare.mutateAsync({
        ...(datasetId ? { dataset_id: datasetId } : {}),
        ...(costAssumptions ? { cost_assumptions: costAssumptions } : {}),
        corporate_action_mode: corporateActionMode,
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
    <section className="mt-5 border-y border-[var(--app-divider)] py-4">
      <div className="app-kicker app-type-overline">{labels.kicker}</div>
      <h3 className="app-card-title mt-1.5">{labels.title}</h3>
      <p className="app-muted mt-2 text-sm leading-6">{labels.subtitle}</p>
      {disabledReason ? (
        <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
          {disabledReason}
        </p>
      ) : null}

      <form className="mt-4 grid gap-3" onSubmit={submitCompare}>
        <label className="grid gap-2 text-sm font-medium">
          {labels.parameterSets}
          <textarea
            className="app-field min-h-24 rounded-[var(--app-radius-control)] px-3 py-2.5 font-mono text-sm tabular-nums"
            value={parameterSets}
            onChange={(event) => setParameterSets(event.target.value)}
            aria-label={labels.parameterSets}
          />
        </label>
        <span className="app-muted text-xs">
          {parameterSchema.some((param) => param.type === 'dict')
            ? locale === 'zh'
              ? `每行一个参数 JSON 对象；例如 ${exampleSet}`
              : `One JSON parameter object per line; for example ${exampleSet}`
            : labels.setsHint(parsedRuns.parsed.length, exampleSet)}
        </span>
        {error ? (
          <div
            className="border-l-2 border-[var(--app-danger-border)] py-2 pl-3 text-sm text-[var(--app-danger-text)]"
            role="alert"
          >
            {error}
          </div>
        ) : null}
        <div className="flex justify-end">
          <button
            type="submit"
            className="app-button-secondary rounded-[var(--app-radius-control)] px-4 py-2.5 text-sm font-semibold"
            disabled={compare.isPending || Boolean(disabledReason)}
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
          <div className="app-kicker app-type-overline">
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
      <div className="overflow-x-auto border-y border-[var(--app-divider)]">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="app-type-overline bg-[color-mix(in_srgb,var(--app-surface-0)_35%,transparent)] text-[var(--app-muted)]">
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
        <div className="border-l-2 border-[var(--app-warning-border)] py-2 pl-3 text-sm leading-6 text-[var(--app-warning-text)]">
          {response.warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
