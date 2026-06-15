import { useMemo } from 'react';

import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatTimestamp,
} from '../../../shared/format';
import {
  useIntradayDecisionQuery,
  useTodayDecisionQuery,
  type DecisionCandidate,
  type DecisionResponse,
} from '../api';

function normalizeStatus(value: string | null | undefined) {
  return (value ?? 'unknown').replace(/_/g, ' ');
}

function decisionTone(value: string) {
  if (value === 'passed' || value === 'attached' || value === 'live') {
    return 'success';
  }
  if (
    value === 'blocked' ||
    value === 'failed' ||
    value === 'missing' ||
    value === 'not_attached'
  ) {
    return 'danger';
  }
  return 'warning';
}

function evidenceStatus(candidate: DecisionCandidate) {
  return candidate.evidence.after_cost_oos_validation.status;
}

function manualStatus(candidate: DecisionCandidate) {
  if (
    candidate.manual_confirmation_status === 'ready_for_manual_confirmation'
  ) {
    return 'ready for confirmation';
  }
  return normalizeStatus(candidate.manual_confirmation_status);
}

export function DecisionCockpitPage() {
  const copy = useCopy();
  const labels = copy.decision;
  const today = useTodayDecisionQuery();
  const intraday = useIntradayDecisionQuery();
  const loading = today.isLoading || intraday.isLoading;
  const error = today.error ?? intraday.error;
  const lanes = useMemo(
    () =>
      [today.data, intraday.data].filter((item): item is DecisionResponse =>
        Boolean(item),
      ),
    [intraday.data, today.data],
  );
  const commandRegisterRows = useMemo(() => {
    const totals = lanes.reduce(
      (accumulator, lane) => ({
        candidates: accumulator.candidates + lane.summary.candidate_count,
        manualReady:
          accumulator.manualReady +
          lane.summary.ready_for_manual_confirmation_count,
        riskBlocked: accumulator.riskBlocked + lane.summary.risk_blocked_count,
        signals: accumulator.signals + (lane.summary.audit?.signal_count ?? 0),
        journalEntries:
          accumulator.journalEntries +
          (lane.summary.audit?.journal_entry_count ?? 0),
      }),
      {
        candidates: 0,
        manualReady: 0,
        riskBlocked: 0,
        signals: 0,
        journalEntries: 0,
      },
    );

    return [
      {
        label: labels.candidateActions,
        value: String(totals.candidates),
        tone: totals.candidates > 0 ? 'success' : 'neutral',
      },
      {
        label: labels.manualConfirmations,
        value: labels.readyCount(totals.manualReady),
        tone: totals.manualReady > 0 ? 'success' : 'neutral',
      },
      {
        label: labels.riskBlocks,
        value: labels.blockedCount(totals.riskBlocked),
        tone: totals.riskBlocked > 0 ? 'danger' : 'success',
      },
      {
        label: labels.auditCoverage,
        value: `${totals.journalEntries}/${totals.signals}`,
        tone:
          totals.signals > 0 && totals.journalEntries >= totals.signals
            ? 'success'
            : 'warning',
      },
      {
        label: labels.marketData,
        value: today.data?.summary.market_data?.source_health ?? '--',
        tone:
          today.data?.summary.market_data?.source_health === 'live'
            ? 'success'
            : 'warning',
      },
      {
        label: labels.executionDefault,
        value: labels.manualConfirmationRequired,
        tone: 'success',
      },
    ] satisfies Array<{
      label: string;
      value: string;
      tone: 'success' | 'warning' | 'danger' | 'neutral';
    }>;
  }, [lanes, labels, today.data]);

  if (loading) {
    return (
      <section className="space-y-5">
        <PageHeader title={labels.title} subtitle={labels.subtitle} />
        <StatePanel title={copy.states.loading} detail={labels.loading} />
      </section>
    );
  }

  if (error) {
    return (
      <section className="space-y-5">
        <PageHeader title={labels.title} subtitle={labels.subtitle} />
        <StatePanel
          title={copy.states.error}
          detail={error instanceof Error ? error.message : labels.error}
        />
      </section>
    );
  }

  return (
    <section className="min-w-0 space-y-5 sm:space-y-6">
      <PageHeader title={labels.title} subtitle={labels.subtitle} />

      <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
        <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="app-product-mark">{labels.commandRegister}</div>
              <h2 className="app-card-title mt-1.5">
                {labels.commandRegisterTitle}
              </h2>
            </div>
            <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
              {labels.commandRegisterDetail}
            </p>
          </div>
          <div className="mt-4 grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-3">
            {commandRegisterRows.map((row) => (
              <DecisionRegisterRow
                key={row.label}
                label={row.label}
                value={row.value}
                tone={row.tone}
              />
            ))}
          </div>
        </div>
      </section>

      <div
        data-testid="decision-summary-grid"
        className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-4"
      >
        {lanes.map((lane) => (
          <LaneStatusTile key={lane.lane} lane={lane} />
        ))}
        <SummaryTile
          label={labels.marketHealth}
          value={`Market health: ${
            today.data?.summary.market_data?.source_health ?? '--'
          }`}
          detail={labels.quotesDetail(
            today.data?.summary.market_data?.live_quote_count ?? 0,
            today.data?.summary.market_data?.stale_quote_count ?? 0,
          )}
        />
        <SummaryTile
          label={labels.portfolio}
          value={`${labels.portfolioEquity}: ${formatCurrency(
            today.data?.summary.portfolio?.total_equity,
          )}`}
          detail={labels.positionCount(
            today.data?.summary.portfolio?.position_count ?? 0,
          )}
        />
      </div>

      <div
        data-testid="decision-lane-grid"
        className="grid min-w-0 gap-5 xl:grid-cols-2"
      >
        {lanes.map((lane) => (
          <DecisionLanePanel key={lane.lane} lane={lane} />
        ))}
      </div>
    </section>
  );
}

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  const labels = useCopy().decision;
  return (
    <header className="app-page-header min-w-0 pb-1">
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">{labels.kicker}</div>
          <h1 className="app-page-title mt-2">{title}</h1>
        </div>
        <p className="app-page-subtitle min-w-0 break-words sm:max-w-xl sm:text-right">
          {subtitle}
        </p>
      </div>
    </header>
  );
}

function StatePanel({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="app-terminal-panel rounded-[28px] p-[1px]">
      <div className="app-terminal-inner rounded-[27px] p-5">
        <h2 className="app-card-title">{title}</h2>
        <p className="app-muted mt-2 text-sm">{detail}</p>
      </div>
    </section>
  );
}

function SummaryTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="app-card min-w-0 rounded-[22px] p-4">
      <div className="app-product-mark">{label}</div>
      <div className="mt-2 break-words text-base font-semibold text-[var(--app-text)]">
        {value}
      </div>
      <div className="app-muted mt-1 break-words text-xs">{detail}</div>
    </div>
  );
}

function DecisionRegisterRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'success' | 'warning' | 'danger' | 'neutral';
}) {
  const toneClass =
    tone === 'success'
      ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success)]'
      : tone === 'danger'
        ? 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger)]'
        : tone === 'warning'
          ? 'border-[color-mix(in_srgb,var(--app-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] text-[var(--app-warning)]'
          : 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] text-[var(--app-soft)]';
  return (
    <div
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
      aria-label={`Decision register item: ${label} ${value}`}
    >
      <div className="min-w-0 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--app-muted)]">
        {label}
      </div>
      <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 justify-self-end">
        <span
          className={`h-2 w-2 rounded-full border ${toneClass}`}
          aria-hidden="true"
        />
        <span className="min-w-0 text-right font-mono text-sm font-semibold tabular-nums text-[var(--app-text)]">
          {value}
        </span>
      </div>
    </div>
  );
}

function LaneStatusTile({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  return (
    <SummaryTile
      label={lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane}
      value={`${labels.decision}: ${lane.decision}`}
      detail={labels.candidateCount(lane.summary.candidate_count)}
    />
  );
}

function DecisionLanePanel({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  const laneLabel =
    lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane;
  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{laneLabel}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.decision}: {lane.decision}
            </h2>
            <p className="app-muted mt-2 break-words text-sm">
              {labels.generatedAt}: {formatTimestamp(lane.generated_at)}
            </p>
          </div>
          <div className="grid min-w-0 gap-1 text-left text-xs sm:text-right">
            <span>
              {labels.riskBlocked}: {lane.summary.risk_blocked_count}
            </span>
            <span>
              {labels.manualReady}:{' '}
              {lane.summary.ready_for_manual_confirmation_count}
            </span>
            {lane.summary.excluded_daily_count !== undefined ? (
              <span>
                {labels.excludedDaily}: {lane.summary.excluded_daily_count}
              </span>
            ) : null}
          </div>
        </div>

        {lane.candidates.length > 0 ? (
          <div className="mt-5 grid min-w-0 gap-3">
            {lane.candidates.map((candidate) => (
              <DecisionCandidateCard
                key={`${lane.lane}-${candidate.action_id ?? candidate.symbol}`}
                candidate={candidate}
              />
            ))}
          </div>
        ) : (
          <NoActionReasons reasons={lane.no_action_reasons} />
        )}
      </div>
    </section>
  );
}

function NoActionReasons({ reasons }: { reasons: string[] }) {
  const labels = useCopy().decision;
  return (
    <div className="mt-5 min-w-0 rounded-[20px] border border-[color-mix(in_srgb,var(--app-border)_50%,transparent)] p-4">
      <div className="text-sm font-semibold">{labels.noActionReasons}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {(reasons.length ? reasons : [labels.noActionUnavailable]).map(
          (reason) => (
            <span
              key={reason}
              className="min-w-0 rounded-full border border-[var(--app-accent-border)] px-3 py-1 text-xs text-[var(--app-muted)]"
            >
              {reason}
            </span>
          ),
        )}
      </div>
    </div>
  );
}

function DecisionCandidateCard({
  candidate,
}: {
  candidate: DecisionCandidate;
}) {
  const labels = useCopy().decision;
  const readyForManual =
    candidate.manual_confirmation_status === 'ready_for_manual_confirmation';
  return (
    <article
      data-testid={`decision-candidate-card-${candidate.symbol}`}
      className="min-w-0 break-words rounded-[22px] border border-[color-mix(in_srgb,var(--app-border)_55%,transparent)] bg-[color-mix(in_srgb,var(--app-panel)_58%,transparent)] p-4"
    >
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="break-all font-semibold text-[var(--app-text)]">
              {candidate.symbol}
            </span>
            <StatusPill value={candidate.action} />
            <StatusPill
              value={candidate.risk_gate_status}
              prefix={labels.riskGate}
            />
          </div>
          <p className="app-muted mt-2 break-words text-sm">
            {candidate.detail || candidate.title || labels.noDetail}
          </p>
        </div>
        {readyForManual ? (
          <a
            className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-2xl px-4 text-center text-sm font-semibold whitespace-normal"
            href="/trading"
            aria-label={`${labels.openTradingApprovals}: ${candidate.symbol}`}
          >
            {labels.openTradingApprovals}
          </a>
        ) : null}
      </div>

      <div className="mt-4 grid min-w-0 gap-2 text-sm sm:grid-cols-2">
        <EvidenceLine
          label={labels.manual}
          value={manualStatus(candidate)}
          tone={readyForManual ? 'success' : 'warning'}
        />
        <EvidenceLine
          label={labels.afterCostOos}
          value={evidenceStatus(candidate)}
          tone={decisionTone(evidenceStatus(candidate))}
        />
        <EvidenceLine
          label={labels.dataFreshness}
          value={candidate.evidence.data_freshness.status}
          tone={decisionTone(candidate.evidence.data_freshness.status)}
        />
        <EvidenceLine
          label={labels.journal}
          value={candidate.evidence.journal.latest_event_type ?? '--'}
          tone={
            candidate.evidence.journal.has_journal_entry ? 'success' : 'warning'
          }
        />
        <EvidenceLine
          label={labels.strategy}
          value={candidate.evidence.strategy.strategy_id ?? '--'}
        />
        <EvidenceLine
          label={labels.targetWeight}
          value={formatPercent(candidate.target_weight)}
        />
        <EvidenceLine
          label={labels.price}
          value={formatPrice(candidate.price)}
        />
        <EvidenceLine
          label={labels.riskDecision}
          value={String(candidate.evidence.risk_gate.decision_id ?? '--')}
        />
      </div>
    </article>
  );
}

function StatusPill({ value, prefix }: { value: string; prefix?: string }) {
  const tone = decisionTone(value);
  return (
    <span
      className={`min-w-0 rounded-full border px-2.5 py-1 text-xs font-semibold break-words ${
        tone === 'success'
          ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success)]'
          : tone === 'danger'
            ? 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger)]'
            : 'border-[color-mix(in_srgb,var(--app-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] text-[var(--app-warning)]'
      }`}
    >
      {prefix ? `${prefix}: ${normalizeStatus(value)}` : normalizeStatus(value)}
    </span>
  );
}

function EvidenceLine({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'success' | 'warning' | 'danger';
}) {
  const textColor =
    tone === 'success'
      ? 'text-[var(--app-success)]'
      : tone === 'danger'
        ? 'text-[var(--app-danger)]'
        : tone === 'warning'
          ? 'text-[var(--app-warning)]'
          : 'text-[var(--app-text)]';
  return (
    <div
      data-testid="decision-evidence-line"
      className="min-w-0 rounded-2xl bg-[color-mix(in_srgb,var(--app-mantle)_42%,transparent)] px-3 py-2"
    >
      <div className="app-muted break-words text-[11px] uppercase">{label}</div>
      <div className={`mt-1 break-words text-sm font-semibold ${textColor}`}>
        {label}: {value}
      </div>
    </div>
  );
}
