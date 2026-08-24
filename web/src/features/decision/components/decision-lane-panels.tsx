import { useState } from 'react';
import { EvidenceState, StatusBadge } from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatPercent,
  formatPrice,
  formatTimestamp,
} from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import { type DecisionCandidate, type DecisionResponse } from '../api';
import type { CandidateEvidenceChainItem } from './decision-status-model';
import {
  accountTruthScore,
  accountTruthTone,
  accountTruthValue,
  decisionTone,
  evidenceStatus,
  manualStatus,
  normalizeStatus,
  strategyAttributionAuditId,
  strategyAttributionTone,
  strategyAttributionValue,
  strategyAuditIdFromDisplay,
  strategyDisplayNameFromId,
} from './decision-status-model';
import {
  candidateEvidenceChainItems,
  strategyContributionDetailItems,
} from './decision-candidate-evidence-model';
import {
  decisionCandidateBacktestHref,
  decisionCandidateHoldingAttributionHref,
  decisionGateDetailLabels,
} from './decision-workflow-model';

export function SummaryTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="min-w-0 border-l-2 border-[var(--app-divider)] px-3 py-2.5">
      <div className="app-product-mark">{label}</div>
      <div className="mt-1 break-words text-base font-semibold text-[var(--app-text)]">
        {value}
      </div>
      <div className="app-muted mt-1 break-words text-xs">{detail}</div>
    </div>
  );
}

export function LaneStatusTile({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  return (
    <SummaryTile
      label={lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane}
      value={`${labels.decision}: ${formatPublicStatus(lane.decision, locale)}`}
      detail={labels.candidateCount(lane.summary.candidate_count)}
    />
  );
}

export function AccountTruthGateTile({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const accountTruth = lane.summary.account_truth;
  const requiredActions = accountTruth?.required_actions ?? [];
  const blockingReasons = accountTruth?.blocking_reasons ?? [];
  const unresolvedDetail = labels.accountTruthUnresolved(
    accountTruth?.unresolved_mismatch_count ?? 0,
  );
  const actionDetail = decisionGateDetailLabels({
    requiredActions,
    blockingReasons,
    labels,
    locale,
  }).join(' · ');
  const detail =
    actionDetail.length > 0
      ? `${unresolvedDetail} · ${actionDetail}`
      : unresolvedDetail;

  return (
    <SummaryTile
      label={labels.accountTruthGate}
      value={accountTruthValue(accountTruth, locale)}
      detail={detail}
    />
  );
}

export function StrategyAttributionGateTile({
  lane,
}: {
  lane: DecisionResponse;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const strategyAttribution = lane.summary.strategy_attribution;
  const requiredActions = strategyAttribution?.required_actions ?? [];
  const blockingReasons = strategyAttribution?.blocking_reasons ?? [];
  const auditId = strategyAttributionAuditId(
    strategyAttribution,
    copy.backtest.page.strategyNames,
  );
  const detailItems = [
    auditId ? `${labels.strategyAuditId}: ${auditId}` : '',
    strategyAttribution?.attribution_status
      ? `${labels.strategyAttributionStatus}: ${formatPublicCode(
          strategyAttribution.attribution_status,
          locale,
        )}`
      : '',
    strategyAttribution?.contribution_status
      ? `${labels.strategyContributionStatus}: ${formatPublicCode(
          strategyAttribution.contribution_status,
          locale,
        )}`
      : '',
    ...strategyContributionDetailItems(strategyAttribution, copy.backtest.page),
    decisionGateDetailLabels({
      requiredActions,
      blockingReasons,
      labels,
      locale,
    }).join(' · '),
  ].filter(Boolean);

  return (
    <SummaryTile
      label={labels.strategyAttributionGate}
      value={strategyAttributionValue(
        strategyAttribution,
        locale,
        copy.backtest.page.strategyNames,
      )}
      detail={detailItems.length > 0 ? detailItems.join(' · ') : labels.none}
    />
  );
}

export function DecisionLanePanel({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const defaultExpanded = lane.summary.candidate_count === 0;
  const [expanded, setExpanded] = useState(defaultExpanded);
  const laneLabel =
    lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane;
  const hasCandidates = lane.candidates.length > 0;
  return (
    <section className="app-workbench-section min-w-0 py-4">
      <div className="min-w-0 px-1 sm:px-3">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{laneLabel}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.decision}: {formatPublicStatus(lane.decision, locale)}
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

        {hasCandidates ? (
          <div className="mt-5 grid min-w-0 gap-3">
            <div className="flex min-w-0 flex-col gap-3 border-y border-[var(--app-divider)] px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-[var(--app-text)]">
                  {labels.candidateEvidenceCollapsedTitle(
                    lane.summary.candidate_count,
                  )}
                </div>
                <p className="app-muted mt-1 break-words text-xs leading-5">
                  {labels.candidateEvidenceCollapsedDetail}
                </p>
              </div>
              <button
                className="app-button-secondary inline-flex min-h-9 max-w-full items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                type="button"
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded
                  ? labels.collapseCandidateEvidence
                  : labels.expandCandidateEvidence}
              </button>
            </div>

            {expanded ? (
              <div className="grid min-w-0 gap-3">
                {lane.candidates.map((candidate) => (
                  <DecisionCandidateCard
                    key={`${lane.lane}-${candidate.action_id ?? candidate.symbol}`}
                    candidate={candidate}
                  />
                ))}
              </div>
            ) : null}
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
  const items = reasons.length ? reasons : [labels.noActionUnavailable];
  return (
    <EvidenceState
      className="mt-5"
      kind="empty"
      statusLabel={labels.noActionReasons}
      title={labels.noActionReasons}
      description={
        <ul className="grid gap-1">
          {items.map((reason) => (
            <li
              key={reason}
              className="border-l border-[var(--app-divider)] pl-2"
            >
              {labels.gateRequirementLabel(reason)}
            </li>
          ))}
        </ul>
      }
    />
  );
}

function DecisionCandidateCard({
  candidate,
}: {
  candidate: DecisionCandidate;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const strategyNames = copy.backtest.page.strategyNames;
  const { locale } = usePreferences();
  const readyForManual =
    candidate.manual_confirmation_status === 'ready_for_manual_confirmation';
  const instrumentLabel = formatInstrumentDisplayLabel(candidate);
  const publicDetail = formatPublicNote(
    candidate.detail || candidate.title || labels.noDetail,
    locale,
  );
  const strategyId = candidate.evidence.strategy.strategy_id;
  const strategyAuditId = strategyAuditIdFromDisplay(strategyId, strategyNames);
  const backtestHref = decisionCandidateBacktestHref(candidate);
  const holdingDetailHref = `/portfolio/${encodeURIComponent(candidate.symbol)}`;
  const holdingAttributionHref =
    decisionCandidateHoldingAttributionHref(candidate);
  const riskGateReasons = candidate.evidence.risk_gate.reasons.map((reason) =>
    formatPublicNote(reason, locale),
  );
  return (
    <article
      data-testid={`decision-candidate-card-${candidate.symbol}`}
      className="min-w-0 break-words border-l-2 border-[var(--app-divider)] px-3 py-3"
    >
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="break-all font-semibold text-[var(--app-text)]">
              {instrumentLabel}
            </span>
            <StatusPill value={candidate.action} />
            <StatusPill
              value={candidate.risk_gate_status}
              prefix={labels.riskGate}
            />
          </div>
          <p className="app-muted mt-2 break-words text-sm">{publicDetail}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2 lg:justify-end">
          <a
            className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] px-4 text-center text-sm font-semibold whitespace-normal"
            href={backtestHref}
            aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
          >
            {labels.openBacktestEvidence}
          </a>
          <a
            className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] px-4 text-center text-sm font-semibold whitespace-normal"
            href={holdingDetailHref}
            aria-label={`${labels.openHoldingDetail}: ${instrumentLabel}`}
          >
            {labels.openHoldingDetail}
          </a>
          <a
            className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] px-4 text-center text-sm font-semibold whitespace-normal"
            href={holdingAttributionHref}
            aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
          >
            {labels.openAttributionReview}
          </a>
          {readyForManual ? (
            <a
              className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] px-4 text-center text-sm font-semibold whitespace-normal"
              href="/trading"
              aria-label={`${labels.openTradingApprovals}: ${instrumentLabel}`}
            >
              {labels.openTradingApprovals}
            </a>
          ) : null}
        </div>
      </div>

      <dl className="mt-4 grid min-w-0 text-sm sm:grid-cols-2 sm:gap-x-4">
        <EvidenceLine
          label={labels.manual}
          value={manualStatus(candidate, locale)}
          tone={readyForManual ? 'success' : 'warning'}
        />
        <EvidenceLine
          label={labels.afterCostOos}
          value={formatPublicStatus(evidenceStatus(candidate), locale)}
          tone={decisionTone(evidenceStatus(candidate))}
        />
        <EvidenceLine
          label={labels.dataFreshness}
          value={formatPublicStatus(
            candidate.evidence.data_freshness.status,
            locale,
          )}
          tone={decisionTone(candidate.evidence.data_freshness.status)}
        />
        <EvidenceLine
          label={labels.accountTruth}
          value={formatPublicStatus(
            candidate.evidence.account_truth?.gate_status ?? 'not_evaluated',
            locale,
          )}
          tone={accountTruthTone(candidate.evidence.account_truth)}
        />
        <EvidenceLine
          label={labels.accountTruthScore}
          value={accountTruthScore(candidate.evidence.account_truth)}
          tone={accountTruthTone(candidate.evidence.account_truth)}
        />
        <EvidenceLine
          label={labels.strategyAttribution}
          value={formatPublicStatus(
            candidate.evidence.strategy_attribution?.gate_status ??
              'not_configured',
            locale,
          )}
          tone={strategyAttributionTone(
            candidate.evidence.strategy_attribution,
          )}
        />
        <EvidenceLine
          label={labels.journal}
          value={formatPublicCode(
            candidate.evidence.journal.latest_event_type ?? '--',
            locale,
          )}
          tone={
            candidate.evidence.journal.has_journal_entry ? 'success' : 'warning'
          }
        />
        <EvidenceLine
          label={labels.strategy}
          value={strategyDisplayNameFromId(strategyId, strategyNames)}
        />
        {strategyAuditId ? (
          <EvidenceLine
            label={labels.strategyAuditId}
            value={strategyAuditId}
          />
        ) : null}
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
        {riskGateReasons.length > 0 ? (
          <EvidenceLine
            label={formatPublicCode('risk_block_evidence', locale)}
            value={riskGateReasons.join('；')}
            tone={decisionTone(candidate.evidence.risk_gate.status)}
          />
        ) : null}
      </dl>

      <CandidateEvidenceChain candidate={candidate} />
    </article>
  );
}

function CandidateEvidenceChain({
  candidate,
}: {
  candidate: DecisionCandidate;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const strategyNames = copy.backtest.page.strategyNames;
  const { locale } = usePreferences();
  const items = candidateEvidenceChainItems(
    candidate,
    locale,
    labels,
    strategyNames,
  );
  return (
    <section className="mt-4 min-w-0 border-t border-[var(--app-divider)] pt-3">
      <div className="app-type-overline text-[var(--app-muted)]">
        {labels.candidateEvidenceChain}
      </div>
      <dl className="mt-2 grid min-w-0 md:grid-cols-3 md:gap-x-4">
        {items.map((item) => (
          <EvidenceChainCell key={item.label} item={item} />
        ))}
      </dl>
    </section>
  );
}

function EvidenceChainCell({ item }: { item: CandidateEvidenceChainItem }) {
  const textColor =
    item.tone === 'success'
      ? 'text-[var(--app-success-text)]'
      : item.tone === 'danger'
        ? 'text-[var(--app-danger-text)]'
        : item.tone === 'warning'
          ? 'text-[var(--app-warning-text)]'
          : 'text-[var(--app-text)]';
  return (
    <div className="min-w-0 border-b border-[var(--app-divider)] py-2">
      <dt className="app-muted app-type-micro">{item.label}</dt>
      <dd className={`mt-1 break-words text-sm font-semibold ${textColor}`}>
        {item.value}
      </dd>
    </div>
  );
}

export function StatusPill({
  value,
  prefix,
}: {
  value: string;
  prefix?: string;
}) {
  const { locale } = usePreferences();
  const tone = decisionTone(value);
  const label = normalizeStatus(value, locale);
  return (
    <StatusBadge tone={tone} className="min-w-0 break-words">
      {prefix ? `${prefix}: ${label}` : label}
    </StatusBadge>
  );
}

function EvidenceLine({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'success' | 'warning' | 'danger' | 'neutral';
}) {
  const textColor =
    tone === 'success'
      ? 'text-[var(--app-success-text)]'
      : tone === 'danger'
        ? 'text-[var(--app-danger-text)]'
        : tone === 'warning'
          ? 'text-[var(--app-warning-text)]'
          : 'text-[var(--app-text)]';
  return (
    <div
      data-testid="decision-evidence-line"
      className="min-w-0 border-b border-[var(--app-divider)] py-2"
    >
      <dt className="app-muted app-type-overline break-words">{label}</dt>
      <dd className={`mt-1 break-words text-sm font-semibold ${textColor}`}>
        {label}: {value}
      </dd>
    </div>
  );
}
