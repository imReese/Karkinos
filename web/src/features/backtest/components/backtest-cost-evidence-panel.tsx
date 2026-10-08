import { usePreferences } from '../../../shared/preferences/context';
import { formatPercent } from '../../../shared/format';
import { StatusBadge } from '../../../shared/ui/workbench';
import type {
  BacktestReport,
  BacktestEffectiveCosts,
  BacktestCapacityReview,
} from '../api';
import { backtestCostCopy } from '../copy-costs';
import { readBacktestEffectiveCosts } from '../cost-contracts';

function numeric(value: string | number | undefined, scale = 1) {
  if (value === undefined || value === null || value === '') return '—';
  const number = Number(value) * scale;
  return Number.isFinite(number)
    ? new Intl.NumberFormat('en', { maximumFractionDigits: 6 }).format(number)
    : '—';
}

export function BacktestCostEvidencePanel({
  report,
}: {
  report: BacktestReport;
}) {
  const { locale } = usePreferences();
  const labels = backtestCostCopy[locale];
  return (
    <section
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      aria-label={labels.report}
    >
      <h3 className="text-sm font-semibold">{labels.report}</h3>
      <BacktestEffectiveCostsView
        costs={report.metrics_json?.cost_assumptions}
      />
      <CostSensitivity report={report} />
      <CapacityReview capacity={report.metrics_json?.capacity_review} />
    </section>
  );
}

export function BacktestEffectiveCostsView({
  costs: recordedCosts,
  recordedLabel,
}: {
  costs?: BacktestEffectiveCosts | null;
  recordedLabel?: string;
}) {
  const { locale } = usePreferences();
  const labels = backtestCostCopy[locale];
  const costs = readBacktestEffectiveCosts(recordedCosts);
  if (!costs) {
    return (
      <p className="app-muted mt-3 text-xs leading-5">
        {recordedCosts ? labels.unsupportedCosts : labels.missingCosts}
      </p>
    );
  }
  const rows = (['stock', 'etf', 'bond', 'gold'] as const).flatMap((asset) =>
    costs[asset] ? [{ asset, fees: costs[asset] }] : [],
  );
  return (
    <div className="mt-3 min-w-0">
      <p className="app-muted text-xs">{recordedLabel ?? labels.recorded}</p>
      <dl className="mt-2 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="app-muted text-xs">{labels.slippage}</dt>
          <dd className="mt-1 font-mono tabular-nums">
            {numeric(costs.slippage_bps)} {labels.bps}
          </dd>
        </div>
        <div>
          <dt className="app-muted text-xs">{labels.participation}</dt>
          <dd className="mt-1 font-mono tabular-nums">
            {costs.max_volume_participation === undefined
              ? labels.participationMissing
              : `${numeric(costs.max_volume_participation, 100)}%`}
          </dd>
        </div>
      </dl>
      {costs.commission_model_reference ? (
        <div className="app-muted mt-3 break-words text-xs leading-5">
          <p>
            {labels.commissionReference}:{' '}
            <span className="font-mono">
              {costs.commission_model_reference}
            </span>
          </p>
          <p>{labels.commissionReferenceDetail}</p>
        </div>
      ) : null}
      {rows.length ? (
        <div
          className="mt-3 min-w-0 overflow-x-auto"
          role="region"
          aria-label={recordedLabel ?? labels.recorded}
          tabIndex={0}
        >
          <table className="w-full min-w-[680px] text-left text-xs">
            <caption className="sr-only">
              {recordedLabel ?? labels.recorded}
            </caption>
            <thead className="app-muted">
              <tr>
                {[
                  labels.asset,
                  labels.commission,
                  labels.minimum,
                  labels.stamp,
                  labels.transfer,
                  labels.other,
                ].map((label) => (
                  <th key={label} className="px-2 py-2 font-medium">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ asset, fees }) => (
                <tr
                  key={asset}
                  className="border-t border-[var(--app-divider)]"
                >
                  <th scope="row" className="px-2 py-2 font-medium">
                    {labels[asset]}
                  </th>
                  {[
                    numeric(fees.commission_rate, 10000),
                    numeric(fees.min_commission),
                    numeric(fees.sell_stamp_tax_rate, 10000),
                    numeric(fees.transfer_fee_rate, 10000),
                    numeric(fees.other_fee_rate, 10000),
                  ].map((value, index) => (
                    <td
                      key={index}
                      className="px-2 py-2 font-mono tabular-nums"
                    >
                      {value}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <details className="mt-3 min-w-0 text-xs">
        <summary className="cursor-pointer font-medium">
          {labels.recordedNotes}
        </summary>
        <dl className="mt-2 space-y-1">
          {rows
            .filter(({ fees }) => fees.fee_rule_id)
            .map(({ asset, fees }) => (
              <div key={asset} className="break-words">
                <dt className="inline app-muted">{labels[asset]}: </dt>
                <dd className="inline font-mono">{fees.fee_rule_id}</dd>
              </div>
            ))}
        </dl>
        {costs.limitations?.length ? (
          <ul className="app-muted mt-2 list-disc space-y-1 pl-4 leading-5">
            {costs.limitations.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
      </details>
    </div>
  );
}

function CostSensitivity({ report }: { report: BacktestReport }) {
  const { locale } = usePreferences();
  const labels = backtestCostCopy[locale];
  const scenarios = report.metrics_json?.cost_sensitivity;
  const baseCosts = readBacktestEffectiveCosts(
    report.metrics_json?.cost_assumptions,
  );
  const normalized = Array.isArray(scenarios)
    ? scenarios.map((scenario) => ({
        ...scenario,
        costs: readBacktestEffectiveCosts(
          scenario &&
            typeof scenario === 'object' &&
            'cost_assumptions' in scenario
            ? scenario.cost_assumptions
            : scenario,
        ),
      }))
    : [];
  const supported =
    baseCosts &&
    Number.isFinite(report.metrics.total_return) &&
    Number.isFinite(report.metrics.max_drawdown) &&
    normalized.every(
      (scenario) =>
        scenario.costs &&
        [
          scenario.total_return,
          scenario.max_drawdown,
          scenario.fill_count,
        ].every(Number.isFinite) &&
        Number.isInteger(scenario.fill_count) &&
        scenario.fill_count >= 0,
    );
  const rows =
    supported && scenarios?.length
      ? [
          {
            name: labels.baseScenario,
            costs: baseCosts,
            netReturn: report.metrics.total_return,
            drawdown: report.metrics.max_drawdown,
            fills:
              report.cost_summary_json?.total_trades ??
              report.metrics.total_trades,
          },
          ...normalized.map((scenario) => ({
            name: labels.stressScenario,
            costs: scenario.costs,
            netReturn: scenario.total_return,
            drawdown: scenario.max_drawdown,
            fills: scenario.fill_count,
          })),
        ]
      : [];
  return (
    <div className="mt-4 min-w-0 border-t border-[var(--app-divider)] pt-3">
      <h4 className="text-xs font-semibold">{labels.sensitivity}</h4>
      {rows.length ? (
        <>
          <p className="app-muted mt-2 text-xs leading-5">
            {labels.sensitivityDetail}
          </p>
          <div
            className="mt-3 min-w-0 overflow-x-auto"
            role="region"
            aria-label={labels.sensitivity}
            tabIndex={0}
          >
            <table className="w-full min-w-[650px] text-left text-xs">
              <caption className="sr-only">{labels.sensitivity}</caption>
              <thead className="app-muted">
                <tr>
                  {[
                    labels.scenario,
                    labels.slippage,
                    labels.participation,
                    labels.netReturn,
                    labels.maxDrawdown,
                    labels.fills,
                  ].map((label) => (
                    <th key={label} className="px-2 py-2 font-medium">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr
                    key={index}
                    className="border-t border-[var(--app-divider)]"
                  >
                    <th scope="row" className="px-2 py-2 font-medium">
                      {row.name}
                    </th>
                    <td className="px-2 py-2 font-mono tabular-nums">
                      {numeric(row.costs?.slippage_bps)} {labels.bps}
                    </td>
                    <td className="px-2 py-2 font-mono tabular-nums">
                      {row.costs?.max_volume_participation === undefined
                        ? labels.participationMissing
                        : `${numeric(row.costs.max_volume_participation, 100)}%`}
                    </td>
                    <td className="px-2 py-2 font-mono tabular-nums">
                      {formatPercent(row.netReturn)}
                    </td>
                    <td className="px-2 py-2 font-mono tabular-nums">
                      {formatPercent(row.drawdown)}
                    </td>
                    <td className="px-2 py-2 font-mono tabular-nums">
                      {numeric(row.fills)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="app-muted mt-2 text-xs leading-5">
          {scenarios == null || (Array.isArray(scenarios) && !scenarios.length)
            ? labels.sensitivityMissing
            : labels.sensitivityUnsupported}
        </p>
      )}
    </div>
  );
}

function CapacityReview({
  capacity,
}: {
  capacity?: BacktestCapacityReview | null;
}) {
  const { locale } = usePreferences();
  const labels = backtestCostCopy[locale];
  const legacy = capacity?.schema_version === 'karkinos.backtest_capacity.v1';
  if (
    !capacity ||
    (!legacy && capacity.schema_version !== 'karkinos.backtest_capacity.v2')
  ) {
    return (
      <p className="app-muted mt-3 text-xs leading-5">
        {capacity ? labels.unsupportedCapacity : labels.missingCapacity}
      </p>
    );
  }
  return (
    <div className="mt-4 border-t border-[var(--app-divider)] pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-semibold">{labels.capacity}</h4>
        <StatusBadge
          tone={capacity.status === 'pass' && !legacy ? 'success' : 'warning'}
        >
          {capacity.status === 'pass' ? labels.passed : labels.blocked}
        </StatusBadge>
      </div>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        {[
          [
            labels.capital,
            `${numeric(capacity.capacity_utilization_pct, 100)}%`,
          ],
          [
            labels.liquidity,
            `${numeric(capacity.liquidity_utilization_pct, 100)}%`,
          ],
          [
            labels.ceiling,
            `${numeric(capacity.max_daily_volume_participation, 100)}%`,
          ],
          [
            labels.observations,
            `${numeric(capacity.observation_count)} / ${numeric(capacity.fill_count)}`,
          ],
        ].map(([label, value]) => (
          <div key={label}>
            <dt className="app-muted text-xs">{label}</dt>
            <dd className="mt-1 font-mono text-sm tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="app-muted mt-3 text-xs leading-5">
        {legacy ? labels.legacyCapacity : labels.capacityDetail}
      </p>
      {capacity.issues?.length ? (
        <div className="mt-2 text-xs text-[var(--app-warning-text)]">
          <p>{labels.issues}</p>
          <ul className="mt-1 list-disc space-y-1 break-words pl-4">
            {capacity.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {capacity.assumptions?.length || capacity.limitations?.length ? (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer font-medium">
            {labels.recordedNotes}
          </summary>
          <ul className="app-muted mt-2 list-disc space-y-1 pl-4 leading-5">
            {[
              ...(capacity.assumptions ?? []),
              ...(capacity.limitations ?? []),
            ].map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
