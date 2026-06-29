import { appFeatureChunk } from './chunk-config';

describe('appFeatureChunk', () => {
  it('groups cross-linked workspace features into one non-circular chunk', () => {
    expect(appFeatureChunk('/repo/web/src/features/account/api.ts')).toBe(
      'feature-workbench-core',
    );
    expect(appFeatureChunk('/repo/web/src/features/market/api.ts')).toBe(
      'feature-workbench-core',
    );
    expect(appFeatureChunk('/repo/web/src/features/portfolio/api.ts')).toBe(
      'feature-workbench-core',
    );
    expect(
      appFeatureChunk('/repo/web/src/features/backtest/components/page.tsx'),
    ).toBe('feature-workbench-core');
    expect(appFeatureChunk('/repo/web/src/features/activity/api.ts')).toBe(
      'feature-workbench-core',
    );
  });

  it('keeps account truth and strategy evidence inside the workspace core', () => {
    expect(appFeatureChunk('/repo/web/src/features/account-truth/api.ts')).toBe(
      'feature-workbench-core',
    );
    expect(
      appFeatureChunk('/repo/web/src/features/account-strategy/api.ts'),
    ).toBe('feature-workbench-core');
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
