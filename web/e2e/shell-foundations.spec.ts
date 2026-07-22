import { expect, test } from '@playwright/test';

const desktopViewports = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
];

test('desktop shell defaults to labeled business groups and remains collapsible', async ({
  page,
}) => {
  for (const viewport of desktopViewports) {
    await page.setViewportSize(viewport);
    await page.goto('/overview');

    const sidebar = page.locator('#app-shell-navigation');
    const header = page.locator('.app-toolbar-shell');
    const statusFooter = page.locator('.app-status-footer');
    await expect(sidebar).toBeVisible();
    await expect(statusFooter).toBeVisible();
    await expect(
      page.getByText('Decision & Risk', { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('Execution & Operations', { exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId('sidebar-nav-overview')).toContainText(
      'Overview',
    );
    await expect(page.getByText('Workspace toolbar')).toHaveCount(0);
    await expect(page.getByTestId('workspace-command-trigger')).toBeVisible();
    if (viewport.width >= 1280) {
      await expect(page.locator('.app-toolbar-state')).toBeVisible();
    } else {
      await expect(page.locator('.app-toolbar-state')).toBeHidden();
    }
    await expect(statusFooter).toContainText('Persisted evidence');
    await expect(
      page.getByRole('button', { name: /Refresh quotes: Market/ }),
    ).toHaveCount(0);

    const shellGeometry = await page.evaluate(() => {
      const sidebarElement = document.querySelector(
        '#app-shell-navigation',
      ) as HTMLElement;
      const headerElement = document.querySelector(
        '.app-toolbar-shell',
      ) as HTMLElement;
      const headerStyle = getComputedStyle(headerElement);
      return {
        sidebarWidth: sidebarElement.getBoundingClientRect().width,
        headerHeight: headerElement.getBoundingClientRect().height,
        headerTop: headerElement.getBoundingClientRect().top,
        headerRadius: headerStyle.borderRadius,
        backdropFilter: headerStyle.backdropFilter,
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      };
    });
    expect(shellGeometry.sidebarWidth).toBeGreaterThanOrEqual(200);
    expect(shellGeometry.headerHeight).toBe(49);
    expect(shellGeometry.headerTop).toBe(0);
    expect(shellGeometry.headerRadius).toBe('0px');
    expect(shellGeometry.backdropFilter).toBe('none');
    expect(shellGeometry.documentOverflow).toBeLessThanOrEqual(0);

    await page.getByRole('button', { name: 'Close navigation' }).click();
    await expect
      .poll(async () => (await sidebar.boundingBox())?.width)
      .toBe(56);
  }
});

test('workspace command menu navigates without adding execution authority', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/overview');

  await page.keyboard.press('Control+k');
  const commandMenu = page.getByRole('dialog', { name: 'Go to workspace' });
  await expect(commandMenu).toBeVisible();
  const search = commandMenu.getByRole('textbox', { name: 'Search routes' });
  await expect(search).toBeFocused();
  await search.fill('risk');
  await commandMenu.getByRole('link', { name: 'Risk' }).click();

  await expect(page).toHaveURL(/\/risk$/);
  await expect(commandMenu).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: 'Risk control center' }),
  ).toBeVisible();
});

test('desktop utility controls align and overview holdings avoid partial columns', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.addInitScript(() => {
    window.localStorage.setItem('karkinos.locale', 'zh');
  });
  await page.goto('/overview');
  await page.getByRole('button', { name: '浅色主题' }).click();
  await expect(page.getByTestId('overview-holdings-section')).toBeVisible({
    timeout: 15_000,
  });

  const geometry = await page.evaluate(() => {
    const valuation = document.querySelector(
      '[data-testid="status-pill-valuation"]',
    ) as HTMLElement;
    const value = valuation.querySelector(
      '[data-status-chip-part="value"]',
    ) as HTMLElement;
    const meta = valuation.querySelector(
      '[data-status-chip-part="meta"]',
    ) as HTMLElement;
    const chevron = valuation.querySelector(
      '[data-status-chip-part="chevron"]',
    ) as SVGElement;
    const holdingsSection = document.querySelector(
      '[data-testid="overview-holdings-section"]',
    ) as HTMLElement;
    const dashboardScroll = holdingsSection.querySelector(
      '[data-testid="positions-table-scroll"]',
    ) as HTMLElement | null;
    const dashboardOverflowTarget = dashboardScroll ?? holdingsSection;
    const toolbarControls = [
      document.querySelector('.app-command-trigger') as HTMLElement,
      document.querySelector('.app-theme-switcher') as HTMLElement,
      document.querySelector('.app-language-control') as HTMLElement,
    ].map((element) => element.getBoundingClientRect());
    const valueBox = value.getBoundingClientRect();
    const metaBox = meta.getBoundingClientRect();
    const chevronBox = chevron.getBoundingClientRect();

    return {
      dashboardOverflow:
        dashboardOverflowTarget.scrollWidth -
        dashboardOverflowTarget.clientWidth,
      statusValueWidth: valueBox.width,
      statusValueClipped: value.scrollWidth > value.clientWidth,
      statusMetaChevronGap: chevronBox.left - metaBox.right,
      toolbarHeights: toolbarControls.map((box) => box.height),
      toolbarCenters: toolbarControls.map((box) => box.top + box.height / 2),
    };
  });

  expect(geometry.dashboardOverflow).toBeLessThanOrEqual(0);
  expect(geometry.statusValueWidth).toBeGreaterThan(0);
  expect(geometry.statusValueClipped).toBe(false);
  expect(geometry.statusMetaChevronGap).toBeGreaterThanOrEqual(4);
  expect(geometry.toolbarHeights).toEqual([32, 32, 32]);
  expect(
    Math.max(...geometry.toolbarCenters) - Math.min(...geometry.toolbarCenters),
  ).toBeLessThanOrEqual(1);

  const valuationStatus = page.getByTestId('status-pill-valuation');
  await valuationStatus.click();
  await expect
    .poll(() =>
      valuationStatus.evaluate((element) => {
        const style = getComputedStyle(element);
        const selectedTheme = document.querySelector(
          '.app-theme-switcher-option[aria-pressed="true"]',
        ) as HTMLElement;
        const themeSwitcher = document.querySelector(
          '.app-theme-switcher',
        ) as HTMLElement;
        return {
          backgroundMatches:
            style.backgroundColor ===
            getComputedStyle(selectedTheme).backgroundColor,
          borderMatches:
            style.borderColor === getComputedStyle(themeSwitcher).borderColor,
        };
      }),
    )
    .toEqual({ backgroundMatches: true, borderMatches: true });
});

test('shell remains local-overflow safe in Latte and Mocha across tablet and mobile', async ({
  page,
}) => {
  test.setTimeout(60_000);
  for (const theme of ['light', 'dark']) {
    for (const viewport of [
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto('/overview');
      const themeName = theme === 'light' ? 'Light theme' : 'Dark theme';
      if (viewport.width < 640) {
        await page.getByTestId('mobile-preferences-toggle').click();
        await page
          .getByRole('dialog', { name: 'Theme · Language' })
          .getByRole('button', { name: themeName })
          .click();
      } else {
        await page.getByRole('button', { name: themeName }).click();
      }

      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      const toggle = page.getByTestId('mobile-navigation-toggle');
      const primaryNavigation = page.getByRole('navigation', {
        name: 'Primary navigation',
      });
      await expect(toggle).toBeVisible();
      await expect(primaryNavigation).toBeVisible();
      await expect(
        primaryNavigation.getByRole('link', { name: 'Overview' }),
      ).toBeVisible();
      await expect(
        primaryNavigation.getByRole('link', { name: 'Portfolio' }),
      ).toBeVisible();
      await expect(
        primaryNavigation.getByRole('link', { name: 'Decision' }),
      ).toBeVisible();
      await expect(page.locator('#app-shell-navigation')).not.toBeInViewport();
      await toggle.click();
      await expect(
        page.getByRole('navigation', { name: 'Navigation', exact: true }),
      ).toBeVisible();
      await expect(page.getByTestId('sidebar-nav-overview')).toContainText(
        'Overview',
      );

      const documentOverflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(documentOverflow).toBeLessThanOrEqual(0);
      await page
        .locator('#app-shell-navigation')
        .getByRole('button', { name: 'Close navigation' })
        .first()
        .click();
    }
  }
});
