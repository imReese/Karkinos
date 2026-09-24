import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../../shared/api/client';
import { formatPublicCode } from '../../../shared/public-labels';
import { StatusBadge } from '../../../shared/ui/workbench';

const PAGE_SIZE = 20;
const OUTCOME_HORIZONS = ['T+1', 'T+5', 'T+20'] as const;

type CandidateHorizon = {
  status: 'observed' | 'pending' | 'unavailable';
  reason_code?: string;
  price_move_pct?: number;
  entry_open?: string;
  horizon_close?: string;
  horizon_receipt_fingerprint?: string;
};

type CandidateOutcome = {
  source_ref: string | null;
  anchor_status: 'verified' | 'unavailable';
  reason_code?: string;
  anchor: { receipt_fingerprint: string } | null;
  horizons: Record<(typeof OUTCOME_HORIZONS)[number], CandidateHorizon>;
};

export type DailyReportCandidate = {
  kind: 'formal_signal';
  decision_date: string;
  frozen_market_date: string | null;
  symbol: string;
  direction: string;
  scan_run_id: string;
  signal_id: number;
  action_id: number;
  source_ref: string;
  frozen_price: number | null;
  report_authoritative: boolean;
};

export type DailyReportBlockedSignal = {
  kind: 'account_blocked_signal';
  decision_date: string;
  symbol: string;
  strategy_id: string;
  board: string;
  reason: string;
  scan_run_id: string;
  source_ref: string | null;
  frozen_price: number | null;
  frozen_market_date: string | null;
  source_bound: boolean;
  report_authoritative: false;
};

export type DailyReportResearchOperation = {
  kind: 'research_preview';
  market_date: string;
  target_market_date: string | null;
  signal_date: string | null;
  symbol: string;
  operation: string;
  source_ref: string;
  dataset_snapshot_id: string | null;
  formula_fingerprint: string | null;
  frozen_price: number | null;
  research_only: true;
  report_authoritative: false;
};

export type DailyDecisionReport = {
  schema_version: 'karkinos.decision.daily_report.v1';
  report_date: string;
  status:
    | 'missing_run'
    | 'failed'
    | 'blocked'
    | 'completed_no_signal'
    | 'formal_candidate';
  calendar_evidence_ref: string;
  preparations: Array<{
    run_id: string;
    status: string;
    reason_codes: string[];
  }>;
  attempts: Array<{
    run_id: string;
    status: string;
    failure_stage: string | null;
    failure_code: string | null;
    error_type: string | null;
    evidence_refs: string[];
  }>;
  daily_evidence_runs: Array<{
    run_id: string;
    status: string;
    integrity_valid: boolean;
    decision_outcome: string | null;
    production_gate_status: string | null;
    scan_run_id: string | null;
  }>;
  scans: Array<{
    run_id: string;
    status: string;
    integrity_valid: boolean;
    market_date: string | null;
    selected_signal_count: number;
    raw_signal_count: number;
    normal_no_signal: boolean;
    account_blocked_buys: Array<{
      symbol: string;
      board: string;
      reason: string;
    }>;
    reason_codes: string[];
  }>;
  candidates: DailyReportCandidate[];
  blocked_signals: DailyReportBlockedSignal[];
  blocked_signal_count: number;
  research_previews: Array<{
    run_id: string;
    selection_id: string;
    status: string;
    normalized_research_status?: string;
    research_winner_candidate_id?: string | null;
    dataset_snapshot_id?: string | null;
    formula_fingerprint?: string | null;
    operations: DailyReportResearchOperation[];
    research_only: true;
  }>;
  research_history_status: 'complete' | 'unavailable';
  authoritative_candidate_count: number;
  reason_codes: string[];
  candidate_outcomes?: {
    schema_version: 'karkinos.decision.candidate_outcomes.v1';
    items: CandidateOutcome[];
    formal_authoritative_directional_hits: Record<
      (typeof OUTCOME_HORIZONS)[number],
      {
        observed_count: number;
        directional_hit_count: number;
        directional_hit_rate: number | null;
      }
    >;
  };
  read_only: true;
  authorizes_execution: false;
};

type DailyDecisionReportIndex = {
  schema_version: 'karkinos.decision.daily_report_index.v1';
  status: 'complete' | 'partial' | 'unavailable';
  reports: DailyDecisionReport[];
  has_more: boolean;
  blockers: string[];
};

function useDailyDecisionReportsQuery(page: number) {
  return useQuery({
    queryKey: ['decision', 'daily-reports', page],
    queryFn: () =>
      apiClient<DailyDecisionReportIndex>(
        `/api/decision/daily-reports?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`,
      ),
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  });
}

function outcomeReason(code: string | undefined, locale: 'zh' | 'en') {
  const reasons = {
    research_snapshot_source_unbound: {
      zh: '历史研究快照未绑定行情来源',
      en: 'Historical research snapshot has no market source binding',
    },
    horizon_receipt_missing: {
      zh: '目标日缺少同源行情收据',
      en: 'Target session has no receipt from the same source',
    },
    daily_receipt_unverified: {
      zh: '行情收据校验失败',
      en: 'Market receipt verification failed',
    },
    historical_price_basis_unverified: {
      zh: '旧版行情收据缺少价格基准证明',
      en: 'Legacy market receipt has no verified price basis',
    },
  } as const;
  if (code && code in reasons) {
    return reasons[code as keyof typeof reasons][locale];
  }
  return formatPublicCode(code ?? 'candidate_outcome_unavailable', locale);
}

function CandidateOutcomeView({
  outcome,
  locale,
}: {
  outcome: CandidateOutcome | undefined;
  locale: 'zh' | 'en';
}) {
  if (!outcome) return null;
  const zh = locale === 'zh';
  return (
    <div className="mt-1 space-y-0.5 pl-2 text-xs">
      <div>
        {zh ? '假设价格变化' : 'Hypothetical price move'} ·{' '}
        {outcome.anchor_status === 'verified'
          ? zh
            ? '收据已核验；精确信息可用时间未核验'
            : 'Receipt verified; exact availability time unverified'
          : `${zh ? '不可评估' : 'Unavailable'} · ${outcomeReason(outcome.reason_code, locale)}`}
      </div>
      {outcome.anchor?.receipt_fingerprint ? (
        <div className="break-all font-mono text-[10px]">
          {zh ? '锚点收据' : 'Anchor receipt'}:{' '}
          {outcome.anchor.receipt_fingerprint}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono tabular-nums">
        {OUTCOME_HORIZONS.map((horizon) => {
          const value = outcome.horizons[horizon];
          return (
            <span key={horizon}>
              {horizon}:{' '}
              {value.status === 'observed' &&
              typeof value.price_move_pct === 'number'
                ? `${value.price_move_pct > 0 ? '+' : ''}${value.price_move_pct.toFixed(2)}%`
                : value.status === 'pending'
                  ? zh
                    ? '待到期'
                    : 'Pending'
                  : `${zh ? '不可评估' : 'Unavailable'} (${outcomeReason(value.reason_code, locale)})`}
            </span>
          );
        })}
      </div>
    </div>
  );
}

const statusLabels = {
  zh: {
    missing_run: '未形成当日报告',
    failed: '生成失败',
    blocked: '证据阻断',
    completed_no_signal: '完成扫描 · 无信号',
    formal_candidate: '正式候选',
  },
  en: {
    missing_run: 'No daily report',
    failed: 'Generation failed',
    blocked: 'Evidence blocked',
    completed_no_signal: 'Scan complete · no signal',
    formal_candidate: 'Formal candidate',
  },
} as const;

function statusTone(status: DailyDecisionReport['status']) {
  if (status === 'formal_candidate') return 'success';
  if (status === 'completed_no_signal') return 'neutral';
  return 'warning';
}

export function DailyDecisionReportPanel({ locale }: { locale: 'zh' | 'en' }) {
  const [page, setPage] = useState(0);
  const reportsQuery = useDailyDecisionReportsQuery(page);
  const [expandedDate, setExpandedDate] = useState<string | null>(null);
  const detailQuery = useQuery({
    queryKey: ['decision', 'daily-report', expandedDate],
    queryFn: () =>
      apiClient<DailyDecisionReport>(
        `/api/decision/daily-reports/${expandedDate}`,
      ),
    enabled: expandedDate !== null,
    staleTime: 15_000,
  });
  const labels =
    locale === 'zh'
      ? {
          title: '每日决策记录',
          detail:
            '按当时保存的运行与信号复盘；失败、未运行和研究预览均单独保留。',
          loading: '正在读取每日记录…',
          error: '每日记录读取失败。',
          unavailable: '缺少已核验交易日历，无法确认历史覆盖范围。',
          partial: '更早交易日历未核验，历史覆盖范围不完整。',
          researchUnavailable: '研究记录不可核验，不能判定该日没有研究预览。',
          noCandidate: '当日没有已绑定最终报告的正式候选。',
          formal: '正式信号',
          orphan: '信号未绑定当日最终报告',
          research: '研究预览 · 不构成账户买入建议',
          attempt: '当日尝试',
          final: '最终证据',
          scan: '扫描',
          accountBlocked: '账户条件未通过',
          blockedSourceUnavailable: '原始信号未保存完整，无法核验后续表现。',
          reason: '原因',
          failure: '失败阶段',
          previous: '较新日期',
          next: '更早日期',
          source: '来源',
          frozen: '信号冻结价',
          detailLoading: '正在核验当日复盘…',
          detailError: '当日复盘详情读取失败。',
          outcomeMethod:
            '复盘按次一交易日开盘至目标日收盘计算，未计费用、分红或实际成交。',
          formalHits: '正式信号方向命中',
          formalCoverage: '正式候选',
          observed: '已评估',
        }
      : {
          title: 'Daily decision history',
          detail:
            'Replays persisted runs and signals. Failures, missing days, and research previews remain distinct.',
          loading: 'Reading daily reports…',
          error: 'Daily reports could not be read.',
          unavailable:
            'A verified trading calendar is needed for history coverage.',
          partial:
            'Older trading calendars are unverified; history coverage is incomplete.',
          researchUnavailable:
            'Research history could not be verified for this day.',
          noCandidate: 'No formal candidate is bound to a final daily report.',
          formal: 'Formal signal',
          orphan: 'Signal not bound to the final daily report',
          research: 'Research preview · not an account buy recommendation',
          attempt: 'Daily attempt',
          final: 'Final evidence',
          scan: 'Scan',
          accountBlocked: 'Account eligibility blocked',
          blockedSourceUnavailable:
            'The frozen raw signal is incomplete, so its later price move cannot be verified.',
          reason: 'Reason',
          failure: 'Failure stage',
          previous: 'Newer dates',
          next: 'Older dates',
          source: 'Source',
          frozen: 'Frozen signal price',
          detailLoading: 'Verifying this daily report…',
          detailError: 'Daily report detail could not be read.',
          outcomeMethod:
            'Price moves run from the next session open to the target close; fees, dividends and actual fills are excluded.',
          formalHits: 'Formal signal directional hits',
          formalCoverage: 'Formal candidates',
          observed: 'Observed',
        };

  return (
    <section data-testid="daily-decision-report-panel" className="min-w-0">
      <div className="app-product-mark">{labels.title}</div>
      <p className="app-muted mt-1 text-xs leading-5">{labels.detail}</p>
      {reportsQuery.isLoading ? (
        <p role="status" className="app-muted mt-3 text-sm">
          {labels.loading}
        </p>
      ) : reportsQuery.isError || !reportsQuery.data ? (
        <p role="alert" className="app-error-text mt-3 text-sm">
          {labels.error}
        </p>
      ) : reportsQuery.data.status === 'unavailable' ? (
        <p role="status" className="app-muted mt-3 text-sm">
          {labels.unavailable}
        </p>
      ) : (
        <>
          {reportsQuery.data.status === 'partial' ? (
            <p role="status" className="app-muted mt-3 text-xs">
              {labels.partial}
            </p>
          ) : null}
          <div className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {reportsQuery.data.reports.map((report) => {
              const expanded = expandedDate === report.report_date;
              const detail =
                expanded && detailQuery.data?.report_date === report.report_date
                  ? detailQuery.data
                  : null;
              const visible = detail ?? report;
              const outcomes = new Map(
                visible.candidate_outcomes?.items
                  .filter((item) => item.source_ref)
                  .map((item) => [item.source_ref, item]) ?? [],
              );
              return (
                <div key={report.report_date} className="py-2.5">
                  <button
                    type="button"
                    className="flex w-full min-w-0 items-center justify-between gap-3 text-left"
                    aria-expanded={expanded}
                    onClick={() =>
                      setExpandedDate(expanded ? null : report.report_date)
                    }
                  >
                    <span className="font-mono text-xs tabular-nums text-[var(--app-text)]">
                      {report.report_date}
                    </span>
                    <StatusBadge tone={statusTone(visible.status)}>
                      {statusLabels[locale][visible.status]}
                    </StatusBadge>
                  </button>
                  {expanded ? (
                    <div className="mt-3 space-y-3 text-xs leading-5 text-[var(--app-text-secondary)]">
                      {detailQuery.isLoading ? (
                        <p role="status">{labels.detailLoading}</p>
                      ) : null}
                      {detailQuery.isError ? (
                        <p role="alert">{labels.detailError}</p>
                      ) : null}
                      {detail ? <p>{labels.outcomeMethod}</p> : null}
                      {visible.attempts.map((attempt) => (
                        <div key={attempt.run_id}>
                          <div>
                            {labels.attempt}: {attempt.status}
                          </div>
                          {attempt.failure_code ? (
                            <div>
                              {labels.failure}: {attempt.failure_stage ?? '--'}{' '}
                              · {formatPublicCode(attempt.failure_code, locale)}
                            </div>
                          ) : null}
                          <div className="break-all font-mono">
                            {attempt.run_id}
                          </div>
                        </div>
                      ))}
                      {visible.daily_evidence_runs.map((run) => (
                        <div key={run.run_id}>
                          {labels.final}: {run.status} ·{' '}
                          {run.decision_outcome ?? '--'}
                          <div className="break-all font-mono">
                            {run.run_id}
                          </div>
                        </div>
                      ))}
                      {visible.scans.map((scan) => (
                        <div key={scan.run_id}>
                          {labels.scan}: {scan.status} ·{' '}
                          {scan.selected_signal_count}
                          <div className="break-all font-mono">
                            {scan.run_id}
                          </div>
                        </div>
                      ))}
                      {visible.blocked_signals.map((item, index) => (
                        <div
                          key={`${item.scan_run_id}:${item.symbol}:${index}`}
                        >
                          <span className="font-semibold text-[var(--app-text)]">
                            {item.symbol}
                          </span>{' '}
                          · {labels.accountBlocked} · {item.board} ·{' '}
                          {formatPublicCode(item.reason, locale)}
                          {typeof item.frozen_price === 'number' ? (
                            <div>
                              {labels.frozen} ({item.frozen_market_date ?? '--'}
                              ): {item.frozen_price.toFixed(2)}
                            </div>
                          ) : null}
                          {item.source_ref ? (
                            <div className="break-all font-mono">
                              {labels.source}: {item.source_ref}
                            </div>
                          ) : null}
                          {!item.source_bound ? (
                            <div>{labels.blockedSourceUnavailable}</div>
                          ) : null}
                          <CandidateOutcomeView
                            outcome={outcomes.get(item.source_ref)}
                            locale={locale}
                          />
                        </div>
                      ))}
                      {visible.candidates.length === 0 ? (
                        <p>{labels.noCandidate}</p>
                      ) : (
                        visible.candidates.map((candidate) => (
                          <div key={candidate.source_ref}>
                            <span className="font-semibold text-[var(--app-text)]">
                              {candidate.symbol} · {candidate.direction}
                            </span>{' '}
                            ·{' '}
                            {candidate.report_authoritative
                              ? labels.formal
                              : labels.orphan}
                            {typeof candidate.frozen_price === 'number' ? (
                              <div>
                                {labels.frozen} (
                                {candidate.frozen_market_date ?? '--'}):{' '}
                                {candidate.frozen_price.toFixed(2)}
                              </div>
                            ) : null}
                            <div className="break-all font-mono">
                              {labels.source}: {candidate.source_ref}
                            </div>
                            <CandidateOutcomeView
                              outcome={outcomes.get(candidate.source_ref)}
                              locale={locale}
                            />
                          </div>
                        ))
                      )}
                      {visible.research_previews.flatMap((research) =>
                        research.operations.map((operation) => (
                          <div key={operation.source_ref}>
                            <span className="font-semibold text-[var(--app-text)]">
                              {operation.symbol} · {operation.operation}
                            </span>{' '}
                            · {labels.research}
                            <div className="break-all font-mono">
                              {labels.source}: {operation.source_ref}
                            </div>
                            <CandidateOutcomeView
                              outcome={outcomes.get(operation.source_ref)}
                              locale={locale}
                            />
                          </div>
                        )),
                      )}
                      {detail?.candidate_outcomes
                        ? OUTCOME_HORIZONS.map((horizon) => {
                            const hits =
                              detail.candidate_outcomes!
                                .formal_authoritative_directional_hits[horizon];
                            return hits &&
                              visible.authoritative_candidate_count ? (
                              <div key={horizon}>
                                {labels.formalHits} {horizon}:{' '}
                                {hits.directional_hit_count}/
                                {hits.observed_count} · {labels.formalCoverage}{' '}
                                {visible.authoritative_candidate_count} ·{' '}
                                {labels.observed} {hits.observed_count}
                              </div>
                            ) : null;
                          })
                        : null}
                      {visible.research_history_status === 'unavailable' ? (
                        <p>{labels.researchUnavailable}</p>
                      ) : null}
                      {visible.reason_codes.slice(0, 5).map((reason) => (
                        <div key={reason}>
                          {labels.reason}: {formatPublicCode(reason, locale)}
                        </div>
                      ))}
                      <div className="break-all font-mono">
                        {labels.source}: {visible.calendar_evidence_ref}
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs disabled:opacity-50"
              disabled={page === 0}
              onClick={() => {
                setExpandedDate(null);
                setPage((value) => value - 1);
              }}
            >
              {labels.previous}
            </button>
            <button
              type="button"
              className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs disabled:opacity-50"
              disabled={!reportsQuery.data.has_more}
              onClick={() => {
                setExpandedDate(null);
                setPage((value) => value + 1);
              }}
            >
              {labels.next}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
