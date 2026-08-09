import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { PublicHomePage } from './public-home-page';

function installMatchMediaMock(initialDark = false) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('prefers-color-scheme: dark') && initialDark,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function renderPublicHome(locale: 'en' | 'zh' = 'en') {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', locale);
  window.localStorage.setItem('karkinos.theme', 'light');
  installMatchMediaMock();

  const rootRoute = createRootRoute({ component: Outlet });
  const homeRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: PublicHomePage,
  });
  const overviewRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/overview',
    component: () => <div>Private workbench</div>,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([homeRoute, overviewRoute]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  });

  render(
    <PreferencesProvider>
      <RouterProvider router={router} />
    </PreferencesProvider>,
  );
}

afterEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, '', '/');
  vi.unstubAllGlobals();
});

test('renders an evidence-first public home without loading financial data', async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  renderPublicHome();

  expect(
    await screen.findByRole('heading', {
      level: 1,
      name: 'Every decision should leave evidence.',
    }),
  ).toBeTruthy();
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  expect(
    screen.getByRole('navigation', { name: 'Public navigation' }),
  ).toBeTruthy();
  expect(screen.getByRole('contentinfo')).toBeTruthy();
  expect(screen.getAllByTestId('karkinos-mark')).toHaveLength(2);
  expect(
    screen.getByText(
      'Structural product proof only. It contains no account, return, order, or execution data.',
    ),
  ).toBeTruthy();
  expect(screen.getByText('Evidence references')).toBeTruthy();

  const evidenceTrace = screen.getByTestId('public-evidence-trace');
  const workbenchStructure = within(evidenceTrace).getByLabelText(
    'Workbench structure',
  );
  expect(within(workbenchStructure).getByText('Evidence quality')).toBeTruthy();
  expect(
    within(evidenceTrace).getByRole('heading', {
      name: 'Resolve the highest blocker first.',
    }),
  ).toBeTruthy();
  expect(
    within(evidenceTrace).getByLabelText('Public-to-private route'),
  ).toBeTruthy();
  expect(
    within(
      within(evidenceTrace).getByRole('list', {
        name: 'Decision evidence path',
      }),
    ).getAllByRole('listitem'),
  ).toHaveLength(4);
  expect(within(evidenceTrace).getByText('Read and review only')).toBeTruthy();
  expect(
    within(evidenceTrace).getByText(
      'No order placement, cancellation, recovery, or capital expansion by default.',
    ),
  ).toBeTruthy();

  const workbenchLinks = screen.getAllByRole('link', {
    name: 'Open private workbench',
  });
  expect(workbenchLinks.length).toBeGreaterThanOrEqual(2);
  expect(workbenchLinks[0]?.getAttribute('href')).toBe('/overview');
  expect(screen.getByText('Workbench')).toBeTruthy();
  expect(
    screen
      .getByRole('link', { name: 'Open surface: Account Truth' })
      .getAttribute('href'),
  ).toBe('/account-truth');
  expect(
    screen
      .getByRole('link', { name: 'Open surface: Activity history' })
      .getAttribute('href'),
  ).toBe('/activity');
  expect(
    screen
      .getByRole('link', { name: 'Open surface: Decision gates' })
      .getAttribute('href'),
  ).toBe('/decision');
  expect(document.querySelector('.app-shell-frame')).toBeNull();
  expect(document.body.textContent).not.toMatch(
    /canonical|persisted|provider|paper\/shadow|snapshot|ledger cutoff|fail[- ]closed|\bGET\b/i,
  );
  expect(fetchMock).not.toHaveBeenCalled();
});

test('keeps public sections addressable through anchor navigation', async () => {
  renderPublicHome();
  const user = userEvent.setup();
  const navigation = await screen.findByRole('navigation', {
    name: 'Public navigation',
  });
  const sectionNavigation = screen.getByRole('navigation', {
    name: 'Page sections',
  });

  for (const [name, id] of [
    ['Product', 'product'],
    ['Trust', 'principles'],
    ['Workflow', 'workflow'],
  ] as const) {
    expect(
      within(sectionNavigation)
        .getByRole('link', { name })
        .getAttribute('href'),
    ).toBe(`#${id}`);
    expect(document.getElementById(id)?.getAttribute('tabindex')).toBe('-1');
    expect(document.getElementById(id)?.getAttribute('aria-labelledby')).toBe(
      `public-${id}-title`,
    );
  }

  const productNavigationLink = within(navigation).getByRole('link', {
    name: 'Product',
  });
  productNavigationLink.focus();
  await user.keyboard('{Enter}');
  expect(
    within(navigation)
      .getByRole('link', { name: 'Product' })
      .getAttribute('aria-current'),
  ).toBe('location');
  expect(
    screen.getByRole('link', { name: 'Open surface: Account Truth' }),
  ).toBeTruthy();
  await waitFor(() => {
    expect(document.activeElement).toBe(document.getElementById('product'));
  });

  await user.click(within(navigation).getByRole('link', { name: 'Trust' }));
  expect(
    within(navigation)
      .getByRole('link', { name: 'Trust' })
      .getAttribute('aria-current'),
  ).toBe('location');

  await user.click(within(navigation).getByRole('link', { name: 'Workflow' }));
  expect(
    within(navigation)
      .getByRole('link', { name: 'Workflow' })
      .getAttribute('aria-current'),
  ).toBe('location');
  expect(
    screen.getByRole('heading', {
      name: 'From an idea to a controlled decision.',
    }),
  ).toBeTruthy();
  await waitFor(() => {
    expect(document.activeElement).toBe(document.getElementById('workflow'));
  });

  expect(
    screen
      .getByRole('list', { name: 'Product proof' })
      .getAttribute('data-local-overflow'),
  ).toBe('public-product-proof');
  expect(
    screen
      .getByRole('list', { name: 'Capability flow' })
      .getAttribute('data-local-overflow'),
  ).toBe('public-workflow');
  expect(
    screen
      .getByLabelText('Trust principles')
      .getAttribute('data-local-overflow'),
  ).toBe('public-principles');

  const productRail = screen.getByRole('list', { name: 'Product proof' });
  const scrollBy = vi.fn();
  Object.defineProperties(productRail, {
    clientWidth: { configurable: true, value: 340 },
    scrollWidth: { configurable: true, value: 744 },
    scrollBy: { configurable: true, value: scrollBy },
  });
  fireEvent.keyDown(productRail, { key: 'ArrowRight' });
  expect(scrollBy).toHaveBeenCalledWith({
    left: 340 * 0.78,
    behavior: 'smooth',
  });
  vi.mocked(window.matchMedia).mockReturnValue({
    matches: true,
  } as MediaQueryList);
  fireEvent.keyDown(productRail, { key: 'ArrowLeft' });
  expect(scrollBy).toHaveBeenLastCalledWith({
    left: -(340 * 0.78),
    behavior: 'auto',
  });
});

test('focuses a directly linked public section after mounting', async () => {
  window.history.replaceState(null, '', '/#principles');
  renderPublicHome();

  await waitFor(() => {
    expect(document.activeElement).toBe(document.getElementById('principles'));
  });
  expect(
    screen.getByRole('heading', {
      name: 'Trust begins where convenience stops.',
    }),
  ).toBeTruthy();
});

test('supports localized copy and direct Latte or Mocha switching', async () => {
  renderPublicHome('zh');
  const user = userEvent.setup();

  expect(
    await screen.findByRole('heading', {
      level: 1,
      name: '让每一个投资决定，都有证据可回放。',
    }),
  ).toBeTruthy();

  await user.click(screen.getByRole('button', { name: '切换为英文' }));
  expect(
    await screen.findByRole('heading', {
      level: 1,
      name: 'Every decision should leave evidence.',
    }),
  ).toBeTruthy();

  const header = screen.getByRole('banner');
  await user.click(
    within(header).getByRole('button', { name: 'Switch to Mocha theme' }),
  );
  await waitFor(() => {
    expect(document.documentElement.dataset.theme).toBe('dark');
  });
  expect(
    within(header).getByRole('button', { name: 'Switch to Latte theme' }),
  ).toBeTruthy();
});
