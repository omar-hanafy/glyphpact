# Changelog

## 1.1.0 - 2026-07-27

- Added an optional exact-boolean `catalog` config with `--catalog` and
  `--no-catalog` CLI overrides. Enabled builds emit
  `<ClassName>Catalog.byName` beside the existing Dart provider, mapping every
  emitted Dart name to its `IconData` in ascending codepoint order.
- Added `<ClassName>Catalog.layeredByName` when a pack contains partial-alpha
  icons, covering only their lossless layered descriptors.
- Preserved normal Flutter icon subsetting when an emitted catalog is
  unreachable, and documented that reachable catalog maps retain the glyphs
  they enumerate. The static-const catalog companion carries Flutter's provider
  annotation so declarations from other packs are not mistaken for reachable
  uses.
- Annotated the generated static-const layered descriptor provider so Flutter
  can continue subsetting directly referenced layered icons independently.
- Kept catalog-enabled Dart byte-stable under Dart 3.0 through current
  formatters with legacy-canonical layouts and narrow formatter controls.
- Added report schema v3 capacity telemetry with `codepointsRemaining` and
  `rangeUtilization`. Package and report-schema versions evolve independently:
  report-driven consumers must recognize v3 before upgrading to GlyphPact
  1.1.0, while the published schema retains validation support for closed
  report schemas v1 and v2.
- Added a stable `CODEPOINT_RANGE_NEAR_EXHAUSTION` warning at 80% utilization
  for library, CLI, and MCP builds. Established locks now reject
  `startCodepoint` changes and mixed-range assignments instead of producing
  misleading capacity or silently chaining allocation ranges.
- Documented report schema v3 as the stable lower-level code-generation
  contract for consumers that need a different collection, ordering, or
  language. CLI success JSON remains schema v2 and lockfiles remain schema v1.

## 1.0.1 - 2026-07-25

- Fixed lossless compilation of valid root, nested SVG, and symbol `viewBox`
  values that use comma-whitespace separators or surrounding whitespace.
- Added stable `SVG_XML_MALFORMED` and `SVG_XML_RESOURCE_LIMIT` diagnostics,
  preserved `SVG_TOO_DEEP` beyond the XML parser's own nesting ceiling, and
  stopped exposing raw upstream messages as compiler failures.
- Classified unexpected conversion faults as `INTERNAL_CONVERSION_ERROR` and
  corrected the CLI to return exit code 1 for internal diagnostics, including
  mixed diagnostic batches.
- Clarified how to resolve embedding-dependent root percentage dimensions
  without silently choosing a different icon canvas.
- Added the official GlyphPact website, canonical brand assets, social
  previews, and self-contained Claude Code and Codex plugin branding.
- Added automated responsive-layout, accessibility, metadata, link, and
  capability-claim checks for the public site.
- Added tag-only PyPI trusted publishing with attestations, a default-branch
  containment guard, exact release-tool pins, and reproducible package
  metadata.

## 1.0.0 - 2026-07-25

- Added recursive SVG pack compilation into validated OpenType/CFF fonts and
  tree-shakeable Dart `IconData` providers.
- Added a bounded SVG profile with strict lossless defaults, explicit
  approximation and omission policies, and stable typed diagnostics.
- Added lockfile-backed codepoint allocation with tombstones and
  content-preserving rename recovery.
- Added deterministic report schema v2 output, artwork attribution, pinned-font
  provenance, and byte-identical artifacts across worker counts.
- Added exact ordered solid-alpha layer fonts with generated Flutter layer
  descriptors and widgets.
- Added app-font and package-font output, supplementary private-use codepoints,
  RTL metadata, and final font validation.
- Added owned-directory publication with concurrent-writer coordination,
  rollback, interrupted-build recovery, and non-rewriting stale artifact
  checks.
- Added a local MCP server for strict audits with stable bounded snapshots,
  reproducible builds, stale-output checks, pageable report reads, and bundled
  schema resources.
- Added one installable Claude Code and Codex plugin containing the exact
  release wheel and a project-integration skill.
- Established Python 3.10 or newer as the compiler runtime and Dart 3 or newer
  for generated providers.
