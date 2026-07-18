import { useState } from 'react';

import { createColumnHelper } from '@tanstack/react-table';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  ControlledActionZone,
  DataTable,
  EvidenceDrawer,
  EvidenceState,
  ExceptionList,
  FilterBar,
  GateMatrix,
  MetricStrip,
  StatusBadge,
  Timeline,
  WorkspaceHeader,
} from './index';

test('renders the workspace hierarchy without routine card nesting', () => {
  render(
    <main>
      <WorkspaceHeader
        eyebrow="Portfolio"
        title="Account evidence"
        description="Persisted account projection"
        context="snapshot: snap-7 · ledger cutoff: 42"
        actions={<button type="button">Inspect</button>}
      />
      <MetricStrip
        ariaLabel="Account metrics"
        items={[
          {
            id: 'equity',
            label: 'Equity',
            value: 'Unavailable',
            detail: 'Snapshot missing',
          },
          {
            id: 'pnl',
            label: 'P&L',
            value: 'Unavailable',
            tone: 'pnl-positive',
          },
        ]}
      />
      <FilterBar label="Position filters" summary="No authoritative rows">
        <button type="button">All assets</button>
      </FilterBar>
    </main>,
  );

  expect(
    screen.getByRole('heading', { name: 'Account evidence' }),
  ).toBeTruthy();
  expect(screen.getByLabelText('Account metrics').tagName).toBe('DL');
  expect(screen.getByLabelText('Position filters').tagName).toBe('SECTION');
  expect(screen.getByText('snapshot: snap-7 · ledger cutoff: 42')).toBeTruthy();

  const header = screen
    .getByRole('heading', { name: 'Account evidence' })
    .closest('header');
  const metrics = screen.getByLabelText('Account metrics');
  const filters = screen.getByLabelText('Position filters');
  expect(header?.getAttribute('data-workbench-primitive')).toBe(
    'workspace-header',
  );
  expect(metrics.getAttribute('data-workbench-primitive')).toBe('metric-strip');
  expect(filters.getAttribute('data-workbench-primitive')).toBe('filter-bar');
  expect(metrics.className).not.toContain('rounded-');
});

test('keeps operational state and financial direction on separate roles', () => {
  render(
    <div>
      <StatusBadge tone="success">reconciled</StatusBadge>
      <MetricStrip
        ariaLabel="Direction metrics"
        items={[
          {
            id: 'positive',
            label: 'Return',
            value: 'Positive',
            tone: 'pnl-positive',
          },
          {
            id: 'negative',
            label: 'Drawdown',
            value: 'Negative',
            tone: 'pnl-negative',
          },
        ]}
      />
    </div>,
  );

  expect(screen.getByText('reconciled').className).toContain(
    'app-success-text',
  );
  expect(screen.getByText('Positive').className).toContain('app-pnl-positive');
  expect(screen.getByText('Negative').className).toContain('app-pnl-negative');
});

test('exposes explicit evidence lifecycle states', () => {
  const { rerender } = render(
    <EvidenceState
      kind="loading"
      title="Loading persisted projection"
      description="No value is authoritative yet"
    />,
  );

  expect(
    screen
      .getByText('Loading persisted projection')
      .closest('section')
      ?.getAttribute('aria-busy'),
  ).toBe('true');

  rerender(
    <EvidenceState
      kind="missing"
      title="Snapshot missing"
      description="Authoritative result is blocked"
      evidence="snapshot: none"
    />,
  );
  expect(
    screen
      .getByText('Snapshot missing')
      .closest('section')
      ?.getAttribute('data-evidence-kind'),
  ).toBe('missing');
  expect(screen.queryByText('missing')).toBeNull();
  expect(screen.getByText('Authoritative result is blocked')).toBeTruthy();
});

test('renders a dense accessible TanStack data table and a real empty state', () => {
  type Row = { id: string; label: string; state: string };
  const column = createColumnHelper<Row>();
  const columns = [
    column.accessor('label', { header: 'Evidence' }),
    column.accessor('state', { header: 'State' }),
  ];
  const { rerender } = render(
    <DataTable
      caption="Evidence rows"
      data={[{ id: 'row-1', label: 'Ledger cutoff', state: 'persisted' }]}
      columns={columns}
      emptyState="No persisted rows"
      getRowId={(row) => row.id}
      rowLabel={(row) => row.label}
    />,
  );

  const table = screen.getByRole('table', { name: 'Evidence rows' });
  const tableShell = table.closest('[data-workbench-primitive="data-table"]');
  expect(tableShell).toBeTruthy();
  expect(tableShell?.className).not.toContain('rounded-');
  expect(
    within(table).getByRole('columnheader', { name: 'Evidence' }),
  ).toBeTruthy();
  expect(
    within(table).getByRole('row', { name: 'Ledger cutoff' }),
  ).toBeTruthy();

  rerender(
    <DataTable
      caption="Evidence rows"
      data={[]}
      columns={columns}
      emptyState="No persisted rows"
    />,
  );
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.getByText('No persisted rows')).toBeTruthy();
});

test('prioritizes blockers, gate evidence, and immutable history', () => {
  render(
    <div>
      <ExceptionList
        ariaLabel="Blocking exceptions"
        emptyState="No exceptions"
        items={[
          {
            id: 'exception-1',
            severity: 'danger',
            title: 'Reconciliation blocked',
            reason: 'Residual is non-zero',
            unblockCondition: 'Residual reconciles to zero',
            nextAction: 'Inspect persisted ledger evidence',
            evidence: 'run: reconcile-9',
          },
        ]}
      />
      <GateMatrix
        caption="Decision gates"
        items={[
          {
            id: 'account-truth',
            gate: 'Account truth',
            state: 'block',
            reason: 'Snapshot missing',
            unblockCondition: 'Persist a validated snapshot',
          },
        ]}
      />
      <Timeline
        ariaLabel="Immutable history"
        emptyState="No history"
        items={[
          {
            id: 'event-1',
            timestamp: '2026-07-18 10:00',
            title: 'Evidence recorded',
            evidence: 'event: evt-1',
          },
        ]}
      />
    </div>,
  );

  expect(screen.getByText('Safe next step')).toBeTruthy();
  expect(screen.getByRole('table', { name: 'Decision gates' })).toBeTruthy();
  expect(screen.getByRole('list', { name: 'Immutable history' })).toBeTruthy();
});

test('closes the evidence drawer with Escape and restores focus', async () => {
  const user = userEvent.setup();

  function DrawerHarness() {
    const [open, setOpen] = useState(false);
    return (
      <div>
        <button type="button" onClick={() => setOpen(true)}>
          Open evidence
        </button>
        <EvidenceDrawer
          open={open}
          onClose={() => setOpen(false)}
          title="Evidence detail"
          description="Persisted provenance"
          closeLabel="Close evidence"
        >
          <p>snapshot: snap-7</p>
        </EvidenceDrawer>
      </div>
    );
  }

  render(<DrawerHarness />);
  const trigger = screen.getByRole('button', { name: 'Open evidence' });
  await user.click(trigger);
  expect(screen.getByRole('dialog', { name: 'Evidence detail' })).toBeTruthy();
  expect(document.activeElement).toBe(
    screen.getAllByRole('button', { name: 'Close evidence' })[1],
  );

  await user.keyboard('{Tab}');
  expect(document.activeElement).toBe(
    screen.getAllByRole('button', { name: 'Close evidence' })[1],
  );

  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

test('isolates privileged controls in a controlled action zone', () => {
  render(
    <ControlledActionZone
      title="Kill switch"
      description="Requires explicit operator confirmation and persisted evidence."
      evidence="authority: denied by default"
    >
      <button type="button" disabled>
        Submit unavailable
      </button>
    </ControlledActionZone>,
  );

  const zone = screen
    .getByRole('heading', { name: 'Kill switch' })
    .closest('section');
  expect(zone?.className).toContain('app-danger-border');
  expect(
    screen.getByRole('button', { name: 'Submit unavailable' }),
  ).toHaveProperty('disabled', true);
  expect(screen.getByText('authority: denied by default')).toBeTruthy();
});
