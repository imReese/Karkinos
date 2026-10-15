import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { PublicationPolicyStatus } from '../publication-policy-api';
import {
  publicationPolicyBinding as binding,
  disabledPublicationPolicyStatus as disabled,
} from '../../../../test-fixtures/publication-policy';
import { AutomaticPublicationPolicy } from './automatic-publication-policy';

const path = '/api/ai/strategy-research/automatic-publication-policy';
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function mount(client?: QueryClient) {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  return render(
    <QueryClientProvider
      client={
        client ??
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <PreferencesProvider>
        <AutomaticPublicationPolicy updatedBy="human:owner" />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('does not infer an account source or permission from missing evidence', async () => {
  const fetchMock = vi.fn(async () =>
    json({
      ...disabled,
      proposed_binding: null,
      preview_blockers: ['publication_account_evidence_missing'],
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  mount();
  expect(
    await screen.findByText('publication_account_evidence_missing'),
  ).toBeInTheDocument();
  expect(screen.getByText('No applicable source')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Enable automatic publication' }),
  ).toBeNull();
  expect(fetchMock.mock.calls).toHaveLength(1);
});

test.each([null, 'existing-generation'])(
  'previews real bindings before explicit authorization and preserves the current generation (%s)',
  async (generation) => {
    let state: PublicationPolicyStatus = generation
      ? {
          ...disabled,
          policy: {
            ...binding,
            policy_id: 'ai_recommendation_publication',
            generation,
            enabled: true,
          },
          status: 'active',
        }
      : disabled;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === `${path}/preview`)
          return json({
            proposed_binding: binding,
            preview_blockers: [],
            binding_source: null,
          });
        if (init?.method === 'PUT') {
          state = {
            ...disabled,
            policy: {
              ...binding,
              policy_id: 'ai_recommendation_publication',
              generation: 'generation-1',
              enabled: true,
            },
            status: 'active',
            usable_current_sources: [
              {
                strategy_id: 'ai_formula_shadow:real-source',
                decision_source: 'policy',
              },
            ],
          };
          return json(state);
        }
        return json(state);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    mount();
    await screen.findByText('No applicable source');
    fireEvent.click(
      screen.getByText('Configure and verify publication bounds'),
    );
    await waitFor(() =>
      expect(screen.getByLabelText('Allocation scope')).toHaveValue(
        binding.allocation_scope,
      ),
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Verify authorization bounds' }),
    );
    const enable = await screen.findByRole('button', {
      name: 'Enable automatic publication',
    });
    expect(screen.getByTestId('publication-entry-boards')).toHaveTextContent(
      'Allowed entry boards: Main boards',
    );
    expect(enable).toBeDisabled();
    const previewCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/preview'),
    );
    const previewBody = JSON.parse(String(previewCall?.[1]?.body));
    expect(previewBody.account_scope_fingerprint).toBeUndefined();
    expect(previewBody.statistical_policy.decision_checkpoint).toBe(
      '2027-06-30',
    );
    fireEvent.click(
      screen.getByRole('checkbox', {
        name: /I authorize automatic account recommendation publication/,
      }),
    );
    fireEvent.click(enable);
    await waitFor(() =>
      expect(
        within(screen.getByTestId('usable-publication-sources')).getByText(
          /ai_formula_shadow:real-source/,
        ),
      ).toBeInTheDocument(),
    );
    const writeCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === 'PUT',
    );
    const body = JSON.parse(String(writeCall?.[1]?.body));
    expect(body.enabled).toBe(true);
    expect(body.expected_generation).toBe(generation);
    expect(body.deployment_scope_fingerprint).toBe(
      binding.deployment_scope_fingerprint,
    );
    expect(body.confirmation).toBe(
      'authorize_bounded_automatic_account_recommendation_publication_without_trade_or_capital_authority',
    );
    expect(body.human_review).toBeUndefined();
    expect(
      screen.queryByRole('button', { name: 'Enable automatic publication' }),
    ).toBeNull();
  },
);

test('shows a rejected preview without offering authorization', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) =>
      String(input) === `${path}/preview`
        ? json({
            proposed_binding: null,
            preview_blockers: [
              'publication_preview_stock_fee_envelope_missing',
            ],
            binding_source: null,
          })
        : json(disabled),
    ),
  );
  mount();
  await screen.findByText('No applicable source');
  fireEvent.click(screen.getByText('Configure and verify publication bounds'));
  await waitFor(() =>
    expect(screen.getByLabelText('Allocation scope')).toHaveValue(
      binding.allocation_scope,
    ),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Verify authorization bounds' }),
  );
  expect(
    await screen.findByText('publication_preview_stock_fee_envelope_missing'),
  ).toBeVisible();
  expect(screen.queryByTestId('publication-grant-preview')).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Enable automatic publication' }),
  ).toBeNull();
});

test('editing a previewed bound invalidates confirmation and requires another preview', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) =>
      String(input) === `${path}/preview`
        ? json({ proposed_binding: binding, preview_blockers: [] })
        : json(disabled),
    ),
  );
  mount();
  await screen.findByText('No applicable source');
  fireEvent.click(screen.getByText('Configure and verify publication bounds'));
  await waitFor(() =>
    expect(screen.getByLabelText('Allocation scope')).toHaveValue(
      binding.allocation_scope,
    ),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Verify authorization bounds' }),
  );
  await screen.findByTestId('publication-grant-preview');
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: /I authorize automatic account recommendation publication/,
    }),
  );
  fireEvent.change(screen.getByLabelText('Maximum applicable capital (CNY)'), {
    target: { value: '50000' },
  });
  expect(screen.queryByTestId('publication-grant-preview')).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Enable automatic publication' }),
  ).toBeNull();
});

test.each(['status', 'preview'])(
  'keeps revocation available while %s verification is pending',
  async (pendingOperation) => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    let state: PublicationPolicyStatus = {
      ...disabled,
      policy: {
        ...binding,
        policy_id: 'ai_recommendation_publication',
        generation: 'active-generation',
        enabled: true,
      },
      status: 'active',
    };
    let reads = 0;
    let release = () => {};
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'PUT') {
          state = {
            ...disabled,
            policy: { enabled: false, generation: 'revoked-generation' },
          };
          return json(state);
        }
        const isPreview = String(input).endsWith('/preview');
        if (!isPreview) reads += 1;
        if (
          (isPreview && pendingOperation === 'preview') ||
          (!isPreview && reads === 2 && pendingOperation === 'status')
        ) {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
        }
        return json(
          isPreview
            ? { proposed_binding: binding, preview_blockers: [] }
            : state,
        );
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    mount(client);
    const revoke = await screen.findByRole('button', {
      name: 'Revoke grant and suspend its recommendation sources',
    });
    try {
      if (pendingOperation === 'status') {
        void client.invalidateQueries({
          queryKey: ['automatic-publication-policy'],
        });
        await waitFor(() => expect(reads).toBe(2));
      } else {
        fireEvent.click(
          screen.getByText('Configure and verify publication bounds'),
        );
        await waitFor(() =>
          expect(screen.getByLabelText('Allocation scope')).toHaveValue(
            binding.allocation_scope,
          ),
        );
        fireEvent.click(
          screen.getByRole('button', { name: 'Verify authorization bounds' }),
        );
        await waitFor(() =>
          expect(
            fetchMock.mock.calls.some(([input]) =>
              String(input).endsWith('/preview'),
            ),
          ).toBe(true),
        );
      }
      expect(revoke).toBeEnabled();
      fireEvent.click(revoke);
      await waitFor(() => {
        const call = fetchMock.mock.calls.find(
          ([, init]) => init?.method === 'PUT',
        );
        expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
          enabled: false,
          expected_generation: 'active-generation',
          confirmation: 'revoke_automatic_account_recommendation_publication',
        });
      });
      release();
      await screen.findByText('Current grant: disabled');
      await waitFor(() =>
        expect(screen.queryByTestId('publication-grant-preview')).toBeNull(),
      );
    } finally {
      release();
      client.clear();
    }
  },
);
