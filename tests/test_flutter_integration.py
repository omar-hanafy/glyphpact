from __future__ import annotations

import json
import os
import shutil
import subprocess
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
) -> None:
    assert subset.is_file()
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
        assert set(font.getBestCmap() or {}) == codepoints
        assert font["OS/2"].fsType == 0
        assert {"CFF ", "OS/2", "cmap", "head", "hhea", "hmtx", "maxp", "name", "post"} <= set(
            font.keys()
        )
        cff_bbox = font["CFF "].cff.topDictIndex[0].FontBBox
        assert cff_bbox[1] == font["hhea"].descent
        assert cff_bbox[3] == font["hhea"].ascent
    finally:
        font.close()


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
        "zz_layered.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path opacity=".4" d="M2 2h8v8H2z"/>'
        '<path d="M14 14h8v8h-8z"/></svg>',
    )

    overrides = {
        "small.svg": IconOverride(match_text_direction=True),
        "zz_layered.svg": IconOverride(
            name="layered",
            partial_alpha=PartialAlphaConfig(),
        ),
    }
    app_result = build(
        BuildConfig(
            input_path=inputs,
            output_dir=tmp_path / "app-compiler-output",
            font_family="AppSmokeIcons",
            class_name="AppSmokeIcons",
            icons=overrides,
        ).validated()
    )
    package_result = build(
        BuildConfig(
            input_path=inputs,
            output_dir=tmp_path / "package-compiler-output",
            font_family="PackageSmokeIcons",
            class_name="PackageSmokeIcons",
            font_package="icon_font_fixture",
            icons=overrides,
        ).validated()
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
  sdk: '>=3.3.0 <4.0.0'
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
    app_layer_fonts = (
        project / "assets" / "fonts" / "AppSmokeIconsLayer1.otf",
        project / "assets" / "fonts" / "AppSmokeIconsLayer2.otf",
    )
    test_target = project / "test" / "icon_font_test.dart"
    web_index = project / "web" / "index.html"
    assert len(app_result.layer_font_paths) == len(app_layer_fonts)
    for path in (app_dart, app_font, *app_layer_fonts, test_target, web_index):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_result.dart_path, app_dart)
    shutil.copy2(app_result.font_path, app_font)
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
  sdk: '>=3.3.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  icon_font_fixture:
    path: ../icon_font_fixture
dev_dependencies:
  flutter_test:
    sdk: flutter
flutter:
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
        r"""import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:icon_font_fixture/icon_font_fixture.dart';
import 'package:icon_font_smoke/generated/app_smoke_icons.dart';

Future<
  ({
    int darkPixels,
    int minX,
    int minY,
    int maxX,
    int maxY,
    double baseline,
  })
>
rasterize(IconData icon) async {
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
  expect(painter.width, canvasSize);
  expect(painter.height, canvasSize);
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
    'app and package OTFs load and paint base and layered geometry',
    () async {
    expect(AppSmokeIcons.large.codePoint, 0xe000);
    expect(AppSmokeIcons.small.codePoint, 0xe001);
    expect(AppSmokeIcons.small.matchTextDirection, isTrue);
    expect(PackageSmokeIcons.large.fontPackage, 'icon_font_fixture');
    expect(AppSmokeIconsLayers.layered.fallback.codePoint, 0xe004);
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

    final appLarge = await rasterize(AppSmokeIcons.large);
    final appSmall = await rasterize(AppSmokeIcons.small);
    final appAlignment = await rasterize(AppSmokeIcons.verticalAlignment);
    final packageLarge = await rasterize(PackageSmokeIcons.large);
    final packageSmall = await rasterize(PackageSmokeIcons.small);
    final packageAlignment = await rasterize(
      PackageSmokeIcons.verticalAlignment,
    );
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
    await tester.pumpWidget(
      const Directionality(
        textDirection: TextDirection.ltr,
        child: Row(
          children: <Widget>[
            AppSmokeIconsLayeredIcon(
              AppSmokeIconsLayers.layered,
              size: 96,
            ),
            PackageSmokeIconsLayeredIcon(
              PackageSmokeIconsLayers.layered,
              size: 96,
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    final opacities = tester
        .widgetList<Opacity>(find.byType(Opacity))
        .map((widget) => widget.opacity);
    expect(opacities, <double>[0.4, 1.0, 0.4, 1.0]);
    final icons = tester.widgetList<Icon>(find.byType(Icon)).toList();
    expect(icons, hasLength(4));
    expect(
      icons.map((widget) => widget.icon!.fontFamily),
      <String>[
        'AppSmokeIcons Layer 1',
        'AppSmokeIcons Layer 2',
        'PackageSmokeIcons Layer 1',
        'PackageSmokeIcons Layer 2',
      ],
    );
    expect(tester.takeException(), isNull);
  });
}
""",
        encoding="utf-8",
    )

    app_before_format = app_dart.read_bytes()
    package_before_format = package_dart.read_bytes()
    _run([dart, "format", str(app_dart), str(package_dart)], project)
    assert app_dart.read_bytes() == app_before_format
    assert package_dart.read_bytes() == package_before_format

    _run([flutter, "pub", "get"], project)
    _run([flutter, "analyze", "--fatal-infos"], project)
    _run([flutter, "test", "--reporter", "expanded"], project)

    web_command = [flutter, "build", "web", "--release", "--no-pub"]
    if "--no-wasm-dry-run" in _run([flutter, "build", "web", "--help"], project):
        web_command.append("--no-wasm-dry-run")
    _run(web_command, project)

    web_assets = project / "build" / "web" / "assets"
    manifest = json.loads((web_assets / "FontManifest.json").read_text(encoding="utf-8"))
    assert {entry["family"] for entry in manifest} == {
        "AppSmokeIcons",
        "AppSmokeIcons Layer 1",
        "AppSmokeIcons Layer 2",
        "packages/icon_font_fixture/PackageSmokeIcons",
        "packages/icon_font_fixture/PackageSmokeIcons Layer 1",
        "packages/icon_font_fixture/PackageSmokeIcons Layer 2",
    }
    _assert_release_subset(
        app_font,
        web_assets / "assets" / "fonts" / "AppSmokeIcons.otf",
        codepoints={0xE000, 0xE004},
    )
    _assert_release_subset(
        app_layer_fonts[0],
        web_assets / "assets" / "fonts" / "AppSmokeIconsLayer1.otf",
        codepoints={0xE004},
    )
    _assert_release_subset(
        app_layer_fonts[1],
        web_assets / "assets" / "fonts" / "AppSmokeIconsLayer2.otf",
        codepoints={0xE004},
    )
    _assert_release_subset(
        package_font,
        web_assets
        / "packages"
        / "icon_font_fixture"
        / "assets"
        / "fonts"
        / "PackageSmokeIcons.otf",
        codepoints={0xE000, 0xE004},
    )
    _assert_release_subset(
        package_layer_fonts[0],
        web_assets
        / "packages"
        / "icon_font_fixture"
        / "assets"
        / "fonts"
        / "PackageSmokeIconsLayer1.otf",
        codepoints={0xE004},
    )
    _assert_release_subset(
        package_layer_fonts[1],
        web_assets
        / "packages"
        / "icon_font_fixture"
        / "assets"
        / "fonts"
        / "PackageSmokeIconsLayer2.otf",
        codepoints={0xE004},
    )
