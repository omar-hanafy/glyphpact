# GlyphPact

**The deterministic SVG-to-Flutter icon compiler.**

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

Install the command directly from GitHub with
[uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/omar-hanafy/glyphpact.git@v1.0.0
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
[examples/README.md](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/examples/README.md).

## Claude Code and Codex plugin

The optional `glyphpact` plugin gives Claude Code and Codex a project-aware
skill plus four local MCP tools:

- audit an SVG file or directory once, then page a stable local snapshot
- build the output declared by a checked-in config
- check committed output for staleness without rewriting generated artifacts
- page through large machine-readable reports

The plugin bundles the exact GlyphPact 1.0.1 wheel, starts its MCP server
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
[plugin guide](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/plugins/glyphpact/README.md)
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
app_icons.dart            const Flutter IconData provider
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

When the font is shipped by a Dart package, pass its package name:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons \
  --font-package my_icon_package
```

See
[Flutter integration](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/docs/flutter-adoption.md)
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

For a larger pack, start in a supplementary private use range:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons \
  --start-codepoint 0xF0000
```

A complete supplementary private use range provides 65,534 slots. Split a
larger catalog into multiple independently versioned fonts.

Performance depends heavily on SVG complexity, not just file count. GlyphPact
does not publish a private-corpus headline. The
[benchmark guide](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/docs/benchmarking.md)
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

Approximations and skips are typed records in CLI JSON and report schema v2.
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
[examples/layered_icon_font.json](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/examples/layered_icon_font.json)
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
[SVG profile](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/docs/svg-profile.md).

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

Use `--json` for stable machine-readable results. Successful result and report
payloads use schema version 2. Lockfiles use schema version 1 because they
record ABI allocation, not build policy.

## Development

```bash
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

See
[CONTRIBUTING.md](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/CONTRIBUTING.md)
for semantic and validation requirements.

## License and artwork

GlyphPact is MIT licensed. User-provided SVG artwork and pinned text fonts keep
their own licenses. GlyphPact cannot grant font embedding, outlining, or
subsetting rights.

Configure `author`, `license`, `sourceUrl`, and `copyright` per icon when
provenance matters. `ATTRIBUTION.md` carries supplied metadata for emitted
glyphs and reports how many emitted icons have no declared provenance.

See the
[changelog](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/CHANGELOG.md),
[architecture](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/docs/architecture.md),
[security policy](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/SECURITY.md),
and
[third-party notice](https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/NOTICE).
