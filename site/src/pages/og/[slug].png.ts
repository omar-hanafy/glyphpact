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
    title: 'Why icon-font codepoints move, and how to stop it',
    subtitle:
      'Most generators assign codepoints from the current file list. A committed registry makes each assignment permanent, and tombstones the ones you remove.',
    footnote: 'iconfont.lock.json',
  },
  flutter: {
    eyebrow: 'Flutter',
    title: 'Custom Flutter icons that keep their codepoints',
    subtitle:
      'An OpenType font plus a tree-shakeable const IconData class, with a check mode that fails CI when committed output drifts from its sources.',
    footnote: 'glyphpact assets/icons -o lib/generated/app_icons -n AppIcons',
  },
  vsIcomoon: {
    eyebrow: 'Comparison',
    title: 'GlyphPact and IcoMoon do different jobs',
    subtitle:
      'IcoMoon keeps codepoints when you re-import selection.json, and exports web assets GlyphPact does not. GlyphPact keeps them in a file CI can verify.',
    footnote: 'Verified 2026-07-25',
  },
  vsFlutterIcon: {
    eyebrow: 'Comparison',
    title: 'GlyphPact and FlutterIcon.com, compared fairly',
    subtitle:
      'FlutterIcon.com is a hosted Fontello fork with bundled icon packs. GlyphPact is a local CLI with a committed codepoint registry and byte-identical rebuilds.',
    footnote: 'Verified 2026-07-25',
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
