import type { Locale } from '../../../shared/preferences/context';

export function RiskHistoryPager({
  kind,
  page,
  pageCount,
  totalItems,
  locale,
  onPageChange,
}: {
  kind: 'events' | 'timeline';
  page: number;
  pageCount: number;
  totalItems: number;
  locale: Locale;
  onPageChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;

  return (
    <div
      role="group"
      aria-label={
        locale === 'zh'
          ? kind === 'events'
            ? '影响事件分页'
            : '估值日分页'
          : kind === 'events'
            ? 'Impact event pagination'
            : 'Valuation day pagination'
      }
      className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--app-divider)] pt-3"
      data-testid={`risk-history-${kind}-pager`}
    >
      <span className="text-xs tabular-nums text-[var(--app-text-tertiary)]">
        {locale === 'zh'
          ? `第 ${page + 1} / ${pageCount} 页 · 共 ${totalItems} 条`
          : `Page ${page + 1} of ${pageCount} · ${totalItems} items`}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={page === 0}
          onClick={() => onPageChange(Math.max(0, page - 1))}
        >
          {locale === 'zh' ? '较新' : 'Newer'}
        </button>
        <button
          type="button"
          className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(Math.min(pageCount - 1, page + 1))}
        >
          {locale === 'zh' ? '较早' : 'Older'}
        </button>
      </div>
    </div>
  );
}
