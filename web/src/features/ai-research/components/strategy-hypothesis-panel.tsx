import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';

import { usePreferences } from '../../../app/preferences';
import { formatCurrency, formatPercent } from '../../../shared/format';
import type { BacktestReport } from '../../backtest/api';
import {
  useCritiqueStrategyBacktestMutation,
  useGenerateStrategyHypothesesMutation,
  useReviewStrategyResearchMutation,
  useRunStrategyFormulaBacktestMutation,
  type StrategyHypothesisDraft,
} from '../api';

const COST_MODEL =
  'karkinos.backtest.multi_asset_commission.default.v1' as const;

let keySequence = 0;

function newKey(prefix: string) {
  keySequence += 1;
  return `${prefix}:${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${keySequence}`}`;
}

const COPY = {
  en: {
    kicker: 'AI strategy research',
    title: 'Evidence-bound hypothesis lab',
    detail:
      'A configured provider may propose and critique formulas. Karkinos validates the DSL and the canonical engine alone calculates after-cost results.',
    open: 'Open AI strategy research',
    close: 'Close',
    noAuthority: 'No trading authority',
    humanGated: 'Three human gates',
    savedBacktest: 'Saved backtest',
    dataset: 'Dataset snapshot',
    window: 'Frozen window',
    universe: 'Frozen universe',
    cost: 'Canonical cost model',
    accountBinding: 'Account facts',
    notApplicable: 'Not applicable — strategy-only research',
    question: 'Research question',
    operator: 'Human operator',
    account: 'Research account alias',
    exportConfirm:
      'I authorize sending only the displayed sanitized research evidence and frozen identifiers to the configured external model.',
    generate: 'Generate hypothesis drafts',
    generating: 'Calling configured model…',
    missingReport: 'Run and save a backtest first.',
    missingSnapshot:
      'The saved result has no complete dataset snapshot; hypothesis export is blocked.',
    drafts: 'Candidate hypotheses',
    valid: 'Locally validated',
    blocked: 'Blocked by Formula DSL',
    formula: 'Formula AST',
    parameters: 'Parameters',
    risk: 'Risk impact',
    limitations: 'Limitations',
    tests: 'Proposed deterministic tests',
    backtestConfirm:
      'I select this validated draft and authorize one local canonical research backtest.',
    runBacktest: 'Run canonical research backtest',
    runningBacktest: 'Running deterministic backtest…',
    result: 'Canonical after-cost result',
    totalReturn: 'Total return',
    drawdown: 'Max drawdown',
    commission: 'Commission',
    trades: 'Trades',
    critiqueConfirm:
      'I authorize sending this normalized draft and canonical backtest evidence for one external critique.',
    critique: 'Request evidence critique',
    critiquing: 'Calling configured model…',
    critiqueTitle: 'AI evidence critique',
    supported: 'Supported claims',
    contradicted: 'Contradicted claims',
    gaps: 'Evidence gaps',
    robustness: 'Recommended robustness tests',
    uncertainty: 'Uncertainty',
    finalReview: 'Human final review',
    reviewNote: 'Review note',
    accept: 'Keep for more research',
    revise: 'Needs revision',
    reject: 'Reject hypothesis',
    recordReview: 'Record human review',
    recordingReview: 'Recording…',
    reviewRecorded:
      'Human review recorded; no Decision or execution input was created.',
    externalError:
      'The research stage failed closed. No automatic retry was started; use a new human request to retry.',
    validationErrors: 'Validation blockers',
    identity: 'Evidence identity',
    providerEvidence: 'Model provenance',
    invalidated:
      'This historical research binding is no longer current. Evidence or audit drift blocks backtest and critique.',
    incomplete: 'The research stage is not complete',
  },
  zh: {
    kicker: 'AI 策略研究',
    title: '证据绑定的策略假设实验室',
    detail:
      '已配置模型只负责提出和批判公式；Formula DSL 由本地严格验证，成本后结果只由 canonical 回测引擎计算。',
    open: '打开 AI 策略研究',
    close: '收起',
    noAuthority: '无交易权限',
    humanGated: '三次人工门禁',
    savedBacktest: '已保存回测',
    dataset: '数据集快照',
    window: '冻结区间',
    universe: '冻结股票池',
    cost: 'Canonical 成本模型',
    accountBinding: '账户事实',
    notApplicable: '不适用——仅策略研究',
    question: '研究问题',
    operator: '人工操作人',
    account: '研究账户别名',
    exportConfirm:
      '我授权仅将上方展示的脱敏研究证据与冻结标识发送给已配置外部模型。',
    generate: '生成策略假设草案',
    generating: '正在调用已配置模型…',
    missingReport: '请先运行并保存一条回测。',
    missingSnapshot:
      '已保存结果缺少完整 dataset snapshot，禁止外发和生成草案。',
    drafts: '候选策略假设',
    valid: '本地验证通过',
    blocked: 'Formula DSL 已阻断',
    formula: '公式 AST',
    parameters: '参数',
    risk: '风险影响',
    limitations: '限制',
    tests: '建议的确定性测试',
    backtestConfirm:
      '我选择这条已验证草案，并授权运行一次本地 canonical 研究回测。',
    runBacktest: '运行 canonical 研究回测',
    runningBacktest: '正在运行确定性回测…',
    result: 'Canonical 成本后结果',
    totalReturn: '总收益',
    drawdown: '最大回撤',
    commission: '佣金',
    trades: '成交数',
    critiqueConfirm:
      '我授权将该规范化草案与 canonical 回测证据发送给外部模型进行一次批判。',
    critique: '请求证据批判',
    critiquing: '正在调用已配置模型…',
    critiqueTitle: 'AI 证据批判',
    supported: '得到支持的主张',
    contradicted: '被证据反驳的主张',
    gaps: '证据缺口',
    robustness: '建议的稳健性测试',
    uncertainty: '不确定性',
    finalReview: '最终人工复核',
    reviewNote: '复核备注',
    accept: '保留并继续研究',
    revise: '需要修订',
    reject: '驳回假设',
    recordReview: '记录人工复核',
    recordingReview: '正在记录…',
    reviewRecorded: '人工复核已记录；未生成 Decision 或执行输入。',
    externalError:
      '研究阶段已 fail closed，系统不会自动重试；如需重试，请发起新的人工请求。',
    validationErrors: '验证阻断原因',
    identity: '证据标识',
    providerEvidence: '模型来源证据',
    invalidated: '该历史研究绑定已不再有效；证据或审计漂移已阻断回测与批判。',
    incomplete: '研究阶段尚未完整完成',
  },
} as const;

export function StrategyHypothesisPanel({
  report,
}: {
  report: BacktestReport | null;
}) {
  const { locale } = usePreferences();
  const copy = COPY[locale];
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

  const snapshot = report?.metrics_json?.dataset_snapshot;
  const assets = report?.config.assets ?? [];
  const selectionReady = Boolean(
    report &&
    snapshot?.snapshot_id &&
    snapshot.data_quality?.status === 'ok' &&
    assets.length > 0,
  );
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
    if (!report || !snapshot || !selectionReady || !exportConfirmed) return;
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
          cost_model_reference: COST_MODEL,
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
      <section className="app-panel flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
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
      className="app-panel p-5"
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
        <Identity label={copy.cost} value={COST_MODEL} mono />
        <Identity label={copy.accountBinding} value={copy.notApplicable} />
      </div>

      {!selectionReady ? (
        <div
          className="mt-4 rounded-2xl border border-[var(--app-danger)] bg-[var(--app-danger-bg)] p-4 text-sm text-[var(--app-danger)]"
          role="alert"
        >
          {report ? copy.missingSnapshot : copy.missingReport}
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

function DraftCard({
  copy,
  draft,
  selected,
  current,
  onSelect,
}: {
  copy: (typeof COPY)['en'] | (typeof COPY)['zh'];
  draft: StrategyHypothesisDraft;
  selected: boolean;
  current: boolean;
  onSelect: () => void;
}) {
  const valid = draft.validation.status === 'valid';
  return (
    <article
      className={`rounded-2xl border p-4 ${selected ? 'border-[var(--app-accent)]' : 'border-[var(--app-border)]'}`}
    >
      <label className="flex cursor-pointer items-start gap-3">
        <input
          className="mt-1"
          type="radio"
          name="strategy-draft"
          checked={selected}
          onChange={onSelect}
        />
        <span className="min-w-0">
          <span
            className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${valid ? 'bg-[var(--app-success-bg)] text-[var(--app-success)]' : 'bg-[var(--app-danger-bg)] text-[var(--app-danger)]'}`}
          >
            {valid ? copy.valid : copy.blocked}
          </span>
          <span className="mt-2 block text-sm font-semibold leading-6 text-[var(--app-text)]">
            {draft.economic_hypothesis}
          </span>
        </span>
      </label>
      <div className="mt-3 grid gap-3 text-sm">
        <TextBlock
          title={copy.parameters}
          value={JSON.stringify(draft.parameter_values)}
        />
        <TextBlock title={copy.risk} value={draft.risk_impact} />
        <TextList title={copy.limitations} items={draft.limitations} />
        <TextList
          title={copy.tests}
          items={draft.proposed_deterministic_tests}
        />
        {!valid ? (
          <TextList
            title={copy.validationErrors}
            items={draft.validation.errors}
            danger
          />
        ) : null}
        <details>
          <summary className="cursor-pointer font-semibold text-[var(--app-text)]">
            {copy.formula}
          </summary>
          <pre className="mt-2 max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-[var(--app-surface-0)] p-3 text-xs leading-5 text-[var(--app-muted)]">
            {JSON.stringify(draft.formula_ast, null, 2)}
          </pre>
        </details>
        <TextBlock
          title={copy.identity}
          value={`${draft.formula_fingerprint ?? 'blocked'} · dataset ${draft.dataset_snapshot_id} · evidence ${draft.evidence_reference_id} · context ${draft.context_snapshot_id}${current ? '' : ' · historical / not current'}`}
          mono
        />
        <TextBlock
          title={copy.providerEvidence}
          value={provenanceSummary(
            draft.provider_id,
            draft.model_id,
            draft.prompt_version,
            draft.provider_provenance,
          )}
          mono
        />
      </div>
    </article>
  );
}

function Label({ text, children }: { text: string; children: ReactNode }) {
  return (
    <label className="grid gap-2 text-sm font-medium text-[var(--app-text)]">
      {text}
      {children}
    </label>
  );
}

function Confirmation({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 rounded-2xl border border-[var(--app-warning)] bg-[var(--app-warning-bg)] p-4 text-sm leading-6 text-[var(--app-text)]">
      <input
        className="mt-1"
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

function Identity({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-2xl border border-[var(--app-border)] p-3">
      <div className="app-muted text-xs">{label}</div>
      <div
        className={`mt-1 break-all text-sm font-semibold text-[var(--app-text)] ${mono ? 'font-mono text-xs' : ''}`}
      >
        {value}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[var(--app-border)] p-3">
      <div className="app-muted text-xs">{label}</div>
      <div className="mt-1 font-mono text-base font-semibold tabular-nums text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}

function TextBlock({
  title,
  value,
  mono = false,
}: {
  title: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <p
      className={`break-words text-[var(--app-muted)] ${mono ? 'font-mono text-xs' : ''}`}
    >
      <strong className="text-[var(--app-text)]">{title}: </strong>
      {value}
    </p>
  );
}

function TextList({
  title,
  items,
  danger = false,
}: {
  title: string;
  items: string[];
  danger?: boolean;
}) {
  return (
    <div
      className={
        danger ? 'text-[var(--app-danger)]' : 'text-[var(--app-muted)]'
      }
    >
      <div className="font-semibold text-[var(--app-text)]">{title}</div>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm leading-6">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function BoundaryBadge({ text }: { text: string }) {
  return (
    <span className="rounded-full border border-[var(--app-border)] px-3 py-1 text-[var(--app-muted)]">
      {text}
    </span>
  );
}

function FailClosedMessage({ text }: { text: string }) {
  return (
    <div
      className="mt-4 rounded-2xl border border-[var(--app-danger)] bg-[var(--app-danger-bg)] p-4 text-sm text-[var(--app-danger)]"
      role="alert"
    >
      {text}
    </div>
  );
}

function provenanceSummary(
  providerId: string | null | undefined,
  modelId: string | null | undefined,
  promptVersion: string | null | undefined,
  provenance: Record<string, unknown> | undefined,
) {
  const usage =
    provenance?.usage && typeof provenance.usage === 'object'
      ? (provenance.usage as Record<string, unknown>)
      : undefined;
  const totalTokens =
    typeof usage?.total_tokens === 'number' ? usage.total_tokens : null;
  const latency =
    typeof provenance?.latency_ms === 'number' ? provenance.latency_ms : null;
  return [
    providerId ?? 'provider unavailable',
    modelId ?? 'model unavailable',
    promptVersion ?? 'prompt unavailable',
    totalTokens === null ? 'token usage unavailable' : `${totalTokens} tokens`,
    latency === null ? 'latency unavailable' : `${latency} ms`,
  ].join(' · ');
}
