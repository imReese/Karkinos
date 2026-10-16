import { ChevronDown } from 'lucide-react';
import {
  GateMatrix,
  StatusBadge,
  type GateMatrixItem,
  type StatusTone,
} from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';

const gateTones: Record<GateMatrixItem['state'], StatusTone> = {
  pass: 'success',
  warning: 'warning',
  block: 'danger',
  unknown: 'neutral',
};

export function DecisionGateMatrixSection({
  gateItems,
  allDecisionGatesPass,
  decisionGateAttentionCount,
  expanded,
  onToggle,
}: {
  gateItems: GateMatrixItem[];
  allDecisionGatesPass: boolean;
  decisionGateAttentionCount: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  return (
    <section className="min-w-0" data-testid="decision-gate-matrix">
      <div className="min-w-0" data-testid="decision-gate-disclosure">
        <button
          aria-controls="decision-gate-matrix-content"
          aria-expanded={expanded}
          className="flex min-h-11 w-full cursor-pointer items-center justify-between gap-3 border-b border-[var(--app-divider)] py-2.5 text-left text-sm font-semibold text-[var(--app-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
          onClick={onToggle}
          type="button"
        >
          <span className="min-w-0">{labels.workflowTitle}</span>
          <span className="flex shrink-0 items-center gap-2">
            <StatusBadge tone={allDecisionGatesPass ? 'success' : 'warning'}>
              {allDecisionGatesPass
                ? locale === 'zh'
                  ? `${gateItems.length}/${gateItems.length} 已通过`
                  : `${gateItems.length}/${gateItems.length} passed`
                : locale === 'zh'
                  ? `${decisionGateAttentionCount} 项待复核`
                  : `${decisionGateAttentionCount} need review`}
            </StatusBadge>
            <ChevronDown
              className={`size-4 text-[var(--app-text-tertiary)] transition-transform ${expanded ? 'rotate-180' : ''}`}
              aria-hidden="true"
            />
          </span>
        </button>
        <ol
          aria-label={labels.workflowTitle}
          className="app-decision-gate-track"
          data-testid="decision-gate-track"
        >
          {gateItems.map((item) => (
            <li
              key={item.id}
              className="app-decision-gate-step flex min-w-0 flex-wrap items-center justify-between gap-2 py-2"
              data-gate-state={item.state}
            >
              <span className="app-decision-gate-label font-medium">
                {item.gate}
              </span>
              <StatusBadge tone={gateTones[item.state]}>
                {item.stateLabel ?? item.state}
              </StatusBadge>
            </li>
          ))}
        </ol>
        <div
          className={`${expanded ? 'block' : 'hidden'} pt-2`}
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
