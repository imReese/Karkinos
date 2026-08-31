import type {
  ControlledLedgerCorrectionReason,
  ControlledOrderJourney,
} from './api';
import type { OperationsLocale } from './controlled-operation-panel-primitives';

export type { ControlledLedgerCorrectionReason } from './api';

export type ControlledLedgerCorrectionOperatorPanelProps = {
  journey: ControlledOrderJourney;
  locale: OperationsLocale;
};

export const correctionReasons: Array<{
  value: ControlledLedgerCorrectionReason;
  en: string;
  zh: string;
}> = [
  {
    value: 'broker_evidence_superseded',
    en: 'Broker evidence was superseded',
    zh: '券商证据已被更新证据取代',
  },
  {
    value: 'duplicate_controlled_posting',
    en: 'Controlled posting was duplicated',
    zh: '受控入账发生重复',
  },
  {
    value: 'operator_confirmed_mapping_error',
    en: 'Operator confirmed a mapping error',
    zh: '操作员确认映射错误',
  },
];

export function reasonLabel(
  reason: ControlledLedgerCorrectionReason,
  locale: OperationsLocale,
) {
  const item = correctionReasons.find(
    (candidate) => candidate.value === reason,
  );
  return item?.[locale] ?? reason;
}

export function controlledLedgerCorrectionContext(
  journey: ControlledOrderJourney,
) {
  const postingStage = journey.stages.find(
    (stage) => stage.key === 'reconciled_ledger_posting',
  );
  const correctionStage = journey.stages.find(
    (stage) => stage.key === 'append_only_ledger_correction',
  );
  const postingId = postingStage?.evidence_id ?? '';
  const actionable = Boolean(
    postingId &&
    postingStage?.complete &&
    (postingStage.ledger_entry_count ?? 0) > 0 &&
    !correctionStage?.complete,
  );
  return { actionable, postingId };
}
