import { useMemo, useState } from 'react';

import { usePreferences } from '../../../app/preferences';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  useCaptureDecisionQualityMutation,
  useDecisionQualityQuery,
  type DecisionQualityDimension,
} from '../api';

const DIMENSION_LABELS = {
  en: {
    data_complete: 'Data and Account Truth complete',
    risk_checked: 'Deterministic risk checked',
    benchmark_aware: 'Benchmark-aware evidence',
    journaled: 'Decision journaled',
    later_reviewable: 'Later reviewable',
  },
  zh: {
    data_complete: '数据与账户事实完整',
    risk_checked: '确定性风控已检查',
    benchmark_aware: '具备基准对照证据',
    journaled: '决策已入日志',
    later_reviewable: '后续可复盘',
  },
} as const;

function requestKey(decisionDate: string, fingerprint: string) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}`;
  return `decision-quality:${decisionDate}:${fingerprint.slice(0, 16)}:${suffix}`;
}

function dimensionTone(dimension: DecisionQualityDimension) {
  return dimension.passed
    ? 'border-[color-mix(in_srgb,var(--app-success)_30%,var(--app-border))] text-[var(--app-success)]'
    : 'border-[color-mix(in_srgb,var(--app-warning)_38%,var(--app-border))] text-[var(--app-warning)]';
}

export function DecisionQualityPanel() {
  const { locale } = usePreferences();
  const quality = useDecisionQualityQuery();
  const capture = useCaptureDecisionQualityMutation();
  const [capturedBy, setCapturedBy] = useState('local-operator');
  const view = quality.data;
  const target = view?.current_target;
  const report = view?.report;
  const key = useMemo(
    () =>
      target ? requestKey(target.decision_date, target.target_fingerprint) : '',
    [target?.decision_date, target?.target_fingerprint],
  );
  const labels =
    locale === 'zh'
      ? {
          kicker: '北极星指标',
          title: '决策质量证据',
          detail:
            '衡量每日决策是否同时具备完整数据、Account Truth、风控、基准、日志与复盘身份。',
          current: '当前决策',
          history: '已捕获日期',
          score: '历史合格率',
          empty: '尚无显式捕获日期',
          operator: '证据捕获人',
          capture: '固化今日质量证据',
          capturing: '正在固化…',
          captured: '当前证据已固化',
          stale: '已保存证据与当前投影不一致，请重新复核后捕获。',
          blocked: '当前未满足全部质量维度，仍可如实捕获为 blocked。',
          retry: '重新读取证据',
          safety:
            '只追加决策质量审计；不会联系 provider、调用 AI、修改账本或产生交易/资本权限。',
          error: '决策质量证据读取或捕获失败。',
        }
      : {
          kicker: 'North Star metric',
          title: 'Decision quality evidence',
          detail:
            'Measures whether each daily decision has complete data and Account Truth, risk, benchmark, journal, and review identities.',
          current: 'Current decision',
          history: 'Captured days',
          score: 'Historical qualification rate',
          empty: 'No explicitly captured days yet',
          operator: 'Evidence captured by',
          capture: 'Capture today’s quality evidence',
          capturing: 'Capturing…',
          captured: 'Current evidence captured',
          stale:
            'Stored evidence no longer matches the current projection; review and capture again.',
          blocked:
            'Not every quality dimension passes; it can still be captured honestly as blocked.',
          retry: 'Read evidence again',
          safety:
            'Appends decision-quality audit evidence only; it cannot contact a provider, invoke AI, mutate the ledger, or grant trading or capital authority.',
          error: 'Decision quality evidence could not be read or captured.',
        };

  const submit = async () => {
    if (!target || !capturedBy.trim() || !key) {
      return;
    }
    try {
      await capture.mutateAsync({
        idempotency_key: key,
        captured_by: capturedBy.trim(),
        expected_target_fingerprint: target.target_fingerprint,
      });
    } catch {
      // Mutation state renders the fail-closed error without an implicit retry.
    }
  };

  return (
    <section
      data-testid="decision-quality-panel"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.kicker}</div>
            <h2 className="app-card-title mt-1.5">{labels.title}</h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {labels.detail}
            </p>
          </div>
          {target ? (
            <div
              className={`inline-flex min-h-9 shrink-0 items-center justify-center rounded-full border px-3 py-1 text-sm font-semibold tabular-nums ${
                target.qualified
                  ? 'border-[color-mix(in_srgb,var(--app-success)_38%,transparent)] text-[var(--app-success)]'
                  : 'border-[color-mix(in_srgb,var(--app-warning)_45%,transparent)] text-[var(--app-warning)]'
              }`}
            >
              {target.diagnostic_score_percent.toFixed(0)}% ·{' '}
              {target.qualified
                ? locale === 'zh'
                  ? '合格'
                  : 'Qualified'
                : locale === 'zh'
                  ? '未合格'
                  : 'Blocked'}
            </div>
          ) : null}
        </div>

        {quality.isLoading ? (
          <p className="app-muted mt-4 text-sm">
            {locale === 'zh'
              ? '正在读取持久化证据…'
              : 'Reading persisted evidence…'}
          </p>
        ) : quality.isError || !view || !target || !report ? (
          <div className="mt-4 grid justify-items-start gap-2">
            <p role="alert" className="app-error-text text-sm">
              {labels.error}
            </p>
            <button
              type="button"
              className="app-button-secondary min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
              onClick={() => void quality.refetch()}
            >
              {labels.retry}
            </button>
          </div>
        ) : (
          <>
            <div className="mt-4 grid min-w-0 gap-2 sm:grid-cols-2 xl:grid-cols-5">
              {target.dimensions.map((dimension) => (
                <article
                  key={dimension.name}
                  className={`min-w-0 rounded-2xl border bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3 ${dimensionTone(
                    dimension,
                  )}`}
                >
                  <div className="text-xs font-semibold leading-5">
                    {DIMENSION_LABELS[locale][dimension.name]}
                  </div>
                  <div className="app-muted mt-1 text-[11px] leading-5">
                    {formatPublicStatus(dimension.status, locale)}
                  </div>
                  {dimension.blockers.length > 0 ? (
                    <div className="mt-2 text-[11px] leading-5">
                      {dimension.blockers
                        .map((item) => formatPublicCode(item, locale))
                        .join(' · ')}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>

            <div className="mt-4 grid min-w-0 gap-2 sm:grid-cols-3">
              <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2.5">
                <div className="app-muted text-[11px]">{labels.current}</div>
                <div className="mt-1 font-mono text-sm tabular-nums text-[var(--app-text)]">
                  {target.decision_date} · {target.passed_dimension_count}/
                  {target.dimension_count}
                </div>
              </div>
              <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2.5">
                <div className="app-muted text-[11px]">{labels.history}</div>
                <div className="mt-1 font-mono text-sm tabular-nums text-[var(--app-text)]">
                  {report.evaluated_day_count}
                </div>
              </div>
              <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2.5">
                <div className="app-muted text-[11px]">{labels.score}</div>
                <div className="mt-1 font-mono text-sm tabular-nums text-[var(--app-text)]">
                  {report.score_percent == null
                    ? labels.empty
                    : `${report.score_percent.toFixed(1)}%`}
                </div>
              </div>
            </div>

            {!target.qualified ? (
              <p className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-warning)_35%,transparent)] px-3 py-2 text-xs leading-5 text-[var(--app-warning)]">
                {labels.blocked}
              </p>
            ) : null}
            {view.current_day_captured &&
            view.current_binding_valid === false ? (
              <p className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-warning)_35%,transparent)] px-3 py-2 text-xs leading-5 text-[var(--app-warning)]">
                {labels.stale}
              </p>
            ) : null}

            <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
              <label className="grid gap-1 text-xs text-[var(--app-muted)]">
                {labels.operator}
                <input
                  className="app-field min-h-10 rounded-xl px-3 py-2 text-sm text-[var(--app-text)]"
                  value={capturedBy}
                  onChange={(event) => setCapturedBy(event.target.value)}
                />
              </label>
              <button
                type="button"
                className="app-button-primary min-h-10 rounded-xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                disabled={
                  capture.isPending ||
                  !capturedBy.trim() ||
                  (view.current_day_captured &&
                    view.current_binding_valid === true)
                }
                onClick={() => void submit()}
              >
                {capture.isPending
                  ? labels.capturing
                  : view.current_day_captured &&
                      view.current_binding_valid === true
                    ? labels.captured
                    : labels.capture}
              </button>
            </div>
            {capture.isError ? (
              <p role="alert" className="app-error-text mt-3 text-xs">
                {labels.error} {labels.retry}
              </p>
            ) : null}
            <p className="app-muted mt-3 text-[11px] leading-5">
              {labels.safety}
            </p>
          </>
        )}
      </div>
    </section>
  );
}
