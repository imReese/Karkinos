/**
 * Risk composes persisted projections owned by Account and Decision plus the
 * operator-owned kill switch. Keep those dependencies at this explicit adapter
 * so Risk models and views do not import another feature's private modules.
 */

export {
  useAccountStateQuery,
  useExplainabilityQuery,
  useRiskWorkspaceQuery,
} from '../account/api';
export type {
  AccountStateResponse,
  ExplainabilityResponse,
  RiskWorkspaceResponse,
} from '../account/api';
export { ReturnCalendarCard } from '../account/components/return-calendar-card';

export {
  useBatchPreTradeRiskMutation,
  useTodayDecisionQuery,
} from '../decision/api';
export type {
  BatchPreTradeRiskResult,
  DecisionResponse,
  DecisionWorkflowTask,
} from '../decision/api';

export { KillSwitchPanel } from '../trading/components/kill-switch-panel';
