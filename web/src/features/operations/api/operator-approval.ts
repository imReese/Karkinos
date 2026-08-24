import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient, postJson } from '../../../shared/api/client';

export type TrustedOperatorIdentity = {
  operator_id: string;
  key_id: string;
  algorithm: 'ed25519';
  enabled: boolean;
  public_key_fingerprint: string;
};

export type OperatorApprovalStatus = {
  schema_version: string;
  contract_status: string;
  trusted_identity_count: number;
  enabled_identity_count: number;
  trusted_identities: TrustedOperatorIdentity[];
  private_key_storage_enabled: false;
  runtime_execution_authority: 'disabled';
  broker_submission_enabled: false;
};

export type OperatorApprovalChallenge = {
  challenge_id: string;
  challenge_status: string;
  signing_payload_base64: string;
  operator_id: string;
  key_id: string;
  action: string;
  artifact_type: string;
  artifact_fingerprint: string;
  issued_at: string;
  expires_at: string;
  reused: boolean;
  operator_identity_verified: false;
  authorizes_execution: false;
};

export type VerifiedOperatorApproval = {
  approval_id: string;
  approval_status: 'verified';
  operator_id: string;
  key_id: string;
  action: string;
  artifact_type: string;
  artifact_fingerprint: string;
  expires_at: string;
  operator_identity_verified: true;
  authorizes_execution: false;
  reused: boolean;
};

export function useOperatorApprovalStatusQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['automation', 'operator-approvals', 'status'],
    queryFn: () =>
      apiClient<OperatorApprovalStatus>(
        '/api/automation/capital-authority/operator-approvals/status',
      ),
    enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  });
}

export function useOperatorApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'post_controlled_submission_ledger';
      artifact_type: 'controlled_submission_ledger_posting';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useOperatorApprovalVerificationMutation() {
  return useMutation({
    mutationFn: (request: { challenge_id: string; signature_base64: string }) =>
      postJson<VerifiedOperatorApproval>(
        '/api/automation/capital-authority/operator-approvals/verifications',
        request,
      ),
  });
}
