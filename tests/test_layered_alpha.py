from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from conftest import write_svg
from fontTools.ttLib import TTFont

from glyphpact.builder import build
from glyphpact.config import (
    BuildConfig,
    ConversionPolicy,
    IconOverride,
    LossyPolicy,
    PartialAlphaConfig,
    PartialAlphaFallback,
)
from glyphpact.discovery import SvgSource
from glyphpact.errors import BatchError, SvgFeatureClass, SvgFeatureError
from glyphpact.svg_compiler import compile_svg

LAYERED_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path opacity=".4" d="M1 1h8v8H1z"/>'
    '<path d="M12 12h8v8h-8z"/>'
    "</svg>"
)


def _source(content: str, source_id: str = "icon.svg") -> SvgSource:
    data = content.encode("utf-8")
    return SvgSource(
        path=Path(source_id),
        source_id=source_id,
        content=content,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
    )


def _config(
    tmp_path: Path,
    *,
    fallback: PartialAlphaFallback = PartialAlphaFallback.SILHOUETTE,
    lossy: LossyPolicy = LossyPolicy.ERROR,
) -> BuildConfig:
    return BuildConfig(
        input_path=tmp_path / "icons",
        output_dir=tmp_path / "generated",
        policy=ConversionPolicy(lossy=lossy),
        icons={
            "icon.svg": IconOverride(
                partial_alpha=PartialAlphaConfig(fallback=fallback),
            )
        },
        jobs=1,
    ).validated()


def test_layered_alpha_preserves_exact_opacity_and_paint_order(tmp_path: Path) -> None:
    alpha = "0.1234567891234567"
    content = LAYERED_SVG.replace('opacity=".4"', f'opacity="{alpha}"')

    glyph = compile_svg(_source(content), _config(tmp_path))

    assert [layer.opacity for layer in glyph.layers] == [float(alpha), 1.0]
    assert [layer.bounds for layer in glyph.layers] == [
        pytest.approx((1.0, 1.0, 9.0, 9.0)),
        pytest.approx((12.0, 12.0, 20.0, 20.0)),
    ]
    assert glyph.bounds == pytest.approx((1.0, 1.0, 20.0, 20.0))
    assert [issue.code for issue in glyph.issues] == ["SVG_PARTIAL_ALPHA_APPROXIMATED"]
    assert glyph.issues[0].details == {
        "approximation": "any-positive-alpha-to-opaque",
        "losslessLayeredOutput": True,
        "occurrences": 1,
        "scope": "single-glyph-fallback",
    }


def test_opaque_only_fallback_drops_only_surviving_partial_paint(tmp_path: Path) -> None:
    glyph = compile_svg(
        _source(LAYERED_SVG),
        _config(tmp_path, fallback=PartialAlphaFallback.OPAQUE_ONLY),
    )

    assert [layer.opacity for layer in glyph.layers] == [0.4, 1.0]
    assert glyph.bounds == pytest.approx((12.0, 12.0, 20.0, 20.0))
    assert [issue.code for issue in glyph.issues] == ["SVG_PARTIAL_ALPHA_DROPPED"]
    assert glyph.issues[0].details == {
        "approximation": "opaque-only",
        "losslessLayeredOutput": True,
        "occurrences": 1,
        "scope": "single-glyph-fallback",
    }


def test_layered_fallback_is_an_explicit_per_icon_lossy_opt_in(tmp_path: Path) -> None:
    glyph = compile_svg(_source(LAYERED_SVG), _config(tmp_path))

    assert [issue.code for issue in glyph.issues] == ["SVG_PARTIAL_ALPHA_APPROXIMATED"]
    assert glyph.issues[0].details["scope"] == "single-glyph-fallback"


def test_opaque_only_fallback_rejects_an_empty_legacy_glyph(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path opacity=".4" d="M1 1h8v8H1z"/></svg>'
    )

    with pytest.raises(SvgFeatureError) as caught:
        compile_svg(
            _source(content),
            _config(tmp_path, fallback=PartialAlphaFallback.OPAQUE_ONLY),
        )

    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_EMPTY_OUTLINE"


def test_layered_mode_rejects_nonuniform_alpha_paint_instead_of_claiming_fidelity(
    tmp_path: Path,
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><defs>'
        '<linearGradient id="g"><stop stop-opacity=".2"/>'
        '<stop offset="1" stop-opacity=".8"/></linearGradient></defs>'
        '<path fill="url(#g)" d="M1 1h8v8H1z"/>'
        '<path d="M12 12h8v8h-8z"/></svg>'
    )

    with pytest.raises(SvgFeatureError) as caught:
        compile_svg(_source(content), _config(tmp_path))

    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_LAYERED_ALPHA_PAINT_UNREPRESENTABLE"
    assert caught.value.diagnostic.details["features"] == ["spatial-gradient-alpha"]


def test_layered_build_is_per_icon_and_emits_same_codepoint_layer_fonts(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "layered.svg", LAYERED_SVG)
    write_svg(inputs, "legacy.svg", LAYERED_SVG)
    config = BuildConfig(
        input_path=inputs,
        output_dir=output,
        font_family="Layer Test",
        class_name="LayerTest",
        policy=ConversionPolicy(lossy=LossyPolicy.CONVERT),
        icons={
            "layered.svg": IconOverride(
                partial_alpha=PartialAlphaConfig(
                    fallback=PartialAlphaFallback.OPAQUE_ONLY,
                )
            )
        },
        jobs=1,
    ).validated()

    result = build(config)
    checked = build(config, check=True)

    assert checked.checked
    assert len(result.layer_font_paths) == 2
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    by_source = {glyph["source"]: glyph for glyph in report["glyphs"]}
    layered = by_source["layered.svg"]
    legacy = by_source["legacy.svg"]
    assert layered["layeredRendering"]["lossless"] is True
    assert layered["layeredRendering"]["fallback"] == "opaque-only"
    assert [layer["opacity"] for layer in layered["layeredRendering"]["layers"]] == [0.4, 1.0]
    assert "layeredRendering" not in legacy
    assert legacy["issues"][0]["details"] == {
        "approximation": "any-positive-alpha-to-opaque",
        "occurrences": 1,
    }
    assert [font["family"] for font in report["layerFonts"]] == [
        "Layer Test Layer 1",
        "Layer Test Layer 2",
    ]
    assert [font["file"] for font in report["layerFonts"]] == [
        "layer_fonts/layer_1.otf",
        "layer_fonts/layer_2.otf",
    ]

    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    codepoints = {glyph["source"]: int(glyph["codepoint"], 16) for glyph in lock["glyphs"]}
    for path in result.layer_font_paths:
        font = TTFont(BytesIO(path.read_bytes()), recalcTimestamp=False)
        try:
            assert set(font.getBestCmap() or {}) == {codepoints["layered.svg"]}
        finally:
            font.close()

    dart = result.dart_path.read_text(encoding="utf-8")
    assert "abstract final class LayerTestLayers" in dart
    assert "const LayerTestLayeredData({required this.fallback, required this.layers});" in dart
    assert "static const LayerTestLayeredData layered" in dart
    assert "class LayerTestLayeredIcon extends flutter.StatelessWidget" in dart
    assert "fontFamily: 'Layer Test Layer 1'" in dart
    assert "opacity: 0.4" in dart
    assert "LayerTestLayers.legacy" not in dart


def test_scoped_layered_opt_in_does_not_allow_unrelated_lossy_conversion(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "layered.svg", LAYERED_SVG)
    write_svg(inputs, "unrelated.svg", LAYERED_SVG)
    config = BuildConfig(
        input_path=inputs,
        output_dir=output,
        policy=ConversionPolicy(lossy=LossyPolicy.ERROR),
        icons={
            "layered.svg": IconOverride(
                partial_alpha=PartialAlphaConfig(),
            )
        },
        jobs=1,
    ).validated()

    with pytest.raises(BatchError) as caught:
        build(config)

    assert [item.code for item in caught.value.diagnostics] == ["SVG_PARTIAL_ALPHA_APPROXIMATED"]
    assert caught.value.diagnostics[0].source == "unrelated.svg"
    assert not output.exists()


def test_generated_layered_dart_qualifies_flutter_types_for_shadowing_class_names(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "icons"
    write_svg(inputs, "icon.svg", LAYERED_SVG)
    result = build(
        BuildConfig(
            input_path=inputs,
            output_dir=tmp_path / "generated",
            class_name="Icon",
            policy=ConversionPolicy(lossy=LossyPolicy.ERROR),
            icons={
                "icon.svg": IconOverride(
                    partial_alpha=PartialAlphaConfig(),
                )
            },
            jobs=1,
        ).validated()
    )

    dart = result.dart_path.read_text(encoding="utf-8")
    assert "import 'package:flutter/widgets.dart' as flutter;" in dart
    assert "abstract final class Icon {" in dart
    assert dart.count("@flutter.staticIconProvider") == 2
    assert "@flutter.staticIconProvider\nabstract final class IconLayers {" in dart
    assert "// dart format off" not in dart
    assert "// dart format on" not in dart
    assert "static const flutter.IconData icon = flutter.IconData(" in dart
    assert "class IconLayeredIcon extends flutter.StatelessWidget" in dart
    assert "flutter.Widget build(flutter.BuildContext context)" in dart
    assert "flutter.Opacity(" in dart
    assert "child: flutter.Icon(" in dart


def test_wrapped_package_layer_provider_is_legacy_formatter_canonical(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "icons"
    write_svg(inputs, "layered.svg", LAYERED_SVG)
    config = BuildConfig(
        input_path=inputs,
        output_dir=tmp_path / "generated",
        font_family="Package Smoke Icons",
        class_name="PackageSmokeIcons",
        font_package="icon_font_fixture",
        catalog=True,
        icons={
            "layered.svg": IconOverride(
                partial_alpha=PartialAlphaConfig(),
            )
        },
        jobs=1,
    ).validated()

    result = build(config)

    dart = result.dart_path.read_text(encoding="utf-8")
    provider = (
        "// dart format off\n"
        "\n"
        "/// Layered icon descriptors for SVGs that opted into partial-alpha preservation.\n"
        "///\n"
        "/// This static-const provider lets Flutter subset unreferenced descriptors.\n"
        "@flutter.staticIconProvider\n"
        "abstract final class PackageSmokeIconsLayers {\n"
        "  /// Lossless ordered layers for [PackageSmokeIcons.layered].\n"
        "  static const PackageSmokeIconsLayeredData layered =\n"
        "      PackageSmokeIconsLayeredData(\n"
        "    fallback: PackageSmokeIcons.layered,\n"
        "    layers: <PackageSmokeIconsLayer>[\n"
        "      PackageSmokeIconsLayer(\n"
        "        icon: flutter.IconData(\n"
        "          0xE000,\n"
        "          fontFamily: 'Package Smoke Icons Layer 1',\n"
        "          fontPackage: 'icon_font_fixture',\n"
        "        ),\n"
        "        opacity: 0.4,\n"
        "      ),\n"
        "      PackageSmokeIconsLayer(\n"
        "        icon: flutter.IconData(\n"
        "          0xE000,\n"
        "          fontFamily: 'Package Smoke Icons Layer 2',\n"
        "          fontPackage: 'icon_font_fixture',\n"
        "        ),\n"
        "        opacity: 1.0,\n"
        "      ),\n"
        "    ],\n"
        "  );\n"
        "}\n"
        "\n"
        "// dart format on\n"
    )
    assert provider in dart
    assert dart.index("final class PackageSmokeIconsLayeredData {") < dart.index(provider)
    assert dart.index(provider) < dart.index(
        "class PackageSmokeIconsLayeredIcon extends flutter.StatelessWidget"
    )
    assert dart.count("// dart format off") == 2
    assert dart.count("// dart format on") == 2
    assert build(config, check=True).checked


def test_layered_build_failure_publishes_no_partial_output(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "icon.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<g opacity=".4"><path d="M1 1h8v8H1z"/>'
        '<path d="M4 4h8v8H4z"/></g>'
        '<path d="M12 12h8v8h-8z"/></svg>',
    )

    with pytest.raises(BatchError) as caught:
        build(_config(tmp_path))

    assert [item.code for item in caught.value.diagnostics] == [
        "SVG_LAYERED_ALPHA_PAINT_UNREPRESENTABLE"
    ]
    assert not output.exists()


def test_catalog_separates_layered_descriptors_from_plain_icons(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "layered.svg", LAYERED_SVG)
    write_svg(
        inputs,
        "plain.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M2 2h20v20H2z"/>'
        "</svg>",
    )
    config = BuildConfig(
        input_path=inputs,
        output_dir=output,
        font_family="Layer Test",
        class_name="LayerTest",
        catalog=True,
        policy=ConversionPolicy(lossy=LossyPolicy.CONVERT),
        icons={
            "layered.svg": IconOverride(
                partial_alpha=PartialAlphaConfig(
                    fallback=PartialAlphaFallback.OPAQUE_ONLY,
                )
            )
        },
        jobs=1,
    ).validated()

    result = build(config)

    dart = result.dart_path.read_text(encoding="utf-8")
    catalog = dart.split("abstract final class LayerTestCatalog {", 1)[1]
    assert "static const Map<String, flutter.IconData> byName" in catalog
    assert "'layered': LayerTest.layered," in catalog
    assert "'plain': LayerTest.plain," in catalog
    assert "static const Map<String, LayerTestLayeredData> layeredByName" in catalog
    assert "'layered': LayerTestLayers.layered," in catalog
    assert "'plain': LayerTestLayers.plain," not in catalog
    assert "Retaining or enumerating this map keeps every listed fallback and" in catalog
    assert "layer glyph, but does not keep unrelated plain icons." in catalog
    assert catalog.count("Keep the literal expanded for Dart 3.0-3.6 formatters.") == 2
    assert "@flutter.staticIconProvider\nabstract final class LayerTestCatalog {" in dart
    assert dart.count("@flutter.staticIconProvider") == 3
    assert build(config, check=True).checked


def test_first_and_last_layered_icon_toggle_conditional_catalog_api(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "plain.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M2 2h20v20H2z"/>'
        "</svg>",
    )
    plain_config = BuildConfig(
        input_path=inputs,
        output_dir=output,
        font_family="Layer Test",
        class_name="LayerTest",
        catalog=True,
        jobs=1,
    ).validated()

    plain = build(plain_config)
    plain_dart = plain.dart_path.read_text(encoding="utf-8")
    assert "LayerTestLayeredData" not in plain_dart
    assert "LayerTestLayers" not in plain_dart
    assert "layeredByName" not in plain_dart
    assert build(plain_config, check=True).checked

    write_svg(inputs, "layered.svg", LAYERED_SVG)
    layered_config = BuildConfig(
        input_path=inputs,
        output_dir=output,
        font_family="Layer Test",
        class_name="LayerTest",
        catalog=True,
        icons={
            "layered.svg": IconOverride(
                partial_alpha=PartialAlphaConfig(),
            )
        },
        jobs=1,
    ).validated()
    layered = build(layered_config)
    layered_dart = layered.dart_path.read_text(encoding="utf-8")
    assert "final class LayerTestLayeredData" in layered_dart
    assert "abstract final class LayerTestLayers" in layered_dart
    assert "static const Map<String, LayerTestLayeredData> layeredByName" in layered_dart
    assert "'layered': LayerTestLayers.layered," in layered_dart
    assert build(layered_config, check=True).checked

    (inputs / "layered.svg").unlink()
    removed = build(plain_config)
    removed_dart = removed.dart_path.read_text(encoding="utf-8")
    assert "LayerTestLayeredData" not in removed_dart
    assert "LayerTestLayers" not in removed_dart
    assert "layeredByName" not in removed_dart
    assert "'plain': LayerTest.plain," in removed_dart
    retired = json.loads(removed.lock_path.read_text(encoding="utf-8"))["retired"]
    assert [glyph["source"] for glyph in retired] == ["layered.svg"]
    assert build(plain_config, check=True).checked
