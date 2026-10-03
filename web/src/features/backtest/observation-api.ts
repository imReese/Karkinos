import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson, putJson } from '../../shared/api/client';
import type {
  ObservationCommand,
  ResearchObservation,
} from './observation-contracts';

const path = '/api/research-observations';
const queryKey = (sourceResultId: number) => [
  'research-observations',
  sourceResultId,
];

export function useResearchObservations(
  enabled: boolean,
  sourceResultId: number,
) {
  return useQuery({
    queryKey: queryKey(sourceResultId),
    queryFn: () =>
      apiClient<ResearchObservation[]>(
        `${path}?source_backtest_result_id=${sourceResultId}&limit=100`,
      ),
    enabled,
    retry: false,
  });
}

export function useObservationCommand() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (command: ObservationCommand) => {
      const url =
        command.kind === 'start'
          ? path
          : `${path}/${encodeURIComponent(command.id)}/${command.kind}`;
      const receipt = await postJson<{ id: string }>(url, command.payload);
      // A receipt acknowledges the command; display the current persisted history.
      return apiClient<ResearchObservation>(
        `${path}/${encodeURIComponent(receipt.id)}`,
      );
    },
    retry: false,
    onSuccess: (observation) => {
      const key = queryKey(observation.source_backtest_result_id);
      client.setQueryData<ResearchObservation[]>(key, (current) => [
        observation,
        ...(current ?? []).filter((item) => item.id !== observation.id),
      ]);
      void client.invalidateQueries({ queryKey: key });
    },
  });
}

export function useConfigureObservationAutomation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (command: {
      observationId: string;
      sourceResultId: number;
      enabled: boolean;
      expectedGeneration: string | null;
    }) => {
      const url = `${path}/${encodeURIComponent(command.observationId)}`;
      await putJson(`${url}/automation`, {
        enabled: command.enabled,
        expected_generation: command.expectedGeneration,
      });
      const observation = await apiClient<ResearchObservation>(url);
      if (
        observation.id !== command.observationId ||
        observation.source_backtest_result_id !== command.sourceResultId
      )
        throw new Error('observation_automation_response_mismatch');
      return observation;
    },
    retry: false,
    onSuccess: (observation) => {
      const key = queryKey(observation.source_backtest_result_id);
      client.setQueryData<ResearchObservation[]>(key, (current) =>
        current
          ? current.map((item) =>
              item.id === observation.id ? observation : item,
            )
          : [observation],
      );
      void client.invalidateQueries({ queryKey: key });
    },
  });
}
