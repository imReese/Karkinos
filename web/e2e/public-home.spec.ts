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

test('public home presents the brand contract before entering the workbench', async ({
  page,
}) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) {
      apiRequests.push(request.url());
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

  const composition = await page.evaluate(() => {
    const evidenceTop = Math.round(
      document
        .querySelector('.app-public-evidence-frame')
        ?.getBoundingClientRect().top ?? 0,
    );
    return {
      evidenceTop,
      sectionTops: ['product', 'principles', 'workflow'].map((id) =>
        Math.round(
          document.getElementById(id)?.getBoundingClientRect().top ?? 0,
        ),
      ),
      verticalOverflow:
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight,
    };
  });
  expect(composition.evidenceTop).toBeLessThan(500);
  expect(composition.verticalOverflow).toBeGreaterThan(0);
  expect(composition.sectionTops[0]).toBeGreaterThan(800);
  expect(composition.sectionTops[1]).toBeGreaterThan(
    composition.sectionTops[0] ?? 0,
  );
  expect(composition.sectionTops[2]).toBeGreaterThan(
    composition.sectionTops[1] ?? 0,
  );

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
  await expect(
    page.getByRole('link', { name: 'Open surface: Account Truth' }),
  ).toHaveAttribute('href', '/account-truth');
  await publicNavigation.getByRole('link', { name: 'Trust' }).click();
  await expect(page).toHaveURL(/#principles$/);
  await expect(page.locator('#principles')).toBeVisible();
  await publicNavigation.getByRole('link', { name: 'Workflow' }).click();
  await expect(page).toHaveURL(/#workflow$/);
  await expect(page.locator('#workflow')).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight,
    ),
  ).toBeGreaterThan(0);

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
      name: '让每一个投资决定，都有证据可回放。',
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
  expect(geometry.evidenceTop).toBeLessThan(700);
  await expect(
    page.getByRole('banner').getByText('工作台', { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator('.app-public-evidence-boundary')
      .getByText('仅查看与复核', { exact: true }),
  ).toBeVisible();
});

test('public home preserves its composition across the seven visual acceptance viewports', async ({
  page,
}) => {
  for (const viewport of publicHomeViewports) {
    await page.setViewportSize(viewport);
    await page.goto('/');

    const latteGeometry = await page.evaluate(() => ({
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      evidenceTop: Math.round(
        document
          .querySelector('.app-public-evidence-frame')
          ?.getBoundingClientRect().top ?? 0,
      ),
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
    expect(latteGeometry.evidenceTop, JSON.stringify(viewport)).toBeLessThan(
      700,
    );
    expect(latteGeometry.visibleSections, JSON.stringify(viewport)).toEqual([
      'product',
      'principles',
      'workflow',
    ]);
    expect(
      latteGeometry.verticalOverflow,
      JSON.stringify(viewport),
    ).toBeGreaterThan(0);
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

test('public home completes the evidence path inside the tablet first viewport', async ({
  page,
}) => {
  await page.setViewportSize({ width: 834, height: 1112 });
  await page.goto('/');

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
  expect(geometry.evidence?.bottom).toBeLessThanOrEqual(1112);
  expect(geometry.hero?.bottom).toBeLessThanOrEqual(1112);
});
