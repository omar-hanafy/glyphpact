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

## Enumerating every icon

Enable the generated catalog when runtime or test code needs every glyph by its
Dart name:

```json
{
  "catalog": true
}
```

GlyphPact adds a separate `AppIconsCatalog` companion to the existing generated
Dart library. It contains only static const maps and is annotated so Flutter
ignores unreachable catalog declarations while continuing to discover the
values of a reachable map. `AppIconsCatalog.byName` is a
`Map<String, IconData>` containing every emitted glyph in ascending codepoint
order. Packs with partial-alpha icons also get
`AppIconsCatalog.layeredByName`, containing only their layered descriptors.
Their static-const `AppIconsLayers` descriptor provider is annotated separately
so a direct reference to one layered descriptor does not retain its siblings.

Use the map directly for galleries and pickers, or derive the shape a call site
needs:

```dart
for (final MapEntry(key: name, value: icon) in
    AppIconsCatalog.byName.entries) {
  print('$name: U+${icon.codePoint.toRadixString(16).toUpperCase()}');
}
```

Other common projections are `byName.keys`, `byName.values`,
`byName.entries`, `byName.keys.toList()`, and `byName.values.toSet()`. Copy to a
list before applying consumer-specific sorting.

Emitting the catalog does not itself change release subsetting. If the catalog
is unreachable, Flutter removes it and retains only individually referenced
provider constants. A reachable `byName` retains every base glyph. A reachable
`layeredByName` retains those icons' fallbacks and layer-font glyphs. Catalog
references confined to `test/` have no release cost.

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

Successful CLI JSON uses schema version 2. Deterministic reports use schema
version 3 and add `codepointsRemaining` plus `rangeUtilization`; lockfiles
remain schema version 1. Check `quality`, `policy`, glyph counts, skipped count,
typed issues, and remaining allocation capacity rather than treating every
successful invocation as equivalent. At or above 80% utilization, build and
check still exit successfully but emit `CODEPOINT_RANGE_NEAR_EXHAUSTION` to
stderr. The report schema still validates historical v1 and v2 payloads, but
custom generators must add v3 support before upgrading to GlyphPact 1.1.

## Report-driven custom generation

The built-in catalog is the standard Dart enumeration API. Use
`iconfont.report.json` as the stable lower-level input when another language or
collection shape is required. Check `schemaVersion`, then read the font and Dart
provider fields plus the codepoint-ordered `glyphs` records.

`glyphs` contains active shipped glyphs only, ordered by ascending codepoint.
Report codepoints are uppercase hexadecimal strings such as `0xE000`. Parse
them only in build-time code generation or artifact tests:

```dart
final codepoint = int.parse(
  reportGlyph['codepoint'].substring(2),
  radix: 16,
);
```

Generated Dart should import the reported provider file and reference its
constants instead of constructing `IconData` dynamically at runtime.

The configured output directory is exclusively owned by GlyphPact. A custom
generator must write outside it, run after the GlyphPact build, and provide its
own non-rewriting drift check. A useful application test compares its generated
names and codepoints with `report['glyphs']`, then loads the reported fonts and
renders every generated icon.

For an app-owned font, the following Flutter test covers that complete base-font
surface:

```dart
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:my_app/generated/app_icons/app_icons.dart';

void main() {
  testWidgets('catalog matches the report and every glyph paints', (tester) async {
    const output = 'lib/generated/app_icons';
    final report = jsonDecode(
      await File('$output/iconfont.report.json').readAsString(),
    ) as Map<String, dynamic>;
    final font = report['font'] as Map<String, dynamic>;
    final dart = report['dart'] as Map<String, dynamic>;
    final glyphs = <String, Map<String, dynamic>>{
      for (final value in report['glyphs'] as List<dynamic>)
        (value as Map<String, dynamic>)['name'] as String: value,
    };

    expect(AppIconsCatalog.byName.keys, orderedEquals(glyphs.keys));

    final fontBytes = await File('$output/${font['file']}').readAsBytes();
    await (FontLoader(font['family'] as String)
          ..addFont(Future<ByteData>.value(ByteData.sublistView(fontBytes))))
        .load();

    final boundaryKey = GlobalKey();
    for (final entry in AppIconsCatalog.byName.entries) {
      final glyph = glyphs[entry.key]!;
      final encodedCodepoint = glyph['codepoint'] as String;
      expect(
        entry.value.codePoint,
        int.parse(encodedCodepoint.substring(2), radix: 16),
      );
      expect(entry.value.fontFamily, font['family']);
      expect(entry.value.fontPackage, dart['fontPackage']);
      expect(entry.value.matchTextDirection, glyph['matchTextDirection']);

      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: RepaintBoundary(
            key: boundaryKey,
            child: Icon(entry.value, size: 32),
          ),
        ),
      );
      await tester.pump();
      final boundary =
          boundaryKey.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 2);
      final pixels = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      expect(
        pixels!.buffer.asUint8List().any((byte) => byte != 0),
        isTrue,
        reason: entry.key,
      );
      image.dispose();
    }
  });
}
```

For a layered pack, load each `layerFonts[].family` and `layerFonts[].file` the
same way, then render every `AppIconsCatalog.layeredByName` descriptor through
the generated layered widget.
