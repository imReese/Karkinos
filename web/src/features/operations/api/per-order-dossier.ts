import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../../shared/api/client';
import type { OperatorApprovalChallenge } from './operator-approval';

export type CurrentPerOrderDossierCandidate = {
  order_id: string;
  symbol: string;
  side: string;
  asset_class: string;
  quantity: string;
  order_type: string;
  limit_price: string | null;
  oms_status: 'manually_confirmed' | string;
  updated_at: string;
  order_fingerprint: string;
  dossier_fingerprint: string;
  review_status: string;
  review_ready: boolean;
  review_blockers: string[];
  evidence_resolution_status: string;
  confirmation_status: string;
  authorizes_execution: false;
};

export type CurrentPerOrderDossierCandidates = {
  schema_version: string;
  candidate_count: number;
  candidates: CurrentPerOrderDossierCandidate[];
  truncated: boolean;
  selection_contract: 'canonical_manually_confirmed_oms_orders_only';
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  runtime_connector_query_performed: false;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  does_not_mutate_risk: true;
  does_not_mutate_kill_switch: true;
  does_not_change_capital_authority: true;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  authorizes_execution: false;
};

export type CurrentPerOrderDossierPreview = {
  schema_version: string;
  underlying_dossier_schema_version: string;
  order: {
    order_id: string;
    intent_key: string;
    symbol: string;
    side: string;
    asset_class: string;
    quantity: string;
    order_type: string;
    limit_price: string | null;
    source: string;
    source_ref: string;
  };
  order_fingerprint: string;
  dossier_fingerprint: string;
  generated_at: string;
  evidence_resolution: {
    status: string;
    selected_capital_evaluation_event_id: number | null;
    selected_capital_evaluation_recorded_at: string;
    capital_evaluation_input_fingerprint: string;
    prior_batch_reconciliation_fingerprint: string;
    execution_gateway_verification_fingerprint: string;
    blockers: string[];
    scan_limit: number;
    scan_truncated: boolean;
  };
  capital_evaluation: {
    status: string;
    authorization_id: string;
    policy_version: string;
    effective_at: string;
    expires_at: string;
    scope: {
      account_alias: string;
      strategy_id: string;
      symbol: string;
      evidence_connector_id: string;
      execution_gateway_id: string;
    };
    effective_limits: Record<string, string | number>;
    remaining_budget: Record<string, string | number>;
  };
  broker_adapter_release: {
    schema_version: string;
    status: string;
    expected_scope: {
      collector_id: string;
      gateway_id: string;
      account_alias: string;
    };
    matching_release_count: number;
    release: {
      release_evidence_ref: string;
      manifest_fingerprint: string;
      provider: string;
      gateway_id: string;
      account_alias: string;
      collector_id: string;
      review_status: string;
      conformance_status: string;
      collector_status: string;
      collector_run_id: string;
      status: string;
      does_not_authorize_provider_activation: boolean;
    } | null;
    blockers: string[];
    persisted_evidence_only: boolean;
    provider_contact_performed: boolean;
    broker_submission_enabled: false;
    authorizes_execution: false;
  };
  prior_execution_reconciliation: {
    status: string;
    run_id?: string;
    run_date?: string;
    reconciliation_status?: string;
  };
  execution_gateway_verification: {
    status: string;
    verification_fingerprint: string;
    recorded_at: string;
  };
  kill_switch: {
    status: string;
    enabled: boolean | null;
    reason: string;
  };
  confirmation: {
    status: string;
    confirmation_id: string;
    recorded_at: string;
    operator_label: string;
  };
  review_status: string;
  review_ready: boolean;
  current_evidence_resolved: boolean;
  review_blockers: string[];
  hard_submission_blockers: string[];
  submission_status: 'blocked';
  required_operator_approval: {
    action: 'attest_per_order_dossier';
    artifact_type: 'per_order_dossier';
    artifact_fingerprint: string;
  } | null;
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  runtime_connector_query_performed: false;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  does_not_mutate_risk: true;
  does_not_mutate_kill_switch: true;
  does_not_change_capital_authority: true;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  authorizes_execution: false;
};

export type CurrentPerOrderConfirmation = {
  status: 'recorded_verified_identity' | string;
  confirmation_id: string;
  order_id: string;
  dossier_fingerprint: string;
  operator_label: string;
  operator_identity_verified: boolean;
  authorizes_execution: false;
  broker_submission_enabled: false;
  reused: boolean;
};

export function useCurrentPerOrderDossierCandidatesQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['automation', 'controlled-bridge', 'current-dossiers'],
    queryFn: () =>
      apiClient<CurrentPerOrderDossierCandidates>(
        '/api/automation/controlled-bridge/dossiers/current?limit=20',
      ),
    enabled,
    staleTime: 2_000,
    refetchOnWindowFocus: true,
  });
}

export function useCurrentPerOrderDossierPreviewMutation() {
  return useMutation({
    mutationFn: ({ orderId }: { orderId: string }) =>
      postJson<CurrentPerOrderDossierPreview>(
        `/api/automation/controlled-bridge/orders/${encodeURIComponent(
          orderId,
        )}/dossier/current/preview`,
      ),
  });
}

export function useCurrentPerOrderDossierApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'attest_per_order_dossier';
      artifact_type: 'per_order_dossier';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useCurrentPerOrderConfirmationMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      orderId: string;
      dossier_fingerprint: string;
      operator_label: string;
      operator_approval_id: string;
      acknowledgement: 'confirm_exact_non_submitting_dossier_for_review';
    }) => {
      const { orderId, ...body } = request;
      return postJson<CurrentPerOrderConfirmation>(
        `/api/automation/controlled-bridge/orders/${encodeURIComponent(
          orderId,
        )}/dossier/current/confirmations`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['automation', 'controlled-bridge', 'current-dossiers'],
        }),
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}
