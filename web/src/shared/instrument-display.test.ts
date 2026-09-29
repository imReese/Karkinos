import { expect, test } from 'vitest';

import {
  formatInstrumentDisplayLabel,
  formatInstrumentDisplayLabelFromNameMap,
  registerInstrumentDisplayNames,
} from './instrument-display';

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

test('formats common symbols like 603659 with Chinese display name', () => {
  expect(formatInstrumentDisplayLabel({ symbol: '603659' })).toBe(
    '璞泰来 603659',
  );
  expect(formatInstrumentDisplayLabel({ symbol: '601985' })).toBe(
    '中国核电 601985',
  );
});

test('supports dynamic instrument name registration', () => {
  registerInstrumentDisplayNames([
    { symbol: '300059', display_name: '东方财富' },
  ]);
  expect(formatInstrumentDisplayLabel({ symbol: '300059' })).toBe(
    '东方财富 300059',
  );
});
