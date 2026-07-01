import { appFeatureChunk } from './chunk-config';

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

  it('keeps account truth and strategy evidence beside the account workspace', () => {
    expect(appFeatureChunk('/repo/web/src/features/account-truth/api.ts')).toBe(
      'feature-account',
    );
    expect(
      appFeatureChunk('/repo/web/src/features/account-strategy/api.ts'),
    ).toBe('feature-account');
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
});
