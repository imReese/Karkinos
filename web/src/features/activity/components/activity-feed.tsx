import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import type { LedgerEntry } from '../api';
import {
  formatLedgerPublicNote,
  resolveLedgerInstrumentName,
  summarizeLedgerEntry,
} from '../ledger-format';

export function ActivityFeed({ entries }: { entries: LedgerEntry[] }) {
  const copy = useCopy();
  const labels = copy.activity.feed;

  if (entries.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-5 text-sm app-muted">
        {labels.empty}
      </div>
    );
  }

  return (
    <div className="app-panel min-w-0 overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div>
          <div className="app-product-mark">{labels.kicker}</div>
          <h2 className="mt-2 text-base font-semibold">{labels.title}</h2>
        </div>
        <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-soft)]">
          {labels.count(entries.length)}
        </span>
      </div>
      <div className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
        <table className="app-data-table w-full min-w-[820px] text-left text-sm">
          <thead>
            <tr>
              <th className="px-5 py-3">{labels.columns.time}</th>
              <th className="px-5 py-3">{labels.columns.activity}</th>
              <th className="px-5 py-3">{labels.columns.instrument}</th>
              <th className="px-5 py-3 text-right">{labels.columns.amount}</th>
              <th className="px-5 py-3">{labels.columns.detail}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const summary = summarizeEntry(entry, copy);
              return (
                <tr key={entry.id}>
                  <td className="px-5 py-4 align-top">
                    <div className="font-mono text-xs font-semibold text-[var(--app-soft)]">
                      {formatTimestamp(entry.timestamp)}
                    </div>
                    <div className="app-muted mt-1 text-[11px]">
                      {formatSource(entry.source, labels)}
                    </div>
                  </td>
                  <td className="px-5 py-4 align-top">
                    <div className="flex items-center gap-3">
                      <span
                        className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold ${summary.badgeClass}`}
                      >
                        {summary.shortLabel}
                      </span>
                      <div>
                        <div className="font-semibold">{summary.label}</div>
                        <div className="app-muted mt-1 text-xs">
                          {summary.cashImpactLabel}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4 align-top">
                    <div className="font-semibold">
                      {resolveLedgerInstrumentName(entry) || '--'}
                    </div>
                    <div className="app-muted mt-1 flex items-center gap-2 text-xs">
                      <span>{entry.symbol ?? '--'}</span>
                      <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]">
                        {formatAssetClass(entry.asset_class, copy)}
                      </span>
                    </div>
                  </td>
                  <td
                    className={`px-5 py-4 text-right align-top font-mono text-sm font-semibold tabular-nums ${summary.amountClass}`}
                  >
                    {summary.amount}
                    <LedgerExecutionDetails entry={entry} labels={labels} />
                  </td>
                  <td className="max-w-[280px] px-5 py-4 align-top text-[var(--app-muted)]">
                    <span className="line-clamp-2 break-words">
                      {formatLedgerPublicNote(entry) ?? labels.noDetail}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function summarizeEntry(entry: LedgerEntry, copy: ReturnType<typeof useCopy>) {
  const labels = copy.activity.feed;
  const summary = summarizeLedgerEntry(entry);
  const grossAmount = summary.grossAmount;
  if (summary.kind === 'trade_buy') {
    return {
      label: labels.entryTypes.tradeBuy,
      shortLabel: labels.shortTypes.buy,
      amount: formatSignedCurrency(grossAmount === null ? null : -grossAmount),
      cashImpactLabel: labels.cashImpact.debit,
      amountClass: 'text-[var(--app-danger)]',
      badgeClass:
        'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]',
    };
  }
  if (summary.kind === 'trade_sell') {
    return {
      label: labels.entryTypes.tradeSell,
      shortLabel: labels.shortTypes.sell,
      amount: formatSignedCurrency(grossAmount),
      cashImpactLabel: labels.cashImpact.credit,
      amountClass: 'text-[var(--app-success)]',
      badgeClass:
        'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]',
    };
  }
  if (summary.kind === 'cash_deposit') {
    return {
      label: labels.entryTypes.cashDeposit,
      shortLabel: labels.shortTypes.cashIn,
      amount: formatSignedCurrency(grossAmount),
      cashImpactLabel: labels.cashImpact.credit,
      amountClass: 'text-[var(--app-success)]',
      badgeClass:
        'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]',
    };
  }
  if (summary.kind === 'cash_withdrawal') {
    return {
      label: labels.entryTypes.cashWithdrawal,
      shortLabel: labels.shortTypes.cashOut,
      amount: formatSignedCurrency(grossAmount === null ? null : -grossAmount),
      cashImpactLabel: labels.cashImpact.debit,
      amountClass: 'text-[var(--app-danger)]',
      badgeClass:
        'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]',
    };
  }
  if (summary.kind === 'dividend') {
    return {
      label: labels.entryTypes.dividend,
      shortLabel: labels.shortTypes.dividend,
      amount: formatSignedCurrency(grossAmount),
      cashImpactLabel: labels.cashImpact.credit,
      amountClass: 'text-[var(--app-success)]',
      badgeClass:
        'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]',
    };
  }
  if (summary.kind === 'manual_adjustment') {
    return {
      label: labels.entryTypes.adjustment,
      shortLabel: labels.shortTypes.adjustment,
      amount: formatCurrency(grossAmount),
      cashImpactLabel: labels.cashImpact.adjustment,
      amountClass: 'text-[var(--app-soft)]',
      badgeClass:
        'bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-soft)] ring-1 ring-[color-mix(in_srgb,var(--app-border)_34%,transparent)]',
    };
  }
  return {
    label: labels.entryTypes.other,
    shortLabel: labels.shortTypes.other,
    amount: formatCurrency(grossAmount),
    cashImpactLabel: labels.cashImpact.neutral,
    amountClass: 'text-[var(--app-soft)]',
    badgeClass:
      'bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-soft)] ring-1 ring-[color-mix(in_srgb,var(--app-border)_34%,transparent)]',
  };
}

function formatSignedCurrency(value: number | null) {
  if (value === null || !Number.isFinite(value)) {
    return '--';
  }
  const prefix = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${prefix}${formatCurrency(Math.abs(value))}`;
}

function LedgerExecutionDetails({
  entry,
  labels,
}: {
  entry: LedgerEntry;
  labels: ReturnType<typeof useCopy>['activity']['feed'];
}) {
  const details = [
    {
      label: labels.detailFields.amount,
      value:
        entry.amount === null || !Number.isFinite(entry.amount)
          ? null
          : formatCurrency(entry.amount),
    },
    {
      label: labels.detailFields.quantity,
      value:
        entry.quantity === null || !Number.isFinite(entry.quantity)
          ? null
          : formatQuantity(entry.quantity),
    },
    {
      label: labels.detailFields.price,
      value:
        entry.price === null || !Number.isFinite(entry.price)
          ? null
          : formatCurrency(entry.price),
    },
    {
      label: labels.detailFields.fee,
      value: formatCurrency(entry.commission),
    },
  ].filter((item) => item.value !== null);

  if (details.length === 0) {
    return <div className="app-muted mt-1 text-xs">--</div>;
  }

  return (
    <div className="app-muted mt-1 flex flex-col items-end gap-0.5 text-xs">
      {details.map((item) => (
        <span key={item.label}>
          {item.label} {item.value}
        </span>
      ))}
    </div>
  );
}

function formatSource(
  source: string | null | undefined,
  labels: ReturnType<typeof useCopy>['activity']['feed'],
) {
  const normalized = (source ?? '').trim().toLowerCase();
  if (normalized === 'manual') {
    return labels.sources.manual;
  }
  if (normalized === 'system') {
    return labels.sources.system;
  }
  return source || labels.sources.unknown;
}

function formatAssetClass(
  assetClass: string,
  copy: ReturnType<typeof useCopy>,
) {
  return formatAssetClassLabel(assetClass, copy.common);
}
