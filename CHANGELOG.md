# Changelog

## 1.0.1 - Unreleased

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
