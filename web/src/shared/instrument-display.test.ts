import { expect, test } from 'vitest';

import { formatInstrumentDisplayLabelFromNameMap } from './instrument-display';

test('formats a symbol with a case-insensitive mapped display name', () => {
  expect(
    formatInstrumentDisplayLabelFromNameMap(
      'ABC123',
      new Map([['abc123', 'Example Asset']]),
    ),
  ).toBe('Example Asset ABC123');
});

test('preserves the original symbol when no distinct name is available', () => {
  expect(formatInstrumentDisplayLabelFromNameMap('ABC123')).toBe('ABC123');
  expect(
    formatInstrumentDisplayLabelFromNameMap(
      'ABC123',
      new Map([['abc123', 'ABC123']]),
    ),
  ).toBe('ABC123');
});
