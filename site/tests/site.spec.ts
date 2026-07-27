import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const pages = [
  '/glyphpact/',
  '/glyphpact/bulk-svg-to-flutter-icons/',
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

test('bulk guide owns folder conversion, automation, and capacity intent', async ({ page }) => {
  await page.goto('/glyphpact/bulk-svg-to-flutter-icons/');

  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Convert a folder of SVGs to Flutter icons',
  );
  const body = page.locator('body');
  await expect(body).toContainText('Discovery is recursive');
  await expect(body).toContainText('const Flutter IconData');
  await expect(body).toContainText('Fail CI on stale output');
  await expect(body).toContainText('audit_icon_pack');
  await expect(body).toContainText('65,534 usable glyphs');
  await expect(body).toContainText('sharded into independently named and versioned fonts');
  await expect(body).toContainText('Fontello provides a browser catalogue');

  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    'href',
    'https://omar-hanafy.github.io/glyphpact/bulk-svg-to-flutter-icons/',
  );
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
    'content',
    'https://omar-hanafy.github.io/glyphpact/og/bulk.png',
  );
});

test('all workflow guides link to the bulk SVG page', async ({ page }) => {
  const href = '/glyphpact/bulk-svg-to-flutter-icons/';
  for (const route of [
    '/glyphpact/',
    '/glyphpact/flutter/',
    '/glyphpact/mcp/',
    '/glyphpact/stable-codepoints/',
    '/glyphpact/vs/icomoon/',
    '/glyphpact/vs/fluttericon/',
  ]) {
    await page.goto(route);
    await expect(page.locator(`main a[href="${href}"]`).first(), route).toBeVisible();
  }
});

test('stable codepoint guide covers repeated Figma batches without replacing its proof', async ({
  page,
}) => {
  await page.goto('/glyphpact/stable-codepoints/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Add Flutter icons without changing existing codepoints',
  );
  const growth = page.locator('.gp-codepoint-growth');
  await expect(growth).toContainText('3');
  await expect(growth).toContainText('5');
  await expect(growth).toContainText('10');
  await expect(growth).toContainText('100');
  await expect(page.locator('body')).toContainText(
    'The verified lock diff later on this page remains a smaller two-to-six fixture',
  );
});

test('FlutterIcon comparison publishes the dated even-odd reproduction', async ({ page }) => {
  await page.goto('/glyphpact/vs/fluttericon/');

  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'A FlutterIcon.com alternative for repeatable Flutter icon builds',
  );
  await expect(page.locator('body')).toContainText(
    'If image looks not as expected please convert to compound path manually',
  );
  await expect(page.locator('body')).toContainText('Skipped tags and attributes: ...');
  await expect(page.locator('body')).toContainText('Hole lost');
  await expect(page.locator('body')).toContainText('Dot lost');
  await expect(page.locator('body')).toContainText('Cutout lost');
  await expect(page.locator('body')).toContainText('Flutter 3.44.4 and Dart 3.12.2');
  await expect(page.locator('body')).toContainText('Version 1.0.1');

  const cover = page.locator('.gp-comparison-cover img');
  await expect(cover).toHaveAttribute('width', '1000');
  await expect(cover).toHaveAttribute('height', '420');
  await expect(cover).toHaveAttribute(
    'alt',
    'The same location, chat, and mail glyphs with geometry lost in FlutterIcon.com and preserved by GlyphPact',
  );
  await expect(cover).toHaveAttribute(
    'src',
    '/glyphpact/images/comparisons/fluttericon-glyphpact-cover-2x.png',
  );

  const table = page.getByRole('table', {
    name: /exact source SVG, FlutterIcon TTF glyph, and GlyphPact OTF\/CFF glyph/,
  });
  await expect(table.getByRole('columnheader')).toHaveCount(4);
  await expect(table.getByRole('rowheader')).toHaveCount(3);
  await expect(table.locator('tbody > tr')).toHaveCount(3);

  const sourceImages = table.locator('.gp-render-cell--source img');
  await expect(sourceImages).toHaveCount(3);
  await expect(sourceImages.nth(0)).toHaveAttribute(
    'alt',
    'Original Location Bold SVG with a centre hole',
  );
  await expect(sourceImages.nth(1)).toHaveAttribute(
    'alt',
    'Original Chat Bold SVG with three dots',
  );
  await expect(sourceImages.nth(2)).toHaveAttribute(
    'alt',
    'Original Mail Bold SVG with an envelope cutout',
  );
  await expect(table.locator('.gp-evidence-glyph--fluttericon')).toHaveCount(3);
  await expect(table.locator('.gp-evidence-glyph--glyphpact')).toHaveCount(3);

  const loadedFonts = await page.evaluate(async () => {
    const [flutterIconFaces, glyphPactFaces] = await Promise.all([
      document.fonts.load('72px "FlutterIconEvidence"', '\ue805'),
      document.fonts.load('72px "GlyphPactEvidence"', '\ue001'),
    ]);
    await document.fonts.ready;

    return {
      flutterIconFaces: flutterIconFaces.length,
      glyphPactFaces: glyphPactFaces.length,
      flutterIconReady: document.fonts.check('72px "FlutterIconEvidence"', '\ue805'),
      glyphPactReady: document.fonts.check('72px "GlyphPactEvidence"', '\ue001'),
    };
  });
  expect(loadedFonts).toEqual({
    flutterIconFaces: 1,
    glyphPactFaces: 1,
    flutterIconReady: true,
    glyphPactReady: true,
  });

  const goldenReference = page.locator('.gp-golden-reference');
  await goldenReference.locator('summary').click();
  const golden = goldenReference.locator('img');
  await expect(golden).toBeVisible();
  await expect(golden).toHaveAttribute('width', '800');
  await expect(golden).toHaveAttribute('height', '640');
  await expect(golden).toHaveAttribute(
    'src',
    '/glyphpact/images/comparisons/fluttericon-glyphpact-table-2x.png',
  );
  await expect(goldenReference.getByRole('link', { name: 'public fixture' })).toHaveAttribute(
    'href',
    'https://github.com/omar-hanafy/glyphpact/tree/main/examples/fluttericon-evenodd-comparison',
  );
  await expect(goldenReference.getByRole('link', { name: 'full app capture' })).toHaveAttribute(
    'href',
    '/glyphpact/images/comparisons/fluttericon-evenodd-comparison.png',
  );
});

test('IcoMoon comparison reflects the current app rather than old selection.json claims', async ({
  page,
}) => {
  await page.goto('/glyphpact/vs/icomoon/');
  const body = page.locator('body');

  await expect(body).toContainText('offline-first progressive web app');
  await expect(body).toContainText('generate a Dart class for Flutter');
  await expect(body).toContainText('icomoon.json');
  await expect(body).toContainText('Replace by Matching Names');
  await expect(body).toContainText('selection.json belongs to the old app');
  await expect(body).not.toContainText('No Dart output');
  await expect(body).not.toContainText('No CLI to run in CI');
});

test('public install guidance uses PyPI and pins only CI', async ({ page }) => {
  await page.goto('/glyphpact/');
  await expect(page.locator('.gp-install__cmd code').first()).toHaveText(
    'uv tool install glyphpact',
  );

  await page.goto('/glyphpact/flutter/');
  await expect(page.locator('body')).toContainText('uv tool install glyphpact==1.1.0');
  await expect(page.locator('body')).not.toContainText('uv tool install git+');
});

test('machine-readable release facts match v1.1.0', async ({ page }) => {
  await page.goto('/glyphpact/llms.txt');
  await expect(page.locator('body')).toContainText('Current release: v1.1.0');
  await expect(page.locator('body')).toContainText('uv tool install glyphpact');
  await expect(page.locator('body')).not.toContainText('uv tool install git+');

  await page.goto('/glyphpact/');
  const reportArtifact = page
    .locator('.gp-tree__row')
    .filter({ hasText: 'iconfont.report.json' });
  await expect(reportArtifact).toContainText('Schema version 3');
  const schemas = await page
    .locator('script[type="application/ld+json"]')
    .evaluateAll((nodes) => nodes.map((node) => JSON.parse(node.textContent ?? '{}')));
  expect(JSON.stringify(schemas)).toContain('"softwareVersion":"1.1.0"');
});

test('Flutter guide exposes catalog reachability and report codegen boundaries', async ({
  page,
}) => {
  await page.goto('/glyphpact/flutter/');
  const body = page.locator('body');
  await expect(body).toContainText('AppIconsCatalog.byName');
  await expect(body).toContainText('when the catalog is unreachable');
  await expect(body).toContainText('Report codepoints are 0x... strings');
  await expect(body).toContainText('codepointsRemaining');
  await expect(body).toContainText('rangeUtilization');
  await expect(body).toContainText('CODEPOINT_RANGE_NEAR_EXHAUSTION');
  await expect(body).toContainText('Write custom generated files elsewhere');
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

test('MCP guide documents the portable server without leaking plugin-cache paths', async ({
  page,
}) => {
  await page.goto('/glyphpact/mcp/');

  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Automate SVG-to-Flutter icon builds with MCP',
  );
  await expect(page.locator('.gp-mcp-client')).toHaveCount(10);
  await expect(page.locator('.gp-mcp-tool')).toHaveCount(4);
  await expect(page.locator('.gp-mcp-resources > div')).toHaveCount(3);

  for (const client of [
    'Antigravity / Agy',
    'Cursor',
    'JetBrains AI Assistant',
    'VS Code / GitHub Copilot',
    'Zed',
    'Windsurf / Devin Desktop',
    'Gemini CLI',
    'Claude Code, manual MCP',
    'Codex, manual MCP',
    'Other stdio MCP clients',
  ]) {
    await expect(page.getByText(client, { exact: true }).first()).toBeVisible();
  }

  const manualCode = await page
    .locator('.gp-mcp-clients pre')
    .evaluateAll((nodes) => nodes.map((node) => node.textContent ?? '').join('\n'));
  expect(manualCode).toContain('glyphpact[mcp]==1.1.0');
  expect(manualCode).toContain('"type": "stdio"');
  expect(manualCode).toContain('"servers"');
  expect(manualCode).toContain('"context_servers"');
  expect(manualCode).toContain('[mcp_servers.glyphpact]');
  expect(manualCode).not.toContain('CLAUDE_PLUGIN_ROOT');
});

test('MCP client anchors open the requested native configuration', async ({ page }) => {
  await page.goto('/glyphpact/mcp/#client-vscode');

  const vscode = page.locator('#client-vscode');
  await expect(vscode).toHaveAttribute('open', '');
  await expect(vscode.locator('pre')).toContainText('"servers"');

  await page
    .locator('.gp-mcp-clients__jump')
    .getByRole('link', { name: 'Cursor', exact: true })
    .click();
  const cursor = page.locator('#client-cursor');
  await expect(cursor).toHaveAttribute('open', '');
  await expect(cursor.locator('pre')).toContainText('"type": "stdio"');
  await expect(page).toHaveURL(/#client-cursor$/);
});

test('every JSON client uses the same pinned GlyphPact stdio launcher', async ({ page }) => {
  await page.goto('/glyphpact/mcp/');

  const expectedArgs = [
    'tool',
    'run',
    '--quiet',
    '--no-progress',
    '--color',
    'never',
    '--no-config',
    '--isolated',
    '--from',
    'glyphpact[mcp]==1.1.0',
    'glyphpact-mcp',
  ];

  for (const { id, root } of [
    { id: 'antigravity', root: 'mcpServers' },
    { id: 'cursor', root: 'mcpServers' },
    { id: 'jetbrains', root: 'mcpServers' },
    { id: 'vscode', root: 'servers' },
    { id: 'zed', root: 'context_servers' },
    { id: 'windsurf', root: 'mcpServers' },
    { id: 'gemini-cli', root: 'mcpServers' },
    { id: 'generic', root: 'mcpServers' },
  ]) {
    const raw = await page.locator(`#client-${id} pre`).textContent();
    const parsed = JSON.parse(raw ?? '{}');
    expect(parsed[root].glyphpact.command, id).toBe('uv');
    expect(parsed[root].glyphpact.args, id).toEqual(expectedArgs);
  }
});

test('MCP install modes keep the plugin and manual server boundaries distinct', async ({
  page,
}) => {
  await page.goto('/glyphpact/mcp/');

  const install = page.locator('#install');
  await expect(install.getByRole('heading', { name: 'Full plugin', exact: true })).toBeVisible();
  await expect(
    install.getByRole('heading', { name: 'MCP server only', exact: true }),
  ).toBeVisible();
  await expect(install).toContainText('sync-flutter-svg-icons');
  await expect(install).toContainText('Version pinned until you update the entry');
  await expect(install).toContainText('Do not add a second manual GlyphPact MCP entry');
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
    '/glyphpact/bulk-svg-to-flutter-icons/',
    '/glyphpact/flutter/',
    '/glyphpact/vs/icomoon/',
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

test('FlutterIcon hero balances its decision copy and comparison cover', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/glyphpact/vs/fluttericon/');

  const copy = await page.locator('.gp-secondary-hero__body').boundingBox();
  const cover = await page.locator('.gp-secondary-hero .gp-comparison-cover').boundingBox();
  const image = await page.locator('.gp-secondary-hero .gp-comparison-cover img').boundingBox();

  expect(copy).not.toBeNull();
  expect(cover).not.toBeNull();
  expect(image).not.toBeNull();
  expect(copy!.width).toBeGreaterThan(300);
  expect(cover!.width).toBeGreaterThan(430);
  expect(cover!.x).toBeGreaterThan(copy!.x + copy!.width);
  expect(image!.width / image!.height).toBeCloseTo(1000 / 420, 2);
});

test('MCP hero balances its decision copy and local process map', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/glyphpact/mcp/');

  const copy = await page.locator('.gp-secondary-hero__body').boundingBox();
  const route = await page.locator('.gp-secondary-hero .gp-mcp-route').boundingBox();

  expect(copy).not.toBeNull();
  expect(route).not.toBeNull();
  expect(copy!.width).toBeGreaterThan(300);
  expect(route!.width).toBeGreaterThan(430);
  expect(route!.x).toBeGreaterThan(copy!.x + copy!.width);
});

test('IcoMoon comparison workflow lanes remain readable at desktop width', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/glyphpact/vs/icomoon/');
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
      '/glyphpact/bulk-svg-to-flutter-icons/',
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
