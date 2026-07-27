---
name: sync-flutter-svg-icons
description: Audit, compile, repair, wire, update, and visually verify one or many SVG files as stable Flutter IconData fonts with GlyphPact. Use when adding or replacing Flutter icons, migrating an existing icon font, processing large SVG collections, isolating malformed or unsupported artwork, preserving codepoints and public Dart constants, configuring layered alpha or text fonts, fixing font registration, or proving generated glyphs in a running Flutter target.
---

# Sync Flutter SVG Icons

Produce a reproducible Flutter icon-font integration with explicit fidelity
policy, stable codepoints, and rendered proof. Treat a successful compilation
as artifact evidence, not visual evidence.

## Establish scope

Resolve absolute paths for:

- the Flutter app or package containing `pubspec.yaml`
- the SVG source file or directory
- an existing GlyphPact config, if present
- the dedicated generated output directory

Inspect repository status before editing and preserve unrelated changes. Keep
source artwork under project control by default. Do not make builds depend on
Downloads, Desktop, or another machine-local directory.

Read [configuration.md](references/configuration.md) before creating or
changing a config. Read [fidelity-policy.md](references/fidelity-policy.md)
when the audit reports any issue or the sources contain text, alpha, paint
servers, masks, filters, external content, or other complex SVG features. Read
[flutter-verification.md](references/flutter-verification.md) before wiring a
new font or claiming completion.

## Use the packaged runtime

Prefer the GlyphPact MCP server bundled with this plugin. Do not search for or
depend on a GlyphPact source checkout.

Use the MCP operations in this order:

1. `audit_icon_pack` with exactly one absolute `input_path` or absolute
   `config_path`. Keep `lossy="error"` and `unrepresentable="error"` first.
   Start at `offset=0`. If the response contains `snapshot.id`, call the same
   tool with that `snapshot_id` and each `findings.nextOffset` until every
   bounded findings page has been reviewed. Then release it with
   `release_snapshot=true`.
2. Decide every reported policy exception with the user.
3. `build_icon_font` with the absolute checked-in config path.
4. `check_icon_font` with the same config after publication.
5. `read_icon_report` to page through the published report after a successful
   build.

The audit uses disposable output and removes it before returning, so it does not
produce a persistent report path for `read_icon_report`. Review its typed audit
`findings` pages through the stable local snapshot. Do not rerun compilation for
each page. Snapshots expire automatically after a bounded idle or maximum age,
but release them explicitly after review. Pages contain at most 500 findings and
1 MiB. Each snapshot is capped at 64 MiB, expires after 15 idle minutes or one
hour total, and shares a cache limited to 8 snapshots and 128 MiB. Use report
paging only after `build_icon_font` publishes the configured report.

Pass absolute paths because the MCP server is installed outside the user's
workspace. Use `jobs=1` only when the execution environment blocks worker
processes; otherwise leave automatic parallelism enabled. Increase timeouts
proportionally for large sets instead of splitting them arbitrarily.

If MCP tools are unavailable but the plugin files are accessible, locate the
plugin root two directories above this `SKILL.md` and run the packaged CLI:

```bash
python <plugin-root>/scripts/run_glyphpact.py \
  --config /absolute/project/tool/icon_font.json --json
```

Use `--check` for the artifact-non-rewriting reproducibility gate. It may create
the output parent directory and leaves a persistent `.<output>.glyphpact.lock`
coordination file. If the packaged wheel is missing or its checksum fails,
report an incomplete plugin installation. Do not silently substitute an
editable checkout or a globally installed version.

## Audit before mutation

Inventory the SVG tree and record:

- recursive source count and normalized relative paths
- case-insensitive filename and generated Dart-name collisions
- exact duplicate digests
- malformed XML, missing geometry, and unusable view boxes
- external resources, scripts, event handlers, and unsafe references
- text plus the exact font files needed to outline it
- color, opacity, gradients, masks, filters, patterns, images, and animation
- clipping, transforms, reuse, strokes, fill rules, and nested viewports

Keep exact duplicates unless the user requests consolidation. Different public
names may intentionally point to identical artwork.

Run the strict audit before editing project files. Classify each source from
GlyphPact's typed result:

- lossless and safe to normalize
- approximated only with explicit `lossy="convert"` approval
- unrepresentable and omitted only with explicit
  `unrepresentable="skip"` approval
- repairable at the source, config, project wiring, or compiler boundary
- hard failure that remains fatal under every policy

Do not weaken safety checks to get a partial result. For a truly broken source,
use a temporary mirror that preserves relative paths and excludes only the
confirmed file, then report the required re-export, font, linked resource, or
redraw action.

## Build without breaking the ABI

For an existing integration:

- retain the same owned output directory and lock file
- retain font family, Dart class, package name, and start codepoint
- let GlyphPact verify content-based renames and preserve tombstones
- inspect the generated provider diff for removed or renamed constants
- never recreate the lock to make a migration easier

For a new integration:

1. Check in a config with strict default policies.
2. Keep the generated directory exclusive to GlyphPact.
3. Build only after the audit and policy decisions are settled.
4. Confirm the report counts, quality, issues, font digest, provider path, and
   lock path, plus remaining codepoints and range utilization.
5. Use `read_icon_report` in bounded pages for the published glyphs, skipped
   sources, and diagnostic set.
6. Run `check_icon_font` and require a clean result.

Use `adopt_output=true` only when the user explicitly intends GlyphPact to
replace a non-empty directory that lacks its ownership marker. Resolve the
exact target and inspect it first.

## Wire and prove Flutter behavior

Register the primary font and every reported layer font using the exact
families and files in `iconfont.report.json`. Set `fontPackage` only for a
reusable Flutter package. Import the generated provider instead of duplicating
numeric codepoints.

After Dart or `pubspec.yaml` edits:

1. run `dart format` on edited Dart
2. run scoped or full `dart analyze` in proportion to the change
3. build the relevant Flutter target
4. launch to a usable screen
5. compare rendered glyphs against their source SVGs

Inspect every icon for small sets. For larger sets, render a complete searchable
gallery, scan every card for tofu, clipping, emptiness, and shifts, then compare
all diagnostics and a representative sample directly. Include the first, last,
repaired, approximated, skipped, directional, and layered cases.

Compare silhouette, holes, winding, stroke caps and joins, proportions,
padding, clipping, baseline, direction, and alpha. Validate the generated
layered widget separately from its documented single-glyph fallback.

Do not claim visual fidelity from a cmap check, analyzer result, successful
build, or widget construction alone.

## Handoff

Report:

- discovered, lossless, approximated, skipped, broken, repaired, and duplicate
  counts
- each approximation and omission plus its explicit approval state
- every excluded source and required user action
- codepoint and public API compatibility
- remaining codepoint capacity, range utilization, and any near-exhaustion
  warning
- exact config, provider, font, lock, report, and attribution paths
- analyzer, build, launch, and visual checks actually completed

Use the generated report as the machine log and the final response as the human
summary. Do not add a second persistent project log without an existing
convention or an explicit request.
