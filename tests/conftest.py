from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from glyphpact.config import TextFont


@pytest.fixture
def simple_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M2 2h20v20H2z"/>'
        "</svg>"
    )


def write_svg(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def pinned_text_font(tmp_path: Path) -> tuple[str, TextFont]:
    """Build a tiny, deterministic outline font without relying on host fonts."""

    def glyph(points: tuple[tuple[int, int], ...] = ()) -> Any:
        pen = TTGlyphPen(None)
        if points:
            pen.moveTo(points[0])
            for point in points[1:]:
                pen.lineTo(point)
            pen.closePath()
        return pen.glyph()

    glyph_order = [".notdef", "A", "space"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({0x20: "space", 0x41: "A"})
    builder.setupGlyf(
        {
            ".notdef": glyph(),
            "space": glyph(),
            "A": glyph(
                (
                    (100, 0),
                    (300, 700),
                    (500, 0),
                    (400, 0),
                    (350, 200),
                    (250, 200),
                    (200, 0),
                )
            ),
        }
    )
    builder.setupHorizontalMetrics(
        {
            ".notdef": (600, 0),
            "A": (600, 100),
            "space": (300, 0),
        }
    )
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    builder.setupNameTable(
        {
            "familyName": "Pinned Test",
            "styleName": "Regular",
            "uniqueFontIdentifier": "PinnedTest-Regular",
            "fullName": "Pinned Test Regular",
            "psName": "PinnedTest-Regular",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.setupHead(created=3_500_000_000, modified=3_500_000_000)

    path = tmp_path / "pinned-test.ttf"
    builder.save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "Pinned Test", TextFont(path=path, sha256=digest)
