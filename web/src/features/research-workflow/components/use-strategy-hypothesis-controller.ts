import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  useAccountStateQuery,
  type StrategyHypothesisBacktestEvidence,
} from '../research-workflow-feature-boundary';
import {
  useCritiqueStrategyBacktestMutation,
  useGenerateStrategyHypothesesMutation,
  useReviewStrategyResearchMutation,
  useRunStrategyFormulaBacktestMutation,
} from '../strategy-research-api';
import { STRATEGY_HYPOTHESIS_COPY } from './strategy-hypothesis-copy';

const REVIEWED_COST_MODEL_PREFIX =
  'karkinos.backtest.reviewed_account_fee_schedule.v1:';

export type ReviewDisposition =
  'accepted_for_more_research' | 'needs_revision' | 'rejected';

let keySequence = 0;

function newKey(prefix: string) {
  keySequence += 1;
  return `${prefix}:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${keySequence}`}`;
}

function selectionBlockerFor(
  copy: (typeof STRATEGY_HYPOTHESIS_COPY)[keyof typeof STRATEGY_HYPOTHESIS_COPY],
  reportReady: boolean,
  datasetReady: boolean,
  reviewedCostsReady: boolean,
  accountReady: boolean,
) {
  if (!reportReady) return copy.missingReport;
  if (!datasetReady) return copy.missingSnapshot;
  if (!reviewedCostsReady) return copy.missingReviewedCosts;
  if (!accountReady) return copy.missingAccount;
  return '';
}

function useStrategyHypothesisFormState() {
  const [open, setOpen] = useState(false);
  const [operator, setOperator] = useState('human:owner');
  const [accountAlias, setAccountAlias] = useState('strategy-research-only');
  const [question, setQuestion] = useState('');
  const [exportConfirmed, setExportConfirmed] = useState(false);
  const [selectedDraftId, setSelectedDraftId] = useState('');
  const [backtestConfirmed, setBacktestConfirmed] = useState(false);
  const [critiqueConfirmed, setCritiqueConfirmed] = useState(false);
  const [reviewNote, setReviewNote] = useState('');
  const [reviewDisposition, setReviewDisposition] =
    useState<ReviewDisposition>('needs_revision');
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

  return {
    accountAlias,
    backtestConfirmed,
    backtestKey,
    critiqueConfirmed,
    critiqueKey,
    exportConfirmed,
    hypothesisKey,
    open,
    operator,
    question,
    reviewDisposition,
    reviewKey,
    reviewNote,
    reviewRecorded,
    selectedDraftId,
    setAccountAlias,
    setBacktestConfirmed,
    setBacktestKey,
    setCritiqueConfirmed,
    setCritiqueKey,
    setExportConfirmed,
    setHypothesisKey,
    setOpen,
    setOperator,
    setQuestion,
    setReviewDisposition,
    setReviewKey,
    setReviewNote,
    setReviewRecorded,
    setSelectedDraftId,
  };
}

function useResetStrategyHypothesisOnReportChange({
  critique,
  form,
  generate,
  reportId,
  review,
  runBacktest,
}: {
  critique: ReturnType<typeof useCritiqueStrategyBacktestMutation>;
  form: ReturnType<typeof useStrategyHypothesisFormState>;
  generate: ReturnType<typeof useGenerateStrategyHypothesesMutation>;
  reportId: number | undefined;
  review: ReturnType<typeof useReviewStrategyResearchMutation>;
  runBacktest: ReturnType<typeof useRunStrategyFormulaBacktestMutation>;
}) {
  useEffect(() => {
    generate.reset();
    runBacktest.reset();
    critique.reset();
    review.reset();
    form.setSelectedDraftId('');
    form.setExportConfirmed(false);
    form.setBacktestConfirmed(false);
    form.setCritiqueConfirmed(false);
    form.setReviewRecorded(false);
  }, [reportId]);
}

export function useStrategyHypothesisController(
  report: StrategyHypothesisBacktestEvidence | null,
) {
  const { locale } = usePreferences();
  const copy = STRATEGY_HYPOTHESIS_COPY[locale];
  const form = useStrategyHypothesisFormState();
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
  const selectionBlocker = selectionBlockerFor(
    copy,
    Boolean(report),
    datasetReady,
    reviewedCostsReady,
    accountReady,
  );
  const selectedDraft = useMemo(
    () =>
      generate.data?.drafts.find(
        (draft) => draft.draft_id === form.selectedDraftId,
      ) ?? null,
    [form.selectedDraftId, generate.data?.drafts],
  );
  const researchCurrent =
    generate.data?.binding_validity !== 'invalidated_by_drift';
  const researchCompleted = generate.data?.status === 'completed';

  useResetStrategyHypothesisOnReportChange({
    critique,
    form,
    generate,
    reportId: report?.id,
    review,
    runBacktest,
  });

  const submitHypothesis = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !report ||
      !snapshot ||
      !accountSummary ||
      !selectionReady ||
      !form.exportConfirmed
    )
      return;
    try {
      const session = await generate.mutateAsync({
        idempotency_key: form.hypothesisKey,
        requested_by: form.operator.trim(),
        account_alias: form.accountAlias.trim(),
        research_question: form.question.trim(),
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
      form.setSelectedDraftId(
        firstValid?.draft_id ?? session.drafts[0]?.draft_id ?? '',
      );
      form.setHypothesisKey(newKey('ai-strategy-hypothesis'));
      form.setExportConfirmed(false);
    } catch {
      // Mutation state renders a fail-closed error with no automatic retry.
    }
  };

  const submitBacktest = async () => {
    if (!generate.data || !selectedDraft || !form.backtestConfirmed) return;
    try {
      await runBacktest.mutateAsync({
        idempotency_key: form.backtestKey,
        requested_by: form.operator.trim(),
        session_id: generate.data.session_id,
        draft_id: selectedDraft.draft_id,
      });
      form.setBacktestKey(newKey('ai-formula-backtest'));
      form.setBacktestConfirmed(false);
    } catch {
      // Stable key remains for audited idempotent replay.
    }
  };

  const submitCritique = async () => {
    if (
      !generate.data ||
      !selectedDraft ||
      !runBacktest.data ||
      !form.critiqueConfirmed
    )
      return;
    try {
      await critique.mutateAsync({
        idempotency_key: form.critiqueKey,
        requested_by: form.operator.trim(),
        session_id: generate.data.session_id,
        draft_id: selectedDraft.draft_id,
        backtest_run_id: runBacktest.data.backtest_run_id,
      });
      form.setCritiqueKey(newKey('ai-strategy-critique'));
      form.setCritiqueConfirmed(false);
    } catch {
      // Stable key remains for audited idempotent replay.
    }
  };

  const submitReview = async () => {
    if (!generate.data || !critique.data || !form.reviewNote.trim()) return;
    try {
      await review.mutateAsync({
        idempotency_key: form.reviewKey,
        session_id: generate.data.session_id,
        critique_id: critique.data.critique_id,
        reviewer: form.operator.trim(),
        disposition: form.reviewDisposition,
        notes: form.reviewNote.trim(),
      });
      form.setReviewKey(newKey('ai-strategy-review'));
      form.setReviewRecorded(true);
    } catch {
      // Mutation state renders the failure.
    }
  };

  const selectDraft = (draftId: string) => {
    form.setSelectedDraftId(draftId);
    runBacktest.reset();
    critique.reset();
    form.setBacktestConfirmed(false);
    form.setCritiqueConfirmed(false);
  };

  return {
    ...form,
    accountReady,
    accountSummary,
    assets,
    canonical: runBacktest.data?.canonical_backtest,
    copy,
    costModelReference,
    critique,
    critiqueArtifact: critique.data?.artifact,
    generate,
    report,
    researchCompleted,
    researchCurrent,
    review,
    runBacktest,
    selectedDraft,
    selectionBlocker,
    selectionReady,
    selectDraft,
    snapshot,
    submitBacktest,
    submitCritique,
    submitHypothesis,
    submitReview,
  };
}

export type StrategyHypothesisController = ReturnType<
  typeof useStrategyHypothesisController
>;
