import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const pages = [
  '/glyphpact/',
  '/glyphpact/stable-codepoints/',
  '/glyphpact/flutter/',
  '/glyphpact/mcp/',
  '/glyphpact/vs/icomoon/',
  '/glyphpact/vs/fluttericon/',
  '/glyphpact/404.html',
] as const;

const viewports = [
  { name: 'compact', width: 320, height: 844 },
  { name: 'mobile', width: 375, height: 844 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'desktop', width: 1440, height: 900 },
] as const;

for (const viewport of viewports) {
  test.describe(viewport.name, () => {
    test.use({ viewport });

    for (const route of pages) {
      test(`${route} stays inside the viewport`, async ({ page }) => {
        await page.goto(route);
        await expect(page.locator('main')).toBeVisible();

        await expect
          .poll(() =>
            page.evaluate(
              () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
            ),
          )
          .toBe(0);
      });
    }
  });
}

for (const colorScheme of ['dark', 'light'] as const) {
  test(`homepage has no detectable accessibility violations in ${colorScheme} mode`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
    await page.goto('/glyphpact/');

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();

    expect(results.violations).toEqual([]);
  });
}

test('public install guidance uses PyPI and pins only CI', async ({ page }) => {
  await page.goto('/glyphpact/');
  await expect(page.locator('.gp-install__cmd code').first()).toHaveText(
    'uv tool install glyphpact',
  );

  await page.goto('/glyphpact/flutter/');
  await expect(page.locator('body')).toContainText('uv tool install glyphpact==1.0.1');
  await expect(page.locator('body')).not.toContainText('uv tool install git+');
});

test('machine-readable release facts match v1.0.1', async ({ page }) => {
  await page.goto('/glyphpact/llms.txt');
  await expect(page.locator('body')).toContainText('Current release: v1.0.1');
  await expect(page.locator('body')).toContainText('uv tool install glyphpact');
  await expect(page.locator('body')).not.toContainText('uv tool install git+');

  await page.goto('/glyphpact/');
  const schemas = await page
    .locator('script[type="application/ld+json"]')
    .evaluateAll((nodes) => nodes.map((node) => JSON.parse(node.textContent ?? '{}')));
  expect(JSON.stringify(schemas)).toContain('"softwareVersion":"1.0.1"');
});

test('donation link is explicit without an embedded solicitation', async ({ page }) => {
  const supportUrl = 'https://buymeacoffee.com/omar.hanafy';
  await page.goto('/glyphpact/');

  const headerSupport = page
    .locator('.gp-header')
    .getByRole('link', { name: 'Buy me a coffee', exact: true });
  const footerSupport = page
    .locator('.gp-footer')
    .getByRole('link', { name: 'Buy me a coffee', exact: true });
  await expect(headerSupport).toHaveAttribute('href', supportUrl);
  await expect(footerSupport).toHaveAttribute('href', supportUrl);
  // Desktop and mobile navigation both exist in the DOM; only one is visible.
  await expect(page.locator(`a[href="${supportUrl}"]`)).toHaveCount(3);
  await expect(
    page.locator(
      'script[src*="buymeacoffee"], iframe[src*="buymeacoffee"], img[src*="buymeacoffee"]',
    ),
  ).toHaveCount(0);
});

test('donation link remains visible in the mobile menu', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 844 });
  await page.goto('/glyphpact/');
  await page.locator('.gp-mobile-nav summary').click();

  const support = page
    .locator('.gp-mobile-nav__panel')
    .getByRole('link', { name: 'Buy me a coffee', exact: true });
  await expect(support).toBeVisible();
  await expect(support).toHaveAttribute('href', 'https://buymeacoffee.com/omar.hanafy');
});

test('MCP tab opens the first-class guide and marks the current route', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/glyphpact/');

  const desktopTab = page
    .locator('.gp-nav--desktop')
    .getByRole('link', { name: 'MCP', exact: true });
  await expect(desktopTab).toHaveAttribute('href', '/glyphpact/mcp/');
  await expect(desktopTab).not.toHaveAttribute('aria-current', 'page');

  await page.goto('/glyphpact/mcp/');
  await expect(desktopTab).toHaveAttribute('aria-current', 'page');

  await page.setViewportSize({ width: 375, height: 844 });
  await page.locator('.gp-mobile-nav summary').click();
  const mobileTab = page
    .locator('.gp-mobile-nav__panel')
    .getByRole('link', { name: 'MCP', exact: true });
  await expect(mobileTab).toBeVisible();
  await expect(mobileTab).toHaveAttribute('href', '/glyphpact/mcp/');
  await expect(mobileTab).toHaveAttribute('aria-current', 'page');
});

test('four-card homepage grids form balanced rows', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/glyphpact/');

  for (const selector of [
    'section[aria-labelledby="agents-heading"] .gp-cell',
    '.gp-next a',
  ]) {
    const cards = page.locator(selector);
    await expect(cards).toHaveCount(4);
    const boxes = await cards.evaluateAll((nodes) =>
      nodes.map((node) => {
        const box = node.getBoundingClientRect();
        return { x: box.x, y: box.y, width: box.width };
      }),
    );

    expect(boxes[0].y).toBe(boxes[1].y);
    expect(boxes[2].y).toBe(boxes[3].y);
    expect(boxes[2].y).toBeGreaterThan(boxes[0].y);
    expect(boxes[0].x).toBe(boxes[2].x);
    expect(boxes[1].x).toBe(boxes[3].x);
    expect(boxes[0].width).toBe(boxes[3].width);
  }
});

test('secondary heroes balance the decision copy and workflow proof', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const route of [
    '/glyphpact/flutter/',
    '/glyphpact/mcp/',
    '/glyphpact/vs/icomoon/',
    '/glyphpact/vs/fluttericon/',
  ]) {
    await page.goto(route);

    const copy = await page.locator('.gp-secondary-hero__body').boundingBox();
    const diagram = await page.locator('.gp-secondary-hero .gp-signal').boundingBox();

    expect(copy).not.toBeNull();
    expect(diagram).not.toBeNull();
    expect(copy!.width).toBeGreaterThan(300);
    expect(diagram!.width).toBeGreaterThan(430);
    expect(diagram!.x).toBeGreaterThan(copy!.x + copy!.width);
  }
});

test('comparison workflow lanes remain readable at desktop width', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const route of ['/glyphpact/vs/icomoon/', '/glyphpact/vs/fluttericon/']) {
    await page.goto(route);
    const lanes = page.locator('.gp-secondary-hero .gp-signal__lane');
    await expect(lanes).toHaveCount(2);

    for (const lane of await lanes.all()) {
      const nodes = await lane.locator('li').evaluateAll((elements) =>
        elements.map((element) => {
          const box = element.getBoundingClientRect();
          return { x: box.x, y: box.y, width: box.width };
        }),
      );

      expect(nodes).toHaveLength(3);
      expect(nodes[0].x).toBe(nodes[1].x);
      expect(nodes[1].x).toBe(nodes[2].x);
      expect(nodes[0].width).toBe(nodes[2].width);
      expect(nodes[1].y).toBeGreaterThan(nodes[0].y);
      expect(nodes[2].y).toBeGreaterThan(nodes[1].y);
    }
  }
});

test('Flutter quick start is a two-by-two desktop grid and a mobile sequence', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/glyphpact/flutter/');

  const desktop = await page.locator('.gp-steps--compact > li').evaluateAll((elements) =>
    elements.map((element) => {
      const box = element.getBoundingClientRect();
      return { x: box.x, y: box.y };
    }),
  );

  expect(desktop).toHaveLength(4);
  expect(desktop[0].y).toBe(desktop[1].y);
  expect(desktop[2].y).toBe(desktop[3].y);
  expect(desktop[0].x).toBe(desktop[2].x);
  expect(desktop[1].x).toBe(desktop[3].x);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await page.locator('.gp-steps--compact > li').evaluateAll((elements) =>
    elements.map((element) => {
      const box = element.getBoundingClientRect();
      return { x: box.x, y: box.y };
    }),
  );

  expect(new Set(mobile.map(({ x }) => x)).size).toBe(1);
  expect(mobile[1].y).toBeGreaterThan(mobile[0].y);
  expect(mobile[2].y).toBeGreaterThan(mobile[1].y);
  expect(mobile[3].y).toBeGreaterThan(mobile[2].y);
});

test('every table header pins below the navigation and releases at its table boundary', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const { route, count } of [
    { route: '/glyphpact/', count: 3 },
    { route: '/glyphpact/vs/icomoon/', count: 1 },
    { route: '/glyphpact/vs/fluttericon/', count: 1 },
  ]) {
    await page.goto(route);
    const wrappers = page.locator('.gp-table-wrap');
    const pins = page.locator('.gp-table-pin');
    await expect(wrappers).toHaveCount(count);
    await expect(pins).toHaveCount(count);

    for (let index = 0; index < count; index += 1) {
      const wrapper = wrappers.nth(index);
      const pin = pins.nth(index);
      const activationScroll = await wrapper.evaluate((element) => {
        const head = element.querySelector('thead');
        const navigation = document.querySelector('.gp-header');
        if (!head || !navigation) throw new Error('Expected table head and navigation');

        return (
          window.scrollY +
          head.getBoundingClientRect().top -
          navigation.getBoundingClientRect().bottom +
          12
        );
      });

      await page.evaluate((scrollTop) => window.scrollTo(0, scrollTop), activationScroll);
      await expect(pin).toBeVisible();

      const pinnedGeometry = await pin.evaluate((element) => ({
        top: element.getBoundingClientRect().top,
        hidden: (element as HTMLElement).hidden,
      }));
      const navigationBottom = await page
        .locator('.gp-header')
        .evaluate((element) => element.getBoundingClientRect().bottom);

      expect(pinnedGeometry.hidden).toBe(false);
      expect(Math.abs(pinnedGeometry.top - navigationBottom)).toBeLessThan(1);

      const releaseScroll = await wrapper.evaluate(
        (element) => window.scrollY + element.getBoundingClientRect().bottom + 1,
      );
      await page.evaluate((scrollTop) => window.scrollTo(0, scrollTop), releaseScroll);
      await expect(pin).toBeHidden();
    }
  }
});

test('a pinned mobile table header stays aligned while the table scrolls horizontally', async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 844 });
  await page.goto('/glyphpact/vs/fluttericon/');

  const wrapper = page.locator('.gp-table-wrap');
  const pin = page.locator('.gp-table-pin');
  await wrapper.evaluate((element) => {
    element.scrollLeft = 180;
  });

  const activationScroll = await wrapper.evaluate((element) => {
    const head = element.querySelector('thead');
    const navigation = document.querySelector('.gp-header');
    if (!head || !navigation) throw new Error('Expected table head and navigation');

    return (
      window.scrollY +
      head.getBoundingClientRect().top -
      navigation.getBoundingClientRect().bottom +
      12
    );
  });
  await page.evaluate((scrollTop) => window.scrollTo(0, scrollTop), activationScroll);
  await expect(pin).toBeVisible();

  const alignment = await page.evaluate(() => {
    const sourceCells = Array.from(
      document.querySelectorAll('.gp-table-wrap thead tr:first-child > *'),
    );
    const pinnedCells = Array.from(
      document.querySelectorAll('.gp-table-pin thead tr:first-child > *'),
    );

    return sourceCells.map((source, index) => {
      const sourceRect = source.getBoundingClientRect();
      const pinnedRect = pinnedCells[index]?.getBoundingClientRect();
      return {
        x: Math.abs(sourceRect.x - (pinnedRect?.x ?? 0)),
        width: Math.abs(sourceRect.width - (pinnedRect?.width ?? 0)),
      };
    });
  });

  expect(alignment.length).toBeGreaterThan(1);
  for (const delta of alignment) {
    expect(delta.x).toBeLessThan(1);
    expect(delta.width).toBeLessThan(1);
  }
});

for (const colorScheme of ['dark', 'light'] as const) {
  test(`secondary pages have no detectable accessibility violations in ${colorScheme} mode`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });

    for (const route of [
      '/glyphpact/flutter/',
      '/glyphpact/mcp/',
      '/glyphpact/vs/icomoon/',
      '/glyphpact/vs/fluttericon/',
    ]) {
      await page.goto(route);
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze();

      expect(results.violations, route).toEqual([]);
    }
  });
}
