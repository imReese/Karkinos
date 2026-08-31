import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicCode } from '../../../shared/public-labels';
import { ExceptionList } from '../../../shared/ui/workbench';
import type { PositionEvidenceReview } from '../api';

export function PortfolioEvidenceReviewPanel({
  copy,
  items,
  locale,
}: {
  copy: ReturnType<typeof useCopy>;
  items: PositionEvidenceReview[];
  locale: Locale;
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section
      data-testid="portfolio-position-evidence-review"
      className="min-w-0"
    >
      <div className="mb-2 flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.portfolio.evidenceReview.title}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.portfolio.evidenceReview.detail}
          </p>
        </div>
        <span className="text-xs font-semibold tabular-nums text-[var(--app-warning-text)]">
          {copy.portfolio.evidenceReview.count(items.length)}
        </span>
      </div>
      <ExceptionList
        ariaLabel={copy.portfolio.evidenceReview.title}
        emptyState={copy.portfolio.evidenceReview.detail}
        items={items.map((item) => ({
          id: item.position.symbol,
          severity: 'warning',
          statusLabel: locale === 'zh' ? '待复核' : 'Review',
          title:
            item.position.display_name ??
            item.position.name ??
            item.position.symbol,
          reason: item.reason_codes
            .map((reason) => formatPublicCode(reason, locale))
            .join(' · '),
          nextAction: (
            <a
              href="/account-truth"
              className="font-semibold text-[var(--app-accent)] hover:underline"
            >
              {locale === 'zh' ? '复核账户事实' : 'Review account truth'}
            </a>
          ),
          evidence: item.position.symbol,
        }))}
        labels={
          locale === 'zh'
            ? {
                reason: '原因',
                unblockCondition: '解除条件',
                nextAction: '安全下一步',
                evidence: '标的',
              }
            : {
                reason: 'Reason',
                unblockCondition: 'Unblock condition',
                nextAction: 'Safe next step',
                evidence: 'Instrument',
              }
        }
      />
    </section>
  );
}
