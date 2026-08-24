import { useCopy } from '../../../shared/i18n/context';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import type { BacktestStrategyInfo } from '../api';
import {
  strategyDescription,
  strategySourceDisplayName,
} from './backtest-page-model';

export function StrategyCatalogPanel({
  strategyCatalog,
  selectedStrategyName,
  onSelect,
}: {
  strategyCatalog: BacktestStrategyInfo[];
  selectedStrategyName: string;
  onSelect: (strategyName: string) => void;
}) {
  const labels = useCopy().backtest.page;
  const selectedStrategy =
    strategyCatalog.find((item) => item.name === selectedStrategyName) ??
    strategyCatalog[0];
  const selectedStrategyDisplayName = strategyDisplayName(
    selectedStrategy,
    labels.strategyNames,
  );
  const selectedDescription = strategyDescription(
    selectedStrategy,
    labels.strategyDescriptions,
  );
  const badges = [
    strategySourceDisplayName(selectedStrategy, labels),
    selectedStrategy.requires_out_of_sample_validation
      ? labels.oosRequired
      : null,
    selectedStrategy.requires_after_cost_report
      ? labels.afterCostRequired
      : null,
  ].filter(Boolean);

  return (
    <section className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4">
      <div
        className="grid min-w-0 gap-3 2xl:grid-cols-[minmax(0,1fr)_minmax(180px,240px)] 2xl:items-end"
        data-testid="backtest-strategy-catalog-header"
      >
        <div className="min-w-0">
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
            {labels.strategyCatalogKicker}
          </div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {labels.strategyCatalogTitle}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {labels.strategyCatalogDetail}
          </p>
        </div>
        <label className="grid min-w-0 gap-1.5 text-xs font-medium text-[var(--app-text-secondary)]">
          <span>{labels.strategy}</span>
          <select
            aria-label={labels.strategyCatalogTitle}
            className="app-field h-10 rounded-[var(--app-radius-control)] px-3 text-sm"
            value={selectedStrategy.name}
            onChange={(event) => onSelect(event.target.value)}
          >
            {strategyCatalog.map((item) => (
              <option key={item.strategy_id} value={item.name}>
                {strategyDisplayName(item, labels.strategyNames)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <details
        className="group mt-3 min-w-0 border-t border-[var(--app-divider)] pt-1"
        data-testid="backtest-strategy-detail-disclosure"
      >
        <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 py-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
          <span className="min-w-0">
            <span className="app-type-micro block font-medium text-[var(--app-text-tertiary)]">
              {labels.selectedStrategy}
            </span>
            <span className="app-type-subsection-title mt-0.5 block truncate text-[var(--app-text)]">
              {selectedStrategyDisplayName}
            </span>
          </span>
          <span
            aria-hidden="true"
            className="app-disclosure-chevron shrink-0 text-sm text-[var(--app-text-secondary)] group-open:rotate-180"
          >
            ▾
          </span>
        </summary>
        <div className="min-w-0 pb-2">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <p className="min-w-0 text-xs leading-5 text-[var(--app-text-secondary)]">
              {selectedDescription}
            </p>
            <code className="app-type-micro shrink-0 break-all font-mono text-[var(--app-text-tertiary)]">
              {selectedStrategy.strategy_id}
            </code>
          </div>
          {badges.length ? (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
              {badges.map((badge) => (
                <span
                  className="app-type-micro font-medium text-[var(--app-text-tertiary)]"
                  key={badge}
                >
                  {badge}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </details>
    </section>
  );
}
