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
    await page.goto('/');

    const sidebar = page.locator('#app-shell-navigation');
    const header = page.locator('.app-toolbar-shell');
    await expect(sidebar).toBeVisible();
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
      await page.goto('/');
      await page.evaluate((nextTheme) => {
        localStorage.setItem('karkinos.theme', nextTheme);
      }, theme);
      await page.reload();

      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      const toggle = page.getByTestId('mobile-navigation-toggle');
      await expect(toggle).toBeVisible();
      await expect(page.locator('#app-shell-navigation')).not.toBeInViewport();
      await toggle.click();
      await expect(
        page.getByRole('navigation', { name: 'Navigation' }),
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
