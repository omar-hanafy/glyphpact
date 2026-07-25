# GlyphPact brand assets

This directory is the single source of truth for GlyphPact's visual identity.
The marketing site reads the canonical SVG artwork directly. Surfaces that must
be self-contained, such as the installed Codex plugin and PNG-only platform
slots, carry generated copies whose parity is checked in CI.

## The mark

**Registered em square, locked node.**

Four registration marks measure the em square, the way a type drawing is
registered before any curve is committed. The solid diamond at the centre is
the vector anchor point: the codepoint that never moves. That is the whole
product argument in one figure.

The geometry is filled outlines in a single colour, with no strokes, gradients,
or transparency - exactly the representation an icon-font glyph can hold.
GlyphPact compiles `glyphpact-mark.svg` strictly and losslessly as five separate
contours. That self-hosting contract is covered by the Python test suite.

The tiled `glyphpact-icon.svg` is a display asset, not an icon-font input. Its
opaque background, light frame, and cyan node intentionally collapse to one
rounded-square alpha silhouette in a monochrome font.

## Files

| File | Paint | Use |
| --- | --- | --- |
| `glyphpact-mark.svg` | `currentColor` | Inlined in HTML where it should inherit text colour. The site header and footer use this. |
| `glyphpact-icon.svg` | Explicit hex on a tile | Anywhere the mark cannot inherit a colour: README, favicon, plugin catalogs, social profiles. |
| `apple-touch-icon.png` | 180x180 PNG | Canonical Apple Web Clip image generated from `glyphpact-icon.svg`. |
| `glyphpact-social-preview.png` | 1280x640 PNG | Timeless repository social preview generated from the canonical icon and brand palette. |
| `tokens.json` | - | Named colour tokens with their roles. |

Both SVGs share one 32x32 grid. `glyphpact-icon.svg` places that grid on a
64x64 tile (inset 6, scaled 1.625x).

## Who consumes these files

| Consumer | How |
| --- | --- |
| `site/src/components/BrandMark.astro` | Inlines `glyphpact-mark.svg` at build time via a `?raw` import. Accepts a `tone` prop for the mono or two-tone treatment. |
| `site/src/pages/favicon.svg.ts` | Serves `glyphpact-icon.svg` at build time. |
| `site/src/lib/og.ts` | Composites `glyphpact-icon.svg` into every site social preview image. |
| `site/src/styles/global.css` | Mirrors `tokens.json` as CSS custom properties. |
| `site/public/apple-touch-icon.png` | Byte-identical publication copy of the canonical Apple touch icon. |
| `plugins/glyphpact/assets/` | Self-contained, byte-identical SVG copies for Codex plugin surfaces. Plugin validation rejects drift. |
| `README.md` | Links `brand/glyphpact-icon.svg` directly. |
| GitHub repository settings | Uses `glyphpact-social-preview.png` as the uploaded social preview. |

## Rebranding

The identity is deliberately cheap to replace.

**To change only the colours**, edit `tokens.json`, then update the explicit
brand mirrors in `glyphpact-icon.svg`, `site/src/styles/global.css`,
`site/src/lib/og.ts`, the theme-colour metadata in
`site/src/layouts/Base.astro`, and the Codex plugin `brandColor`. Regenerate the
PNG assets afterward. Brand and plugin validation catch drift in the surfaces
whose values or bytes can be compared mechanically.

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

After any change:

1. Regenerate `apple-touch-icon.png`,
   `glyphpact-social-preview.png`, the `site/public/` publication copy, and the
   two plugin-local SVG copies from the canonical SVGs.
2. Re-upload `glyphpact-social-preview.png` under the repository's Social
   preview setting.
3. Run the brand, plugin, and compiler contract checks:

```bash
(cd site && npm run check:brand)
.venv/bin/pytest tests/test_brand_contract.py plugins/glyphpact/tests
.venv/bin/python plugins/glyphpact/scripts/validate_plugin.py
```
