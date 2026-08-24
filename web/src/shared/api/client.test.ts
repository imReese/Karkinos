import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiClient, postJson, requestJson } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('JSON API client', () => {
  it('uses a shared JSON request contract for reads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient<{ status: string }>('/api/status')).resolves.toEqual(
      { status: 'ok' },
    );
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(options.headers).get('Accept')).toBe('application/json');
    expect(options.body).toBeUndefined();
  });

  it('serializes mutation bodies and headers consistently', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ saved: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await postJson('/api/items', { name: 'evidence' });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(options.headers);
    expect(options.method).toBe('POST');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(options.body).toBe(JSON.stringify({ name: 'evidence' }));
  });

  it('surfaces FastAPI detail while preserving structured blockers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: ['stale', 'partial'] }), {
          status: 409,
        }),
      ),
    );

    await expect(requestJson('/api/blocked')).rejects.toThrow(
      '["stale","partial"]',
    );
  });
});
