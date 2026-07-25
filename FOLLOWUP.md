# Follow-ups

Deliberately deferred work, known limitations, and manual steps, recorded when
the marketing site in [`site/`](site/) was built (2026-07-25, GlyphPact v1.0.0).

Nothing here blocks announcing the site. Items are grouped by what they need.

---

## Manual actions required before the site is public

### 1. Select GitHub Actions as the Pages source

**Why it matters:** the deploy job cannot run until this is set, and it is a
repository setting that cannot be changed from a workflow.

**Next action:** in the repository, open **Settings -> Pages** and set
**Source** to **GitHub Actions**. Then either push a change under `site/` or
`brand/` on `main`, or run the **Site** workflow manually via
**Actions -> Site -> Run workflow**. The site publishes to
`https://omar-hanafy.github.io/glyphpact/`.

The `github-pages` environment is referenced by the deploy job and is created
automatically on first deploy; no manual environment setup is needed.

### 2. Verify the deployed site

**Why it matters:** everything below was verified against a local production
preview. Base-path handling, canonical URLs, and social cards are correct in the
build output, but only a real deploy proves the Pages serving layer agrees.

**Next action:** after the first deploy, load the five indexable pages plus
`/llms.txt`, `/robots.txt`, `/sitemap-index.xml`, and a deliberately wrong URL
to confirm the 404 page renders. Then re-run
`cd site && npm run check:links -- --external` against the live origin if you
want external links re-checked.

### 3. Submit the sitemap to search consoles

**Why it matters:** discovery is the entire point of the site, and neither
Google nor Bing will find a brand-new subpath quickly on its own.

**Next action:** verify the property in
[Google Search Console](https://search.google.com/search-console) and
[Bing Webmaster Tools](https://www.bing.com/webmasters), then submit
`https://omar-hanafy.github.io/glyphpact/sitemap-index.xml`. This needs an
account and cannot be automated from here.

### 4. Validate structured data with a live URL

**Why it matters:** every JSON-LD block was parsed and structurally checked
against its schema.org type locally, and `check:links` fails the build on
invalid JSON or a missing `@context`/`@type`. But Google's
[Rich Results Test](https://search.google.com/test/rich-results) and the
[schema.org validator](https://validator.schema.org/) both require a public URL,
so neither was run.

**Next action:** run both against the homepage and one comparison page after
deploy. Expect `SoftwareApplication`, `WebSite`, `FAQPage`, `TechArticle`, and
`BreadcrumbList` to be recognised.

---

## Release process

### 5. Bump the advertised version when GlyphPact releases

**Why it matters:** the site names v1.0.0 in the hero, the install command, the
generated-code samples, the CI example, and `/llms.txt`. All of them derive from
one constant, but that constant is deliberately not read from
`src/glyphpact/version.py`, because the source tree can carry an unreleased
bump and the site must only ever advertise a published release.

**Next action:** add to the release checklist: update `RELEASE.version` in
`site/src/site.config.ts` after tagging. `npm run check:claims` fails the build
if that version has no matching `v<version>` git tag, so a mistake here cannot
ship silently. Consider automating it in `release.yml` once the release flow
settles.

### 6. Consider publishing to PyPI so the install command can float

**Why it matters:** the install command pins `@v1.0.0`. That is currently the
correct choice - GlyphPact is not on PyPI, and an unpinned
`git+https://...glyphpact.git` installs the `main` branch rather than a release,
which would be worse than a stale pin for a tool whose entire premise is
determinism. But it does mean every visitor copies a version-locked command that
ages with each release.

**Next action:** `release.yml` already has a `pypi` job behind a
`workflow_dispatch` input. Publishing there would let the site show
`uv tool install glyphpact`, which resolves to the newest release with no site
change ever needed. Until then the site explains the pin inline and links to the
releases page.

---

## Content opportunities

### 7. More comparison pages

**Why it matters:** the comparison pages are the clearest search wedge, and two
of them cover only part of the field.

**Next action:** Fontello and `icon_font_generator` currently appear only as
columns in the shared comparison data. Each could carry its own page if search
data shows demand. `site/src/data/comparison.ts` already holds sourced,
dated cells for both, so a new page is mostly prose. Resist adding a page that
would only restate the table.

### 8. A `/vs/` index page

**Why it matters:** the comparison pages currently use a two-level breadcrumb
because there is no comparisons hub to link an intermediate crumb to.

**Next action:** worth adding only once there are four or more comparisons.
With two, a hub page would be thin and would compete with the pages it links to.

### 9. Blog or changelog-driven content collection

**Why it matters:** the site has no surface for "what changed and why", which is
where a deterministic-build tool can be genuinely interesting.

**Next action:** deferred as pure scope. A content collection is unjustified for
five hand-written pages. Revisit if there is a steady stream of posts to publish;
`CHANGELOG.md` remains the canonical release record.

### 10. Deeper agent and MCP documentation

**Why it matters:** the plugin is a real differentiator and the homepage gives
it one section.

**Next action:** a dedicated page covering the audit-snapshot paging model, the
mutation boundary, and the read-only tool annotations would serve the
"Claude Code icon font" search intent. Deferred because the plugin's own guide
already covers it and a thin duplicate would be worse than a link.

---

## Site engineering

### 11. No automated horizontal-overflow regression test

**Why it matters:** four separate layout bugs found during this build caused the
whole page to scroll sideways on narrow viewports - grid items refusing to
shrink, an unwrapped code-block title bar, an SVG painting outside its viewBox,
and a wide table escaping its `overflow-x: auto` wrapper. Every one of them was
invisible in the build output and in desktop review.

**Next action:** the fixes are documented in `site/src/styles/global.css` under
"overflow discipline", but nothing stops a regression. A Playwright check that
loads each page at 320/375/768/1440 and asserts
`documentElement.scrollWidth === clientWidth` would catch the whole class. It
needs a browser in CI, which is why it was not added now.

### 12. No automated accessibility audit in CI

**Why it matters:** the site reaches Lighthouse 100 for accessibility, and two
genuine failures were fixed to get there (a footer link distinguishable only by
colour, and copy buttons whose accessible names did not contain their visible
text). Both were found by an audit, not by reading the code.

**Next action:** add `axe-core` plus Playwright, or Lighthouse CI, to the Site
workflow. Same blocker as above: it needs a browser in CI. `check:links` already
covers the static half - single `h1`, heading order, duplicate ids, and dangling
`aria-labelledby` targets.

### 13. Colour-scheme toggle

**Why it matters:** the site honours `prefers-color-scheme` and both schemes are
fully designed and contrast-checked, but a reader cannot override the OS setting.

**Next action:** the stylesheet already carries `:root[data-theme='dark']` and
`:root[data-theme='light']` blocks that win over the media query in both
directions, so a toggle is a small button plus a `localStorage` read. Deferred
to keep shipped JavaScript to the single copy-button handler.

### 14. Comparison data needs periodic re-verification

**Why it matters:** every comparison cell is stamped "verified on 2026-07-25"
and cites its source. Those claims will age, and a stale comparison is worse
than none.

**Next action:** re-check `site/src/data/comparison.ts` against first-party
documentation roughly every six months, and move `VERIFIED_ON` forward only for
cells actually re-checked. Two findings worth preserving because they are widely
misstated: IcoMoon processes artwork in the browser and does **not** upload SVGs
on its free plan, and both IcoMoon and Fontello/FlutterIcon **do** preserve
codepoints when their session file is re-imported. The site says so.

### 15. Social cards are generated at build time from one template

**Why it matters:** `site/src/pages/og/[slug].png.ts` holds the copy for six
cards. Adding a page means adding a card, or the layout falls back to a missing
image.

**Next action:** `check:links` already fails when a page's `twitter:image` does
not resolve to a built file, so this cannot ship broken. No change needed unless
per-page art direction becomes worthwhile.

---

## Product work the site deliberately does not advertise

These are recorded because the site was written not to claim them, and
`npm run check:claims` fails the build if any of them appear as a GlyphPact
capability in the shipped HTML.

### 16. WOFF2 output

**Why it matters:** the single most requested thing a web developer will look
for. The site states plainly that GlyphPact does not produce it and that using
the font on the web means converting the `.otf` yourself.

**Next action:** genuine product work - implementation, tests, schema and report
changes, and documentation. Not a copy change.

### 17. Generated CSS

**Why it matters:** same as above. Without a stylesheet, the OpenType font plus
lock file is a usable but incomplete web story.

**Next action:** would pair naturally with WOFF2. Needs a decision about class
naming and whether the lock file grows a CSS-facing view.

### 18. Bindings beyond Dart

**Why it matters:** the honest boundary the site draws is "universal font and
lock file, Flutter-specific binding". Any additional binding would widen that.

**Next action:** the lock file is already a documented, schema-backed registry,
so a third-party generator could consume it without changes to GlyphPact. That
may be a better answer than shipping more bindings.

---

## Known limitations found while verifying

### 19. Root percentage dimensions leak a raw upstream message in v1.0.0

**Why it matters:** while verifying the fidelity policy for the site, an SVG with
`width="100%" height="100%"` and no `viewBox` produced
`SVG_CONVERSION_FAILED: could not convert string to float: '100%'` rather than a
clean unrepresentable classification. It is a diagnostic-quality issue, not a
correctness one - the build still refuses to publish.

**Next action:** already addressed in the unreleased 1.0.1 changelog entries
covering root percentage dimensions and no longer exposing raw upstream
messages. The site therefore uses an `feGaussianBlur` filter as its
unrepresentable example instead, which classifies cleanly in v1.0.0. No site
change needed once 1.0.1 ships, but the example is worth revisiting then.
