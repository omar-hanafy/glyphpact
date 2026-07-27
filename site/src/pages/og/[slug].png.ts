import type { APIRoute, GetStaticPaths } from 'astro';
import { renderOg, type OgCard } from '../../lib/og';
import { INSTALL_COMMAND } from '../../site.config';

/**
 * Social preview images, one per indexable page, written as static PNGs at
 * build time. Slugs match the `ogSlug` each page passes to the layout.
 */
const cards: Record<string, OgCard> = {
  index: {
    title: 'Your icon codepoints should never move.',
    subtitle:
      'A deterministic compiler from SVG files to a validated OpenType font, a committed codepoint registry, and a const Flutter IconData API.',
    footnote: INSTALL_COMMAND,
  },
  codepoints: {
    eyebrow: 'Stable codepoints',
    title: 'Add Flutter icons without changing existing codepoints',
    subtitle:
      'A committed registry keeps assignments fixed as Figma deliveries grow from 3 icons to 5, 10, and 100, and tombstones the ones you remove.',
    footnote: 'iconfont.lock.json',
  },
  bulk: {
    eyebrow: 'Bulk SVG to Flutter icons',
    title: 'Compile an SVG folder with one local command',
    subtitle:
      'Recursive discovery, stable IconData codepoints, typed SVG diagnostics, CI checks, and MCP automation for icon packs that keep growing.',
    footnote: 'glyphpact assets/icons -o lib/generated/app_icons -n AppIcons',
  },
  flutter: {
    eyebrow: 'Flutter',
    title: 'Use a custom icon font in Flutter',
    subtitle:
      'Wire the font and const IconData provider through pubspec, packages, semantics, tree shaking, and a CI staleness check.',
    footnote: 'glyphpact assets/icons -o lib/generated/app_icons -n AppIcons',
  },
  mcp: {
    eyebrow: 'Model Context Protocol',
    title: 'Automate SVG-to-Flutter icon builds with MCP',
    subtitle:
      'A local stdio MCP server for auditing SVG packs, building and checking deterministic Flutter icon fonts, and paging validated reports.',
    footnote: 'glyphpact@glyphpact',
  },
  vsIcomoon: {
    eyebrow: 'Comparison',
    title: 'An IcoMoon alternative for repository-managed icons',
    subtitle:
      'IcoMoon offers visual editing, Flutter output, and broad exports. GlyphPact turns sources, a lock, generated output, and CI checks into one repository contract.',
    footnote: 'Verified 2026-07-27',
  },
  vsFlutterIcon: {
    eyebrow: 'Comparison',
    title: 'A FlutterIcon.com alternative for repeatable builds',
    subtitle:
      'FlutterIcon.com is a hosted Fontello fork with bundled icon packs. GlyphPact is a local CLI with a committed codepoint registry and byte-identical rebuilds.',
    footnote: 'Verified 2026-07-27',
  },
  '404': {
    title: 'That page does not exist',
    subtitle: 'The compiler is stricter than this website. Here is the way back.',
    footnote: '404',
  },
};

export const getStaticPaths: GetStaticPaths = () =>
  Object.keys(cards).map((slug) => ({ params: { slug } }));

export const GET: APIRoute = async ({ params }) => {
  const spec = cards[params.slug as string];
  if (!spec) return new Response('Not found', { status: 404 });

  const png = await renderOg(spec);
  return new Response(new Uint8Array(png), {
    headers: {
      'Content-Type': 'image/png',
      'Cache-Control': 'public, max-age=31536000, immutable',
    },
  });
};
