import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicCode } from '../../../shared/public-labels';
import { type DailyCandidateFinancialPreflight } from '../../operations/api';
import {
  actionLabels,
  completionLabels,
  evidenceLabels,
  gateLabels,
  gateReviewPaths,
} from './daily-candidate-preflight-model';

export function DailyCandidateFinancialPreflightPanel({
  preflight,
}: {
  preflight: DailyCandidateFinancialPreflight;
}) {
  const { locale } = usePreferences();
  const ready = preflight.eligible_to_start_manual_attempt;
  const reasons = preflight.no_action_reasons.slice(0, 8);
  const operatorChecklist = (preflight.operator_checklist ?? []).slice(0, 8);

  return (
    <div
      data-testid="daily-candidate-financial-preflight"
      className="mt-4 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-accent)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_7%,transparent)] px-3 py-3"
    >
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
            {locale === 'zh'
              ? '每日候选财务预检'
              : 'Daily candidate financial preflight'}
          </div>
          <div className="app-muted mt-1 break-words text-xs leading-5">
            {locale === 'zh'
              ? '只读汇总当日 Account Truth、行情、策略、费用与前序执行闭环。通过也只允许进入风控与 paper/shadow，不会生成或提交真实订单。'
              : 'Read-only Account Truth, market, strategy, fee, and prior-closure check. Passing permits only risk plus paper/shadow; it creates and submits no real order.'}
          </div>
        </div>
        <span className="app-chip">
          {ready
            ? locale === 'zh'
              ? '可进入模拟尝试'
              : 'Simulation attempt ready'
            : locale === 'zh'
              ? 'NO-ACTION'
              : 'NO-ACTION'}
        </span>
      </div>

      <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {preflight.gates.map((gate) => {
          const label = gateLabels[gate.gate];
          return (
            <div
              className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2"
              key={gate.gate}
            >
              <div className="app-muted text-xs">
                {label?.[locale] ?? formatPublicCode(gate.gate, locale)}
              </div>
              <div
                className={`mt-1 text-sm font-semibold ${
                  gate.status === 'pass'
                    ? 'text-[var(--app-success)]'
                    : 'text-[var(--app-warning)]'
                }`}
              >
                {gate.status === 'pass'
                  ? locale === 'zh'
                    ? '通过'
                    : 'Pass'
                  : locale === 'zh'
                    ? '阻断'
                    : 'Blocked'}
              </div>
            </div>
          );
        })}
      </div>

      {reasons.length ? (
        <div className="mt-3 break-words text-xs font-semibold leading-5 text-[var(--app-warning)]">
          {locale === 'zh' ? 'NO-ACTION 原因：' : 'NO-ACTION reasons: '}
          {reasons.map((item) => formatPublicCode(item, locale)).join(' · ')}
          {preflight.no_action_reasons.length > reasons.length
            ? locale === 'zh'
              ? ` · 其余 ${preflight.no_action_reasons.length - reasons.length} 项`
              : ` · ${preflight.no_action_reasons.length - reasons.length} more`
            : ''}
        </div>
      ) : null}

      {operatorChecklist.length ? (
        <div
          data-testid="daily-candidate-operator-checklist"
          className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2"
        >
          <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
            {locale === 'zh' ? '准备顺序' : 'Preparation order'}
          </div>
          <ol className="mt-2 space-y-2">
            {operatorChecklist.map((item) => {
              const action = actionLabels[item.action];
              const gate = gateLabels[item.gate];
              return (
                <li
                  className="flex min-w-0 gap-2 text-xs leading-5"
                  key={item.step}
                >
                  <span className="font-semibold text-[var(--app-accent)]">
                    {item.step}.
                  </span>
                  <div className="min-w-0">
                    <div className="break-words font-semibold text-[var(--app-text)]">
                      {action?.[locale] ??
                        formatPublicCode(item.action, locale)}
                    </div>
                    <div className="app-muted break-words">
                      {gate?.[locale] ?? formatPublicCode(item.gate, locale)}
                      {item.blockers.length
                        ? locale === 'zh'
                          ? ` · ${item.blockers.length} 项阻断`
                          : ` · ${item.blockers.length} blocker(s)`
                        : locale === 'zh'
                          ? ' · 门禁已通过'
                          : ' · gates passed'}
                      {' · '}
                      {item.completion_mode === 'human_review'
                        ? locale === 'zh'
                          ? '需人工复核'
                          : 'human review required'
                        : locale === 'zh'
                          ? '仅按 canonical 流程完成'
                          : 'canonical workflow only'}
                    </div>
                    <div className="mt-2 grid gap-2 lg:grid-cols-2">
                      <div>
                        <div className="font-semibold text-[var(--app-text)]">
                          {locale === 'zh' ? '需要的证据' : 'Required evidence'}
                        </div>
                        <ul className="app-muted mt-1 list-disc space-y-1 pl-4">
                          {item.required_evidence.map((requirement) => (
                            <li key={requirement}>
                              {evidenceLabels[requirement]?.[locale] ??
                                formatPublicCode(requirement, locale)}
                            </li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <div className="font-semibold text-[var(--app-text)]">
                          {locale === 'zh' ? '完成标准' : 'Done when'}
                        </div>
                        <ul className="app-muted mt-1 list-disc space-y-1 pl-4">
                          {item.completion_criteria.map((criterion) => (
                            <li key={criterion}>
                              {completionLabels[criterion]?.[locale] ??
                                formatPublicCode(criterion, locale)}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                    <div className="app-muted mt-2 break-words">
                      {locale === 'zh'
                        ? '边界：只接受 canonical 持久化证据；所有者口述不是财务事实；不要求写入原始 XLS 行或私有账户标识。'
                        : 'Boundary: canonical persisted evidence only; owner statements are not financial facts; raw XLS rows and private account identifiers are not required.'}
                    </div>
                    <a
                      className="app-link mt-1 inline-flex"
                      href={gateReviewPaths[item.gate] ?? '/operations'}
                    >
                      {locale === 'zh'
                        ? '前往对应复核页'
                        : 'Open review surface'}
                    </a>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}

      <div className="app-muted mt-3 break-words text-xs leading-5">
        {locale === 'zh'
          ? `候选 ${preflight.eligible_candidate_count} · 当日 ${preflight.run_date ?? '未绑定'} · 人工票据未创建 · 不授予执行或资本权限`
          : `${preflight.eligible_candidate_count} eligible candidate(s) · ${preflight.run_date ?? 'date unbound'} · no manual ticket created · no execution or capital authority`}
      </div>
    </div>
  );
}
