import { usePreferences } from '../../../shared/preferences/context';
import { StatusBadge } from '../../../shared/ui/workbench';
import type {
  BacktestReport,
  BacktestEffectiveCosts,
  BacktestCapacityReview,
} from '../api';
import { backtestCostCopy } from '../copy-costs';

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
      <EffectiveCosts costs={report.metrics_json?.cost_assumptions} />
      <CapacityReview capacity={report.metrics_json?.capacity_review} />
    </section>
  );
}

function EffectiveCosts({ costs }: { costs?: BacktestEffectiveCosts | null }) {
  const { locale } = usePreferences();
  const labels = backtestCostCopy[locale];
  if (
    !costs ||
    costs.schema_version !== 'karkinos.backtest_cost_assumptions.v1' ||
    costs.slippage_model !== 'percent_of_reference_price'
  ) {
    return (
      <p className="app-muted mt-3 text-xs leading-5">
        {costs ? labels.unsupportedCosts : labels.missingCosts}
      </p>
    );
  }
  const rows = (['stock', 'etf', 'bond', 'gold'] as const).flatMap((asset) =>
    costs[asset] ? [{ asset, fees: costs[asset] }] : [],
  );
  return (
    <div className="mt-3 min-w-0">
      <p className="app-muted text-xs">{labels.recorded}</p>
      <dl className="mt-2 text-sm">
        <dt className="app-muted text-xs">{labels.slippage}</dt>
        <dd className="mt-1 font-mono tabular-nums">
          {numeric(costs.slippage_bps)} {labels.bps}
        </dd>
      </dl>
      <div
        className="mt-3 min-w-0 overflow-x-auto"
        role="region"
        aria-label={labels.recorded}
        tabIndex={0}
      >
        <table className="w-full min-w-[680px] text-left text-xs">
          <caption className="sr-only">{labels.recorded}</caption>
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
              <tr key={asset} className="border-t border-[var(--app-divider)]">
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
                  <td key={index} className="px-2 py-2 font-mono tabular-nums">
                    {value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
