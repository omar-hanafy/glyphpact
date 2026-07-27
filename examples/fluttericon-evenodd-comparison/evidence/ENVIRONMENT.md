# Preserved environment

- Capture date: 2026-07-26
- FlutterIcon.com: export downloaded on 2026-07-26; no application version was
  present in the bundle
- GlyphPact: 1.0.1
- Flutter: 3.44.4
- Dart: 3.12.2
- Source viewport used by the comparison app: 1440 logical pixels wide
- Native capture: 1291 x 768 PNG
- Web-safe sRGB derivative: 1291 x 768 PNG, metadata stripped
- Preserved 2x CleanShot: 3346 x 2082 PNG
- Deterministic article table: 1600 x 1280 PNG from an 800 x 640 logical canvas
- Deterministic article cover: 2000 x 840 PNG from a 1000 x 420 logical canvas

`FlutterIcon.ttf` identifies itself as font version 1.0. That is generic font
metadata and must not be presented as the FlutterIcon.com application version.

The FlutterIcon config retains normalized path data for each fixture but does
not carry the source `fill-rule`. The visual claim is based on the font rendered
through its generated `IconData`, beside the original SVG and GlyphPact output.

The screenshot uses "OpenType" as shorthand for the GlyphPact output. The exact
formats are FlutterIcon TTF with TrueType outlines and GlyphPact OTF with CFF
outlines. TTF can also be an OpenType font, so this reproduction does not claim
that one container format is inherently more faithful than the other.

The deterministic article graphics use the bundled Geist font, the exact source
SVG assets through `flutter_svg`, and both retained icon fonts through their
generated `IconData`. No screenshot scaling or generated approximation is used.
