# Follow-ups

Remaining non-blocking work as of July 25, 2026. The package, plugins, release
automation, and public site do not depend on these items.

## Account-bound discovery

### 1. Upload the GitHub repository social preview

The canonical 1280x640 image is
[`brand/glyphpact-social-preview.png`](brand/glyphpact-social-preview.png).
Upload it under **Settings -> General -> Social preview**. GitHub does not
expose a supported public API for this upload, so it requires a signed-in
browser session.

### 2. Submit the sitemap to search consoles

Verify the site in Google Search Console and Bing Webmaster Tools, then submit:

```text
https://omar-hanafy.github.io/glyphpact/sitemap-index.xml
```

The sitemap, robots file, canonical URLs, and live Pages routes are already
validated.

### 3. Run account-backed rich-result tools

Run Google's Rich Results Test and the schema.org validator against the live
homepage and one comparison page. The build already parses every JSON-LD block
and validates its required fields, URLs, and referenced images.

## Content opportunities

### 4. Add comparison pages only when they add new evidence

Fontello and `icon_font_generator` already appear in the sourced comparison
data. Give either tool a dedicated page only when the page can answer search
intent beyond restating the existing table.

### 5. Add a `/vs/` index after the comparison library grows

Two comparison pages do not justify a thin hub. Revisit this after there are at
least four useful comparisons.

### 6. Add long-form release content when there is a real cadence

`CHANGELOG.md` remains the canonical release record. An Astro content
collection becomes worthwhile only after several substantial posts exist.

### 7. Expand agent and MCP documentation when usage data supports it

The plugin guide already covers audit snapshots, mutation boundaries, and
local MCP operation. A dedicated public page should add examples or answer
measured search demand rather than duplicate that guide.

## Site maintenance

### 8. Consider a manual color-scheme toggle

The site fully supports dark and light OS preferences, including reduced
motion. A manual override can reuse the existing `data-theme` CSS contract and
persist a small preference in `localStorage`.

### 9. Re-verify comparison evidence periodically

Each comparison claim is dated and linked to a first-party source. Re-check
[`site/src/data/comparison.ts`](site/src/data/comparison.ts) roughly every six
months and advance the verification date only for cells actually reviewed.

## Product work the site deliberately does not advertise

### 10. WOFF2 and generated CSS

GlyphPact emits validated OpenType/CFF fonts and Dart bindings. Native WOFF2
and stylesheet output would require implementation, schema, report, test, and
documentation changes before the site could claim a complete web workflow.

### 11. Bindings beyond Dart

The lock file is a documented, schema-backed registry that third-party
generators can already consume. Additional first-party bindings should be
driven by proven demand and maintained as real compatibility contracts.
