# Changelog

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
