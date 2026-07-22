import { useMemo } from 'react';

import { usePreferences, type Locale } from '../../../app/preferences';
import {
  useStrategyLearningReviewQuery,
  type StrategyLearningReviewItem,
} from '../api';

const COPY = {
  en: {
    kicker: 'Reviewed learning evidence',
    title: 'Strategy learning review queue',
    detail:
      'Translate the latest persisted human outcome review for each signal into a safe next step. Historical labels are revalidated against current canonical evidence before they can enter this queue.',
    reviewed: 'Reviewed signals',
    actions: 'Action items',
    critical: 'Integrity blocks',
    loading: 'Loading persisted outcome-review evidence…',
    loadError:
      'The learning queue could not be read. No learning action is authoritative while this evidence is unavailable.',
    empty:
      'No reviewed learning evidence yet. Record a human signal-outcome review in Decision before using this queue.',
    clear:
      'The latest reviewed signals do not require a learning action. This is not a profitability claim.',
    exactEvidence: 'Exact persisted evidence',
    blocker: 'Blocker',
    outcome: 'Reviewed outcome',
    decision: 'Human decision',
    reviewedAt: 'Reviewed at',
    binding: 'Current evidence binding',
    bindingValid: 'Exact and replay-valid',
    bindingInvalid: 'Blocked by drift or audit integrity',
    nextAction: 'Safe human next action',
    researchHandoff: 'Copy-only research handoff',
    researchBoundary:
      'Copy this question into a separately human-started evidence capture and research task. Nothing starts here.',
    persistedOnly: 'Persisted facts only',
    aiIdle: 'AI not invoked',
    noMutation: 'No strategy mutation',
    noAuthority: 'No execution or capital authority',
    queueFingerprint: 'Queue fingerprint',
    signal: 'Signal',
    status: {
      blocked: 'Integrity blocked',
      review_required: 'Human review required',
      clear: 'No learning action',
      not_configured: 'No reviewed evidence',
    },
    priority: {
      critical: 'Critical',
      high: 'High',
      medium: 'Medium',
      low: 'Low',
      none: 'None',
    },
    outcomeLabels: {
      evidence_supported: 'Supported by bound evidence',
      evidence_not_supported: 'Not supported by bound evidence',
      risk_gate_validated: 'Risk block validated',
      not_executed: 'Not executed',
      inconclusive: 'Inconclusive',
    },
    decisionLabels: {
      acted: 'Acted',
      ignored: 'Ignored',
      deferred: 'Deferred',
      blocked: 'Blocked',
    },
    actionLabels: {
      repair_post_decision_review_integrity_before_learning:
        'Repair and replay the post-decision review before learning from it',
      re_preview_post_decision_review_against_current_evidence:
        'Re-preview the outcome review against current canonical evidence',
      open_human_strategy_research_task:
        'Open a separate human-started strategy research task',
      resolve_or_wait_for_canonical_outcome_evidence:
        'Resolve or wait for canonical outcome evidence',
      review_why_the_signal_was_not_executed:
        'Review why the signal was not executed',
      none: 'No action',
    },
  },
  zh: {
    kicker: '已复盘学习证据',
    title: '策略学习复核队列',
    detail:
      '把每个信号最新的持久化人工结果复盘转换为安全下一步；历史标签必须先用当前 canonical 证据重新校验，才能进入队列。',
    reviewed: '已复盘信号',
    actions: '待办项',
    critical: '完整性阻断',
    loading: '正在读取持久化结果复盘证据…',
    loadError: '无法读取学习队列；证据恢复前，任何学习动作都不具权威性。',
    empty: '尚无已复盘学习证据。请先在 Decision 中记录人工信号结果复盘。',
    clear: '最新已复盘信号无需学习动作；这不代表策略具备盈利能力。',
    exactEvidence: '精确持久化证据',
    blocker: '阻断原因',
    outcome: '复盘结果',
    decision: '人工决定',
    reviewedAt: '复盘时间',
    binding: '当前证据绑定',
    bindingValid: '精确且审计回放有效',
    bindingInvalid: '因证据漂移或审计完整性而阻断',
    nextAction: '安全人工下一步',
    researchHandoff: '仅复制的研究交接',
    researchBoundary:
      '请把问题复制到另行人工启动的证据捕获与研究任务中；本面板不会启动任何流程。',
    persistedOnly: '仅持久化事实',
    aiIdle: '未调用 AI',
    noMutation: '不修改策略',
    noAuthority: '无执行或资本权限',
    queueFingerprint: '队列指纹',
    signal: '信号',
    status: {
      blocked: '完整性阻断',
      review_required: '需要人工处理',
      clear: '无需学习动作',
      not_configured: '尚无复盘证据',
    },
    priority: {
      critical: '严重',
      high: '高',
      medium: '中',
      low: '低',
      none: '无',
    },
    outcomeLabels: {
      evidence_supported: '证据支持',
      evidence_not_supported: '证据不支持',
      risk_gate_validated: '风控阻断得到验证',
      not_executed: '未执行',
      inconclusive: '证据不足，暂不下结论',
    },
    decisionLabels: {
      acted: '已执行',
      ignored: '已忽略',
      deferred: '已延后',
      blocked: '已阻断',
    },
    actionLabels: {
      repair_post_decision_review_integrity_before_learning:
        '先修复并回放决策后复盘，再从中学习',
      re_preview_post_decision_review_against_current_evidence:
        '用当前 canonical 证据重新预览结果复盘',
      open_human_strategy_research_task: '另行打开人工启动的策略研究任务',
      resolve_or_wait_for_canonical_outcome_evidence:
        '补齐或等待 canonical 结果证据',
      review_why_the_signal_was_not_executed: '复核该信号为何未执行',
      none: '无需动作',
    },
  },
} as const;

type PanelCopy = (typeof COPY)[Locale];

function knownLabel(
  labels: Record<string, string>,
  value: string,
  locale: Locale,
) {
  if (labels[value]) {
    return labels[value];
  }
  return locale === 'zh'
    ? '待人工复核项'
    : value
        .split('_')
        .filter(Boolean)
        .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
        .join(' ');
}

function priorityClass(priority: StrategyLearningReviewItem['priority']) {
  if (priority === 'critical') {
    return 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger-text)]';
  }
  if (priority === 'high' || priority === 'medium') {
    return 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]';
  }
  return 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]';
}

export function StrategyLearningReviewPanel() {
  const { locale } = usePreferences();
  const copy = COPY[locale];
  const queue = useStrategyLearningReviewQuery();
  const actionItems = useMemo(
    () =>
      (queue.data?.items ?? []).filter(
        (item) => item.safe_next_action !== 'none',
      ),
    [queue.data?.items],
  );

  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{copy.kicker}</div>
            <h2 className="app-card-title mt-1.5">{copy.title}</h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {copy.detail}
            </p>
          </div>
          <div className="grid shrink-0 grid-cols-3 gap-2 text-right text-xs tabular-nums">
            <Count
              label={copy.reviewed}
              value={queue.data?.reviewed_signal_count}
            />
            <Count label={copy.actions} value={queue.data?.action_item_count} />
            <Count
              label={copy.critical}
              value={queue.data?.critical_item_count}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2 text-xs font-semibold">
          <BoundaryChip>{copy.persistedOnly}</BoundaryChip>
          <BoundaryChip>{copy.aiIdle}</BoundaryChip>
          <BoundaryChip>{copy.noMutation}</BoundaryChip>
          <BoundaryChip>{copy.noAuthority}</BoundaryChip>
        </div>

        {queue.isLoading ? (
          <p className="app-muted mt-5 text-sm">{copy.loading}</p>
        ) : queue.isError || !queue.data ? (
          <p className="mt-5 rounded-2xl border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-4 py-3 text-sm text-[var(--app-danger-text)]">
            {copy.loadError}
          </p>
        ) : queue.data.status === 'not_configured' ? (
          <p className="app-muted mt-5 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_40%,transparent)] px-4 py-5 text-sm leading-6">
            {copy.empty}
          </p>
        ) : actionItems.length === 0 ? (
          <p className="mt-5 rounded-2xl border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-4 py-3 text-sm leading-6 text-[var(--app-success-text)]">
            {copy.clear}
          </p>
        ) : (
          <div className="mt-5 space-y-3">
            {actionItems.map((item) => (
              <LearningItemCard
                key={item.item_fingerprint}
                copy={copy}
                item={item}
                locale={locale}
              />
            ))}
          </div>
        )}

        {queue.data ? (
          <div className="app-muted mt-4 break-all font-mono text-[10px] leading-4">
            {copy.status[queue.data.status]} · {copy.queueFingerprint}:{' '}
            {queue.data.queue_fingerprint}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function LearningItemCard({
  copy,
  item,
  locale,
}: {
  copy: PanelCopy;
  item: StrategyLearningReviewItem;
  locale: Locale;
}) {
  const validBinding = item.audit_integrity_valid && item.target_binding_valid;
  return (
    <article className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="font-semibold text-[var(--app-text)]">
            {item.strategy_id}
            {item.symbol ? ` · ${item.symbol}` : ''}
          </div>
          <div className="app-muted mt-1 text-xs tabular-nums">
            {copy.signal} #{item.signal_id} · {copy.reviewedAt}{' '}
            {item.reviewed_at}
          </div>
        </div>
        <span
          className={`w-fit rounded-full border px-3 py-1 text-xs font-semibold ${priorityClass(item.priority)}`}
        >
          {copy.priority[item.priority]}
        </span>
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Fact
          label={copy.outcome}
          value={knownLabel(copy.outcomeLabels, item.outcome, locale)}
        />
        <Fact
          label={copy.decision}
          value={knownLabel(copy.decisionLabels, item.user_decision, locale)}
        />
        <Fact
          label={copy.binding}
          value={validBinding ? copy.bindingValid : copy.bindingInvalid}
          danger={!validBinding}
        />
        <Fact
          label={copy.nextAction}
          value={knownLabel(copy.actionLabels, item.safe_next_action, locale)}
        />
      </dl>

      {item.blockers.length > 0 ? (
        <div className="mt-4 rounded-2xl border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-4 py-3 text-sm text-[var(--app-danger-text)]">
          <div className="text-xs font-semibold uppercase tracking-[0.12em]">
            {copy.blocker}
          </div>
          <ul className="mt-2 space-y-1">
            {item.blockers.map((blocker) => (
              <li key={blocker} className="break-all font-mono text-xs">
                {blocker}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-4">
        <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
          {copy.exactEvidence}
        </div>
        <ul className="mt-2 grid gap-1.5 text-xs sm:grid-cols-2">
          {item.evidence_refs.map((reference) => (
            <li
              key={reference}
              className="app-muted min-w-0 break-all rounded-xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-2 font-mono"
            >
              {reference}
            </li>
          ))}
        </ul>
      </div>

      {item.research_handoff ? (
        <div className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-4">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--app-warning-text)]">
            {copy.researchHandoff}
          </div>
          <p className="mt-2 select-text text-sm leading-6 text-[var(--app-text)]">
            {item.research_handoff.research_question}
          </p>
          <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
            {copy.researchBoundary}
          </p>
        </div>
      ) : null}
    </article>
  );
}

function Count({ label, value }: { label: string; value?: number }) {
  return (
    <div className="min-w-24 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-2">
      <div className="app-muted text-[10px]">{label}</div>
      <div className="mt-1 text-lg font-semibold text-[var(--app-text)]">
        {value ?? '--'}
      </div>
    </div>
  );
}

function BoundaryChip({ children }: { children: string }) {
  return (
    <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-1.5 text-[var(--app-muted)]">
      {children}
    </span>
  );
}

function Fact({
  danger = false,
  label,
  value,
}: {
  danger?: boolean;
  label: string;
  value: string;
}) {
  return (
    <div>
      <dt className="app-muted text-[10px] uppercase tracking-[0.12em]">
        {label}
      </dt>
      <dd
        className={`mt-1 break-words font-semibold ${
          danger ? 'text-[var(--app-danger-text)]' : 'text-[var(--app-text)]'
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
