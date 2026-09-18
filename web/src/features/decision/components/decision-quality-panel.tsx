import { useMemo, useState } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  ControlledActionZone,
  EvidenceState,
  Register,
  RegisterRow,
  StatusBadge,
} from '../../../shared/ui/workbench';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  useCaptureDecisionQualityMutation,
  useDecisionQualityQuery,
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
            '衡量每日决策是否同时具备完整数据、账户事实、风控、基准、日志与可追溯复盘记录。',
          current: '当前决策',
          history: '已捕获日期',
          score: '历史合格率',
          empty: '尚无显式捕获日期',
          operator: '证据捕获人',
          capture: '固化今日质量证据',
          capturing: '正在固化…',
          captured: '当前证据已固化',
          stale: '已保存证据与当前事实不一致，请重新复核后采集。',
          blocked: '当前未满足全部质量维度，仍可如实捕获为 blocked。',
          retry: '重新读取证据',
          safety:
            '只追加决策质量审计；不会联系外部服务、调用 AI、修改账本或产生交易/资本权限。',
          error: '决策质量证据读取或捕获失败。',
        }
      : {
          kicker: 'North Star metric',
          title: 'Decision quality evidence',
          detail:
            'Measures whether each daily decision has complete data and Account Truth, risk, benchmark, journal, and a traceable review record.',
          current: 'Current decision',
          history: 'Captured days',
          score: 'Historical qualification rate',
          empty: 'No explicitly captured days yet',
          operator: 'Evidence captured by',
          capture: 'Capture today’s quality evidence',
          capturing: 'Capturing…',
          captured: 'Current evidence captured',
          stale:
            'Saved evidence no longer matches the current facts; review and capture again.',
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
    <section data-testid="decision-quality-panel" className="min-w-0">
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">{labels.kicker}</div>
          <h2 className="app-type-section-title mt-1.5 text-[var(--app-text)]">
            {labels.title}
          </h2>
          <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
            {labels.detail}
          </p>
        </div>
        {target ? (
          <StatusBadge tone={target.qualified ? 'success' : 'warning'}>
            {target.diagnostic_score_percent.toFixed(0)}% ·{' '}
            {target.qualified
              ? locale === 'zh'
                ? '合格'
                : 'Qualified'
              : locale === 'zh'
                ? '未合格'
                : 'Blocked'}
          </StatusBadge>
        ) : null}
      </div>

      {quality.isLoading ? (
        <EvidenceState
          className="mt-4"
          kind="loading"
          statusLabel={labels.kicker}
          title={
            locale === 'zh'
              ? '正在读取持久化证据…'
              : 'Reading persisted evidence…'
          }
          description={labels.detail}
        />
      ) : quality.isError || !view || !target || !report ? (
        <EvidenceState
          className="mt-4"
          kind="error"
          statusLabel={labels.kicker}
          title={labels.error}
          description={labels.detail}
          action={
            <button
              type="button"
              className="app-button-secondary min-h-9 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
              onClick={() => void quality.refetch()}
            >
              {labels.retry}
            </button>
          }
        />
      ) : (
        <>
          <Register ariaLabel={labels.title} className="mt-4">
            {target.dimensions.map((dimension) => (
              <RegisterRow
                key={dimension.name}
                label={DIMENSION_LABELS[locale][dimension.name]}
                value={
                  <StatusBadge tone={dimension.passed ? 'success' : 'warning'}>
                    {formatPublicStatus(dimension.status, locale)}
                  </StatusBadge>
                }
                detail={
                  dimension.blockers.length > 0
                    ? dimension.blockers
                        .map((item) => formatPublicCode(item, locale))
                        .join(' · ')
                    : undefined
                }
              />
            ))}
            <RegisterRow
              label={labels.current}
              value={`${target.decision_date} · ${target.passed_dimension_count}/${target.dimension_count}`}
              mono
            />
            <RegisterRow
              label={labels.history}
              value={report.evaluated_day_count}
              mono
            />
            <RegisterRow
              label={labels.score}
              value={
                report.score_percent == null
                  ? labels.empty
                  : `${report.score_percent.toFixed(1)}%`
              }
              mono
            />
          </Register>

          {!target.qualified ? (
            <p className="mt-3 border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5 text-[var(--app-warning-text)]">
              {labels.blocked}
            </p>
          ) : null}
          {view.current_day_captured && view.current_binding_valid === false ? (
            <p className="mt-3 border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5 text-[var(--app-warning-text)]">
              {labels.stale}
            </p>
          ) : null}

          <ControlledActionZone
            className="mt-4"
            tone="info"
            title={labels.capture}
            description={labels.safety}
            evidence={`${target.decision_date} · ${target.passed_dimension_count}/${target.dimension_count}`}
            layout="stack"
          >
            <div className="grid w-full min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
              <label className="grid min-w-0 gap-1 text-xs text-[var(--app-muted)]">
                {labels.operator}
                <input
                  className="app-field min-h-10 rounded-[var(--app-radius-control)] px-3 py-2 text-sm text-[var(--app-text)]"
                  value={capturedBy}
                  onChange={(event) => setCapturedBy(event.target.value)}
                />
              </label>
              <button
                type="button"
                className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
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
          </ControlledActionZone>
          {capture.isError ? (
            <p role="alert" className="app-error-text mt-3 text-xs">
              {labels.error} {labels.retry}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
