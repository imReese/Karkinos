export type JsonRequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown;
};

export async function requestJson<T>(
  path: string,
  options: JsonRequestOptions = {},
): Promise<T> {
  const { body, headers: suppliedHeaders, ...requestOptions } = options;
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    ...(suppliedHeaders
      ? Object.fromEntries(new Headers(suppliedHeaders).entries())
      : {}),
  };
  const response = await fetch(path, {
    ...requestOptions,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown };
      if (typeof parsed.detail === 'string') {
        detail = parsed.detail;
      } else if (parsed.detail !== undefined) {
        detail = JSON.stringify(parsed.detail);
      }
    } catch {
      // Preserve a non-JSON response body.
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function apiClient<T>(path: string): Promise<T> {
  return requestJson<T>(path);
}

export function postJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, { method: 'POST', body });
}

export function putJson<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(path, { method: 'PUT', body });
}

export function deleteJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { method: 'DELETE' });
}
