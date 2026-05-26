import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import type { LedgerEntry } from '../api';

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
    <div className="app-panel overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div>
          <div className="app-product-mark">{labels.kicker}</div>
          <h2 className="mt-2 text-base font-semibold">{labels.title}</h2>
        </div>
        <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-soft)]">
          {labels.count(entries.length)}
        </span>
      </div>
      <div className="overflow-x-auto">
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
                      {resolveInstrumentName(entry)}
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
                    <div className="app-muted mt-1 text-xs">
                      {formatExecution(entry)}
                    </div>
                  </td>
                  <td className="max-w-[280px] px-5 py-4 align-top text-[var(--app-muted)]">
                    <span className="line-clamp-2 break-words">
                      {formatPublicNote(entry.note) ?? labels.noDetail}
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
  const grossAmount = entryAmount(entry);
  const entryType = entry.entry_type.trim().toLowerCase();
  if (entryType === 'trade_buy') {
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
  if (entryType === 'trade_sell') {
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
  if (entryType === 'cash_deposit') {
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
  if (entryType === 'cash_withdrawal') {
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
  if (entryType === 'dividend') {
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
  if (entryType === 'manual_adjustment') {
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

function entryAmount(entry: LedgerEntry) {
  if (entry.amount !== null) {
    return entry.amount;
  }
  if (entry.price !== null && entry.quantity !== null) {
    return entry.price * entry.quantity;
  }
  return null;
}

function formatSignedCurrency(value: number | null) {
  if (value === null || !Number.isFinite(value)) {
    return '--';
  }
  const prefix = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${prefix}${formatCurrency(Math.abs(value))}`;
}

function formatExecution(entry: LedgerEntry) {
  if (entry.quantity === null && entry.price === null) {
    return '--';
  }
  return `${formatQuantity(entry.quantity)} @ ${formatPrice(entry.price)}`;
}

function resolveInstrumentName(entry: LedgerEntry) {
  const noteName = readableNoteSegments(entry.note).find(
    (segment) =>
      /[\u4e00-\u9fff]/.test(segment) &&
      !segment.includes('用户记录') &&
      !segment.includes('保存') &&
      !segment.includes('加仓') &&
      !segment.includes('成本价'),
  );
  return noteName ?? entry.symbol ?? '--';
}

function formatPublicNote(note: string | null | undefined) {
  const segments = readableNoteSegments(note)
    .filter((segment) => !looksLikeInstrumentNameOnly(segment))
    .map((segment) => segment.replace(/^用户记录[:：]\s*/, '').trim())
    .filter(Boolean);
  return segments.length > 0 ? segments.slice(0, 2).join(' · ') : null;
}

function readableNoteSegments(note: string | null | undefined) {
  if (!note) {
    return [];
  }
  return note
    .split('|')
    .map((segment) => segment.trim())
    .filter((segment) => segment && !isTechnicalNoteSegment(segment));
}

function isTechnicalNoteSegment(segment: string) {
  return (
    /(^|\s)[a-z][a-z0-9_]*=/i.test(segment) ||
    /auto-confirmed/i.test(segment) ||
    /confirmed_(trade_date|nav|quantity)/i.test(segment) ||
    /gross_amount/i.test(segment)
  );
}

function looksLikeInstrumentNameOnly(segment: string) {
  return /^[\u4e00-\u9fffA-Za-z0-9（）()·\-\s]+[A-C]?$/.test(segment);
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
  const normalized = assetClass.trim().toLowerCase();
  if (normalized === 'fund') return copy.common.assetClassFund;
  if (normalized === 'etf') return copy.common.assetClassEtf;
  if (normalized === 'gold') return copy.common.assetClassGold;
  if (normalized === 'bond') return copy.common.assetClassBond;
  return copy.common.assetClassStock;
}
