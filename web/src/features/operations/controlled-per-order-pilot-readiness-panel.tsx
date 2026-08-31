import {
  EvidenceState,
  GateMatrix,
  StatusBadge,
} from '../../shared/ui/workbench';
import type { Locale } from '../../shared/preferences/context';
import { formatPublicStatus } from '../../shared/public-labels';
import type { ControlledPerOrderPilotReadiness } from './api';
import {
  actionLabel,
  blockerLabel,
  gateLabel,
  readinessContractIsSafe,
  resolutionLabel,
} from './controlled-per-order-pilot-readiness-model';

export function ControlledPerOrderPilotReadinessPanel({
  readiness,
  locale,
}: {
  readiness: ControlledPerOrderPilotReadiness | undefined;
  locale: Locale;
}) {
  if (!readiness) {
    return null;
  }
  const safe = readinessContractIsSafe(readiness);
  const ready = safe && readiness.status === 'ready_for_exact_order_review';
  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-testid="controlled-pilot-readiness"
      open={safe ? undefined : true}
    >
      <summary className="app-pilot-readiness-summary flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 py-2.5 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--app-focus-ring)] sm:gap-4">
        <span className="min-w-0 break-words">
          {locale === 'zh'
            ? '受控逐单试点准入证据'
            : 'Controlled per-order pilot admission evidence'}
        </span>
        <span className="flex min-w-0 max-w-28 shrink items-center justify-end gap-2 sm:max-w-none">
          <StatusBadge
            className="min-w-0 max-w-full text-right whitespace-normal"
            tone={!safe ? 'danger' : ready ? 'success' : 'neutral'}
          >
            {!safe
              ? locale === 'zh'
                ? '合同阻断'
                : 'Contract blocked'
              : ready
                ? locale === 'zh'
                  ? '可进入复核'
                  : 'Ready for review'
                : locale === 'zh'
                  ? '条件未满足'
                  : 'Prerequisites unmet'}
          </StatusBadge>
          <span
            aria-hidden="true"
            className="app-disclosure-chevron inline-flex h-5 w-5 shrink-0 items-center justify-center text-[var(--app-text-tertiary)] group-open:rotate-180"
          >
            ▾
          </span>
        </span>
      </summary>
      <div className="min-w-0 space-y-4 pb-4 pt-2">
        {!safe ? (
          <EvidenceState
            kind="error"
            title={
              locale === 'zh'
                ? '试点准入合同已阻断'
                : 'Pilot admission contract blocked'
            }
            description={
              locale === 'zh'
                ? '来源违反只读或非授权合同；不得据此进入逐单复核。'
                : 'The source violates the read-only or non-authorizing contract; do not enter exact-order review.'
            }
          />
        ) : (
          <>
            <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
              {locale === 'zh'
                ? '这是可选真实试点的准入前置证据，不是 v1.8 发布完成证明，也不授予订单、券商或资本权限。'
                : 'These are admission prerequisites for an optional real pilot, not proof of v1.8 completion and not order, broker, or capital authority.'}
            </p>
            <GateMatrix
              caption={
                locale === 'zh'
                  ? '受控逐单试点准入门禁'
                  : 'Controlled per-order pilot admission gates'
              }
              labels={{
                gate: locale === 'zh' ? '门禁' : 'Gate',
                state: locale === 'zh' ? '状态' : 'State',
                reason:
                  locale === 'zh' ? '阻断原因 / 结论' : 'Blocker / conclusion',
                evidence:
                  locale === 'zh' ? '证据 / 解除条件' : 'Evidence / unblock',
              }}
              items={readiness.gates.map((gate) => ({
                id: gate.key,
                gate: gateLabel(gate.key, locale),
                state: gate.status === 'pass' ? 'pass' : 'block',
                stateLabel: formatPublicStatus(gate.status, locale),
                reason:
                  gate.blockers.length > 0
                    ? gate.blockers
                        .map((item) => blockerLabel(item, locale))
                        .join(' · ')
                    : locale === 'zh'
                      ? '已记录证据满足当前门禁'
                      : 'Recorded evidence satisfies this gate',
                evidence:
                  gate.evidence_refs.length > 0 ? (
                    <details
                      className="group/evidence min-w-0"
                      data-testid={`pilot-gate-evidence-${gate.key}`}
                    >
                      <summary className="cursor-pointer list-none font-medium text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                        {locale === 'zh'
                          ? `${gate.evidence_refs.length} 条已记录证据`
                          : `${gate.evidence_refs.length} recorded evidence ${gate.evidence_refs.length === 1 ? 'reference' : 'references'}`}
                        <span
                          aria-hidden="true"
                          className="app-disclosure-chevron ml-1 inline-block text-[var(--app-text-tertiary)] group-open/evidence:rotate-180"
                        >
                          ▾
                        </span>
                      </summary>
                      <div className="mt-1 space-y-1">
                        {gate.evidence_refs.map((reference) => (
                          <code
                            key={reference}
                            className="app-type-micro block break-all text-[var(--app-text-tertiary)]"
                          >
                            {reference}
                          </code>
                        ))}
                      </div>
                    </details>
                  ) : locale === 'zh' ? (
                    '尚无匹配证据标识'
                  ) : (
                    'No matching evidence reference'
                  ),
                unblockCondition:
                  gate.status === 'blocked'
                    ? resolutionLabel(gate.resolution_condition, locale)
                    : undefined,
              }))}
            />
            <dl className="grid gap-3 text-xs sm:grid-cols-2">
              <div>
                <dt className="font-medium text-[var(--app-text-tertiary)]">
                  {locale === 'zh' ? '下一安全步骤' : 'Next safe step'}
                </dt>
                <dd className="mt-1 text-[var(--app-text)]">
                  {actionLabel(readiness.next_safe_action, locale)}
                </dd>
              </div>
              <div>
                <dt className="sr-only">
                  {locale === 'zh' ? '技术证据标识' : 'Technical evidence ID'}
                </dt>
                <dd>
                  <details
                    className="group/identity min-w-0 border-y border-[var(--app-divider)] py-1.5"
                    data-testid="pilot-readiness-identity"
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-2 font-medium text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                      <span>
                        {locale === 'zh'
                          ? '技术证据标识'
                          : 'Technical evidence ID'}
                      </span>
                      <span
                        aria-hidden="true"
                        className="app-disclosure-chevron text-[var(--app-text-tertiary)] group-open/identity:rotate-180"
                      >
                        ▾
                      </span>
                    </summary>
                    <code className="app-type-micro mt-1.5 block break-all font-mono text-[var(--app-text-tertiary)]">
                      {readiness.readiness_fingerprint}
                    </code>
                  </details>
                </dd>
              </div>
            </dl>
            <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
              {locale === 'zh'
                ? '即使所有行通过，每一笔订单仍须重新通过账户事实、决策门禁、风控、模拟与影子检验、资本权限、执行网关、生命周期、对账、入账与短时效人工签名。'
                : 'Even when every row passes, each order must separately re-pass Account Truth, Decision, risk, paper/shadow, capital, gateway, lifecycle, reconciliation, posting, and short-lived human-signature gates.'}
            </p>
          </>
        )}
      </div>
    </details>
  );
}
