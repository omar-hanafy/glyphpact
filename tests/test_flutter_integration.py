from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from conftest import write_svg
from fontTools.ttLib import TTFont

from glyphpact.builder import build
from glyphpact.config import BuildConfig, IconOverride, PartialAlphaConfig
from glyphpact.font_builder import _validate_sfnt_checksums


def _run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"{' '.join(command)} failed ({result.returncode}):\n{result.stdout}")
    return result.stdout


def _assert_release_subset(
    original: Path,
    subset: Path,
    *,
    codepoints: set[int],
    expect_smaller: bool = True,
) -> set[int]:
    assert subset.is_file()
    if expect_smaller:
        assert subset.stat().st_size < original.stat().st_size
    data = subset.read_bytes()
    font = TTFont(
        BytesIO(data),
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
        checkChecksums=2,
    )
    try:
        _validate_sfnt_checksums(data, font)
        assert font.sfntVersion == "OTTO"
        actual_codepoints = set(font.getBestCmap() or {})
        assert actual_codepoints == codepoints
        assert font["OS/2"].fsType == 0
        assert {"CFF ", "OS/2", "cmap", "head", "hhea", "hmtx", "maxp", "name", "post"} <= set(
            font.keys()
        )
        cff_bbox = font["CFF "].cff.topDictIndex[0].FontBBox
        assert cff_bbox[1] == font["hhea"].descent
        assert cff_bbox[3] == font["hhea"].ascent
        return actual_codepoints
    finally:
        font.close()


def _write_package_config(project: Path, *, language_version: str) -> None:
    package_config = project / ".dart_tool" / "package_config.json"
    package_config.parent.mkdir(parents=True, exist_ok=True)
    package_config.write_text(
        json.dumps(
            {
                "configVersion": 2,
                "packages": [
                    {
                        "name": "formatter_fixture",
                        "rootUri": "../",
                        "packageUri": "lib/",
                        "languageVersion": language_version,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.flutter
@pytest.mark.skipif(
    os.environ.get("RUN_DART_FORMAT_TESTS") != "1",
    reason="Set RUN_DART_FORMAT_TESTS=1 to run the Dart formatter compatibility gate.",
)
def test_catalog_is_stable_across_supported_dart_formatters(tmp_path: Path) -> None:
    dart = shutil.which("dart")
    if dart is None:
        pytest.skip("Dart is required")
    cached_dart = Path(dart).parent / "cache" / "dart-sdk" / "bin" / "dart"
    if cached_dart.is_file():
        dart = str(cached_dart)

    expected_dart_series = os.environ["EXPECTED_DART_SERIES"]
    language_version = os.environ["FORMATTER_LANGUAGE_VERSION"]
    marker_supported = os.environ["FORMATTER_MARKER_SUPPORTED"] == "1"
    version_output = _run([dart, "--version"], tmp_path)
    assert f"Dart SDK version: {expected_dart_series}." in version_output

    single_project = tmp_path / "single_formatter_fixture"
    single_inputs = tmp_path / "single_formatter_icon"
    write_svg(
        single_inputs,
        "icon.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect x="2" y="2" width="8" height="8"/></svg>',
    )
    single_config = BuildConfig(
        input_path=single_inputs,
        output_dir=single_project / "lib" / "generated",
        font_family="Ic",
        class_name="Ic",
        catalog=True,
        jobs=1,
    ).validated()
    single_result = build(single_config)
    assert len(json.loads(single_result.report_path.read_text(encoding="utf-8"))["glyphs"]) == 1
    _write_package_config(single_project, language_version=language_version)

    project = tmp_path / "large_formatter_fixture"
    inputs = tmp_path / "large_formatter_icons"
    max_class_name = "A" + ("b" * 39)
    max_plain_name = "c" + ("d" * 39)
    max_layered_name = "a" + ("b" * 39)
    overrides: dict[str, IconOverride] = {}
    for index in range(173):
        source = f"icon_{index:03d}.svg"
        write_svg(
            inputs,
            source,
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            f'<rect x="{index % 8 + 1}" y="2" width="8" height="8"/></svg>',
        )
        overrides[source] = IconOverride(name=max_plain_name if index == 0 else f"icon{index:03d}")
    layered_source = "zz_layered.svg"
    write_svg(
        inputs,
        layered_source,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect opacity=".4" x="2" y="2" width="8" height="8"/>'
        '<rect x="14" y="14" width="8" height="8"/></svg>',
    )
    overrides[layered_source] = IconOverride(
        name=max_layered_name,
        partial_alpha=PartialAlphaConfig(),
    )
    large_config = BuildConfig(
        input_path=inputs,
        output_dir=project / "lib" / "generated",
        font_family="F" * 63,
        class_name=max_class_name,
        font_package="p" * 100,
        catalog=True,
        icons=overrides,
        jobs=1,
    ).validated()
    large_result = build(large_config)
    assert len(json.loads(large_result.report_path.read_text(encoding="utf-8"))["glyphs"]) == 174
    large_dart = large_result.dart_path.read_text(encoding="utf-8")
    assert f"abstract final class {max_class_name}Catalog" in large_dart
    assert "layeredByName =" in large_dart
    assert max_plain_name in large_dart
    assert max_layered_name in large_dart
    _write_package_config(project, language_version=language_version)

    marker_probe = project / "lib" / "format_marker_probe.dart"
    marker_probe.parent.mkdir(parents=True, exist_ok=True)
    marker_probe.write_text(
        "// dart format off\nconst List<int> markerProbe=<int>[1,2,3];\n",
        encoding="utf-8",
    )
    generated_before = {
        single_result.dart_path: single_result.dart_path.read_bytes(),
        large_result.dart_path: large_result.dart_path.read_bytes(),
    }
    marker_before = marker_probe.read_bytes()

    _run([dart, "format", str(single_project / "lib")], single_project)
    _run([dart, "format", str(project / "lib")], project)

    for path, before in generated_before.items():
        after = path.read_bytes()
        if after != before:
            diff = "".join(
                difflib.unified_diff(
                    before.decode("utf-8").splitlines(keepends=True),
                    after.decode("utf-8").splitlines(keepends=True),
                    fromfile=f"{path.name}-before",
                    tofile=f"{path.name}-after",
                )
            )
            pytest.fail(f"dart format rewrote the generated catalog:\n{diff}")
    if marker_supported:
        assert marker_probe.read_bytes() == marker_before
    else:
        assert marker_probe.read_bytes() != marker_before
    assert build(single_config, check=True).checked
    assert build(large_config, check=True).checked


@pytest.mark.flutter
@pytest.mark.skipif(
    os.environ.get("RUN_FLUTTER_TESTS") != "1",
    reason="Set RUN_FLUTTER_TESTS=1 to run the Flutter integration gate.",
)
def test_generated_fonts_render_and_tree_shake_in_flutter(tmp_path: Path) -> None:
    flutter = shutil.which("flutter")
    dart = shutil.which("dart")
    if flutter is None or dart is None:
        pytest.skip("Flutter and Dart are required")

    inputs = tmp_path / "icons"
    write_svg(
        inputs,
        "large.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect x="2" y="2" width="20" height="20"/></svg>',
    )
    write_svg(
        inputs,
        "small.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect x="8" y="8" width="8" height="8"/></svg>',
    )
    write_svg(
        inputs,
        "this_is_a_deliberately_extremely_long_icon_filename_for_formatter_stability.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<circle cx="12" cy="12" r="6"/></svg>',
    )
    write_svg(
        inputs,
        "vertical_alignment.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="20" y="10" width="60" height="20"/></svg>',
    )
    write_svg(
        inputs,
        "yy_layered_second.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<circle opacity=".25" cx="6" cy="6" r="4"/>'
        '<rect x="14" y="14" width="8" height="8"/></svg>',
    )
    write_svg(
        inputs,
        "zz_layered.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path opacity=".4" d="M2 2h8v8H2z"/>'
        '<path d="M14 14h8v8h-8z"/></svg>',
    )

    overrides = {
        "small.svg": IconOverride(match_text_direction=True),
        "this_is_a_deliberately_extremely_long_icon_filename_for_formatter_stability.svg": (
            IconOverride(name="circle")
        ),
        "yy_layered_second.svg": IconOverride(
            name="second",
            partial_alpha=PartialAlphaConfig(),
        ),
        "zz_layered.svg": IconOverride(
            name="layered",
            partial_alpha=PartialAlphaConfig(),
        ),
    }
    app_config = BuildConfig(
        input_path=inputs,
        output_dir=tmp_path / "app-compiler-output",
        font_family="AppSmokeIcons",
        class_name="AppSmokeIcons",
        icons=overrides,
        catalog=True,
    ).validated()
    package_config = BuildConfig(
        input_path=inputs,
        output_dir=tmp_path / "package-compiler-output",
        font_family="PackageSmokeIcons",
        class_name="PackageSmokeIcons",
        font_package="icon_font_fixture",
        icons=overrides,
        catalog=True,
    ).validated()
    app_result = build(app_config)
    package_result = build(package_config)
    app_without_catalog_result = build(
        replace(
            app_config,
            output_dir=tmp_path / "app-without-catalog-output",
            catalog=False,
        ).validated()
    )
    package_without_catalog_result = build(
        replace(
            package_config,
            output_dir=tmp_path / "package-without-catalog-output",
            catalog=False,
        ).validated()
    )
    assert app_without_catalog_result.font_path.read_bytes() == app_result.font_path.read_bytes()
    assert (
        package_without_catalog_result.font_path.read_bytes()
        == package_result.font_path.read_bytes()
    )
    assert (
        app_without_catalog_result.report_path.read_bytes() == app_result.report_path.read_bytes()
    )
    assert (
        package_without_catalog_result.report_path.read_bytes()
        == package_result.report_path.read_bytes()
    )

    package = tmp_path / "icon_font_fixture"
    package_dart = package / "lib" / "generated" / "package_smoke_icons.dart"
    package_font = package / "assets" / "fonts" / "PackageSmokeIcons.otf"
    package_layer_fonts = (
        package / "assets" / "fonts" / "PackageSmokeIconsLayer1.otf",
        package / "assets" / "fonts" / "PackageSmokeIconsLayer2.otf",
    )
    assert len(package_result.layer_font_paths) == len(package_layer_fonts)
    for path in (package_dart, package_font, *package_layer_fonts):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package_result.dart_path, package_dart)
    shutil.copy2(package_result.font_path, package_font)
    for source, destination in zip(
        package_result.layer_font_paths,
        package_layer_fonts,
        strict=True,
    ):
        shutil.copy2(source, destination)
    (package / "lib" / "icon_font_fixture.dart").write_text(
        "export 'generated/package_smoke_icons.dart';\n",
        encoding="utf-8",
    )
    (package / "pubspec.yaml").write_text(
        """name: icon_font_fixture
description: Temporary package-font integration fixture.
version: 1.0.0
publish_to: none
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
flutter:
  fonts:
    - family: PackageSmokeIcons
      fonts:
        - asset: assets/fonts/PackageSmokeIcons.otf
    - family: PackageSmokeIcons Layer 1
      fonts:
        - asset: assets/fonts/PackageSmokeIconsLayer1.otf
    - family: PackageSmokeIcons Layer 2
      fonts:
        - asset: assets/fonts/PackageSmokeIconsLayer2.otf
""",
        encoding="utf-8",
    )

    project = tmp_path / "flutter_app"
    app_dart = project / "lib" / "generated" / "app_smoke_icons.dart"
    app_font = project / "assets" / "fonts" / "AppSmokeIcons.otf"
    app_report = project / "assets" / "iconfont.report.json"
    package_report = project / "assets" / "package-iconfont.report.json"
    app_layer_fonts = (
        project / "assets" / "fonts" / "AppSmokeIconsLayer1.otf",
        project / "assets" / "fonts" / "AppSmokeIconsLayer2.otf",
    )
    test_target = project / "test" / "icon_font_test.dart"
    web_index = project / "web" / "index.html"
    assert len(app_result.layer_font_paths) == len(app_layer_fonts)
    for path in (
        app_dart,
        app_font,
        app_report,
        package_report,
        *app_layer_fonts,
        test_target,
        web_index,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_result.dart_path, app_dart)
    shutil.copy2(app_result.font_path, app_font)
    shutil.copy2(app_result.report_path, app_report)
    shutil.copy2(package_result.report_path, package_report)
    for source, destination in zip(
        app_result.layer_font_paths,
        app_layer_fonts,
        strict=True,
    ):
        shutil.copy2(source, destination)

    (project / "pubspec.yaml").write_text(
        """name: icon_font_smoke
description: Temporary app-font integration fixture.
publish_to: none
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  icon_font_fixture:
    path: ../icon_font_fixture
dev_dependencies:
  flutter_test:
    sdk: flutter
flutter:
  assets:
    - assets/iconfont.report.json
    - assets/package-iconfont.report.json
  fonts:
    - family: AppSmokeIcons
      fonts:
        - asset: assets/fonts/AppSmokeIcons.otf
    - family: AppSmokeIcons Layer 1
      fonts:
        - asset: assets/fonts/AppSmokeIconsLayer1.otf
    - family: AppSmokeIcons Layer 2
      fonts:
        - asset: assets/fonts/AppSmokeIconsLayer2.otf
""",
        encoding="utf-8",
    )
    (project / "lib" / "main.dart").write_text(
        """import 'package:flutter/widgets.dart';
import 'package:icon_font_fixture/icon_font_fixture.dart';
import 'generated/app_smoke_icons.dart';

void main() => runApp(
  const Directionality(
    textDirection: TextDirection.ltr,
    child: Row(
      children: <Widget>[
        Icon(AppSmokeIcons.large),
        Icon(PackageSmokeIcons.large),
        AppSmokeIconsLayeredIcon(AppSmokeIconsLayers.layered),
        PackageSmokeIconsLayeredIcon(PackageSmokeIconsLayers.layered),
      ],
    ),
  ),
);
""",
        encoding="utf-8",
    )
    web_index.write_text(
        """<!doctype html>
<html>
<head><meta charset="UTF-8"><title>icon font smoke</title></head>
<body><script src="flutter_bootstrap.js" async></script></body>
</html>
""",
        encoding="utf-8",
    )
    test_target.write_text(
        r"""import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:icon_font_fixture/icon_font_fixture.dart';
import 'package:icon_font_smoke/generated/app_smoke_icons.dart';

typedef RasterResult = ({
  int darkPixels,
  int minX,
  int minY,
  int maxX,
  int maxY,
  double baseline,
});

Future<RasterResult> rasterize(IconData icon) async {
  const canvasSize = 100;
  final recorder = ui.PictureRecorder();
  final canvas = ui.Canvas(recorder);
  final painter = TextPainter(
    text: TextSpan(
      text: String.fromCharCode(icon.codePoint),
      style: TextStyle(
        color: const Color(0xff000000),
        fontFamily: icon.fontFamily,
        package: icon.fontPackage,
        fontSize: canvasSize.toDouble(),
        height: 1,
        leadingDistribution: TextLeadingDistribution.even,
      ),
    ),
    textDirection: TextDirection.ltr,
  )..layout();
  final baseline = painter.computeDistanceToActualBaseline(
    TextBaseline.alphabetic,
  );
  expect(painter.width, closeTo(canvasSize, 0.01));
  expect(painter.height, closeTo(canvasSize, 0.01));
  painter.paint(canvas, ui.Offset.zero);
  painter.dispose();
  final picture = recorder.endRecording();
  final image = await picture.toImage(canvasSize, canvasSize);
  picture.dispose();
  final data = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
  var darkPixels = 0;
  var minX = canvasSize;
  var minY = canvasSize;
  var maxX = -1;
  var maxY = -1;
  for (var y = 0; y < canvasSize; y++) {
    for (var x = 0; x < canvasSize; x++) {
      final offset = (y * canvasSize + x) * 4;
      if (data.getUint8(offset + 3) > 128 && data.getUint8(offset) < 64) {
        darkPixels++;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }
  }
  image.dispose();
  return (
    darkPixels: darkPixels,
    minX: minX,
    minY: minY,
    maxX: maxX,
    maxY: maxY,
    baseline: baseline,
  );
}

Future<void> loadFont(String asset, String family) async {
  final bytes = await rootBundle.load(asset);
  await (FontLoader(family)..addFont(Future.value(bytes))).load();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'catalog matches the report and every emitted glyph paints',
    () async {
    expect(AppSmokeIcons.large.codePoint, 0xe000);
    expect(AppSmokeIcons.small.codePoint, 0xe001);
    expect(AppSmokeIcons.small.matchTextDirection, isTrue);

    final report =
        jsonDecode(
              await rootBundle.loadString('assets/iconfont.report.json'),
            )
            as Map<String, dynamic>;
    final reportFont = report['font'] as Map<String, dynamic>;
    final reportDart = report['dart'] as Map<String, dynamic>;
    final reportGlyphs = (report['glyphs'] as List<dynamic>)
        .cast<Map<String, dynamic>>();
    final reportNames = reportGlyphs
        .map((glyph) => glyph['name'] as String)
        .toList();
    final reportCodePoints = reportGlyphs
        .map(
          (glyph) => int.parse(
            (glyph['codepoint'] as String).substring(2),
            radix: 16,
          ),
        )
        .toList();
    const appProviderByName = <String, IconData>{
      'large': AppSmokeIcons.large,
      'small': AppSmokeIcons.small,
      'circle': AppSmokeIcons.circle,
      'verticalAlignment': AppSmokeIcons.verticalAlignment,
      'second': AppSmokeIcons.second,
      'layered': AppSmokeIcons.layered,
    };

    expect(
      AppSmokeIconsCatalog.byName.keys,
      orderedEquals(reportNames),
    );
    expect(
      AppSmokeIconsCatalog.byName.values.map((icon) => icon.codePoint),
      orderedEquals(reportCodePoints),
    );
    expect(
      reportCodePoints,
      orderedEquals([...reportCodePoints]..sort()),
    );
    expect(appProviderByName.keys, orderedEquals(reportNames));
    for (final entry in AppSmokeIconsCatalog.byName.entries) {
      expect(entry.value, same(appProviderByName[entry.key]));
    }
    for (final glyph in reportGlyphs) {
      final icon = AppSmokeIconsCatalog.byName[glyph['name']]!;
      expect(icon.codePoint, reportCodePoints[reportGlyphs.indexOf(glyph)]);
      expect(icon.fontFamily, reportFont['family']);
      expect(icon.fontPackage, reportDart['fontPackage']);
      expect(icon.matchTextDirection, glyph['matchTextDirection']);
    }

    final reportLayeredNames = reportGlyphs
        .where((glyph) => glyph.containsKey('layeredRendering'))
        .map((glyph) => glyph['name'] as String)
        .toList();
    expect(
      AppSmokeIconsCatalog.layeredByName.keys,
      orderedEquals(reportLayeredNames),
    );
    expect(
      AppSmokeIconsCatalog.layeredByName['layered'],
      same(AppSmokeIconsLayers.layered),
    );
    expect(
      AppSmokeIconsCatalog.layeredByName['second'],
      same(AppSmokeIconsLayers.second),
    );
    expect(AppSmokeIconsCatalog.layeredByName.keys, isNot(contains('large')));
    for (final entry in AppSmokeIconsCatalog.layeredByName.entries) {
      final glyph = reportGlyphs.singleWhere(
        (glyph) => glyph['name'] == entry.key,
      );
      final rendering = glyph['layeredRendering'] as Map<String, dynamic>;
      final layers = (rendering['layers'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
      expect(
        entry.value.fallback,
        same(AppSmokeIconsCatalog.byName[entry.key]),
      );
      expect(
        entry.value.layers.map((layer) => layer.icon.codePoint),
        orderedEquals(
          layers.map(
            (layer) => int.parse(
              (layer['codepoint'] as String).substring(2),
              radix: 16,
            ),
          ),
        ),
      );
      expect(
        entry.value.layers.map((layer) => layer.icon.fontFamily),
        orderedEquals(layers.map((layer) => layer['fontFamily'])),
      );
      expect(
        entry.value.layers.map((layer) => layer.icon.fontPackage),
        orderedEquals(layers.map((_) => reportDart['fontPackage'])),
      );
      expect(
        entry.value.layers.map((layer) => layer.opacity),
        orderedEquals(layers.map((layer) => layer['opacity'])),
      );
    }

    final packageReport =
        jsonDecode(
              await rootBundle.loadString(
                'assets/package-iconfont.report.json',
              ),
            )
            as Map<String, dynamic>;
    final packageReportFont =
        packageReport['font'] as Map<String, dynamic>;
    final packageReportDart =
        packageReport['dart'] as Map<String, dynamic>;
    final packageReportGlyphs =
        (packageReport['glyphs'] as List<dynamic>)
            .cast<Map<String, dynamic>>();
    final packageReportNames = packageReportGlyphs
        .map((glyph) => glyph['name'] as String)
        .toList();
    final packageReportCodePoints = packageReportGlyphs
        .map(
          (glyph) => int.parse(
            (glyph['codepoint'] as String).substring(2),
            radix: 16,
          ),
        )
        .toList();
    const packageProviderByName = <String, IconData>{
      'large': PackageSmokeIcons.large,
      'small': PackageSmokeIcons.small,
      'circle': PackageSmokeIcons.circle,
      'verticalAlignment': PackageSmokeIcons.verticalAlignment,
      'second': PackageSmokeIcons.second,
      'layered': PackageSmokeIcons.layered,
    };
    expect(
      PackageSmokeIconsCatalog.byName.keys,
      orderedEquals(packageReportNames),
    );
    expect(
      PackageSmokeIconsCatalog.byName.values.map(
        (icon) => icon.codePoint,
      ),
      orderedEquals(packageReportCodePoints),
    );
    expect(packageProviderByName.keys, orderedEquals(packageReportNames));
    for (final entry in PackageSmokeIconsCatalog.byName.entries) {
      expect(entry.value, same(packageProviderByName[entry.key]));
    }
    for (final glyph in packageReportGlyphs) {
      final icon = PackageSmokeIconsCatalog.byName[glyph['name']]!;
      expect(
        icon.codePoint,
        packageReportCodePoints[packageReportGlyphs.indexOf(glyph)],
      );
      expect(icon.fontFamily, packageReportFont['family']);
      expect(icon.fontPackage, packageReportDart['fontPackage']);
      expect(icon.matchTextDirection, glyph['matchTextDirection']);
    }
    final packageReportLayeredNames = packageReportGlyphs
        .where((glyph) => glyph.containsKey('layeredRendering'))
        .map((glyph) => glyph['name'] as String)
        .toList();
    expect(
      PackageSmokeIconsCatalog.layeredByName.keys,
      orderedEquals(packageReportLayeredNames),
    );
    for (final entry in PackageSmokeIconsCatalog.layeredByName.entries) {
      final glyph = packageReportGlyphs.singleWhere(
        (glyph) => glyph['name'] == entry.key,
      );
      final rendering = glyph['layeredRendering'] as Map<String, dynamic>;
      final layers = (rendering['layers'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
      expect(
        entry.value.fallback,
        same(PackageSmokeIconsCatalog.byName[entry.key]),
      );
      expect(
        entry.value.layers.map((layer) => layer.icon.codePoint),
        orderedEquals(
          layers.map(
            (layer) => int.parse(
              (layer['codepoint'] as String).substring(2),
              radix: 16,
            ),
          ),
        ),
      );
      expect(
        entry.value.layers.map((layer) => layer.icon.fontFamily),
        orderedEquals(layers.map((layer) => layer['fontFamily'])),
      );
      expect(
        entry.value.layers.map((layer) => layer.icon.fontPackage),
        orderedEquals(layers.map((_) => packageReportDart['fontPackage'])),
      );
      expect(
        entry.value.layers.map((layer) => layer.opacity),
        orderedEquals(layers.map((layer) => layer['opacity'])),
      );
    }

    expect(PackageSmokeIcons.large.fontPackage, 'icon_font_fixture');
    expect(
      AppSmokeIconsLayers.layered.layers.map((layer) => layer.opacity),
      <double>[0.4, 1.0],
    );
    expect(
      PackageSmokeIconsLayers.layered.layers.map(
        (layer) => layer.icon.fontPackage,
      ),
      <String?>['icon_font_fixture', 'icon_font_fixture'],
    );

    await loadFont(
      'assets/fonts/AppSmokeIcons.otf',
      'AppSmokeIcons',
    );
    await loadFont(
      'packages/icon_font_fixture/assets/fonts/PackageSmokeIcons.otf',
      'packages/icon_font_fixture/PackageSmokeIcons',
    );
    await loadFont(
      'assets/fonts/AppSmokeIconsLayer1.otf',
      'AppSmokeIcons Layer 1',
    );
    await loadFont(
      'assets/fonts/AppSmokeIconsLayer2.otf',
      'AppSmokeIcons Layer 2',
    );
    await loadFont(
      'packages/icon_font_fixture/assets/fonts/PackageSmokeIconsLayer1.otf',
      'packages/icon_font_fixture/PackageSmokeIcons Layer 1',
    );
    await loadFont(
      'packages/icon_font_fixture/assets/fonts/PackageSmokeIconsLayer2.otf',
      'packages/icon_font_fixture/PackageSmokeIcons Layer 2',
    );

    final appRasterByName = <String, RasterResult>{};
    for (final entry in AppSmokeIconsCatalog.byName.entries) {
      final raster = await rasterize(entry.value);
      expect(
        raster.darkPixels,
        greaterThan(0),
        reason: '${entry.key} did not paint from the loaded base font',
      );
      appRasterByName[entry.key] = raster;
    }
    for (final entry in AppSmokeIconsCatalog.layeredByName.entries) {
      for (var index = 0; index < entry.value.layers.length; index++) {
        final raster = await rasterize(entry.value.layers[index].icon);
        expect(
          raster.darkPixels,
          greaterThan(0),
          reason: '${entry.key} layer $index did not paint from its loaded font',
        );
      }
    }
    final packageRasterByName = <String, RasterResult>{};
    for (final entry in PackageSmokeIconsCatalog.byName.entries) {
      final raster = await rasterize(entry.value);
      expect(
        raster.darkPixels,
        greaterThan(0),
        reason: '${entry.key} did not paint from the loaded package base font',
      );
      packageRasterByName[entry.key] = raster;
    }
    for (final entry in PackageSmokeIconsCatalog.layeredByName.entries) {
      for (var index = 0; index < entry.value.layers.length; index++) {
        final raster = await rasterize(entry.value.layers[index].icon);
        expect(
          raster.darkPixels,
          greaterThan(0),
          reason:
              '${entry.key} package layer $index did not paint from its loaded font',
        );
      }
    }

    final appLarge = appRasterByName['large']!;
    final appSmall = appRasterByName['small']!;
    final appAlignment = appRasterByName['verticalAlignment']!;
    final packageLarge = packageRasterByName['large']!;
    final packageSmall = packageRasterByName['small']!;
    final packageAlignment = packageRasterByName['verticalAlignment']!;
    final appPartialLayer = await rasterize(
      AppSmokeIconsLayers.layered.layers[0].icon,
    );
    final appOpaqueLayer = await rasterize(
      AppSmokeIconsLayers.layered.layers[1].icon,
    );
    final packagePartialLayer = await rasterize(
      PackageSmokeIconsLayers.layered.layers[0].icon,
    );
    final packageOpaqueLayer = await rasterize(
      PackageSmokeIconsLayers.layered.layers[1].icon,
    );

    // Missing/fallback PUA glyphs paint the same tofu box or nothing. These
    // source rectangles have deliberately very different painted areas.
    expect(appSmall.darkPixels, greaterThan(500));
    expect(appLarge.darkPixels, greaterThan(appSmall.darkPixels * 4));
    expect(packageSmall.darkPixels, greaterThan(500));
    expect(
      packageLarge.darkPixels,
      greaterThan(packageSmall.darkPixels * 4),
    );
    expect(
      (appLarge.darkPixels - packageLarge.darkPixels).abs(),
      lessThan(30),
    );
    expect(
      (appSmall.darkPixels - packageSmall.darkPixels).abs(),
      lessThan(30),
    );

    // Flutter's Icon widget uses these same height and leading settings.
    // The declared SVG rectangle is x=20..80 and y=10..30 in a 100x100
    // viewBox, so the CFF metric envelope must not move it toward the baseline.
    for (final alignment in [appAlignment, packageAlignment]) {
      expect(alignment.minX, inInclusiveRange(19, 20));
      expect(alignment.minY, inInclusiveRange(9, 10));
      expect(alignment.maxX, inInclusiveRange(79, 80));
      expect(alignment.maxY, inInclusiveRange(29, 30));
      expect(alignment.baseline, closeTo(100, 0.01));
    }

    for (final partial in [appPartialLayer, packagePartialLayer]) {
      expect(partial.darkPixels, greaterThan(900));
      expect(partial.minX, inInclusiveRange(8, 9));
      expect(partial.minY, inInclusiveRange(8, 9));
      expect(partial.maxX, inInclusiveRange(41, 42));
      expect(partial.maxY, inInclusiveRange(41, 42));
    }
    for (final opaque in [appOpaqueLayer, packageOpaqueLayer]) {
      expect(opaque.darkPixels, greaterThan(900));
      expect(opaque.minX, inInclusiveRange(58, 59));
      expect(opaque.minY, inInclusiveRange(58, 59));
      expect(opaque.maxX, inInclusiveRange(91, 92));
      expect(opaque.maxY, inInclusiveRange(91, 92));
    }
  });

  testWidgets('generated layered widgets render ordered alpha layers', (
    tester,
  ) async {
    final expectedOpacities = <double>[
      for (final descriptor in AppSmokeIconsCatalog.layeredByName.values)
        for (final layer in descriptor.layers) layer.opacity,
      for (final descriptor in PackageSmokeIconsCatalog.layeredByName.values)
        for (final layer in descriptor.layers) layer.opacity,
    ];
    final expectedFamilies = <String?>[
      for (final descriptor in AppSmokeIconsCatalog.layeredByName.values)
        for (final layer in descriptor.layers) layer.icon.fontFamily,
      for (final descriptor in PackageSmokeIconsCatalog.layeredByName.values)
        for (final layer in descriptor.layers) layer.icon.fontFamily,
    ];
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: Row(
          children: <Widget>[
            for (final descriptor
                in AppSmokeIconsCatalog.layeredByName.values)
              AppSmokeIconsLayeredIcon(descriptor, size: 96),
            for (final descriptor
                in PackageSmokeIconsCatalog.layeredByName.values)
              PackageSmokeIconsLayeredIcon(descriptor, size: 96),
          ],
        ),
      ),
    );
    await tester.pump();

    final opacities = tester
        .widgetList<Opacity>(find.byType(Opacity))
        .map((widget) => widget.opacity);
    expect(
      opacities,
      expectedOpacities,
    );
    final icons = tester.widgetList<Icon>(find.byType(Icon)).toList();
    expect(icons, hasLength(expectedFamilies.length));
    expect(
      icons.map((widget) => widget.icon!.fontFamily),
      expectedFamilies,
    );
    expect(tester.takeException(), isNull);
  });
}
""",
        encoding="utf-8",
    )

    _run([flutter, "pub", "get"], package)
    _run([flutter, "pub", "get"], project)

    # Generate package_config first so dart format uses the fixture's Dart 3.0
    # language version. That line ignores format-off markers, so byte stability
    # here proves the generated fallback layout as well as the modern marker.
    formatted_targets = (app_dart, package_dart)
    before_format = {path: path.read_bytes() for path in formatted_targets}
    _run([dart, "format", str(project / "lib"), str(package / "lib")], project)
    for path, original in before_format.items():
        assert path.read_bytes() == original, f"dart format rewrote {path.name}"

    _run([dart, "analyze"], package)
    _run([dart, "analyze"], project)
    _run([flutter, "analyze", "--fatal-infos"], project)
    _run([flutter, "test", "--reporter", "expanded"], project)

    web_command = [flutter, "build", "web", "--release", "--no-pub"]
    if "--no-wasm-dry-run" in _run([flutter, "build", "web", "--help"], project):
        web_command.append("--no-wasm-dry-run")

    app_report_data = json.loads(app_report.read_text(encoding="utf-8"))
    package_report_data = json.loads(package_report.read_text(encoding="utf-8"))
    app_codepoints = {
        glyph["name"]: int(glyph["codepoint"], 16) for glyph in app_report_data["glyphs"]
    }
    package_codepoints = {
        glyph["name"]: int(glyph["codepoint"], 16) for glyph in package_report_data["glyphs"]
    }
    app_layered_codepoints = {
        int(glyph["codepoint"], 16)
        for glyph in app_report_data["glyphs"]
        if "layeredRendering" in glyph
    }
    package_layered_codepoints = {
        int(glyph["codepoint"], 16)
        for glyph in package_report_data["glyphs"]
        if "layeredRendering" in glyph
    }
    assert len(app_codepoints) == 6
    assert len(app_layered_codepoints) == 2
    assert app_codepoints == package_codepoints
    assert app_layered_codepoints == package_layered_codepoints

    expected_families = {
        "AppSmokeIcons",
        "AppSmokeIcons Layer 1",
        "AppSmokeIcons Layer 2",
        "packages/icon_font_fixture/PackageSmokeIcons",
        "packages/icon_font_fixture/PackageSmokeIcons Layer 1",
        "packages/icon_font_fixture/PackageSmokeIcons Layer 2",
    }
    direct_package_base = {
        package_codepoints["large"],
        package_codepoints["layered"],
    }
    direct_package_layers = {package_codepoints["layered"]}

    def assert_release_variant(
        *,
        app_base_codepoints: set[int],
        app_layer_codepoints: set[int],
        package_base_codepoints: set[int],
        package_layer_codepoints: set[int],
    ) -> dict[str, set[int]]:
        actual: dict[str, set[int]] = {}
        web_assets = project / "build" / "web" / "assets"
        manifest = json.loads((web_assets / "FontManifest.json").read_text(encoding="utf-8"))
        assert {entry["family"] for entry in manifest} == expected_families
        actual["app-base"] = _assert_release_subset(
            app_font,
            web_assets / "assets" / "fonts" / "AppSmokeIcons.otf",
            codepoints=app_base_codepoints,
            expect_smaller=app_base_codepoints != set(app_codepoints.values()),
        )
        for original, filename in zip(
            app_layer_fonts,
            ("AppSmokeIconsLayer1.otf", "AppSmokeIconsLayer2.otf"),
            strict=True,
        ):
            actual[f"app-{filename}"] = _assert_release_subset(
                original,
                web_assets / "assets" / "fonts" / filename,
                codepoints=app_layer_codepoints,
                expect_smaller=app_layer_codepoints != app_layered_codepoints,
            )
        actual["package-base"] = _assert_release_subset(
            package_font,
            web_assets
            / "packages"
            / "icon_font_fixture"
            / "assets"
            / "fonts"
            / "PackageSmokeIcons.otf",
            codepoints=package_base_codepoints,
            expect_smaller=package_base_codepoints != set(package_codepoints.values()),
        )
        for original, filename in zip(
            package_layer_fonts,
            ("PackageSmokeIconsLayer1.otf", "PackageSmokeIconsLayer2.otf"),
            strict=True,
        ):
            actual[f"package-{filename}"] = _assert_release_subset(
                original,
                web_assets / "packages" / "icon_font_fixture" / "assets" / "fonts" / filename,
                codepoints=package_layer_codepoints,
                expect_smaller=package_layer_codepoints != package_layered_codepoints,
            )
        return actual

    direct_app_base = {
        app_codepoints["large"],
        app_codepoints["layered"],
    }
    direct_app_layers = {app_codepoints["layered"]}
    enabled_app_dart = app_dart.read_bytes()
    enabled_package_dart = package_dart.read_bytes()

    # First prove the direct-reference baseline with catalog generation disabled
    # for both the app-owned and reusable-package fonts.
    shutil.copy2(app_without_catalog_result.dart_path, app_dart)
    shutil.copy2(package_without_catalog_result.dart_path, package_dart)
    _run(web_command, project)
    disabled_cmaps = assert_release_variant(
        app_base_codepoints=direct_app_base,
        app_layer_codepoints=direct_app_layers,
        package_base_codepoints=direct_package_base,
        package_layer_codepoints=direct_package_layers,
    )

    # Merely emitting and importing both catalogs has exactly the same cmap
    # reachability as the catalog-disabled build.
    app_dart.write_bytes(enabled_app_dart)
    package_dart.write_bytes(enabled_package_dart)
    _run(web_command, project)
    unused_cmaps = assert_release_variant(
        app_base_codepoints=direct_app_base,
        app_layer_codepoints=direct_app_layers,
        package_base_codepoints=direct_package_base,
        package_layer_codepoints=direct_package_layers,
    )
    assert unused_cmaps == disabled_cmaps

    # Shipping iteration over byName retains every base-font glyph, but it does
    # not make the other layered descriptor reachable.
    (project / "lib" / "main.dart").write_text(
        """import 'package:flutter/widgets.dart';
import 'package:icon_font_fixture/icon_font_fixture.dart';
import 'generated/app_smoke_icons.dart';

void main() => runApp(
  Directionality(
    textDirection: TextDirection.ltr,
    child: Column(
      children: <Widget>[
        for (final entry in AppSmokeIconsCatalog.byName.entries)
          Icon(entry.value),
        for (final entry in PackageSmokeIconsCatalog.byName.entries)
          Icon(entry.value),
        const AppSmokeIconsLayeredIcon(AppSmokeIconsLayers.layered),
        const PackageSmokeIconsLayeredIcon(PackageSmokeIconsLayers.layered),
      ],
    ),
  ),
);
""",
        encoding="utf-8",
    )
    _run(web_command, project)
    assert_release_variant(
        app_base_codepoints=set(app_codepoints.values()),
        app_layer_codepoints={app_codepoints["layered"]},
        package_base_codepoints=set(package_codepoints.values()),
        package_layer_codepoints={package_codepoints["layered"]},
    )

    # Shipping iteration over layeredByName retains each layered fallback and
    # all corresponding layer glyphs, while ordinary base glyphs remain absent.
    (project / "lib" / "main.dart").write_text(
        """import 'package:flutter/widgets.dart';
import 'package:icon_font_fixture/icon_font_fixture.dart';
import 'generated/app_smoke_icons.dart';

void main() => runApp(
  Directionality(
    textDirection: TextDirection.ltr,
    child: Column(
      children: <Widget>[
        for (final descriptor in AppSmokeIconsCatalog.layeredByName.values)
          AppSmokeIconsLayeredIcon(descriptor),
        for (final descriptor in PackageSmokeIconsCatalog.layeredByName.values)
          PackageSmokeIconsLayeredIcon(descriptor),
        const Icon(PackageSmokeIcons.large),
      ],
    ),
  ),
);
""",
        encoding="utf-8",
    )
    _run(web_command, project)
    assert_release_variant(
        app_base_codepoints=app_layered_codepoints,
        app_layer_codepoints=app_layered_codepoints,
        package_base_codepoints=package_layered_codepoints | {package_codepoints["large"]},
        package_layer_codepoints=package_layered_codepoints,
    )

    # Using both maps combines their reachability: every base glyph and every
    # generated layer glyph is retained.
    (project / "lib" / "main.dart").write_text(
        """import 'package:flutter/widgets.dart';
import 'package:icon_font_fixture/icon_font_fixture.dart';
import 'generated/app_smoke_icons.dart';

void main() => runApp(
  Directionality(
    textDirection: TextDirection.ltr,
    child: Column(
      children: <Widget>[
        for (final icon in AppSmokeIconsCatalog.byName.values) Icon(icon),
        for (final descriptor in AppSmokeIconsCatalog.layeredByName.values)
          AppSmokeIconsLayeredIcon(descriptor),
        for (final icon in PackageSmokeIconsCatalog.byName.values) Icon(icon),
        for (final descriptor in PackageSmokeIconsCatalog.layeredByName.values)
          PackageSmokeIconsLayeredIcon(descriptor),
      ],
    ),
  ),
);
""",
        encoding="utf-8",
    )
    _run(web_command, project)
    assert_release_variant(
        app_base_codepoints=set(app_codepoints.values()),
        app_layer_codepoints=app_layered_codepoints,
        package_base_codepoints=set(package_codepoints.values()),
        package_layer_codepoints=package_layered_codepoints,
    )
