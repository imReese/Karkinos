import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicNote } from '../../../shared/public-labels';
import type { BacktestStrategyInfo } from '../api';
import { benchmarkRoleDisplayName } from './backtest-page-model';

export function StrategyMetadataPanel({
  strategy,
  labels,
}: {
  strategy: BacktestStrategyInfo;
  labels: ReturnType<typeof useCopy>['backtest']['page'];
}) {
  const { locale } = usePreferences();
  const assetUniverse = strategy.asset_universe ?? strategy.benchmark_universe;
  const frequencies = strategy.supported_frequencies;
  const validationBadges = [
    strategy.requires_out_of_sample_validation ? labels.oosRequired : null,
    strategy.requires_after_cost_report ? labels.afterCostRequired : null,
  ].filter(Boolean);
  const validationNoteLabels: Record<string, string> = labels.validationNotes;

  return (
    <section className="border-y border-[var(--app-divider)] py-3">
      <div className="app-kicker app-type-overline">
        {labels.strategyMetadata}
      </div>
      <div className="mt-2 grid gap-x-4 sm:grid-cols-2">
        <MetadataItem
          label={labels.assetUniverse}
          value={formatMetadataList(assetUniverse, labels.notDeclared)}
        />
        <MetadataItem
          label={labels.supportedFrequencies}
          value={formatMetadataList(frequencies, labels.notDeclared)}
        />
        <MetadataItem
          label={labels.benchmarkRole}
          value={benchmarkRoleDisplayName(
            strategy.benchmark_role,
            labels.benchmarkRoleNames,
            labels.notDeclared,
          )}
        />
        <div className="min-w-0 border-t border-[var(--app-divider)] py-2.5">
          <div className="app-type-micro font-medium text-[var(--app-text-secondary)]">
            {labels.validationRequirements}
          </div>
          {validationBadges.length > 0 ? (
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
              {validationBadges.map((badge) => (
                <span
                  key={badge}
                  className="text-xs font-semibold text-[var(--app-text)]"
                >
                  {badge}
                </span>
              ))}
            </div>
          ) : (
            <div className="mt-1 text-sm font-semibold">
              {labels.notDeclared}
            </div>
          )}
        </div>
      </div>
      {strategy.validation_notes?.length ? (
        <ul className="mt-3 space-y-1 text-xs leading-5 text-[var(--app-muted)]">
          {strategy.validation_notes.map((note) => (
            <li key={note}>
              {validationNoteLabels[note] ?? formatPublicNote(note, locale)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function MetadataItem({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0 border-t border-[var(--app-divider)] py-2.5">
      <div className="app-type-micro font-medium text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div
        className="mt-0.5 break-words text-sm leading-5 font-semibold tabular-nums text-[var(--app-text)]"
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

export function formatMetadataList(
  values: string[] | undefined,
  fallback: string,
) {
  return values && values.length > 0 ? values.join(', ') : fallback;
}

export function SummaryValue({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'pnl-negative';
}) {
  return (
    <div>
      <div className="app-kicker app-type-overline">{label}</div>
      <div
        className={`mt-1 font-semibold ${tone === 'pnl-negative' ? 'text-[var(--app-pnl-negative)]' : 'text-[var(--app-text)]'}`}
      >
        {value}
      </div>
    </div>
  );
}
