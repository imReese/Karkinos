import { expect, test } from '@playwright/test';

const desktopViewports = [
  { width: 1536, height: 900 },
  { width: 1280, height: 800 },
];

test('desktop shell defaults to labeled business groups and remains collapsible', async ({
  page,
}) => {
  for (const viewport of desktopViewports) {
    await page.setViewportSize(viewport);
    await page.goto('/overview');

    const sidebar = page.locator('#app-shell-navigation');
    const header = page.locator('.app-toolbar-shell');
    const statusRail = page.locator('.app-toolbar-status-rail');
    await expect(sidebar).toBeVisible();
    const wideStatusRail = viewport.width >= 1536;
    if (wideStatusRail) {
      await expect(statusRail).toBeVisible();
    } else {
      await expect(statusRail).toBeHidden();
    }
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
    if (wideStatusRail) {
      await expect(page.locator('.app-toolbar-state')).toBeVisible();
    } else {
      await expect(page.locator('.app-toolbar-state')).toBeHidden();
    }
    if (wideStatusRail) {
      await expect(
        statusRail.getByTestId('status-pill-valuation'),
      ).toBeVisible();
      await expect(statusRail.getByTestId('status-pill-market')).toBeVisible();
    }
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

test('laptop routes defer hidden toolbar projections until the rail is visible', async ({
  page,
}) => {
  const requestedApiPaths: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      requestedApiPaths.push(url.pathname);
    }
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/risk');
  await expect(page.getByTestId('risk-loading-workspace')).toHaveCount(0, {
    timeout: 15_000,
  });
  await expect(page.locator('.app-toolbar-status-rail')).toBeHidden();
  expect(requestedApiPaths).not.toContain('/api/portfolio/overview');
  expect(requestedApiPaths).not.toContain('/api/market/data-health');

  await page.setViewportSize({ width: 1536, height: 900 });
  await expect(page.locator('.app-toolbar-status-rail')).toBeVisible();
  await expect
    .poll(() => requestedApiPaths.includes('/api/portfolio/overview'))
    .toBe(true);
  expect(requestedApiPaths).toContain('/api/market/data-health');
});

test('workspace routes start at the top and restore prior scroll on browser history', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/overview');
  await page.addStyleTag({
    content: '.app-route-stage { min-height: 1400px; }',
  });

  const content = page.locator('.app-shell-content');
  await expect(content).toBeVisible();
  const savedScrollTop = await content.evaluate((element) => {
    element.scrollTop = Math.min(
      320,
      element.scrollHeight - element.clientHeight,
    );
    return element.scrollTop;
  });
  expect(savedScrollTop).toBeGreaterThan(0);

  await page.getByRole('link', { name: 'Risk', exact: true }).click();
  await expect(page).toHaveURL(/\/risk$/);
  await expect
    .poll(() => content.evaluate((element) => element.scrollTop))
    .toBe(0);

  await page.goBack();
  await expect(page).toHaveURL(/\/overview$/);
  await expect
    .poll(() => content.evaluate((element) => element.scrollTop))
    .toBe(savedScrollTop);
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

test('desktop keyboard order reaches a named command with a visible focus ring', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/settings');
  await expect(
    page.getByRole('heading', { name: 'Control center' }),
  ).toBeVisible();

  const focusSequence: Array<{
    name: string;
    outlineStyle: string;
    outlineWidth: number;
    testId: string | null;
  }> = [];
  for (let step = 0; step < 24; step += 1) {
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      const style = element ? getComputedStyle(element) : null;
      return {
        name:
          element?.getAttribute('aria-label') ??
          element?.textContent?.trim().replace(/\s+/g, ' ') ??
          '',
        outlineStyle: style?.outlineStyle ?? 'none',
        outlineWidth: Number.parseFloat(style?.outlineWidth ?? '0'),
        testId: element?.getAttribute('data-testid') ?? null,
      };
    });
    focusSequence.push(focused);
    if (focused.testId === 'workspace-command-trigger') {
      break;
    }
  }

  const commandFocus = focusSequence.find(
    (entry) => entry.testId === 'workspace-command-trigger',
  );
  expect(commandFocus).toBeDefined();
  expect(commandFocus?.name).toBe('Go to a workspace route');
  expect(commandFocus?.outlineStyle).not.toBe('none');
  expect(commandFocus?.outlineWidth).toBeGreaterThanOrEqual(2);
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
  await expect(page.locator('.app-toolbar-status-rail')).toBeHidden();
  await expect(page.locator('.app-toolbar-state')).toBeHidden();

  const laptopGeometry = await page.evaluate(() => {
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
    const commandBox = toolbarControls[0];

    return {
      dashboardOverflow:
        dashboardOverflowTarget.scrollWidth -
        dashboardOverflowTarget.clientWidth,
      commandWidth: commandBox.width,
      toolbarHeights: toolbarControls.map((box) => box.height),
      toolbarCenters: toolbarControls.map((box) => box.top + box.height / 2),
    };
  });

  expect(laptopGeometry.dashboardOverflow).toBeLessThanOrEqual(0);
  expect(laptopGeometry.commandWidth).toBe(196);
  expect(laptopGeometry.toolbarHeights).toEqual([32, 32, 32]);
  expect(
    Math.max(...laptopGeometry.toolbarCenters) -
      Math.min(...laptopGeometry.toolbarCenters),
  ).toBeLessThanOrEqual(1);

  await page.setViewportSize({ width: 1536, height: 900 });
  await expect(page.locator('.app-toolbar-status-rail')).toBeVisible();
  await expect(page.getByTestId('status-pill-valuation')).not.toHaveAttribute(
    'aria-label',
    /检查中/,
  );
  await expect(page.getByTestId('status-pill-market')).not.toHaveAttribute(
    'aria-label',
    /检查中/,
  );

  const wideGeometry = await page.evaluate(() => {
    const valuation = document.querySelector(
      '[data-testid="status-pill-valuation"]',
    ) as HTMLElement;
    const market = document.querySelector(
      '[data-testid="status-pill-market"]',
    ) as HTMLElement;
    const value = valuation.querySelector(
      '[data-status-chip-part="value"]',
    ) as HTMLElement;
    const meta = valuation.querySelector(
      '[data-status-chip-part="meta"]',
    ) as HTMLElement;
    const command = document.querySelector(
      '.app-command-trigger',
    ) as HTMLElement;
    return {
      statusValueWidth: value.getBoundingClientRect().width,
      statusValueClipped: value.scrollWidth > value.clientWidth,
      statusMetaDisplay: getComputedStyle(meta).display,
      marketAccessibleName: market.getAttribute('aria-label'),
      marketCommandGap:
        command.getBoundingClientRect().left -
        market.getBoundingClientRect().right,
      commandWidth: command.getBoundingClientRect().width,
    };
  });

  expect(wideGeometry.statusValueWidth).toBeGreaterThan(0);
  expect(wideGeometry.statusValueClipped).toBe(false);
  expect(wideGeometry.statusMetaDisplay).not.toBe('none');
  expect(wideGeometry.marketAccessibleName).not.toContain('检查中');
  expect(wideGeometry.marketCommandGap).toBeGreaterThanOrEqual(12);
  expect(wideGeometry.commandWidth).toBe(240);

  const valuationStatus = page.getByTestId('status-pill-valuation');
  await valuationStatus.hover();
  await expect(page.getByText('查看估值详情', { exact: true })).toBeVisible();
  await valuationStatus.focus();
  await expect(valuationStatus).toBeFocused();
  await valuationStatus.click();
  const valuationDialog = page.getByRole('dialog', { name: '净值' });
  await expect(valuationDialog).toBeVisible();
  await expect(page.getByText('查看估值详情', { exact: true })).toHaveCount(0);
  await expect
    .poll(() =>
      valuationStatus.evaluate((element) => {
        const style = getComputedStyle(element);
        const statusShell = element.closest('.app-status-chip') as HTMLElement;
        const toolbar = element.closest('.app-toolbar-shell') as HTMLElement;
        const selectedTheme = document.querySelector(
          '.app-theme-switcher-option[aria-pressed="true"]',
        ) as HTMLElement;
        return {
          backgroundMatches:
            style.backgroundColor ===
            getComputedStyle(selectedTheme).backgroundColor,
          dividerMatches:
            getComputedStyle(statusShell).borderRightColor ===
            getComputedStyle(toolbar).borderBottomColor,
        };
      }),
    )
    .toEqual({ backgroundMatches: true, dividerMatches: true });

  const overlayGeometry = await page.evaluate(() => {
    const content = document.querySelector('.app-shell-content') as HTMLElement;
    const header = document.querySelector('.app-toolbar-shell') as HTMLElement;
    const trigger = document.querySelector(
      '[data-testid="status-pill-valuation"]',
    ) as HTMLElement;
    const popover = document.querySelector(
      '.app-status-popover-root',
    ) as HTMLElement;
    const contentBox = content.getBoundingClientRect();
    const headerBox = header.getBoundingClientRect();
    const triggerBox = trigger.getBoundingClientRect();
    const popoverBox = popover.getBoundingClientRect();
    return {
      contentTop: contentBox.top,
      contentBottom: contentBox.bottom,
      headerBottom: headerBox.bottom,
      popoverTop: popoverBox.top,
      popoverLeft: popoverBox.left,
      popoverRight: popoverBox.right,
      triggerLeft: triggerBox.left,
      triggerBottom: triggerBox.bottom,
      viewportHeight: window.innerHeight,
      viewportWidth: window.innerWidth,
    };
  });
  expect(
    Math.abs(overlayGeometry.headerBottom - overlayGeometry.contentTop),
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(overlayGeometry.viewportHeight - overlayGeometry.contentBottom),
  ).toBeLessThanOrEqual(1);
  expect(
    overlayGeometry.popoverTop - overlayGeometry.triggerBottom,
  ).toBeGreaterThanOrEqual(8);
  expect(
    overlayGeometry.viewportWidth - overlayGeometry.popoverRight,
  ).toBeGreaterThanOrEqual(12);
  expect(
    Math.abs(overlayGeometry.popoverLeft - overlayGeometry.triggerLeft),
  ).toBeLessThanOrEqual(1);

  await page.keyboard.press('Escape');
  await expect(valuationDialog).toHaveCount(0);
  await expect(valuationStatus).toBeFocused();

  await valuationStatus.click();
  await expect(valuationDialog).toBeVisible();
  await page.getByRole('heading', { name: '当前持仓' }).click();
  await expect(valuationDialog).toHaveCount(0);

  const marketStatus = page.getByTestId('status-pill-market');
  await marketStatus.click();
  const marketDialog = page.getByRole('dialog', { name: '行情' });
  await expect(marketDialog).toBeVisible();
  await expect(
    marketDialog.getByText('上次状态检查', { exact: true }),
  ).toBeVisible();
  const marketOverlayGeometry = await marketDialog.evaluate((dialog) => {
    const trigger = document.querySelector(
      '[data-testid="status-pill-market"]',
    ) as HTMLElement;
    const popover = dialog.closest('.app-status-popover-root') as HTMLElement;
    const triggerBox = trigger.getBoundingClientRect();
    const popoverBox = popover.getBoundingClientRect();
    return {
      popoverLeft: popoverBox.left,
      triggerLeft: triggerBox.left,
    };
  });
  expect(
    Math.abs(
      marketOverlayGeometry.popoverLeft - marketOverlayGeometry.triggerLeft,
    ),
  ).toBeLessThanOrEqual(1);

  await page.keyboard.press('Escape');
  await expect(
    valuationStatus.locator('[data-status-chip-part="meta"]'),
  ).toBeVisible();
});

test('shell remains local-overflow safe in Latte and Mocha across tablet and mobile', async ({
  page,
}) => {
  test.setTimeout(60_000);
  for (const theme of ['light', 'dark']) {
    for (const viewport of [
      { width: 1024, height: 768 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto('/overview');
      const themeName = theme === 'light' ? 'Light theme' : 'Dark theme';
      if (viewport.width < 640) {
        await page.getByTestId('mobile-preferences-toggle').click();
        const themeButton = page
          .getByRole('dialog', { name: 'Theme · Language' })
          .getByRole('button', { name: themeName });
        expect(
          Math.round((await themeButton.boundingBox())?.height ?? 0),
        ).toBeGreaterThanOrEqual(44);
        await themeButton.click();
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
      await expect(
        page.getByRole('navigation', { name: 'Navigation', exact: true }),
      ).toBeHidden();
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
        .getByRole('button', { name: 'Close navigation', exact: true })
        .click();
      await expect(
        page.getByRole('navigation', { name: 'Navigation', exact: true }),
      ).toBeHidden();
      await expect(toggle).toBeFocused();
    }
  }
});
