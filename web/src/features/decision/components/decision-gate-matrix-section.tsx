import {
  GateMatrix,
  StatusBadge,
  type GateMatrixItem,
} from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';

export function DecisionGateMatrixSection({
  gateItems,
  allDecisionGatesPass,
  decisionGateAttentionCount,
  healthyGateMatrixExpanded,
  onToggle,
}: {
  gateItems: GateMatrixItem[];
  allDecisionGatesPass: boolean;
  decisionGateAttentionCount: number;
  healthyGateMatrixExpanded: boolean;
  onToggle: () => void;
}) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const setHealthyGateMatrixExpanded = onToggle;
  return (
    <section className="min-w-0 space-y-2" data-testid="decision-gate-matrix">
      <div className="min-w-0" data-testid="decision-gate-disclosure">
        <button
          aria-controls="decision-gate-matrix-content"
          aria-expanded={!allDecisionGatesPass || healthyGateMatrixExpanded}
          className="flex min-h-11 w-full cursor-pointer items-center justify-between gap-3 border-y border-[var(--app-divider)] py-2.5 text-left text-sm font-semibold text-[var(--app-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
          onClick={setHealthyGateMatrixExpanded}
          type="button"
        >
          <span className="min-w-0">
            <span className="block">{labels.workflowTitle}</span>
            <span className="mt-0.5 hidden text-xs font-normal text-[var(--app-text-secondary)] sm:block">
              {labels.workflowDetail}
            </span>
          </span>
          <StatusBadge tone={allDecisionGatesPass ? 'success' : 'warning'}>
            {allDecisionGatesPass
              ? locale === 'zh'
                ? `${gateItems.length}/${gateItems.length} 已通过`
                : `${gateItems.length}/${gateItems.length} passed`
              : locale === 'zh'
                ? `${decisionGateAttentionCount} 项待复核`
                : `${decisionGateAttentionCount} need review`}
          </StatusBadge>
        </button>
        {allDecisionGatesPass ? (
          <ol
            aria-label={labels.workflowTitle}
            className="app-decision-gate-track"
            data-testid="decision-gate-track"
          >
            {gateItems.map((item, index) => (
              <li
                key={item.id}
                className="app-decision-gate-step"
                data-gate-state={item.state}
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="app-decision-gate-index" aria-hidden="true">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span
                    className="app-decision-gate-connector"
                    aria-hidden="true"
                  />
                </div>
                <span className="app-decision-gate-label">{item.gate}</span>
              </li>
            ))}
          </ol>
        ) : null}
        <div
          className={`${
            !allDecisionGatesPass || healthyGateMatrixExpanded
              ? 'block'
              : 'hidden'
          } pt-2`}
          id="decision-gate-matrix-content"
        >
          <GateMatrix
            caption={labels.workflowTitle}
            items={gateItems}
            labels={{
              gate: locale === 'zh' ? '闸门' : 'Gate',
              state: locale === 'zh' ? '状态' : 'State',
              reason:
                locale === 'zh' ? '阻断原因 / 结论' : 'Blocker / conclusion',
              evidence:
                locale === 'zh' ? '证据 / 解除条件' : 'Evidence / unblock',
            }}
          />
        </div>
      </div>
    </section>
  );
}
