import { afterEach, expect, test, vi } from 'vitest';

import { toDatetimeLocalInputValue } from './datetime-local';

afterEach(() => {
  vi.restoreAllMocks();
});

test('formats datetime-local defaults in the browser local timezone', () => {
  vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(-480);

  const value = toDatetimeLocalInputValue(
    new Date('2026-06-30T09:05:21.000Z'),
  );

  expect(value).toBe('2026-06-30T17:05');
});
