import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../shared/api/client';
import type {
  PaperBookCommand,
  ResearchPaperBook,
} from './paper-book-contracts';

const path = (observationId: string) =>
  `/api/research-observations/${encodeURIComponent(observationId)}/paper-book`;
const key = (observationId: string) => ['research-paper-book', observationId];

function checked(book: ResearchPaperBook | null, observationId: string) {
  if (book && book.observation_id !== observationId)
    throw new Error('paper_book_response_mismatch');
  return book;
}

export function useResearchPaperBook(observationId: string, enabled: boolean) {
  return useQuery({
    queryKey: key(observationId),
    queryFn: async () =>
      checked(
        await apiClient<ResearchPaperBook | null>(path(observationId)),
        observationId,
      ),
    enabled,
    retry: false,
  });
}

export function usePaperBookCommand() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (command: PaperBookCommand) => {
      const suffix = command.kind === 'create' ? '' : `/${command.kind}`;
      const receipt = checked(
        await postJson<ResearchPaperBook>(
          `${path(command.observationId)}${suffix}`,
          command.payload,
        ),
        command.observationId,
      );
      if (!receipt) throw new Error('paper_book_response_mismatch');
      // An idempotent command can return its original version. Read current
      // persisted state before replacing the displayed snapshot.
      const book = checked(
        await apiClient<ResearchPaperBook | null>(path(command.observationId)),
        command.observationId,
      );
      if (!book) throw new Error('paper_book_response_mismatch');
      return book;
    },
    retry: false,
    onSuccess: (book) => {
      client.setQueryData<ResearchPaperBook | null>(
        key(book.observation_id),
        (current) =>
          current && current.version > book.version ? current : book,
      );
    },
  });
}
