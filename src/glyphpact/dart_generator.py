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


def _named_argument(indent: str, name: str, value: str) -> list[str]:
    line = f"{indent}{name}: {value},"
    if len(line) <= 80:
        return [line]
    return [f"{indent}{name}:", f"{indent}    {value},"]


def _qualified_named_argument(
    indent: str,
    name: str,
    qualifier: str,
    member: str,
) -> list[str]:
    line = f"{indent}{name}: {qualifier}.{member},"
    if len(line) <= 80:
        return [line]
    value_line = f"{indent}    {qualifier}.{member},"
    if len(value_line) <= 80:
        return [f"{indent}{name}:", value_line]
    return [f"{indent}{name}: {qualifier}", f"{indent}    .{member},"]


def _map_declaration(value_type: str, name: str) -> list[str]:
    line = f"  static const Map<String, {value_type}> {name} ="
    if len(line) <= 80:
        return [line]
    return [f"  static const Map<String, {value_type}>", f"      {name} ="]


def _map_entry(key: str, qualifier: str, member: str) -> list[str]:
    encoded_key = dart_string(key)
    line = f"    {encoded_key}: {qualifier}.{member},"
    if len(line) <= 80:
        return [line]
    value_line = f"        {qualifier}.{member},"
    if len(value_line) <= 80:
        return [f"    {encoded_key}:", value_line]
    return [f"    {encoded_key}:", f"        {qualifier}", f"            .{member},"]


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
        *(["// dart format off", ""] if config.catalog else []),
        "/// Layered icon descriptors for SVGs that opted into partial-alpha preservation.",
        "///",
        "/// This static-const provider lets Flutter subset unreferenced descriptors.",
        "@flutter.staticIconProvider",
        f"abstract final class {provider_type} {{",
    ]
    layered_glyphs = tuple(glyph for glyph in glyphs if glyph.source in layers_by_source)
    for source_index, glyph in enumerate(layered_glyphs):
        source = glyph.source
        assignment = f"  static const {data_type} {glyph.name} ="
        constructor = f"{data_type}("
        wrapped = len(f"{assignment} {constructor}") > 80
        argument_indent = "    " if config.catalog else ("        " if wrapped else "    ")
        item_indent = f"{argument_indent}  "
        property_indent = f"{item_indent}  "
        icon_argument_indent = f"{property_indent}  "
        constructor_indent = "      " if wrapped else "  "
        lines.extend(
            [
                f"  /// Lossless ordered layers for [{class_name}.{glyph.name}].",
            ]
        )
        if config.catalog and len(assignment) > 80:
            lines.extend(
                [
                    f"  static const {data_type}",
                    f"      {glyph.name} =",
                    f"{constructor_indent}{constructor}",
                ]
            )
        elif wrapped:
            lines.extend([assignment, f"{constructor_indent}{constructor}"])
        else:
            lines.append(f"{assignment} {constructor}")
        lines.extend(
            [
                *(
                    _qualified_named_argument(
                        argument_indent,
                        "fallback",
                        class_name,
                        glyph.name,
                    )
                    if config.catalog
                    else [f"{argument_indent}fallback: {class_name}.{glyph.name},"]
                ),
                f"{argument_indent}layers: <{layer_type}>[",
            ]
        )
        for layer in layers_by_source[source]:
            lines.extend(
                [
                    f"{item_indent}{layer_type}(",
                    f"{property_indent}icon: flutter.IconData(",
                    f"{icon_argument_indent}0x{glyph.codepoint:X},",
                    *(
                        _named_argument(
                            icon_argument_indent,
                            "fontFamily",
                            dart_string(layer.font_family),
                        )
                        if config.catalog
                        else [
                            f"{icon_argument_indent}fontFamily: {dart_string(layer.font_family)},"
                        ]
                    ),
                    *(
                        _named_argument(icon_argument_indent, "fontPackage", package)
                        if config.catalog
                        else [f"{icon_argument_indent}fontPackage: {package},"]
                    ),
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
        lines.extend(
            [
                f"{argument_indent}],",
                "  );" if config.catalog else f"{constructor_indent});",
            ]
        )
        if source_index != len(layered_glyphs) - 1:
            lines.append("")
    lines.extend(
        [
            "}",
            *(["", "// dart format on"] if config.catalog else []),
            "",
            "/// Renders a generated layered descriptor with source-order alpha compositing.",
            *(
                [f"class {widget_type} extends flutter.StatelessWidget {{"]
                if (
                    not config.catalog
                    or len(f"class {widget_type} extends flutter.StatelessWidget {{") <= 80
                )
                else [f"class {widget_type}", "    extends flutter.StatelessWidget {"]
            ),
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


def _catalog_dart(
    ordered: tuple[LockGlyph, ...],
    layers_by_source: Mapping[str, tuple[DartLayer, ...]],
    config: BuildConfig,
) -> list[str]:
    if not config.catalog:
        return []
    class_name = config.class_name
    assert class_name is not None
    catalog_type = f"{class_name}Catalog"
    lines = [
        "",
        "// dart format off",
        "",
        f"/// Runtime lookup for every generated {class_name} glyph.",
        "///",
        "/// Generating or importing this companion does not retain glyphs by itself.",
        "/// Retaining or enumerating [byName] keeps every base-font glyph, but not",
        "/// layer glyphs, in release builds.",
        "/// Use individual provider constants when glyph-level subsetting matters.",
        "///",
        "/// The provider annotation suppresses unreachable catalog declarations;",
        "/// reachable map values remain visible to Flutter's icon tree shaker.",
        "@flutter.staticIconProvider",
        f"abstract final class {catalog_type} {{",
        *_map_declaration("flutter.IconData", "byName"),
        "      // Keep the literal expanded for Dart 3.0-3.6 formatters.",
        "      <String, flutter.IconData>{",
        *(line for glyph in ordered for line in _map_entry(glyph.name, class_name, glyph.name)),
        "  };",
    ]
    if layers_by_source:
        data_type = f"{class_name}LayeredData"
        provider_type = f"{class_name}Layers"
        layered = tuple(glyph for glyph in ordered if glyph.source in layers_by_source)
        lines.extend(
            [
                "",
                "  /// Every layered descriptor keyed by its Dart name.",
                "  ///",
                "  /// Retaining or enumerating this map keeps every listed fallback and",
                "  /// layer glyph, but does not keep unrelated plain icons.",
                *_map_declaration(data_type, "layeredByName"),
                "      // Keep the literal expanded for Dart 3.0-3.6 formatters.",
                f"      <String, {data_type}>{{",
                *(
                    line
                    for glyph in layered
                    for line in _map_entry(glyph.name, provider_type, glyph.name)
                ),
                "  };",
            ]
        )
    lines.extend(["}", "", "// dart format on"])
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
    ordered = tuple(sorted(glyphs, key=lambda value: value.codepoint))
    layers = layers_by_source or {}
    protect_provider_format = config.catalog and any(
        len(f"  static const flutter.IconData {glyph.name} = flutter.IconData(") > 80
        for glyph in ordered
    )
    lines = [
        "// GENERATED CODE - DO NOT MODIFY BY HAND.",
        f"// Generated by {PRODUCT_NAME} {__version__}.",
        "",
        "import 'package:flutter/widgets.dart' as flutter;",
        "",
        *(["// dart format off", ""] if protect_provider_format else []),
        f"/// Constant [flutter.IconData] values backed by the {config.font_family} font.",
        "@flutter.staticIconProvider",
        f"abstract final class {class_name} {{",
        *_const_assignment("String", "_fontFamily", dart_string(config.font_family)),
        *_const_assignment("String?", "_fontPackage", package),
        "",
    ]
    for index, glyph in enumerate(ordered):
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
            argument_indent = "    " if config.catalog else "        "
            lines.extend(
                [
                    assignment,
                    f"      {constructor}",
                    f"{argument_indent}0x{glyph.codepoint:X},",
                    f"{argument_indent}fontFamily: _fontFamily,",
                    f"{argument_indent}fontPackage: _fontPackage,",
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
                f"{'    ' if config.catalog else '        '}matchTextDirection: true,"
                if wrapped
                else "    matchTextDirection: true,"
            )
        lines.append(("  );" if config.catalog else "      );") if wrapped else "  );")
        if index != len(ordered) - 1:
            lines.append("")
    lines.append("}")
    if protect_provider_format:
        lines.extend(["", "// dart format on"])
    lines.extend(_layered_dart(ordered, layers, config))
    lines.extend(_catalog_dart(ordered, layers, config))
    lines.append("")
    return "\n".join(lines).encode("utf-8")
