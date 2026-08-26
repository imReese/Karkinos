import type { ResearchEvidenceType } from '../research-task-api';

export const BASE_EVIDENCE: ResearchEvidenceType[] = [
  'portfolio',
  'account_state',
  'operations',
  'account_truth',
];

let auditKeySequence = 0;

export function newAuditKey(prefix: string) {
  auditKeySequence += 1;
  const random = globalThis.crypto?.randomUUID?.();
  return `${prefix}:${random ?? `${Date.now()}-${auditKeySequence}`}`;
}
