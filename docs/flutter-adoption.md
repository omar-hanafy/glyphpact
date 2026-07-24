# Flutter integration

GlyphPact generates an OpenType/CFF font, a tree-shakeable Dart provider, and
the metadata needed to verify that both remain in sync.

## App font

Compile into a directory inside the Flutter application:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons
```

Register the emitted font in `pubspec.yaml`:

```yaml
flutter:
  fonts:
    - family: AppIcons
      fonts:
        - asset: lib/generated/app_icons/fonts/AppIcons.otf
```

Then import `lib/generated/app_icons/app_icons.dart` and use the provider:

```dart
Icon(
  AppIcons.back,
  semanticLabel: 'Back',
)
```

## Package font

When the generated font lives in a Dart package, provide its package name:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons \
  --font-package my_icon_package
```

Keep the `family` entry in the package's `pubspec.yaml` equal to the configured
font family. The generated `IconData` constants include the package name so
Flutter resolves the asset correctly.

## Layered partial alpha

A normal icon font glyph cannot preserve multiple alpha values. GlyphPact can
represent an icon made from ordered solid-alpha regions with auxiliary
same-codepoint fonts.

Register the base font and each emitted layer family:

```yaml
flutter:
  fonts:
    - family: AppIcons
      fonts:
        - asset: lib/generated/app_icons/fonts/AppIcons.otf
    - family: AppIcons Layer 1
      fonts:
        - asset: lib/generated/app_icons/layer_fonts/layer_1.otf
    - family: AppIcons Layer 2
      fonts:
        - asset: lib/generated/app_icons/layer_fonts/layer_2.otf
```

Use the generated widget for exact ordered alpha:

```dart
AppIconsLayeredIcon(
  AppIconsLayers.verifiedLayers,
  size: 24,
  color: const Color(0xFF222222),
  semanticLabel: 'Verified',
)
```

The ordinary `IconData` remains available as the configured `silhouette` or
`opaque-only` fallback. The report records every layer's paint order, opacity,
family, file, codepoint, and font bounds.

## Accessibility

Generated `IconData` does not provide a label. Supply a localized
`semanticLabel` to `Icon`, use an appropriately labeled `IconButton`, or exclude
decorative icons from semantics.

## Source control

Commit the complete owned output:

- generated OTF fonts
- generated Dart
- `iconfont.lock.json`
- `iconfont.report.json`
- `ATTRIBUTION.md`
- the ownership marker

The lock is the codepoint ABI. Removing it can reassign icons even when the
source files have not changed.

## CI

After generating and committing the artifacts, verify that they are current:

```bash
glyphpact --config icon_font.json --check
```

`--check` rebuilds a candidate artifact set and compares it without rewriting
the owned output directory. It may create the output's parent directory and
leaves the sibling `.<output>.glyphpact.lock` coordination file in place. Exit
code `3` means checked-in output is stale.

For machine-readable CI output:

```bash
glyphpact --config icon_font.json --check --json
```

Successful JSON and report payloads use schema version 2. Check `quality`,
`policy`, glyph counts, skipped count, and typed issues rather than treating
every successful invocation as equivalent.
