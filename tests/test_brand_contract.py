from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from glyphpact.builder import build
from glyphpact.config import BuildConfig
from glyphpact.discovery import SvgSource
from glyphpact.svg_compiler import compile_svg

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
BRAND_ROOT = REPOSITORY_ROOT / "brand"


def _png_dimensions(path: Path) -> tuple[int, int]:
    content = path.read_bytes()
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    assert content[12:16] == b"IHDR"
    return struct.unpack(">II", content[16:24])


def test_brand_mark_compiles_losslessly_as_five_contours(tmp_path: Path) -> None:
    mark = BRAND_ROOT / "glyphpact-mark.svg"
    content = mark.read_text(encoding="utf-8")
    encoded = content.encode()
    source = SvgSource(
        path=mark,
        source_id=mark.name,
        content=content,
        sha256=hashlib.sha256(encoded).hexdigest(),
        byte_count=len(encoded),
    )
    config = BuildConfig(
        input_path=mark,
        output_dir=tmp_path / "generated",
        font_family="GlyphPact Brand",
        class_name="GlyphPactBrand",
        jobs=1,
    ).validated()

    glyph = compile_svg(source, config)
    assert glyph.issues == ()
    assert glyph.source_shape_count == 5
    assert len(glyph.paths) == 5
    assert glyph.fill_rules == ("nonzero",) * 5
    assert glyph.bounds == (2.5, 2.5, 29.5, 29.5)

    result = build(config)
    assert result.quality == "lossless"
    assert result.glyph_count == 1
    assert result.lossless_glyph_count == 1
    assert result.approximated_glyph_count == 0
    assert result.skipped_icon_count == 0
    assert result.issues == ()


def test_generated_platform_brand_assets_have_canonical_dimensions() -> None:
    apple_touch = BRAND_ROOT / "apple-touch-icon.png"
    social_preview = BRAND_ROOT / "glyphpact-social-preview.png"
    published_touch = REPOSITORY_ROOT / "site" / "public" / "apple-touch-icon.png"

    assert _png_dimensions(apple_touch) == (180, 180)
    assert _png_dimensions(social_preview) == (1280, 640)
    assert social_preview.stat().st_size < 1_000_000
    assert published_touch.read_bytes() == apple_touch.read_bytes()
