import { formatTimestamp } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { StatusBadge } from '../../../shared/ui/workbench';
import type { DatasetDecisionAvailability } from '../api';

function hasFirstLateTime(
  value: object | null,
  count: number,
  timeField: 'available_at' | 'checked_at',
) {
  if (count === 0) {
    return value === null;
  }
  if (!value || typeof value !== 'object') {
    return false;
  }
  const row = value as Record<string, unknown>;
  return ['symbol', 'session_date', 'decision_at', timeField].every(
    (field) => typeof row[field] === 'string' && Boolean(row[field]),
  );
}

function isSupportedEvidence(
  value: DatasetDecisionAvailability | null | undefined,
): value is DatasetDecisionAvailability {
  if (
    value?.schema_version !== 'karkinos.dataset_decision_availability.v1' ||
    value.decision_time_basis !== 'bar_event_time' ||
    !['pass', 'blocked'].includes(value.status)
  ) {
    return false;
  }
  const counts = [
    value.checked_bar_count,
    value.late_bar_count,
    value.late_verification_count,
  ];
  return (
    counts.every((count) => Number.isInteger(count) && count >= 0) &&
    value.checked_bar_count > 0 &&
    value.late_bar_count <= value.checked_bar_count &&
    value.late_verification_count <= value.checked_bar_count &&
    hasFirstLateTime(
      value.first_late_bar,
      value.late_bar_count,
      'available_at',
    ) &&
    hasFirstLateTime(
      value.first_late_verification,
      value.late_verification_count,
      'checked_at',
    ) &&
    (value.status === 'blocked') ===
      (value.late_bar_count > 0 || value.late_verification_count > 0)
  );
}

export function DecisionAvailabilityPanel({
  availability,
  preview = false,
}: {
  availability: DatasetDecisionAvailability | null | undefined;
  preview?: boolean;
}) {
  const labels = useCopy().backtest.decisionAvailability;
  const evidence = isSupportedEvidence(availability) ? availability : null;
  const status = evidence?.status ?? 'not_evaluated';

  return (
    <section
      aria-label={labels.title}
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      data-testid="decision-availability-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">{labels.kicker}</div>
          <h4 className="app-type-subsection-title mt-1 text-[var(--app-text)]">
            {labels.title}
          </h4>
        </div>
        <StatusBadge
          tone={
            status === 'blocked'
              ? 'danger'
              : status === 'pass'
                ? 'neutral'
                : 'warning'
          }
        >
          {status === 'blocked'
            ? labels.blocked
            : status === 'pass'
              ? labels.pass
              : labels.notEvaluated}
        </StatusBadge>
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--app-text-secondary)]">
        {labels.scope}
      </p>
      {evidence ? (
        <>
          <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
            <Count
              label={labels.checkedBars}
              value={evidence.checked_bar_count}
            />
            <Count label={labels.lateBars} value={evidence.late_bar_count} />
            <Count
              label={labels.lateVerifications}
              value={evidence.late_verification_count}
            />
          </dl>
          {evidence.first_late_bar || evidence.first_late_verification ? (
            <dl className="mt-3 grid gap-3 text-xs lg:grid-cols-2">
              {evidence.first_late_bar ? (
                <LateEvidence
                  title={labels.firstLateBar}
                  symbol={evidence.first_late_bar.symbol}
                  sessionDate={evidence.first_late_bar.session_date}
                  decisionAt={evidence.first_late_bar.decision_at}
                  evidenceAt={evidence.first_late_bar.available_at}
                  evidenceLabel={labels.barAvailableAt}
                  decisionLabel={labels.replayTime}
                />
              ) : null}
              {evidence.first_late_verification ? (
                <LateEvidence
                  title={labels.firstLateVerification}
                  symbol={evidence.first_late_verification.symbol}
                  sessionDate={evidence.first_late_verification.session_date}
                  decisionAt={evidence.first_late_verification.decision_at}
                  evidenceAt={evidence.first_late_verification.checked_at}
                  evidenceLabel={labels.verificationTime}
                  decisionLabel={labels.replayTime}
                />
              ) : null}
            </dl>
          ) : null}
        </>
      ) : (
        <p className="mt-3 text-xs text-[var(--app-warning-text)]">
          {labels.missingEvidence}
        </p>
      )}
      <p className="mt-3 text-xs leading-5 text-[var(--app-warning-text)]">
        {preview ? labels.previewBoundary : labels.backtestBoundary}
      </p>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {labels.researchBoundary}
      </p>
    </section>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-l border-[var(--app-divider)] pl-3">
      <dt className="text-[var(--app-text-secondary)]">{label}</dt>
      <dd className="mt-1 font-mono font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function LateEvidence({
  title,
  symbol,
  sessionDate,
  decisionAt,
  evidenceAt,
  evidenceLabel,
  decisionLabel,
}: {
  title: string;
  symbol: string;
  sessionDate: string;
  decisionAt: string;
  evidenceAt: string;
  evidenceLabel: string;
  decisionLabel: string;
}) {
  return (
    <div className="border-l-2 border-[var(--app-warning-border)] pl-3">
      <dt className="font-semibold text-[var(--app-warning-text)]">
        {title}: {symbol} · {sessionDate}
      </dt>
      <dd className="mt-1 text-[var(--app-text-secondary)]">
        {decisionLabel}: {formatTimestamp(decisionAt)} · {evidenceLabel}:{' '}
        {formatTimestamp(evidenceAt)}
      </dd>
    </div>
  );
}
