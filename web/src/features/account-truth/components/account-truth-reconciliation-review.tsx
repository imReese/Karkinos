import { useState, type ReactNode } from 'react';

import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import {
  formatPublicNote,
  formatPublicOperationalNote,
  formatPublicReviewActionLabel,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatLedgerEvidenceReference } from '../../../shared/ledger-format';
import {
  ControlledActionZone,
  EvidenceIdentityDisclosure,
  EvidenceState,
  StatusBadge,
} from '../../../shared/ui/workbench';
import type { ReconciliationItem, ReviewStatus } from '../api';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import {
  formatCode,
  formatReconciliationValue,
  statusTone,
} from './account-truth-review-format';

export type IndexedReconciliationItem = {
  id: string;
  item: ReconciliationItem;
};

const reviewActions: ReviewStatus[] = [
  'accepted',
  'ignored',
  'known_difference',
  'ledger_candidate',
  'needs_investigation',
];

export function AccountTruthDisclosure({
  children,
  defaultOpen = false,
  detail,
  id,
  testId,
  title,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  detail: string;
  id?: string;
  testId: string;
  title: string;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <details
      className="group min-w-0"
      data-testid={testId}
      id={id}
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-start justify-between gap-4 border-y border-[var(--app-divider)] py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
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
          className="shrink-0 text-sm text-[var(--app-text-tertiary)] group-open:rotate-45"
        >
          +
        </span>
      </summary>
      <div className="min-w-0 pt-3">{children}</div>
    </details>
  );
}

export function ReconciliationItemList({
  ariaLabel,
  entries,
  locale,
  onSelect,
  selectedIdentity,
}: {
  ariaLabel: string;
  entries: IndexedReconciliationItem[];
  locale: 'en' | 'zh';
  onSelect: (identity: string) => void;
  selectedIdentity: string | null;
}) {
  const text = labels[locale];
  return (
    <div
      aria-label={ariaLabel}
      className="max-h-[34rem] min-w-0 divide-y divide-[var(--app-divider)] overflow-y-auto overscroll-y-contain border-y border-[var(--app-divider)]"
      role="list"
    >
      {entries.map(({ id, item }) => {
        const itemTitle = item.symbol
          ? formatInstrumentDisplayLabel({
              symbol: item.symbol,
              display_name: item.display_name ?? null,
            })
          : formatCode(item.category, locale, 'code');
        return (
          <div key={id} role="listitem">
            <button
              aria-label={`${text.selectItem}: ${itemTitle}`}
              aria-pressed={selectedIdentity === id}
              className={`grid min-h-14 w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 gap-y-1 px-2 py-2.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
                selectedIdentity === id ? 'bg-[var(--app-accent-bg)]' : ''
              }`}
              data-testid={`account-truth-item-selector-${item.item_key}`}
              onClick={() => onSelect(id)}
              type="button"
            >
              <StatusBadge tone={statusTone(item.status)}>
                {formatCode(item.status, locale, 'status')}
              </StatusBadge>
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold text-[var(--app-text)]">
                  {itemTitle}
                </span>
                <span className="app-type-micro mt-0.5 block truncate text-[var(--app-text-secondary)]">
                  {formatCode(item.category, locale, 'code')} ·{' '}
                  {text.difference}{' '}
                  {formatReconciliationValue(
                    item.category,
                    item.difference,
                    locale,
                  )}
                </span>
              </span>
            </button>
          </div>
        );
      })}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <div className="app-type-micro truncate font-medium text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div className="mt-0.5 text-base font-semibold text-[var(--app-text)] tabular-nums">
        {value}
      </div>
    </div>
  );
}

export function MissingEvidenceCallout({ locale }: { locale: 'en' | 'zh' }) {
  const text = labels[locale];
  return (
    <div className="mt-4 border-l-2 border-[var(--app-warning-indicator)] py-1 pl-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {text.notReadyTitle}
      </div>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {text.notReadyBody}
      </p>
      <div className="mt-3 border-t border-[var(--app-divider)] pt-3">
        <div className="app-type-overline text-[var(--app-text-tertiary)]">
          {text.workflowTitle}
        </div>
        <ol className="mt-2 grid gap-2 text-xs font-medium text-[var(--app-text-secondary)]">
          {text.workflowSteps.map((step, index) => (
            <li
              key={step}
              className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2"
            >
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-[var(--app-radius-control)] border border-[var(--app-accent-border)] text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-accent)]">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  body,
  locale,
}: {
  title: string;
  body: string;
  locale: 'en' | 'zh';
}) {
  const text = labels[locale];
  return (
    <div className="border-l-2 border-[var(--app-warning-indicator)] px-3 py-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {title}
      </div>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {body}
      </p>
      <div className="mt-2 text-xs font-medium text-[var(--app-text-secondary)]">
        {text.workflowSteps[0]} → {text.workflowSteps[1]}
      </div>
    </div>
  );
}

export function ReasonList({
  title,
  values,
  locale,
}: {
  title: string;
  values: string[];
  locale: 'en' | 'zh';
}) {
  if (values.length === 0) {
    return null;
  }
  return (
    <div className="mt-4">
      <div className="app-type-overline text-[var(--app-muted)]">{title}</div>
      <div className="mt-2 grid gap-2">
        {values.map((value) => (
          <div
            key={value}
            className="border-l-2 border-[var(--app-divider)] py-1 pl-3 text-xs font-medium leading-5 text-[var(--app-text-secondary)]"
          >
            {formatCode(value, locale, 'code')}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReviewItemCard({
  item,
  importRunId,
  locale,
  reviewPending,
  onReview,
}: {
  item: ReconciliationItem;
  importRunId: string;
  locale: 'en' | 'zh';
  reviewPending: boolean;
  onReview: (status: ReviewStatus) => void;
}) {
  const text = labels[locale];
  const itemTitle = item.symbol
    ? formatInstrumentDisplayLabel({
        symbol: item.symbol,
        display_name: item.display_name ?? null,
      })
    : formatCode(item.category, locale, 'code');
  const latestReviewNote = formatPublicOperationalNote(
    item.latest_review?.note,
    locale,
  );
  const evidenceInstrumentNames =
    item.symbol && item.display_name
      ? new Map([[item.symbol.toLowerCase(), item.display_name]])
      : undefined;
  const detailContextEntries = Object.entries(item.detail_context ?? {}).filter(
    ([, value]) => value.trim().length > 0,
  );
  const reviewControls = (
    <ControlledActionZone
      title={text.auditDecision}
      description={text.auditDecisionDetail}
      evidence={text.safety}
      layout="stack"
      tone="info"
    >
      <div className="flex max-w-full flex-wrap gap-2">
        {reviewActions.map((action) => (
          <button
            key={action}
            type="button"
            className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={reviewPending}
            onClick={() => onReview(action)}
          >
            {formatPublicReviewActionLabel(action, locale)}
          </button>
        ))}
      </div>
    </ControlledActionZone>
  );
  return (
    <article
      className="min-w-0 rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3 sm:p-4"
      data-testid={`account-truth-item-${item.item_key}`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <StatusBadge tone={statusTone(item.status)}>
              {formatCode(item.status, locale, 'status')}
            </StatusBadge>
            <span className="text-base font-semibold text-[var(--app-text)]">
              {itemTitle}
            </span>
            <span className="text-xs font-medium text-[var(--app-text-tertiary)]">
              {formatCode(item.category, locale, 'code')}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-[var(--app-text-secondary)]">
            {formatPublicNote(item.detail_code ?? item.detail, locale)}
          </p>
        </div>
        <EvidenceIdentityDisclosure
          triggerLabel={text.openEvidence}
          title={text.evidenceDetail}
          description={itemTitle}
          closeLabel={text.closeEvidence}
          copyLabel={text.copyEvidence}
          copiedLabel={text.copiedEvidence}
          fields={[
            {
              label: text.importRunIdentity,
              value: importRunId,
              mono: true,
            },
            {
              label: text.itemIdentity,
              value: item.item_key,
              mono: true,
            },
            ...item.evidence_references.map((reference, index) => ({
              label: text.evidenceReference(index + 1),
              value: formatLedgerEvidenceReference(
                reference,
                locale,
                evidenceInstrumentNames,
              ),
              copyValue: reference,
              mono: true,
            })),
          ]}
        />
      </div>

      {detailContextEntries.length > 0 ? (
        <dl className="mt-3 grid divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] text-xs sm:grid-cols-2 sm:divide-y-0">
          {detailContextEntries.map(([key, value]) => (
            <div
              key={key}
              className="grid min-w-0 gap-1 py-2 sm:border-b sm:border-[var(--app-divider)] sm:px-2"
            >
              <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                {formatCode(key, locale, 'code')}
              </dt>
              <dd className="text-[var(--app-text-secondary)]">
                {formatCode(value, locale, 'code')}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <div className="mt-4 grid grid-cols-1 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <Metric
          label={text.broker}
          value={`${text.broker} ${formatReconciliationValue(
            item.category,
            item.broker_value,
            locale,
          )}`}
        />
        <Metric
          label={text.karkinos}
          value={`${text.karkinos} ${formatReconciliationValue(
            item.category,
            item.karkinos_value,
            locale,
          )}`}
        />
        <Metric
          label={text.difference}
          value={`${text.difference} ${formatReconciliationValue(
            item.category,
            item.difference,
            locale,
          )}`}
        />
      </div>

      {item.suggested_review_action ? (
        <div className="border-t border-[var(--app-divider)] py-3">
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
            {text.suggestedAction}
          </div>
          <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
            {formatCode(item.suggested_review_action || '--', locale, 'code')}
          </div>
        </div>
      ) : null}

      {item.latest_review ? (
        <EvidenceState
          className="mt-4"
          kind={item.latest_review.is_current === false ? 'stale' : 'ready'}
          title={`${text.latestReview}: ${formatPublicStatus(
            item.latest_review.review_status,
            locale,
          )}`}
          description={
            <>
              <span className="block">
                {item.latest_review.is_current === false
                  ? text.staleReview
                  : text.currentReview}
              </span>
              {latestReviewNote ? (
                <span className="mt-1 block">{latestReviewNote}</span>
              ) : null}
            </>
          }
        />
      ) : null}

      {item.status === 'pass' ? (
        <details className="mt-4 border-y border-[var(--app-divider)]">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
            {text.showAuditActions}
            <span aria-hidden="true">+</span>
          </summary>
          <div className="pb-3">{reviewControls}</div>
        </details>
      ) : (
        <div className="mt-4">{reviewControls}</div>
      )}
    </article>
  );
}
