from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from pathlib import Path

import pytest
from conftest import write_svg
from fontTools.ttLib import TTFont

from glyphpact import __version__
from glyphpact.builder import build
from glyphpact.config import (
    BuildConfig,
    ConversionPolicy,
    IconOverride,
    LossyPolicy,
)
from glyphpact.discovery import SvgSource
from glyphpact.errors import (
    IconFontError,
    IssueAction,
    SvgFeatureClass,
    SvgFeatureError,
)
from glyphpact.naming import derive_dart_name
from glyphpact.svg_compiler import compile_svg


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _simple_input(root: Path) -> Path:
    inputs = root / "icons"
    write_svg(
        inputs,
        "icon.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect x="1" y="1" width="8" height="8"/></svg>',
    )
    return inputs


def _source(content: str) -> SvgSource:
    data = content.encode("utf-8")
    return SvgSource(
        path=Path("icon.svg"),
        source_id="icon.svg",
        content=content,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
    )


def test_release_versions_and_generated_surfaces_agree(tmp_path: Path) -> None:
    project = Path(__file__).parents[1]
    pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert version_match is not None and version_match.group(1) == __version__

    result = build(BuildConfig(_simple_input(tmp_path), tmp_path / "generated"))
    lock = json.loads(result.lock_path.read_text(encoding="utf-8"))
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    dart = result.dart_path.read_text(encoding="utf-8")
    assert lock["generatorVersion"] == __version__
    assert report["generatorVersion"] == __version__
    assert lock["generator"] == "glyphpact"
    assert report["generator"] == "glyphpact"
    assert f"GlyphPact {__version__}" in dart


def test_unicode_flutter_family_uses_portable_unique_cff_names(tmp_path: Path) -> None:
    inputs = _simple_input(tmp_path)
    first = build(
        BuildConfig(
            inputs,
            tmp_path / "arabic",
            font_family="أيقونات",
            class_name="ArabicIcons",
        )
    )
    second = build(
        BuildConfig(
            inputs,
            tmp_path / "other",
            font_family="أيقونات أخرى",
            class_name="ArabicIcons",
        )
    )
    first_font = TTFont(BytesIO(first.font_path.read_bytes()), recalcTimestamp=False)
    second_font = TTFont(BytesIO(second.font_path.read_bytes()), recalcTimestamp=False)
    try:
        assert first_font["name"].getDebugName(1) == "أيقونات"
        assert second_font["name"].getDebugName(1) == "أيقونات أخرى"
        first_ps = first_font["name"].getDebugName(6)
        second_ps = second_font["name"].getDebugName(6)
        assert first_ps != second_ps
        assert first_ps is not None and len(first_ps) <= 63 and first_ps.isascii()
        assert second_ps is not None and len(second_ps) <= 63 and second_ps.isascii()
    finally:
        first_font.close()
        second_font.close()


def test_attribution_carries_declared_metadata_and_missing_count(tmp_path: Path) -> None:
    inputs = _simple_input(tmp_path)
    write_svg(
        inputs,
        "plain.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<circle cx="5" cy="5" r="3"/></svg>',
    )
    result = build(
        BuildConfig(
            inputs,
            tmp_path / "generated",
            icons={
                "icon.svg": IconOverride(
                    author="Example Studio",
                    license="MIT",
                    source_url="https://example.com/icon",
                )
            },
        )
    )
    attribution = (result.output_dir / "ATTRIBUTION.md").read_text(encoding="utf-8")
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert "Icons with declared metadata: 1" in attribution
    assert "Icons without declared metadata: 1" in attribution
    assert "Example Studio" in attribution
    assert "font embedding and subsetting" in attribution
    assert report["attributionFile"] == "ATTRIBUTION.md"


def test_unclipped_mode_emits_and_covers_intentional_bleed(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    write_svg(
        inputs,
        "bleed.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<path d="M-5-5h20v20H-5z"/></svg>',
    )
    result = build(
        BuildConfig(
            inputs,
            tmp_path / "generated",
            clip_to_viewbox=False,
        )
    )
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    bounds = report["glyphs"][0]["fontBounds"]
    assert bounds == [-500.0, -500.0, 1500.0, 1500.0]
    assert report["font"]["ascent"] == 1500
    assert report["font"]["descent"] == -500
    font = TTFont(BytesIO(result.font_path.read_bytes()), lazy=False, recalcTimestamp=False)
    try:
        assert tuple(font["CFF "].cff.topDictIndex[0].FontBBox) == (
            -500,
            -500,
            1500,
            1500,
        )
    finally:
        font.close()


def test_source_date_epoch_is_not_a_hidden_build_input(tmp_path: Path, monkeypatch) -> None:
    inputs = _simple_input(tmp_path)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1")
    first = build(BuildConfig(inputs, tmp_path / "first"))
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "999999999")
    second = build(BuildConfig(inputs, tmp_path / "second"))
    assert first.font_sha256 == second.font_sha256
    assert _tree(first.output_dir) == _tree(second.output_dir)


def test_derived_dart_names_are_formatter_safe_and_collision_resistant() -> None:
    first_source = "category/" + "extremely-long-descriptive-icon-name-" * 4 + "a.svg"
    second_source = "category/" + "extremely-long-descriptive-icon-name-" * 4 + "b.svg"
    first = derive_dart_name(first_source)
    second = derive_dart_name(second_source)
    assert len(first) <= 40
    assert len(second) <= 40
    assert first != second


def test_cyclic_local_reuse_is_rejected_before_picosvg(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<defs><g id="a"><use href="#a"/></g></defs><use href="#a"/></svg>'
    )
    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(content),
            BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
        )
    assert caught.value.diagnostic.code == "SVG_REFERENCE_CYCLE"


def test_unused_cyclic_local_reuse_is_still_rejected_before_picosvg(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<defs><g id="a"><use href="#a"/></g></defs>'
        '<path d="M0 0h1v1z"/></svg>'
    )
    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(content),
            BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
        )
    assert caught.value.diagnostic.code == "SVG_REFERENCE_CYCLE"


def test_inline_style_nested_clip_cycle_is_rejected_before_expansion(
    tmp_path: Path,
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
        '<clipPath id="a"><path style="clip-path:url(#b)" d="M0 0h9v9z"/></clipPath>'
        '<clipPath id="b"><path style="clip-path:url(#a)" d="M1 1h8v8z"/></clipPath>'
        '</defs><path clip-path="url(#a)" d="M0 0h10v10z"/></svg>'
    )
    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(content),
            BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
        )
    assert caught.value.diagnostic.code == "SVG_REFERENCE_CYCLE"


def test_exponential_local_reuse_is_budgeted_before_expansion(tmp_path: Path) -> None:
    definitions = ['<path id="p" d="M0 0h1v1z"/>']
    previous = "p"
    for index in range(12):
        current = f"n{index}"
        definitions.append(
            f'<g id="{current}"><use href="#{previous}"/><use href="#{previous}"/></g>'
        )
        previous = current
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
        + "".join(definitions)
        + f'</defs><use href="#{previous}"/></svg>'
    )
    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(content),
            BuildConfig(
                tmp_path / "input",
                tmp_path / "output",
                max_expanded_elements=100,
            ).validated(),
        )
    assert caught.value.diagnostic.code == "SVG_EXPANSION_LIMIT"


@pytest.mark.parametrize(
    "config",
    [
        lambda input_path, output_path: BuildConfig(
            input_path,
            output_path,
            font_family="Icons\ud800",
            class_name="AppIcons",
        ),
        lambda input_path, output_path: BuildConfig(
            input_path,
            output_path,
            copyright="Copyright\ud800",
        ),
        lambda input_path, output_path: BuildConfig(
            input_path,
            output_path,
            icons={"icon.svg": IconOverride(author="Author\ud800")},
        ),
    ],
)
def test_config_rejects_non_scalar_unicode_before_generation(tmp_path: Path, config) -> None:
    with pytest.raises(IconFontError) as caught:
        config(tmp_path / "input", tmp_path / "output").validated()
    assert caught.value.diagnostic.code == "TEXT_INVALID"


def test_fractional_alpha_is_strict_by_default_and_explicit_when_converted(
    tmp_path: Path,
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" opacity=".5">'
        '<path d="M0 0h10v10H0z"/></svg>'
    )

    with pytest.raises(SvgFeatureError) as caught:
        compile_svg(
            _source(content),
            BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
        )

    assert caught.value.diagnostic.code == "SVG_PARTIAL_ALPHA_APPROXIMATED"
    assert caught.value.classification is SvgFeatureClass.LOSSY

    glyph = compile_svg(
        _source(content),
        BuildConfig(
            tmp_path / "input",
            tmp_path / "output",
            policy=ConversionPolicy(lossy=LossyPolicy.CONVERT),
        ).validated(),
    )

    assert glyph.bounds == pytest.approx((0.0, 0.0, 10.0, 10.0))
    assert len(glyph.issues) == 1
    assert glyph.issues[0].classification is SvgFeatureClass.LOSSY
    assert glyph.issues[0].action is IssueAction.CONVERTED


def test_zero_opacity_container_produces_typed_empty_silhouette(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<svg opacity="0"><path d="M0 0h10v10H0z"/></svg></svg>'
    )

    with pytest.raises(SvgFeatureError) as caught:
        compile_svg(
            _source(content),
            BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
        )

    assert caught.value.diagnostic.code == "SVG_EMPTY_OUTLINE"
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE


@pytest.mark.parametrize(
    ("content", "expected_bounds"),
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
            'transform="translate(1)"><path d="M0 0h9v9H0z"/></svg>',
            (1.0, 0.0, 10.0, 9.0),
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<defs><clipPath id="c"><rect width="5" height="10"/></clipPath></defs>'
            '<svg clip-path="url(#c)"><path d="M0 0h10v10H0z"/></svg></svg>',
            (0.0, 0.0, 5.0, 10.0),
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<defs><symbol id="s" viewBox="0 0 1 1">'
            '<path d="M0 0h1v1H0z"/></symbol></defs>'
            '<use href="#s" width="10" height="10"/></svg>',
            (0.0, 0.0, 10.0, 10.0),
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<defs><clipPath id="c" clipPathUnits="objectBoundingBox">'
            '<rect width=".5" height="1"/></clipPath></defs>'
            '<path clip-path="url(#c)" d="M0 0h10v10H0z"/></svg>',
            (0.0, 0.0, 5.0, 10.0),
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
            '<clipPath id="b"><rect x="2" y="2" width="4" height="4"/></clipPath>'
            '<clipPath id="a"><rect width="8" height="8" clip-path="url(#b)"/>'
            '</clipPath></defs><path clip-path="url(#a)" d="M0 0h10v10H0z"/></svg>',
            (2.0, 2.0, 6.0, 6.0),
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
            '<clipPath id="c"><rect width="8" height="8" display="none"/>'
            '<rect x="2" y="2" width="2" height="2"/></clipPath></defs>'
            '<path clip-path="url(#c)" d="M0 0h10v10H0z"/></svg>',
            (2.0, 2.0, 4.0, 4.0),
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
            '<defs><path id="a" d="M0 0h1v1H0z"/>'
            '<path id="b" d="M2 2h1v1H2z"/></defs>'
            '<use href="#a" xlink:href="#b"/></svg>',
            (0.0, 0.0, 1.0, 1.0),
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<path d="M0 5h10" fill="none" stroke="black" stroke-width="2" '
            'stroke-dasharray="1 1"/></svg>',
            (0.0, 4.0, 9.0, 6.0),
        ),
    ],
    ids=[
        "root-transform",
        "container-clip",
        "symbol-viewport",
        "object-bounding-box-clip",
        "nested-clip",
        "hidden-clip-child",
        "svg2-href-precedence",
        "dashed-stroke",
    ],
)
def test_supported_container_and_reference_semantics_preserve_exact_bounds(
    tmp_path: Path,
    content: str,
    expected_bounds: tuple[float, float, float, float],
) -> None:
    glyph = compile_svg(
        _source(content),
        BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
    )

    assert glyph.bounds == pytest.approx(expected_bounds)
    assert glyph.issues == ()


@pytest.mark.parametrize(
    "paint",
    ["black", "LightGoldenRodYellow", "#abc", "#A1B2C3", "rgb(1 2 3)", "hsl(20 30% 40%)"],
)
def test_provably_opaque_svg_paints_are_accepted(tmp_path: Path, paint: str) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<path fill="{paint}" d="M0 0h10v10z"/></svg>'
    )
    assert compile_svg(
        _source(content),
        BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
    ).paths


@pytest.mark.parametrize(
    "paint",
    [
        "notacolor",
        "rgb(1.2.3 2 3)",
        "hsl(1.2.3 20% 30%)",
        "rgb(1,2,3,0.5)",
        "rgb(0%,0,0)",
    ],
)
def test_malformed_color_syntax_is_rejected(tmp_path: Path, paint: str) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<path fill="{paint}" d="M0 0h10v10z"/></svg>'
    )
    with pytest.raises(IconFontError):
        compile_svg(
            _source(content),
            BuildConfig(tmp_path / "input", tmp_path / "output").validated(),
        )
