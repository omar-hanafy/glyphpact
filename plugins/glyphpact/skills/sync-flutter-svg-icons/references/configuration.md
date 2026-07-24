# GlyphPact configuration

Use a checked-in JSON config for every durable integration. Resolve `input`,
`output`, pinned text-font paths, and artifact paths relative to the config
file. Pass the config itself to MCP tools as an absolute path.

## Recommended layout

```text
project/
├── assets/svg/icons/             source artwork
├── lib/generated/app_icons/      GlyphPact-owned output
│   ├── fonts/AppIcons.otf
│   ├── layer_fonts/*.otf
│   ├── app_icons.dart
│   ├── iconfont.lock.json
│   ├── iconfont.report.json
│   └── ATTRIBUTION.md
└── tool/icon_font.json
```

Do not register source SVGs as runtime assets unless the application also
renders those SVGs directly.

## Strict starting config

```json
{
  "$schema": "https://raw.githubusercontent.com/omar-hanafy/glyphpact/main/schema/icon-font-config.schema.json",
  "input": "../assets/svg/icons",
  "output": "../lib/generated/app_icons",
  "fontFamily": "AppIcons",
  "className": "AppIcons",
  "fontPackage": null,
  "startCodepoint": "0xE000",
  "unitsPerEm": 1000,
  "precision": 3,
  "padding": 0,
  "clipToViewBox": true,
  "policy": {
    "lossy": "error",
    "unrepresentable": "error"
  },
  "jobs": 0,
  "icons": {}
}
```

Keep the private-use start codepoint and committed lock stable after the first
release. Do not set `fontPackage` for an application. For a reusable package,
set it to that package's exact lower_snake_case package name.

## Per-icon metadata

Key overrides by the normalized path relative to `input`:

```json
{
  "icons": {
    "navigation/back.svg": {
      "name": "back",
      "matchTextDirection": true,
      "author": "Example Studio",
      "license": "MIT",
      "sourceUrl": "https://example.com/icons/back"
    }
  }
}
```

Use `matchTextDirection` only when semantic direction should mirror in RTL.
Use a stable Dart identifier in `name`; do not rename a public constant merely
to satisfy a temporary call site.

## Text

SVG text requires an exact local font plus its SHA-256:

```json
{
  "textFonts": {
    "Inter": {
      "file": "../assets/fonts/Inter-Regular.ttf",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  }
}
```

Pin every face referenced by source text. Do not substitute a system font or
guess a missing font.

## Layered alpha

Opt in only the affected source:

```json
{
  "icons": {
    "status/bulk.svg": {
      "name": "statusBulk",
      "partialAlpha": {
        "mode": "layers",
        "fallback": "opaque-only"
      }
    }
  }
}
```

`silhouette` keeps all nontransparent coverage in the normal IconData fallback.
`opaque-only` keeps only fully opaque coverage. The generated layered widget is
the lossless result; the normal single-glyph constant remains an explicit
fallback.

## Scale limits

One OpenType font can contain at most 65,534 generated glyphs. For a larger
library, shard by a stable semantic family into multiple configs and output
directories. Do not split merely to hide a failing source.

The basic private-use range beginning at U+E000 contains only 6,400 codepoints.
Count active entries plus tombstones before importing a large set. Do not move
an established start codepoint to gain capacity because that breaks the
existing ABI. Plan a separate stable family/config when the current range lacks
enough lifetime slots.

Raise discovery, byte, element, or path-command limits only after measuring the
trusted input and confirming that the higher bound is intentional. Limits are
part of the parser's safety boundary.
