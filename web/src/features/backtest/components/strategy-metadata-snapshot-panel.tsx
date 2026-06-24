import { BadgeCheck, SlidersHorizontal } from 'lucide-react';

import { useCopy } from '../../../app/copy';
import { usePreferences, type Locale } from '../../../app/preferences';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatPublicNote } from '../../../shared/public-labels';
import type {
  BacktestReport,
  StrategyMetadataSnapshot,
  StrategyParameterSchema,
} from '../api';

type ParamValue = number | string | boolean | null;

function snapshotFromReport(
  report: BacktestReport,
): StrategyMetadataSnapshot | null {
  return report.metrics_json?.strategy_metadata ?? null;
}

function formatValue(value: ParamValue | Record<string, unknown>) {
  if (value === null) {
    return 'null';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatList(
  values: string[] | undefined,
  fallback: string,
  formatter: (value: string) => string = (value) => value,
) {
  return values?.length ? values.map(formatter).join(', ') : fallback;
}

function translatedStrategyName(
  snapshot: StrategyMetadataSnapshot,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  return (
    labels.strategyNames[
      snapshot.strategy_id as keyof typeof labels.strategyNames
    ] ??
    snapshot.display_name ??
    snapshot.name ??
    snapshot.strategy_id
  );
}

function translatedStrategyDescription(
  snapshot: StrategyMetadataSnapshot,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  return (
    labels.strategyDescriptions[
      snapshot.strategy_id as keyof typeof labels.strategyDescriptions
    ] ??
    snapshot.description ??
    ''
  );
}

function translatedParameterLabel(
  name: string,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  return (labels.parameterLabels as Record<string, string>)[name] ?? name;
}

function translatedParameterDescription(
  parameter: StrategyParameterSchema,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  return (
    (labels.parameterDescriptions as Record<string, string>)[parameter.name] ??
    parameter.description
  );
}

function translatedValidationNote(
  note: string,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
  locale: Locale,
) {
  return (
    (labels.validationNotes as Record<string, string>)[note] ??
    formatPublicNote(note, locale)
  );
}

function translatedBenchmarkRole(
  role: string | null | undefined,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
  fallback: string,
) {
  if (!role) {
    return fallback;
  }
  return (labels.benchmarkRoleNames as Record<string, string>)[role] ?? role;
}

function translatedFrequency(
  frequency: string,
  labels: ReturnType<typeof useCopy>['backtest']['strategySnapshot'],
) {
  const normalized = frequency.trim().toLowerCase();
  if (['1d', 'daily', 'day'].includes(normalized)) {
    return labels.frequencyDaily;
  }
  if (['1m', 'minute', 'min'].includes(normalized)) {
    return labels.frequencyMinute;
  }
  if (normalized === 'tick') {
    return labels.frequencyTick;
  }
  return frequency;
}

function boundsLabel(
  parameter: StrategyParameterSchema,
  labels: ReturnType<typeof useCopy>['backtest']['strategySnapshot'],
) {
  if (parameter.allowed_values?.length) {
    return parameter.allowed_values.map(String).join(', ');
  }
  if (parameter.min !== undefined && parameter.min !== null) {
    if (parameter.max !== undefined && parameter.max !== null) {
      return labels.minMax(String(parameter.min), String(parameter.max));
    }
    return `>= ${parameter.min}`;
  }
  if (parameter.max !== undefined && parameter.max !== null) {
    return `<= ${parameter.max}`;
  }
  return labels.noBounds;
}

export function StrategyMetadataSnapshotPanel({
  report,
}: {
  report: BacktestReport;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.backtest.strategySnapshot;
  const pageLabels = copy.backtest.page;
  const commonLabels = copy.common;
  const snapshot = snapshotFromReport(report);

  if (!snapshot) {
    return null;
  }

  const description = translatedStrategyDescription(snapshot, pageLabels);
  const params = Object.entries(snapshot.params ?? {});
  const schema = snapshot.parameter_schema ?? [];

  return (
    <section className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <h3 className="app-card-title mt-1.5">{labels.title}</h3>
          <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
            {labels.subtitle}
          </p>
        </div>
        <span className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_30%,transparent)] p-2 text-[var(--app-muted)]">
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <SnapshotStat
          label={labels.strategy}
          value={translatedStrategyName(snapshot, pageLabels)}
        />
        <SnapshotStat
          label={labels.internalStrategyId}
          value={snapshot.strategy_id}
          mono
        />
        <SnapshotStat
          label={labels.benchmarkRole}
          value={translatedBenchmarkRole(
            snapshot.benchmark_role,
            pageLabels,
            labels.notDeclared,
          )}
        />
        <SnapshotStat
          label={labels.universe}
          value={formatList(
            snapshot.asset_universe,
            labels.notDeclared,
            (item) => formatAssetClassLabel(item, commonLabels),
          )}
        />
        <SnapshotStat
          label={labels.frequencies}
          value={formatList(
            snapshot.supported_frequencies,
            labels.notDeclared,
            (item) => translatedFrequency(item, labels),
          )}
        />
      </div>

      {description ? (
        <p className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 text-sm leading-6 text-[var(--app-text)]">
          {description}
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <BoundaryChip
          label={labels.validation}
          value={
            snapshot.requires_out_of_sample_validation
              ? labels.oosRequired
              : labels.notDeclared
          }
        />
        <BoundaryChip
          label={labels.validation}
          value={
            snapshot.requires_after_cost_report
              ? labels.afterCostRequired
              : labels.notDeclared
          }
        />
        <BoundaryChip
          label={labels.runParams}
          value={params.length ? `${params.length}` : labels.notDeclared}
        />
      </div>

      {params.length ? (
        <div className="mt-4">
          <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
            {labels.runParams}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {params.map(([name, value]) => (
              <span
                key={name}
                className="inline-flex min-w-0 flex-col rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-2"
              >
                <span className="text-sm font-semibold">
                  {translatedParameterLabel(name, pageLabels)}=
                  {formatValue(value)}
                </span>
                <span className="app-muted mt-0.5 text-[11px]">
                  {labels.apiField(name)}
                </span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {schema.length ? (
        <div className="mt-4 overflow-x-auto rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)]">
          <table className="min-w-[860px] w-full text-left text-sm">
            <thead className="bg-[color-mix(in_srgb,var(--app-surface-0)_35%,transparent)] text-xs uppercase tracking-[0.12em] text-[var(--app-muted)]">
              <tr>
                <th className="px-4 py-3 font-semibold">{labels.parameter}</th>
                <th className="px-4 py-3 font-semibold">{labels.type}</th>
                <th className="px-4 py-3 font-semibold">
                  {labels.defaultValue('')}
                </th>
                <th className="px-4 py-3 font-semibold">{labels.bounds}</th>
                <th className="px-4 py-3 font-semibold">
                  {labels.description}
                </th>
              </tr>
            </thead>
            <tbody>
              {schema.map((parameter) => (
                <tr
                  key={parameter.name}
                  className="border-t border-[color-mix(in_srgb,var(--app-border)_18%,transparent)]"
                >
                  <td className="px-4 py-3">
                    <div className="font-semibold">
                      {translatedParameterLabel(parameter.name, pageLabels)}
                    </div>
                    <div className="app-muted mt-0.5 text-[11px]">
                      {labels.apiField(parameter.name)}
                    </div>
                  </td>
                  <td className="px-4 py-3 tabular-nums">{parameter.type}</td>
                  <td className="px-4 py-3 tabular-nums">
                    {labels.defaultValue(formatValue(parameter.default))}
                  </td>
                  <td className="px-4 py-3 tabular-nums">
                    {boundsLabel(parameter, labels)}
                  </td>
                  <td className="px-4 py-3 leading-6">
                    {translatedParameterDescription(parameter, pageLabels)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {snapshot.validation_notes?.length ? (
        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3">
          <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
            {labels.validationNotes}
          </div>
          <ul className="mt-2 space-y-2 text-sm leading-6 text-[var(--app-text)]">
            {snapshot.validation_notes.map((note) => (
              <li key={note}>
                {translatedValidationNote(note, pageLabels, locale)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function SnapshotStat({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-3">
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {label}
      </div>
      <div
        className={`mt-1.5 truncate text-sm font-semibold ${mono ? 'font-mono' : ''}`}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function BoundaryChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2">
      <span className="app-muted min-w-0 truncate text-xs">{label}</span>
      <span className="inline-flex items-center gap-1 text-sm font-semibold">
        <BadgeCheck className="h-3.5 w-3.5 text-[#a6e3a1]" aria-hidden="true" />
        {value}
      </span>
    </div>
  );
}
