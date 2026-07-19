import { useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
import { EvidenceIdentityDisclosure } from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import { formatCurrency } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  useDecisionOutcomeReviewPreviewMutation,
  useRecordDecisionOutcomeReviewMutation,
  type DecisionOutcomeReviewTarget,
  type SignalJournalEntry,
} from '../api';

type ReviewDecision = 'acted' | 'ignored' | 'deferred' | 'blocked';
type ReviewOutcome = DecisionOutcomeReviewTarget['allowed_outcomes'][number];

const REVIEW_LABELS = {
  en: {
    acted: 'Acted',
    ignored: 'Ignored',
    deferred: 'Deferred',
    blocked: 'Blocked',
    evidence_supported: 'Supported by bound evidence',
    evidence_not_supported: 'Not supported by bound evidence',
    risk_gate_validated: 'Risk block validated',
    not_executed: 'Not executed',
    inconclusive: 'Inconclusive',
    fills_linked: 'Linked fills',
    order_recorded_no_fill: 'Order recorded; fill pending',
    risk_blocked_no_execution: 'Risk blocked; no execution',
    bound: 'Evidence bound',
    not_applicable: 'Not applicable',
  },
  zh: {
    acted: '已执行',
    ignored: '已忽略',
    deferred: '已延后',
    blocked: '已阻断',
    evidence_supported: '证据支持',
    evidence_not_supported: '证据不支持',
    risk_gate_validated: '风控阻断得到验证',
    not_executed: '未执行',
    inconclusive: '证据不足，暂不下结论',
    fills_linked: '成交已关联',
    order_recorded_no_fill: '订单已记录，成交待确认',
    risk_blocked_no_execution: '风控已阻断，未执行',
    bound: '证据已绑定',
    not_applicable: '不适用',
  },
} as const;

function reviewLabel(value: string, locale: 'en' | 'zh') {
  const labels = REVIEW_LABELS[locale] as Record<string, string>;
  return labels[value] ?? formatPublicStatus(value, locale);
}

function idempotencyKey(signalId: number) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`;
  return `decision-outcome-review:${signalId}:${suffix}`;
}

function defaultDecision(target: DecisionOutcomeReviewTarget): ReviewDecision {
  if (target.allowed_outcomes.includes('evidence_supported')) {
    return 'acted';
  }
  if (target.allowed_outcomes.includes('risk_gate_validated')) {
    return 'blocked';
  }
  return 'ignored';
}

function defaultOutcome(target: DecisionOutcomeReviewTarget): ReviewOutcome {
  if (target.allowed_outcomes.includes('not_executed')) {
    return 'not_executed';
  }
  return 'inconclusive';
}

export function DecisionOutcomeReviewPanel({
  entry,
}: {
  entry: SignalJournalEntry;
}) {
  const appCopy = useCopy();
  const { locale } = usePreferences();
  const signalId = entry.signal.id;
  const reviewSignalId = signalId ?? 0;
  const preview = useDecisionOutcomeReviewPreviewMutation();
  const record = useRecordDecisionOutcomeReviewMutation();
  const [expanded, setExpanded] = useState(false);
  const [reviewedBy, setReviewedBy] = useState('local-operator');
  const [decision, setDecision] = useState<ReviewDecision>('ignored');
  const [outcome, setOutcome] = useState<ReviewOutcome>('inconclusive');
  const [note, setNote] = useState('');
  const [requestKey] = useState(() => idempotencyKey(reviewSignalId));
  const labels = useMemo(
    () =>
      locale === 'zh'
        ? {
            open: '复盘决策结果',
            close: '收起复盘',
            loading: '正在读取持久化证据…',
            retry: '重新预览证据',
            execution: '执行证据',
            financial: '财务证据',
            snapshot: '估值快照',
            cutoff: '账本截止',
            blocked: '当前证据不能支持确定性结果判断',
            reviewer: '复核人',
            decision: '人工决策',
            outcome: '结果结论',
            note: '复核说明',
            notePlaceholder: '记录假设、证据解释和仍需验证的风险。',
            confirm: '确认记录复盘',
            saving: '正在记录…',
            recorded: '复盘已记录',
            noAuthority: '只追加审计证据；不会提交订单、改账本或扩大资本权限。',
            error: '复盘失败，请重新预览证据。',
          }
        : {
            open: 'Review decision outcome',
            close: 'Close review',
            loading: 'Reading persisted evidence…',
            retry: 'Preview evidence again',
            execution: 'Execution evidence',
            financial: 'Financial evidence',
            snapshot: 'Valuation snapshot',
            cutoff: 'Ledger cutoff',
            blocked: 'Current evidence cannot support a conclusive outcome',
            reviewer: 'Reviewer',
            decision: 'Human decision',
            outcome: 'Outcome conclusion',
            note: 'Review note',
            notePlaceholder:
              'Record assumptions, evidence interpretation, and remaining risk.',
            confirm: 'Record review',
            saving: 'Recording…',
            recorded: 'Review recorded',
            noAuthority:
              'Appends audit evidence only; it cannot submit orders, mutate the ledger, or expand capital authority.',
            error: 'Review failed; preview the evidence again.',
          },
    [locale],
  );

  if (!Number.isInteger(signalId)) {
    return null;
  }

  const refreshPreview = async () => {
    if (record.isError) {
      record.reset();
    }
    try {
      const target = await preview.mutateAsync(reviewSignalId);
      setDecision(defaultDecision(target));
      setOutcome(defaultOutcome(target));
    } catch {
      // The mutation state renders the fail-closed error and allows a retry.
    }
  };

  const openPreview = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (!preview.data || preview.isError || record.isError) {
      await refreshPreview();
    }
  };

  const submit = async () => {
    const target = preview.data;
    if (!target || !note.trim() || !reviewedBy.trim()) {
      return;
    }
    try {
      await record.mutateAsync({
        signalId: reviewSignalId,
        idempotency_key: requestKey,
        reviewed_by: reviewedBy.trim(),
        user_decision: decision,
        outcome,
        note: note.trim(),
        expected_target_fingerprint: target.target_fingerprint,
      });
    } catch {
      // A target drift or validation error is shown without retrying implicitly.
    }
  };

  const target = preview.data;
  const contribution = target?.strategy_contribution_report;

  return (
    <div className="mt-2 border-t border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] pt-2">
      <button
        type="button"
        className="app-button-secondary inline-flex min-h-8 items-center justify-center rounded-xl px-2.5 py-1.5 text-[11px] font-semibold"
        aria-expanded={expanded}
        onClick={() => void openPreview()}
      >
        {expanded ? labels.close : labels.open}
      </button>

      {expanded ? (
        <div
          data-testid={`decision-outcome-review-${signalId}`}
          className="mt-3 grid gap-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)] p-3"
        >
          {preview.isPending ? (
            <p className="app-muted text-xs">{labels.loading}</p>
          ) : preview.isError ? (
            <div className="grid justify-items-start gap-2">
              <p role="alert" className="app-error-text text-xs">
                {labels.error}
              </p>
              <button
                type="button"
                className="app-button-secondary min-h-8 rounded-xl px-2.5 py-1.5 text-[11px] font-semibold"
                onClick={() => void refreshPreview()}
              >
                {labels.retry}
              </button>
            </div>
          ) : target ? (
            <>
              <div className="flex justify-end">
                <EvidenceIdentityDisclosure
                  triggerLabel={appCopy.common.viewEvidenceIdentity}
                  title={appCopy.common.evidenceIdentityTitle}
                  description={appCopy.common.evidenceIdentityDescription}
                  closeLabel={appCopy.common.closeEvidenceIdentity}
                  fields={[
                    {
                      label: appCopy.common.valuationSnapshot,
                      value: target.valuation_snapshot_id ?? '--',
                      mono: true,
                    },
                    {
                      label: appCopy.common.ledgerCutoff,
                      value: target.ledger_cutoff_id,
                      mono: true,
                    },
                    {
                      label: appCopy.common.reviewFingerprint,
                      value: target.target_fingerprint,
                      mono: true,
                    },
                  ]}
                />
              </div>
              <dl className="grid gap-2 text-[11px] sm:grid-cols-2">
                <div>
                  <dt className="app-muted">{labels.execution}</dt>
                  <dd className="mt-0.5 font-semibold text-[var(--app-soft)]">
                    {reviewLabel(target.execution_evidence.status, locale)} ·{' '}
                    {target.execution_evidence.order_count}/
                    {target.execution_evidence.fill_count}
                  </dd>
                </div>
                <div>
                  <dt className="app-muted">{labels.financial}</dt>
                  <dd className="mt-0.5 font-semibold text-[var(--app-soft)]">
                    {reviewLabel(target.financial_evidence_status, locale)}
                    {contribution?.net_contribution != null
                      ? ` · ${formatCurrency(contribution.net_contribution)}`
                      : ''}
                  </dd>
                </div>
              </dl>
              {target.blockers.length > 0 ? (
                <p className="rounded-lg border border-[color-mix(in_srgb,var(--app-warning)_32%,transparent)] px-2.5 py-2 text-[11px] leading-5 text-[var(--app-warning)]">
                  {labels.blocked}:{' '}
                  {target.blockers
                    .map((item) => formatPublicCode(item, locale))
                    .join(' · ')}
                </p>
              ) : null}

              {record.data ? (
                <div
                  role="status"
                  className="text-xs text-[var(--app-success)]"
                >
                  {labels.recorded} · {record.data.review.review_id}
                </div>
              ) : (
                <div className="grid gap-2">
                  <label className="grid gap-1 text-[11px] text-[var(--app-muted)]">
                    {labels.reviewer}
                    <input
                      className="app-field rounded-xl px-2.5 py-2 text-xs text-[var(--app-text)]"
                      value={reviewedBy}
                      onChange={(event) => setReviewedBy(event.target.value)}
                    />
                  </label>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="grid gap-1 text-[11px] text-[var(--app-muted)]">
                      {labels.decision}
                      <select
                        className="app-field rounded-xl px-2.5 py-2 text-xs text-[var(--app-text)]"
                        value={decision}
                        onChange={(event) =>
                          setDecision(event.target.value as ReviewDecision)
                        }
                      >
                        <option value="acted">
                          {reviewLabel('acted', locale)}
                        </option>
                        <option value="ignored">
                          {reviewLabel('ignored', locale)}
                        </option>
                        <option value="deferred">
                          {reviewLabel('deferred', locale)}
                        </option>
                        <option value="blocked">
                          {reviewLabel('blocked', locale)}
                        </option>
                      </select>
                    </label>
                    <label className="grid gap-1 text-[11px] text-[var(--app-muted)]">
                      {labels.outcome}
                      <select
                        className="app-field rounded-xl px-2.5 py-2 text-xs text-[var(--app-text)]"
                        value={outcome}
                        onChange={(event) =>
                          setOutcome(event.target.value as ReviewOutcome)
                        }
                      >
                        {target.allowed_outcomes.map((item) => (
                          <option key={item} value={item}>
                            {reviewLabel(item, locale)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label className="grid gap-1 text-[11px] text-[var(--app-muted)]">
                    {labels.note}
                    <textarea
                      className="app-field min-h-20 rounded-xl px-2.5 py-2 text-xs leading-5 text-[var(--app-text)]"
                      placeholder={labels.notePlaceholder}
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                    />
                  </label>
                  <p className="app-muted text-[11px] leading-5">
                    {labels.noAuthority}
                  </p>
                  {record.isError ? (
                    <p role="alert" className="app-error-text text-[11px]">
                      {labels.error}
                    </p>
                  ) : null}
                  <button
                    type="button"
                    className="app-button-primary min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={
                      record.isPending || !note.trim() || !reviewedBy.trim()
                    }
                    onClick={() => void submit()}
                  >
                    {record.isPending ? labels.saving : labels.confirm}
                  </button>
                </div>
              )}
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
