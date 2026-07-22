import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router';
import { render, screen, waitFor, within } from '@testing-library/react';
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
  expect(
    screen.getByText(
      'A structural view of the product contract. It contains no account, return, order, or execution data.',
    ),
  ).toBeTruthy();

  const workbenchLinks = screen.getAllByRole('link', {
    name: 'Enter workbench',
  });
  expect(workbenchLinks.length).toBeGreaterThanOrEqual(2);
  expect(workbenchLinks[0]?.getAttribute('href')).toBe('/overview');
  expect(document.querySelector('.app-shell-frame')).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
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
