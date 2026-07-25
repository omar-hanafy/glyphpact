from __future__ import annotations

import colorsys
import copy
import math
import re
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, NoReturn, cast

import webcolors
from lxml import etree
from picosvg import svg_pathops
from picosvg.geometric_types import Rect
from picosvg.svg import SVG, from_element
from picosvg.svg_meta import strip_ns, xlinkns
from picosvg.svg_transform import Affine2D
from picosvg.svg_types import SVGPath
from tinycss2.color4 import Color as CssColor  # type: ignore[import-untyped]
from tinycss2.color4 import parse_color as parse_css_color

from .config import BuildConfig, LossyPolicy, PartialAlphaFallback
from .css_cascade import materialize_css
from .discovery import SvgSource
from .errors import (
    ConversionIssue,
    IconFontError,
    SvgFeatureBatchError,
    SvgFeatureClass,
    SvgFeatureError,
    conversion_notice,
)
from .text_outliner import outline_text

_FORBIDDEN_ELEMENTS = frozenset(
    {
        "animate",
        "animateColor",
        "animateMotion",
        "animateTransform",
        "audio",
        "discard",
        "filter",
        "foreignObject",
        "image",
        "mask",
        "mpath",
        "script",
        "set",
        "style",
        "textPath",
        "tspan",
        "video",
    }
)

_PAINT_SERVER_ELEMENTS = frozenset({"linearGradient", "pattern", "radialGradient", "stop"})

_SVG_NAMESPACE = "http://www.w3.org/2000/svg"

_SUPPORTED_ELEMENTS = frozenset(
    {
        "a",
        "circle",
        "clipPath",
        "defs",
        "desc",
        "ellipse",
        "g",
        "line",
        "marker",
        "path",
        "polygon",
        "polyline",
        "rect",
        "svg",
        "symbol",
        "switch",
        "text",
        "title",
        "use",
        "view",
    }
)

_FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "class",
        "filter",
        "mask",
    }
)

_ALLOWED_STYLE_PROPERTIES = frozenset(
    {
        "-inkscape-stroke",
        "clip-path",
        "clip-rule",
        "color",
        "color-interpolation",
        "color-interpolation-filters",
        "color-rendering",
        "cursor",
        "display",
        "direction",
        "fill",
        "fill-opacity",
        "fill-rule",
        "font-family",
        "font-size",
        "font-stretch",
        "font-style",
        "font-variant",
        "font-weight",
        "isolation",
        "lengthadjust",
        "mix-blend-mode",
        "opacity",
        "overflow",
        "paint-order",
        "pathlength",
        "text-anchor",
        "stroke",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "stroke-opacity",
        "stroke-width",
        "transform",
        "unicode-bidi",
        "vector-effect",
        "visibility",
        "writing-mode",
    }
)

_SUPPORTED_ATTRIBUTES = frozenset(
    {
        "clippathunits",
        "clip-path",
        "clip-rule",
        "color",
        "color-interpolation",
        "color-interpolation-filters",
        "color-rendering",
        "cursor",
        "cx",
        "cy",
        "d",
        "direction",
        "display",
        "dx",
        "dy",
        "fill",
        "fill-opacity",
        "fill-rule",
        "focusable",
        "font-family",
        "font-size",
        "font-stretch",
        "font-style",
        "font-variant",
        "font-weight",
        "height",
        "href",
        "id",
        "image-rendering",
        "isolation",
        "lengthadjust",
        "marker-end",
        "markerheight",
        "marker-mid",
        "marker-start",
        "markerunits",
        "markerwidth",
        "mix-blend-mode",
        "opacity",
        "orient",
        "overflow",
        "paint-order",
        "pathlength",
        "points",
        "preserveaspectratio",
        "pointer-events",
        "r",
        "refx",
        "refy",
        "requiredextensions",
        "requiredfeatures",
        "role",
        "rotate",
        "rx",
        "ry",
        "stroke",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "stroke-opacity",
        "stroke-width",
        "style",
        "systemlanguage",
        "shape-rendering",
        "tabindex",
        "text-anchor",
        "textlength",
        "transform",
        "unicode-bidi",
        "version",
        "vector-effect",
        "viewbox",
        "visibility",
        "width",
        "writing-mode",
        "x",
        "x1",
        "x2",
        "y",
        "y1",
        "y2",
    }
)

_CSS_PROPERTIES = _ALLOWED_STYLE_PROPERTIES | frozenset(
    {
        "filter",
        "mask",
        "marker-end",
        "marker-mid",
        "marker-start",
        "stop-color",
        "stop-opacity",
        "vector-effect",
    }
)

_SOLID_HEX_PAINT = re.compile(r"#[0-9a-f]{3}(?:[0-9a-f]{3})?", re.IGNORECASE)
_ALPHA_HEX_PAINT = re.compile(r"#[0-9a-f]{4}(?:[0-9a-f]{4})?", re.IGNORECASE)
_PAINT_IDENTIFIER = re.compile(r"[a-z]+", re.IGNORECASE)
_NUMBER_TOKEN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_PERCENT_TOKEN = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)%")
_CSS_LENGTH_TOKEN = re.compile(
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(%|px|in|cm|mm|q|pt|pc)?",
    re.IGNORECASE,
)
_CSS_DIMENSION_TOKEN = re.compile(
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(%|[a-z]+)?",
    re.IGNORECASE,
)
_RELATIVE_LENGTH_UNITS = frozenset(
    {
        "cap",
        "ch",
        "dvb",
        "dvh",
        "dvi",
        "dvmax",
        "dvmin",
        "dvw",
        "em",
        "ex",
        "ic",
        "lh",
        "lvb",
        "lvh",
        "lvi",
        "lvmax",
        "lvmin",
        "lvw",
        "rem",
        "rlh",
        "svb",
        "svh",
        "svi",
        "svmax",
        "svmin",
        "svw",
        "vb",
        "vh",
        "vi",
        "vmax",
        "vmin",
        "vw",
    }
)
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
_LOSSY_GRADIENT_ALPHA = 1 << 0
_LOSSY_PATTERN = 1 << 1
_LOSSY_GROUP_OPACITY = 1 << 2
_LOSSY_FRACTIONAL_ALPHA = 1 << 3
_LOSSY_GRADIENT_COVERAGE = 1 << 4
_LAYERED_PAINT_MARKER = 1 << 23
_MARKER_TARGET_OPACITY = "data-glyphpact-marker-opacity"
_LOSSY_PAINT_MASK = (
    _LOSSY_GRADIENT_ALPHA
    | _LOSSY_PATTERN
    | _LOSSY_GROUP_OPACITY
    | _LOSSY_FRACTIONAL_ALPHA
    | _LOSSY_GRADIENT_COVERAGE
)
_MAX_LAYERED_ALPHA_LAYERS = 8
_LOSSY_FEATURES = {
    _LOSSY_GRADIENT_ALPHA: (
        "spatial-gradient-alpha",
        "SVG_GRADIENT_ALPHA_APPROXIMATED",
        "A surviving gradient with spatially varying alpha was flattened to the painted "
        "shape's opaque coverage.",
        "Use opaque stops, cover the region with later opaque paint, or allow lossy conversion.",
        {"approximation": "painted-shape-silhouette"},
    ),
    _LOSSY_PATTERN: (
        "pattern-paint",
        "SVG_PATTERN_APPROXIMATED",
        "A surviving declared vector pattern was replaced by the target shape's opaque "
        "silhouette; tile gaps and clipped or empty content are not preserved.",
        "Expand the pattern into bounded outlines, cover it later, or allow this coarse loss.",
        {"approximation": "declared-pattern-target-silhouette"},
    ),
    _LOSSY_GROUP_OPACITY: (
        "group-opacity",
        "SVG_GROUP_OPACITY_APPROXIMATED",
        "A surviving partially transparent compositing group was flattened to opaque coverage.",
        "Cover the group with later opaque paint, outline its final silhouette, or allow loss.",
        {"approximation": "any-positive-alpha-to-opaque"},
    ),
    _LOSSY_FRACTIONAL_ALPHA: (
        "fractional-alpha",
        "SVG_PARTIAL_ALPHA_APPROXIMATED",
        "Surviving fractional alpha was flattened to opaque coverage.",
        "Make the final alpha silhouette binary or keep strict lossy=error.",
        {"approximation": "any-positive-alpha-to-opaque"},
    ),
    _LOSSY_GRADIENT_COVERAGE: (
        "radial-gradient-coverage",
        "SVG_GRADIENT_COVERAGE_APPROXIMATED",
        "A radial gradient whose cone may not cover the target was replaced by the target "
        "shape's opaque silhouette.",
        "Keep the focal circle inside the end circle or allow this painted-shape loss.",
        {"approximation": "painted-shape-silhouette"},
    ),
}
_PATH_COMMAND_TOKEN = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]")

_GEOMETRY_LENGTH_ATTRIBUTES = {
    "circle": {"cx", "cy", "r"},
    "ellipse": {"cx", "cy", "rx", "ry"},
    "line": {"x1", "x2", "y1", "y2"},
    "rect": {"height", "rx", "ry", "width", "x", "y"},
}
_NONNEGATIVE_GEOMETRY_LENGTHS = {
    ("circle", "r"),
    ("ellipse", "rx"),
    ("ellipse", "ry"),
    ("rect", "height"),
    ("rect", "rx"),
    ("rect", "ry"),
    ("rect", "width"),
}


@dataclass(frozen=True)
class CanonicalLayer:
    paths: tuple[str, ...]
    fill_rules: tuple[str, ...]
    opacity: float
    bounds: tuple[float, float, float, float]
    path_command_count: int


@dataclass(frozen=True)
class CanonicalGlyph:
    paths: tuple[str, ...]
    fill_rules: tuple[str, ...]
    view_box: tuple[float, float, float, float]
    bounds: tuple[float, float, float, float]
    source_shape_count: int
    path_command_count: int
    issues: tuple[ConversionIssue, ...] = ()
    layers: tuple[CanonicalLayer, ...] = ()


@dataclass(frozen=True)
class _PaintServerResolution:
    paint: str
    alpha: float
    lossy_provenance: int = 0


@dataclass(frozen=True)
class _UrlReference:
    start: int
    end: int
    target: str


@dataclass(frozen=True)
class _PaintServerReference:
    identifier: str
    fallback: str | None


@dataclass(frozen=True)
class _PathSegment:
    start: tuple[float, float]
    end: tuple[float, float]
    start_tangent: tuple[float, float]
    end_tangent: tuple[float, float]
    logical_end: bool = True


class _ConversionContext:
    def __init__(self, config: BuildConfig, source_id: str) -> None:
        self.config = config
        self.source_id = source_id
        override = config.icons.get(source_id)
        self.partial_alpha = override.partial_alpha if override is not None else None
        self._lossy: dict[tuple[str, str, str], tuple[int, dict[str, Any]]] = {}
        self._layered_paints: dict[int, tuple[int, float]] = {}
        self._layered_paint_tokens: dict[tuple[int, str], int] = {}

    def layered_paint(self, bits: int, alpha: float) -> str:
        key = (bits, alpha.hex())
        token = self._layered_paint_tokens.get(key)
        if token is None:
            token = len(self._layered_paint_tokens) + 1
            maximum_token = (_LAYERED_PAINT_MARKER - 1) >> 5
            if token > maximum_token:
                raise IconFontError(
                    "SVG_LAYERED_ALPHA_LIMIT",
                    "The SVG exceeds the bounded number of exact alpha paint tokens.",
                    source=self.source_id,
                )
            self._layered_paint_tokens[key] = token
            self._layered_paints[token] = (bits, alpha)
        encoded = _LAYERED_PAINT_MARKER | (token << 5) | bits
        return f"#{encoded:06x}"

    def layered_alpha(self, paint: str) -> float | None:
        value = paint.strip().casefold()
        if re.fullmatch(r"#[0-9a-f]{6}", value) is None:
            return None
        encoded = int(value[1:], 16)
        if not encoded & _LAYERED_PAINT_MARKER:
            return None
        token = (encoded & (_LAYERED_PAINT_MARKER - 1)) >> 5
        recorded = self._layered_paints.get(token)
        if recorded is None or recorded[0] != (encoded & _LOSSY_PAINT_MASK):
            raise IconFontError(
                "SVG_LAYERED_ALPHA_TOKEN_INVALID",
                "Canonicalization corrupted an internal exact-alpha paint token.",
                source=self.source_id,
            )
        return recorded[1]

    def lossy(
        self,
        feature: str,
        code: str,
        message: str,
        *,
        hint: str,
        details: dict[str, Any] | None = None,
        scoped_opt_in: bool = False,
    ) -> None:
        if self.config.policy.lossy is LossyPolicy.ERROR and not scoped_opt_in:
            raise SvgFeatureError(
                SvgFeatureClass.LOSSY,
                feature,
                code,
                message,
                source=self.source_id,
                hint=hint,
                details=details,
            )
        key = (code, feature, message)
        count, first_details = self._lossy.get(key, (0, details or {}))
        self._lossy[key] = (count + 1, first_details)

    def unrepresentable(
        self,
        feature: str,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> NoReturn:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            feature,
            code,
            message,
            source=self.source_id,
            hint=hint,
            details=details,
        )

    def issues(self) -> tuple[ConversionIssue, ...]:
        return tuple(
            conversion_notice(
                code,
                message,
                source=self.source_id,
                feature=feature,
                details={**details, "occurrences": count},
            )
            for (code, feature, message), (count, details) in sorted(self._lossy.items())
        )


def _url_references(value: str, source_id: str) -> tuple[_UrlReference, ...]:
    """Parse CSS url() tokens in linear time without regex backtracking."""

    if "\\" in value:
        raise IconFontError(
            "SVG_URL_INVALID",
            "CSS escapes in SVG attribute url() values are outside the bounded profile.",
            source=source_id,
        )
    references: list[_UrlReference] = []
    index = 0
    length = len(value)
    while index + 4 <= length:
        if value[index : index + 4].casefold() != "url(":
            index += 1
            continue
        start = index
        index += 4
        while index < length and value[index].isspace():
            index += 1
        if index >= length:
            raise IconFontError(
                "SVG_URL_INVALID",
                f"Reference {value!r} contains an unterminated url() token.",
                source=source_id,
            )

        quote = value[index] if value[index] in {"'", '"'} else None
        if quote is not None:
            index += 1
            target_start = index
            while index < length and value[index] != quote:
                if value[index] == "\\":
                    raise IconFontError(
                        "SVG_URL_INVALID",
                        "Escapes inside SVG url() references are outside the bounded profile.",
                        source=source_id,
                    )
                index += 1
            if index >= length:
                raise IconFontError(
                    "SVG_URL_INVALID",
                    f"Reference {value!r} contains an unterminated quoted url() token.",
                    source=source_id,
                )
            target = value[target_start:index]
            index += 1
            while index < length and value[index].isspace():
                index += 1
            if index >= length or value[index] != ")":
                raise IconFontError(
                    "SVG_URL_INVALID",
                    f"Reference {value!r} contains a malformed url() token.",
                    source=source_id,
                )
        else:
            target_start = index
            while index < length and value[index] != ")":
                character = value[index]
                if character in {"'", '"', "(", "\\"}:
                    raise IconFontError(
                        "SVG_URL_INVALID",
                        f"Reference {value!r} contains a malformed url() token.",
                        source=source_id,
                    )
                index += 1
            if index >= length:
                raise IconFontError(
                    "SVG_URL_INVALID",
                    f"Reference {value!r} contains an unterminated url() token.",
                    source=source_id,
                )
            raw_target = value[target_start:index]
            target = raw_target.strip()
            if any(character.isspace() for character in target):
                raise IconFontError(
                    "SVG_URL_INVALID",
                    "Unquoted SVG url() references cannot contain whitespace.",
                    source=source_id,
                )
        if not target:
            raise IconFontError(
                "SVG_URL_INVALID",
                "SVG url() references cannot be empty.",
                source=source_id,
            )
        index += 1
        references.append(_UrlReference(start, index, target))
    return tuple(references)


def _single_local_url(value: str, source_id: str, code: str, label: str) -> str:
    stripped = value.strip()
    references = _url_references(stripped, source_id)
    if (
        len(references) != 1
        or references[0].start != 0
        or references[0].end != len(stripped)
        or not references[0].target.startswith("#")
        or len(references[0].target) == 1
    ):
        raise IconFontError(
            code,
            f"{label} {value!r} must use exactly one local url(#id) reference.",
            source=source_id,
        )
    return references[0].target[1:]


def _paint_server_reference(value: str, source_id: str) -> _PaintServerReference:
    stripped = value.strip()
    references = _url_references(stripped, source_id)
    if (
        len(references) != 1
        or references[0].start != 0
        or not references[0].target.startswith("#")
        or len(references[0].target) == 1
    ):
        raise IconFontError(
            "SVG_PAINT_SERVER_INVALID",
            f"Paint server {value!r} must start with one local url(#id) reference.",
            source=source_id,
        )
    fallback = stripped[references[0].end :].strip()
    if fallback:
        if fallback.lstrip().casefold().startswith("url("):
            raise IconFontError(
                "SVG_PAINT_SERVER_INVALID",
                "A paint-server fallback cannot contain another url() reference.",
                source=source_id,
            )
        _validate_paint(fallback, source_id)
        if fallback.casefold() in {"inherit", "initial", "unset"}:
            raise IconFontError(
                "SVG_PAINT_SERVER_INVALID",
                "A paint-server fallback must be a color or none, not a CSS-wide keyword.",
                source=source_id,
            )
    return _PaintServerReference(references[0].target[1:], fallback or None)


def _reject_unsafe_xml(source: SvgSource) -> None:
    lowered = source.content.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise IconFontError(
            "SVG_DTD_FORBIDDEN",
            "DOCTYPE and ENTITY declarations are forbidden.",
            source=source.source_id,
        )


def _parse_style(style: str, source_id: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for declaration in style.split(";"):
        declaration = declaration.strip()
        if not declaration:
            continue
        if ":" not in declaration:
            raise IconFontError(
                "SVG_STYLE_INVALID",
                f"Malformed inline style declaration {declaration!r}.",
                source=source_id,
            )
        name, value = declaration.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if name not in _ALLOWED_STYLE_PROPERTIES:
            raise IconFontError(
                "SVG_STYLE_UNSUPPORTED",
                f"Inline style property {name!r} cannot be represented safely.",
                source=source_id,
                hint="Bake the effect into opaque vector outlines before building the font.",
            )
        if name == "-inkscape-stroke" and value != "none":
            raise IconFontError(
                "SVG_STYLE_UNSUPPORTED",
                "Only the no-op '-inkscape-stroke:none' editor hint is accepted.",
                source=source_id,
            )
        if name in {"color", "fill", "stroke"}:
            _validate_paint(value, source_id)
        if name in {"fill-opacity", "opacity", "stroke-opacity"}:
            _validate_opacity(value, name, source_id)
        _reject_external_url(value, source_id)
        properties[name] = value
    return properties


def _opacity_value(value: str, name: str, source_id: str) -> float:
    text = value.strip()
    if text.endswith("%"):
        percentage = _percentage_component(text)
        if percentage is None:
            raise IconFontError(
                "SVG_OPACITY_INVALID",
                f"{name}={value!r} is not a finite percentage.",
                source=source_id,
            )
        return min(1.0, max(0.0, percentage / 100.0))
    try:
        opacity = float(text)
    except ValueError as error:
        raise IconFontError(
            "SVG_OPACITY_INVALID",
            f"{name} must be a finite number or percentage.",
            source=source_id,
        ) from error
    if not math.isfinite(opacity):
        raise IconFontError(
            "SVG_OPACITY_INVALID",
            f"{name} must be finite.",
            source=source_id,
        )
    return min(1.0, max(0.0, opacity))


def _validate_opacity(value: str, name: str, source_id: str) -> None:
    if value.strip().casefold() in {"inherit", "initial", "unset"}:
        return
    _opacity_value(value, name, source_id)


def _alpha_component(value: str) -> float | None:
    percentage = _percentage_component(value)
    if percentage is not None:
        return min(1.0, max(0.0, percentage / 100.0))
    number = _numeric_component(value)
    if number is None:
        return None
    return min(1.0, max(0.0, number))


def _alpha_paint(value: str) -> tuple[str, float] | None:
    paint = value.strip().casefold()
    try:
        parsed_color = parse_css_color(value)
    except (TypeError, ValueError):
        parsed_color = None
    if isinstance(parsed_color, CssColor):
        css_alpha = 0.0 if parsed_color.alpha is None else float(parsed_color.alpha)
        if math.isfinite(css_alpha):
            return "#000000", min(1.0, max(0.0, css_alpha))
    compact = re.sub(r"\s+", "", paint)
    if compact == "transparent":
        return "#000000", 0.0
    if _ALPHA_HEX_PAINT.fullmatch(compact):
        digits = compact[1:]
        if len(digits) == 4:
            red, green, blue, alpha_hex = (character * 2 for character in digits)
        else:
            red, green, blue, alpha_hex = (
                digits[0:2],
                digits[2:4],
                digits[4:6],
                digits[6:8],
            )
        return f"#{red}{green}{blue}", int(alpha_hex, 16) / 255.0

    function = re.fullmatch(r"(rgba?|hsla?)\((.*)\)", paint)
    if function is None:
        return None
    function_name = function.group(1)
    body = function.group(2).strip()
    alpha_text: str | None = None
    if "/" in body:
        if body.count("/") != 1:
            return None
        color_body, alpha_text = (part.strip() for part in body.split("/", 1))
        components = tuple(color_body.split())
    elif "," in body:
        components_with_alpha = tuple(part.strip() for part in body.split(","))
        if len(components_with_alpha) != 4:
            return None
        components = components_with_alpha[:3]
        alpha_text = components_with_alpha[3]
    else:
        components_with_alpha = tuple(body.split())
        if len(components_with_alpha) != 4:
            return None
        components = components_with_alpha[:3]
        alpha_text = components_with_alpha[3]
    if alpha_text is None or len(components) != 3:
        return None
    alpha = _alpha_component(alpha_text)
    if alpha is None:
        return None
    comma_separated = "," in body
    if function_name.startswith("rgb"):
        if not _valid_rgb_components(components, comma_separated=comma_separated):
            return None
        opaque = "rgb(" + " ".join(components) + ")"
    else:
        if not _valid_hsl_components(components):
            return None
        opaque = "hsl(" + " ".join(components) + ")"
    return opaque, alpha


def _validate_paint(value: str, source_id: str) -> None:
    paint = value.strip().casefold()
    compact = re.sub(r"\s+", "", paint)
    if _alpha_paint(value) is not None:
        return
    if compact == "transparent" or _ALPHA_HEX_PAINT.fullmatch(compact):
        raise IconFontError(
            "SVG_PAINT_INVALID",
            f"Paint {value!r} has invalid alpha-color syntax.",
            source=source_id,
        )
    if compact.startswith(("rgba(", "hsla(")) or ("/" in compact and "(" in compact):
        raise IconFontError(
            "SVG_PAINT_INVALID",
            f"Paint {value!r} has invalid alpha-color syntax.",
            source=source_id,
        )
    if compact.startswith("url("):
        return
    if paint == "none":
        return
    if paint in {
        "currentcolor",
        "inherit",
        "initial",
        "unset",
    }:
        return
    if paint in {"context-fill", "context-stroke"}:
        return
    if paint in {"revert", "revert-layer"}:
        raise IconFontError(
            "SVG_PAINT_UNSUPPORTED",
            f"Context-dependent paint {value!r} cannot be flattened safely.",
            source=source_id,
            hint="Resolve the paint to one explicit opaque solid color.",
        )
    if _SOLID_HEX_PAINT.fullmatch(paint):
        return
    if _PAINT_IDENTIFIER.fullmatch(paint):
        try:
            webcolors.name_to_hex(paint, spec=webcolors.CSS3)
        except ValueError as error:
            raise IconFontError(
                "SVG_PAINT_UNSUPPORTED",
                f"{value!r} is not an SVG 1.1 named color.",
                source=source_id,
            ) from error
        return
    function = re.fullmatch(r"(rgb|hsl)\((.*)\)", paint)
    if function is not None:
        body = function.group(2).strip()
        comma_separated = "," in body
        components = (
            tuple(component.strip() for component in body.split(","))
            if comma_separated
            else tuple(body.split())
        )
        if len(components) == 4 and all(components):
            raise IconFontError(
                "SVG_PARTIAL_OPACITY_UNSUPPORTED",
                "Four-component color functions carry an alpha channel.",
                source=source_id,
            )
        if len(components) == 3 and all(components):
            if function.group(1) == "rgb" and _valid_rgb_components(
                components, comma_separated=comma_separated
            ):
                return
            if function.group(1) == "hsl" and _valid_hsl_components(components):
                return
    raise IconFontError(
        "SVG_PAINT_UNSUPPORTED",
        f"Paint {value!r} is not a provably opaque solid color.",
        source=source_id,
        hint="Use an opaque named color, #RGB, #RRGGBB, rgb(), or hsl().",
    )


def _numeric_component(value: str) -> float | None:
    if _NUMBER_TOKEN.fullmatch(value) is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _percentage_component(value: str) -> float | None:
    match = _PERCENT_TOKEN.fullmatch(value)
    if match is None:
        return None
    result = float(match.group(1))
    return result if math.isfinite(result) else None


def _valid_rgb_components(components: tuple[str, ...], *, comma_separated: bool) -> bool:
    component_is_percentage = tuple(
        _percentage_component(component) is not None for component in components
    )
    if comma_separated and len(set(component_is_percentage)) != 1:
        return False
    for component in components:
        percentage = _percentage_component(component)
        if percentage is not None:
            if not 0 <= percentage <= 100:
                return False
            continue
        number = _numeric_component(component)
        if number is None or not 0 <= number <= 255:
            return False
    return True


def _valid_hsl_components(components: tuple[str, ...]) -> bool:
    hue = _numeric_component(components[0])
    saturation = _percentage_component(components[1])
    lightness = _percentage_component(components[2])
    return (
        hue is not None
        and saturation is not None
        and lightness is not None
        and 0 <= saturation <= 100
        and 0 <= lightness <= 100
    )


def _canonical_solid_paint(value: str) -> tuple[float, float, float]:
    """Normalize an already-validated opaque paint for equivalence checks."""
    paint = value.strip().casefold()
    if _SOLID_HEX_PAINT.fullmatch(paint):
        rgb = webcolors.hex_to_rgb(paint)
        return float(rgb.red), float(rgb.green), float(rgb.blue)
    if _PAINT_IDENTIFIER.fullmatch(paint):
        rgb = webcolors.hex_to_rgb(webcolors.name_to_hex(paint, spec=webcolors.CSS3))
        return float(rgb.red), float(rgb.green), float(rgb.blue)

    function = re.fullmatch(r"(rgb|hsl)\((.*)\)", paint)
    assert function is not None
    body = function.group(2).strip()
    components = (
        tuple(component.strip() for component in body.split(","))
        if "," in body
        else tuple(body.split())
    )
    if function.group(1) == "rgb":
        channels = tuple(
            percentage * 2.55
            if (percentage := _percentage_component(component)) is not None
            else float(component)
            for component in components
        )
    else:
        hue = float(components[0]) % 360 / 360
        saturation = float(components[1][:-1]) / 100
        lightness = float(components[2][:-1]) / 100
        channels = tuple(
            channel * 255 for channel in colorsys.hls_to_rgb(hue, lightness, saturation)
        )
    return (
        round(channels[0], 9),
        round(channels[1], 9),
        round(channels[2], 9),
    )


def _lossy_paint(bits: int) -> str:
    if bits <= 0 or bits & ~_LOSSY_PAINT_MASK:
        raise ValueError(f"Invalid lossy paint bitset: {bits}")
    return f"#{bits:06x}"


def _lossy_paint_bits(value: str) -> int:
    paint = value.strip().casefold()
    if re.fullmatch(r"#[0-9a-f]{6}", paint) is None:
        return 0
    bits = int(paint[1:], 16)
    if bits & _LAYERED_PAINT_MARKER:
        bits &= _LOSSY_PAINT_MASK
    return bits if bits and not bits & ~_LOSSY_PAINT_MASK else 0


def _attribute_namespace(raw_name: str) -> str | None:
    if not raw_name.startswith("{"):
        return None
    return raw_name[1:].split("}", 1)[0]


def _has_ancestor(element: Any, tag: str) -> bool:
    parent = element.getparent()
    while parent is not None:
        if isinstance(parent.tag, str) and strip_ns(parent.tag) == tag:
            return True
        parent = parent.getparent()
    return False


def _element_namespace(raw_name: str) -> str | None:
    return _attribute_namespace(raw_name)


def _drop_nonrendering_metadata(root: Any, source_id: str) -> None:
    def visit(parent: Any) -> None:
        for element in tuple(parent):
            if not isinstance(element.tag, str):
                continue
            namespace = _element_namespace(element.tag)
            if strip_ns(element.tag) == "metadata" or namespace not in {None, _SVG_NAMESPACE}:
                parent.remove(element)
                continue
            if namespace is None:
                raise IconFontError(
                    "SVG_NAMESPACE_INVALID",
                    "Elements that reset the SVG namespace are not SVG rendering elements.",
                    source=source_id,
                )
            visit(element)

    visit(root)


def _validate_unique_ids(root: Any, source_id: str) -> None:
    identifiers: set[str] = set()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        identifier = element.get("id")
        if identifier is not None:
            if not identifier:
                raise IconFontError(
                    "SVG_ID_INVALID",
                    "SVG id attributes cannot be empty.",
                    source=source_id,
                )
            if identifier in identifiers:
                raise IconFontError(
                    "SVG_ID_DUPLICATE",
                    f"Duplicate id {identifier!r} makes local references ambiguous.",
                    source=source_id,
                )
            identifiers.add(identifier)


def _canonicalize_href_precedence(root: Any) -> None:
    xlink_href = f"{{{xlinkns()}}}href"
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        bare_href = element.attrib.pop("href", None)
        if bare_href is not None:
            element.set(xlink_href, bare_href)


def _validate_local_references(root: Any, source_id: str) -> None:
    identifiers = {
        identifier
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }
    references: list[str] = []
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        tag = strip_ns(element.tag)
        for raw_name, value in element.attrib.items():
            lowered = strip_ns(raw_name).lower()
            if tag == "a" and lowered == "href":
                continue
            if lowered == "href" and value.startswith("#"):
                references.append(value[1:])
            if lowered in {"fill", "stroke"} and value.lstrip().casefold().startswith("url("):
                # SVG paint references deliberately fail over to their optional
                # fallback, or to none when omitted. Missing and wrong-type paint
                # targets are therefore not broken structural references.
                _paint_server_reference(value, source_id)
                continue
            for reference in _url_references(value, source_id):
                target = reference.target
                if target.startswith("#"):
                    references.append(target[1:])
    missing = sorted({reference for reference in references if reference not in identifiers})
    if missing:
        raise IconFontError(
            "SVG_REFERENCE_NOT_FOUND",
            f"Local reference target(s) do not exist: {', '.join(repr(item) for item in missing)}.",
            source=source_id,
        )


def _require_reference_target(
    by_id: dict[str, Any],
    identifier: str,
    allowed: frozenset[str],
    label: str,
    source_id: str,
) -> None:
    target = by_id.get(identifier)
    if target is None:
        raise IconFontError(
            "SVG_REFERENCE_NOT_FOUND",
            f"Local reference target {identifier!r} does not exist.",
            source=source_id,
        )
    target_tag = strip_ns(target.tag)
    if target_tag not in allowed:
        raise IconFontError(
            "SVG_REFERENCE_TARGET_INVALID",
            f"{label} cannot reference <{target_tag}> target {identifier!r}.",
            source=source_id,
            details={
                "reference": identifier,
                "targetTag": target_tag,
                "allowedTargetTags": sorted(allowed),
            },
        )


def _hard_validate_reference_property(
    name: str,
    value: str,
    by_id: dict[str, Any],
    source_id: str,
) -> None:
    normalized = value.strip().casefold()
    inert = {"none", "inherit", "initial", "unset"}
    lowered = name.casefold()
    identifier: str | None = None
    allowed: frozenset[str] | None = None
    if lowered == "clip-path" and normalized not in inert:
        identifier = _single_local_url(
            value, source_id, "SVG_CLIP_REFERENCE_INVALID", "Clip reference"
        )
        allowed = frozenset({"clipPath"})
    elif lowered in {"marker-end", "marker-mid", "marker-start"} and normalized not in inert:
        identifier = _single_local_url(
            value, source_id, "SVG_MARKER_REFERENCE_INVALID", "Marker reference"
        )
        allowed = frozenset({"marker"})
    elif lowered in {"fill", "stroke"} and value.lstrip().casefold().startswith("url("):
        _paint_server_reference(value, source_id)
    if identifier is not None and allowed is not None:
        _require_reference_target(by_id, identifier, allowed, lowered, source_id)
    if lowered in {"filter", "mask"} and normalized not in inert:
        for reference in _url_references(value, source_id):
            if reference.target.startswith("#"):
                _require_reference_target(
                    by_id,
                    reference.target[1:],
                    frozenset({lowered}),
                    lowered,
                    source_id,
                )


def _validate_reference_target_types(root: Any, source_id: str) -> None:
    by_id = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }

    def require(identifier: str, allowed: frozenset[str], label: str) -> None:
        _require_reference_target(by_id, identifier, allowed, label, source_id)

    use_targets = frozenset(
        {
            "circle",
            "ellipse",
            "g",
            "line",
            "path",
            "polygon",
            "polyline",
            "rect",
            "svg",
            "symbol",
            "text",
            "use",
        }
    )
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        tag = strip_ns(element.tag)
        for raw_name, value in element.attrib.items():
            name = strip_ns(raw_name).casefold()
            if name in {
                "clip-path",
                "fill",
                "filter",
                "marker-end",
                "marker-mid",
                "marker-start",
                "mask",
                "stroke",
            }:
                _hard_validate_reference_property(name, value, by_id, source_id)
                continue
            if name == "href" and value.startswith("#"):
                identifier = value[1:]
                if tag == "use":
                    require(identifier, use_targets, "use")
                elif tag in {"linearGradient", "radialGradient"}:
                    require(
                        identifier,
                        frozenset({"linearGradient", "radialGradient"}),
                        f"{tag} template",
                    )
                elif tag == "pattern":
                    require(identifier, frozenset({"pattern"}), "pattern template")
                elif tag == "filter":
                    require(identifier, frozenset({"filter"}), "filter template")
                elif tag == "a":
                    continue
                else:
                    raise IconFontError(
                        "SVG_REFERENCE_OWNER_INVALID",
                        f"<{tag}> cannot carry an href rendering reference.",
                        source=source_id,
                    )


def _validate_paint_server_cycles(root: Any, source_id: str) -> None:
    servers = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        and strip_ns(element.tag) in {"filter", "linearGradient", "pattern", "radialGradient"}
        if (identifier := element.get("id")) is not None
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def dependencies(identifier: str) -> set[str]:
        element = servers[identifier]
        result: set[str] = set()
        href = element.get("href")
        if href is None:
            href = element.get(f"{{{xlinkns()}}}href")
        if href is not None and href.startswith("#") and href[1:] in servers:
            result.add(href[1:])
        for descendant in element.iter():
            if not isinstance(descendant.tag, str):
                continue
            for value in descendant.attrib.values():
                for reference in _url_references(value, source_id):
                    if reference.target.startswith("#") and reference.target[1:] in servers:
                        result.add(reference.target[1:])
        return result

    for start in servers:
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            identifier, exiting = stack.pop()
            if exiting:
                visiting.discard(identifier)
                visited.add(identifier)
                continue
            if identifier in visited:
                continue
            if identifier in visiting:
                cycle_tag = strip_ns(servers[identifier].tag)
                raise IconFontError(
                    (
                        "SVG_FILTER_REFERENCE_CYCLE"
                        if cycle_tag == "filter"
                        else "SVG_PAINT_SERVER_CYCLE"
                    ),
                    "Resource templates form a cycle.",
                    source=source_id,
                )
            visiting.add(identifier)
            stack.append((identifier, True))
            for dependency in sorted(dependencies(identifier), reverse=True):
                if dependency in visiting:
                    cycle_tag = strip_ns(servers[dependency].tag)
                    raise IconFontError(
                        (
                            "SVG_FILTER_REFERENCE_CYCLE"
                            if cycle_tag == "filter"
                            else "SVG_PAINT_SERVER_CYCLE"
                        ),
                        "Resource templates form a cycle.",
                        source=source_id,
                    )
                if dependency not in visited:
                    stack.append((dependency, False))


def _drop_paint_servers(root: Any) -> None:
    for element in tuple(root.iter()):
        if not isinstance(element.tag, str) or strip_ns(element.tag) not in _PAINT_SERVER_ELEMENTS:
            continue
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def _enforce_tree_limits(root: Any, source: SvgSource, config: BuildConfig) -> None:
    for element_count, element in enumerate(root.iter(), start=1):
        if element_count > config.max_elements:
            raise IconFontError(
                "SVG_TOO_MANY_ELEMENTS",
                f"The SVG exceeds the {config.max_elements}-element limit.",
                source=source.source_id,
            )
        depth = 0
        parent = element.getparent()
        while parent is not None:
            depth += 1
            if depth > 128:
                raise IconFontError(
                    "SVG_TOO_DEEP",
                    "The SVG exceeds the 128-element nesting limit.",
                    source=source.source_id,
                )
            parent = parent.getparent()


def _enforce_raw_geometry_budget(root: Any, source_id: str, config: BuildConfig) -> None:
    # Canonical commands are the public limit. A conservative lexical ceiling
    # prevents a hostile path from doing unbounded parser work before that final
    # command count exists.
    limit = config.max_path_commands * 16
    work = 0
    geometry_tags = {
        "circle",
        "ellipse",
        "line",
        "path",
        "polygon",
        "polyline",
        "rect",
        "text",
    }
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if strip_ns(element.tag) in geometry_tags:
            work += 1
        for raw_name, value in element.attrib.items():
            lowered = strip_ns(raw_name).lower()
            if lowered == "d":
                work += sum(1 for _ in _PATH_COMMAND_TOKEN.finditer(value))
                work += sum(1 for _ in _NUMBER_TOKEN.finditer(value))
            elif lowered == "points":
                work += sum(1 for _ in _NUMBER_TOKEN.finditer(value))
            if work > limit:
                raise IconFontError(
                    "SVG_RAW_PATH_LIMIT",
                    "Raw path tokens exceed the pre-canonicalization work limit.",
                    source=source_id,
                    details={"rawPathTokens": work, "maxRawPathTokens": limit},
                    hint="Simplify or split the source path before conversion.",
                )


def _hard_validate_length_syntax(
    value: str,
    *,
    label: str,
    source_id: str,
    nonnegative: bool,
    invalid_code: str = "SVG_LENGTH_INVALID",
    allow_css_wide: bool = False,
) -> None:
    text = value.strip()
    if allow_css_wide and text.casefold() in {"inherit", "initial", "unset"}:
        return
    match = _CSS_DIMENSION_TOKEN.fullmatch(text)
    if match is None:
        if text.casefold().startswith(("calc(", "clamp(", "max(", "min(", "var(")):
            if _valid_bounded_css_length_function(text):
                return
            raise IconFontError(
                invalid_code,
                f"{label}={value!r} contains a malformed CSS function.",
                source=source_id,
            )
        raise IconFontError(
            invalid_code,
            f"{label}={value!r} is not a valid CSS length.",
            source=source_id,
        )
    unit = (match.group(2) or "").casefold()
    if unit not in _ABSOLUTE_LENGTH_SCALE and unit != "%" and unit not in _RELATIVE_LENGTH_UNITS:
        raise IconFontError(
            invalid_code,
            f"{label}={value!r} uses an unknown CSS length unit.",
            source=source_id,
        )
    number = float(match.group(1))
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise IconFontError(
            invalid_code,
            f"{label} must be finite{' and nonnegative' if nonnegative else ''}.",
            source=source_id,
        )


def _valid_bounded_css_length_function(value: str) -> bool:
    match = re.fullmatch(r"(?is)(calc|min|max|clamp|var)\((.*)\)", value)
    if match is None:
        return False
    name, body = match.group(1).casefold(), match.group(2).strip()
    if not body:
        return False
    depth = 0
    quote: str | None = None
    escaped = False
    for character in body:
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return False
    if escaped or quote is not None or depth != 0:
        return False

    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(body):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(body[start:index].strip())
            start = index + 1
    parts.append(body[start:].strip())
    if not all(parts):
        return False
    if name == "var":
        return len(parts) <= 2 and re.fullmatch(r"--[A-Za-z_][\w-]*", parts[0]) is not None
    if name == "clamp" and len(parts) != 3:
        return False
    if name in {"min", "max"} and not parts:
        return False
    if name == "calc" and len(parts) != 1:
        return False
    return not re.search(r"(?:^|[+*/-])\s*$", body)


def _hard_validate_geometry(element: Any, source_id: str) -> None:
    tag = strip_ns(element.tag)
    if tag == "path":
        try:
            commands = tuple(SVGPath(d=element.get("d", "")).as_cmd_seq())
        except Exception as error:
            raise IconFontError(
                "SVG_PATH_INVALID",
                str(error),
                source=source_id,
            ) from error
        if any(not math.isfinite(value) for _command, arguments in commands for value in arguments):
            raise IconFontError(
                "SVG_PATH_INVALID",
                "Path data must contain only finite numbers.",
                source=source_id,
            )
        return
    if tag in {"polygon", "polyline"}:
        points = element.get("points", "").strip()
        number = _NUMBER_TOKEN.pattern
        if points and re.fullmatch(rf"{number}(?:(?:\s*,\s*|\s+){number})*", points) is None:
            raise IconFontError(
                "SVG_POINTS_INVALID",
                f"<{tag}> points are malformed.",
                source=source_id,
            )
        values = tuple(float(token) for token in _NUMBER_TOKEN.findall(points))
        if len(values) % 2 or any(not math.isfinite(value) for value in values):
            raise IconFontError(
                "SVG_POINTS_INVALID",
                f"<{tag}> points must contain finite coordinate pairs.",
                source=source_id,
            )
        return
    for name in _GEOMETRY_LENGTH_ATTRIBUTES.get(tag, ()):
        if name not in element.attrib:
            continue
        _hard_validate_length_syntax(
            element.attrib[name],
            label=f"<{tag}> {name}",
            source_id=source_id,
            nonnegative=(tag, name) in _NONNEGATIVE_GEOMETRY_LENGTHS,
        )


def _hard_validate_view_box(value: str, source_id: str) -> None:
    number = _NUMBER_TOKEN.pattern
    match = re.fullmatch(
        rf"\s*({number})(?:\s*,\s*|\s+)({number})"
        rf"(?:\s*,\s*|\s+)({number})(?:\s*,\s*|\s+)({number})\s*",
        value,
    )
    if match is None:
        raise IconFontError(
            "SVG_VIEWBOX_INVALID",
            "viewBox must contain four finite numbers.",
            source=source_id,
        )
    numbers = tuple(float(part) for part in match.groups())
    if not all(math.isfinite(number) for number in numbers) or numbers[2] < 0 or numbers[3] < 0:
        raise IconFontError(
            "SVG_VIEWBOX_INVALID",
            "viewBox dimensions must be finite and nonnegative.",
            source=source_id,
        )


def _normalize_view_boxes(root: Any) -> None:
    """Canonicalize separators only after every authored viewBox is validated."""

    for element in root.iter():
        if not isinstance(element.tag, str) or strip_ns(element.tag) not in {
            "marker",
            "pattern",
            "svg",
            "symbol",
        }:
            continue
        value = element.get("viewBox")
        if value is None:
            continue
        parts = tuple(part for part in re.split(r"[\s,]+", value.strip()) if part)
        element.set("viewBox", " ".join(parts))


def _hard_validate_dash_syntax(value: str, source_id: str, *, allow_css_wide: bool = False) -> None:
    text = value.strip()
    if text.casefold() == "none" or (
        allow_css_wide and text.casefold() in {"inherit", "initial", "unset"}
    ):
        return
    token = _CSS_DIMENSION_TOKEN.pattern
    if re.fullmatch(rf"\s*{token}(?:(?:\s*,\s*|\s+){token})*\s*", text) is None:
        if text.casefold().startswith(("calc(", "clamp(", "max(", "min(", "var(")):
            return
        raise IconFontError(
            "SVG_DASH_INVALID",
            f"stroke-dasharray={value!r} is malformed.",
            source=source_id,
        )
    for match in _CSS_DIMENSION_TOKEN.finditer(text):
        _hard_validate_length_syntax(
            match.group(0),
            label="stroke-dasharray component",
            source_id=source_id,
            nonnegative=True,
        )


def _hard_validate_length_list(
    value: str,
    *,
    label: str,
    source_id: str,
    nonnegative: bool,
) -> None:
    token = _CSS_DIMENSION_TOKEN.pattern
    if re.fullmatch(rf"\s*{token}(?:(?:\s*,\s*|\s+){token})*\s*", value) is None:
        raise IconFontError(
            "SVG_TEXT_POSITIONING_INVALID",
            f"{label}={value!r} is not a valid length list.",
            source=source_id,
        )
    for match in _CSS_DIMENSION_TOKEN.finditer(value):
        _hard_validate_length_syntax(
            match.group(0),
            label=label,
            source_id=source_id,
            nonnegative=nonnegative,
        )


def _transform_arguments(body: str, source_id: str) -> tuple[str, ...]:
    stripped = body.strip()
    if not stripped or stripped.startswith(",") or stripped.endswith(",") or ",," in stripped:
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            f"Transform argument list {body!r} is malformed.",
            source=source_id,
        )
    arguments: list[str] = []
    current: list[str] = []
    depth = 0
    for character in stripped:
        if character == "(":
            depth += 1
            current.append(character)
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise IconFontError(
                    "SVG_TRANSFORM_INVALID",
                    f"Transform argument list {body!r} is malformed.",
                    source=source_id,
                )
            current.append(character)
        elif depth == 0 and (character == "," or character.isspace()):
            if current:
                arguments.append("".join(current))
                current = []
        else:
            current.append(character)
    if depth != 0:
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            f"Transform argument list {body!r} is malformed.",
            source=source_id,
        )
    if current:
        arguments.append("".join(current))
    if not arguments:
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            f"Transform argument list {body!r} is malformed.",
            source=source_id,
        )
    return tuple(arguments)


def _transform_number(value: str, source_id: str) -> float:
    if _NUMBER_TOKEN.fullmatch(value) is None:
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            f"Transform component {value!r} must be a finite number.",
            source=source_id,
        )
    number = float(value)
    if not math.isfinite(number):
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            "Transform components must be finite.",
            source=source_id,
        )
    return number


def _constant_calc_length(value: str) -> float | None:
    lowered = value.strip().casefold()
    if not lowered.startswith("calc(") or not lowered.endswith(")"):
        return None
    body = lowered[5:-1].strip()
    if not body or body[-1] in "+-*/":
        return None
    cursor = 0
    total = 0.0
    first = True
    while cursor < len(body):
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        sign = 1.0
        if cursor < len(body) and body[cursor] in "+-":
            sign = -1.0 if body[cursor] == "-" else 1.0
            cursor += 1
        elif not first:
            return None
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        match = _CSS_LENGTH_TOKEN.match(body, cursor)
        if match is None:
            return None
        unit = (match.group(2) or "").casefold()
        if unit == "%" or unit not in _ABSOLUTE_LENGTH_SCALE:
            return None
        total += sign * float(match.group(1)) * _ABSOLUTE_LENGTH_SCALE[unit]
        cursor = match.end()
        first = False
    return total if math.isfinite(total) else None


def _transform_length(
    value: str,
    source_id: str,
    *,
    percentage_basis: float | None,
    validate_only: bool,
) -> float:
    match = _CSS_DIMENSION_TOKEN.fullmatch(value)
    if match is not None:
        unit = (match.group(2) or "").casefold()
        number = float(match.group(1))
        if unit == "%":
            if percentage_basis is None:
                if validate_only:
                    return 0.0
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "transform-reference-box",
                    "SVG_TRANSFORM_ENVIRONMENT_UNREPRESENTABLE",
                    f"Transform percentage {value!r} has no bounded viewport reference box.",
                    source=source_id,
                )
            return number * percentage_basis / 100
        if unit in _ABSOLUTE_LENGTH_SCALE:
            number *= _ABSOLUTE_LENGTH_SCALE[unit]
        elif unit in _RELATIVE_LENGTH_UNITS:
            if validate_only:
                return 0.0
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "transform-length-environment",
                "SVG_TRANSFORM_ENVIRONMENT_UNREPRESENTABLE",
                f"Transform length {value!r} depends on a wider CSS environment.",
                source=source_id,
            )
        else:
            raise IconFontError(
                "SVG_TRANSFORM_INVALID",
                f"Transform length {value!r} uses an unknown unit.",
                source=source_id,
            )
    elif (constant := _constant_calc_length(value)) is not None:
        number = constant
    elif value.strip().casefold().startswith(("calc(", "env(", "var(")) and value.strip().endswith(
        ")"
    ):
        if validate_only:
            return 0.0
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "transform-length-environment",
            "SVG_TRANSFORM_ENVIRONMENT_UNREPRESENTABLE",
            f"Transform length {value!r} requires a wider CSS math environment.",
            source=source_id,
        )
    else:
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            f"Transform length {value!r} is malformed.",
            source=source_id,
        )
    if not math.isfinite(number):
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            "Transform lengths must be finite.",
            source=source_id,
        )
    return number


def _transform_angle(value: str, source_id: str) -> float:
    match = re.fullmatch(rf"({_NUMBER_TOKEN.pattern})(deg|grad|rad|turn)?", value.casefold())
    if match is None:
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            f"Transform angle {value!r} is invalid.",
            source=source_id,
        )
    angle = float(match.group(1))
    angle *= {
        "deg": 1.0,
        "grad": 0.9,
        "rad": 180.0 / math.pi,
        "turn": 360.0,
    }[match.group(2) or "deg"]
    if not math.isfinite(angle):
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            "Transform angles must be finite.",
            source=source_id,
        )
    return angle


def _canonical_transform(
    value: str,
    source_id: str,
    *,
    percentage_basis: tuple[float, float] | None = None,
    validate_only: bool = False,
) -> str:
    normalized = value.strip().casefold()
    if normalized in {"initial", "none", "unset"}:
        return ""
    if normalized == "inherit":
        return "inherit"
    cursor = 0
    functions: list[str] = []
    while cursor < len(value):
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor < len(value) and value[cursor] == ",":
            if not functions:
                raise IconFontError(
                    "SVG_TRANSFORM_INVALID",
                    "A transform list cannot start with a comma.",
                    source=source_id,
                )
            cursor += 1
            while cursor < len(value) and value[cursor].isspace():
                cursor += 1
        if cursor >= len(value):
            raise IconFontError(
                "SVG_TRANSFORM_INVALID",
                "A transform list cannot end with a separator.",
                source=source_id,
            )
        function = re.match(r"([A-Za-z][A-Za-z0-9-]*)\s*\(", value[cursor:])
        if function is None:
            raise IconFontError(
                "SVG_TRANSFORM_INVALID",
                f"Unexpected transform syntax near {value[cursor:]!r}.",
                source=source_id,
            )
        name = function.group(1).casefold()
        body_start = cursor + function.end()
        depth = 1
        body_end = body_start
        while body_end < len(value) and depth:
            if value[body_end] == "(":
                depth += 1
            elif value[body_end] == ")":
                depth -= 1
            body_end += 1
        if depth != 0:
            raise IconFontError(
                "SVG_TRANSFORM_INVALID",
                f"Transform function {name!r} is not properly closed.",
                source=source_id,
            )
        body_end -= 1
        arguments = _transform_arguments(value[body_start:body_end], source_id)
        if name == "matrix" and len(arguments) == 6:
            numbers = tuple(_transform_number(argument, source_id) for argument in arguments)
            functions.append("matrix(" + " ".join(f"{number:.17g}" for number in numbers) + ")")
        elif name in {"translate", "translatex", "translatey"}:
            expected = {"translate": {1, 2}, "translatex": {1}, "translatey": {1}}[name]
            if len(arguments) not in expected:
                raise IconFontError(
                    "SVG_TRANSFORM_INVALID",
                    f"{name}() has the wrong number of arguments.",
                    source=source_id,
                )
            axes = (
                (0,)
                if name == "translatex"
                else (1,)
                if name == "translatey"
                else tuple(range(len(arguments)))
            )
            lengths = tuple(
                _transform_length(
                    argument,
                    source_id,
                    percentage_basis=(percentage_basis or (None, None))[axis],
                    validate_only=validate_only,
                )
                for argument, axis in zip(arguments, axes, strict=True)
            )
            if name == "translatex":
                lengths = (lengths[0], 0.0)
            elif name == "translatey":
                lengths = (0.0, lengths[0])
            functions.append("translate(" + " ".join(f"{item:.17g}" for item in lengths) + ")")
        elif name in {"scale", "scalex", "scaley"}:
            expected = {"scale": {1, 2}, "scalex": {1}, "scaley": {1}}[name]
            if len(arguments) not in expected:
                raise IconFontError(
                    "SVG_TRANSFORM_INVALID",
                    f"{name}() has the wrong number of arguments.",
                    source=source_id,
                )
            numbers = tuple(_transform_number(argument, source_id) for argument in arguments)
            if name == "scalex":
                numbers = (numbers[0], 1.0)
            elif name == "scaley":
                numbers = (1.0, numbers[0])
            functions.append("scale(" + " ".join(f"{item:.17g}" for item in numbers) + ")")
        elif name in {"rotate", "rotatez"} and len(arguments) in (
            {1, 3} if name == "rotate" else {1}
        ):
            angle = _transform_angle(arguments[0], source_id)
            centers = tuple(
                _transform_length(
                    argument,
                    source_id,
                    percentage_basis=(percentage_basis or (None, None))[axis],
                    validate_only=validate_only,
                )
                for argument, axis in zip(arguments[1:], (0, 1)[: len(arguments) - 1], strict=True)
            )
            functions.append(
                "rotate(" + " ".join(f"{item:.17g}" for item in (angle, *centers)) + ")"
            )
        elif name in {"skewx", "skewy"} and len(arguments) == 1:
            angle = _transform_angle(arguments[0], source_id)
            functions.append(f"{name}({angle:.17g})")
        else:
            raise IconFontError(
                "SVG_TRANSFORM_INVALID",
                f"Unsupported or malformed 2D transform function {name!r}.",
                source=source_id,
            )
        cursor = body_end + 1
    canonical = " ".join(functions)
    try:
        transform = Affine2D.fromstring(canonical)
    except (ValueError, TypeError) as error:
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            str(error),
            source=source_id,
        ) from error
    if not all(math.isfinite(component) for component in transform):
        raise IconFontError(
            "SVG_TRANSFORM_INVALID",
            "Transform matrices must contain only finite numbers.",
            source=source_id,
        )
    return canonical


def _hard_validate_transform(value: str, source_id: str) -> None:
    _canonical_transform(value, source_id, validate_only=True)


def _normalize_transforms(root: Any, source_id: str) -> None:
    root_view_box = root.get("viewBox")
    if root_view_box is not None:
        root_parts = tuple(
            float(part) for part in re.split(r"[\s,]+", root_view_box.strip()) if part
        )
        root_viewport: tuple[float, float] | None = (root_parts[2], root_parts[3])
    else:
        width = _CSS_LENGTH_TOKEN.fullmatch(root.get("width", ""))
        height = _CSS_LENGTH_TOKEN.fullmatch(root.get("height", ""))
        root_viewport = (
            (
                float(width.group(1)) * _ABSOLUTE_LENGTH_SCALE[(width.group(2) or "").casefold()],
                float(height.group(1)) * _ABSOLUTE_LENGTH_SCALE[(height.group(2) or "").casefold()],
            )
            if width is not None
            and height is not None
            and width.group(2) != "%"
            and height.group(2) != "%"
            else None
        )

    def visit(
        element: Any,
        inherited: str,
        viewport: tuple[float, float] | None,
    ) -> None:
        tag = strip_ns(element.tag)
        current_viewport = viewport
        if tag in {"marker", "symbol"} and element.get("viewBox") is not None:
            parts = tuple(
                float(part) for part in re.split(r"[\s,]+", element.get("viewBox").strip()) if part
            )
            current_viewport = parts[2], parts[3]
        elif tag == "clipPath" and element.get("clipPathUnits", "userSpaceOnUse") == (
            "objectBoundingBox"
        ):
            current_viewport = (1.0, 1.0)
        raw = element.get("transform")
        canonical = (
            ""
            if raw is None
            else _canonical_transform(raw, source_id, percentage_basis=current_viewport)
        )
        if canonical == "inherit":
            canonical = inherited
        if canonical:
            element.set("transform", canonical)
        else:
            element.attrib.pop("transform", None)
        for child in element:
            if isinstance(child.tag, str):
                visit(child, canonical, current_viewport)

    visit(root, "", root_viewport)


def _hard_validate_presentation_value(name: str, value: str, source_id: str) -> None:
    lowered = name.casefold()
    normalized = value.strip().casefold()
    css_wide = {"inherit", "initial", "unset"}
    if lowered in {"color", "fill", "stroke", "stop-color"}:
        _validate_paint(value, source_id)
        if lowered in {"color", "stop-color"} and normalized == "none":
            raise IconFontError(
                "SVG_PAINT_INVALID",
                f"{name} cannot use the fill/stroke-only 'none' keyword.",
                source=source_id,
            )
    elif lowered in {"fill-opacity", "opacity", "stop-opacity", "stroke-opacity"}:
        _validate_opacity(value, lowered, source_id)
    elif lowered == "transform":
        _hard_validate_transform(value, source_id)
    elif lowered == "stroke-dasharray":
        _hard_validate_dash_syntax(value, source_id, allow_css_wide=True)
    elif lowered in {"font-size", "stroke-dashoffset", "stroke-width"}:
        _hard_validate_length_syntax(
            value,
            label=lowered,
            source_id=source_id,
            nonnegative=lowered != "stroke-dashoffset",
            allow_css_wide=True,
        )
    elif lowered in {"pathlength", "stroke-miterlimit"} and normalized not in css_wide:
        try:
            number = float(value)
        except ValueError as error:
            raise IconFontError(
                "SVG_PRESENTATION_VALUE_INVALID",
                f"{name}={value!r} must be a finite positive number.",
                source=source_id,
            ) from error
        invalid = number < 1 if lowered == "stroke-miterlimit" else number <= 0
        if not math.isfinite(number) or invalid:
            raise IconFontError(
                "SVG_PRESENTATION_VALUE_INVALID",
                (
                    f"{name}={value!r} must be finite and at least 1."
                    if lowered == "stroke-miterlimit"
                    else f"{name}={value!r} must be finite and greater than zero."
                ),
                source=source_id,
            )
    elif lowered in {"clip-rule", "fill-rule"} and normalized not in css_wide | {
        "evenodd",
        "nonzero",
    }:
        raise IconFontError(
            "SVG_FILL_RULE_INVALID",
            f"{name}={value!r} is invalid.",
            source=source_id,
        )
    else:
        enums = {
            "direction": {"ltr", "rtl"},
            "display": {
                "block",
                "contents",
                "flex",
                "flow-root",
                "grid",
                "inline",
                "inline-block",
                "inline-flex",
                "inline-grid",
                "inline-table",
                "list-item",
                "math",
                "none",
                "ruby",
                "ruby-base",
                "ruby-base-container",
                "ruby-text",
                "ruby-text-container",
                "table",
                "table-caption",
                "table-cell",
                "table-column",
                "table-column-group",
                "table-footer-group",
                "table-header-group",
                "table-row",
                "table-row-group",
            },
            "isolation": {"auto", "isolate"},
            "mix-blend-mode": {
                "color",
                "color-burn",
                "color-dodge",
                "darken",
                "difference",
                "exclusion",
                "hard-light",
                "hue",
                "lighten",
                "luminosity",
                "multiply",
                "normal",
                "overlay",
                "saturation",
                "screen",
                "soft-light",
            },
            "overflow": {"auto", "clip", "hidden", "scroll", "visible"},
            "stroke-linecap": {"butt", "round", "square"},
            "stroke-linejoin": {"arcs", "bevel", "miter", "miter-clip", "round"},
            "text-anchor": {"end", "middle", "start"},
            "vector-effect": {
                "fixed-position",
                "non-rotation",
                "non-scaling-size",
                "non-scaling-stroke",
                "none",
            },
            "visibility": {"collapse", "hidden", "visible"},
            "writing-mode": {
                "horizontal-tb",
                "lr",
                "lr-tb",
                "rl",
                "rl-tb",
                "tb",
                "tb-rl",
                "vertical-lr",
                "vertical-rl",
            },
        }
        allowed = enums.get(lowered)
        if allowed is not None and normalized not in allowed | css_wide:
            raise IconFontError(
                "SVG_PRESENTATION_VALUE_INVALID",
                f"{name}={value!r} is not a recognized value.",
                source=source_id,
            )
    _reject_external_url(value, source_id)


def _hard_validate_resource_element(element: Any, source_id: str) -> None:
    tag = strip_ns(element.tag)
    common = {"class", "id", "style"} | {name.casefold() for name in _CSS_PROPERTIES}
    allowed_by_tag = {
        "linearGradient": common
        | {
            "gradienttransform",
            "gradientunits",
            "href",
            "spreadmethod",
            "x1",
            "x2",
            "y1",
            "y2",
        },
        "radialGradient": common
        | {
            "cx",
            "cy",
            "fr",
            "fx",
            "fy",
            "gradienttransform",
            "gradientunits",
            "href",
            "r",
            "spreadmethod",
        },
        "pattern": common
        | {
            "height",
            "href",
            "patterncontentunits",
            "patterntransform",
            "patternunits",
            "preserveaspectratio",
            "viewbox",
            "width",
            "x",
            "y",
        },
        "stop": common | {"offset", "stop-color", "stop-opacity"},
        "filter": common
        | {
            "color-interpolation-filters",
            "filterunits",
            "height",
            "href",
            "primitiveunits",
            "width",
            "x",
            "y",
        },
        "mask": common
        | {
            "height",
            "mask-type",
            "maskcontentunits",
            "maskunits",
            "width",
            "x",
            "y",
        },
    }
    allowed = allowed_by_tag.get(tag)
    if allowed is None:
        return
    for raw_name, value in element.attrib.items():
        name = strip_ns(raw_name)
        lowered = name.casefold()
        namespace = _attribute_namespace(raw_name)
        if (
            lowered.startswith(("aria-", "data-"))
            or namespace == "http://www.w3.org/XML/1998/namespace"
        ):
            continue
        if lowered not in allowed:
            raise IconFontError(
                "SVG_ATTRIBUTE_UNSUPPORTED",
                f"Attribute {name!r} has unknown <{tag}> rendering semantics.",
                source=source_id,
            )
        if lowered in {
            "cx",
            "cy",
            "fr",
            "fx",
            "fy",
            "height",
            "r",
            "width",
            "x",
            "x1",
            "x2",
            "y",
            "y1",
            "y2",
        }:
            _hard_validate_length_syntax(
                value,
                label=f"<{tag}> {name}",
                source_id=source_id,
                nonnegative=lowered in {"fr", "height", "r", "width"},
            )
        elif lowered in {"gradienttransform", "patterntransform"}:
            _hard_validate_transform(value, source_id)
        elif lowered == "viewbox":
            _hard_validate_view_box(value, source_id)
        elif lowered == "preserveaspectratio":
            try:
                Affine2D.rect_to_rect(Rect(0, 0, 1, 1), Rect(0, 0, 1, 1), value)
            except (ValueError, TypeError) as error:
                raise IconFontError(
                    "SVG_ASPECT_RATIO_INVALID",
                    str(error),
                    source=source_id,
                ) from error
        elif lowered in {
            "filterunits",
            "gradientunits",
            "maskcontentunits",
            "maskunits",
            "patterncontentunits",
            "patternunits",
            "primitiveunits",
        } and value not in {
            "objectBoundingBox",
            "userSpaceOnUse",
        }:
            raise IconFontError(
                "SVG_RESOURCE_UNITS_INVALID",
                f"{name}={value!r} is invalid.",
                source=source_id,
            )
        elif lowered == "spreadmethod" and value not in {"pad", "reflect", "repeat"}:
            raise IconFontError(
                "SVG_GRADIENT_SPREAD_INVALID",
                f"spreadMethod={value!r} is invalid.",
                source=source_id,
            )
        elif lowered == "offset":
            number = (
                _percentage_component(value)
                if value.strip().endswith("%")
                else _numeric_component(value)
            )
            if number is None:
                raise IconFontError(
                    "SVG_GRADIENT_OFFSET_INVALID",
                    f"Gradient stop offset={value!r} must be a finite number or percentage.",
                    source=source_id,
                )
        elif lowered == "mask-type" and value not in {"alpha", "luminance"}:
            raise IconFontError(
                "SVG_MASK_TYPE_INVALID",
                f"mask-type={value!r} is invalid.",
                source=source_id,
            )


def _enforce_expansion_budget(root: Any, source_id: str, config: BuildConfig) -> None:
    by_id = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }
    memo: dict[Any, tuple[int, int]] = {}
    # PicoSVG resolves every use node, including ones under definitions that
    # never paint. They still belong in the hostile-work budget.
    nonrendering_children = {"desc", "title"}

    def bounded_add(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
        return (
            min(config.max_expanded_elements + 1, left[0] + right[0]),
            min(config.max_expanded_bytes + 1, left[1] + right[1]),
        )

    def own_cost(element: Any) -> tuple[int, int]:
        encoded_bytes = len(str(element.tag).encode("utf-8"))
        encoded_bytes += sum(
            len(str(name).encode("utf-8")) + len(value.encode("utf-8"))
            for name, value in element.attrib.items()
        )
        encoded_bytes += len((element.text or "").encode("utf-8"))
        encoded_bytes += len((element.tail or "").encode("utf-8"))
        return (1, max(1, encoded_bytes))

    def reference_target(element: Any) -> Any | None:
        for raw_name, value in element.attrib.items():
            if strip_ns(raw_name).lower() == "href" and value.startswith("#"):
                return by_id.get(value[1:])
        return None

    def dependencies(element: Any) -> tuple[Any, ...]:
        result: list[Any] = []
        tag = strip_ns(element.tag)
        if tag == "use":
            target = reference_target(element)
            if target is not None:
                result.append(target)
        else:
            for child in element:
                if not isinstance(child.tag, str) or strip_ns(child.tag) in nonrendering_children:
                    continue
                result.append(child)
        for raw_name, value in element.attrib.items():
            if strip_ns(raw_name).lower() not in {
                "clip-path",
                "marker-end",
                "marker-mid",
                "marker-start",
                "style",
            }:
                continue
            for reference in _url_references(value, source_id):
                target = reference.target
                if target.startswith("#") and target[1:] in by_id:
                    result.append(by_id[target[1:]])
        return tuple(result)

    visiting: set[Any] = set()
    stack: list[tuple[Any, bool]] = [(root, False)]
    while stack:
        element, exiting = stack.pop()
        if exiting:
            cost = own_cost(element)
            for dependency in dependencies(element):
                cost = bounded_add(cost, memo[dependency])
            memo[element] = cost
            visiting.remove(element)
            continue
        if element in memo:
            continue
        if element in visiting:
            raise IconFontError(
                "SVG_REFERENCE_CYCLE",
                "Local geometry references form a cycle.",
                source=source_id,
            )
        visiting.add(element)
        stack.append((element, True))
        for dependency in reversed(dependencies(element)):
            if dependency in visiting:
                raise IconFontError(
                    "SVG_REFERENCE_CYCLE",
                    "Local geometry references form a cycle.",
                    source=source_id,
                )
            if dependency not in memo:
                stack.append((dependency, False))

    expanded_elements, expanded_bytes = memo[root]
    if (
        expanded_elements > config.max_expanded_elements
        or expanded_bytes > config.max_expanded_bytes
    ):
        raise IconFontError(
            "SVG_EXPANSION_LIMIT",
            "Local reuse exceeds the configured pre-expansion work budget.",
            source=source_id,
            details={
                "expandedElements": expanded_elements,
                "maxExpandedElements": config.max_expanded_elements,
                "expandedBytes": expanded_bytes,
                "maxExpandedBytes": config.max_expanded_bytes,
            },
            hint="Flatten or simplify nested use, points, path, and transform data.",
        )


def _computed_keyword(value: str | None, inherited: str, initial: str) -> str:
    if value is None:
        return inherited
    lowered = value.strip().casefold()
    if lowered in {"inherit", "unset"}:
        return inherited
    if lowered == "initial":
        return initial
    return value.strip()


def _computed_opacity(
    value: str | None,
    inherited: float,
    initial: float,
    name: str,
    source_id: str,
) -> float:
    if value is None:
        return inherited
    lowered = value.strip().casefold()
    if lowered in {"inherit", "unset"}:
        return inherited
    if lowered == "initial":
        return initial
    return _opacity_value(value, name, source_id)


def _computed_noninherited_keyword(value: str | None, parent: str, initial: str) -> str:
    if value is None:
        return initial
    lowered = value.strip().casefold()
    if lowered == "inherit":
        return parent
    if lowered in {"initial", "unset"}:
        return initial
    return value.strip()


def _computed_noninherited_opacity(
    value: str | None,
    parent: float,
    initial: float,
    name: str,
    source_id: str,
) -> float:
    if value is None:
        return initial
    lowered = value.strip().casefold()
    if lowered == "inherit":
        return parent
    if lowered in {"initial", "unset"}:
        return initial
    return _opacity_value(value, name, source_id)


def _gradient_stops(
    target: Any,
    by_id: dict[str, Any],
    source_id: str,
    stack: frozenset[str] = frozenset(),
) -> tuple[Any, ...]:
    seen = set(stack)
    current = target
    while current is not None:
        identifier = current.get("id", "")
        if identifier and identifier in seen:
            raise IconFontError(
                "SVG_PAINT_SERVER_CYCLE",
                "Paint-server templates form a cycle.",
                source=source_id,
            )
        if identifier:
            seen.add(identifier)
        own = tuple(
            child
            for child in current
            if isinstance(child.tag, str) and strip_ns(child.tag) == "stop"
        )
        if own:
            return own
        href = next(
            (
                value
                for raw_name, value in current.attrib.items()
                if strip_ns(raw_name).lower() == "href"
            ),
            None,
        )
        if not href or not href.startswith("#") or href[1:] not in by_id:
            return ()
        current = by_id[href[1:]]
        if strip_ns(current.tag) not in {"linearGradient", "radialGradient"}:
            raise IconFontError(
                "SVG_REFERENCE_TARGET_INVALID",
                f"Gradient template {href[1:]!r} is not a gradient element.",
                source=source_id,
            )
    return ()


def _gradient_attribute(
    target: Any,
    name: str,
    by_id: dict[str, Any],
    source_id: str,
) -> str | None:
    seen: set[str] = set()
    current = target
    while current is not None:
        value = current.get(name)
        if value is not None:
            return cast(str, value)
        identifier = current.get("id", "")
        if identifier and identifier in seen:
            raise IconFontError(
                "SVG_PAINT_SERVER_CYCLE",
                "Paint-server templates form a cycle.",
                source=source_id,
            )
        if identifier:
            seen.add(identifier)
        href = next(
            (
                candidate
                for raw_name, candidate in current.attrib.items()
                if strip_ns(raw_name).casefold() == "href"
            ),
            None,
        )
        if not href or not href.startswith("#"):
            return None
        current = by_id.get(href[1:])
        if current is None:
            return None
        if strip_ns(current.tag) not in {"linearGradient", "radialGradient"}:
            raise IconFontError(
                "SVG_REFERENCE_TARGET_INVALID",
                f"Gradient template {href[1:]!r} is not a gradient element.",
                source=source_id,
            )
    return None


def _gradient_coordinates_equal(left: str, right: str, units: str) -> bool:
    if left.strip().casefold() == right.strip().casefold():
        return True
    left_match = _CSS_LENGTH_TOKEN.fullmatch(left.strip())
    right_match = _CSS_LENGTH_TOKEN.fullmatch(right.strip())
    if left_match is None or right_match is None:
        return False
    left_number = float(left_match.group(1))
    right_number = float(right_match.group(1))
    left_unit = (left_match.group(2) or "").casefold()
    right_unit = (right_match.group(2) or "").casefold()
    if left_number == 0 and right_number == 0:
        return True
    if units == "objectBoundingBox":
        if left_unit not in {"", "%"} or right_unit not in {"", "%"}:
            return False
        left_value = left_number / 100 if left_unit == "%" else left_number
        right_value = right_number / 100 if right_unit == "%" else right_number
        return left_value == right_value
    if left_unit == right_unit == "%":
        return left_number == right_number
    if left_unit in _ABSOLUTE_LENGTH_SCALE and right_unit in _ABSOLUTE_LENGTH_SCALE:
        return (
            left_number * _ABSOLUTE_LENGTH_SCALE[left_unit]
            == right_number * _ABSOLUTE_LENGTH_SCALE[right_unit]
        )
    return False


def _gradient_coordinate_scalar(value: str, units: str) -> float | None:
    match = _CSS_LENGTH_TOKEN.fullmatch(value.strip())
    if match is None:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "").casefold()
    if units == "objectBoundingBox":
        if unit == "%":
            return number / 100
        return number if unit == "" else None
    if unit == "%" or unit not in _ABSOLUTE_LENGTH_SCALE:
        return None
    return number * _ABSOLUTE_LENGTH_SCALE[unit]


def _radial_gradient_covers_plane(
    target: Any,
    by_id: dict[str, Any],
    source_id: str,
) -> bool:
    units = _gradient_attribute(target, "gradientUnits", by_id, source_id) or "objectBoundingBox"
    cx = _gradient_attribute(target, "cx", by_id, source_id) or "50%"
    cy = _gradient_attribute(target, "cy", by_id, source_id) or "50%"
    radius = _gradient_attribute(target, "r", by_id, source_id) or "50%"
    fx = _gradient_attribute(target, "fx", by_id, source_id) or cx
    fy = _gradient_attribute(target, "fy", by_id, source_id) or cy
    focal_radius = _gradient_attribute(target, "fr", by_id, source_id) or "0%"
    values = tuple(
        _gradient_coordinate_scalar(value, units)
        for value in (cx, cy, radius, fx, fy, focal_radius)
    )
    if any(value is None for value in values):
        return False
    resolved_cx, resolved_cy, resolved_radius, resolved_fx, resolved_fy, resolved_fr = cast(
        tuple[float, float, float, float, float, float], values
    )
    return (
        math.hypot(resolved_fx - resolved_cx, resolved_fy - resolved_cy) + resolved_fr
        <= resolved_radius
    )


def _degenerate_gradient_kind(
    target: Any,
    by_id: dict[str, Any],
    source_id: str,
) -> str | None:
    units = _gradient_attribute(target, "gradientUnits", by_id, source_id) or "objectBoundingBox"
    tag = strip_ns(target.tag)
    if tag == "linearGradient":
        x1 = _gradient_attribute(target, "x1", by_id, source_id) or "0%"
        y1 = _gradient_attribute(target, "y1", by_id, source_id) or "0%"
        x2 = _gradient_attribute(target, "x2", by_id, source_id) or "100%"
        y2 = _gradient_attribute(target, "y2", by_id, source_id) or "0%"
        if _gradient_coordinates_equal(x1, x2, units) and _gradient_coordinates_equal(
            y1, y2, units
        ):
            return "linear-last-stop"
        return None
    cx = _gradient_attribute(target, "cx", by_id, source_id) or "50%"
    cy = _gradient_attribute(target, "cy", by_id, source_id) or "50%"
    radius = _gradient_attribute(target, "r", by_id, source_id) or "50%"
    fx = _gradient_attribute(target, "fx", by_id, source_id) or cx
    fy = _gradient_attribute(target, "fy", by_id, source_id) or cy
    focal_radius = _gradient_attribute(target, "fr", by_id, source_id) or "0%"
    if (
        _gradient_coordinates_equal(fx, cx, units)
        and _gradient_coordinates_equal(fy, cy, units)
        and _gradient_coordinates_equal(focal_radius, radius, units)
    ):
        return "radial-empty"
    return None


def _paint_server_uses_object_bbox(
    target: Any,
    by_id: dict[str, Any],
    source_id: str,
) -> bool:
    tag = strip_ns(target.tag)
    if tag in {"linearGradient", "radialGradient"}:
        return (
            _gradient_attribute(target, "gradientUnits", by_id, source_id) or "objectBoundingBox"
        ) == "objectBoundingBox"
    seen: set[str] = set()
    current = target
    while current is not None:
        units = current.get("patternUnits")
        if units is not None:
            return bool(units == "objectBoundingBox")
        identifier = current.get("id", "")
        if identifier and identifier in seen:
            raise IconFontError(
                "SVG_PAINT_SERVER_CYCLE",
                "Pattern templates form a cycle.",
                source=source_id,
            )
        if identifier:
            seen.add(identifier)
        href = next(
            (
                value
                for raw_name, value in current.attrib.items()
                if strip_ns(raw_name).casefold() == "href"
            ),
            None,
        )
        current = by_id.get(href[1:]) if href and href.startswith("#") else None
    return True


def _stop_alpha(stop: Any, source_id: str, *, host: Any | None = None) -> float:
    color = "black"
    stop_color = "black"
    stop_opacity = 1.0
    # Referenced gradient stops are cloned into a shadow tree hosted by the
    # consuming gradient. Their inherited presentation comes from that host,
    # not from the template element that owns the source stop.
    effective_parent = stop.getparent() if host is None else host
    ancestry = (
        (*reversed(tuple(effective_parent.iterancestors())), effective_parent, stop)
        if effective_parent is not None
        else (stop,)
    )
    for element in ancestry:
        parent_color = color
        parent_stop_color = stop_color
        parent_stop_opacity = stop_opacity
        color = _computed_keyword(element.get("color"), parent_color, "black")
        if color.casefold() == "currentcolor":
            color = parent_color
        stop_color = _computed_noninherited_keyword(
            element.get("stop-color"), parent_stop_color, "black"
        )
        if stop_color.casefold() == "currentcolor":
            stop_color = color
        stop_opacity = _computed_noninherited_opacity(
            element.get("stop-opacity"),
            parent_stop_opacity,
            1.0,
            "stop-opacity",
            source_id,
        )
    alpha_paint = _alpha_paint(stop_color)
    if alpha_paint is not None:
        stop_opacity *= alpha_paint[1]
    return stop_opacity


def _pattern_has_paint(
    pattern: Any,
    by_id: dict[str, Any],
    source_id: str,
    stack: frozenset[str] = frozenset(),
) -> bool:
    def inherited_attribute(node: Any, name: str, seen: frozenset[str]) -> str | None:
        identifiers = set(seen)
        current = node
        while current is not None:
            value = current.get(name)
            if value is not None:
                return cast(str, value)
            node_id = current.get("id", "")
            if node_id and node_id in identifiers:
                raise IconFontError(
                    "SVG_PAINT_SERVER_CYCLE",
                    "Pattern templates form a cycle.",
                    source=source_id,
                )
            if node_id:
                identifiers.add(node_id)
            node_href = next(
                (
                    candidate
                    for raw_name, candidate in current.attrib.items()
                    if strip_ns(raw_name).casefold() == "href"
                ),
                None,
            )
            if not node_href or not node_href.startswith("#"):
                return None
            current = by_id.get(node_href[1:])
            if current is not None and strip_ns(current.tag) != "pattern":
                raise IconFontError(
                    "SVG_REFERENCE_TARGET_INVALID",
                    f"Pattern template {node_href[1:]!r} is not a pattern element.",
                    source=source_id,
                )
        return None

    for name in ("width", "height"):
        value = inherited_attribute(pattern, name, frozenset())
        if value is None:
            return False
        match = _CSS_DIMENSION_TOKEN.fullmatch(value.strip())
        if match is not None and float(match.group(1)) == 0:
            return False

    view_box = inherited_attribute(pattern, "viewBox", frozenset())
    if view_box is not None:
        parts = tuple(part for part in re.split(r"[\s,]+", view_box.strip()) if part)
        if float(parts[2]) == 0 or float(parts[3]) == 0:
            return False

    seen = set(stack)
    current = pattern
    content: tuple[Any, ...] = ()
    while current is not None:
        identifier = current.get("id", "")
        if identifier and identifier in seen:
            raise IconFontError(
                "SVG_PAINT_SERVER_CYCLE",
                "Pattern templates form a cycle.",
                source=source_id,
            )
        if identifier:
            seen.add(identifier)
        content = tuple(
            child
            for child in current
            if isinstance(child.tag, str)
            and strip_ns(child.tag) not in {"desc", "metadata", "title"}
        )
        if content:
            break
        href = next(
            (
                value
                for raw_name, value in current.attrib.items()
                if strip_ns(raw_name).casefold() == "href"
            ),
            None,
        )
        if not href or not href.startswith("#"):
            current = None
            break
        current = by_id.get(href[1:])
        if current is not None and strip_ns(current.tag) != "pattern":
            raise IconFontError(
                "SVG_REFERENCE_TARGET_INVALID",
                f"Pattern template {href[1:]!r} is not a pattern element.",
                source=source_id,
            )
    if content:
        geometry_tags = {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}

        def may_paint(element: Any) -> bool:
            def literal_zero(value: str | None, name: str) -> bool:
                return (
                    value is not None
                    and value.strip().casefold() not in {"inherit", "initial", "unset"}
                    and _opacity_value(value, name, source_id) == 0
                )

            if element.get("display", "inline").strip().casefold() == "none":
                return False
            if element.get("visibility", "visible").strip().casefold() in {
                "collapse",
                "hidden",
            }:
                return False
            raw_opacity = element.get("opacity")
            if literal_zero(raw_opacity, "opacity"):
                return False
            tag = strip_ns(element.tag)
            if tag in geometry_tags:
                fill_value = cast(str, element.get("fill", "black"))
                fill_visible = fill_value.strip().casefold() != "none"
                raw_fill_opacity = element.get("fill-opacity")
                if literal_zero(raw_fill_opacity, "fill-opacity"):
                    fill_visible = False
                stroke_value = cast(str, element.get("stroke", "none"))
                stroke_visible = stroke_value.strip().casefold() != "none"
                raw_stroke_opacity = element.get("stroke-opacity")
                if literal_zero(raw_stroke_opacity, "stroke-opacity"):
                    stroke_visible = False
                raw_stroke_width = element.get("stroke-width")
                if raw_stroke_width is not None:
                    width = _CSS_LENGTH_TOKEN.fullmatch(raw_stroke_width.strip())
                    if width is not None and float(width.group(1)) == 0:
                        stroke_visible = False
                if tag == "rect":
                    for name in ("width", "height"):
                        length = _CSS_LENGTH_TOKEN.fullmatch(element.get(name, "0").strip())
                        if length is not None and float(length.group(1)) == 0:
                            return False
                elif tag == "circle":
                    radius = _CSS_LENGTH_TOKEN.fullmatch(element.get("r", "0").strip())
                    if radius is not None and float(radius.group(1)) == 0:
                        return False
                elif tag == "ellipse":
                    for name in ("rx", "ry"):
                        radius = _CSS_LENGTH_TOKEN.fullmatch(element.get(name, "0").strip())
                        if radius is not None and float(radius.group(1)) == 0:
                            return False
                return fill_visible or stroke_visible
            return any(
                may_paint(child)
                for child in element
                if isinstance(child.tag, str)
                and strip_ns(child.tag) not in {"desc", "metadata", "title"}
            )

        return any(may_paint(child) for child in content)
    return False


def _resolve_paint_server(
    value: str,
    by_id: dict[str, Any],
    context: _ConversionContext,
    *,
    current_color: str,
    object_bbox_degenerate: bool,
) -> _PaintServerResolution:
    reference = _paint_server_reference(value, context.source_id)
    target = by_id.get(reference.identifier)

    def fallback() -> _PaintServerResolution:
        paint = reference.fallback or "none"
        if paint.casefold() == "currentcolor":
            paint = current_color
        if paint.casefold() == "none":
            return _PaintServerResolution("none", 0.0)
        alpha_paint = _alpha_paint(paint)
        if alpha_paint is not None:
            return _PaintServerResolution("#000000", alpha_paint[1])
        _canonical_solid_paint(paint)
        return _PaintServerResolution("#000000", 1.0)

    if target is None:
        return fallback()
    tag = strip_ns(target.tag)
    if tag not in {"linearGradient", "pattern", "radialGradient"}:
        return fallback()
    if object_bbox_degenerate and _paint_server_uses_object_bbox(target, by_id, context.source_id):
        return _PaintServerResolution("none", 0.0)
    if tag in {"linearGradient", "radialGradient"}:
        stops = _gradient_stops(target, by_id, context.source_id)
        if not stops:
            return _PaintServerResolution("none", 0.0)
        alphas = tuple(_stop_alpha(stop, context.source_id, host=target) for stop in stops)
        degenerate = _degenerate_gradient_kind(target, by_id, context.source_id)
        if degenerate == "radial-empty":
            return _PaintServerResolution("none", 0.0)
        if degenerate == "linear-last-stop":
            last_alpha = alphas[-1]
            return _PaintServerResolution(
                "none" if last_alpha == 0 else "#000000",
                last_alpha,
            )
        coverage_bits = (
            _LOSSY_GRADIENT_COVERAGE
            if tag == "radialGradient"
            and not _radial_gradient_covers_plane(target, by_id, context.source_id)
            else 0
        )
        if all(alpha == alphas[0] for alpha in alphas):
            if alphas[0] == 0:
                return _PaintServerResolution("none", 0.0)
            return _PaintServerResolution("#000000", alphas[0], coverage_bits)
        return _PaintServerResolution("#000000", 1.0, _LOSSY_GRADIENT_ALPHA | coverage_bits)
    if tag == "pattern":
        if not _pattern_has_paint(target, by_id, context.source_id):
            return _PaintServerResolution("none", 0.0)
        return _PaintServerResolution("#000000", 1.0, _LOSSY_PATTERN)
    raise IconFontError(
        "SVG_PAINT_SERVER_INVALID",
        f"Paint server {reference.identifier!r} targets unsupported <{tag}> content.",
        source=context.source_id,
    )


def _normalize_presentation(root: Any, context: _ConversionContext) -> None:
    geometry_tags = {
        "circle",
        "ellipse",
        "line",
        "path",
        "polygon",
        "polyline",
        "rect",
        "text",
    }
    # Paint-server classification must not observe mutations from this same
    # traversal. Otherwise a definition before its consumer is normalized first
    # while an identical forward definition is read raw, making valid SVG output
    # depend on source order. Resolve every paint against one immutable snapshot.
    paint_server_root = copy.deepcopy(root)
    by_id = {
        identifier: element
        for element in paint_server_root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }

    def visit(
        element: Any,
        parent_color: str,
        parent_fill: str,
        parent_stroke: str,
        parent_fill_opacity: float,
        parent_stroke_opacity: float,
        parent_opacity: float,
        parent_stop_color: str,
        parent_stop_opacity: float,
    ) -> None:
        color = _computed_keyword(element.get("color"), parent_color, "black")
        if color.casefold() == "currentcolor":
            color = parent_color
        fill = _computed_keyword(element.get("fill"), parent_fill, "black")
        stroke = _computed_keyword(element.get("stroke"), parent_stroke, "none")
        if fill.casefold() == "currentcolor":
            fill = color
        if stroke.casefold() == "currentcolor":
            stroke = color
        fill_opacity = _computed_opacity(
            element.get("fill-opacity"),
            parent_fill_opacity,
            1.0,
            "fill-opacity",
            context.source_id,
        )
        stroke_opacity = _computed_opacity(
            element.get("stroke-opacity"),
            parent_stroke_opacity,
            1.0,
            "stroke-opacity",
            context.source_id,
        )
        raw_opacity = element.get("opacity")
        if raw_opacity is None or raw_opacity.strip().casefold() in {"initial", "unset"}:
            opacity = 1.0
        elif raw_opacity.strip().casefold() == "inherit":
            opacity = parent_opacity
        else:
            opacity = _opacity_value(raw_opacity, "opacity", context.source_id)

        stop_color = _computed_noninherited_keyword(
            element.get("stop-color"), parent_stop_color, "black"
        )
        if stop_color.casefold() == "currentcolor":
            stop_color = color
        stop_opacity = _computed_noninherited_opacity(
            element.get("stop-opacity"),
            parent_stop_opacity,
            1.0,
            "stop-opacity",
            context.source_id,
        )

        tag = strip_ns(element.tag)
        if tag == "stop":
            alpha_paint = _alpha_paint(stop_color)
            if alpha_paint is not None:
                stop_color, color_alpha = alpha_paint
                stop_opacity *= color_alpha
            else:
                _canonical_solid_paint(stop_color)
            element.set("stop-color", "#000000")
            element.set("stop-opacity", f"{stop_opacity:.17g}")
        if tag in geometry_tags:
            marked = any(
                element.get(name, "none").strip().casefold() != "none"
                for name in ("marker-start", "marker-mid", "marker-end")
            )
            geometry_opacity = 1.0 if marked else opacity
            if (
                context.partial_alpha is not None
                and geometry_opacity != 1
                and fill.strip().casefold() != "none"
                and stroke.strip().casefold() != "none"
            ):
                context.unrepresentable(
                    "layered-alpha-compositing",
                    "SVG_LAYERED_ALPHA_COMPOSITING_UNREPRESENTABLE",
                    "Layered alpha cannot preserve element opacity applied after overlapping "
                    "fill and stroke paint.",
                    hint=(
                        "Expand the fill and stroke into one composited outline, or use separate "
                        "paint opacity values instead of element opacity."
                    ),
                )
            if marked and opacity != 1:
                element.set(_MARKER_TARGET_OPACITY, f"{opacity:.17g}")
            has_paint_server = any(
                paint.lstrip().casefold().startswith("url(") for paint in (fill, stroke)
            )
            object_bbox_degenerate = False
            if has_paint_server and tag != "text":
                geometry_box = cast(SVGPath, from_element(element).as_path()).bounding_box()
                object_bbox_degenerate = geometry_box.w == 0 or geometry_box.h == 0
            normalized_paints: list[tuple[str, str, float]] = []
            for name, paint, paint_opacity in (
                ("fill", fill, fill_opacity),
                ("stroke", stroke, stroke_opacity),
            ):
                if paint.casefold() in {"context-fill", "context-stroke"} and not _has_ancestor(
                    element, "marker"
                ):
                    context.unrepresentable(
                        "context-paint-environment",
                        "SVG_CONTEXT_PAINT_UNREPRESENTABLE",
                        f"{name}={paint!r} has no resolved marker context.",
                        hint="Resolve context paint to an explicit fill or stroke.",
                    )
                lossy_bits = 0
                if paint.lstrip().casefold().startswith("url("):
                    resolution = _resolve_paint_server(
                        paint,
                        by_id,
                        context,
                        current_color=color,
                        object_bbox_degenerate=object_bbox_degenerate,
                    )
                    paint = resolution.paint
                    paint_opacity *= resolution.alpha
                    lossy_bits = resolution.lossy_provenance
                else:
                    alpha_paint = _alpha_paint(paint)
                    if alpha_paint is not None:
                        paint, alpha = alpha_paint
                        paint_opacity *= alpha
                combined_alpha = paint_opacity * geometry_opacity
                if paint.casefold() == "none" or combined_alpha == 0:
                    paint = "none"
                    paint_opacity = 1.0
                else:
                    if combined_alpha != 1:
                        lossy_bits |= _LOSSY_FRACTIONAL_ALPHA
                    if lossy_bits:
                        paint = (
                            context.layered_paint(lossy_bits, combined_alpha)
                            if context.partial_alpha is not None
                            and lossy_bits == _LOSSY_FRACTIONAL_ALPHA
                            else _lossy_paint(lossy_bits)
                        )
                    elif paint.casefold() not in {"context-fill", "context-stroke"}:
                        # RGB is outside the icon-font fidelity target. Canonicalize
                        # ordinary opaque paints to black and reserve low colors for
                        # non-quantized lossy provenance.
                        paint = "#000000"
                    paint_opacity = 1.0
                normalized_paints.append((name, paint, paint_opacity))
            for name, paint, paint_opacity in normalized_paints:
                element.set(name, paint)
                element.set(f"{name}-opacity", f"{paint_opacity:.12g}")
            element.set("opacity", "1")

        for child in element:
            if isinstance(child.tag, str):
                visit(
                    child,
                    color,
                    fill,
                    stroke,
                    fill_opacity,
                    stroke_opacity,
                    opacity,
                    stop_color,
                    stop_opacity,
                )

        if tag not in geometry_tags:
            for name in ("color", "fill", "stroke", "fill-opacity", "stroke-opacity"):
                element.attrib.pop(name, None)
            if tag == "marker":
                # display does not suppress a referenced resource, but opacity
                # remains part of every instantiated marker. Preserve zero here
                # instead of translating it to display:none, which the resource
                # boundary normalization must intentionally ignore.
                if element.get("opacity") is not None:
                    element.set(
                        "opacity",
                        "0" if opacity == 0 else "0.5" if opacity < 1 else "1",
                    )
            elif tag in {"g", "svg"}:
                if opacity == 0:
                    element.set("display", "none")
                    element.set("opacity", "1")
                elif element.get("opacity") is not None:
                    element.set("opacity", "0.5" if 0 < opacity < 1 else "1")

    visit(root, "black", "black", "none", 1.0, 1.0, 1.0, "black", 1.0)
    _drop_paint_servers(root)


def _normalize_visibility_and_display(root: Any, source_id: str) -> None:
    geometry_tags = {
        "circle",
        "ellipse",
        "line",
        "path",
        "polygon",
        "polyline",
        "rect",
        "text",
    }
    removals: list[Any] = []
    resource_boundaries = {
        "clipPath",
        "defs",
        "filter",
        "linearGradient",
        "marker",
        "mask",
        "pattern",
        "radialGradient",
        "symbol",
    }

    def visit(
        element: Any,
        inherited_visibility: str,
        inherited_display: str,
        ancestor_display_none: bool,
    ) -> None:
        tag = strip_ns(element.tag)
        raw_visibility = element.attrib.pop("visibility", None)
        visibility = _computed_keyword(raw_visibility, inherited_visibility, "visible").casefold()
        if visibility not in {"visible", "hidden", "collapse"}:
            raise IconFontError(
                "SVG_VISIBILITY_INVALID",
                f"visibility={visibility!r} is invalid.",
                source=source_id,
            )
        raw_display = element.attrib.pop("display", None)
        if (
            tag in resource_boundaries
            or raw_display is None
            or raw_display.strip().casefold()
            in {
                "initial",
                "unset",
            }
        ):
            display = "inline"
        elif raw_display.strip().casefold() == "inherit":
            display = inherited_display
        else:
            display = raw_display.strip().casefold()
        if display == "contents":
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "display-layout-mode",
                "SVG_DISPLAY_UNREPRESENTABLE",
                f"display={display!r} requires layout semantics outside the outline profile.",
                source=source_id,
            )
        display_none = ancestor_display_none or display == "none"
        if tag in resource_boundaries:
            display_none = False
        if tag in geometry_tags and (display_none or visibility != "visible"):
            removals.append(element)
            return
        for child in element:
            if isinstance(child.tag, str):
                visit(child, visibility, display, display_none)

    visit(root, "visible", "inline", False)
    for element in removals:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def _drop_non_geometric_presentation_hints(root: Any) -> None:
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for name in (
            "color-interpolation",
            "color-interpolation-filters",
            "color-rendering",
            "cursor",
            "image-rendering",
            "isolation",
            "mix-blend-mode",
            "paint-order",
            "pointer-events",
            "shape-rendering",
            "tabindex",
        ):
            element.attrib.pop(name, None)


def _normalize_noop_effects(root: Any) -> None:
    def visit(element: Any, inherited_filter: str, inherited_mask: str) -> None:
        computed: dict[str, str] = {}
        for name, parent in (("filter", inherited_filter), ("mask", inherited_mask)):
            raw = element.get(name)
            if raw is None or raw.strip().casefold() in {"initial", "unset"}:
                value = "none"
            elif raw.strip().casefold() == "inherit":
                value = parent
            else:
                value = raw.strip()
            computed[name] = value
            if value.casefold() == "none":
                element.attrib.pop(name, None)
            else:
                element.set(name, value)
        for child in element:
            if isinstance(child.tag, str):
                visit(child, computed["filter"], computed["mask"])

    visit(root, "none", "none")


def _referenced_render_targets(root: Any, source_id: str) -> set[Any]:
    definition_tags = {
        "clipPath",
        "defs",
        "filter",
        "linearGradient",
        "marker",
        "mask",
        "pattern",
        "radialGradient",
        "symbol",
    }
    by_id = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }
    pending: list[str] = []

    def collect_references(element: Any) -> None:
        for raw_name, value in element.attrib.items():
            if strip_ns(raw_name).casefold() == "href" and value.startswith("#"):
                pending.append(value[1:])
            for reference in _url_references(value, source_id):
                if reference.target.startswith("#"):
                    pending.append(reference.target[1:])

    def visit_live(
        element: Any,
        parent_display: str,
        parent_opacity: float,
        ancestor_hidden: bool,
        in_definition: bool,
    ) -> None:
        tag = strip_ns(element.tag)
        definition = in_definition or tag in definition_tags
        raw_display = element.get("display")
        if raw_display is None or raw_display.strip().casefold() in {"initial", "unset"}:
            display = "inline"
        elif raw_display.strip().casefold() == "inherit":
            display = parent_display
        else:
            display = raw_display.strip().casefold()
        raw_opacity = element.get("opacity")
        if raw_opacity is None or raw_opacity.strip().casefold() in {"initial", "unset"}:
            opacity = 1.0
        elif raw_opacity.strip().casefold() == "inherit":
            opacity = parent_opacity
        else:
            opacity = _opacity_value(raw_opacity, "opacity", source_id)
        hidden = (ancestor_hidden or display == "none" or opacity == 0) and not definition
        if not hidden and not definition:
            collect_references(element)
        for child in element:
            if isinstance(child.tag, str):
                visit_live(child, display, opacity, hidden, definition)

    visit_live(root, "inline", 1.0, False, False)
    protected: set[Any] = set()
    visited: set[str] = set()
    while pending:
        identifier = pending.pop()
        if identifier in visited:
            continue
        visited.add(identifier)
        target = by_id.get(identifier)
        if target is None:
            continue
        for descendant in target.iter():
            if isinstance(descendant.tag, str):
                protected.add(descendant)
                collect_references(descendant)
        parent = target.getparent()
        while parent is not None:
            protected.add(parent)
            parent = parent.getparent()
    return protected


def _prune_display_none_render_branches(root: Any, protected: set[Any]) -> None:
    definition_tags = {
        "clipPath",
        "defs",
        "filter",
        "linearGradient",
        "marker",
        "mask",
        "pattern",
        "radialGradient",
        "symbol",
    }

    def visit(element: Any, parent_display: str, ancestor_none: bool, in_definition: bool) -> None:
        tag = strip_ns(element.tag)
        definition = in_definition or tag in definition_tags
        raw = element.get("display")
        if raw is None or raw.strip().casefold() in {"initial", "unset"}:
            display = "inline"
        elif raw.strip().casefold() == "inherit":
            display = parent_display
        else:
            display = raw.strip().casefold()
        hidden = (ancestor_none or display == "none") and not definition
        if element is not root and hidden and tag not in {"g", "svg"} and element not in protected:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
            return
        for child in tuple(element):
            if not isinstance(child.tag, str):
                continue
            child_tag = strip_ns(child.tag)
            child_definition = child_tag in definition_tags
            if (
                hidden
                and not child_definition
                and child_tag not in {"g", "svg"}
                and child not in protected
            ):
                element.remove(child)
                continue
            visit(child, display, hidden, definition)
        if not definition and display not in {"contents", "none"}:
            element.attrib.pop("display", None)

    visit(root, "inline", False, False)


def _prune_zero_opacity_render_branches(root: Any, source_id: str, protected: set[Any]) -> None:
    definition_tags = {
        "clipPath",
        "defs",
        "filter",
        "linearGradient",
        "marker",
        "mask",
        "pattern",
        "radialGradient",
        "symbol",
    }

    def visit(
        element: Any, parent_opacity: float, ancestor_zero: bool, in_definition: bool
    ) -> None:
        tag = strip_ns(element.tag)
        definition = in_definition or tag in definition_tags
        raw = element.get("opacity")
        if raw is None or raw.strip().casefold() in {"initial", "unset"}:
            opacity = 1.0
        elif raw.strip().casefold() == "inherit":
            opacity = parent_opacity
        else:
            opacity = _opacity_value(raw, "opacity", source_id)
        hidden = (ancestor_zero or opacity == 0) and not definition
        if element is not root and hidden and tag not in {"g", "svg"} and element not in protected:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
            return
        for child in tuple(element):
            if not isinstance(child.tag, str):
                continue
            child_tag = strip_ns(child.tag)
            child_definition = child_tag in definition_tags
            if (
                hidden
                and not child_definition
                and child_tag not in {"g", "svg"}
                and child not in protected
            ):
                element.remove(child)
                continue
            visit(child, opacity, hidden, definition)
        if not definition:
            if opacity == 1:
                element.attrib.pop("opacity", None)
            elif raw is not None and raw.strip().casefold() in {"inherit", "initial", "unset"}:
                element.set("opacity", f"{opacity:.17g}")

    visit(root, 1.0, False, False)


def _prune_unreachable_definitions(root: Any, source_id: str) -> None:
    definition_tags = {
        "clipPath",
        "defs",
        "filter",
        "linearGradient",
        "marker",
        "mask",
        "pattern",
        "radialGradient",
        "symbol",
    }
    by_id = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }

    def inside_definition(element: Any) -> bool:
        parent = element.getparent()
        while parent is not None:
            if isinstance(parent.tag, str) and strip_ns(parent.tag) in definition_tags:
                return True
            parent = parent.getparent()
        return False

    def references(element: Any) -> set[str]:
        result: set[str] = set()
        for descendant in element.iter():
            if not isinstance(descendant.tag, str):
                continue
            for raw_name, value in descendant.attrib.items():
                if strip_ns(raw_name).casefold() == "href" and value.startswith("#"):
                    result.add(value[1:])
                for reference in _url_references(value, source_id):
                    if reference.target.startswith("#"):
                        result.add(reference.target[1:])
        return result

    pending: list[str] = []
    for element in root.iter():
        if (
            not isinstance(element.tag, str)
            or strip_ns(element.tag) in definition_tags
            or inside_definition(element)
        ):
            continue
        for raw_name, value in element.attrib.items():
            if strip_ns(raw_name).casefold() == "href" and value.startswith("#"):
                pending.append(value[1:])
            for reference in _url_references(value, source_id):
                if reference.target.startswith("#"):
                    pending.append(reference.target[1:])

    reachable_ids: set[str] = set()
    keep_nodes: set[Any] = {root}
    while pending:
        identifier = pending.pop()
        if identifier in reachable_ids:
            continue
        reachable_ids.add(identifier)
        target = by_id.get(identifier)
        if target is None:
            continue
        for descendant in target.iter():
            if isinstance(descendant.tag, str):
                keep_nodes.add(descendant)
        parent = target.getparent()
        while parent is not None:
            keep_nodes.add(parent)
            parent = parent.getparent()
        pending.extend(references(target) - reachable_ids)

    for element in reversed(tuple(root.iter())):
        if element is root or not isinstance(element.tag, str):
            continue
        tag = strip_ns(element.tag)
        if tag == "defs":
            continue
        if (
            inside_definition(element) or tag in definition_tags - {"defs"}
        ) and element not in keep_nodes:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)


def _symbol_length(
    value: str | None, name: str, source_id: str, *, nonnegative: bool = True
) -> float:
    if value is None:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "symbol-external-viewport",
            "SVG_SYMBOL_VIEWPORT_UNREPRESENTABLE",
            f"A symbol use requires an explicit numeric {name}.",
            source=source_id,
            hint="Set numeric width and height on every use of a symbol.",
        )
    match = _CSS_LENGTH_TOKEN.fullmatch(value.strip())
    if match is not None and match.group(2) == "%":
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "symbol-external-viewport",
            "SVG_SYMBOL_VIEWPORT_UNREPRESENTABLE",
            f"Symbol {name}={value!r} depends on an external viewport.",
            source=source_id,
        )
    result = _resolved_bounded_length(
        value,
        1.0,
        source_id,
        feature="symbol-external-viewport",
        unrepresentable_code="SVG_SYMBOL_VIEWPORT_UNREPRESENTABLE",
        invalid_code="SVG_SYMBOL_VIEWPORT_INVALID",
        label=f"symbol {name}",
    )
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise IconFontError(
            "SVG_SYMBOL_VIEWPORT_INVALID",
            f"Symbol {name} must be finite and nonnegative.",
            source=source_id,
        )
    return result


def _symbol_reference_coordinate(
    value: str,
    *,
    axis: str,
    view_box: Rect,
    source_id: str,
) -> float:
    normalized = value.strip().casefold()
    if axis == "x" and normalized in {"left", "center", "right"}:
        return {
            "left": view_box.x,
            "center": view_box.x + view_box.w / 2,
            "right": view_box.x + view_box.w,
        }[normalized]
    if axis == "y" and normalized in {"bottom", "center", "top"}:
        return {
            "top": view_box.y,
            "center": view_box.y + view_box.h / 2,
            "bottom": view_box.y + view_box.h,
        }[normalized]
    basis = view_box.w if axis == "x" else view_box.h
    origin = view_box.x if axis == "x" else view_box.y
    resolved = _resolved_bounded_length(
        value,
        basis,
        source_id,
        feature="symbol-reference-environment",
        unrepresentable_code="SVG_SYMBOL_REFERENCE_UNREPRESENTABLE",
        invalid_code="SVG_SYMBOL_REFERENCE_INVALID",
        label=f"symbol ref{axis.upper()}",
    )
    match = _CSS_LENGTH_TOKEN.fullmatch(value.strip())
    return origin + resolved if match is not None and match.group(2) == "%" else resolved


def _rewrite_cloned_ids(element: Any, prefix: str, used_ids: set[str]) -> None:
    replacements: dict[str, str] = {}
    for descendant in element.iter():
        if not isinstance(descendant.tag, str):
            continue
        identifier = descendant.get("id")
        if identifier is None:
            continue
        candidate = f"{prefix}{identifier}"
        suffix = 1
        while candidate in used_ids:
            candidate = f"{prefix}{identifier}_{suffix}"
            suffix += 1
        used_ids.add(candidate)
        replacements[identifier] = candidate
        descendant.set("id", candidate)

    for descendant in element.iter():
        if not isinstance(descendant.tag, str):
            continue
        for raw_name, value in tuple(descendant.attrib.items()):
            if strip_ns(raw_name).lower() == "href" and value.startswith("#"):
                target = value[1:]
                if target in replacements:
                    descendant.set(raw_name, f"#{replacements[target]}")
            else:
                references = _url_references(value, "expanded SVG reference")
                if not references:
                    continue
                pieces: list[str] = []
                cursor = 0
                for reference in references:
                    pieces.append(value[cursor : reference.start])
                    target = reference.target
                    if target.startswith("#") and target[1:] in replacements:
                        pieces.append(f"url(#{replacements[target[1:]]})")
                    else:
                        pieces.append(value[reference.start : reference.end])
                    cursor = reference.end
                pieces.append(value[cursor:])
                descendant.set(raw_name, "".join(pieces))


def _expand_symbol_uses(root: Any, source_id: str) -> None:
    used_ids = {
        identifier
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }
    instance = 0
    while True:
        by_id = {
            identifier: element
            for element in root.iter()
            if isinstance(element.tag, str)
            if (identifier := element.get("id")) is not None
        }
        target_use: tuple[Any, Any] | None = None
        for element in root.iter():
            if not isinstance(element.tag, str) or strip_ns(element.tag) != "use":
                continue
            href = next(
                (
                    value
                    for raw_name, value in element.attrib.items()
                    if strip_ns(raw_name).lower() == "href"
                ),
                "",
            )
            target = by_id.get(href[1:]) if href.startswith("#") else None
            if target is not None and strip_ns(target.tag) == "symbol":
                target_use = (element, target)
                break
        if target_use is None:
            break

        use, symbol = target_use
        if _has_ancestor(use, "clipPath"):
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "symbol-in-clip",
                "SVG_SYMBOL_CLIP_UNREPRESENTABLE",
                "A clip-path use cannot reference a symbol viewport.",
                source=source_id,
            )
        width = _symbol_length(use.get("width", symbol.get("width")), "width", source_id)
        height = _symbol_length(use.get("height", symbol.get("height")), "height", source_id)
        x = _symbol_length(use.get("x", "0"), "x", source_id, nonnegative=False)
        y = _symbol_length(use.get("y", "0"), "y", source_id, nonnegative=False)
        x += _symbol_length(symbol.get("x", "0"), "symbol x", source_id, nonnegative=False)
        y += _symbol_length(symbol.get("y", "0"), "symbol y", source_id, nonnegative=False)

        view_box_value = symbol.get("viewBox")
        if view_box_value is not None:
            view_box_values = tuple(
                float(part) for part in re.split(r"[\s,]+", view_box_value.strip()) if part
            )
            symbol_view_box = Rect(*view_box_values)
        else:
            symbol_view_box = Rect(0, 0, width, height)
        if symbol.get("refX") is not None or symbol.get("refY") is not None:
            reference_x = _symbol_reference_coordinate(
                symbol.get("refX", "left"),
                axis="x",
                view_box=symbol_view_box,
                source_id=source_id,
            )
            reference_y = _symbol_reference_coordinate(
                symbol.get("refY", "top"),
                axis="y",
                view_box=symbol_view_box,
                source_id=source_id,
            )
            try:
                viewport = Affine2D.rect_to_rect(
                    symbol_view_box,
                    Rect(0, 0, width, height),
                    symbol.get("preserveAspectRatio", "xMidYMid"),
                )
            except (ValueError, TypeError) as error:
                raise IconFontError(
                    "SVG_SYMBOL_ASPECT_RATIO_INVALID",
                    str(error),
                    source=source_id,
                ) from error
            mapped_reference = viewport.map_point((reference_x, reference_y))
            x -= mapped_reference.x
            y -= mapped_reference.y

        outer = root.makeelement(f"{{{_SVG_NAMESPACE}}}g")
        nested = root.makeelement(f"{{{_SVG_NAMESPACE}}}svg")
        excluded_use = {"href", "height", "transform", "width", "x", "y"}
        for raw_name, value in use.attrib.items():
            if strip_ns(raw_name).lower() not in excluded_use:
                outer.set(raw_name, value)
        if transform := use.get("transform"):
            outer.set("transform", transform)
        nested.set("x", f"{x:.12g}")
        nested.set("y", f"{y:.12g}")
        nested.set("width", f"{width:.12g}")
        nested.set("height", f"{height:.12g}")
        if view_box := symbol.get("viewBox"):
            nested.set("viewBox", view_box)
        else:
            nested.set("viewBox", f"0 0 {width:.12g} {height:.12g}")
        nested.set("preserveAspectRatio", symbol.get("preserveAspectRatio", "xMidYMid"))
        nested.set("overflow", symbol.get("overflow", "hidden"))
        excluded_symbol = {
            "display",
            "height",
            "id",
            "overflow",
            "preserveaspectratio",
            "viewbox",
            "width",
            "x",
            "y",
            "refx",
            "refy",
        }
        for raw_name, value in symbol.attrib.items():
            if strip_ns(raw_name).lower() not in excluded_symbol:
                nested.set(raw_name, value)
        for child in symbol:
            nested.append(copy.deepcopy(child))
        instance += 1
        _rewrite_cloned_ids(nested, f"__symbol_{instance}_", used_ids)
        if width != 0 and height != 0:
            outer.append(nested)
        outer.tail = use.tail
        parent = use.getparent()
        if parent is None:
            raise IconFontError(
                "SVG_SYMBOL_EXPANSION_FAILED",
                "A symbol use has no parent element.",
                source=source_id,
            )
        parent.replace(use, outer)

    for symbol in tuple(
        element
        for element in root.iter()
        if isinstance(element.tag, str) and strip_ns(element.tag) == "symbol"
    ):
        parent = symbol.getparent()
        if parent is not None:
            parent.remove(symbol)


def _normalize_static_structure(root: Any, source_id: str) -> None:
    for element in tuple(root.iter()):
        if not isinstance(element.tag, str) or strip_ns(element.tag) != "a":
            continue
        for raw_name in tuple(element.attrib):
            if strip_ns(raw_name).casefold() == "href":
                del element.attrib[raw_name]
        element.tag = f"{{{_SVG_NAMESPACE}}}g"

    switches = tuple(
        element
        for element in root.iter()
        if isinstance(element.tag, str) and strip_ns(element.tag) == "switch"
    )
    condition_names = {"requiredextensions", "requiredfeatures", "systemlanguage"}
    for element in reversed(switches):
        children = tuple(child for child in element if isinstance(child.tag, str))
        selected: Any | None = None
        for child in children:
            conditions = {
                strip_ns(name).casefold()
                for name in child.attrib
                if strip_ns(name).casefold() in condition_names
            }
            if conditions:
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "conditional-switch",
                    "SVG_SWITCH_ENVIRONMENT_UNREPRESENTABLE",
                    "switch child selection depends on runtime language or feature support.",
                    source=source_id,
                    details={"conditions": sorted(conditions)},
                )
            selected = child
            break
        for child in children:
            if child is not selected:
                element.remove(child)
        element.tag = f"{{{_SVG_NAMESPACE}}}g"

    for element in reversed(tuple(root.iter())):
        if not isinstance(element.tag, str) or strip_ns(element.tag) != "view":
            continue
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def _materialize_marker_references(root: Any) -> None:
    geometry_tags = {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}

    def visit(element: Any, inherited: tuple[str, str, str]) -> None:
        values = cast(
            tuple[str, str, str],
            tuple(
                _computed_keyword(element.get(name), parent, "none")
                for name, parent in zip(
                    ("marker-start", "marker-mid", "marker-end"), inherited, strict=True
                )
            ),
        )
        if strip_ns(element.tag) in geometry_tags:
            for name, value in zip(
                ("marker-start", "marker-mid", "marker-end"), values, strict=True
            ):
                element.set(name, value)
        for child in element:
            if isinstance(child.tag, str):
                visit(child, values)
        if strip_ns(element.tag) not in geometry_tags:
            for name in ("marker-start", "marker-mid", "marker-end"):
                element.attrib.pop(name, None)

    visit(root, ("none", "none", "none"))


def _materialize_computed_geometry_properties(root: Any, source_id: str) -> None:
    geometry_tags = {
        "circle",
        "ellipse",
        "line",
        "path",
        "polygon",
        "polyline",
        "rect",
        "text",
    }

    def visit(
        element: Any,
        parent_fill_rule: str,
        parent_linecap: str,
        parent_linejoin: str,
        parent_miterlimit: str,
        parent_clip_path: str,
        parent_vector_effect: str,
    ) -> None:
        fill_rule = _computed_keyword(element.get("fill-rule"), parent_fill_rule, "nonzero")
        linecap = _computed_keyword(element.get("stroke-linecap"), parent_linecap, "butt")
        linejoin = _computed_keyword(element.get("stroke-linejoin"), parent_linejoin, "miter")
        miterlimit = _computed_keyword(element.get("stroke-miterlimit"), parent_miterlimit, "4")
        clip_path = _computed_noninherited_keyword(
            element.get("clip-path"), parent_clip_path, "none"
        )
        vector_effect = _computed_noninherited_keyword(
            element.get("vector-effect"), parent_vector_effect, "none"
        )
        if fill_rule not in {"evenodd", "nonzero"}:
            raise IconFontError(
                "SVG_FILL_RULE_INVALID",
                f"fill-rule={fill_rule!r} is invalid.",
                source=source_id,
            )
        if linecap not in {"butt", "round", "square"}:
            raise IconFontError(
                "SVG_STROKE_CAP_INVALID",
                f"stroke-linecap={linecap!r} is invalid.",
                source=source_id,
            )
        if linejoin in {"arcs", "miter-clip"}:
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "stroke-linejoin-mode",
                "SVG_STROKE_JOIN_UNREPRESENTABLE",
                f"stroke-linejoin={linejoin!r} requires an extended SVG 2 stroker.",
                source=source_id,
            )
        if linejoin not in {"bevel", "miter", "round"}:
            raise IconFontError(
                "SVG_STROKE_JOIN_INVALID",
                f"stroke-linejoin={linejoin!r} is invalid.",
                source=source_id,
            )
        try:
            numeric_miterlimit = float(miterlimit)
        except ValueError as error:
            raise IconFontError(
                "SVG_STROKE_MITERLIMIT_INVALID",
                f"stroke-miterlimit={miterlimit!r} is invalid.",
                source=source_id,
            ) from error
        if not math.isfinite(numeric_miterlimit) or numeric_miterlimit < 1:
            raise IconFontError(
                "SVG_STROKE_MITERLIMIT_INVALID",
                "stroke-miterlimit must be finite and at least 1.",
                source=source_id,
            )
        if vector_effect not in {"none", "non-scaling-stroke"}:
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "vector-effect-mode",
                "SVG_VECTOR_EFFECT_UNREPRESENTABLE",
                f"vector-effect={vector_effect!r} is outside the non-scaling-stroke profile.",
                source=source_id,
            )

        tag = strip_ns(element.tag)
        if tag in geometry_tags:
            element.set("fill-rule", fill_rule)
            element.set("stroke-linecap", linecap)
            element.set("stroke-linejoin", linejoin)
            element.set("stroke-miterlimit", f"{numeric_miterlimit:.17g}")
            element.set("vector-effect", vector_effect)
        else:
            for name in (
                "fill-rule",
                "stroke-linecap",
                "stroke-linejoin",
                "stroke-miterlimit",
                "vector-effect",
            ):
                element.attrib.pop(name, None)
        if clip_path.casefold() == "none":
            element.attrib.pop("clip-path", None)
        else:
            element.set("clip-path", clip_path)

        for child in element:
            if isinstance(child.tag, str):
                visit(
                    child,
                    fill_rule,
                    linecap,
                    linejoin,
                    f"{numeric_miterlimit:.17g}",
                    clip_path,
                    vector_effect,
                )

    visit(root, "nonzero", "butt", "miter", "4", "none", "none")


def _nonzero_vector(*vectors: tuple[float, float]) -> tuple[float, float]:
    return next((vector for vector in vectors if not math.isclose(math.hypot(*vector), 0)), (0, 0))


def _marker_subpaths(path: SVGPath, source_id: str) -> tuple[tuple[_PathSegment, ...], ...]:
    normalized = (
        path.absolute(inplace=False).explicit_lines(inplace=True).expand_shorthand(inplace=True)
    )
    subpaths: list[list[_PathSegment]] = []
    current_subpath: list[_PathSegment] = []
    current = (0.0, 0.0)
    start = current

    def segment_for(
        command: str,
        arguments: tuple[float, ...],
        segment_start: tuple[float, float],
        *,
        logical_end: bool = True,
    ) -> _PathSegment:
        if command == "L":
            end = (arguments[0], arguments[1])
            tangent = _nonzero_vector((end[0] - segment_start[0], end[1] - segment_start[1]))
            return _PathSegment(segment_start, end, tangent, tangent, logical_end)
        if command == "Q":
            control = (arguments[0], arguments[1])
            end = (arguments[2], arguments[3])
            return _PathSegment(
                segment_start,
                end,
                _nonzero_vector(
                    (control[0] - segment_start[0], control[1] - segment_start[1]),
                    (end[0] - segment_start[0], end[1] - segment_start[1]),
                ),
                _nonzero_vector(
                    (end[0] - control[0], end[1] - control[1]),
                    (end[0] - segment_start[0], end[1] - segment_start[1]),
                ),
                logical_end,
            )
        if command == "C":
            first = (arguments[0], arguments[1])
            second = (arguments[2], arguments[3])
            end = (arguments[4], arguments[5])
            return _PathSegment(
                segment_start,
                end,
                _nonzero_vector(
                    (first[0] - segment_start[0], first[1] - segment_start[1]),
                    (second[0] - segment_start[0], second[1] - segment_start[1]),
                    (end[0] - segment_start[0], end[1] - segment_start[1]),
                ),
                _nonzero_vector(
                    (end[0] - second[0], end[1] - second[1]),
                    (end[0] - first[0], end[1] - first[1]),
                    (end[0] - segment_start[0], end[1] - segment_start[1]),
                ),
                logical_end,
            )
        if command == "Z":
            end = start
            tangent = _nonzero_vector((end[0] - segment_start[0], end[1] - segment_start[1]))
            return _PathSegment(segment_start, end, tangent, tangent, logical_end)
        raise IconFontError(
            "SVG_MARKER_PATH_INVALID",
            f"Unexpected path command {command!r} during marker analysis.",
            source=source_id,
        )

    for command, arguments in normalized:
        if command == "M":
            if current_subpath:
                subpaths.append(current_subpath)
                current_subpath = []
            current = (arguments[0], arguments[1])
            start = current
            continue
        if command == "A":
            arc_input: tuple[tuple[str, tuple[float, ...]], ...] = (
                ("M", current),
                ("A", cast(tuple[float, ...], arguments)),
            )
            arc = SVGPath.from_commands(item for item in arc_input).arcs_to_cubics()
            arc_commands = tuple(
                (arc_command, arc_arguments)
                for arc_command, arc_arguments in arc
                if arc_command != "M"
            )
            if not arc_commands:
                end = (arguments[-2], arguments[-1])
                current_subpath.append(_PathSegment(current, end, (0, 0), (0, 0)))
                current = end
                continue
            for index, (arc_command, arc_arguments) in enumerate(arc_commands):
                segment = segment_for(
                    arc_command,
                    arc_arguments,
                    current,
                    logical_end=index == len(arc_commands) - 1,
                )
                current_subpath.append(segment)
                current = segment.end
            continue
        segment = segment_for(command, arguments, current)
        current_subpath.append(segment)
        current = segment.end
    if current_subpath:
        subpaths.append(current_subpath)
    return tuple(tuple(subpath) for subpath in subpaths)


def _vector_angle(vector: tuple[float, float]) -> float:
    return math.degrees(math.atan2(vector[1], vector[0]))


def _forward_marker_tangent(subpath: tuple[_PathSegment, ...], index: int) -> tuple[float, float]:
    for segment in subpath[index:]:
        tangent = _nonzero_vector(segment.start_tangent, segment.end_tangent)
        if tangent != (0, 0):
            return tangent
    return (1, 0)


def _backward_marker_tangent(subpath: tuple[_PathSegment, ...], index: int) -> tuple[float, float]:
    for segment in reversed(subpath[: index + 1]):
        tangent = _nonzero_vector(segment.end_tangent, segment.start_tangent)
        if tangent != (0, 0):
            return tangent
    return (1, 0)


def _mid_angle(incoming: tuple[float, float], outgoing: tuple[float, float]) -> float:
    incoming_length = math.hypot(*incoming)
    outgoing_length = math.hypot(*outgoing)
    left = (incoming[0] / incoming_length, incoming[1] / incoming_length)
    right = (outgoing[0] / outgoing_length, outgoing[1] / outgoing_length)
    combined = (left[0] + right[0], left[1] + right[1])
    return _vector_angle(left if math.isclose(math.hypot(*combined), 0) else combined)


def _marker_view_box(marker: Any, width: float, height: float, source_id: str) -> Rect:
    value = marker.get("viewBox")
    if value is None:
        return Rect(0, 0, width, height)
    parts = tuple(part for part in re.split(r"[\s,]+", value.strip()) if part)
    if len(parts) != 4:
        raise IconFontError(
            "SVG_MARKER_VIEWBOX_INVALID",
            "Marker viewBox must contain four numbers.",
            source=source_id,
        )
    try:
        values = tuple(float(part) for part in parts)
    except ValueError as error:
        raise IconFontError(
            "SVG_MARKER_VIEWBOX_INVALID",
            "Marker viewBox must contain four finite numbers.",
            source=source_id,
        ) from error
    if not all(math.isfinite(value) for value in values) or values[2] < 0 or values[3] < 0:
        raise IconFontError(
            "SVG_MARKER_VIEWBOX_INVALID",
            "Marker viewBox dimensions must be finite and nonnegative.",
            source=source_id,
        )
    return Rect(*values)


def _marker_reference_coordinate(
    value: str,
    *,
    axis: str,
    view_box: Rect,
    source_id: str,
) -> float:
    normalized = value.strip().casefold()
    if axis == "x" and normalized in {"left", "center", "right"}:
        return {
            "left": view_box.x,
            "center": view_box.x + view_box.w / 2,
            "right": view_box.x + view_box.w,
        }[normalized]
    if axis == "y" and normalized in {"bottom", "center", "top"}:
        return {
            "top": view_box.y,
            "center": view_box.y + view_box.h / 2,
            "bottom": view_box.y + view_box.h,
        }[normalized]
    basis = view_box.w if axis == "x" else view_box.h
    origin = view_box.x if axis == "x" else view_box.y
    resolved = _resolved_bounded_length(
        value,
        basis,
        source_id,
        feature="marker-reference-environment",
        unrepresentable_code="SVG_MARKER_REFERENCE_UNREPRESENTABLE",
        invalid_code="SVG_MARKER_REFERENCE_INVALID",
        label=f"marker ref{axis.upper()}",
    )
    match = _CSS_LENGTH_TOKEN.fullmatch(value.strip())
    return origin + resolved if match is not None and match.group(2) == "%" else resolved


def _marker_angle(orient: str, automatic: float, kind: str, source_id: str) -> float:
    lowered = orient.strip().casefold()
    if lowered == "auto":
        return automatic
    if lowered == "auto-start-reverse":
        return automatic + (180 if kind == "start" else 0)
    match = re.fullmatch(rf"({_NUMBER_TOKEN.pattern})(deg|grad|rad|turn)?", lowered)
    if match is None:
        raise IconFontError(
            "SVG_MARKER_ORIENTATION_INVALID",
            f"Marker orient={orient!r} is invalid.",
            source=source_id,
        )
    angle = float(match.group(1))
    unit = match.group(2) or "deg"
    angle *= {
        "deg": 1.0,
        "grad": 0.9,
        "rad": 180.0 / math.pi,
        "turn": 360.0,
    }[unit]
    if not math.isfinite(angle):
        raise IconFontError(
            "SVG_MARKER_ORIENTATION_INVALID",
            "Marker orientation must be finite.",
            source=source_id,
        )
    return angle


def _expand_markers(root: Any, source_id: str, config: BuildConfig) -> None:
    _materialize_marker_references(root)
    by_id = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }
    definitions = next(
        (child for child in root if isinstance(child.tag, str) and strip_ns(child.tag) == "defs"),
        None,
    )
    if definitions is None:
        definitions = root.makeelement(f"{{{_SVG_NAMESPACE}}}defs")
        root.insert(0, definitions)
    used_ids = set(by_id)
    clip_ids: dict[str, str] = {}
    expanded_elements = 0
    expanded_bytes = 0
    marker_targets = tuple(
        element
        for element in root.iter()
        if isinstance(element.tag, str)
        and strip_ns(element.tag)
        in {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}
        and any(
            element.get(name, "none") != "none"
            for name in ("marker-start", "marker-mid", "marker-end")
        )
    )
    for target in marker_targets:
        if _has_ancestor(target, "marker"):
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "nested-marker",
                "SVG_NESTED_MARKER_UNREPRESENTABLE",
                "Markers cannot recursively contain marked geometry in the bounded profile.",
                source=source_id,
            )
        if target.get("vector-effect", "none") != "none":
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "marker-vector-effect",
                "SVG_MARKER_VECTOR_EFFECT_UNREPRESENTABLE",
                "Markers combined with vector effects require the extended stroke profile.",
                source=source_id,
            )
        shape = from_element(target)
        subpaths = _marker_subpaths(cast(SVGPath, shape.as_path()), source_id)
        occurrences: list[tuple[str, tuple[float, float], float, str]] = []
        references = {
            kind: target.attrib.pop(f"marker-{kind}", "none") for kind in ("start", "mid", "end")
        }
        for subpath in subpaths:
            if not subpath:
                continue
            if references["start"] != "none":
                occurrences.append(
                    (
                        "start",
                        subpath[0].start,
                        _vector_angle(_forward_marker_tangent(subpath, 0)),
                        references["start"],
                    )
                )
            if references["mid"] != "none":
                for index, (left, _right) in enumerate(pairwise(subpath)):
                    if not left.logical_end:
                        continue
                    occurrences.append(
                        (
                            "mid",
                            left.end,
                            _mid_angle(
                                _backward_marker_tangent(subpath, index),
                                _forward_marker_tangent(subpath, index + 1),
                            ),
                            references["mid"],
                        )
                    )
            if references["end"] != "none":
                occurrences.append(
                    (
                        "end",
                        subpath[-1].end,
                        _vector_angle(_backward_marker_tangent(subpath, len(subpath) - 1)),
                        references["end"],
                    )
                )

        parent = target.getparent()
        if parent is None:
            continue
        insert_at = parent.index(target) + 1
        target_clip = target.get("clip-path")
        target_opacity = target.attrib.pop(_MARKER_TARGET_OPACITY, "1")
        wrap_decorated_target = target_clip not in {None, "none"} or target_opacity != "1"
        generated_markers: list[Any] = []
        target_transform = (
            Affine2D.fromstring(target.get("transform"))
            if target.get("transform")
            else Affine2D.identity()
        )
        for offset, (kind, point, automatic_angle, reference) in enumerate(occurrences):
            marker_id = _clip_reference(reference, source_id)
            marker = by_id.get(marker_id)
            if marker is None or strip_ns(marker.tag) != "marker":
                raise IconFontError(
                    "SVG_MARKER_REFERENCE_INVALID",
                    f"Marker target {marker_id!r} is not a marker element.",
                    source=source_id,
                )
            width = _symbol_length(marker.get("markerWidth", "3"), "markerWidth", source_id)
            height = _symbol_length(marker.get("markerHeight", "3"), "markerHeight", source_id)
            if width == 0 or height == 0:
                continue
            view_box = _marker_view_box(marker, width, height, source_id)
            if view_box.w == 0 or view_box.h == 0:
                continue
            ref_x = _marker_reference_coordinate(
                marker.get("refX", "0"), axis="x", view_box=view_box, source_id=source_id
            )
            ref_y = _marker_reference_coordinate(
                marker.get("refY", "0"), axis="y", view_box=view_box, source_id=source_id
            )
            marker_units = marker.get("markerUnits", "strokeWidth")
            if marker_units == "strokeWidth":
                unit_scale = float(shape.stroke_width)
            elif marker_units == "userSpaceOnUse":
                unit_scale = 1.0
            else:
                raise IconFontError(
                    "SVG_MARKER_UNITS_INVALID",
                    f"markerUnits={marker_units!r} is invalid.",
                    source=source_id,
                )
            try:
                viewport = Affine2D.rect_to_rect(
                    view_box,
                    Rect(0, 0, width, height),
                    marker.get("preserveAspectRatio", "xMidYMid"),
                )
            except ValueError as error:
                raise IconFontError(
                    "SVG_MARKER_ASPECT_RATIO_INVALID",
                    str(error),
                    source=source_id,
                ) from error
            mapped_ref = viewport.map_point((ref_x, ref_y))
            angle = _marker_angle(marker.get("orient", "0"), automatic_angle, kind, source_id)
            placement = Affine2D.compose_ltr(
                (
                    Affine2D.identity().translate(-mapped_ref.x, -mapped_ref.y),
                    Affine2D.identity().scale(unit_scale),
                    Affine2D.identity().rotate(math.radians(angle)),
                    Affine2D.identity().translate(point[0], point[1]),
                    Affine2D.identity() if wrap_decorated_target else target_transform,
                )
            )
            outer = root.makeelement(f"{{{_SVG_NAMESPACE}}}g", {"transform": placement.tostring()})
            viewport_group = root.makeelement(
                f"{{{_SVG_NAMESPACE}}}g", {"transform": viewport.tostring()}
            )
            for container_name in ("clip-path", "opacity", "visibility"):
                container_value = marker.get(container_name)
                if container_value is not None:
                    viewport_group.set(container_name, container_value)
            for child in marker:
                viewport_group.append(copy.deepcopy(child))
            _rewrite_cloned_ids(viewport_group, f"__marker_{marker_id}_{offset}_", used_ids)
            for descendant in viewport_group.iter():
                if not isinstance(descendant.tag, str):
                    continue
                for name in ("fill", "stroke"):
                    value = descendant.get(name, "")
                    if value.casefold() == "context-fill":
                        descendant.set(name, shape.fill)
                    elif value.casefold() == "context-stroke":
                        descendant.set(name, shape.stroke)
            overflow = marker.get("overflow", "hidden")
            if overflow == "hidden":
                clip_id = clip_ids.get(marker_id)
                if clip_id is None:
                    clip_id = f"__marker_viewport_{len(clip_ids) + 1}"
                    while clip_id in used_ids:
                        clip_id += "_"
                    used_ids.add(clip_id)
                    clip = root.makeelement(
                        f"{{{_SVG_NAMESPACE}}}clipPath",
                        {"id": clip_id, "clipPathUnits": "userSpaceOnUse"},
                    )
                    clip.append(
                        root.makeelement(
                            f"{{{_SVG_NAMESPACE}}}rect",
                            {
                                "x": "0",
                                "y": "0",
                                "width": f"{width:.12g}",
                                "height": f"{height:.12g}",
                            },
                        )
                    )
                    definitions.append(clip)
                    clip_ids[marker_id] = clip_id
                clipped_group = root.makeelement(
                    f"{{{_SVG_NAMESPACE}}}g", {"clip-path": f"url(#{clip_id})"}
                )
                clipped_group.append(viewport_group)
                outer.append(clipped_group)
            elif overflow != "visible":
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "marker-overflow-mode",
                    "SVG_MARKER_OVERFLOW_UNREPRESENTABLE",
                    f"Marker overflow={overflow!r} is outside the marker viewport profile.",
                    source=source_id,
                )
            else:
                outer.append(viewport_group)
            element_count = sum(1 for _ in outer.iter())
            byte_count = sum(
                len(str(element.tag).encode("utf-8"))
                + sum(
                    len(str(name).encode("utf-8")) + len(value.encode("utf-8"))
                    for name, value in element.attrib.items()
                )
                for element in outer.iter()
                if isinstance(element.tag, str)
            )
            expanded_elements += element_count
            expanded_bytes += byte_count
            if (
                expanded_elements > config.max_expanded_elements
                or expanded_bytes > config.max_expanded_bytes
            ):
                raise IconFontError(
                    "SVG_MARKER_EXPANSION_LIMIT",
                    "Marker instances exceed the configured expansion work budget.",
                    source=source_id,
                )
            generated_markers.append(outer)

        if wrap_decorated_target:
            # A marker is a decoration of the marked element, so the element's
            # clip applies to both its own paint and every marker instance. Keep
            # them in one transformed/clipped unit instead of leaving generated
            # marker siblings outside the target clip.
            target_index = parent.index(target)
            wrapper_attributes: dict[str, str] = {}
            if target.get("clip-path") not in {None, "none"}:
                wrapper_attributes["clip-path"] = target.attrib.pop("clip-path")
            if target_opacity != "1":
                wrapper_attributes["opacity"] = target_opacity
            target_transform_text = target.attrib.pop("transform", None)
            if target_transform_text:
                wrapper_attributes["transform"] = target_transform_text
            wrapper = root.makeelement(f"{{{_SVG_NAMESPACE}}}g", wrapper_attributes)
            wrapper.tail = target.tail
            target.tail = None
            wrapper.append(target)
            for marker in generated_markers:
                wrapper.append(marker)
            parent.insert(target_index, wrapper)
        else:
            for offset, marker in enumerate(generated_markers):
                parent.insert(insert_at + offset, marker)

    for marker in tuple(
        element
        for element in root.iter()
        if isinstance(element.tag, str) and strip_ns(element.tag) == "marker"
    ):
        parent = marker.getparent()
        if parent is not None:
            parent.remove(marker)


def _normalize_clip_semantics(root: Any, source_id: str) -> None:
    """Make inherited clip rules explicit and reject unsafe reuse inside clips."""
    geometry_tags = {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}

    def visit(element: Any, inherited_rule: str, inside_clip: bool) -> None:
        tag = strip_ns(element.tag)
        attribute_rule: str | None = None
        style_rule: str | None = None
        attribute_name: str | None = None
        style_name: str | None = None
        style_properties: dict[str, str] = {}
        for raw_name, value in tuple(element.attrib.items()):
            lowered = strip_ns(raw_name).lower()
            if lowered == "clip-rule":
                attribute_rule = value.strip().casefold()
                attribute_name = raw_name
            elif lowered == "style":
                style_name = raw_name
                style_properties = _parse_style(value, source_id)
                style_rule = style_properties.get("clip-rule")
        direct_rule = style_rule.strip().casefold() if style_rule is not None else attribute_rule
        computed_rule = direct_rule if direct_rule is not None else inherited_rule
        if computed_rule not in {"nonzero", "evenodd"}:
            raise IconFontError(
                "SVG_CLIP_RULE_UNSUPPORTED",
                f"clip-rule={computed_rule!r} is outside the strict clip profile.",
                source=source_id,
                hint="Use only nonzero or evenodd.",
            )

        # PicoSVG does not consistently inherit clip-rule from containers. Remove
        # the inherited declarations after computing them, then materialize the
        # value only on geometry that participates in a clip.
        if attribute_name is not None:
            del element.attrib[attribute_name]
        if style_name is not None and "clip-rule" in style_properties:
            del style_properties["clip-rule"]
            if style_properties:
                element.attrib[style_name] = ";".join(
                    f"{name}:{value}" for name, value in style_properties.items()
                )
            else:
                del element.attrib[style_name]

        now_inside_clip = inside_clip or tag == "clipPath"
        if inside_clip and tag == "use":
            raise IconFontError(
                "SVG_CLIP_USE_UNSUPPORTED",
                "use inside clipPath can import hidden or recursively clipped semantics.",
                source=source_id,
                hint="Expand the referenced clip geometry into explicit shapes.",
            )
        if now_inside_clip and tag in geometry_tags:
            element.set("clip-rule", computed_rule)
        for child in element:
            if isinstance(child.tag, str):
                visit(child, computed_rule, now_inside_clip)

    visit(root, "nonzero", False)


def _element_transform(element: Any, inherited: Affine2D) -> Affine2D:
    value = element.get("transform")
    if not value:
        return inherited
    return Affine2D.compose_ltr((Affine2D.fromstring(value), inherited))


def _intersection_paths(left: SVGPath, right: SVGPath) -> SVGPath | None:
    result = SVGPath.from_commands(
        svg_pathops.intersection(
            [left.as_cmd_seq(), right.as_cmd_seq()],
            ["nonzero", "nonzero"],
        )
    )
    result.remove_empty_subpaths(inplace=True)
    return result if _path_has_area(result) else None


def _clip_reference(value: str, source_id: str) -> str:
    return _single_local_url(
        value,
        source_id,
        "SVG_CLIP_REFERENCE_INVALID",
        "Clip reference",
    )


def _materialize_clips(root: Any, source_id: str, config: BuildConfig) -> None:
    """Reduce nested and object-bounding-box clips to target-specific user-space paths."""

    geometry_tags = {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}
    for nested_svg in tuple(
        element
        for element in root.iter()
        if element is not root
        and isinstance(element.tag, str)
        and strip_ns(element.tag) == "svg"
        and element.get("clip-path") not in {None, "none"}
    ):
        clip = nested_svg.attrib.pop("clip-path")
        wrapper = root.makeelement(f"{{{_SVG_NAMESPACE}}}g", {"clip-path": clip})
        renderable = [
            child
            for child in nested_svg
            if isinstance(child.tag, str)
            and strip_ns(child.tag) not in {"clipPath", "defs", "desc", "metadata", "title"}
        ]
        if renderable:
            insert_at = min(nested_svg.index(child) for child in renderable)
            for child in renderable:
                wrapper.append(child)
            nested_svg.insert(insert_at, wrapper)

    by_id = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }

    def raw_subtree_paths(element: Any, inherited: Affine2D) -> tuple[SVGPath, ...]:
        tag = strip_ns(element.tag)
        transform = _element_transform(element, inherited)
        if tag in geometry_tags:
            shape = cast(SVGPath, from_element(element).as_path())
            shape.fill_rule = shape.clip_rule
            return (shape.apply_transform(transform),)
        paths: list[SVGPath] = []
        for child in element:
            if not isinstance(child.tag, str) or strip_ns(child.tag) in {
                "clipPath",
                "defs",
                "desc",
                "metadata",
                "title",
            }:
                continue
            paths.extend(raw_subtree_paths(child, transform))
        return tuple(paths)

    def local_bbox(element: Any) -> Rect | None:
        if strip_ns(element.tag) in geometry_tags:
            try:
                return cast(Rect, from_element(element).bounding_box())
            except Exception:
                return None
        paths: list[SVGPath] = []
        for child in element:
            if isinstance(child.tag, str):
                paths.extend(raw_subtree_paths(child, Affine2D.identity()))
        boxes = tuple(path.bounding_box() for path in paths if _path_has_area(path))
        if not boxes:
            return None
        result = boxes[0]
        for box in boxes[1:]:
            result = result.union(box)
        return result

    def union_all(paths: tuple[SVGPath, ...]) -> SVGPath | None:
        result: SVGPath | None = None
        for path in paths:
            canonical = SVGPath.from_commands(
                svg_pathops.union([path.as_cmd_seq()], [path.fill_rule])
            )
            canonical.fill_rule = "nonzero"
            if _path_has_area(canonical):
                result = _union_paths(result, canonical)
        return result

    def object_bbox_clip_is_inert(identifier: str, target_box: Rect | None) -> bool:
        clip = by_id.get(identifier)
        return (
            clip is not None
            and strip_ns(clip.tag) == "clipPath"
            and clip.get("clipPathUnits", "userSpaceOnUse") == "objectBoundingBox"
            and (target_box is None or target_box.w == 0 or target_box.h == 0)
        )

    def resolve_clip(
        identifier: str,
        target_box: Rect | None,
        inherited: Affine2D,
        stack: frozenset[str],
    ) -> SVGPath | None:
        if identifier in stack:
            raise IconFontError(
                "SVG_CLIP_CYCLE",
                "Clip-path references form a cycle.",
                source=source_id,
            )
        clip = by_id.get(identifier)
        if clip is None or strip_ns(clip.tag) != "clipPath":
            raise IconFontError(
                "SVG_CLIP_REFERENCE_INVALID",
                f"Clip target {identifier!r} is not a clipPath.",
                source=source_id,
            )
        units = clip.get("clipPathUnits", "userSpaceOnUse")
        units_transform = Affine2D.identity()
        if units == "objectBoundingBox":
            if target_box is None or target_box.w == 0 or target_box.h == 0:
                return None
            units_transform = Affine2D.rect_to_rect(
                Rect(0, 0, 1, 1),
                target_box,
            )
        elif units != "userSpaceOnUse":
            raise IconFontError(
                "SVG_CLIP_UNITS_INVALID",
                f"clipPathUnits={units!r} is invalid.",
                source=source_id,
            )
        clip_transform = (
            Affine2D.fromstring(clip.get("transform"))
            if clip.get("transform")
            else Affine2D.identity()
        )
        transform = Affine2D.compose_ltr((units_transform, clip_transform, inherited))

        def clipped_subtree(element: Any, parent_transform: Affine2D) -> SVGPath | None:
            tag = strip_ns(element.tag)
            element_transform = _element_transform(element, parent_transform)
            if tag in geometry_tags:
                raw = cast(SVGPath, from_element(element).as_path())
                raw.fill_rule = raw.clip_rule
                path = raw.apply_transform(element_transform)
                nested = element.get("clip-path")
                if nested and nested != "none":
                    nested_identifier = _clip_reference(nested, source_id)
                    raw_box = raw.bounding_box()
                    if object_bbox_clip_is_inert(nested_identifier, raw_box):
                        return path
                    nested_clip = resolve_clip(
                        nested_identifier,
                        raw_box,
                        element_transform,
                        stack | {identifier},
                    )
                    if nested_clip is None:
                        return None
                    return _intersection_paths(path, nested_clip)
                return path

            children = tuple(
                result
                for child in element
                if isinstance(child.tag, str)
                if (result := clipped_subtree(child, element_transform)) is not None
            )
            group_path = union_all(children)
            nested = element.get("clip-path")
            if group_path is not None and nested and nested != "none":
                nested_identifier = _clip_reference(nested, source_id)
                group_box = local_bbox(element)
                if object_bbox_clip_is_inert(nested_identifier, group_box):
                    return group_path
                nested_clip = resolve_clip(
                    nested_identifier,
                    group_box,
                    element_transform,
                    stack | {identifier},
                )
                if nested_clip is None:
                    return None
                return _intersection_paths(group_path, nested_clip)
            return group_path

        result = union_all(
            tuple(
                path
                for child in clip
                if isinstance(child.tag, str)
                if (path := clipped_subtree(child, transform)) is not None
            )
        )
        outer_clip = clip.get("clip-path")
        if result is not None and outer_clip and outer_clip != "none":
            nested = resolve_clip(
                _clip_reference(outer_clip, source_id),
                result.bounding_box(),
                inherited,
                stack | {identifier},
            )
            if nested is None:
                return None
            result = _intersection_paths(result, nested)
        return result

    definitions = next(
        (child for child in root if isinstance(child.tag, str) and strip_ns(child.tag) == "defs"),
        None,
    )
    if definitions is None:
        definitions = root.makeelement(f"{{{_SVG_NAMESPACE}}}defs")
        root.insert(0, definitions)
    used_ids = set(by_id)
    generated_count = 0
    targets = tuple(
        element
        for element in root.iter()
        if isinstance(element.tag, str)
        and not _has_ancestor(element, "clipPath")
        and element.get("clip-path") not in {None, "none"}
    )
    for target in targets:
        clip_value = target.attrib.pop("clip-path")
        clip_identifier = _clip_reference(clip_value, source_id)
        target_box = local_bbox(target)
        if object_bbox_clip_is_inert(clip_identifier, target_box):
            continue
        path = resolve_clip(
            clip_identifier,
            target_box,
            Affine2D.identity(),
            frozenset(),
        )
        if path is None:
            target.set("display", "none")
            continue
        generated_count += 1
        identifier = f"__canonical_clip_{generated_count}"
        while identifier in used_ids:
            generated_count += 1
            identifier = f"__canonical_clip_{generated_count}"
        used_ids.add(identifier)
        canonical_clip = root.makeelement(
            f"{{{_SVG_NAMESPACE}}}clipPath",
            {"id": identifier, "clipPathUnits": "userSpaceOnUse"},
        )
        canonical_path = root.makeelement(
            f"{{{_SVG_NAMESPACE}}}path",
            {"clip-rule": "nonzero", "d": path.d},
        )
        canonical_clip.append(canonical_path)
        definitions.append(canonical_clip)
        target.set("clip-path", f"url(#{identifier})")
        command_count = sum(1 for _ in path)
        if command_count > config.max_path_commands:
            raise IconFontError(
                "SVG_CLIP_EXPANSION_LIMIT",
                "Canonical clip geometry exceeds the path-command limit.",
                source=source_id,
            )


def _path_length_upper_bound(path: SVGPath) -> tuple[float, int]:
    current = (0.0, 0.0)
    start = current
    length = 0.0
    segments = 0

    def distance(left: tuple[float, float], right: tuple[float, float]) -> float:
        return math.hypot(right[0] - left[0], right[1] - left[1])

    for command, arguments in path.as_cmd_seq():
        if command == "M":
            current = (arguments[0], arguments[1])
            start = current
        elif command == "L":
            end = (arguments[0], arguments[1])
            length += distance(current, end)
            current = end
            segments += 1
        elif command == "Q":
            control = (arguments[0], arguments[1])
            end = (arguments[2], arguments[3])
            length += distance(current, control) + distance(control, end)
            current = end
            segments += 1
        elif command == "C":
            first = (arguments[0], arguments[1])
            second = (arguments[2], arguments[3])
            end = (arguments[4], arguments[5])
            length += distance(current, first) + distance(first, second) + distance(second, end)
            current = end
            segments += 1
        elif command == "Z":
            length += distance(current, start)
            current = start
            segments += 1
        else:
            raise IconFontError(
                "SVG_DASH_ANALYSIS_FAILED",
                f"Unexpected canonical path command {command!r} during dash analysis.",
            )
    return length, segments


def _resolved_bounded_length(
    value: str,
    basis: float,
    source_id: str,
    *,
    feature: str,
    unrepresentable_code: str,
    invalid_code: str,
    label: str,
) -> float:
    match = _CSS_LENGTH_TOKEN.fullmatch(value.strip())
    if match is None:
        dimension = _CSS_DIMENSION_TOKEN.fullmatch(value.strip())
        unit = dimension.group(2).casefold() if dimension and dimension.group(2) else ""
        lowered = value.strip().casefold()
        if unit in _RELATIVE_LENGTH_UNITS or lowered.startswith(
            ("calc(", "clamp(", "env(", "max(", "min(", "var(")
        ):
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                feature,
                unrepresentable_code,
                f"{label}={value!r} depends on a wider CSS length environment.",
                source=source_id,
            )
        raise IconFontError(
            invalid_code,
            f"{label}={value!r} is not a valid supported CSS length.",
            source=source_id,
        )
    number = float(match.group(1))
    unit = (match.group(2) or "").casefold()
    result = number * (_ABSOLUTE_LENGTH_SCALE.get(unit, 1.0))
    if unit == "%":
        result = number * basis / 100
    if not math.isfinite(result):
        raise IconFontError(
            invalid_code,
            f"{label} must resolve to a finite length.",
            source=source_id,
        )
    return result


def _viewport_length(
    value: str,
    basis: float,
    name: str,
    source_id: str,
    *,
    nonnegative: bool,
) -> float:
    result = _resolved_bounded_length(
        value,
        basis,
        source_id,
        feature="viewport-relative-length",
        unrepresentable_code="SVG_VIEWPORT_LENGTH_UNREPRESENTABLE",
        invalid_code="SVG_VIEWPORT_LENGTH_INVALID",
        label=name,
    )
    if nonnegative and result < 0:
        raise IconFontError(
            "SVG_VIEWPORT_LENGTH_INVALID",
            f"{name} must resolve to a nonnegative length.",
            source=source_id,
        )
    return result


def _viewport_dimensions(
    element: Any, fallback: tuple[float, float], source_id: str
) -> tuple[float, float]:
    view_box = element.get("viewBox")
    if view_box is not None:
        parts = tuple(part for part in re.split(r"[\s,]+", view_box.strip()) if part)
        if len(parts) != 4:
            raise IconFontError(
                "SVG_VIEWBOX_INVALID",
                "A viewBox must contain four finite numbers.",
                source=source_id,
            )
        try:
            values = tuple(float(part) for part in parts)
        except ValueError as error:
            raise IconFontError(
                "SVG_VIEWBOX_INVALID",
                "A viewBox must contain four finite numbers.",
                source=source_id,
            ) from error
        if not all(math.isfinite(item) for item in values) or values[2] < 0 or values[3] < 0:
            raise IconFontError(
                "SVG_VIEWBOX_INVALID",
                "A viewBox must have finite, nonnegative dimensions.",
                source=source_id,
            )
        return values[2], values[3]
    width = _viewport_length(
        element.get("width", "100%"),
        fallback[0],
        "nested SVG width",
        source_id,
        nonnegative=True,
    )
    height = _viewport_length(
        element.get("height", "100%"),
        fallback[1],
        "nested SVG height",
        source_id,
        nonnegative=True,
    )
    return width, height


def _normalize_use_lengths(svg: SVG, source_id: str) -> None:
    root_view_box = _finite_view_box(svg.view_box(), source_id)

    def visit(element: Any, viewport: tuple[float, float]) -> None:
        tag = strip_ns(element.tag)
        current_viewport = viewport
        if element is not svg.svg_root and tag == "svg":
            current_viewport = _viewport_dimensions(element, viewport, source_id)
        if tag == "use":
            for name, basis, default, nonnegative in (
                ("x", current_viewport[0], "0", False),
                ("y", current_viewport[1], "0", False),
                ("width", current_viewport[0], None, True),
                ("height", current_viewport[1], None, True),
            ):
                raw = element.get(name, default)
                if raw is None:
                    continue
                resolved = _viewport_length(
                    raw,
                    basis,
                    f"use {name}",
                    source_id,
                    nonnegative=nonnegative,
                )
                element.set(name, f"{resolved:.12g}")
        for child in element:
            if isinstance(child.tag, str):
                visit(child, current_viewport)

    visit(svg.svg_root, (root_view_box.w, root_view_box.h))


def _absolute_dash_value(value: str, basis: float, source_id: str) -> str:
    result = _resolved_bounded_length(
        value,
        basis,
        source_id,
        feature="relative-dash-length",
        unrepresentable_code="SVG_DASH_LENGTH_UNREPRESENTABLE",
        invalid_code="SVG_DASH_INVALID",
        label="dash length",
    )
    return f"{result:.12g}"


def _absolute_dash_array(value: str, basis: float, source_id: str) -> str:
    if value.strip().casefold() == "none":
        return "none"
    token = _CSS_DIMENSION_TOKEN.pattern
    if re.fullmatch(rf"\s*{token}(?:(?:\s*,\s*|\s+){token})*\s*", value) is None:
        if any(
            function in value.casefold()
            for function in ("calc(", "clamp(", "env(", "max(", "min(", "var(")
        ):
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "relative-dash-length",
                "SVG_DASH_LENGTH_UNREPRESENTABLE",
                "stroke-dasharray requires a wider CSS length environment.",
                source=source_id,
            )
        raise IconFontError(
            "SVG_DASH_INVALID",
            f"stroke-dasharray={value!r} is malformed.",
            source=source_id,
        )
    return " ".join(
        _absolute_dash_value(match.group(0), basis, source_id)
        for match in _CSS_DIMENSION_TOKEN.finditer(value)
    )


def _normalize_viewport_relative_lengths(svg: SVG, source_id: str) -> None:
    root_view_box = _finite_view_box(svg.view_box(), source_id)
    geometry_tags = {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}
    length_bases = {
        "circle": {"cx": "x", "cy": "y", "r": "d"},
        "ellipse": {"cx": "x", "cy": "y", "rx": "x", "ry": "y"},
        "line": {"x1": "x", "x2": "x", "y1": "y", "y2": "y"},
        "rect": {"height": "y", "rx": "x", "ry": "y", "width": "x", "x": "x", "y": "y"},
    }

    def visit(
        element: Any,
        inherited_dash: str,
        inherited_offset: str,
        inherited_stroke_width: str,
        viewport: tuple[float, float],
    ) -> None:
        tag = strip_ns(element.tag)
        current_viewport = viewport
        if element is not svg.svg_root and tag == "svg":
            for name, basis, default, nonnegative in (
                ("x", viewport[0], "0", False),
                ("y", viewport[1], "0", False),
                ("width", viewport[0], "100%", True),
                ("height", viewport[1], "100%", True),
            ):
                resolved = _viewport_length(
                    element.get(name, default),
                    basis,
                    f"nested SVG {name}",
                    source_id,
                    nonnegative=nonnegative,
                )
                element.set(name, f"{resolved:.12g}")
            current_viewport = _viewport_dimensions(element, viewport, source_id)
        elif tag == "marker":
            width = _symbol_length(element.get("markerWidth", "3"), "markerWidth", source_id)
            height = _symbol_length(element.get("markerHeight", "3"), "markerHeight", source_id)
            marker_box = _marker_view_box(element, width, height, source_id)
            current_viewport = marker_box.w, marker_box.h
        elif tag == "clipPath" and element.get("clipPathUnits", "userSpaceOnUse") == (
            "objectBoundingBox"
        ):
            # Object-bounding-box clip content lives in a normalized 1x1
            # coordinate system. Percentages must resolve there before the clip
            # is mapped onto each target's actual bounds.
            current_viewport = (1.0, 1.0)

        dash = _computed_keyword(element.get("stroke-dasharray"), inherited_dash, "none")
        offset = _computed_keyword(element.get("stroke-dashoffset"), inherited_offset, "0")
        stroke_width = _computed_keyword(element.get("stroke-width"), inherited_stroke_width, "1")
        if tag in geometry_tags:
            basis = math.hypot(*current_viewport) / math.sqrt(2)
            bases = {"x": current_viewport[0], "y": current_viewport[1], "d": basis}
            for name, axis in length_bases.get(tag, {}).items():
                if name not in element.attrib:
                    continue
                resolved = _resolved_bounded_length(
                    element.attrib[name],
                    bases[axis],
                    source_id,
                    feature="geometry-relative-length",
                    unrepresentable_code="SVG_GEOMETRY_LENGTH_UNREPRESENTABLE",
                    invalid_code="SVG_LENGTH_INVALID",
                    label=f"<{tag}> {name}",
                )
                if (tag, name) in _NONNEGATIVE_GEOMETRY_LENGTHS and resolved < 0:
                    raise IconFontError(
                        "SVG_LENGTH_INVALID",
                        f"<{tag}> {name} must resolve to a nonnegative length.",
                        source=source_id,
                    )
                element.set(name, f"{resolved:.12g}")
            resolved_stroke_width = _resolved_bounded_length(
                stroke_width,
                basis,
                source_id,
                feature="relative-stroke-length",
                unrepresentable_code="SVG_STROKE_LENGTH_UNREPRESENTABLE",
                invalid_code="SVG_LENGTH_INVALID",
                label="stroke-width",
            )
            if resolved_stroke_width < 0:
                raise IconFontError(
                    "SVG_LENGTH_INVALID",
                    "stroke-width must resolve to a nonnegative length.",
                    source=source_id,
                )
            element.set("stroke-width", f"{resolved_stroke_width:.12g}")
            painted_stroke = (
                element.get("stroke", "none").casefold() != "none" and resolved_stroke_width > 0
            )
            if painted_stroke:
                element.set("stroke-dasharray", _absolute_dash_array(dash, basis, source_id))
                element.set("stroke-dashoffset", _absolute_dash_value(offset, basis, source_id))
            else:
                element.set("stroke-dasharray", "none")
                element.set("stroke-dashoffset", "0")
                element.attrib.pop("pathLength", None)
                element.attrib.pop("vector-effect", None)

        for child in element:
            if isinstance(child.tag, str):
                visit(child, dash, offset, stroke_width, current_viewport)

        if tag not in geometry_tags:
            element.attrib.pop("stroke-dasharray", None)
            element.attrib.pop("stroke-dashoffset", None)

    visit(svg.svg_root, "none", "0", "1", (root_view_box.w, root_view_box.h))


def _dash_pattern(value: str, source_id: str) -> tuple[float, ...]:
    text = value.strip()
    if text.casefold() == "none":
        return ()
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    if re.fullmatch(rf"\s*{number}(?:(?:\s*,\s*|\s+){number})*\s*", text) is None:
        raise IconFontError(
            "SVG_DASH_INVALID",
            f"stroke-dasharray={value!r} is not a numeric dash list.",
            source=source_id,
        )
    values = tuple(float(token) for token in re.findall(number, text))
    if not values or any(not math.isfinite(item) or item < 0 for item in values):
        raise IconFontError(
            "SVG_DASH_INVALID",
            "Dash lengths must be finite and nonnegative.",
            source=source_id,
        )
    if sum(values) == 0:
        return ()
    return values + values if len(values) % 2 else values


def _normalize_dash_semantics(svg: SVG, source_id: str, config: BuildConfig) -> None:
    """Prove painted dash expansion is bounded before invoking the Skia stroker."""

    for traversal in svg.depth_first(resolve_clip_paths=False):
        element = traversal.element
        raw_path_length = element.get("pathLength")
        if raw_path_length is None:
            continue
        try:
            path_length = float(raw_path_length)
        except ValueError as error:
            raise IconFontError(
                "SVG_PATH_LENGTH_INVALID",
                "pathLength must be a finite positive number.",
                source=source_id,
            ) from error
        if not math.isfinite(path_length) or path_length <= 0:
            raise IconFontError(
                "SVG_PATH_LENGTH_INVALID",
                "pathLength must be a finite positive number.",
                source=source_id,
            )
        if traversal.is_shape():
            shape = traversal.shape()
            if shape.stroke != "none" and shape.stroke_dasharray != "none":
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "calibrated-dash-lengths",
                    "SVG_PATH_LENGTH_DASH_UNREPRESENTABLE",
                    "pathLength-calibrated dashes are outside the current distance profile.",
                    source=source_id,
                )
        del element.attrib["pathLength"]

    estimated_commands = 0
    for traversal in svg.depth_first(resolve_clip_paths=False):
        if not traversal.is_shape():
            continue
        shape = traversal.shape()
        if shape.stroke.casefold() == "none" or float(shape.stroke_width) == 0:
            continue
        pattern = _dash_pattern(shape.stroke_dasharray, source_id)
        if not pattern:
            shape.stroke_dasharray = "none"
            continue
        if not math.isfinite(float(shape.stroke_dashoffset)):
            raise IconFontError(
                "SVG_DASH_INVALID",
                "stroke-dashoffset must be finite.",
                source=source_id,
            )
        length, segment_count = _path_length_upper_bound(shape.as_path())
        cycles = math.ceil(length / sum(pattern)) + 2
        estimated_commands += max(1, segment_count) * 8
        estimated_commands += cycles * len(pattern) * 8
        if estimated_commands > config.max_path_commands:
            raise IconFontError(
                "SVG_DASH_EXPANSION_LIMIT",
                "Dashed stroke expansion exceeds the pre-stroke path-work limit.",
                source=source_id,
                details={
                    "estimatedPathCommands": estimated_commands,
                    "maxPathCommands": config.max_path_commands,
                },
                hint="Increase dash lengths, simplify the centerline, or raise the explicit limit.",
            )


def _normalize_nested_viewports(svg: SVG, source_id: str) -> None:
    zero_viewports: list[Any] = []
    for nested_svg in tuple(
        element
        for element in svg.svg_root.iter()
        if element is not svg.svg_root
        and isinstance(element.tag, str)
        and strip_ns(element.tag) == "svg"
    ):
        width = float(nested_svg.get("width", "0"))
        height = float(nested_svg.get("height", "0"))
        view_box = nested_svg.get("viewBox")
        if view_box is not None:
            parts = tuple(part for part in re.split(r"[\s,]+", view_box.strip()) if part)
            view_box_width, view_box_height = float(parts[2]), float(parts[3])
        else:
            view_box_width, view_box_height = width, height
        if width == 0 or height == 0 or view_box_width == 0 or view_box_height == 0:
            nested_svg.set("display", "none")
            zero_viewports.append(nested_svg)
    if zero_viewports:
        # A zero viewport disables rendering but does not disable definitions
        # inside it. Reuse the resource-boundary-aware display pass so directly
        # painted descendants disappear while referenced resources survive.
        _normalize_visibility_and_display(svg.svg_root, source_id)

    # PicoSVG resolves nested viewport geometry but does not preserve container
    # compositing attributes. Move those attributes to an inner group while the
    # nested user coordinate system still exists, so the viewport transform is
    # subsequently applied to both geometry and its clip/opacity semantics.
    for nested_svg in tuple(
        element
        for element in svg.svg_root.iter()
        if element is not svg.svg_root
        and isinstance(element.tag, str)
        and strip_ns(element.tag) == "svg"
    ):
        container_attributes = {
            name: nested_svg.attrib.pop(name)
            for name in ("clip-path", "opacity")
            if name in nested_svg.attrib
        }
        if not container_attributes:
            continue
        renderable = [
            child
            for child in nested_svg
            if isinstance(child.tag, str)
            and strip_ns(child.tag) not in {"clipPath", "defs", "desc", "metadata", "title"}
        ]
        if not renderable:
            continue
        wrapper = svg.svg_root.makeelement(f"{{{_SVG_NAMESPACE}}}g", container_attributes)
        insert_at = min(nested_svg.index(child) for child in renderable)
        for child in renderable:
            wrapper.append(child)
        nested_svg.insert(insert_at, wrapper)

    for element in svg.svg_root.iter():
        if (
            element is svg.svg_root
            or not isinstance(element.tag, str)
            or strip_ns(element.tag) != "svg"
        ):
            continue
        for name in ("x", "y", "width", "height"):
            value = element.get(name)
            if value is None:
                continue
            try:
                number = float(value)
            except ValueError as error:
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "nested-external-viewport",
                    "SVG_NESTED_VIEWPORT_UNREPRESENTABLE",
                    f"Nested SVG {name}={value!r} depends on an external viewport.",
                    source=source_id,
                ) from error
            if not math.isfinite(number) or (name in {"width", "height"} and number < 0):
                raise IconFontError(
                    "SVG_NESTED_VIEWPORT_INVALID",
                    f"Nested SVG {name} is invalid.",
                    source=source_id,
                )
        overflow = element.get("overflow", "hidden")
        if overflow not in {"hidden", "visible"}:
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "nested-overflow-mode",
                "SVG_NESTED_VIEWPORT_UNREPRESENTABLE",
                f"Nested SVG overflow={overflow!r} is outside the viewport profile.",
                source=source_id,
            )
    svg.resolve_nested_svgs(inplace=True)


def _filled_path_element(
    root: Any,
    path: SVGPath,
    *,
    fill: str,
    opacity: float,
    fill_rule: str = "nonzero",
) -> Any:
    return root.makeelement(
        f"{{{_SVG_NAMESPACE}}}path",
        {
            "d": path.d,
            "fill": fill,
            "fill-opacity": "1",
            "fill-rule": fill_rule,
            "opacity": f"{opacity:.12g}",
            "stroke": "none",
        },
    )


def _normalize_non_scaling_strokes(svg: SVG, source_id: str) -> None:
    root = svg.svg_root
    replacements: list[tuple[Any, Any]] = []

    def visit(element: Any, parent_transform: Affine2D) -> None:
        tag = strip_ns(element.tag)
        local_transform = (
            Affine2D.fromstring(element.get("transform"))
            if element.get("transform")
            else Affine2D.identity()
        )
        if tag in {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect"}:
            effect = element.attrib.pop("vector-effect", "none").strip().casefold()
            if effect == "none":
                return
            if effect != "non-scaling-stroke":
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "vector-effect-mode",
                    "SVG_VECTOR_EFFECT_UNREPRESENTABLE",
                    f"vector-effect={effect!r} is outside the non-scaling-stroke profile.",
                    source=source_id,
                )
            if _has_ancestor(element, "clipPath"):
                return
            if element.get("clip-path") not in {None, "none"}:
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "clipped-non-scaling-stroke",
                    "SVG_VECTOR_EFFECT_CLIP_UNREPRESENTABLE",
                    (
                        "A clipped non-scaling stroke requires joint centerline and clip "
                        "normalization."
                    ),
                    source=source_id,
                )
            shape = from_element(element)
            if shape.stroke == "none" or float(shape.stroke_width) == 0:
                return
            full_transform = Affine2D.compose_ltr((local_transform, parent_transform))
            if full_transform.is_degenerate() or parent_transform.is_degenerate():
                element.set("display", "none")
                return
            group = root.makeelement(f"{{{_SVG_NAMESPACE}}}g")
            identifier = element.get("id")
            if identifier is not None:
                group.set("id", identifier)
            fill_path = cast(SVGPath, shape.as_path()).apply_transform(local_transform)
            if shape.fill != "none" and float(shape.fill_opacity) * float(shape.opacity) > 0:
                group.append(
                    _filled_path_element(
                        root,
                        fill_path,
                        fill=shape.fill,
                        opacity=float(shape.fill_opacity) * float(shape.opacity),
                        fill_rule=shape.fill_rule,
                    )
                )
            centerline = cast(SVGPath, shape.as_path()).apply_transform(full_transform)
            stroke = SVGPath.from_commands(centerline.stroke_commands(svg.tolerance))
            stroke = stroke.apply_transform(parent_transform.inverse())
            if _path_has_area(stroke):
                group.append(
                    _filled_path_element(
                        root,
                        stroke,
                        fill=shape.stroke,
                        opacity=float(shape.stroke_opacity) * float(shape.opacity),
                    )
                )
            group.tail = element.tail
            replacements.append((element, group))
            return

        next_transform = _element_transform(element, parent_transform)
        for child in element:
            if isinstance(child.tag, str):
                visit(child, next_transform)

    visit(root, Affine2D.identity())
    for element, replacement in replacements:
        parent = element.getparent()
        if parent is not None:
            parent.replace(element, replacement)


def _reject_external_url(value: str, source_id: str) -> None:
    for reference in _url_references(value, source_id):
        target = reference.target
        if not target.startswith("#"):
            raise IconFontError(
                "SVG_EXTERNAL_REFERENCE",
                f"External reference {target!r} is forbidden.",
                source=source_id,
            )


def _preflight(svg: SVG, source: SvgSource, config: BuildConfig) -> None:
    root = svg.svg_root
    if root.tag != f"{{{_SVG_NAMESPACE}}}svg":
        raise IconFontError(
            "SVG_ROOT_INVALID",
            "The document root must be an <svg> element.",
            source=source.source_id,
        )
    _enforce_tree_limits(root, source, config)
    _enforce_raw_geometry_budget(root, source.source_id, config)
    # Hard safety validation must finish before any policy-addressable feature can
    # turn the whole icon into a skip. A skipped icon is never a security bypass.
    for element in root.iter():
        if not isinstance(element.tag, str):
            raise IconFontError(
                "SVG_XML_NODE_FORBIDDEN",
                "Processing instructions and entity nodes are forbidden.",
                source=source.source_id,
            )
        if strip_ns(element.tag).casefold() == "script":
            raise IconFontError(
                "SVG_SCRIPT_FORBIDDEN",
                "Script elements are forbidden even inside nonrendering metadata.",
                source=source.source_id,
            )
        if strip_ns(element.tag) in _PAINT_SERVER_ELEMENTS | {"filter", "mask"}:
            _hard_validate_resource_element(element, source.source_id)
        for raw_name, value in element.attrib.items():
            name = strip_ns(raw_name)
            if name.lower().startswith("on"):
                raise IconFontError(
                    "SVG_EVENT_HANDLER_FORBIDDEN",
                    f"Event attribute {name!r} is forbidden.",
                    source=source.source_id,
                )
            _reject_external_url(value, source.source_id)
            if name.casefold() in _CSS_PROPERTIES:
                _hard_validate_presentation_value(name, value, source.source_id)
            if strip_ns(raw_name).lower() == "href" and not value.startswith("#"):
                raise IconFontError(
                    "SVG_EXTERNAL_REFERENCE",
                    f"Reference {value!r} must be a local #fragment.",
                    source=source.source_id,
                )
    _validate_unique_ids(root, source.source_id)
    _canonicalize_href_precedence(root)
    _drop_nonrendering_metadata(root, source.source_id)
    for element in root.iter():
        if not isinstance(element.tag, str):
            raise IconFontError(
                "SVG_XML_NODE_FORBIDDEN",
                "Processing instructions and entity nodes are forbidden.",
                source=source.source_id,
            )
        tag = strip_ns(element.tag)
        if _element_namespace(element.tag) != _SVG_NAMESPACE:
            raise IconFontError(
                "SVG_NAMESPACE_INVALID",
                f"<{tag}> is not in the SVG namespace.",
                source=source.source_id,
            )
        if tag == "script":
            raise IconFontError(
                "SVG_SCRIPT_FORBIDDEN",
                "Script elements are forbidden even when the icon would otherwise be skipped.",
                source=source.source_id,
            )
        if (
            tag not in _SUPPORTED_ELEMENTS
            and tag not in _PAINT_SERVER_ELEMENTS
            and tag not in _FORBIDDEN_ELEMENTS
            and not tag.startswith(("animate", "fe"))
        ):
            raise IconFontError(
                "SVG_ELEMENT_UNSUPPORTED",
                f"Unknown <{tag}> semantics cannot be converted safely.",
                source=source.source_id,
            )
        if tag in {
            "circle",
            "ellipse",
            "line",
            "path",
            "polygon",
            "polyline",
            "rect",
        }:
            _hard_validate_geometry(element, source.source_id)
        if (
            tag in _PAINT_SERVER_ELEMENTS
            or tag in _FORBIDDEN_ELEMENTS
            or tag.startswith(("animate", "fe"))
            or _has_ancestor(element, "linearGradient")
            or _has_ancestor(element, "radialGradient")
            or _has_ancestor(element, "pattern")
        ):
            continue
        for raw_name, value in element.attrib.items():
            name = strip_ns(raw_name)
            lowered = name.lower()
            if lowered in _FORBIDDEN_ATTRIBUTES or lowered in {"class", "style"}:
                continue
            namespace = _attribute_namespace(raw_name)
            is_foreign_metadata = namespace not in {
                None,
                "http://www.w3.org/2000/svg",
                "http://www.w3.org/1999/xlink",
                "http://www.w3.org/XML/1998/namespace",
            }
            is_nonvisual_metadata = lowered.startswith(("aria-", "data-"))
            is_xml_metadata = namespace == "http://www.w3.org/XML/1998/namespace" and lowered in {
                "lang",
                "space",
            }
            if (
                lowered not in _SUPPORTED_ATTRIBUTES
                and not is_foreign_metadata
                and not is_nonvisual_metadata
                and not is_xml_metadata
            ):
                raise IconFontError(
                    "SVG_ATTRIBUTE_UNSUPPORTED",
                    f"Attribute {name!r} has unsupported rendering semantics.",
                    source=source.source_id,
                )
            if lowered in {"color", "fill", "stroke"}:
                _validate_paint(value, source.source_id)
            if lowered in {"fill-opacity", "opacity", "stroke-opacity"}:
                _validate_opacity(value, lowered, source.source_id)
            if lowered == "viewbox":
                _hard_validate_view_box(value, source.source_id)
            if lowered == "transform" and value:
                _hard_validate_transform(value, source.source_id)
            if lowered == "preserveaspectratio":
                try:
                    Affine2D.rect_to_rect(
                        Rect(0, 0, 1, 1),
                        Rect(0, 0, 1, 1),
                        value,
                    )
                except (ValueError, TypeError) as error:
                    raise IconFontError(
                        "SVG_ASPECT_RATIO_INVALID",
                        str(error),
                        source=source.source_id,
                    ) from error
            if tag in {"svg", "use"} and lowered in {"x", "y", "width", "height"}:
                _hard_validate_length_syntax(
                    value,
                    label=f"<{tag}> {lowered}",
                    source_id=source.source_id,
                    nonnegative=lowered in {"width", "height"},
                    invalid_code=(
                        "SVG_ROOT_LENGTH_INVALID"
                        if element is root
                        else "SVG_VIEWPORT_LENGTH_INVALID"
                    ),
                )
            if lowered == "stroke-dasharray":
                _hard_validate_dash_syntax(value, source.source_id, allow_css_wide=True)
            if lowered == "stroke-dashoffset":
                _hard_validate_length_syntax(
                    value,
                    label="stroke-dashoffset",
                    source_id=source.source_id,
                    nonnegative=False,
                    allow_css_wide=True,
                )
            if lowered == "stroke-width":
                _hard_validate_length_syntax(
                    value,
                    label="stroke-width",
                    source_id=source.source_id,
                    nonnegative=True,
                    allow_css_wide=True,
                )
            if lowered == "pathlength":
                try:
                    path_length = float(value)
                except ValueError as error:
                    raise IconFontError(
                        "SVG_PATH_LENGTH_INVALID",
                        "pathLength must be a finite positive number.",
                        source=source.source_id,
                    ) from error
                if not math.isfinite(path_length) or path_length <= 0:
                    raise IconFontError(
                        "SVG_PATH_LENGTH_INVALID",
                        "pathLength must be a finite positive number.",
                        source=source.source_id,
                    )
            if lowered == "clippathunits" and value not in {
                "objectBoundingBox",
                "userSpaceOnUse",
            }:
                raise IconFontError(
                    "SVG_CLIP_UNITS_INVALID",
                    f"clipPathUnits={value!r} is invalid.",
                    source=source.source_id,
                )
            if lowered in {"clip-rule", "fill-rule"} and value.strip().casefold() not in {
                "inherit",
                "initial",
                "evenodd",
                "nonzero",
                "unset",
            }:
                raise IconFontError(
                    "SVG_FILL_RULE_INVALID",
                    f"{name}={value!r} is invalid.",
                    source=source.source_id,
                )
            if lowered == "markerunits" and value not in {
                "strokeWidth",
                "userSpaceOnUse",
            }:
                raise IconFontError(
                    "SVG_MARKER_UNITS_INVALID",
                    f"markerUnits={value!r} is invalid.",
                    source=source.source_id,
                )
            if tag == "marker" and lowered in {
                "markerheight",
                "markerwidth",
                "refx",
                "refy",
            }:
                marker_keywords = (
                    {"center", "left", "right"}
                    if lowered == "refx"
                    else {"bottom", "center", "top"}
                    if lowered == "refy"
                    else set()
                )
                if value.strip().casefold() not in marker_keywords:
                    _hard_validate_length_syntax(
                        value,
                        label=f"marker {name}",
                        source_id=source.source_id,
                        nonnegative=lowered in {"markerheight", "markerwidth"},
                    )
            if lowered == "orient":
                orient = value.strip().casefold()
                if orient not in {"auto", "auto-start-reverse"}:
                    angle = re.fullmatch(rf"({_NUMBER_TOKEN.pattern})(deg|grad|rad|turn)?", orient)
                    if angle is None or not math.isfinite(float(angle.group(1))):
                        raise IconFontError(
                            "SVG_MARKER_ORIENTATION_INVALID",
                            f"Marker orient={value!r} is invalid.",
                            source=source.source_id,
                        )
            if tag == "text" and lowered in {"dx", "dy", "x", "y"}:
                _hard_validate_length_list(
                    value,
                    label=f"text {lowered}",
                    source_id=source.source_id,
                    nonnegative=False,
                )
            if tag == "text" and lowered in {"font-size", "textlength"}:
                _hard_validate_length_syntax(
                    value,
                    label=f"text {name}",
                    source_id=source.source_id,
                    nonnegative=True,
                    allow_css_wide=True,
                )
            if tag == "text" and lowered == "rotate":
                number = _NUMBER_TOKEN.pattern
                if re.fullmatch(rf"\s*{number}(?:(?:\s*,\s*|\s+){number})*\s*", value) is None:
                    raise IconFontError(
                        "SVG_TEXT_ROTATION_INVALID",
                        f"Text rotate={value!r} is malformed.",
                        source=source.source_id,
                    )
            if (
                namespace == "http://www.w3.org/XML/1998/namespace"
                and lowered == "space"
                and value not in {"default", "preserve"}
            ):
                raise IconFontError(
                    "SVG_TEXT_WHITESPACE_INVALID",
                    f"xml:space={value!r} must be 'default' or 'preserve'.",
                    source=source.source_id,
                )
    _validate_local_references(root, source.source_id)
    _validate_reference_target_types(root, source.source_id)
    _validate_paint_server_cycles(root, source.source_id)
    _enforce_expansion_budget(root, source.source_id, config)
    css_targets = {
        identifier: element
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }

    def hard_validate_css_value(name: str, value: str) -> None:
        _hard_validate_presentation_value(name, value, source.source_id)
        _hard_validate_reference_property(name, value, css_targets, source.source_id)

    materialize_css(
        root,
        source_id=source.source_id,
        supported_properties=_CSS_PROPERTIES,
        max_rules=config.max_expanded_elements,
        max_work=config.max_expanded_bytes,
        hard_validate_value=hard_validate_css_value,
    )
    _validate_local_references(root, source.source_id)
    _validate_reference_target_types(root, source.source_id)
    _validate_paint_server_cycles(root, source.source_id)
    _normalize_transforms(root, source.source_id)
    _normalize_noop_effects(root)
    protected_render_targets = _referenced_render_targets(root, source.source_id)
    _prune_display_none_render_branches(root, protected_render_targets)
    _prune_zero_opacity_render_branches(root, source.source_id, protected_render_targets)
    _prune_unreachable_definitions(root, source.source_id)
    feature_errors: dict[tuple[str, str], SvgFeatureError] = {}

    def unrepresentable(feature: str, code: str, message: str, hint: str | None = None) -> None:
        feature_errors.setdefault(
            (code, feature),
            SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                feature,
                code,
                message,
                source=source.source_id,
                hint=hint,
            ),
        )

    for element in root.iter():
        if not isinstance(element.tag, str):
            raise IconFontError(
                "SVG_XML_NODE_FORBIDDEN",
                "Processing instructions and entity nodes are forbidden.",
                source=source.source_id,
            )
        tag = strip_ns(element.tag)
        if _element_namespace(element.tag) != _SVG_NAMESPACE:
            raise IconFontError(
                "SVG_NAMESPACE_INVALID",
                f"<{tag}> is not in the SVG namespace.",
                source=source.source_id,
            )
        if tag == "script":
            raise IconFontError(
                "SVG_SCRIPT_FORBIDDEN",
                "Script elements are forbidden even when the icon would otherwise be skipped.",
                source=source.source_id,
            )
        if tag in _FORBIDDEN_ELEMENTS or tag.startswith(("animate", "fe")):
            feature = "filter" if tag.startswith("fe") else tag
            unrepresentable(
                feature,
                "SVG_ELEMENT_UNREPRESENTABLE",
                f"<{tag}> has no supported static monochrome outline conversion.",
                "Remove the feature, outline it explicitly, or enable unrepresentable=skip.",
            )
            continue
        if tag not in _SUPPORTED_ELEMENTS and tag not in _PAINT_SERVER_ELEMENTS:
            raise IconFontError(
                "SVG_ELEMENT_UNSUPPORTED",
                f"Unknown <{tag}> semantics cannot be converted safely.",
                source=source.source_id,
            )
        if (
            tag in _PAINT_SERVER_ELEMENTS
            or _has_ancestor(element, "linearGradient")
            or _has_ancestor(element, "radialGradient")
            or _has_ancestor(element, "pattern")
        ):
            continue
        xlink_href = f"{{{xlinkns()}}}href"
        bare_href = element.attrib.get("href")
        if bare_href is not None:
            # SVG 2 defines bare href as authoritative; xlink:href is only fallback.
            element.attrib[xlink_href] = bare_href
            del element.attrib["href"]
        for raw_name, value in tuple(element.attrib.items()):
            name = strip_ns(raw_name)
            lowered = name.lower()
            if lowered in _FORBIDDEN_ATTRIBUTES:
                unrepresentable(
                    lowered,
                    "SVG_ATTRIBUTE_UNREPRESENTABLE",
                    f"Attribute {name!r} has no supported static monochrome conversion.",
                )
                continue
            namespace = _attribute_namespace(raw_name)
            is_foreign_metadata = namespace not in {
                None,
                "http://www.w3.org/2000/svg",
                "http://www.w3.org/1999/xlink",
                "http://www.w3.org/XML/1998/namespace",
            }
            is_nonvisual_metadata = lowered.startswith(("aria-", "data-"))
            is_xml_metadata = namespace == "http://www.w3.org/XML/1998/namespace" and lowered in {
                "lang",
                "space",
            }
            if (
                lowered not in _SUPPORTED_ATTRIBUTES
                and not is_foreign_metadata
                and not is_nonvisual_metadata
                and not is_xml_metadata
            ):
                raise IconFontError(
                    "SVG_ATTRIBUTE_UNSUPPORTED",
                    f"Attribute {name!r} has unsupported rendering semantics.",
                    source=source.source_id,
                )
            if lowered in {"color", "fill", "stroke"}:
                _validate_paint(value, source.source_id)
            if lowered in {"fill-opacity", "opacity", "stroke-opacity"}:
                _validate_opacity(value, lowered, source.source_id)
    _validate_local_references(root, source.source_id)
    _enforce_expansion_budget(root, source.source_id, config)
    if feature_errors:
        errors = tuple(feature_errors.values())
        if len(errors) == 1:
            raise errors[0]
        raise SvgFeatureBatchError(errors)


def _finite_view_box(view_box: Rect | None, source_id: str) -> Rect:
    if view_box is None:
        raise IconFontError(
            "SVG_VIEWBOX_REQUIRED",
            "A numeric viewBox, or numeric width and height, is required.",
            source=source_id,
        )
    values = (view_box.x, view_box.y, view_box.w, view_box.h)
    if not all(math.isfinite(value) for value in values):
        raise IconFontError(
            "SVG_VIEWBOX_NONFINITE",
            "The SVG viewport must contain only finite numbers.",
            source=source_id,
        )
    if view_box.w < 0 or view_box.h < 0:
        raise IconFontError(
            "SVG_VIEWBOX_NONPOSITIVE",
            "The SVG viewport width and height cannot be negative.",
            source=source_id,
        )
    if view_box.w == 0 or view_box.h == 0:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "empty-viewport",
            "SVG_EMPTY_OUTLINE",
            "A zero-sized SVG viewport intentionally renders no icon outline.",
            source=source_id,
        )
    return view_box


def _numeric_root_length(value: str | None, fallback: float, name: str, source_id: str) -> float:
    if value is None:
        return fallback
    match = _CSS_LENGTH_TOKEN.fullmatch(value.strip())
    if match is not None and match.group(2) == "%":
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "root-external-viewport",
            "SVG_ROOT_VIEWPORT_UNREPRESENTABLE",
            f"Root {name}={value!r} depends on the embedding viewport.",
            source=source_id,
            hint=(
                "Provide numeric or absolute root dimensions. Remove responsive dimensions "
                "only if the viewBox itself is the intended icon canvas."
            ),
        )
    result = _resolved_bounded_length(
        value,
        fallback,
        source_id,
        feature="root-external-viewport",
        unrepresentable_code="SVG_ROOT_VIEWPORT_UNREPRESENTABLE",
        invalid_code="SVG_ROOT_LENGTH_INVALID",
        label=f"root {name}",
    )
    if not math.isfinite(result) or result < 0:
        raise IconFontError(
            "SVG_ROOT_LENGTH_INVALID",
            f"Root {name} must be a finite nonnegative number in user units.",
            source=source_id,
        )
    if result == 0:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "empty-viewport",
            "SVG_EMPTY_OUTLINE",
            f"A zero root {name} intentionally renders no icon outline.",
            source=source_id,
        )
    return result


def _normalize_root_viewport(svg: SVG, source_id: str) -> None:
    """Materialize root viewBox, preserveAspectRatio, and transform into geometry."""

    root = svg.svg_root
    source_view_box = _finite_view_box(svg.view_box(), source_id)
    width = _numeric_root_length(root.get("width"), source_view_box.w, "width", source_id)
    height = _numeric_root_length(root.get("height"), source_view_box.h, "height", source_id)
    viewport = Rect(0, 0, width, height)
    preserve = root.attrib.pop("preserveAspectRatio", "xMidYMid")
    try:
        viewport_transform = Affine2D.rect_to_rect(source_view_box, viewport, preserve)
        root_transform_text = root.attrib.pop("transform", "")
        root_transform = (
            Affine2D.fromstring(root_transform_text) if root_transform_text else Affine2D.identity()
        )
    except (ValueError, TypeError) as error:
        raise IconFontError(
            "SVG_ROOT_TRANSFORM_INVALID",
            str(error),
            source=source_id,
        ) from error
    combined = Affine2D.compose_ltr((viewport_transform, root_transform))
    if combined.is_degenerate():
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "degenerate-root-transform",
            "SVG_EMPTY_OUTLINE",
            "The root viewport transform collapses the icon to zero area.",
            source=source_id,
        )

    definition_tags = {"clipPath", "defs", "desc", "metadata", "title"}
    renderable = [
        child
        for child in root
        if isinstance(child.tag, str) and strip_ns(child.tag) not in definition_tags
    ]
    root_opacity = root.attrib.pop("opacity", None)
    root_clip = root.attrib.pop("clip-path", None)
    if renderable and (
        combined != Affine2D.identity() or root_opacity is not None or root_clip is not None
    ):
        group = root.makeelement(f"{{{_SVG_NAMESPACE}}}g")
        if combined != Affine2D.identity():
            group.set("transform", combined.tostring())
        if root_opacity is not None:
            group.set("opacity", root_opacity)
        if root_clip is not None:
            group.set("clip-path", root_clip)
        insert_at = min(root.index(child) for child in renderable)
        for child in renderable:
            group.append(child)
        root.insert(insert_at, group)

    root.set("viewBox", f"0 0 {width:.12g} {height:.12g}")
    root.set("width", f"{width:.12g}")
    root.set("height", f"{height:.12g}")


def _flatten_fractional_opacity_groups(root: Any, source_id: str) -> None:
    """Collapse post-PicoSVG opacity groups into provenance-carrying partial paths."""

    groups = tuple(
        element
        for element in root.iter()
        if isinstance(element.tag, str) and strip_ns(element.tag) == "g"
    )
    for group in reversed(groups):
        try:
            opacity = float(group.get("opacity", "1"))
        except ValueError as error:
            raise IconFontError(
                "SVG_GROUP_COMPOSITING_INVALID",
                "Canonical group opacity must be numeric.",
                source=source_id,
            ) from error
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise IconFontError(
                "SVG_GROUP_COMPOSITING_INVALID",
                "Canonical group opacity must be finite and between zero and one.",
                source=source_id,
            )
        parent = group.getparent()
        if parent is None:
            raise IconFontError(
                "SVG_GROUP_COMPOSITING_UNSUPPORTED",
                "A canonical opacity group has no parent.",
                source=source_id,
            )
        if opacity == 0:
            parent.remove(group)
            continue
        if opacity == 1:
            raise IconFontError(
                "SVG_GROUP_COMPOSITING_UNSUPPORTED",
                "A non-opacity group remained after canonicalization.",
                source=source_id,
            )

        union: SVGPath | None = None
        lossy_bits = _LOSSY_GROUP_OPACITY
        for child in group:
            if not isinstance(child.tag, str) or strip_ns(child.tag) != "path":
                raise IconFontError(
                    "SVG_GROUP_COMPOSITING_UNSUPPORTED",
                    "An opacity group retained non-path content after canonicalization.",
                    source=source_id,
                )
            shape = cast(SVGPath, from_element(child).as_path())
            if (
                shape.fill.casefold() == "none"
                or float(shape.opacity) * float(shape.fill_opacity) <= 0
            ):
                continue
            if shape.stroke.casefold() != "none" or shape.transform or shape.clip_path:
                raise IconFontError(
                    "SVG_GROUP_COMPOSITING_UNSUPPORTED",
                    "Opacity-group geometry was not reduced to untransformed fills.",
                    source=source_id,
                )
            lossy_bits |= _lossy_paint_bits(shape.fill)
            canonical = SVGPath.from_commands(
                svg_pathops.union([shape.as_cmd_seq()], [shape.fill_rule])
            )
            canonical.fill_rule = "nonzero"
            if _path_has_area(canonical):
                union = _union_paths(union, canonical)

        if union is None:
            parent.remove(group)
            continue
        lossy_bits &= ~_LOSSY_FRACTIONAL_ALPHA
        replacement = root.makeelement(
            f"{{{_SVG_NAMESPACE}}}path",
            {
                "d": union.d,
                "fill": _lossy_paint(lossy_bits),
                "fill-opacity": "1",
                "fill-rule": "nonzero",
                "opacity": "0.5",
                "stroke": "none",
            },
        )
        replacement.tail = group.tail
        parent.replace(group, replacement)


def _assert_canonical_shape(shape: Any, source_id: str) -> SVGPath:
    if not isinstance(shape, SVGPath):
        raise IconFontError(
            "SVG_CANONICALIZATION_INCOMPLETE",
            f"PicoSVG left an unsupported {type(shape).__name__} shape.",
            source=source_id,
        )
    if shape.fill.casefold() == "none" or shape.stroke.casefold() != "none":
        raise IconFontError(
            "SVG_CANONICALIZATION_INCOMPLETE",
            "A painted shape was not reduced to a filled outline.",
            source=source_id,
        )
    if shape.fill.lstrip().casefold().startswith("url("):
        raise IconFontError(
            "SVG_PAINT_SERVER_UNSUPPORTED",
            "Gradients and patterns cannot be represented by an IconData font glyph.",
            source=source_id,
            hint="Replace the paint server with an opaque solid fill before conversion.",
        )
    alpha = float(shape.opacity) * float(shape.fill_opacity)
    if not math.isfinite(alpha) or not 0 < alpha <= 1:
        raise IconFontError(
            "SVG_CANONICALIZATION_INCOMPLETE",
            "Canonical painted opacity must be finite and greater than zero.",
            source=source_id,
        )
    if shape.fill_rule != "nonzero":
        raise IconFontError(
            "SVG_FILL_RULE_UNRESOLVED",
            f"Fill rule {shape.fill_rule!r} was not normalized to nonzero winding.",
            source=source_id,
        )
    if shape.transform or shape.clip_path:
        raise IconFontError(
            "SVG_CANONICALIZATION_INCOMPLETE",
            "A transform or clip path remained after canonicalization.",
            source=source_id,
        )
    return shape


def _path_has_area(path: SVGPath) -> bool:
    try:
        return svg_pathops.path_area(path.as_cmd_seq(), fill_rule="nonzero") > 0
    except Exception:
        return True


def _union_paths(left: SVGPath | None, right: SVGPath) -> SVGPath:
    if left is None:
        return right
    return SVGPath.from_commands(
        svg_pathops.union(
            [left.as_cmd_seq(), right.as_cmd_seq()],
            ["nonzero", "nonzero"],
        )
    )


def _difference_paths(left: SVGPath | None, right: SVGPath) -> SVGPath | None:
    if left is None:
        return None
    result = SVGPath.from_commands(
        svg_pathops.difference(
            [left.as_cmd_seq(), right.as_cmd_seq()],
            ["nonzero", "nonzero"],
        )
    )
    result.remove_empty_subpaths(inplace=True)
    return result if _path_has_area(result) else None


def _layered_alpha_geometry(
    shapes: tuple[SVGPath, ...],
    context: _ConversionContext,
) -> tuple[CanonicalLayer, ...]:
    if context.partial_alpha is None:
        return ()

    has_partial_alpha = False
    layers: list[CanonicalLayer] = []
    for shape in shapes:
        encoded_alpha = context.layered_alpha(shape.fill)
        alpha = (
            encoded_alpha
            if encoded_alpha is not None
            else float(shape.opacity) * float(shape.fill_opacity)
        )
        lossy_bits = _lossy_paint_bits(shape.fill)
        unsupported_bits = lossy_bits & ~_LOSSY_FRACTIONAL_ALPHA
        if unsupported_bits:
            features = [
                feature
                for bit, (feature, _code, _message, _hint, _details) in _LOSSY_FEATURES.items()
                if unsupported_bits & bit
            ]
            context.unrepresentable(
                "layered-alpha-paint",
                "SVG_LAYERED_ALPHA_PAINT_UNREPRESENTABLE",
                "The requested layered output contains paint that cannot be reduced to "
                "ordered solid-alpha outlines.",
                hint=(
                    "Expand gradients, patterns, and compositing groups into solid-alpha "
                    "paths before requesting partialAlpha layers."
                ),
                details={"features": features},
            )
        if alpha != 1.0:
            has_partial_alpha = True
        layer_path = copy.deepcopy(shape.as_path())
        layer_path.fill = "#000000"
        layer_path.fill_rule = "nonzero"
        layer_path.opacity = 1.0
        layer_path.fill_opacity = 1.0
        commands = sum(1 for _ in layer_path)
        layers.append(
            CanonicalLayer(
                paths=(layer_path.d,),
                fill_rules=("nonzero",),
                opacity=alpha,
                bounds=_bounds_tuple(layer_path.bounding_box(), context.source_id),
                path_command_count=commands,
            )
        )

    if not has_partial_alpha:
        return ()
    if len(layers) > _MAX_LAYERED_ALPHA_LAYERS:
        context.unrepresentable(
            "layered-alpha-count",
            "SVG_LAYERED_ALPHA_LIMIT",
            f"Layered alpha requires {len(layers)} paint-order layers, exceeding the "
            f"bounded limit of {_MAX_LAYERED_ALPHA_LAYERS}.",
            hint="Merge nonoverlapping shapes without changing paint order, or simplify the icon.",
            details={
                "layers": len(layers),
                "maxLayers": _MAX_LAYERED_ALPHA_LAYERS,
            },
        )
    return tuple(layers)


def _binary_alpha_silhouette(
    shapes: tuple[SVGPath, ...], context: _ConversionContext
) -> tuple[SVGPath, ...]:
    if all(
        float(shape.opacity) * float(shape.fill_opacity) == 1.0
        and _lossy_paint_bits(shape.fill) == 0
        for shape in shapes
    ):
        return shapes

    opaque: SVGPath | None = None
    partial_by_provenance: dict[int, SVGPath] = {}
    for shape in shapes:
        path = shape.as_path()
        path.fill_rule = "nonzero"
        alpha = float(shape.opacity) * float(shape.fill_opacity)
        lossy_bits = _lossy_paint_bits(shape.fill)
        if alpha == 1.0 and lossy_bits == 0:
            opaque = _union_paths(opaque, path)
            for provenance, partial in tuple(partial_by_provenance.items()):
                remainder = _difference_paths(partial, path)
                if remainder is None:
                    del partial_by_provenance[provenance]
                else:
                    partial_by_provenance[provenance] = remainder
        else:
            visible_partial = _difference_paths(path, opaque) if opaque is not None else path
            if visible_partial is not None:
                provenance = lossy_bits
                if provenance == 0:
                    provenance |= _LOSSY_FRACTIONAL_ALPHA
                previous = partial_by_provenance.get(provenance)
                partial_by_provenance[provenance] = _union_paths(previous, visible_partial)

    surviving_bits = 0
    opaque_only_fallback = (
        context.partial_alpha is not None
        and context.partial_alpha.fallback is PartialAlphaFallback.OPAQUE_ONLY
    )
    for provenance, partial in sorted(partial_by_provenance.items()):
        surviving_bits |= provenance
        if not opaque_only_fallback:
            opaque = _union_paths(opaque, partial)
    for bit, (feature, code, message, hint, details) in _LOSSY_FEATURES.items():
        if surviving_bits & bit:
            issue_details: dict[str, Any] = details
            if context.partial_alpha is not None and bit == _LOSSY_FRACTIONAL_ALPHA:
                if opaque_only_fallback:
                    code = "SVG_PARTIAL_ALPHA_DROPPED"
                    message = (
                        "The legacy single-glyph fallback omitted surviving fractional-alpha "
                        "paint; lossless ordered layer fonts were emitted."
                    )
                    hint = "Render the generated layered icon descriptor to preserve source alpha."
                    issue_details = {
                        "approximation": "opaque-only",
                        "scope": "single-glyph-fallback",
                        "losslessLayeredOutput": True,
                    }
                else:
                    message = (
                        "The legacy single-glyph fallback flattened surviving fractional alpha "
                        "to opaque coverage; lossless ordered layer fonts were emitted."
                    )
                    hint = "Render the generated layered icon descriptor to preserve source alpha."
                    issue_details = {
                        **details,
                        "scope": "single-glyph-fallback",
                        "losslessLayeredOutput": True,
                    }
            context.lossy(
                feature,
                code,
                message,
                hint=hint,
                details=issue_details,
                scoped_opt_in=(
                    context.partial_alpha is not None and bit == _LOSSY_FRACTIONAL_ALPHA
                ),
            )
    if opaque is None:
        context.unrepresentable(
            "empty-alpha-silhouette",
            "SVG_EMPTY_OUTLINE",
            (
                "No fully opaque outline remains for the requested opaque-only fallback."
                if opaque_only_fallback
                else "No nontransparent outline remains after alpha compositing."
            ),
        )
    opaque.fill = "#000000"
    opaque.fill_rule = "nonzero"
    opaque.opacity = 1.0
    opaque.fill_opacity = 1.0
    return (opaque,)


def _bounds_tuple(bounds: Rect, source_id: str) -> tuple[float, float, float, float]:
    values = (bounds.x, bounds.y, bounds.x + bounds.w, bounds.y + bounds.h)
    if not all(math.isfinite(value) for value in values):
        raise IconFontError(
            "SVG_EMPTY_OUTLINE",
            "The canonical silhouette has nonfinite bounds.",
            source=source_id,
        )
    if bounds.w <= 0 or bounds.h <= 0:
        raise SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "empty-silhouette",
            "SVG_EMPTY_OUTLINE",
            "The canonical silhouette has no painted area.",
            source=source_id,
        )
    return values


def compile_svg(source: SvgSource, config: BuildConfig) -> CanonicalGlyph:
    _reject_unsafe_xml(source)
    context = _ConversionContext(config, source.source_id)
    try:
        try:
            svg = SVG.fromstring(source.content)
        except etree.XMLSyntaxError as error:
            parser_error = error.error_log.last_error
            if (
                parser_error is not None
                and parser_error.type == etree.ErrorTypes.ERR_RESOURCE_LIMIT
            ):
                if parser_error.message.startswith("Excessive depth"):
                    raise IconFontError(
                        "SVG_TOO_DEEP",
                        "The SVG exceeds the 128-element nesting limit.",
                        source=source.source_id,
                    ) from error
                raise IconFontError(
                    "SVG_XML_RESOURCE_LIMIT",
                    "The XML document exceeds a parser resource limit.",
                    source=source.source_id,
                    hint="Reduce oversized XML text nodes before compiling this icon.",
                ) from error
            line, column = error.position
            raise IconFontError(
                "SVG_XML_MALFORMED",
                "The input is not a well-formed XML document.",
                source=source.source_id,
                hint="Provide well-formed XML whose root element is a namespaced <svg>.",
                details={"line": line, "column": column},
            ) from error
        _preflight(svg, source, config)
        _normalize_view_boxes(svg.svg_root)
        svg.apply_style_attributes(inplace=True)
        _normalize_use_lengths(svg, source.source_id)
        _expand_symbol_uses(svg.svg_root, source.source_id)
        svg.resolve_use(inplace=True)
        _normalize_static_structure(svg.svg_root, source.source_id)
        _materialize_marker_references(svg.svg_root)
        _materialize_computed_geometry_properties(svg.svg_root, source.source_id)
        _drop_non_geometric_presentation_hints(svg.svg_root)
        _normalize_visibility_and_display(svg.svg_root, source.source_id)
        _normalize_presentation(svg.svg_root, context)
        # Presentation normalization can turn zero-opacity containers into
        # display:none after the first visibility pass.
        _normalize_visibility_and_display(svg.svg_root, source.source_id)
        outline_text(
            svg.svg_root,
            text_fonts=dict(config.text_fonts),
            source_id=source.source_id,
            max_expanded_elements=config.max_expanded_elements,
            max_expanded_bytes=config.max_expanded_bytes,
            max_path_commands=config.max_path_commands,
        )
        _normalize_viewport_relative_lengths(svg, source.source_id)
        # Nested viewport mapping is author geometry. Materialize it before
        # resolving clip subtrees so an <svg> inside a clipPath contributes the
        # same transform and viewport clipping as it does in the render tree.
        _normalize_nested_viewports(svg, source.source_id)
        # Resolve target-relative clips while their target tree still contains
        # only author-provided geometry. Marker and vector-effect expansion add
        # compiler-generated decoration that must be clipped, but must never
        # enlarge the objectBoundingBox used to define that clip.
        _normalize_clip_semantics(svg.svg_root, source.source_id)
        _materialize_clips(svg.svg_root, source.source_id, config)
        _expand_markers(svg.svg_root, source.source_id, config)
        _normalize_root_viewport(svg, source.source_id)
        _enforce_tree_limits(svg.svg_root, source, config)
        _normalize_dash_semantics(svg, source.source_id, config)
        _normalize_non_scaling_strokes(svg, source.source_id)
        svg.topicosvg(
            ndigits=max(1, config.precision),
            inplace=True,
            allow_text=False,
            drop_unsupported=False,
        )
        _flatten_fractional_opacity_groups(svg.svg_root, source.source_id)
        view_box = _finite_view_box(svg.view_box(), source.source_id)
        if svg.xpath("//svg:g"):
            raise IconFontError(
                "SVG_GROUP_COMPOSITING_UNSUPPORTED",
                "A group remained after normalization, usually because group "
                "compositing or opacity cannot be represented.",
                source=source.source_id,
            )
        canonical_shapes = tuple(
            _assert_canonical_shape(shape, source.source_id).round_floats(
                config.precision, inplace=False
            )
            for shape in svg.shapes()
        )
        if not canonical_shapes:
            context.unrepresentable(
                "empty-silhouette",
                "SVG_EMPTY_OUTLINE",
                "No painted outline remains after canonicalization.",
            )
        for shape in canonical_shapes:
            _canonical_solid_paint(shape.fill)
        layers = _layered_alpha_geometry(canonical_shapes, context)
        shapes = _binary_alpha_silhouette(canonical_shapes, context)
        paths = tuple(shape.d for shape in shapes)
        fill_rules = tuple(shape.fill_rule for shape in shapes)
        command_count = sum(sum(1 for _ in shape) for shape in shapes) + sum(
            layer.path_command_count for layer in layers
        )
        if command_count > config.max_path_commands:
            raise IconFontError(
                "SVG_TOO_MANY_PATH_COMMANDS",
                f"The canonical outline exceeds {config.max_path_commands} commands.",
                source=source.source_id,
            )
        shape_bounds = tuple(shape.bounding_box() for shape in shapes)
        if not shape_bounds:
            raise IconFontError(
                "SVG_EMPTY_OUTLINE",
                "The canonical silhouette is empty.",
                source=source.source_id,
            )
        min_x = min(bounds.x for bounds in shape_bounds)
        min_y = min(bounds.y for bounds in shape_bounds)
        max_x = max(bounds.x + bounds.w for bounds in shape_bounds)
        max_y = max(bounds.y + bounds.h for bounds in shape_bounds)
        bounds = Rect(min_x, min_y, max_x - min_x, max_y - min_y)
        return CanonicalGlyph(
            paths=paths,
            fill_rules=fill_rules,
            view_box=(view_box.x, view_box.y, view_box.w, view_box.h),
            bounds=_bounds_tuple(bounds, source.source_id),
            source_shape_count=len(canonical_shapes),
            path_command_count=command_count,
            issues=context.issues(),
            layers=layers,
        )
    except (IconFontError, SvgFeatureBatchError):
        raise
    except Exception as error:
        raise IconFontError(
            "INTERNAL_CONVERSION_ERROR",
            "An unexpected internal error occurred while converting this SVG.",
            source=source.source_id,
            hint="Report this input and diagnostic if the failure is reproducible.",
            details={"exceptionType": type(error).__name__},
        ) from error
