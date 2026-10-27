import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';
import { researchSimulationFixture } from '../../../../test-fixtures/research-simulation-fixture';
import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import { OverviewResearchSimulationPreview } from './overview-research-simulation-preview';

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    })),
  });
});

test.each(['zh', 'en'] as const)(
  'keeps source, desired targets and research boundaries visible (%s)',
  async (locale) => {
    localStorage.setItem('karkinos.locale', locale);
    const preview = researchSimulationFixture();
    render(
      <PreferencesProvider>
        <OverviewResearchSimulationPreview preview={preview} />
      </PreferencesProvider>,
    );
    const card = screen.getByTestId('overview-research-simulation-preview');
    expect(card).toHaveTextContent(
      locale === 'zh' ? '待人工确认' : 'Human confirmation required',
    );
    expect(card).toHaveTextContent(
      locale === 'zh' ? '不是当前报价' : 'not current quotes',
    );
    expect(card).toHaveTextContent(
      locale === 'zh'
        ? '未核验当前账户费率'
        : 'current account fees are not evaluated',
    );
    expect(card).toHaveTextContent(
      locale === 'zh' ? '假设买入' : 'Hypothetical buy',
    );
    const action = within(card).getByTestId(
      'overview-research-simulation-action',
    );
    for (const value of [
      '合成制造',
      '600001',
      '200',
      '12.0%',
      preview.actions[0].reason!,
      preview.actions[0].risk_impact!,
      String(preview.actions[0].trigger_condition),
    ])
      expect(action).toHaveTextContent(value);
    expect(within(card).queryByRole('button')).not.toBeInTheDocument();
    const details = within(card).getByText(
      locale === 'zh'
        ? '研究来源、费用假设与风险证据'
        : 'Research source, cost assumptions and risks',
    );
    await userEvent.click(details);
    expect(
      within(card).getByRole('link', {
        name:
          locale === 'zh'
            ? '保存的真实回测 #201'
            : 'Saved actual backtest #201',
      }),
    ).toHaveAttribute('href', '/backtest?id=201');
    for (const value of [
      preview.source.session_id!,
      preview.source.draft_id!,
      preview.source.backtest_run_id!,
      preview.source.critique_id!,
    ])
      expect(card).toHaveTextContent(value);
    expect(card).toHaveTextContent(
      locale === 'zh'
        ? '尚未评估是否通过全部历史门禁'
        : 'Passing all historical gates has not been assessed',
    );
    expect(card).toHaveTextContent(
      locale === 'zh'
        ? '保存报告的研究门禁：受阻'
        : 'Saved report research gate: Blocked',
    );
    expect(card).toHaveTextContent('5 bps');
  },
);

test('blocked research does not display leftover actions or a zero-valued substitute', () => {
  localStorage.setItem('karkinos.locale', 'zh');
  const preview = researchSimulationFixture();
  preview.status = 'blocked';
  preview.blockers = [
    'research_latest_cross_source_dataset_unavailable',
    'future_unknown_blocker',
  ];
  preview.as_of_market_date = null;
  render(
    <PreferencesProvider>
      <OverviewResearchSimulationPreview preview={preview} />
    </PreferencesProvider>,
  );
  expect(
    screen.queryByTestId('overview-research-simulation-actions'),
  ).not.toBeInTheDocument();
  const blockers = screen.getByTestId('overview-research-simulation-blockers');
  expect(blockers).toHaveTextContent('最新交易窗口的双源行情尚未核验完整');
  expect(
    within(blockers).getByTitle('future_unknown_blocker'),
  ).toHaveTextContent('研究模拟所需证据尚未齐全');
  expect(
    screen.getByTestId('overview-research-simulation-preview'),
  ).toHaveTextContent('--');
});

test('missing sizing remains unknown and no action does not become account eligibility', () => {
  const preview = researchSimulationFixture();
  preview.actions[0].estimated_quantity = null;
  preview.actions[0].target_weight = null;
  preview.actions[0].estimated_price = null;
  const { rerender } = render(
    <OverviewResearchSimulationPreview preview={preview} />,
  );
  expect(
    within(
      screen.getByTestId('overview-research-simulation-action'),
    ).getAllByText('--'),
  ).toHaveLength(3);
  preview.status = 'no_action';
  rerender(<OverviewResearchSimulationPreview preview={preview} />);
  expect(
    screen.queryByTestId('overview-research-simulation-actions'),
  ).not.toBeInTheDocument();
  expect(
    screen.getByTestId('overview-research-simulation-preview'),
  ).toHaveTextContent('does not establish formal account eligibility');
});
