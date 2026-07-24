from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .config import BuildConfig
from .identity import PRODUCT_NAME
from .manifest import LockGlyph
from .naming import dart_string
from .version import __version__


@dataclass(frozen=True)
class DartLayer:
    font_family: str
    opacity: float


def _safe_doc(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")


def _const_assignment(type_name: str, name: str, value: str) -> list[str]:
    line = f"  static const {type_name} {name} = {value};"
    if len(line) <= 80:
        return [line]
    return [f"  static const {type_name} {name} =", f"      {value};"]


def _named_parameter_constructor(type_name: str, fields: tuple[str, ...]) -> list[str]:
    parameters = ", ".join(f"required this.{field}" for field in fields)
    line = f"  const {type_name}({{{parameters}}});"
    if len(line) <= 80:
        return [line]
    return [
        f"  const {type_name}({{",
        *(f"    required this.{field}," for field in fields),
        "  });",
    ]


def _dart_double(value: float) -> str:
    text = repr(value)
    return text if any(token in text for token in (".", "e", "E")) else f"{text}.0"


def _layered_dart(
    glyphs: tuple[LockGlyph, ...],
    layers_by_source: Mapping[str, tuple[DartLayer, ...]],
    config: BuildConfig,
) -> list[str]:
    if not layers_by_source:
        return []
    class_name = config.class_name
    assert class_name is not None
    package = "null" if config.font_package is None else dart_string(config.font_package)
    glyph_by_source = {glyph.source: glyph for glyph in glyphs}
    layer_type = f"{class_name}Layer"
    data_type = f"{class_name}LayeredData"
    provider_type = f"{class_name}Layers"
    widget_type = f"{class_name}LayeredIcon"
    lines = [
        "",
        f"/// One ordered paint layer in a [{data_type}].",
        "@flutter.immutable",
        f"final class {layer_type} {{",
        *_named_parameter_constructor(layer_type, ("icon", "opacity")),
        "",
        "  final flutter.IconData icon;",
        "  final double opacity;",
        "}",
        "",
        "/// Lossless solid-alpha layers plus the compatible single-glyph fallback.",
        "@flutter.immutable",
        f"final class {data_type} {{",
        *_named_parameter_constructor(data_type, ("fallback", "layers")),
        "",
        "  final flutter.IconData fallback;",
        f"  final List<{layer_type}> layers;",
        "}",
        "",
        "/// Layered icon descriptors for SVGs that opted into partial-alpha preservation.",
        f"abstract final class {provider_type} {{",
    ]
    ordered_sources = sorted(
        layers_by_source,
        key=lambda source: glyph_by_source[source].codepoint,
    )
    for source_index, source in enumerate(ordered_sources):
        glyph = glyph_by_source[source]
        assignment = f"  static const {data_type} {glyph.name} ="
        constructor = f"{data_type}("
        wrapped = len(f"{assignment} {constructor}") > 80
        argument_indent = "        " if wrapped else "    "
        item_indent = f"{argument_indent}  "
        property_indent = f"{item_indent}  "
        icon_argument_indent = f"{property_indent}  "
        constructor_indent = "      " if wrapped else "  "
        lines.extend(
            [
                f"  /// Lossless ordered layers for [{class_name}.{glyph.name}].",
                assignment if wrapped else f"{assignment} {constructor}",
            ]
        )
        if wrapped:
            lines.append(f"{constructor_indent}{constructor}")
        lines.extend(
            [
                f"{argument_indent}fallback: {class_name}.{glyph.name},",
                f"{argument_indent}layers: <{layer_type}>[",
            ]
        )
        for layer in layers_by_source[source]:
            lines.extend(
                [
                    f"{item_indent}{layer_type}(",
                    f"{property_indent}icon: flutter.IconData(",
                    f"{icon_argument_indent}0x{glyph.codepoint:X},",
                    (f"{icon_argument_indent}fontFamily: {dart_string(layer.font_family)},"),
                    f"{icon_argument_indent}fontPackage: {package},",
                ]
            )
            if glyph.match_text_direction:
                lines.append(f"{icon_argument_indent}matchTextDirection: true,")
            lines.extend(
                [
                    f"{property_indent}),",
                    f"{property_indent}opacity: {_dart_double(layer.opacity)},",
                    f"{item_indent}),",
                ]
            )
        lines.extend([f"{argument_indent}],", f"{constructor_indent});"])
        if source_index != len(ordered_sources) - 1:
            lines.append("")
    lines.extend(
        [
            "}",
            "",
            "/// Renders a generated layered descriptor with source-order alpha compositing.",
            f"class {widget_type} extends flutter.StatelessWidget {{",
            f"  const {widget_type}(",
            "    this.icon, {",
            "    super.key,",
            "    this.size,",
            "    this.color,",
            "    this.semanticLabel,",
            "    this.textDirection,",
            "  });",
            "",
            f"  final {data_type} icon;",
            "  final double? size;",
            "  final flutter.Color? color;",
            "  final String? semanticLabel;",
            "  final flutter.TextDirection? textDirection;",
            "",
            "  @override",
            "  flutter.Widget build(flutter.BuildContext context) {",
            "    final child = flutter.Stack(",
            "      alignment: flutter.Alignment.center,",
            "      children: <flutter.Widget>[",
            "        for (final layer in icon.layers)",
            "          flutter.Opacity(",
            "            opacity: layer.opacity,",
            "            child: flutter.Icon(",
            "              layer.icon,",
            "              size: size,",
            "              color: color,",
            "              textDirection: textDirection,",
            "            ),",
            "          ),",
            "      ],",
            "    );",
            "    final excluded = flutter.ExcludeSemantics(child: child);",
            "    return semanticLabel == null",
            "        ? excluded",
            "        : flutter.Semantics(label: semanticLabel, child: excluded);",
            "  }",
            "}",
        ]
    )
    return lines


def generate_dart(
    glyphs: tuple[LockGlyph, ...],
    config: BuildConfig,
    *,
    layers_by_source: Mapping[str, tuple[DartLayer, ...]] | None = None,
) -> bytes:
    class_name = config.class_name
    assert class_name is not None
    package = "null" if config.font_package is None else dart_string(config.font_package)
    lines = [
        "// GENERATED CODE - DO NOT MODIFY BY HAND.",
        f"// Generated by {PRODUCT_NAME} {__version__}.",
        "",
        "import 'package:flutter/widgets.dart' as flutter;",
        "",
        f"/// Constant [flutter.IconData] values backed by the {config.font_family} font.",
        "@flutter.staticIconProvider",
        f"abstract final class {class_name} {{",
        *_const_assignment("String", "_fontFamily", dart_string(config.font_family)),
        *_const_assignment("String?", "_fontPackage", package),
        "",
    ]
    for index, glyph in enumerate(sorted(glyphs, key=lambda value: value.codepoint)):
        lines.append(f"  /// Source: {_safe_doc(glyph.source)}")
        if glyph.metadata:
            license_name = glyph.metadata.get("license")
            source_url = glyph.metadata.get("sourceUrl")
            if license_name:
                lines.append(f"  /// License: {_safe_doc(license_name)}")
            if source_url:
                lines.append(f"  /// Upstream: {_safe_doc(source_url)}")
        assignment = f"  static const flutter.IconData {glyph.name} ="
        constructor = "flutter.IconData("
        wrapped = len(f"{assignment} {constructor}") > 80
        if wrapped:
            lines.extend(
                [
                    assignment,
                    f"      {constructor}",
                    f"        0x{glyph.codepoint:X},",
                    "        fontFamily: _fontFamily,",
                    "        fontPackage: _fontPackage,",
                ]
            )
        else:
            lines.extend(
                [
                    f"{assignment} {constructor}",
                    f"    0x{glyph.codepoint:X},",
                    "    fontFamily: _fontFamily,",
                    "    fontPackage: _fontPackage,",
                ]
            )
        if glyph.match_text_direction:
            lines.append(
                "        matchTextDirection: true," if wrapped else "    matchTextDirection: true,"
            )
        lines.append("      );" if wrapped else "  );")
        if index != len(glyphs) - 1:
            lines.append("")
    lines.append("}")
    lines.extend(_layered_dart(glyphs, layers_by_source or {}, config))
    lines.append("")
    return "\n".join(lines).encode("utf-8")
