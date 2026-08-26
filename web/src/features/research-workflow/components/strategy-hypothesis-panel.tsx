import { formatCurrency, formatPercent } from '../../../shared/format';
import type { StrategyHypothesisBacktestEvidence } from '../research-workflow-feature-boundary';
import { STRATEGY_HYPOTHESIS_COPY } from './strategy-hypothesis-copy';
import {
  type ReviewDisposition,
  type StrategyHypothesisController,
  useStrategyHypothesisController,
} from './use-strategy-hypothesis-controller';
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

export function StrategyHypothesisPanel({
  report,
}: {
  report: StrategyHypothesisBacktestEvidence | null;
}) {
  const controller = useStrategyHypothesisController(report);
  if (!controller.open) {
    return (
      <StrategyHypothesisCollapsed
        copy={controller.copy}
        onOpen={() => controller.setOpen(true)}
      />
    );
  }
  return <StrategyHypothesisWorkspace controller={controller} />;
}

function StrategyHypothesisWorkspace({
  controller,
}: {
  controller: StrategyHypothesisController;
}) {
  const {
    accountAlias,
    accountReady,
    accountSummary,
    assets,
    backtestConfirmed,
    canonical,
    copy,
    costModelReference,
    critique,
    critiqueArtifact,
    critiqueConfirmed,
    exportConfirmed,
    generate,
    operator,
    question,
    report,
    researchCompleted,
    researchCurrent,
    review,
    reviewDisposition,
    reviewNote,
    reviewRecorded,
    runBacktest,
    selectedDraft,
    selectedDraftId,
    selectionBlocker,
    selectionReady,
    setAccountAlias,
    setBacktestConfirmed,
    setCritiqueConfirmed,
    setExportConfirmed,
    setOpen,
    setOperator,
    setQuestion,
    setReviewDisposition,
    setReviewNote,
    selectDraft,
    snapshot,
    submitBacktest,
    submitCritique,
    submitHypothesis,
    submitReview,
  } = controller;

  return (
    <section
      className="app-ai-research-boundary p-4 sm:p-5"
      data-evidence-kind="cited-ai-research"
      aria-labelledby="ai-strategy-research-title"
    >
      <StrategyHypothesisHeader copy={copy} onClose={() => setOpen(false)} />

      <StrategySelectionIdentity
        accountBinding={
          accountReady
            ? `${accountSummary?.valuation_snapshot_id} · ledger ${accountSummary?.ledger_cutoff_id}`
            : copy.missingAccount
        }
        accountReady={accountReady}
        copy={copy}
        cost={costModelReference || copy.missingReviewedCosts}
        dataset={snapshot?.snapshot_id ?? copy.missingSnapshot}
        savedBacktest={report ? `#${report.id}` : copy.missingReport}
        universe={assets.map((asset) => asset.symbol).join(', ') || '—'}
        window={
          report
            ? `${report.config.start_date} → ${report.config.end_date}`
            : '—'
        }
      />

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
        <StrategyDraftsSection
          backtestConfirmed={backtestConfirmed}
          backtestPending={runBacktest.isPending}
          canBacktest={
            researchCompleted &&
            researchCurrent &&
            selectedDraft?.validation.status === 'valid'
          }
          copy={copy}
          current={researchCompleted && researchCurrent}
          onBacktest={submitBacktest}
          onBacktestConfirmationChange={setBacktestConfirmed}
          onSelectDraft={selectDraft}
          selectedDraftId={selectedDraftId}
          session={generate.data}
        />
      ) : null}

      <StrategyResearchResults
        canonical={canonical}
        copy={copy}
        critique={critique}
        critiqueArtifact={critiqueArtifact}
        critiqueConfirmed={critiqueConfirmed}
        onCritique={submitCritique}
        onCritiqueConfirmationChange={setCritiqueConfirmed}
        onReview={submitReview}
        review={review}
        reviewDisposition={reviewDisposition}
        reviewNote={reviewNote}
        reviewRecorded={reviewRecorded}
        runBacktestError={runBacktest.isError}
        setReviewDisposition={setReviewDisposition}
        setReviewNote={setReviewNote}
      />
    </section>
  );
}

function StrategySelectionIdentity({
  accountBinding,
  accountReady,
  copy,
  cost,
  dataset,
  savedBacktest,
  universe,
  window,
}: {
  accountBinding: string;
  accountReady: boolean;
  copy: (typeof STRATEGY_HYPOTHESIS_COPY)[keyof typeof STRATEGY_HYPOTHESIS_COPY];
  cost: string;
  dataset: string;
  savedBacktest: string;
  universe: string;
  window: string;
}) {
  return (
    <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <Identity label={copy.savedBacktest} value={savedBacktest} />
      <Identity label={copy.dataset} value={dataset} mono />
      <Identity label={copy.window} value={window} mono />
      <Identity label={copy.universe} value={universe} mono />
      <Identity label={copy.cost} value={cost} mono />
      <Identity
        label={copy.accountBinding}
        value={accountBinding}
        mono={accountReady}
      />
    </div>
  );
}

function StrategyHypothesisCollapsed({
  copy,
  onOpen,
}: {
  copy: (typeof STRATEGY_HYPOTHESIS_COPY)[keyof typeof STRATEGY_HYPOTHESIS_COPY];
  onOpen: () => void;
}) {
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
        onClick={onOpen}
      >
        {copy.open}
      </button>
    </section>
  );
}

function StrategyHypothesisHeader({
  copy,
  onClose,
}: {
  copy: (typeof STRATEGY_HYPOTHESIS_COPY)[keyof typeof STRATEGY_HYPOTHESIS_COPY];
  onClose: () => void;
}) {
  return (
    <>
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
          onClick={onClose}
        >
          {copy.close}
        </button>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs font-semibold">
        <BoundaryBadge text={copy.noAuthority} />
        <BoundaryBadge text={copy.humanGated} />
      </div>
    </>
  );
}

function StrategyDraftsSection({
  backtestConfirmed,
  backtestPending,
  canBacktest,
  copy,
  current,
  onBacktest,
  onBacktestConfirmationChange,
  onSelectDraft,
  selectedDraftId,
  session,
}: {
  backtestConfirmed: boolean;
  backtestPending: boolean;
  canBacktest: boolean;
  copy: (typeof STRATEGY_HYPOTHESIS_COPY)[keyof typeof STRATEGY_HYPOTHESIS_COPY];
  current: boolean;
  onBacktest: () => Promise<void>;
  onBacktestConfirmationChange: (checked: boolean) => void;
  onSelectDraft: (draftId: string) => void;
  selectedDraftId: string;
  session: NonNullable<StrategyHypothesisController['generate']['data']>;
}) {
  return (
    <div className="mt-6 border-t border-[var(--app-border)] pt-5">
      <h3 className="text-base font-semibold text-[var(--app-text)]">
        {copy.drafts}
      </h3>
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        {session.drafts.map((draft) => (
          <DraftCard
            key={draft.draft_id}
            copy={copy}
            draft={draft}
            selected={selectedDraftId === draft.draft_id}
            current={current}
            onSelect={() => onSelectDraft(draft.draft_id)}
          />
        ))}
      </div>
      {canBacktest ? (
        <div className="mt-4 grid gap-3">
          <Confirmation
            checked={backtestConfirmed}
            label={copy.backtestConfirm}
            onChange={onBacktestConfirmationChange}
          />
          <div>
            <button
              className="app-button-primary"
              type="button"
              onClick={() => void onBacktest()}
              disabled={!backtestConfirmed || backtestPending}
            >
              {backtestPending ? copy.runningBacktest : copy.runBacktest}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StrategyResearchResults({
  canonical,
  copy,
  critique,
  critiqueArtifact,
  critiqueConfirmed,
  onCritique,
  onCritiqueConfirmationChange,
  onReview,
  review,
  reviewDisposition,
  reviewNote,
  reviewRecorded,
  runBacktestError,
  setReviewDisposition,
  setReviewNote,
}: {
  canonical:
    | NonNullable<
        StrategyHypothesisController['runBacktest']['data']
      >['canonical_backtest']
    | undefined;
  copy: (typeof STRATEGY_HYPOTHESIS_COPY)[keyof typeof STRATEGY_HYPOTHESIS_COPY];
  critique: StrategyHypothesisController['critique'];
  critiqueArtifact:
    | NonNullable<StrategyHypothesisController['critique']['data']>['artifact']
    | undefined;
  critiqueConfirmed: boolean;
  onCritique: () => Promise<void>;
  onCritiqueConfirmationChange: (checked: boolean) => void;
  onReview: () => Promise<void>;
  review: StrategyHypothesisController['review'];
  reviewDisposition: ReviewDisposition;
  reviewNote: string;
  reviewRecorded: boolean;
  runBacktestError: boolean;
  setReviewDisposition: (disposition: ReviewDisposition) => void;
  setReviewNote: (note: string) => void;
}) {
  return (
    <>
      {runBacktestError ? (
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
              onChange={onCritiqueConfirmationChange}
            />
            <div>
              <button
                className="app-button-primary"
                type="button"
                onClick={() => void onCritique()}
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
              onClick={() => void onReview()}
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
    </>
  );
}
