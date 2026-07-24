# Flutter wiring and verification

Drive registration from `iconfont.report.json`, not assumed filenames.

## Register fonts

For each report font, join its relative `file` to the generated output
directory and register its exact `family` in `pubspec.yaml`:

```yaml
flutter:
  fonts:
    - family: AppIcons
      fonts:
        - asset: lib/generated/app_icons/fonts/AppIcons.otf
```

Add one entry for every object in `layerFonts`:

```yaml
    - family: AppIcons Layer 1
      fonts:
        - asset: lib/generated/app_icons/layer_fonts/layer_1.otf
```

Paths are examples. Use the report's actual values. Keep YAML indentation and
existing Flutter configuration intact.

For an application, generated IconData values must have no `fontPackage`. For
a reusable package, the config and generated provider must use the package
name, and verification should consume that package from a separate app when
practical.

## Use generated APIs

Import the generated Dart provider. Do not duplicate integer codepoints or
construct a parallel constants file.

Use the generated normal constant for monochrome output. Where a report glyph
has `layeredRendering`, use the generated layered descriptor/widget for exact
alpha. Its normal IconData constant is only the configured single-glyph
fallback.

## Static gates

After editing Dart or `pubspec.yaml`:

```bash
dart format <edited-dart-paths>
dart analyze <touched-scope>
flutter build <relevant-target>
```

Use full analysis for a small package or broad integration. In a large noisy
app, use the narrowest truthful analysis scope and report unrelated baseline
findings separately.

Confirm:

- report counts add up to the discovered source count
- each accepted source appears once in `glyphs`
- each omitted source appears in `skippedIcons`
- every primary and layer font exists and matches its report SHA-256
- the generated provider path exists and formats cleanly
- the lock remains committed and codepoints remain stable
- package/family metadata matches `pubspec.yaml`

## Runtime proof

Launch the target to a usable screen. A successful build is insufficient.

For a small set, render every generated icon beside or against its source SVG.
For a large set, render a complete searchable gallery and scan every entry,
then directly compare:

- every diagnostic and policy exception
- first and last codepoints
- additions, removals, and content-verified renames
- directional icons
- layered alpha icons
- unusually wide, tall, clipped, stroked, or transformed sources
- a representative sample from every source directory

Check for tofu, missing paint, empty glyphs, clipping, shifted baselines,
incorrect mirroring, and codepoint churn.

Release builds may subset fonts and therefore change the bundled file digest.
When subsetting occurs, verify registered family, asset path, required cmap
entries, shaping, and rendered glyphs rather than demanding byte identity with
the generated source font.

Record exactly which target, device or simulator, screen, and comparison method
were used. If GUI inspection is unavailable, use a deterministic widget or
golden render and state the remaining limitation. Never promote font parsing or
widget construction into visual proof.
