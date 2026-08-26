export async function postAccountTruthJson<T>(path: string, payload: object) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Request failed: ' + response.status);
  }
  return (await response.json()) as T;
}
