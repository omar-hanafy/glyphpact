/**
 * Social preview card generation. Build time only - nothing here ships.
 *
 * Two stages, chosen so neither tool is asked to do what it is bad at:
 *
 *  1. satori lays out the text and returns SVG. It is given real font data, and
 *     it converts text to outlines, so the result carries no font dependency.
 *  2. sharp rasterises that, then composites the actual brand icon from
 *     brand/glyphpact-icon.svg on top.
 *
 * Stage 2 exists specifically so the mark is not redrawn here. Reconstructing
 * the logo in layout primitives would fork the identity into a second source
 * that a rebrand would silently miss.
 */

import satori from 'satori';
import sharp from 'sharp';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { iconSvg } from './brand';

/**
 * Font files are read from disk rather than imported, because they are binary
 * and only needed during the build. `import.meta.url` is not usable here: this
 * module gets bundled into dist/.prerender/chunks, so a URL relative to the
 * source file no longer points anywhere. Resolving against the Astro project
 * root is stable under bundling.
 */
const FONT_DIR = 'src/assets/fonts';

function font(file: string): Buffer {
  const candidates = [join(process.cwd(), FONT_DIR, file), join(process.cwd(), 'site', FONT_DIR, file)];
  const found = candidates.find((p) => existsSync(p));
  if (!found) {
    throw new Error(
      `Social-card font missing: ${file}. Looked in:\n  ${candidates.join('\n  ')}\n` +
        'Run the build from the site/ directory.',
    );
  }
  return readFileSync(found);
}

/** The brand icon arrives as an already-inlined string from lib/brand. */
const brandIcon = () => Buffer.from(iconSvg);

const FONTS = [
  { name: 'Geist', data: font('Geist-Regular.ttf'), weight: 400 as const, style: 'normal' as const },
  { name: 'Geist', data: font('Geist-SemiBold.ttf'), weight: 600 as const, style: 'normal' as const },
  {
    name: 'Geist Mono',
    data: font('GeistMono-Regular.ttf'),
    weight: 400 as const,
    style: 'normal' as const,
  },
];

const INK = '#0B0D10';
const PAPER = '#E9ECF1';
const MUTED = '#9BA4B0';
const FAINT = '#6B7480';
const ACCENT = '#22D3EE';
const RULE = 'rgba(233,236,241,0.14)';

const WIDTH = 1200;
const HEIGHT = 630;
const MARK_SIZE = 60;
const PAD = 72;

/** Minimal element shape satori accepts. */
type El = {
  type: string;
  props: Record<string, unknown> & { children?: El | El[] | string };
};

const el = (type: string, props: El['props']): El => ({ type, props });

export interface OgCard {
  /** Large headline. Keep to roughly 60 characters. */
  title: string;
  /** Supporting line under the headline. */
  subtitle: string;
  /** Small monospace line at the bottom left, e.g. a command or a route. */
  footnote: string;
  /** Small label above the headline, e.g. the section name. */
  eyebrow?: string;
}

function card({ title, subtitle, footnote, eyebrow }: OgCard): El {
  return el('div', {
    style: {
      width: WIDTH,
      height: HEIGHT,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      backgroundColor: INK,
      padding: `${PAD}px`,
      fontFamily: 'Geist',
      // A cyan hairline along the top edge, the one piece of brand colour.
      borderTop: `4px solid ${ACCENT}`,
    },
    children: [
      // Header: space for the composited mark, then the wordmark.
      el('div', {
        style: { display: 'flex', alignItems: 'center', gap: '20px' },
        children: [
          el('div', { style: { width: MARK_SIZE, height: MARK_SIZE } }),
          el('div', {
            style: {
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
            },
            children: [
              el('div', {
                style: { fontSize: 30, fontWeight: 600, color: PAPER, letterSpacing: '-0.02em' },
                children: 'GlyphPact',
              }),
              el('div', {
                style: {
                  fontSize: 17,
                  color: FAINT,
                  fontFamily: 'Geist Mono',
                  letterSpacing: '0.04em',
                },
                children: 'deterministic SVG-to-icon-font compiler',
              }),
            ],
          }),
        ],
      }),

      // Body
      el('div', {
        style: { display: 'flex', flexDirection: 'column', gap: '22px' },
        children: [
          ...(eyebrow
            ? [
                el('div', {
                  style: {
                    fontSize: 18,
                    fontFamily: 'Geist Mono',
                    color: ACCENT,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                  },
                  children: eyebrow,
                }),
              ]
            : []),
          el('div', {
            style: {
              fontSize: title.length > 46 ? 60 : 70,
              fontWeight: 600,
              color: PAPER,
              lineHeight: 1.08,
              letterSpacing: '-0.035em',
              maxWidth: 1000,
            },
            children: title,
          }),
          el('div', {
            style: {
              fontSize: 27,
              color: MUTED,
              lineHeight: 1.45,
              maxWidth: 940,
            },
            children: subtitle,
          }),
        ],
      }),

      // Footer
      el('div', {
        style: {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderTop: `1px solid ${RULE}`,
          paddingTop: '26px',
        },
        children: [
          el('div', {
            style: {
              // Sized so the longest footnote - the install command - stays on
              // one line beside the repository label.
              fontSize: footnote.length > 44 ? 18 : 21,
              fontFamily: 'Geist Mono',
              color: MUTED,
              whiteSpace: 'nowrap',
            },
            children: footnote,
          }),
          el('div', {
            style: { fontSize: 19, fontFamily: 'Geist Mono', color: FAINT },
            children: 'github.com/omar-hanafy/glyphpact',
          }),
        ],
      }),
    ],
  });
}

/** Render a card to PNG bytes. */
export async function renderOg(spec: OgCard): Promise<Buffer> {
  const svg = await satori(card(spec) as never, {
    width: WIDTH,
    height: HEIGHT,
    fonts: FONTS,
  });

  const base = sharp(Buffer.from(svg)).png();

  // The mark is rasterised from the canonical brand file and placed where the
  // layout left a gap for it.
  const mark = await sharp(brandIcon(), { density: 384 })
    .resize(MARK_SIZE, MARK_SIZE)
    .png()
    .toBuffer();

  return base
    .composite([{ input: mark, top: PAD + 4, left: PAD }])
    .png({ compressionLevel: 9 })
    .toBuffer();
}
