import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, test } from 'vitest';

import type { CorporateActionEvidence } from '../api-contracts';
import { CorporateActionEvidencePanel } from './corporate-action-evidence-panel';

const evidence: CorporateActionEvidence = {
  schema_version: 'karkinos.corporate_action_evidence.v1',
  status: 'observed',
  observation_ids: ['observation-1'],
  provider: 'tushare',
  available_at: '2026-10-02T08:00:00Z',
  availability_basis: 'capture_completed_at',
  historical_availability_verified: false,
  covered_action_types: ['cash_dividend', 'bonus_share_distribution'],
  coverage_status: 'provider_reported_only',
  total_record_count: 9,
  matched_event_count: 2,
  undated_event_count: 1,
  events: [],
  returns_modeled: false,
  limitations: [],
};

test('observed records show counts, remaining coverage gaps and unmodeled returns in Chinese', () => {
  render(<CorporateActionEvidencePanel evidence={evidence} locale="zh" />);
  expect(screen.getByText('已采集 · 覆盖未核实')).toBeTruthy();
  for (const [label, count] of [
    ['供应商返回记录', '9'],
    ['区间命中记录', '2'],
    ['日期不足的记录', '1'],
  ]) {
    expect(
      within(screen.getByText(label).parentElement!).getByText(count),
    ).toBeTruthy();
  }
  expect(screen.getByText(/尚未证明区间事件完整/)).toBeTruthy();
  expect(
    screen.getByText(/公告日和实施公告日不证明整条记录当时已知/),
  ).toBeTruthy();
  expect(screen.getByText(/尚未计入现金派息、送转持仓或总收益/)).toBeTruthy();
});

test('zero matches never imply that the interval had no corporate actions', () => {
  render(
    <CorporateActionEvidencePanel
      evidence={{ ...evidence, matched_event_count: 0 }}
      locale="en"
    />,
  );
  expect(screen.getByText('Collected · coverage unverified')).toBeTruthy();
  expect(
    screen.getByText(/No records matched this interval.*does not establish/),
  ).toBeTruthy();
  expect(screen.getByText(/Completeness is unverified/)).toBeTruthy();
  expect(screen.getByText(/total return are not modeled/)).toBeTruthy();
});

test('expanded records preserve proposal status, dates, exact per-share values and unknown fields', () => {
  const event: CorporateActionEvidence['events'][number] = {
    symbol: '600000',
    instrument_type: 'stock',
    div_proc: '预案',
    end_date: '2025-12-31',
    ann_date: '2026-03-20',
    imp_ann_date: null,
    record_date: '2026-06-05',
    ex_date: '2026-06-08',
    pay_date: null,
    div_listdate: '2026-06-10',
    cash_div_tax: '0.125',
    cash_div: null,
    stk_div: '0.3',
    stk_bo_rate: '0.1',
    stk_co_rate: '0.2',
    available_at: evidence.available_at,
    captured_at: evidence.available_at,
    source_revision_id: 'revision-1',
    observation_id: 'observation-1',
  };
  render(
    <CorporateActionEvidencePanel
      evidence={{ ...evidence, events: [event] }}
      locale="zh"
    />,
  );
  fireEvent.click(screen.getByText('查看记录明细（1）'));
  const table = screen.getByRole('table', { name: '分红送转记录明细' });
  for (const value of [
    '600000',
    '预案',
    '2026-03-20',
    '2026-06-05',
    '2026-06-08',
    '2026-06-10',
    '0.125',
    '0.3',
    '0.1',
    '0.2',
  ]) {
    expect(within(table).getByText(value)).toBeTruthy();
  }
  expect(within(table).getAllByText('未知')).toHaveLength(2);
  expect(within(table).queryByText('已到账')).toBeNull();
  expect(screen.getByText(/事件日期不代表已到账/)).toBeTruthy();
  expect(
    screen.getByTestId('corporate-action-events-scroll').className,
  ).toContain('overflow-x-auto');
});

test.each(['zh', 'en'] as const)(
  'missing evidence remains unevaluated in %s',
  (locale) => {
    render(<CorporateActionEvidencePanel locale={locale} />);
    expect(
      screen.getByText(locale === 'zh' ? '未评估' : 'Not evaluated'),
    ).toBeTruthy();
    expect(
      screen.getByText(
        locale === 'zh'
          ? /不能据此判断区间内没有公司行动/
          : /does not establish that the interval had no corporate actions/,
      ),
    ).toBeTruthy();
    expect(screen.queryByText('已采集 · 覆盖未核实')).toBeNull();
  },
);
