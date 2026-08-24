import type { ReactNode } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import type { BacktestStrategyInfo } from '../api';
import { strategySourceDisplayName } from './backtest-page-model';

export function BacktestResponsiveDisclosure({
  detail,
  id,
  open,
  onToggle,
  testId,
  title,
  children,
}: {
  detail: string;
  id: string;
  open: boolean;
  onToggle: () => void;
  testId: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0">
      <button
        aria-controls={id}
        aria-expanded={open}
        className="flex min-h-11 w-full items-start justify-between gap-4 border-y border-[var(--app-divider)] py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
        data-testid={testId}
        onClick={onToggle}
        type="button"
      >
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-[var(--app-text)]">
            {title}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {detail}
          </span>
        </span>
        <span
          aria-hidden="true"
          className="shrink-0 text-sm text-[var(--app-text-tertiary)]"
        >
          {open ? '−' : '+'}
        </span>
      </button>
      <div className="min-w-0 space-y-5" hidden={!open} id={id}>
        {open ? children : null}
      </div>
    </section>
  );
}

export function RunReadinessSummary({
  assetClassLabel,
  labels,
  parameterCount,
  selectedStrategy,
  symbol,
}: {
  assetClassLabel: string;
  labels: ReturnType<typeof useCopy>['backtest']['page'];
  parameterCount: number;
  selectedStrategy: BacktestStrategyInfo;
  symbol: string;
}) {
  return (
    <section
      className="border-l-2 border-[var(--app-info-indicator)] py-1 pl-3"
      data-testid="backtest-run-readiness-summary"
    >
      <div className="min-w-0">
        <div className="app-kicker app-type-overline">
          {labels.runReadinessTitle}
        </div>
        <p className="app-muted mt-2 text-sm leading-6">
          {labels.runReadinessDetail}
        </p>
      </div>
      <div className="mt-3 grid gap-x-4 text-xs sm:grid-cols-2">
        <RunContextValue
          label={labels.runReadinessStrategy}
          value={strategyDisplayName(selectedStrategy, labels.strategyNames)}
        />
        <RunContextValue
          label={labels.runReadinessStrategySource}
          value={strategySourceDisplayName(selectedStrategy, labels)}
        />
        <RunContextValue
          label={labels.runReadinessInstrument}
          value={symbol.trim() || labels.notDeclared}
          numeric
        />
        <RunContextValue
          label={labels.runReadinessAssetClass}
          value={assetClassLabel}
        />
        <RunContextValue
          label={labels.runReadinessParams}
          value={labels.runReadinessParameterCount(parameterCount)}
        />
        <RunContextValue
          label={labels.runReadinessDataset}
          value={labels.runReadinessDatasetPending}
        />
      </div>
    </section>
  );
}

export function RunContextValue({
  label,
  value,
  numeric = false,
}: {
  label: string;
  value: string;
  numeric?: boolean;
}) {
  return (
    <div className="min-w-0 border-t border-[var(--app-divider)] py-2.5">
      <div className="app-type-micro font-medium text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div
        className={`mt-0.5 break-words text-sm leading-5 font-semibold text-[var(--app-text)] ${
          numeric ? 'tabular-nums' : ''
        }`}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}
