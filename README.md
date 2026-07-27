<p align="center">
  <img src="https://raw.githubusercontent.com/omar-hanafy/glyphpact/v1.1.0/brand/glyphpact-icon.svg" alt="" width="72" height="72">
</p>

<h1 align="center">GlyphPact</h1>

<p align="center"><strong>The deterministic SVG-to-Flutter icon compiler.</strong></p>

<p align="center">
  <a href="https://omar-hanafy.github.io/glyphpact/">Website</a>
  &middot;
  <a href="https://omar-hanafy.github.io/glyphpact/stable-codepoints/">Stable codepoints</a>
  &middot;
  <a href="https://omar-hanafy.github.io/glyphpact/flutter/">Flutter guide</a>
  &middot;
  <a href="https://github.com/omar-hanafy/glyphpact/blob/main/CHANGELOG.md">Changelog</a>
</p>

GlyphPact turns a directory of SVG files into a validated OpenType/CFF icon
font and a const Dart `IconData` API. It keeps codepoints stable across pack
changes, records what happened to every source, and refuses to hide fidelity
loss.

The default policy is strict:

- lossless SVG normalization happens automatically
- deterministic approximation requires explicit permission
- omission requires separate explicit permission
- malformed, unsafe, unknown, or resource-exhausting input always fails
- a failed build never replaces the last valid generated output

GlyphPact is a CLI compiler. There is no website upload step, no desktop
project file, and no server that receives your artwork.

## Quick start

GlyphPact requires Python 3.10 or newer. Generated providers require Dart 3 or
newer.

Install the latest stable release from PyPI with
[uv](https://docs.astral.sh/uv/concepts/tools/):

```bash
uv tool install glyphpact
```

Upgrade an existing installation when a new release is available:

```bash
uv tool upgrade glyphpact
```

Pin the version in CI or any other reproducible environment:

```bash
uv tool install glyphpact==1.1.0
```

Compile a Flutter icon pack:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons
```

Or run the checked-in example from a source checkout:

```bash
uv sync --locked
uv run glyphpact --config examples/icon_font.json
```

The example SVGs are original MIT-licensed fixtures. See
[examples/README.md](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/examples/README.md).

## Claude Code and Codex plugin

The optional `glyphpact` plugin gives Claude Code and Codex a project-aware
skill plus four local MCP tools:

- audit an SVG file or directory once, then page a stable local snapshot
- build the output declared by a checked-in config
- check committed output for staleness without rewriting generated artifacts
- page through large machine-readable reports

The plugin bundles the exact GlyphPact 1.1.0 wheel, starts its MCP server
automatically, and does not require a source checkout or global GlyphPact
installation. Add this repository as a marketplace, then install the plugin.

Claude Code:

```bash
claude plugin marketplace add omar-hanafy/glyphpact
claude plugin install glyphpact@glyphpact
```

Codex:

```bash
codex plugin marketplace add omar-hanafy/glyphpact
codex plugin add glyphpact@glyphpact
```

Start a new session after installation. Do not add a duplicate personal MCP
configuration. See the
[plugin guide](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/plugins/glyphpact/README.md)
for its runtime requirements, mutation boundary, and maintainer validation
flow.

An audit response with findings includes a `snapshot.id` and
`findings.nextOffset`. Pass that ID back to `audit_icon_pack` with successive
offsets instead of recompiling the pack. Release it explicitly with
`release_snapshot=true`; otherwise the private local snapshot expires
automatically.

## What gets generated

For `--name AppIcons`, GlyphPact owns the selected output directory and writes:

```text
.glyphpact.json           output ownership marker
ATTRIBUTION.md            artwork licensing and provenance
fonts/AppIcons.otf        validated OpenType/CFF font
layer_fonts/layer_*.otf   optional solid-alpha paint-order layers
app_icons.dart            const provider and optional catalog companion
iconfont.lock.json        stable codepoint and provenance registry
iconfont.report.json      deterministic machine-readable build report
```

Register the font in the Flutter app's `pubspec.yaml`. Asset paths are relative
to that file:

```yaml
flutter:
  fonts:
    - family: AppIcons
      fonts:
        - asset: lib/generated/app_icons/fonts/AppIcons.otf
```

Import the generated provider and use it like any other Flutter icon:

```dart
Icon(
  AppIcons.back,
  semanticLabel: 'Back',
)
```

The provider follows Flutter's tree-shaking contract:

```dart
import 'package:flutter/widgets.dart' as flutter;

@flutter.staticIconProvider
abstract final class AppIcons {
  static const flutter.IconData back = flutter.IconData(...);
}
```

### Icon catalog

Galleries, icon pickers, and coverage tests need every glyph by name. Hand
maintaining that list defeats the point of generating the provider, so enable
the catalog in the checked-in config:

```json
{
  "className": "AppIcons",
  "catalog": true
}
```

```dart
@flutter.staticIconProvider
abstract final class AppIconsCatalog {
  static const Map<String, flutter.IconData> byName =
      <String, flutter.IconData>{
        'back': AppIcons.back,
      };
}
```

`AppIconsCatalog` is a separate companion in the same generated Dart library.
It contains only static const maps and carries Flutter's provider annotation so
unreachable catalog declarations in this or another package are not mistaken
for icon uses. Reachable map values remain visible to the tree shaker.
`AppIcons` remains the base icon provider. A partial-alpha pack also annotates
its static-const `AppIconsLayers` descriptor provider so Flutter can subset
directly referenced layered icons independently. `byName` contains every
emitted glyph in ascending codepoint order, keyed by its Dart member name. A
build containing partial-alpha icons also emits
`AppIconsCatalog.layeredByName`, containing only their lossless layered
descriptors. Use normal map operations to derive names, values, entries, sorted
lists, or sets without asking the compiler for another output shape:
`.keys`, `.values`, `.entries`, `.keys.toList()`, `.values.toSet()`, or a
consumer-side sort of a copied list.

Enabling the catalog does not by itself enlarge a release: when the catalog is
unreachable, Flutter removes it and continues to subset the font from the
individual `AppIcons` constants used by the app. Making `byName` reachable
retains every base glyph. Making `layeredByName` reachable retains those icons'
fallbacks and layer-font glyphs. That bounded cost is appropriate for a
shipping picker or gallery, but a catalog referenced only from tests has no
release cost.

Generated declaration regions whose legacy and current Dart layouts differ use
narrowly scoped formatter controls. This includes catalog and layered
descriptor declarations, plus an over-width base provider when needed. Their
underlying layout is also canonical for Dart 3.0 through 3.6, whose formatters
treat those controls as comments. Dart 3.7 and later honor the controls. In
either case, running `dart format` over the project does not make a subsequent
GlyphPact `--check` fail. The rest of the library remains formatter-owned. The
narrow opt-outs exist because generated bytes participate in `--check`; custom
formatting belongs in an external generator outside GlyphPact's owned output.

Omit `catalog`, or set it to `false`, to leave the generated Dart API unchanged.
The matching `--catalog` and `--no-catalog` flags override the config for a
single invocation; keep the config enabled for a durable checked-in surface.

When the font is shipped by a Dart package, pass its package name:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons \
  --font-package my_icon_package
```

See
[Flutter integration](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/docs/flutter-adoption.md)
for app fonts, package fonts, layered icons, CI checks, and accessibility
notes.

## Why deterministic matters

Icon font generation changes an application-facing API. A reorder must not
make an existing `IconData` render a different picture.

`iconfont.lock.json` is the codepoint ABI:

- adding or reordering SVG files does not change existing codepoints
- removing an icon leaves a tombstone instead of recycling its codepoint
- fixing a previously skipped icon reactivates the same slot
- a unique content-preserving rename keeps its codepoint and Dart name
- the same inputs, config, lock, and compiler version produce byte-identical
  artifacts across worker counts

Commit the lock, generated Dart file, font files, report, and attribution file
with your application.

## Large icon sets

GlyphPact discovers nested directories recursively and compiles with bounded
worker processes. It is designed for large packs, but it does not pretend that
one font is unbounded.

OpenType glyph indexing has a practical limit of 65,534 usable glyphs per font,
and GlyphPact enforces the same per-build icon ceiling. The default BMP private
use range, U+E000 through U+F8FF, provides 6,400 lifetime allocation slots.
Active icons and tombstones both consume slots because codepoints are never
recycled.

Every schema v3 report records `codepointsRemaining` and `rangeUtilization`
for the allocation window from the configured `startCodepoint` through the end
of its private-use range. Builds emit `CODEPOINT_RANGE_NEAR_EXHAUSTION` at or
above 80% utilization, including in `--check` mode. The warning remains a
successful exit and is printed to stderr so `--json` stdout stays valid.

For a larger pack, start in a supplementary private use range:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons \
  --start-codepoint 0xF0000
```

A complete supplementary private use range provides 65,534 slots. Split a
larger catalog into multiple independently versioned fonts. Choose the
`startCodepoint` before the first build: an established lock rejects later
changes rather than silently mixing allocation ranges.

Performance depends heavily on SVG complexity, not just file count. GlyphPact
does not publish a private-corpus headline. The
[benchmark guide](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/docs/benchmarking.md)
provides a reproducible local runner and reporting checklist for your own pack.

## Reproducible config

For repeat builds, check in a JSON config:

```json
{
  "$schema": "https://raw.githubusercontent.com/omar-hanafy/glyphpact/main/schema/icon-font-config.schema.json",
  "input": "assets/icons",
  "output": "lib/generated/app_icons",
  "fontFamily": "AppIcons",
  "className": "AppIcons",
  "catalog": true,
  "fontPackage": null,
  "startCodepoint": "0xE000",
  "unitsPerEm": 1000,
  "padding": 0,
  "clipToViewBox": true,
  "policy": {
    "lossy": "error",
    "unrepresentable": "error"
  },
  "jobs": 0,
  "icons": {
    "arrows/back.svg": {
      "name": "back",
      "matchTextDirection": true,
      "author": "Your team",
      "license": "MIT",
      "sourceUrl": "https://example.com/icon-source"
    }
  }
}
```

Paths are relative to the config file:

```bash
glyphpact --config icon_font.json
```

CLI flags override config values. `jobs: 0` selects up to eight bounded worker
processes.

### Report as a code-generation contract

The built-in catalog covers the common Dart enumeration case. For a different
collection type, variable name, order, or language, use
`iconfont.report.json` as the lower-level code-generation input rather than
parsing generated Dart.

Report schema v3 guarantees the shape and meaning of `schemaVersion`,
`font.family`, `font.file`, `font.sha256`, `dart.className`, `dart.file`,
`dart.fontPackage`, `layerFonts`, and each `glyphs[].source`, `name`,
`codepoint`, and `matchTextDirection`. `glyphs` contains active shipped glyphs
only and is ordered by ascending codepoint. Partial-alpha records use
`glyphs[].layeredRendering` to describe their ordered layers, families, files,
codepoints, and opacities. Skipped sources live in `skippedIcons`, never in
`glyphs`; retired assignments remain tombstones in `iconfont.lock.json`.
`codepointsRemaining` is the number of unused assignments left in the
configured allocation window, while `rangeUtilization` is its consumed
fraction from `0` through `1`.

Programmatic `build(...)` callers receive the same telemetry through the
keyword-only `BuildResult.codepoints_remaining`,
`BuildResult.range_utilization`, and `BuildResult.warnings` fields.

Package releases and report schemas are versioned independently. GlyphPact
1.1 generates report v3, while the published schema continues validating
historical v1 and v2 reports. Report-driven generators must recognize v3 before
upgrading; they should continue rejecting every unsupported `schemaVersion`.

Codepoints are encoded as uppercase hexadecimal strings such as `0xE000`.
Parse them with radix 16 only in build-time generators and artifact tests.
Generated Dart should import `dart.file` and reference
`<dart.className>.<glyph.name>` constants rather than constructing `IconData`
dynamically at runtime. Reject an unsupported `schemaVersion` before generating
code. GlyphPact does not remove, rename, add, or change the type or meaning of
fields inside a published closed schema version; a report-shape change requires
a new schema version.

GlyphPact owns its entire configured output directory. Write custom generated
files outside that directory, run the custom generator after GlyphPact, and
give that output its own non-rewriting check. Consumers can then compare their
generated surface with `glyphs` while GlyphPact `--check` continues to cover the
font, provider, lock, report, and attribution artifacts.

## Fidelity policy

A normal icon font stores monochrome alpha coverage, not source RGB colors.
Flutter supplies the runtime color. White SVG paint is therefore filled
coverage, not an inferred hole.

GlyphPact has two independent global policy axes. Both default to `error`:

| `lossy` | `unrepresentable` | Result |
| --- | --- | --- |
| `error` | `error` | Emit only lossless icons. |
| `convert` | `error` | Permit documented deterministic approximations. |
| `error` | `skip` | Omit sources outside the bounded profile. |
| `convert` | `skip` | Permit reported approximations and omissions. |

Select a non-default policy only after reviewing the affected pack:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons \
  --lossy convert \
  --unrepresentable skip
```

Approximations and skips are typed records in CLI JSON and report schema v3.
They include the feature, classification, action, source, diagnostic code, and
structured details when applicable.

`--unrepresentable skip` is not an error-suppression switch. Scripts, event
handlers, external references, malformed values, unknown semantics, exhausted
work limits, and compiler or font failures remain fatal under every policy. If
every source would be skipped, the build fails and publishes nothing.

### Solid partial-alpha icons

An icon can opt into exact ordered solid-alpha rendering through auxiliary
same-codepoint font families:

```json
{
  "icons": {
    "status/verified_layers.svg": {
      "partialAlpha": {
        "mode": "layers",
        "fallback": "silhouette"
      }
    }
  }
}
```

The generated Dart API includes a layered icon widget and layer descriptors.
The ordinary `IconData` remains available as the explicitly selected
single-glyph fallback. See
[examples/layered_icon_font.json](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/examples/layered_icon_font.json)
for a runnable example.

## Supported SVG profile

GlyphPact resolves common icon geometry directly, including:

- paths and SVG primitives
- transforms, viewBoxes, nested viewports, local reuse, and symbols
- filled and stroked outlines, dashes, clips, markers, and fill rules
- static CSS cascade, inheritance, CSS-wide values, and `currentColor`
- opaque gradients and paint-server fallback semantics
- bounded text outlining through explicitly pinned local font files

Features that need a browser, external environment, animation runtime, or an
unsupported compositing model are classified instead of guessed. The complete
versioned contract is in the
[SVG profile](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/docs/svg-profile.md).

## Failure-safe output

GlyphPact stages and validates the complete artifact set before publication.
The final font is reopened and checked against the Dart API, including cmap,
bounds, metrics, checksums, and required OpenType tables.

A non-empty output directory must contain GlyphPact's ownership marker. Use
`--adopt-output` only once, after inspecting a directory you intentionally want
GlyphPact to replace.

Verify checked-in artifacts without rewriting them:

```bash
glyphpact --config icon_font.json --check
```

The check may create the output's parent directory and leaves the sibling
coordination file `.<output>.glyphpact.lock` in place. The persistent lock inode
prevents a waiting process from bypassing an already-held publication lock.

Exit codes:

- `0`: build or check succeeded
- `1`: unexpected internal failure
- `2`: config, input, policy, geometry, or font contract failed
- `3`: `--check` found stale output

Use `--json` for stable machine-readable results. Successful CLI result
payloads use schema version 2, deterministic reports use schema version 3, and
lockfiles use schema version 1 because they record ABI allocation rather than
build policy. Capacity warnings use stderr and do not corrupt JSON stdout.

## Development

```bash
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

The marketing site is a separate static Astro project in
[`site/`](https://github.com/omar-hanafy/glyphpact/tree/main/site),
deployed to GitHub Pages by `.github/workflows/pages.yml`:

```bash
cd site
npm ci
npm run verify   # type-check, brand and claim checks, build, link check
npm run dev
```

See
[CONTRIBUTING.md](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/CONTRIBUTING.md)
for semantic and validation requirements.

## License and artwork

GlyphPact is MIT licensed. User-provided SVG artwork and pinned text fonts keep
their own licenses. GlyphPact cannot grant font embedding, outlining, or
subsetting rights.

Configure `author`, `license`, `sourceUrl`, and `copyright` per icon when
provenance matters. `ATTRIBUTION.md` carries supplied metadata for emitted
glyphs and reports how many emitted icons have no declared provenance.

Brand assets live in
[`brand/`](https://github.com/omar-hanafy/glyphpact/blob/main/brand/README.md),
which is the single source of truth for the identity and documents how to
replace it.

See the
[changelog](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/CHANGELOG.md),
[architecture](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/docs/architecture.md),
[security policy](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/SECURITY.md),
and
[third-party notice](https://github.com/omar-hanafy/glyphpact/blob/v1.1.0/NOTICE).
