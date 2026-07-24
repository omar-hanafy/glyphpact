from __future__ import annotations

import hashlib
import math
import re
import struct
import unicodedata
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from itertools import repeat
from typing import Any

from fontTools.fontBuilder import FontBuilder
from fontTools.misc.timeTools import timestampSinceEpoch
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont
from picosvg import svg_pathops
from picosvg.svg_transform import Affine2D
from picosvg.svg_types import SVGPath

from .config import BuildConfig
from .errors import BatchError, Diagnostic, IconFontError, as_diagnostic
from .identity import GENERATOR_ID, PRODUCT_NAME, REPOSITORY_URL
from .manifest import LockGlyph
from .svg_compiler import CanonicalGlyph
from .version import FONT_FORMAT_REVISION


@dataclass(frozen=True)
class GlyphInput:
    lock: LockGlyph
    geometry: CanonicalGlyph


@dataclass(frozen=True)
class FontGlyphReport:
    source: str
    name: str
    codepoint: int
    glyph_name: str
    advance: int
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class FontArtifact:
    data: bytes
    sha256: str
    glyphs: tuple[FontGlyphReport, ...]
    tables: tuple[str, ...]
    ascent: int
    descent: int


@dataclass(frozen=True)
class _CharstringResult:
    item: GlyphInput
    charstring: Any | None = None
    bounds: tuple[float, float, float, float] | None = None
    diagnostic: Diagnostic | None = None


def _glyph_name(codepoint: int) -> str:
    return f"uni{codepoint:04X}" if codepoint <= 0xFFFF else f"u{codepoint:X}"


def _cff_family_name(font_family: str, fingerprint: str) -> str:
    normalized = unicodedata.normalize("NFKD", font_family)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9 _-]+", " ", ascii_name)
    ascii_name = " ".join(ascii_name.split()).strip(" -_")
    return ascii_name or f"Icon Font {fingerprint[:12]}"


def _postscript_name(cff_family_name: str, fingerprint: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "", cff_family_name) or "IconFont"
    suffix = f"-{fingerprint[:12]}-Regular"
    return f"{base[: 63 - len(suffix)]}{suffix}"


def _transform(geometry: CanonicalGlyph, config: BuildConfig) -> tuple[Affine2D, SVGPath]:
    x, y, width, height = geometry.view_box
    drawable = config.units_per_em * (1.0 - 2.0 * config.padding)
    scale = drawable / max(width, height)
    x_padding = (config.units_per_em - width * scale) / 2.0
    y_padding = (config.units_per_em - height * scale) / 2.0
    transform = Affine2D(  # type: ignore[call-arg]
        scale,
        0,
        0,
        -scale,
        -x * scale + x_padding,
        config.units_per_em + y * scale - y_padding,
    )
    left = round(x_padding)
    right = round(x_padding + width * scale)
    bottom = round(y_padding)
    top = round(y_padding + height * scale)
    clip = SVGPath(d=f"M{left},{bottom} L{right},{bottom} L{right},{top} L{left},{top} Z")
    return transform, clip


def _font_path(item: GlyphInput, config: BuildConfig) -> SVGPath:
    transform, clip = _transform(item.geometry, config)
    paths = [
        SVGPath(d=path).apply_transform(transform).round_floats(0) for path in item.geometry.paths
    ]
    try:
        if len(paths) == 1:
            merged = paths[0]
        else:
            merged = SVGPath.from_commands(
                svg_pathops.union(
                    [path.as_cmd_seq() for path in paths],
                    item.geometry.fill_rules,
                )
            ).round_floats(0)
        if config.clip_to_viewbox:
            merged = SVGPath.from_commands(
                svg_pathops.intersection(
                    [merged.as_cmd_seq(), clip.as_cmd_seq()],
                    ["nonzero", "nonzero"],
                )
            ).round_floats(0)
        merged.remove_empty_subpaths(inplace=True)
        return merged
    except Exception as error:
        raise IconFontError(
            "FONT_GEOMETRY_OPERATION_FAILED",
            str(error),
            source=item.lock.source,
        ) from error


def _charstring(
    item: GlyphInput, config: BuildConfig
) -> tuple[Any, tuple[float, float, float, float]]:
    font_path = _font_path(item, config)
    t2_pen = T2CharStringPen(config.units_per_em, None, roundTolerance=0.001)
    cubic_pen = Qu2CuPen(t2_pen, max_err=0.001, all_cubic=True)
    bounds_pen = BoundsPen(None)
    try:
        parse_path(font_path.d, cubic_pen)
        parse_path(font_path.d, bounds_pen)
    except (ValueError, IndexError, TypeError) as error:
        raise IconFontError(
            "FONT_PATH_CONVERSION_FAILED",
            str(error),
            source=item.lock.source,
        ) from error
    charstring = t2_pen.getCharString()
    bounds = bounds_pen.bounds
    if bounds is None or not all(math.isfinite(value) for value in bounds):
        raise IconFontError(
            "FONT_GLYPH_EMPTY",
            "The font writer produced an empty or non-finite glyph.",
            source=item.lock.source,
        )
    tolerance = 0.05
    if config.clip_to_viewbox and (
        bounds[0] < -tolerance
        or bounds[1] < -tolerance
        or bounds[2] > config.units_per_em + tolerance
        or bounds[3] > config.units_per_em + tolerance
    ):
        raise IconFontError(
            "FONT_GLYPH_OUT_OF_BOUNDS",
            f"Glyph bounds {tuple(round(value, 3) for value in bounds)} exceed the em square.",
            source=item.lock.source,
        )
    if not config.clip_to_viewbox and (min(bounds) < -32_768 or max(bounds) > 32_767):
        raise IconFontError(
            "FONT_GLYPH_COORDINATE_LIMIT",
            "Unclipped glyph coordinates exceed signed OpenType metric limits.",
            source=item.lock.source,
            hint="Enable viewBox clipping or reduce geometry outside the SVG viewport.",
        )
    typed_bounds = (
        float(bounds[0]),
        float(bounds[1]),
        float(bounds[2]),
        float(bounds[3]),
    )
    return charstring, typed_bounds


def _charstring_worker(item: GlyphInput, config: BuildConfig) -> _CharstringResult:
    try:
        charstring, bounds = _charstring(item, config)
        return _CharstringResult(item=item, charstring=charstring, bounds=bounds)
    except Exception as error:
        return _CharstringResult(
            item=item,
            diagnostic=as_diagnostic(error, source=item.lock.source),
        )


def _build_charstrings(
    ordered: tuple[GlyphInput, ...], config: BuildConfig
) -> tuple[_CharstringResult, ...]:
    if config.jobs == 1 or len(ordered) < 16:
        results = tuple(_charstring_worker(item, config) for item in ordered)
    else:
        chunksize = max(1, len(ordered) // (config.jobs * 8))
        try:
            with ProcessPoolExecutor(max_workers=config.jobs) as executor:
                results = tuple(
                    executor.map(
                        _charstring_worker,
                        ordered,
                        repeat(config),
                        chunksize=chunksize,
                    )
                )
        except Exception as error:
            raise IconFontError(
                "FONT_WORKER_POOL_FAILED",
                str(error),
                hint="Retry with --jobs 1 to isolate the failing input.",
            ) from error
    diagnostics = tuple(result.diagnostic for result in results if result.diagnostic is not None)
    if diagnostics:
        raise BatchError(diagnostics)
    return results


def _build_fingerprint(items: Iterable[GlyphInput], config: BuildConfig) -> str:
    digest = hashlib.sha256()
    digest.update(f"{GENERATOR_ID}\0v2\0".encode())
    digest.update(config.font_family.encode("utf-8"))
    digest.update(b"\0")
    digest.update((config.copyright or "").encode("utf-8"))
    digest.update(
        (
            f"\0{config.units_per_em}\0{config.padding}\0{config.precision}\0"
            f"{int(config.clip_to_viewbox)}\0"
        ).encode()
    )
    for item in sorted(items, key=lambda value: value.lock.codepoint):
        digest.update(f"{item.lock.codepoint:X}\0".encode())
        digest.update((item.lock.geometry_sha256 or "").encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _stabilize_cff_font_bbox(data: bytes, units_per_em: int) -> bytes:
    """Keep Flutter's CFF line metrics anchored to the SVG em square."""
    font: TTFont | None = None
    try:
        font = TTFont(
            BytesIO(data),
            lazy=False,
            recalcBBoxes=False,
            recalcTimestamp=False,
            checkChecksums=2,
        )
        top_dict = font["CFF "].cff.topDictIndex[0]
        actual = tuple(float(value) for value in top_dict.FontBBox)
        if len(actual) != 4 or not all(math.isfinite(value) for value in actual):
            raise ValueError("CFF FontBBox is missing or non-finite.")
        top_dict.FontBBox = [
            math.floor(actual[0]),
            min(0, math.floor(actual[1])),
            math.ceil(actual[2]),
            max(units_per_em, math.ceil(actual[3])),
        ]
        output = BytesIO()
        font.save(output, reorderTables=False)
        return output.getvalue()
    except Exception as error:
        raise IconFontError(
            "FONT_BUILD_FAILED",
            f"Could not stabilize the CFF em-square metrics: {error}",
        ) from error
    finally:
        if font is not None:
            font.close()


def build_font(items: Iterable[GlyphInput], config: BuildConfig) -> FontArtifact:
    ordered = tuple(sorted(items, key=lambda item: item.lock.codepoint))
    if not ordered:
        raise IconFontError("FONT_EMPTY", "At least one glyph is required.")
    if len(ordered) > 65_534:
        raise IconFontError(
            "FONT_GLYPH_LIMIT",
            "A single OpenType font cannot contain more than 65,534 icon glyphs.",
            hint="Split the icon pack into multiple fonts.",
        )

    glyph_order = [".notdef"]
    cmap: dict[int, str] = {}
    charstrings = {}
    metrics: dict[str, tuple[int, float]] = {}
    reports: list[FontGlyphReport] = []

    notdef_pen = T2CharStringPen(config.units_per_em, None)
    notdef = notdef_pen.getCharString()
    charstrings[".notdef"] = notdef
    metrics[".notdef"] = (config.units_per_em, 0)

    for result in _build_charstrings(ordered, config):
        item = result.item
        charstring = result.charstring
        bounds = result.bounds
        assert charstring is not None
        assert bounds is not None
        glyph_name = _glyph_name(item.lock.codepoint)
        glyph_order.append(glyph_name)
        cmap[item.lock.codepoint] = glyph_name
        charstrings[glyph_name] = charstring
        metrics[glyph_name] = (config.units_per_em, bounds[0])
        reports.append(
            FontGlyphReport(
                source=item.lock.source,
                name=item.lock.name,
                codepoint=item.lock.codepoint,
                glyph_name=glyph_name,
                advance=config.units_per_em,
                bounds=bounds,
            )
        )

    fingerprint = _build_fingerprint(ordered, config)
    cff_family_name = _cff_family_name(config.font_family, fingerprint)
    postscript_name = _postscript_name(cff_family_name, fingerprint)
    full_name = f"{config.font_family} Regular"
    timestamp = timestampSinceEpoch(0)
    min_y = min(report.bounds[1] for report in reports)
    max_y = max(report.bounds[3] for report in reports)
    metric_ascent = max(config.units_per_em, math.ceil(max_y))
    metric_descent = min(0, math.floor(min_y))

    builder = FontBuilder(config.units_per_em, isTTF=False)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(cmap)
    cff_info = {
        "FullName": f"{cff_family_name} Regular",
        "FamilyName": cff_family_name,
        "Weight": "Regular",
        "version": f"{FONT_FORMAT_REVISION:.1f}",
        "Notice": "",
    }
    builder.setupCFF(postscript_name, cff_info, charstrings, {})
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=metric_ascent, descent=metric_descent, lineGap=0)
    names = {
        "familyName": config.font_family,
        "styleName": "Regular",
        "uniqueFontIdentifier": f"{GENERATOR_ID}:{fingerprint[:24]}",
        "fullName": full_name,
        "psName": postscript_name,
        "version": f"Version {FONT_FORMAT_REVISION:.1f}",
        "description": f"Deterministic Flutter icon font generated by {PRODUCT_NAME}.",
        "vendorURL": REPOSITORY_URL,
    }
    if config.copyright:
        names["copyright"] = config.copyright
    builder.setupNameTable(names)
    builder.setupOS2(
        sTypoAscender=metric_ascent,
        sTypoDescender=metric_descent,
        sTypoLineGap=0,
        usWinAscent=metric_ascent,
        usWinDescent=-metric_descent,
        usWeightClass=400,
        usWidthClass=5,
        fsType=0,
        fsSelection=0x40,
        sxHeight=0,
        sCapHeight=config.units_per_em,
    )
    builder.setupPost(keepGlyphNames=False)
    builder.font["head"].created = timestamp
    builder.font["head"].modified = timestamp
    builder.font["head"].fontRevision = FONT_FORMAT_REVISION

    output = BytesIO()
    try:
        builder.save(output)
    except Exception as error:
        raise IconFontError("FONT_BUILD_FAILED", str(error)) from error
    data = _stabilize_cff_font_bbox(output.getvalue(), config.units_per_em)
    tables = _validate_font(
        data,
        reports,
        config,
        fingerprint=fingerprint,
        postscript_name=postscript_name,
        cff_family_name=cff_family_name,
    )
    return FontArtifact(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        glyphs=tuple(reports),
        tables=tables,
        ascent=metric_ascent,
        descent=metric_descent,
    )


def _validate_font(
    data: bytes,
    reports: Iterable[FontGlyphReport],
    config: BuildConfig,
    *,
    fingerprint: str,
    postscript_name: str,
    cff_family_name: str,
) -> tuple[str, ...]:
    report_items = tuple(reports)
    expected = {report.codepoint: report.glyph_name for report in report_items}
    try:
        font = TTFont(
            BytesIO(data),
            lazy=False,
            recalcBBoxes=False,
            recalcTimestamp=False,
            checkChecksums=2,
        )
        _validate_sfnt_checksums(data, font)
        required_tables = {"CFF ", "OS/2", "cmap", "head", "hhea", "hmtx", "maxp", "name", "post"}
        missing = required_tables - set(font.keys())
        if missing:
            raise IconFontError(
                "FONT_TABLE_MISSING",
                f"Missing OpenType table(s): {', '.join(sorted(missing))}.",
            )
        if font["head"].unitsPerEm != config.units_per_em:
            raise IconFontError("FONT_METRICS_MISMATCH", "unitsPerEm changed during compilation.")
        expected_ascent = max(
            config.units_per_em,
            math.ceil(max(report.bounds[3] for report in report_items)),
        )
        expected_descent = min(
            0,
            math.floor(min(report.bounds[1] for report in report_items)),
        )
        if (
            font["hhea"].ascent != expected_ascent
            or font["hhea"].descent != expected_descent
            or font["OS/2"].sTypoAscender != expected_ascent
            or font["OS/2"].sTypoDescender != expected_descent
            or font["OS/2"].usWinAscent != expected_ascent
            or font["OS/2"].usWinDescent != -expected_descent
        ):
            raise IconFontError(
                "FONT_METRICS_MISMATCH",
                "Vertical font metrics do not cover every emitted glyph.",
            )
        expected_head_bbox = (
            math.floor(min(report.bounds[0] for report in report_items)),
            math.floor(min(report.bounds[1] for report in report_items)),
            math.ceil(max(report.bounds[2] for report in report_items)),
            math.ceil(max(report.bounds[3] for report in report_items)),
        )
        actual_head_bbox = (
            font["head"].xMin,
            font["head"].yMin,
            font["head"].xMax,
            font["head"].yMax,
        )
        if actual_head_bbox != expected_head_bbox:
            raise IconFontError(
                "FONT_METRICS_MISMATCH",
                "The global head bounds do not exactly cover the emitted glyphs.",
                details={
                    "expected": list(expected_head_bbox),
                    "actual": list(actual_head_bbox),
                },
            )
        horizontal_fields = (
            "advanceWidthMax",
            "minLeftSideBearing",
            "minRightSideBearing",
            "xMaxExtent",
        )
        actual_horizontal_metrics = tuple(
            getattr(font["hhea"], field) for field in horizontal_fields
        )
        font["hhea"].recalc(font)
        recalculated_horizontal_metrics = tuple(
            getattr(font["hhea"], field) for field in horizontal_fields
        )
        if actual_horizontal_metrics != recalculated_horizontal_metrics:
            raise IconFontError(
                "FONT_METRICS_MISMATCH",
                "The horizontal header metrics do not match the emitted glyphs.",
                details={
                    "expected": list(recalculated_horizontal_metrics),
                    "actual": list(actual_horizontal_metrics),
                },
            )
        names = font["name"]
        expected_names = {
            1: config.font_family,
            3: f"{GENERATOR_ID}:{fingerprint[:24]}",
            4: f"{config.font_family} Regular",
            6: postscript_name,
        }
        for name_id, expected_name in expected_names.items():
            if names.getDebugName(name_id) != expected_name:
                raise IconFontError(
                    "FONT_NAME_MISMATCH",
                    f"OpenType name ID {name_id} does not match the configured face identity.",
                )
        if font["OS/2"].fsType != 0:
            raise IconFontError(
                "FONT_EMBEDDING_RESTRICTED",
                "The generated font must permit installable embedding and subsetting.",
            )
        top_dict = font["CFF "].cff.topDictIndex[0]
        if top_dict.FamilyName != cff_family_name or top_dict.FullName != (
            f"{cff_family_name} Regular"
        ):
            raise IconFontError(
                "FONT_CFF_NAME_MISMATCH",
                "CFF and OpenType face metadata are inconsistent.",
            )
        expected_cff_bbox = (
            expected_head_bbox[0],
            min(0, expected_head_bbox[1]),
            expected_head_bbox[2],
            max(config.units_per_em, expected_head_bbox[3]),
        )
        actual_cff_bbox = tuple(top_dict.FontBBox)
        if actual_cff_bbox != expected_cff_bbox:
            raise IconFontError(
                "FONT_METRICS_MISMATCH",
                "The CFF FontBBox does not cover the declared vertical metrics and glyphs.",
                details={
                    "expected": list(expected_cff_bbox),
                    "actual": list(actual_cff_bbox),
                },
            )
        cmap = font.getBestCmap() or {}
        if cmap != expected:
            raise IconFontError(
                "FONT_CMAP_MISMATCH",
                "The compiled cmap does not exactly match the generated Dart API.",
                details={
                    "expected": {f"U+{key:04X}": value for key, value in expected.items()},
                    "actual": {f"U+{key:04X}": value for key, value in cmap.items()},
                },
            )
        glyph_set = font.getGlyphSet()
        for report in report_items:
            glyph = glyph_set[report.glyph_name]
            recording = RecordingPen()
            glyph.draw(recording)
            if not recording.value:
                raise IconFontError(
                    "FONT_GLYPH_EMPTY",
                    "The validated OpenType glyph has no drawing commands.",
                    source=report.source,
                )
            bounds_pen = BoundsPen(glyph_set)
            glyph.draw(bounds_pen)
            if bounds_pen.bounds is None:
                raise IconFontError(
                    "FONT_GLYPH_EMPTY",
                    "The validated OpenType glyph has no bounds.",
                    source=report.source,
                )
            advance, _ = font["hmtx"].metrics[report.glyph_name]
            if advance != config.units_per_em:
                raise IconFontError(
                    "FONT_ADVANCE_MISMATCH",
                    f"Expected advance {config.units_per_em}, got {advance}.",
                    source=report.source,
                )
        table_names = font.keys()
        return tuple(sorted(table for table in table_names if table != "GlyphOrder"))
    except IconFontError:
        raise
    except Exception as error:
        raise IconFontError("FONT_VALIDATION_FAILED", str(error)) from error
    finally:
        if "font" in locals():
            font.close()


def _sfnt_checksum(data: bytes) -> int:
    remainder = len(data) % 4
    if remainder:
        data += b"\0" * (4 - remainder)
    return int(sum(struct.unpack(f">{len(data) // 4}I", data))) & 0xFFFFFFFF


def _validate_sfnt_checksums(data: bytes, font: TTFont) -> None:
    reader = font.reader
    for tag, entry in reader.tables.items():
        table_data = entry.loadData(reader.file)
        if tag == "head":
            table_data = table_data[:8] + b"\0\0\0\0" + table_data[12:]
        if _sfnt_checksum(table_data) != entry.checkSum:
            raise IconFontError(
                "FONT_CHECKSUM_MISMATCH",
                f"OpenType table {tag!s} has an invalid checksum.",
            )
    if _sfnt_checksum(data) != 0xB1B0AFBA:
        raise IconFontError(
            "FONT_CHECKSUM_ADJUSTMENT_INVALID",
            "The OpenType whole-font checksum adjustment is invalid.",
        )
