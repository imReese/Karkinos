// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { appFeatureChunk } from './chunk-config';

const viteConfigSource = readFileSync(
  resolve(process.cwd(), 'vite.config.ts'),
  'utf8',
);

describe('appFeatureChunk', () => {
  it('splits growing workspace features by domain-sized chunks', () => {
    expect(appFeatureChunk('/repo/web/src/features/account/api.ts')).toBe(
      'feature-account',
    );
    expect(appFeatureChunk('/repo/web/src/features/market/api.ts')).toBe(
      'feature-market-portfolio',
    );
    expect(appFeatureChunk('/repo/web/src/features/portfolio/api.ts')).toBe(
      'feature-market-portfolio',
    );
    expect(
      appFeatureChunk('/repo/web/src/features/backtest/components/page.tsx'),
    ).toBe('feature-backtest');
    expect(appFeatureChunk('/repo/web/src/features/activity/api.ts')).toBe(
      'feature-activity',
    );
  });

  it('keeps strategy evidence beside the account workspace', () => {
    expect(
      appFeatureChunk('/repo/web/src/features/account-strategy/api.ts'),
    ).toBe('feature-account');
  });

  it('splits the large account truth workspace into its own route chunk', () => {
    expect(appFeatureChunk('/repo/web/src/features/account-truth/api.ts')).toBe(
      'feature-account-truth',
    );
  });

  it('keeps one-way feature pages split from the workspace core', () => {
    expect(appFeatureChunk('/repo/web/src/features/decision/api.ts')).toBe(
      'feature-decision',
    );
    expect(
      appFeatureChunk('/repo/web/src/features/settings/components/page.tsx'),
    ).toBe('feature-settings');
    expect(
      appFeatureChunk('/repo/web/src/features/trading/components/page.tsx'),
    ).toBe('feature-trading');
  });

  it('leaves vendor and shared app modules to the remaining chunk rules', () => {
    expect(appFeatureChunk('/repo/web/node_modules/react/index.js')).toBe(
      undefined,
    );
    expect(appFeatureChunk('/repo/web/src/app/router.tsx')).toBe(undefined);
  });

  it('does not recursively pull workspace dependencies into the public entry', () => {
    expect(viteConfigSource).toContain('codeSplitting');
    expect(viteConfigSource).toContain('includeDependenciesRecursively: false');
    expect(viteConfigSource).not.toContain('manualChunks');
  });
});
