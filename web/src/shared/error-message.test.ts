import { expect, test } from 'vitest';

import { getErrorMessage } from './error-message';

test('extracts a structured API detail without leaking its JSON envelope', () => {
  expect(
    getErrorMessage(new Error('{"detail":"Persisted evidence missing"}')),
  ).toBe('Persisted evidence missing');
});

test('preserves readable non-JSON errors and has a deterministic fallback', () => {
  expect(getErrorMessage(new Error('Provider unavailable'))).toBe(
    'Provider unavailable',
  );
  expect(getErrorMessage(null)).toBe(
    'Request failed. Check the form values and service status.',
  );
});
