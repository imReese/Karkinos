// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const page = readFileSync(
  resolve(SRC_ROOT, 'features/market/pages/market-page-view.tsx'),
  'utf8',
);
const notes = readFileSync(
  resolve(
    SRC_ROOT,
    'features/market/pages/market-research-notes-workspace.tsx',
  ),
  'utf8',
);

function requiredIndex(source: string, fragment: string) {
  const index = source.indexOf(fragment);
  expect(index).toBeGreaterThanOrEqual(0);
  return index;
}

test('market keeps instrument research primary and global diagnostics secondary', () => {
  const instrument = requiredIndex(page, '<MarketInstrumentSelection');
  const research = requiredIndex(page, '<MarketResearchNotesWorkspace');
  const diagnostics = requiredIndex(page, '<MarketGlobalDataEvidence');

  expect(instrument).toBeLessThan(research);
  expect(research).toBeLessThan(diagnostics);
  expect(page).not.toContain('function MarketSummary');
  expect(page).toContain('data-testid="market-global-data-evidence"');
});

test('market note history stays readable while note editing is disclosed', () => {
  expect(notes).toContain('data-testid="market-research-workspace"');
  expect(notes).toContain('data-testid="market-research-note-editor"');
  expect(notes).toContain('data-testid="market-research-note-history"');
  expect(notes).toContain('<details');
  expect(requiredIndex(notes, '<MarketResearchNoteEditor')).toBeLessThan(
    requiredIndex(notes, '<MarketResearchNoteHistory'),
  );
  expect(notes).not.toContain(
    'xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]',
  );
});
