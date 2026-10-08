import { expect, test } from '@playwright/test';

const publicHomeViewports = [
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 834, height: 1112 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
] as const;

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    window.localStorage.setItem('karkinos.locale', 'en');
    window.localStorage.setItem('karkinos.theme', 'light');
  });
});

test('public home presents the brand contract before entering the workbench', async ({
  page,
}) => {
  const apiRequests: string[] = [];
  const workspaceAssetRequests: string[] = [];
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith('/api/')) {
      apiRequests.push(request.url());
    }
    if (
      pathname.includes('/assets/app-shell-') ||
      pathname.includes('/assets/feature-') ||
      pathname.includes('/assets/charts-')
    ) {
      workspaceAssetRequests.push(pathname);
    }
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  await expect(page.locator('h1')).toHaveCount(1);
  await expect(
    page.getByRole('heading', {
      name: 'Every decision should leave evidence.',
    }),
  ).toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Public navigation' }),
  ).toBeVisible();
  await expect(page.locator('.app-shell-frame')).toHaveCount(0);
  await expect(page.getByRole('contentinfo')).toBeVisible();
  expect(apiRequests).toEqual([]);
  expect(workspaceAssetRequests).toEqual([]);

  const composition = await page.evaluate(() => {
    const evidenceTop = Math.round(
      document
        .querySelector('.app-public-evidence-frame')
        ?.getBoundingClientRect().top ?? 0,
    );
    return {
      evidenceTop,
      footerBottom: document.querySelector('footer')!.getBoundingClientRect()
        .bottom,
      verticalOverflow:
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight,
    };
  });
  expect(composition.evidenceTop).toBeLessThan(500);
  expect(composition.verticalOverflow).toBe(0);
  expect(composition.footerBottom).toBeLessThanOrEqual(900);
  await expect(page.locator('#product')).toBeVisible();
  await expect(page.locator('#principles')).toBeHidden();
  await expect(page.locator('#workflow')).toBeHidden();

  await expect(
    page.getByLabel('Public-to-private route').getByText('/overview'),
  ).toBeVisible();
  await expect(page.getByLabel('Workbench structure')).toBeVisible();
  await expect(
    page.getByRole('heading', {
      name: 'Resolve the highest blocker first.',
    }),
  ).toBeVisible();
  await expect(page.getByText('Read and review only')).toBeVisible();
  const publicNavigation = page.getByRole('navigation', {
    name: 'Public navigation',
  });
  await publicNavigation.getByRole('link', { name: 'Product' }).click();
  await expect(page).toHaveURL(/#product$/);
  await expect(page.locator('#product')).toBeVisible();
  expect(
    await page
      .locator('#product')
      .evaluate((element) => Math.round(element.getBoundingClientRect().top)),
  ).toBeGreaterThanOrEqual(56);
  await expect(page.locator('#product')).toBeFocused();
  await expect(
    publicNavigation.getByRole('link', { name: 'Product' }),
  ).toHaveAttribute('aria-current', 'location');
  await expect(page.locator('.app-public-hero')).toBeHidden();
  await expect(
    page.getByRole('link', { name: 'Open surface: Account Truth' }),
  ).toHaveAttribute('href', '/account-truth');
  await publicNavigation.getByRole('link', { name: 'Trust' }).click();
  await expect(page).toHaveURL(/#principles$/);
  await expect(page.locator('#principles')).toBeVisible();
  await expect(page.locator('#principles')).toBeFocused();
  await expect(page.locator('#product')).toBeHidden();
  await publicNavigation.getByRole('link', { name: 'Workflow' }).click();
  await expect(page).toHaveURL(/#workflow$/);
  await expect(page.locator('#workflow')).toBeVisible();
  await expect(page.locator('#workflow')).toBeFocused();
  await expect(page.locator('#principles')).toBeHidden();
  await page.goBack();
  await expect(page).toHaveURL(/#principles$/);
  await expect(page.locator('#principles')).toBeVisible();
  await expect(page.locator('#principles')).toBeFocused();
  await page
    .getByRole('banner')
    .getByRole('link', { name: 'Karkinos home' })
    .click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('.app-public-hero')).toBeVisible();

  const documentOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(documentOverflow).toBeLessThanOrEqual(0);

  await page
    .getByRole('banner')
    .getByRole('link', { name: 'Open private workbench' })
    .click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.locator('.app-shell-frame')).toBeVisible();
  await expect(page.getByRole('contentinfo')).toHaveCount(0);
});

test('public home remains localized, themeable, and overflow safe on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');

  await page.getByRole('button', { name: 'Switch to Mocha theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: 'Switch to Chinese' }).click();
  await expect(
    page.getByRole('heading', {
      name: /^让每一个投资决定，\s*都有证据可回放。$/,
    }),
  ).toBeVisible();

  const geometry = await page.evaluate(() => ({
    documentOverflow:
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
    controls: Array.from(
      document.querySelectorAll<HTMLElement>(
        '.app-public-header button, .app-public-header a[href]',
      ),
    )
      .map((element) => ({
        height: element.getBoundingClientRect().height,
        width: element.getBoundingClientRect().width,
      }))
      .filter((control) => control.height > 0 && control.width > 0),
    evidenceTop: Math.round(
      document
        .querySelector('.app-public-evidence-frame')
        ?.getBoundingClientRect().top ?? 0,
    ),
  }));
  expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
  expect(geometry.controls.every((control) => control.height >= 36)).toBe(true);
  expect(geometry.evidenceTop).toBeLessThan(844);
  await expect(
    page.getByRole('banner').getByText('工作台', { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator('.app-public-evidence-boundary')
      .getByText('仅查看与复核', { exact: true }),
  ).toBeVisible();
  const productRail = page.getByRole('list', { name: '产品证明' });
  await productRail.focus();
  await productRail.press('ArrowRight');
  await expect
    .poll(() => productRail.evaluate((element) => element.scrollLeft))
    .toBeGreaterThan(0);
  await productRail.press('ArrowLeft');
  await expect
    .poll(() => productRail.evaluate((element) => element.scrollLeft))
    .toBe(0);
});

test('public home preserves its composition across the seven visual acceptance viewports', async ({
  page,
}) => {
  for (const viewport of publicHomeViewports) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await expect(page.locator('.app-public-hero')).toBeVisible();

    const latteGeometry = await page.evaluate(() => ({
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      evidenceTop: Math.round(
        document
          .querySelector('.app-public-evidence-frame')
          ?.getBoundingClientRect().top ?? 0,
      ),
      heroActionBottom: document
        .querySelector('.app-public-hero-actions .app-public-primary-cta')!
        .getBoundingClientRect().bottom,
      sectionIndexBottom: document
        .querySelector('.app-public-section-index')!
        .getBoundingClientRect().bottom,
      unexpectedOverflow: Array.from(
        document.querySelectorAll<HTMLElement>(
          '.app-public-header, .app-public-hero, .app-public-evidence-frame, .app-public-footer',
        ),
      )
        .map((element) => ({
          className: element.className,
          overflow: element.scrollWidth - element.clientWidth,
        }))
        .filter(({ overflow }) => overflow > 0),
      localOverflow: Array.from(
        document.querySelectorAll<HTMLElement>(
          '[data-local-overflow^="public-"]',
        ),
      )
        .map((element) => ({
          name: element.dataset.localOverflow,
          overflow: element.scrollWidth - element.clientWidth,
          overflowX: getComputedStyle(element).overflowX,
          tabIndex: element.tabIndex,
        }))
        .filter(({ overflow }) => overflow > 0),
      verticalOverflow:
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight,
      visibleSections: ['product', 'principles', 'workflow'].filter((id) => {
        const section = document.getElementById(id);
        return Boolean(section && section.getBoundingClientRect().height > 0);
      }),
    }));
    expect(latteGeometry.documentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(latteGeometry.unexpectedOverflow, JSON.stringify(viewport)).toEqual(
      [],
    );
    expect(
      latteGeometry.localOverflow.map(({ name }) => name),
      JSON.stringify(viewport),
    ).toEqual(
      viewport.width < 720
        ? ['public-product-proof', 'public-principles', 'public-workflow']
        : [],
    );
    for (const localOverflow of latteGeometry.localOverflow) {
      expect(localOverflow.overflowX, localOverflow.name).toBe('auto');
      expect(localOverflow.tabIndex, localOverflow.name).toBe(0);
    }
    expect(
      latteGeometry.heroActionBottom,
      JSON.stringify(viewport),
    ).toBeLessThanOrEqual(viewport.height);
    if (viewport.width >= 1024) {
      expect(latteGeometry.evidenceTop, JSON.stringify(viewport)).toBeLessThan(
        viewport.height,
      );
    } else {
      const evidenceGap =
        latteGeometry.evidenceTop - latteGeometry.sectionIndexBottom;
      expect(evidenceGap, JSON.stringify(viewport)).toBeGreaterThanOrEqual(0);
      expect(evidenceGap, JSON.stringify(viewport)).toBeLessThanOrEqual(44);
      const boundary = page.locator('.app-public-evidence-boundary');
      await boundary.scrollIntoViewIfNeeded();
      await expect(boundary).toBeVisible();
      const boundaryBounds = (await boundary.boundingBox())!;
      expect(
        boundaryBounds.y + boundaryBounds.height,
        JSON.stringify(viewport),
      ).toBeLessThanOrEqual(viewport.height);
    }
    expect(latteGeometry.visibleSections, JSON.stringify(viewport)).toEqual(
      viewport.width >= 1024
        ? viewport.height >= 860
          ? ['product']
          : []
        : ['product', 'principles', 'workflow'],
    );
    if (viewport.width >= 1024) {
      expect(latteGeometry.verticalOverflow, JSON.stringify(viewport)).toBe(0);
      const navigation = page.getByRole('navigation', {
        name: 'Public navigation',
      });
      for (const [name, id] of [
        ['Product', 'product'],
        ['Trust', 'principles'],
        ['Workflow', 'workflow'],
      ] as const) {
        const navigationLink = navigation.getByRole('link', {
          name,
          exact: true,
        });
        await navigationLink.press('Enter');
        await expect(page).toHaveURL(new RegExp(`#${id}$`));
        const panel = page.locator(`#${id}`);
        await expect(panel).toBeVisible();
        await expect(panel).toBeFocused();
        await expect(
          navigation.getByRole('link', { name, exact: true }),
        ).toHaveAttribute('aria-current', 'location');
        const panelBounds = await panel.boundingBox();
        const footerBounds = await page.getByRole('contentinfo').boundingBox();
        expect(
          panelBounds!.y,
          `${id} ${JSON.stringify(viewport)}`,
        ).toBeGreaterThanOrEqual(56);
        expect(
          panelBounds!.y + panelBounds!.height,
          `${id} ${JSON.stringify(viewport)}`,
        ).toBeLessThanOrEqual(footerBounds!.y + 1);
      }
    } else {
      expect(
        latteGeometry.verticalOverflow,
        JSON.stringify(viewport),
      ).toBeGreaterThan(0);
    }
    await expect(
      page
        .getByRole('banner')
        .getByRole('link', { name: 'Open private workbench' }),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Switch to Mocha theme' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
      JSON.stringify(viewport),
    ).toBe(0);
    await page.getByRole('button', { name: 'Switch to Latte theme' }).click();
  }
});

test('public home keeps tablet evidence aligned and fully reachable by scrolling', async ({
  page,
}) => {
  await page.setViewportSize({ width: 834, height: 1112 });
  await page.goto('/');
  await expect(page.locator('.app-public-hero')).toBeVisible();

  const geometry = await page.evaluate(() => {
    const hero = document.querySelector('.app-public-hero');
    const evidence = document.querySelector('.app-public-evidence-frame');
    const workspace = document.querySelector('.app-public-preview-workspace');
    const priority = document.querySelector('.app-public-priority-preview');
    const flow = document.querySelector('.app-public-evidence-flow');
    const rect = (element: Element | null) => {
      const bounds = element?.getBoundingClientRect();
      return bounds
        ? {
            bottom: Math.round(bounds.bottom),
            height: Math.round(bounds.height),
            top: Math.round(bounds.top),
          }
        : null;
    };

    return {
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      evidence: rect(evidence),
      flow: rect(flow),
      hero: rect(hero),
      priority: rect(priority),
      workspaceColumns: workspace
        ? getComputedStyle(workspace).gridTemplateColumns
        : '',
    };
  });

  expect(geometry.documentOverflow).toBe(0);
  expect(geometry.workspaceColumns.split(' ')).toHaveLength(2);
  expect(geometry.priority?.top).toBe(geometry.flow?.top);
  expect(geometry.priority?.height).toBeLessThanOrEqual(
    geometry.flow?.height ?? 0,
  );
  expect(geometry.evidence?.top).toBeLessThan(1112);
  expect(geometry.evidence?.bottom).toBeLessThanOrEqual(
    geometry.hero?.bottom ?? 0,
  );
  const boundary = page.locator('.app-public-evidence-boundary');
  await boundary.scrollIntoViewIfNeeded();
  await expect(boundary).toBeVisible();
  const boundaryBounds = (await boundary.boundingBox())!;
  expect(boundaryBounds.y).toBeGreaterThanOrEqual(56);
  expect(boundaryBounds.y + boundaryBounds.height).toBeLessThanOrEqual(1112);
  await expect(
    boundary.getByText('Read and review only', { exact: true }),
  ).toBeVisible();
});
