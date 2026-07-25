import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const pages = [
  '/glyphpact/',
  '/glyphpact/stable-codepoints/',
  '/glyphpact/flutter/',
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
