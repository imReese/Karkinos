import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import { formatCurrency, formatPercent } from '../../../shared/format';
import { useAccountStateQuery } from '../ai-research-feature-boundary';
import type { BacktestReport } from '../ai-research-feature-boundary';
import {
  useCritiqueStrategyBacktestMutation,
  useGenerateStrategyHypothesesMutation,
  useReviewStrategyResearchMutation,
  useRunStrategyFormulaBacktestMutation,
} from '../api';
import { STRATEGY_HYPOTHESIS_COPY } from './strategy-hypothesis-copy';
import {
  BoundaryBadge,
  Confirmation,
  DraftCard,
  FailClosedMessage,
  Identity,
  Label,
  Metric,
  provenanceSummary,
  TextBlock,
  TextList,
} from './strategy-hypothesis-view';

const REVIEWED_COST_MODEL_PREFIX =
  'karkinos.backtest.reviewed_account_fee_schedule.v1:';

let keySequence = 0;

function newKey(prefix: string) {
  keySequence += 1;
  return `${prefix}:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${keySequence}`}`;
}

export function StrategyHypothesisPanel({
  report,
}: {
  report: BacktestReport | null;
}) {
  const { locale } = usePreferences();
  const copy = STRATEGY_HYPOTHESIS_COPY[locale];
  const [open, setOpen] = useState(false);
  const [operator, setOperator] = useState('human:owner');
  const [accountAlias, setAccountAlias] = useState('strategy-research-only');
  const [question, setQuestion] = useState('');
  const [exportConfirmed, setExportConfirmed] = useState(false);
  const [selectedDraftId, setSelectedDraftId] = useState('');
  const [backtestConfirmed, setBacktestConfirmed] = useState(false);
  const [critiqueConfirmed, setCritiqueConfirmed] = useState(false);
  const [reviewNote, setReviewNote] = useState('');
  const [reviewDisposition, setReviewDisposition] = useState<
    'accepted_for_more_research' | 'needs_revision' | 'rejected'
  >('needs_revision');
  const [reviewRecorded, setReviewRecorded] = useState(false);
  const [hypothesisKey, setHypothesisKey] = useState(() =>
    newKey('ai-strategy-hypothesis'),
  );
  const [backtestKey, setBacktestKey] = useState(() =>
    newKey('ai-formula-backtest'),
  );
  const [critiqueKey, setCritiqueKey] = useState(() =>
    newKey('ai-strategy-critique'),
  );
  const [reviewKey, setReviewKey] = useState(() =>
    newKey('ai-strategy-review'),
  );
  const generate = useGenerateStrategyHypothesesMutation();
  const runBacktest = useRunStrategyFormulaBacktestMutation();
  const critique = useCritiqueStrategyBacktestMutation();
  const review = useReviewStrategyResearchMutation();
  const accountState = useAccountStateQuery();

  const snapshot = report?.metrics_json?.dataset_snapshot;
  const feeEvidence = report?.metrics_json?.fee_component_evidence;
  const costModelReference = feeEvidence?.cost_model_reference ?? '';
  const accountSummary = accountState.data?.summary;
  const assets = report?.config.assets ?? [];
  const datasetReady = Boolean(
    snapshot?.snapshot_id &&
    snapshot.data_quality?.status === 'ok' &&
    assets.length > 0,
  );
  const reviewedCostsReady = Boolean(
    costModelReference.startsWith(REVIEWED_COST_MODEL_PREFIX) &&
    feeEvidence?.status === 'complete' &&
    feeEvidence.account_specific === true &&
    feeEvidence.broker_statement_reconciled === true,
  );
  const accountReady = Boolean(
    accountSummary?.valuation_status === 'complete' &&
    accountSummary.valuation_snapshot_id &&
    accountSummary.ledger_cutoff_id !== undefined &&
    report &&
    report.config.initial_cash <= accountSummary.total_equity,
  );
  const selectionReady = Boolean(
    report && datasetReady && reviewedCostsReady && accountReady,
  );
  const selectionBlocker = !report
    ? copy.missingReport
    : !datasetReady
      ? copy.missingSnapshot
      : !reviewedCostsReady
        ? copy.missingReviewedCosts
        : !accountReady
          ? copy.missingAccount
          : '';
  const selectedDraft = useMemo(
    () =>
      generate.data?.drafts.find(
        (draft) => draft.draft_id === selectedDraftId,
      ) ?? null,
    [generate.data?.drafts, selectedDraftId],
  );
  const researchCurrent =
    generate.data?.binding_validity !== 'invalidated_by_drift';
  const researchCompleted = generate.data?.status === 'completed';

  useEffect(() => {
    generate.reset();
    runBacktest.reset();
    critique.reset();
    review.reset();
    setSelectedDraftId('');
    setExportConfirmed(false);
    setBacktestConfirmed(false);
    setCritiqueConfirmed(false);
    setReviewRecorded(false);
  }, [report?.id]);

  const submitHypothesis = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !report ||
      !snapshot ||
      !accountSummary ||
      !selectionReady ||
      !exportConfirmed
    )
      return;
    try {
      const session = await generate.mutateAsync({
        idempotency_key: hypothesisKey,
        requested_by: operator.trim(),
        account_alias: accountAlias.trim(),
        research_question: question.trim(),
        selection: {
          saved_backtest_result_id: report.id,
          universe: assets.map((asset) => asset.symbol),
          asset_classes: assets.map((asset) => asset.asset_class),
          dataset_snapshot_id: snapshot.snapshot_id,
          start_date: report.config.start_date,
          end_date: report.config.end_date,
          frequency: '1d',
          initial_cash: report.config.initial_cash,
          cost_model_reference: costModelReference,
          valuation_snapshot_id: accountSummary.valuation_snapshot_id ?? '',
          ledger_cutoff_id: accountSummary.ledger_cutoff_id ?? 0,
        },
      });
      const firstValid = session.drafts.find(
        (draft) => draft.validation.status === 'valid',
      );
      setSelectedDraftId(
        firstValid?.draft_id ?? session.drafts[0]?.draft_id ?? '',
      );
      setHypothesisKey(newKey('ai-strategy-hypothesis'));
      setExportConfirmed(false);
    } catch {
      // Mutation state renders a fail-closed error with no automatic retry.
    }
  };

  const submitBacktest = async () => {
    if (!generate.data || !selectedDraft || !backtestConfirmed) return;
    try {
      await runBacktest.mutateAsync({
        idempotency_key: backtestKey,
        requested_by: operator.trim(),
        session_id: generate.data.session_id,
        draft_id: selectedDraft.draft_id,
      });
      setBacktestKey(newKey('ai-formula-backtest'));
      setBacktestConfirmed(false);
    } catch {
      // Stable key remains for audited idempotent replay.
    }
  };

  const submitCritique = async () => {
    if (
      !generate.data ||
      !selectedDraft ||
      !runBacktest.data ||
      !critiqueConfirmed
    )
      return;
    try {
      await critique.mutateAsync({
        idempotency_key: critiqueKey,
        requested_by: operator.trim(),
        session_id: generate.data.session_id,
        draft_id: selectedDraft.draft_id,
        backtest_run_id: runBacktest.data.backtest_run_id,
      });
      setCritiqueKey(newKey('ai-strategy-critique'));
      setCritiqueConfirmed(false);
    } catch {
      // Stable key remains for audited idempotent replay.
    }
  };

  const submitReview = async () => {
    if (!generate.data || !critique.data || !reviewNote.trim()) return;
    try {
      await review.mutateAsync({
        idempotency_key: reviewKey,
        session_id: generate.data.session_id,
        critique_id: critique.data.critique_id,
        reviewer: operator.trim(),
        disposition: reviewDisposition,
        notes: reviewNote.trim(),
      });
      setReviewKey(newKey('ai-strategy-review'));
      setReviewRecorded(true);
    } catch {
      // Mutation state renders the failure.
    }
  };

  if (!open) {
    return (
      <section
        className="app-ai-research-boundary flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5"
        data-evidence-kind="cited-ai-research"
      >
        <div>
          <div className="app-kicker">{copy.kicker}</div>
          <h2 className="mt-2 text-lg font-semibold text-[var(--app-text)]">
            {copy.title}
          </h2>
          <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
            {copy.detail}
          </p>
        </div>
        <button
          className="app-button-secondary shrink-0"
          type="button"
          onClick={() => setOpen(true)}
        >
          {copy.open}
        </button>
      </section>
    );
  }

  const canonical = runBacktest.data?.canonical_backtest;
  const critiqueArtifact = critique.data?.artifact;

  return (
    <section
      className="app-ai-research-boundary p-4 sm:p-5"
      data-evidence-kind="cited-ai-research"
      aria-labelledby="ai-strategy-research-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="app-kicker">{copy.kicker}</div>
          <h2
            id="ai-strategy-research-title"
            className="mt-2 text-lg font-semibold text-[var(--app-text)]"
          >
            {copy.title}
          </h2>
          <p className="app-muted mt-2 max-w-4xl text-sm leading-6">
            {copy.detail}
          </p>
        </div>
        <button
          className="app-button-secondary"
          type="button"
          onClick={() => setOpen(false)}
        >
          {copy.close}
        </button>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs font-semibold">
        <BoundaryBadge text={copy.noAuthority} />
        <BoundaryBadge text={copy.humanGated} />
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Identity
          label={copy.savedBacktest}
          value={report ? `#${report.id}` : copy.missingReport}
        />
        <Identity
          label={copy.dataset}
          value={snapshot?.snapshot_id ?? copy.missingSnapshot}
          mono
        />
        <Identity
          label={copy.window}
          value={
            report
              ? `${report.config.start_date} → ${report.config.end_date}`
              : '—'
          }
          mono
        />
        <Identity
          label={copy.universe}
          value={assets.map((asset) => asset.symbol).join(', ') || '—'}
          mono
        />
        <Identity
          label={copy.cost}
          value={costModelReference || copy.missingReviewedCosts}
          mono
        />
        <Identity
          label={copy.accountBinding}
          value={
            accountReady
              ? `${accountSummary?.valuation_snapshot_id} · ledger ${accountSummary?.ledger_cutoff_id}`
              : copy.missingAccount
          }
          mono={accountReady}
        />
      </div>

      {!selectionReady ? (
        <div
          className="mt-4 rounded-2xl border border-[var(--app-danger)] bg-[var(--app-danger-bg)] p-4 text-sm text-[var(--app-danger)]"
          role="alert"
        >
          {selectionBlocker}
        </div>
      ) : null}

      <form className="mt-5 grid gap-4" onSubmit={submitHypothesis}>
        <div className="grid gap-3 md:grid-cols-2">
          <Label text={copy.operator}>
            <input
              className="app-input"
              required
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
            />
          </Label>
          <Label text={copy.account}>
            <input
              className="app-input"
              required
              value={accountAlias}
              onChange={(event) => setAccountAlias(event.target.value)}
            />
          </Label>
        </div>
        <Label text={copy.question}>
          <textarea
            className="app-input min-h-24 resize-y"
            required
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </Label>
        <Confirmation
          checked={exportConfirmed}
          label={copy.exportConfirm}
          onChange={setExportConfirmed}
        />
        <div>
          <button
            className="app-button-primary"
            type="submit"
            disabled={
              !selectionReady ||
              !exportConfirmed ||
              !question.trim() ||
              generate.isPending
            }
          >
            {generate.isPending ? copy.generating : copy.generate}
          </button>
        </div>
      </form>

      {generate.isError ? (
        <FailClosedMessage text={copy.externalError} />
      ) : null}
      {generate.data && (!researchCompleted || !researchCurrent) ? (
        <FailClosedMessage
          text={
            !researchCurrent
              ? `${copy.invalidated} ${generate.data.binding_errors.join(', ')}`
              : `${copy.incomplete}: ${generate.data.status}${generate.data.failure_code ? ` (${generate.data.failure_code})` : ''}`
          }
        />
      ) : null}

      {generate.data ? (
        <div className="mt-6 border-t border-[var(--app-border)] pt-5">
          <h3 className="text-base font-semibold text-[var(--app-text)]">
            {copy.drafts}
          </h3>
          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            {generate.data.drafts.map((draft) => (
              <DraftCard
                key={draft.draft_id}
                copy={copy}
                draft={draft}
                selected={selectedDraftId === draft.draft_id}
                current={researchCompleted && researchCurrent}
                onSelect={() => {
                  setSelectedDraftId(draft.draft_id);
                  runBacktest.reset();
                  critique.reset();
                  setBacktestConfirmed(false);
                  setCritiqueConfirmed(false);
                }}
              />
            ))}
          </div>
          {researchCompleted &&
          researchCurrent &&
          selectedDraft?.validation.status === 'valid' ? (
            <div className="mt-4 grid gap-3">
              <Confirmation
                checked={backtestConfirmed}
                label={copy.backtestConfirm}
                onChange={setBacktestConfirmed}
              />
              <div>
                <button
                  className="app-button-primary"
                  type="button"
                  onClick={submitBacktest}
                  disabled={!backtestConfirmed || runBacktest.isPending}
                >
                  {runBacktest.isPending
                    ? copy.runningBacktest
                    : copy.runBacktest}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {runBacktest.isError ? (
        <FailClosedMessage text={copy.externalError} />
      ) : null}
      {canonical ? (
        <div className="mt-6 border-t border-[var(--app-border)] pt-5">
          <h3 className="text-base font-semibold text-[var(--app-text)]">
            {copy.result}
          </h3>
          <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric
              label={copy.totalReturn}
              value={formatPercent(canonical.total_return)}
            />
            <Metric
              label={copy.drawdown}
              value={formatPercent(-Math.abs(canonical.max_drawdown))}
            />
            <Metric
              label={copy.commission}
              value={formatCurrency(
                canonical.cost_summary.total_commission ?? 0,
              )}
            />
            <Metric
              label={copy.trades}
              value={String(canonical.cost_summary.total_trades ?? 0)}
            />
          </div>
          <div className="mt-4 grid gap-3">
            <Confirmation
              checked={critiqueConfirmed}
              label={copy.critiqueConfirm}
              onChange={setCritiqueConfirmed}
            />
            <div>
              <button
                className="app-button-primary"
                type="button"
                onClick={submitCritique}
                disabled={!critiqueConfirmed || critique.isPending}
              >
                {critique.isPending ? copy.critiquing : copy.critique}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {critique.isError ? (
        <FailClosedMessage text={copy.externalError} />
      ) : null}
      {critiqueArtifact ? (
        <div className="mt-6 border-t border-[var(--app-border)] pt-5">
          <h3 className="text-base font-semibold text-[var(--app-text)]">
            {copy.critiqueTitle}
          </h3>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <TextList
              title={copy.supported}
              items={critiqueArtifact.supported_claims}
            />
            <TextList
              title={copy.contradicted}
              items={critiqueArtifact.contradicted_claims}
            />
            <TextList
              title={copy.gaps}
              items={critiqueArtifact.evidence_gaps}
            />
            <TextList
              title={copy.robustness}
              items={critiqueArtifact.recommended_walk_forward_stress_tests}
            />
          </div>
          <p className="app-muted mt-3 text-sm">
            <strong className="text-[var(--app-text)]">
              {copy.uncertainty}:{' '}
            </strong>
            {critiqueArtifact.uncertainty}
          </p>
          <TextBlock
            title={copy.providerEvidence}
            value={provenanceSummary(
              critique.data?.provider_id,
              critique.data?.model_id,
              critique.data?.prompt_version,
              critiqueArtifact.provider_provenance,
            )}
            mono
          />

          <div className="mt-5 rounded-2xl border border-[var(--app-border)] p-4">
            <h4 className="font-semibold text-[var(--app-text)]">
              {copy.finalReview}
            </h4>
            <div className="mt-3 flex flex-wrap gap-4 text-sm">
              {(
                [
                  ['accepted_for_more_research', copy.accept],
                  ['needs_revision', copy.revise],
                  ['rejected', copy.reject],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="inline-flex items-center gap-2">
                  <input
                    type="radio"
                    name="strategy-review"
                    checked={reviewDisposition === value}
                    onChange={() => setReviewDisposition(value)}
                  />
                  {label}
                </label>
              ))}
            </div>
            <Label text={copy.reviewNote}>
              <textarea
                className="app-input mt-2 min-h-20 resize-y"
                value={reviewNote}
                onChange={(event) => setReviewNote(event.target.value)}
              />
            </Label>
            <button
              className="app-button-primary mt-3"
              type="button"
              onClick={submitReview}
              disabled={!reviewNote.trim() || review.isPending}
            >
              {review.isPending ? copy.recordingReview : copy.recordReview}
            </button>
            {reviewRecorded ? (
              <p
                className="mt-3 text-sm text-[var(--app-success)]"
                role="status"
              >
                {copy.reviewRecorded}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
