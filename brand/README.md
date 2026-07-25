# GlyphPact brand assets

This directory is the single source of truth for GlyphPact's visual identity.
Everything else - the marketing site, the README, the favicon, social preview
images - reads from these files. Nothing duplicates the geometry.

## The mark

**Registered em square, locked node.**

Four registration marks measure the em square, the way a type drawing is
registered before any curve is committed. The solid diamond at the centre is
the vector anchor point: the codepoint that never moves. That is the whole
product argument in one figure.

The geometry is filled outlines in a single colour, with no strokes, no
gradients, and no transparency - exactly the representation an icon-font glyph
can hold. GlyphPact can compile its own logo.

## Files

| File | Paint | Use |
| --- | --- | --- |
| `glyphpact-mark.svg` | `currentColor` | Inlined in HTML where it should inherit text colour. The site header and footer use this. |
| `glyphpact-icon.svg` | Explicit hex on a tile | Anywhere the mark cannot inherit a colour: README, favicon, repository avatar, social profiles. |
| `tokens.json` | - | Named colour tokens with their roles. |

Both SVGs share one 32x32 grid. `glyphpact-icon.svg` places that grid on a
64x64 tile (inset 6, scaled 1.625x).

## Who consumes these files

| Consumer | How |
| --- | --- |
| `site/src/components/BrandMark.astro` | Inlines `glyphpact-mark.svg` at build time via a `?raw` import. Accepts a `tone` prop for the mono or two-tone treatment. |
| `site/src/pages/favicon.svg.ts` | Serves `glyphpact-icon.svg` at build time. |
| `site/src/lib/og.ts` | Draws the mark into every social preview image. |
| `site/src/styles/global.css` | Mirrors `tokens.json` as CSS custom properties. |
| `README.md` | Links `brand/glyphpact-icon.svg` directly. |

## Rebranding

The identity is deliberately cheap to replace.

**To change only the colours**, edit `tokens.json`, then mirror the values in
two places: the `--gp-*` custom properties at the top of
`site/src/styles/global.css`, and the explicit `fill` attributes in
`glyphpact-icon.svg`. Nothing else hardcodes a brand colour.

**To change the mark**, replace `glyphpact-mark.svg` and `glyphpact-icon.svg`,
keeping these three contracts:

1. `glyphpact-mark.svg` paints with `fill="currentColor"` so it inherits type
   colour, and keeps the `gp-mark__node` class on whichever element should
   take the accent colour in the two-tone treatment. If the new mark has no
   accent element, drop the class and the two-tone variant degrades to mono.
2. Both files keep a square `viewBox`. The site sizes the mark by CSS width
   and height, so any square grid works.
3. `glyphpact-icon.svg` keeps explicit colours and stays legible at 16px.

**To change the name**, edit `name` in `site/src/site.config.ts`. The wordmark
is set in live text, not baked into artwork, so a rename needs no redrawing.

After any change, re-run the brand check, which rasterises both files down to
16px and fails if either stops resolving:

```bash
cd site && npm run check:brand
```
