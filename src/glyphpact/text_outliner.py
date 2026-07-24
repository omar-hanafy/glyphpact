from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import unicodedata
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, NoReturn, cast

import uharfbuzz as hb
from fontTools import unicodedata as fonttools_unicodedata
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from lxml import etree
from picosvg.svg_meta import strip_ns
from picosvg.svg_transform import Affine2D
from picosvg.svg_types import SVGPath

from .config import MAX_TEXT_FONT_BYTES, TextFont
from .errors import IconFontError, SvgFeatureClass, SvgFeatureError

_TEXT_STYLE_PROPERTIES = (
    "direction",
    "font-family",
    "font-size",
    "font-stretch",
    "font-style",
    "font-variant",
    "font-weight",
    "text-anchor",
    "unicode-bidi",
    "writing-mode",
)

_GLYPH_PRESENTATION_ATTRIBUTES = (
    "stroke-dasharray",
    "stroke-dashoffset",
    "vector-effect",
)
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_COMMON_SCRIPT_CODES = frozenset({"Zinh", "Zyyy", "Zzzz"})
_ABSOLUTE_LENGTH_SCALE = {
    "": 1.0,
    "px": 1.0,
    "in": 96.0,
    "cm": 96.0 / 2.54,
    "mm": 96.0 / 25.4,
    "q": 96.0 / 101.6,
    "pt": 96.0 / 72.0,
    "pc": 16.0,
}
_ABSOLUTE_LENGTH = re.compile(
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(px|in|cm|mm|q|pt|pc)?",
    re.IGNORECASE,
)


class _PathWorkLimitExceeded(Exception):
    pass


class _LimitedSVGPathPen(SVGPathPen):  # type: ignore[misc]
    """Stop a hostile glyph before its outline can exceed the work budget."""

    def __init__(self, glyph_set: Any, limit: int) -> None:
        super().__init__(glyph_set)
        self.command_work = 0
        self._limit = limit

    def _charge(self) -> None:
        self.command_work += 1
        if self.command_work > self._limit:
            raise _PathWorkLimitExceeded

    def _moveTo(self, point: Any) -> None:
        self._charge()
        super()._moveTo(point)

    def _lineTo(self, point: Any) -> None:
        self._charge()
        super()._lineTo(point)

    def _curveToOne(self, point1: Any, point2: Any, point3: Any) -> None:
        self._charge()
        super()._curveToOne(point1, point2, point3)

    def _qCurveToOne(self, point1: Any, point2: Any) -> None:
        self._charge()
        super()._qCurveToOne(point1, point2)

    def _closePath(self) -> None:
        self._charge()
        super()._closePath()


def _synthetic_element_bytes(
    tag: str,
    attributes: dict[str, str],
    *,
    text: str | None = None,
    tail: str | None = None,
) -> int:
    encoded_bytes = len(tag.encode("utf-8"))
    encoded_bytes += sum(
        len(name.encode("utf-8")) + len(value.encode("utf-8")) for name, value in attributes.items()
    )
    encoded_bytes += len((text or "").encode("utf-8"))
    encoded_bytes += len((tail or "").encode("utf-8"))
    return max(1, encoded_bytes)


def _element_bytes(element: etree._Element) -> int:
    return _synthetic_element_bytes(
        str(element.tag),
        dict(element.attrib),
        text=element.text,
        tail=element.tail,
    )


class _TextWorkBudget:
    """Track text shaping and its projected replacement tree as one bounded stage."""

    def __init__(
        self,
        root: etree._Element,
        *,
        max_expanded_elements: int,
        max_expanded_bytes: int,
        max_path_commands: int,
        source_id: str,
    ) -> None:
        elements = tuple(element for element in root.iter() if isinstance(element.tag, str))
        self.element_count = len(elements)
        self.byte_count = sum(_element_bytes(element) for element in elements)
        self.shaped_glyph_work = 0
        self.path_command_work = 0
        self.max_expanded_elements = max_expanded_elements
        self.max_expanded_bytes = max_expanded_bytes
        self.max_path_commands = max_path_commands
        self.source_id = source_id

    def _raise_expansion(
        self,
        message: str,
        *,
        projected_elements: int | None = None,
        projected_bytes: int | None = None,
        shaped_glyphs: int | None = None,
    ) -> NoReturn:
        details: dict[str, int | str] = {
            "phase": "text-outlining",
            "maxExpandedElements": self.max_expanded_elements,
            "maxExpandedBytes": self.max_expanded_bytes,
        }
        if projected_elements is not None:
            details["expandedElements"] = projected_elements
        if projected_bytes is not None:
            details["expandedBytes"] = projected_bytes
        if shaped_glyphs is not None:
            details["shapedGlyphs"] = shaped_glyphs
        raise IconFontError(
            "SVG_EXPANSION_LIMIT",
            message,
            source=self.source_id,
            details=details,
            hint="Shorten the text, simplify the pinned glyphs, or raise the explicit limits.",
        )

    def projected_replacement_base(
        self,
        element: etree._Element,
        group: etree._Element,
    ) -> tuple[int, int]:
        projected_elements = self.element_count
        projected_bytes = self.byte_count - _element_bytes(element) + _element_bytes(group)
        if (
            projected_elements > self.max_expanded_elements
            or projected_bytes > self.max_expanded_bytes
        ):
            self._raise_expansion(
                "Outlined text exceeds the configured expansion budget.",
                projected_elements=projected_elements,
                projected_bytes=projected_bytes,
            )
        return projected_elements, projected_bytes

    def precheck_shaping(self, text: str) -> None:
        # HarfBuzz may emit more glyphs through GSUB, so this is an input-side
        # upper bound only. The shaped result is checked again below.
        upper_bound = self.shaped_glyph_work + len(text)
        if upper_bound > self.max_expanded_elements:
            self._raise_expansion(
                "Text shaping exceeds the configured expanded-element work budget.",
                shaped_glyphs=upper_bound,
            )

    def accept_shaped_glyphs(self, count: int) -> None:
        shaped_glyphs = self.shaped_glyph_work + count
        if shaped_glyphs > self.max_expanded_elements:
            self._raise_expansion(
                "The pinned font expanded text beyond the shaped-glyph work budget.",
                shaped_glyphs=shaped_glyphs,
            )
        self.shaped_glyph_work = shaped_glyphs

    def ensure_projected_tree(self, elements: int, encoded_bytes: int) -> None:
        if elements > self.max_expanded_elements or encoded_bytes > self.max_expanded_bytes:
            self._raise_expansion(
                "Outlined glyph paths exceed the configured expansion budget.",
                projected_elements=elements,
                projected_bytes=encoded_bytes,
            )

    def remaining_path_work(self, local_work: int) -> int:
        return self.max_path_commands - self.path_command_work - local_work

    def accept_replacement(
        self,
        *,
        projected_elements: int,
        projected_bytes: int,
        path_command_work: int,
    ) -> None:
        total_path_work = self.path_command_work + path_command_work
        if total_path_work > self.max_path_commands:
            self.raise_path_limit(total_path_work)
        self.element_count = projected_elements
        self.byte_count = projected_bytes
        self.path_command_work = total_path_work

    def raise_path_limit(self, path_command_work: int) -> NoReturn:
        raise IconFontError(
            "SVG_TOO_MANY_PATH_COMMANDS",
            "Outlined text exceeds the configured path-command work limit.",
            source=self.source_id,
            details={
                "phase": "text-outlining",
                "outlinedTextPathCommands": path_command_work,
                "maxPathCommands": self.max_path_commands,
            },
            hint="Shorten the text, simplify the pinned glyphs, or raise maxPathCommands.",
        )


@lru_cache(maxsize=1)
def _font_bytes(path: str, expected_hash: str) -> bytes:
    font_path = Path(path)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(font_path, flags)
        try:
            status = os.fstat(descriptor)
            if not stat.S_ISREG(status.st_mode):
                raise OSError("Pinned text font is no longer a regular file.")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(MAX_TEXT_FONT_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise IconFontError(
            "TEXT_FONT_READ_FAILED",
            str(error),
            source=path,
        ) from error
    if len(data) > MAX_TEXT_FONT_BYTES:
        raise IconFontError(
            "TEXT_FONT_READ_FAILED",
            "Pinned text font grew beyond the 64 MiB worker read limit.",
            source=path,
        )
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_hash:
        raise IconFontError(
            "TEXT_FONT_HASH_MISMATCH",
            f"Pinned text font changed after configuration validation: {digest}.",
            source=path,
        )
    return data


@lru_cache(maxsize=64)
def _validate_text_font(path: str, expected_hash: str) -> None:
    data = _font_bytes(path, expected_hash)
    try:
        face = hb.Face(data)
        if face.upem <= 0 or face.glyph_count <= 0:
            raise ValueError("The font has no usable units-per-em or glyphs.")
        font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
        try:
            required = {"cmap", "head", "maxp"}
            missing = required - set(font.keys())
            if missing:
                raise ValueError(f"The font is missing required tables: {sorted(missing)!r}.")
            if font["head"].unitsPerEm <= 0:
                raise ValueError("The font units-per-em must be positive.")
            font.getGlyphOrder()
            font.getBestCmap()
            font.getGlyphSet()
        finally:
            font.close()
    except IconFontError:
        raise
    except Exception as error:
        raise IconFontError(
            "TEXT_FONT_INVALID",
            f"Pinned text font could not be parsed safely: {error}",
            source=path,
        ) from error


def validate_text_fonts(text_fonts: dict[str, TextFont]) -> None:
    """Parse every configured face before any per-icon policy can skip work."""

    for family, text_font in sorted(text_fonts.items(), key=lambda item: item[0].casefold()):
        try:
            _validate_text_font(str(text_font.path), text_font.sha256)
        except IconFontError as error:
            raise IconFontError(
                error.diagnostic.code,
                error.diagnostic.message,
                source=str(text_font.path),
                details={**error.diagnostic.details, "fontFamily": family},
                hint=error.diagnostic.hint,
            ) from error


def _keyword(value: str | None, inherited: str, initial: str) -> str:
    if value is None:
        return inherited
    lowered = value.strip().casefold()
    if lowered in {"inherit", "unset"}:
        return inherited
    if lowered == "initial":
        return initial
    return value.strip()


def _single_number(value: str | None, default: float, name: str, source_id: str) -> float:
    if value is None:
        return default
    text = value.strip()
    if re.search(r"[\s,]", text):
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "per-character-text-positioning",
            "SVG_TEXT_POSITIONING_UNREPRESENTABLE",
            f"Text {name}={value!r} contains a per-character position list.",
            source=source_id,
        )
    match = _ABSOLUTE_LENGTH.fullmatch(text)
    if match is None:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "relative-text-length",
            "SVG_TEXT_POSITIONING_UNREPRESENTABLE",
            f"Text {name}={value!r} is not an absolute user-unit value.",
            source=source_id,
        )
    result = float(match.group(1)) * _ABSOLUTE_LENGTH_SCALE[(match.group(2) or "").casefold()]
    if not math.isfinite(result):
        raise IconFontError(
            "SVG_TEXT_POSITIONING_INVALID",
            f"Text {name} must be finite.",
            source=source_id,
        )
    return result


def _family_names(value: str, source_id: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    for index, character in enumerate(value):
        if character == "\\":
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "font-family-escape",
                "SVG_TEXT_FONT_UNREPRESENTABLE",
                "Escaped CSS font-family names are outside the pinned font profile.",
                source=source_id,
            )
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == ",":
            parts.append(value[start:index])
            start = index + 1
    if quote is not None:
        raise IconFontError(
            "SVG_TEXT_FONT_INVALID",
            f"font-family={value!r} contains an unterminated quote.",
            source=source_id,
        )
    parts.append(value[start:])
    result = tuple(unicodedata.normalize("NFC", part.strip().strip("\"'")) for part in parts)
    if not result or any(not family for family in result):
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "implicit-platform-font",
            "SVG_TEXT_FONT_UNREPRESENTABLE",
            "Text requires one explicit pinned font family.",
            source=source_id,
        )
    return result


def _validate_single_run(text: str, direction: str, source_id: str) -> None:
    strong = {
        "rtl" if unicodedata.bidirectional(character) in {"AL", "R"} else "ltr"
        for character in text
        if unicodedata.bidirectional(character) in {"AL", "L", "R"}
    }
    if len(strong) > 1:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "mixed-bidi-text",
            "SVG_TEXT_BIDI_UNREPRESENTABLE",
            "Mixed-direction text requires paragraph-level bidi layout.",
            source=source_id,
        )
    if strong and direction not in strong:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "text-direction-override",
            "SVG_TEXT_BIDI_UNREPRESENTABLE",
            "The declared text direction conflicts with the shaped run.",
            source=source_id,
        )
    scripts = {
        script
        for character in text
        if (script := fonttools_unicodedata.script(character)) not in _COMMON_SCRIPT_CODES
    }
    if len(scripts) > 1:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "mixed-script-text",
            "SVG_TEXT_SCRIPT_UNREPRESENTABLE",
            "Mixed Unicode scripts require script-segmented shaping.",
            source=source_id,
            details={"scripts": sorted(scripts)},
        )


def _shape_text(
    text: str,
    text_font: TextFont,
    *,
    direction: str,
    language: str | None,
    source_id: str,
) -> tuple[bytes, TTFont, Any, tuple[Any, ...], tuple[Any, ...]]:
    data = _font_bytes(str(text_font.path), text_font.sha256)
    face = hb.Face(data)
    harfbuzz_font = hb.Font(face)
    harfbuzz_font.scale = (face.upem, face.upem)
    hb.ot_font_set_funcs(harfbuzz_font)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    buffer.direction = direction
    if language:
        buffer.language = language
    hb.shape(harfbuzz_font, buffer)
    infos = tuple(buffer.glyph_infos)
    positions = tuple(buffer.glyph_positions)
    if any(info.codepoint == 0 for info in infos):
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "missing-text-glyph",
            "SVG_TEXT_GLYPH_UNREPRESENTABLE",
            "The pinned font does not contain every shaped glyph.",
            source=source_id,
        )
    font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
    color_tables = {"CBDT", "COLR", "EBDT", "sbix", "SVG "} & set(font.keys())
    if color_tables:
        font.close()
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "color-font-text",
            "SVG_TEXT_FONT_UNREPRESENTABLE",
            "Color-font glyphs are outside the monochrome outline text profile.",
            source=source_id,
            details={"tables": sorted(color_tables)},
        )
    return data, font, harfbuzz_font, infos, positions


def _outline_run(
    root: etree._Element,
    element: etree._Element,
    text: str,
    text_font: TextFont,
    styles: dict[str, str],
    language: str | None,
    source_id: str,
    budget: _TextWorkBudget,
) -> etree._Element:
    group = root.makeelement(f"{{{_SVG_NAMESPACE}}}g")
    for name in (
        "clip-path",
        "fill",
        "fill-opacity",
        "fill-rule",
        "opacity",
        "stroke",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "stroke-opacity",
        "stroke-width",
        "transform",
    ):
        if name in element.attrib:
            group.set(name, element.attrib[name])
    group.tail = element.tail
    projected_elements, projected_bytes = budget.projected_replacement_base(element, group)
    budget.precheck_shaping(text)

    direction = styles["direction"].casefold()
    if direction not in {"ltr", "rtl"}:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "text-direction",
            "SVG_TEXT_BIDI_UNREPRESENTABLE",
            f"Text direction={direction!r} is outside the single-run profile.",
            source=source_id,
        )
    _validate_single_run(text, direction, source_id)
    if styles["writing-mode"].casefold() not in {"horizontal-tb", "lr", "lr-tb"}:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "vertical-text",
            "SVG_TEXT_LAYOUT_UNREPRESENTABLE",
            "Vertical text requires the extended text-layout profile.",
            source=source_id,
        )
    if styles["unicode-bidi"].casefold() != "normal":
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "bidi-paragraph-layout",
            "SVG_TEXT_BIDI_UNREPRESENTABLE",
            "unicode-bidi modes, including plaintext, require paragraph-level bidi layout.",
            source=source_id,
        )
    for name, accepted in (
        ("font-style", {"normal"}),
        ("font-stretch", {"normal"}),
        ("font-variant", {"normal"}),
        ("font-weight", {"normal", "400"}),
    ):
        if styles[name].casefold() not in accepted:
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "font-face-selection",
                "SVG_TEXT_FONT_UNREPRESENTABLE",
                f"{name}={styles[name]!r} requires another explicitly pinned font face.",
                source=source_id,
            )

    size = _single_number(styles["font-size"], 16, "font-size", source_id)
    if size <= 0:
        raise IconFontError(
            "SVG_TEXT_SIZE_INVALID",
            "Text font-size must be positive.",
            source=source_id,
        )
    x = _single_number(element.get("x"), 0, "x", source_id)
    y = _single_number(element.get("y"), 0, "y", source_id)
    x += _single_number(element.get("dx"), 0, "dx", source_id)
    y += _single_number(element.get("dy"), 0, "dy", source_id)
    _data, font, _hb_font, infos, positions = _shape_text(
        text,
        text_font,
        direction=direction,
        language=language,
        source_id=source_id,
    )
    budget.accept_shaped_glyphs(len(infos))
    try:
        units_per_em = font["head"].unitsPerEm
        scale = size / units_per_em
        total_advance = sum(position.x_advance for position in positions) * scale
        anchor = styles["text-anchor"].casefold()
        if anchor == "middle":
            anchor_shift = -total_advance / 2
        elif anchor == "end":
            anchor_shift = -total_advance if direction == "ltr" else 0
        elif anchor == "start":
            anchor_shift = 0 if direction == "ltr" else -total_advance
        else:
            raise IconFontError(
                "SVG_TEXT_ANCHOR_INVALID",
                f"text-anchor={anchor!r} is invalid.",
                source=source_id,
            )
        glyph_set = font.getGlyphSet()
        glyph_order = font.getGlyphOrder()
        glyph_attributes = {
            name: element.attrib[name]
            for name in _GLYPH_PRESENTATION_ATTRIBUTES
            if name in element.attrib
        }
        outlined_paths: list[dict[str, str]] = []
        local_path_work = 0
        cursor_x = 0
        cursor_y = 0
        for info, position in zip(infos, positions, strict=True):
            glyph_name = glyph_order[info.codepoint]
            remaining_path_work = budget.remaining_path_work(local_path_work)
            if remaining_path_work < 0:
                budget.raise_path_limit(budget.path_command_work + local_path_work)
            pen = _LimitedSVGPathPen(glyph_set, remaining_path_work)
            try:
                glyph_set[glyph_name].draw(pen)
            except _PathWorkLimitExceeded:
                budget.raise_path_limit(
                    budget.path_command_work + local_path_work + pen.command_work
                )
            commands = pen.getCommands()
            local_path_work += pen.command_work
            if commands:
                transform = Affine2D.identity().matrix(
                    scale,
                    0,
                    0,
                    -scale,
                    x + anchor_shift + (cursor_x + position.x_offset) * scale,
                    y - (cursor_y + position.y_offset) * scale,
                )
                path = SVGPath(d=commands).apply_transform(transform)
                path_attributes = {"d": path.d, **glyph_attributes}
                projected_elements += 1
                projected_bytes += _synthetic_element_bytes(
                    f"{{{_SVG_NAMESPACE}}}path",
                    path_attributes,
                )
                budget.ensure_projected_tree(projected_elements, projected_bytes)
                outlined_paths.append(path_attributes)
            cursor_x += position.x_advance
            cursor_y += position.y_advance
        budget.accept_replacement(
            projected_elements=projected_elements,
            projected_bytes=projected_bytes,
            path_command_work=local_path_work,
        )
        for attributes in outlined_paths:
            group.append(root.makeelement(f"{{{_SVG_NAMESPACE}}}path", attributes))
        return group
    finally:
        font.close()


def outline_text(
    root: etree._Element,
    *,
    text_fonts: dict[str, TextFont],
    source_id: str,
    max_expanded_elements: int,
    max_expanded_bytes: int,
    max_path_commands: int,
) -> None:
    replacements: list[tuple[etree._Element, etree._Element]] = []
    budget = _TextWorkBudget(
        root,
        max_expanded_elements=max_expanded_elements,
        max_expanded_bytes=max_expanded_bytes,
        max_path_commands=max_path_commands,
        source_id=source_id,
    )

    def visit(
        element: etree._Element,
        inherited: dict[str, str],
        xml_space: str,
        xml_language: str | None,
    ) -> None:
        styles = {
            "direction": _keyword(element.get("direction"), inherited["direction"], "ltr"),
            "font-family": _keyword(element.get("font-family"), inherited["font-family"], ""),
            "font-size": _keyword(element.get("font-size"), inherited["font-size"], "16"),
            "font-stretch": _keyword(
                element.get("font-stretch"), inherited["font-stretch"], "normal"
            ),
            "font-style": _keyword(element.get("font-style"), inherited["font-style"], "normal"),
            "font-variant": _keyword(
                element.get("font-variant"), inherited["font-variant"], "normal"
            ),
            "font-weight": _keyword(element.get("font-weight"), inherited["font-weight"], "normal"),
            "text-anchor": _keyword(element.get("text-anchor"), inherited["text-anchor"], "start"),
            "unicode-bidi": _keyword(
                element.get("unicode-bidi"), inherited["unicode-bidi"], "normal"
            ),
            "writing-mode": _keyword(
                element.get("writing-mode"), inherited["writing-mode"], "horizontal-tb"
            ),
        }
        current_space = element.get("{http://www.w3.org/XML/1998/namespace}space", xml_space)
        if current_space not in {"default", "preserve"}:
            raise IconFontError(
                "SVG_TEXT_WHITESPACE_INVALID",
                f"xml:space={current_space!r} must be 'default' or 'preserve'.",
                source=source_id,
            )
        current_language = element.get("{http://www.w3.org/XML/1998/namespace}lang", xml_language)
        if strip_ns(element.tag) == "text":
            if len(element):
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "structured-svg-text",
                    "SVG_TEXT_LAYOUT_UNREPRESENTABLE",
                    "Nested SVG text content requires the extended text-layout profile.",
                    source=source_id,
                )
            if element.get("textLength") is not None or element.get("lengthAdjust") is not None:
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "text-length-adjustment",
                    "SVG_TEXT_LAYOUT_UNREPRESENTABLE",
                    "textLength and lengthAdjust require the extended text-layout profile.",
                    source=source_id,
                )
            if element.get("rotate") is not None:
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "per-character-text-rotation",
                    "SVG_TEXT_LAYOUT_UNREPRESENTABLE",
                    "Per-character text rotation requires the extended text-layout profile.",
                    source=source_id,
                )
            text = element.text or ""
            if current_space != "preserve":
                text = re.sub(r"\s+", " ", text).strip()
            if not text:
                replacement = root.makeelement("{http://www.w3.org/2000/svg}g")
                replacement.tail = element.tail
                replacements.append((element, replacement))
                return
            if (
                element.get("fill", "black").casefold() == "none"
                and element.get("stroke", "none").casefold() == "none"
            ):
                replacement = root.makeelement("{http://www.w3.org/2000/svg}g")
                replacement.tail = element.tail
                replacements.append((element, replacement))
                return
            font_size = _single_number(styles["font-size"], 16, "font-size", source_id)
            if font_size == 0:
                replacement = root.makeelement("{http://www.w3.org/2000/svg}g")
                replacement.tail = element.tail
                replacements.append((element, replacement))
                return
            if font_size < 0:
                raise IconFontError(
                    "SVG_TEXT_SIZE_INVALID",
                    "Text font-size cannot be negative.",
                    source=source_id,
                )
            families = _family_names(styles["font-family"], source_id)
            font_by_folded = {name.casefold(): font for name, font in text_fonts.items()}
            selected = next(
                (
                    (family, font_by_folded[family.casefold()])
                    for family in families
                    if family.casefold() in font_by_folded
                ),
                None,
            )
            text_font = selected[1] if selected is not None else None
            if text_font is None:
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "unpinned-text-font",
                    "SVG_TEXT_FONT_UNREPRESENTABLE",
                    f"Text font families {families!r} have no pinned textFonts entry.",
                    source=source_id,
                )
            replacements.append(
                (
                    element,
                    _outline_run(
                        root,
                        element,
                        text,
                        text_font,
                        styles,
                        current_language,
                        source_id,
                        budget,
                    ),
                )
            )
            return
        for child in element:
            if isinstance(child.tag, str):
                visit(
                    cast(etree._Element, child),
                    styles,
                    current_space,
                    current_language,
                )

    defaults = {
        "direction": "ltr",
        "font-family": "",
        "font-size": "16",
        "font-stretch": "normal",
        "font-style": "normal",
        "font-variant": "normal",
        "font-weight": "normal",
        "text-anchor": "start",
        "unicode-bidi": "normal",
        "writing-mode": "horizontal-tb",
    }
    visit(root, defaults, "default", None)
    for element, replacement in replacements:
        parent = element.getparent()
        if parent is not None:
            parent.replace(element, replacement)
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for name in _TEXT_STYLE_PROPERTIES:
            element.attrib.pop(name, None)
