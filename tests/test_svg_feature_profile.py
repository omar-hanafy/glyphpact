from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest
from lxml import etree
from picosvg import svg_pathops
from picosvg.svg_types import SVGPath

from glyphpact.config import (
    BuildConfig,
    ConversionPolicy,
    LossyPolicy,
    TextFont,
)
from glyphpact.discovery import SvgSource
from glyphpact.errors import (
    IconFontError,
    IssueAction,
    SvgFeatureClass,
    SvgFeatureError,
)
from glyphpact.svg_compiler import CanonicalGlyph, compile_svg
from glyphpact.text_outliner import outline_text


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
    lossy: LossyPolicy = LossyPolicy.ERROR,
    text_fonts: Mapping[str, TextFont] | None = None,
    max_expanded_elements: int = 2_048,
    max_expanded_bytes: int = 4 * 1024 * 1024,
    max_path_commands: int = 100_000,
    precision: int = 3,
) -> BuildConfig:
    return BuildConfig(
        input_path=tmp_path / "input",
        output_dir=tmp_path / "output",
        policy=ConversionPolicy(lossy=lossy),
        text_fonts=text_fonts or {},
        max_expanded_elements=max_expanded_elements,
        max_expanded_bytes=max_expanded_bytes,
        max_path_commands=max_path_commands,
        precision=precision,
    ).validated()


def _compile(
    tmp_path: Path,
    content: str,
    *,
    lossy: LossyPolicy = LossyPolicy.ERROR,
    text_fonts: Mapping[str, TextFont] | None = None,
    max_expanded_elements: int = 2_048,
    max_expanded_bytes: int = 4 * 1024 * 1024,
    max_path_commands: int = 100_000,
    precision: int = 3,
) -> CanonicalGlyph:
    return compile_svg(
        _source(content),
        _config(
            tmp_path,
            lossy=lossy,
            text_fonts=text_fonts,
            max_expanded_elements=max_expanded_elements,
            max_expanded_bytes=max_expanded_bytes,
            max_path_commands=max_path_commands,
            precision=precision,
        ),
    )


def _assert_equivalent(actual: CanonicalGlyph, expected: CanonicalGlyph) -> None:
    assert actual.view_box == pytest.approx(expected.view_box)
    assert actual.bounds == pytest.approx(expected.bounds)
    assert actual.issues == expected.issues == ()

    def union(glyph: CanonicalGlyph) -> SVGPath:
        return SVGPath.from_commands(
            svg_pathops.union(
                [SVGPath(d=path).as_cmd_seq() for path in glyph.paths],
                glyph.fill_rules,
            )
        )

    actual_path = union(actual)
    expected_path = union(expected)
    for left, right in ((actual_path, expected_path), (expected_path, actual_path)):
        remainder = SVGPath.from_commands(
            svg_pathops.difference(
                [left.as_cmd_seq(), right.as_cmd_seq()],
                ["nonzero", "nonzero"],
            )
        )
        assert abs(svg_pathops.path_area(remainder.as_cmd_seq(), fill_rule="nonzero")) < 1e-9


def test_static_css_cascade_current_color_and_inline_important_are_exact(tmp_path: Path) -> None:
    styled = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <style>
            .paint { fill: none; stroke: none }
            g > .paint:first-child { fill: currentColor }
            #last { fill: none !important }
          </style>
          <g color="red">
            <rect class="paint" x="1" y="2" width="4" height="4"/>
            <rect class="paint" id="last" x="10" y="2" width="4" height="4"
                  style="fill: black !important"/>
          </g>
        </svg>
    """
    explicit = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <rect x="1" y="2" width="4" height="4"/>
          <rect x="10" y="2" width="4" height="4"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, styled), _compile(tmp_path, explicit))


def test_css_is_computed_before_use_and_svg2_href_wins_over_xlink(tmp_path: Path) -> None:
    styled_use = """
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 20 10">
          <style>#shape { fill: currentColor } use { color: green }</style>
          <defs>
            <rect id="shape" width="4" height="4"/>
            <rect id="wrong" width="1" height="1"/>
          </defs>
          <use href="#shape" xlink:href="#wrong" x="3" y="2"/>
        </svg>
    """
    glyph = _compile(tmp_path, styled_use)
    assert glyph.bounds == pytest.approx((3, 2, 7, 6))
    assert glyph.paths == ("M3,2 L7,2 L7,6 L3,6 L3,2 Z",)
    assert glyph.issues == ()


def test_authoritative_svg2_href_ignores_dormant_missing_xlink_fallback(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">
          <defs><rect id="good" width="4" height="5"/></defs>
          <use href="#good" xlink:href="#missing" x="2" y="3"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


@pytest.mark.parametrize(
    ("placement", "numeric"),
    [
        ('x="50%" y="25%"', 'x="50" y="5"'),
        ('x="1cm" y="5pt"', 'x="37.79527559055118" y="6.666666666666667"'),
    ],
)
def test_non_symbol_use_lengths_are_resolved_before_clone_expansion(
    tmp_path: Path, placement: str, numeric: str
) -> None:
    template = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 20">
          <defs><rect id="r" width="4" height="4"/></defs>
          <use href="#r" {placement}/>
        </svg>
    """
    _assert_equivalent(
        _compile(tmp_path, template.format(placement=placement)),
        _compile(tmp_path, template.format(placement=numeric)),
    )


def test_context_sensitive_css_with_use_is_typed_before_it_can_be_frozen(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <style>.special rect { fill:none }</style>
          <defs><g class="special"><rect id="r" width="4" height="4"/></g></defs>
          <use href="#r" x="10" fill="black"/>
        </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_CSS_USE_SHADOW_UNREPRESENTABLE"


@pytest.mark.parametrize("pseudo", ["lang(en)", "dir(rtl)", "not(:lang(en))"])
def test_inherited_context_pseudo_class_with_use_is_typed_before_css_is_frozen(
    tmp_path: Path, pseudo: str
) -> None:
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40">
          <style>rect:{pseudo} {{ fill:none }}</style>
          <g xml:lang="en">
            <rect id="r" width="4" height="4"/>
          </g>
          <use href="#r" x="10" xml:lang="fr" fill="black"/>
        </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_CSS_USE_SHADOW_UNREPRESENTABLE"


@pytest.mark.parametrize(
    "definitions",
    [
        """
          <linearGradient id="template" class="template"><stop/></linearGradient>
          <linearGradient id="paint" href="#template"/>
        """,
        """
          <pattern id="template" class="template" width="2" height="2">
            <rect width="2" height="2"/>
          </pattern>
          <pattern id="paint" href="#template"/>
        """,
    ],
)
def test_context_sensitive_css_with_paint_template_is_typed_before_freezing(
    tmp_path: Path, definitions: str
) -> None:
    content = f"""
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
        <style>.template * {{ opacity:0 }}</style>
        <defs>{definitions}</defs>
        <rect width="10" height="10" fill="url(#paint)"/>
      </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_CSS_PAINT_SHADOW_UNREPRESENTABLE"


def test_forward_gradient_reference_has_identical_computed_stop_alpha(
    tmp_path: Path,
) -> None:
    definition = """
      <defs>
        <linearGradient id="g" color="transparent" stop-color="transparent">
          <stop stop-color="currentColor"/>
          <stop offset="1" stop-color="inherit"/>
        </linearGradient>
      </defs>
    """
    geometry = """
      <rect width="5" height="5" fill="url(#g)"/>
      <rect x="7" width="5" height="5"/>
    """
    template = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 5">{}</svg>'
    before = _compile(tmp_path, template.format(definition + geometry))
    after = _compile(tmp_path, template.format(geometry + definition))
    _assert_equivalent(before, after)
    assert before.bounds == pytest.approx((7, 0, 12, 5))


@pytest.mark.parametrize(
    ("host_style", "stop_style"),
    [
        ('stop-color="transparent"', 'stop-color="inherit"'),
        ('stop-opacity="0"', 'stop-opacity="inherit"'),
    ],
)
def test_gradient_template_stops_inherit_from_the_consuming_shadow_host(
    tmp_path: Path, host_style: str, stop_style: str
) -> None:
    content = f"""
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 5">
        <defs>
          <linearGradient id="template"><stop {stop_style}/></linearGradient>
          <linearGradient id="paint" href="#template" {host_style}/>
        </defs>
        <rect width="5" height="5" fill="url(#paint)"/>
        <rect x="10" width="5" height="5"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((10, 0, 15, 5))


def test_noninherited_css_opacity_initial_unset_and_inherit_are_distinct(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 4">
          <g opacity=".5">
            <rect x="0" width="3" height="4" opacity="initial"/>
            <rect x="4" width="3" height="4" opacity="unset"/>
            <rect x="8" width="3" height="4" opacity="inherit"/>
          </g>
        </svg>
    """
    glyph = _compile(tmp_path, content, lossy=LossyPolicy.CONVERT)
    assert glyph.bounds == pytest.approx((0, 0, 11, 4))
    issues = {issue.code: issue for issue in glyph.issues}
    assert set(issues) == {"SVG_GROUP_OPACITY_APPROXIMATED"}
    # The group-level approximation covers every descendant's final partial
    # alpha. `initial` and `unset` still compute to 1 while `inherit` computes
    # to .5, but neither creates a second independent silhouette policy issue.


def test_css_wide_geometry_properties_are_materialized_before_outlining(
    tmp_path: Path,
) -> None:
    template = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
        <defs><clipPath id="clip"><rect width="8" height="10"/></clipPath></defs>
        <g fill-rule="evenodd" stroke-linecap="round" stroke-linejoin="bevel"
           stroke-miterlimit="8" vector-effect="none"
           clip-path="url(#clip)" transform="scale(2)">
          <path d="M1 1H9V9H1zM3 3H7V7H3z" fill="black" stroke="black"
                stroke-width="1" fill-rule="{value}" stroke-linecap="{value}"
                stroke-linejoin="{value}" stroke-miterlimit="{value}"
                vector-effect="{value}" clip-path="{clip_value}"/>
        </g>
      </svg>
    """
    inherited = _compile(tmp_path, template.format(value="inherit", clip_value="inherit"))
    explicit = _compile(
        tmp_path,
        template.format(value="inherit", clip_value="url(#clip)"),
    )
    _assert_equivalent(inherited, explicit)


@pytest.mark.parametrize("linejoin", ["arcs", "miter-clip"])
def test_svg2_stroke_joins_are_typed_before_the_bounded_stroker(
    tmp_path: Path, linejoin: str
) -> None:
    content = f"""
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
        <path d="M1 9L5 1L9 9" fill="none" stroke="black"
              stroke-width="2" stroke-linejoin="{linejoin}"/>
      </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_STROKE_JOIN_UNREPRESENTABLE"


@pytest.mark.parametrize(
    ("style", "code", "classification"),
    [
        (
            "<style>path:hover { fill: red }</style>",
            "SVG_CSS_ENVIRONMENT_UNREPRESENTABLE",
            SvgFeatureClass.UNREPRESENTABLE,
        ),
        (
            '<style>@import url("https://example.com/icon.css");</style>',
            "SVG_EXTERNAL_REFERENCE",
            None,
        ),
        (
            '<style>@supports (display: grid) { path { fill: url("remote.svg#paint") } }</style>',
            "SVG_EXTERNAL_REFERENCE",
            None,
        ),
    ],
)
def test_css_environment_or_external_state_is_never_guessed(
    tmp_path: Path,
    style: str,
    code: str,
    classification: SvgFeatureClass | None,
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'{style}<path d="M0 0h4v4z"/></svg>'
    )
    with pytest.raises(IconFontError) as caught:
        _compile(tmp_path, content)
    assert caught.value.diagnostic.code == code
    if classification is not None:
        assert isinstance(caught.value, SvgFeatureError)
        assert caught.value.classification is classification


def test_unconditional_and_never_media_rules_are_flattened_exactly(tmp_path: Path) -> None:
    conditional = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
        <style>
          @media all { rect { fill:black } }
          @media not all { rect { fill:none } }
        </style>
        <rect x="2" y="3" width="4" height="5" fill="none"/>
      </svg>
    """
    explicit = conditional.replace(
        "@media all { rect { fill:black } }", "rect { fill:black }"
    ).replace("@media not all { rect { fill:none } }", "")
    _assert_equivalent(_compile(tmp_path, conditional), _compile(tmp_path, explicit))


def test_selector_attribute_text_that_looks_dynamic_remains_static(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <style>[data-state=":hover"] { fill: black }</style>
          <rect data-state=":hover" x="2" y="3" width="4" height="5" fill="none"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((2, 3, 6, 8))


def test_css_selector_count_is_bounded_before_selector_compilation(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <style>rect, circle, ellipse, path::: { fill: black }</style><rect width="2" height="2"/>
        </svg>
    """
    with pytest.raises(IconFontError) as caught:
        _compile(tmp_path, content, max_expanded_elements=3)
    assert caught.value.diagnostic.code == "SVG_CSS_WORK_LIMIT"


@pytest.mark.parametrize(
    "stylesheet",
    [
        "@media all{" * 100 + "rect{fill:none}" + "}" * 100,
        "rect" + ":not(" * 100 + ".missing" + ")" * 100 + "{fill:none}",
    ],
)
def test_css_nesting_hits_a_stable_work_limit_before_python_recursion(
    tmp_path: Path, stylesheet: str
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<style>{stylesheet}</style><rect width="2" height="2"/></svg>'
    )
    with pytest.raises(IconFontError) as caught:
        _compile(tmp_path, content)
    assert caught.value.diagnostic.code == "SVG_CSS_WORK_LIMIT"


def test_css_sibling_scans_are_charged_quadratically(tmp_path: Path) -> None:
    siblings = "".join('<rect width="1" height="1"/>' for _ in range(50))
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<style>.never ~ rect { fill: black }</style>"
        f"{siblings}</svg>"
    )
    with pytest.raises(IconFontError) as caught:
        _compile(tmp_path, content, max_expanded_bytes=10_000)
    assert caught.value.diagnostic.code == "SVG_CSS_WORK_LIMIT"


def test_css_attribute_matching_charges_candidate_attribute_bytes(tmp_path: Path) -> None:
    selectors = ",".join(f'[data-x*="missing-{index}"]' for index in range(5))
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f"<style>{selectors}{{fill:none}}</style>"
        f'<rect data-x="{"x" * 5_000}" width="2" height="2"/></svg>'
    )
    with pytest.raises(IconFontError) as caught:
        _compile(tmp_path, content, max_expanded_bytes=10_000)
    assert caught.value.diagnostic.code == "SVG_CSS_WORK_LIMIT"


def test_non_css_style_element_is_inert_for_svg_rendering(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <style type="text/x-not-css">rect { fill: none }</style>
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((2, 3, 6, 8))


def test_inert_anchor_plain_switch_and_view_normalize_losslessly(tmp_path: Path) -> None:
    structured = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <view id="detail" viewBox="0 0 5 5"/>
        <a><g transform="translate(2 1)"><rect width="4" height="3"/></g></a>
        <switch>
          <rect x="10" y="2" width="3" height="4"/>
          <rect x="15" width="5" height="10"/>
        </switch>
      </svg>
    """
    explicit = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <g transform="translate(2 1)"><rect width="4" height="3"/></g>
        <rect x="10" y="2" width="3" height="4"/>
      </svg>
    """
    _assert_equivalent(_compile(tmp_path, structured), _compile(tmp_path, explicit))


def test_conditioned_switch_is_typed_as_environment_dependent(tmp_path: Path) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
        <switch>
          <rect width="5" height="5" systemLanguage="en"/>
          <rect width="10" height="10"/>
        </switch>
      </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_SWITCH_ENVIRONMENT_UNREPRESENTABLE"


@pytest.mark.parametrize(
    "effect",
    [
        'filter="none" mask="none"',
        'style="filter:none;mask:none"',
    ],
)
def test_literal_filter_and_mask_none_are_exact_noops(tmp_path: Path, effect: str) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
        '<filter id="f"><feGaussianBlur stdDeviation="2"/></filter>'
        '<mask id="m"><rect width="10" height="10"/></mask></defs>'
        f'<rect x="2" y="3" width="4" height="5" {effect}/></svg>'
    )
    expected = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect x="2" y="3" width="4" height="5"/></svg>'
    )
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_unreachable_unsupported_definitions_are_pruned_after_hard_scan(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <defs>
            <filter id="unused"><feGaussianBlur stdDeviation="2"/></filter>
            <mask id="unused-mask"><rect width="10" height="10"/></mask>
            <g id="unused-group"><image/><animate attributeName="opacity"/></g>
          </defs>
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_metadata_namespace_resets_are_dropped_as_one_inert_subtree(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <metadata xmlns=""><editor><nested key="value"/></editor></metadata>
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


@pytest.mark.parametrize(
    "display",
    ["block", "flex", "flow-root", "grid", "inline-block", "table"],
)
def test_static_non_none_display_modes_preserve_svg_geometry(tmp_path: Path, display: str) -> None:
    styled = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<g display="{display}"><rect x="2" y="3" width="4" height="5"/></g></svg>'
    )
    expected = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect x="2" y="3" width="4" height="5"/></svg>'
    )
    _assert_equivalent(_compile(tmp_path, styled), _compile(tmp_path, expected))


def test_display_none_prunes_unrepresentable_render_branch_after_hard_scan(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <foreignObject display="none" width="10" height="10"/>
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_zero_opacity_prunes_unrepresentable_render_branch_after_hard_scan(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <g opacity="0"><foreignObject width="10" height="10"/></g>
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


@pytest.mark.parametrize("hidden", ['display="none"', 'opacity="0"'])
def test_pruning_preserves_targets_referenced_outside_a_hidden_ancestor(
    tmp_path: Path, hidden: str
) -> None:
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <g {hidden}><rect id="r" x="2" y="3" width="4" height="5"/></g>
          <use href="#r" x="10"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <rect x="12" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_non_geometric_svg_hints_do_not_block_exact_outlining(tmp_path: Path) -> None:
    hinted = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"
                shape-rendering="crispEdges" color-rendering="optimizeSpeed"
                image-rendering="pixelated" color-interpolation="linearRGB"
                pointer-events="none" cursor="crosshair" tabindex="0"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, hinted), _compile(tmp_path, expected))


def test_symbol_viewport_root_preserve_aspect_ratio_and_root_transform_are_exact(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="24"
             viewBox="0 0 24 24" preserveAspectRatio="xMidYMid meet"
             transform="translate(2 0)">
          <defs>
            <symbol id="tile" viewBox="0 0 10 20" preserveAspectRatio="none">
              <rect width="10" height="20"/>
            </symbol>
          </defs>
          <use href="#tile" x="4" y="2" width="12" height="10"/>
        </svg>
    """
    explicit = """
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="24"
             viewBox="0 0 48 24">
          <rect x="18" y="2" width="12" height="10"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, explicit))


def test_symbol_use_absolute_css_lengths_are_resolved(tmp_path: Path) -> None:
    absolute = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20">
          <defs><symbol id="s" viewBox="0 0 10 10"><rect width="10" height="10"/></symbol></defs>
          <use href="#s" x="5px" y="2pt" width="10px" height=".5in"/>
        </svg>
    """
    numeric = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20">
          <defs><symbol id="s" viewBox="0 0 10 10"><rect width="10" height="10"/></symbol></defs>
          <use href="#s" x="5" y="2.666666666666667" width="10" height="48"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, absolute), _compile(tmp_path, numeric))


def test_symbol_instance_forces_its_definition_root_display_to_inline(tmp_path: Path) -> None:
    hidden_symbol = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><defs>
          <symbol id="s" display="none" viewBox="0 0 4 4"><rect width="4" height="4"/></symbol>
        </defs><use href="#s" x="10" width="4" height="4"/></svg>
    """
    visible_symbol = hidden_symbol.replace(' display="none"', "")
    _assert_equivalent(_compile(tmp_path, hidden_symbol), _compile(tmp_path, visible_symbol))


def test_symbol_definition_geometry_cannot_override_use_instance_viewport(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30"><defs>
          <symbol id="s" x="2" y="3" width="4" height="5"
                  viewBox="0 0 4 5" preserveAspectRatio="none">
            <rect width="4" height="5"/>
          </symbol></defs>
          <use href="#s" x="10" y="8" width="8" height="8"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 30">
          <rect x="12" y="11" width="8" height="8"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_symbol_reference_point_aligns_the_instance_viewport_exactly(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>
          <symbol id="s" refX="center" refY="bottom" viewBox="0 0 4 4">
            <rect width="4" height="4"/>
          </symbol></defs>
          <use href="#s" x="8" y="8" width="4" height="4"/>
        </svg>
    """

    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <rect x="6" y="4" width="4" height="4"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_symbol_dimensions_supply_omitted_use_viewport_defaults(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>
          <symbol id="s" width="8" height="10" viewBox="0 0 4 5"
                  preserveAspectRatio="none">
            <rect width="4" height="5"/>
          </symbol></defs>
          <use href="#s" x="2" y="3"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <rect x="2" y="3" width="8" height="10"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_root_transform_is_applied_in_materialized_viewport_coordinates(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"
             viewBox="0 0 10 10" preserveAspectRatio="xMidYMid meet"
             transform="translate(2 0) scale(2)">
          <rect width="2" height="2"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.view_box == pytest.approx((0, 0, 40, 20))
    assert glyph.bounds == pytest.approx((22, 0, 30, 8))


def test_transform_parser_consumes_every_byte_and_normalizes_css_units(tmp_path: Path) -> None:
    with pytest.raises(IconFontError) as caught:
        _compile(
            tmp_path,
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '<rect width="2" height="2" transform="translate(5 0) garbage"/></svg>',
        )
    assert caught.value.diagnostic.code == "SVG_TRANSFORM_INVALID"

    absolute = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
          <rect width="4" height="2" transform="translate(1in 2.5cm) rotate(.25turn)"/>
        </svg>
    """
    numeric = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
          <rect width="4" height="2" transform="translate(96 94.48818897637796) rotate(90)"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, absolute), _compile(tmp_path, numeric))


@pytest.mark.parametrize(
    ("transform", "numeric"),
    [
        ("translate(50% 25%)", "translate(10 2.5)"),
        ("translateX(25%)", "translate(5 0)"),
        ("translate(calc(2px + 3px) calc(1pt + 2pt))", "translate(5 4)"),
    ],
)
def test_bounded_percentage_and_constant_calc_transforms_are_exact(
    tmp_path: Path, transform: str, numeric: str
) -> None:
    template = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <rect width="2" height="2" transform="{transform}"/>
      </svg>
    """
    _assert_equivalent(
        _compile(tmp_path, template.format(transform=transform)),
        _compile(tmp_path, template.format(transform=numeric)),
    )


def test_environment_dependent_transform_length_is_typed(tmp_path: Path) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <rect width="2" height="2" transform="translate(1em)"/>
      </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_TRANSFORM_ENVIRONMENT_UNREPRESENTABLE"


def test_root_absolute_css_lengths_are_lossless_but_host_percentages_need_embedding(
    tmp_path: Path,
) -> None:
    absolute = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="0.5in" '
        'viewBox="0 0 10 5"><rect width="10" height="5"/></svg>'
    )
    glyph = _compile(tmp_path, absolute)
    assert glyph.view_box == pytest.approx((0, 0, 96, 48))

    percentage = absolute.replace('width="1in"', 'width="100%"')
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, percentage)
    assert caught.value.diagnostic.code == "SVG_ROOT_VIEWPORT_UNREPRESENTABLE"

    malformed = absolute.replace('width="1in"', 'width="banana"')
    with pytest.raises(IconFontError) as malformed_caught:
        _compile(tmp_path, malformed)
    assert type(malformed_caught.value) is IconFontError
    assert malformed_caught.value.diagnostic.code == "SVG_ROOT_LENGTH_INVALID"


def test_zero_sized_viewbox_is_typed_as_an_unrepresentable_empty_icon(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 24"><path d="M0 0h1v1z"/></svg>'
    )
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.feature == "empty-viewport"
    assert caught.value.diagnostic.code == "SVG_EMPTY_OUTLINE"


@pytest.mark.parametrize(
    ("definitions", "expected_bounds"),
    [
        (
            '<clipPath id="clip" clipPathUnits="objectBoundingBox">'
            '<rect width=".5" height="1"/></clipPath>',
            (4, 2, 10, 12),
        ),
        (
            '<clipPath id="clip" clipPathUnits="objectBoundingBox">'
            '<rect width="50%" height="100%"/></clipPath>',
            (4, 2, 10, 12),
        ),
        (
            '<clipPath id="clip"><rect width="5" height="10" '
            'clip-path="url(#inner)"/><rect visibility="hidden" width="10" height="10"/>'
            '</clipPath><clipPath id="inner"><rect width="10" height="5"/></clipPath>',
            (4, 2, 5, 5),
        ),
        (
            '<rect id="clipShape" x="2" width="4" height="8"/>'
            '<clipPath id="clip"><use href="#clipShape"/></clipPath>',
            (4, 2, 6, 8),
        ),
        (
            '<clipPath id="clip"><g visibility="hidden">'
            '<rect visibility="visible" x="2" width="4" height="8"/>'
            '<rect x="8" width="2" height="10"/></g></clipPath>',
            (4, 2, 6, 8),
        ),
    ],
)
def test_clip_paths_support_object_bbox_nested_use_and_visibility(
    tmp_path: Path,
    definitions: str,
    expected_bounds: tuple[float, float, float, float],
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>'
        f'{definitions}</defs><rect x="4" y="2" width="12" height="10" '
        'clip-path="url(#clip)"/></svg>'
    )
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx(expected_bounds)
    assert glyph.issues == ()


def test_nested_svg_viewport_inside_clip_is_materialized_before_clipping(
    tmp_path: Path,
) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10">
        <defs>
          <clipPath id="clip">
            <svg x="10" width="10" height="10" viewBox="0 0 1 1"
                 preserveAspectRatio="none">
              <rect width="1" height="1"/>
            </svg>
          </clipPath>
        </defs>
        <rect width="30" height="10" clip-path="url(#clip)"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((10, 0, 20, 10))
    assert glyph.issues == ()


def test_object_bbox_effects_are_ignored_for_degenerate_geometry_bbox(
    tmp_path: Path,
) -> None:
    template = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 12">
        <defs>{definition}</defs>
        <line x1="5" y1="0" x2="5" y2="10" fill="none" stroke="{stroke}"
              stroke-width="2" {effect}/>
        <rect x="18" y="10" width="1" height="1"/>
      </svg>
    """
    clipped = _compile(
        tmp_path,
        template.format(
            definition=(
                '<clipPath id="effect" clipPathUnits="objectBoundingBox">'
                '<rect width="1" height="1"/></clipPath>'
            ),
            stroke="black",
            effect='clip-path="url(#effect)"',
        ),
    )
    assert clipped.bounds == pytest.approx((4, 0, 19, 11))

    painted = _compile(
        tmp_path,
        template.format(
            definition='<linearGradient id="effect"><stop/></linearGradient>',
            stroke="url(#effect)",
            effect="",
        ),
    )
    assert painted.bounds == pytest.approx((18, 10, 19, 11))
    assert clipped.issues == painted.issues == ()


@pytest.mark.parametrize("view_box", ["0 0 0 10", "0 0 10 0"])
def test_zero_nested_viewbox_disables_rendering_exactly(tmp_path: Path, view_box: str) -> None:
    content = f"""
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <svg width="10" height="10" viewBox="{view_box}">
          <rect width="10" height="10"/>
        </svg>
        <rect x="18" width="1" height="1"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((18, 0, 19, 1))
    assert glyph.issues == ()


def test_evenodd_clip_hole_is_preserved_in_booleanized_geometry(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <defs>
            <clipPath id="ring">
              <path clip-rule="evenodd" d="M0 0h10v10H0zM3 3h4v4H3z"/>
            </clipPath>
          </defs>
          <rect width="10" height="10" clip-path="url(#ring)"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((0, 0, 10, 10))
    assert glyph.paths == ("M0,0 L10,0 L10,10 L0,10 Z M3,3 L3,7 L7,7 L7,3 Z",)


def test_odd_dash_pattern_matches_its_explicit_even_repeat_on_a_curve(tmp_path: Path) -> None:
    template = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <path d="M1 5 C4 1 16 9 19 5" fill="none" stroke="black"
                stroke-width="2" stroke-dasharray="{pattern}" stroke-dashoffset="-2"/>
        </svg>
    """
    odd = _compile(tmp_path, template.format(pattern="3 1 2"))
    explicit = _compile(tmp_path, template.format(pattern="3 1 2 3 1 2"))
    _assert_equivalent(odd, explicit)
    assert odd.path_command_count == 25


def test_percentage_dashes_resolve_against_normalized_viewport_diagonal(
    tmp_path: Path,
) -> None:
    percentage = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
          <path d="M5 50H95" fill="none" stroke="black" stroke-width="4"
                stroke-dasharray="10% 5%" stroke-dashoffset="2.5%"/>
        </svg>
    """
    explicit = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
          <path d="M5 50H95" fill="none" stroke="black" stroke-width="4"
                stroke-dasharray="10 5" stroke-dashoffset="2.5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, percentage), _compile(tmp_path, explicit))


def test_nested_percentage_viewport_and_local_percentage_dash_are_exact(
    tmp_path: Path,
) -> None:
    percentage = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">
          <svg x="10%" y="10%" width="50%" height="50%" viewBox="0 0 50 30">
            <path d="M2 15H48" fill="none" stroke="black" stroke-width="2"
                  stroke-dasharray="10% 5%"/>
          </svg>
        </svg>
    """
    local_diagonal = (50**2 + 30**2) ** 0.5 / 2**0.5
    explicit = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">
          <svg x="10" y="6" width="50" height="30" viewBox="0 0 50 30">
            <path d="M2 15H48" fill="none" stroke="black" stroke-width="2"
                  stroke-dasharray="{local_diagonal * 0.1} {local_diagonal * 0.05}"/>
          </svg>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, percentage), _compile(tmp_path, explicit))


def test_absolute_css_dash_lengths_are_normalized_losslessly(tmp_path: Path) -> None:
    absolute = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 20">
          <path d="M2 10H118" fill="none" stroke="black" stroke-width="2"
                stroke-dasharray="0.125in 6pt"/>
        </svg>
    """
    explicit = absolute.replace("0.125in 6pt", "12 8")
    _assert_equivalent(_compile(tmp_path, absolute), _compile(tmp_path, explicit))


@pytest.mark.parametrize(
    ("dash, expected_type, code"),
    [
        ("1em 2em", SvgFeatureError, "SVG_DASH_LENGTH_UNREPRESENTABLE"),
        ("banana", IconFontError, "SVG_DASH_INVALID"),
        ("1,,2", IconFontError, "SVG_DASH_INVALID"),
    ],
)
def test_dash_length_environment_is_distinct_from_malformed_input(
    tmp_path: Path,
    dash: str,
    expected_type: type[IconFontError],
    code: str,
) -> None:
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <path d="M1 5H19" fill="none" stroke="black" stroke-dasharray="{dash}"/>
        </svg>
    """
    with pytest.raises(expected_type) as caught:
        _compile(tmp_path, content)
    assert caught.value.diagnostic.code == code


def test_path_length_is_inert_without_dashes_but_calibrated_dashes_are_explicitly_out(
    tmp_path: Path,
) -> None:
    plain = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <path d="M1 1H19V9H1z" pathLength="100"/>
        </svg>
    """
    reference = plain.replace(' pathLength="100"', "")
    _assert_equivalent(_compile(tmp_path, plain), _compile(tmp_path, reference))

    dashed = plain.replace(
        'pathLength="100"',
        'pathLength="100" fill="none" stroke="black" stroke-dasharray="2 1"',
    )
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, dashed)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_PATH_LENGTH_DASH_UNREPRESENTABLE"


def test_tiny_dash_pattern_hits_pre_stroke_work_limit(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
          <path d="M1 5H19" fill="none" stroke="black" stroke-width="2"
                stroke-dasharray=".000001 .000001"/>
        </svg>
    """
    with pytest.raises(IconFontError) as caught:
        _compile(tmp_path, content, max_path_commands=1_000)
    assert caught.value.diagnostic.code == "SVG_DASH_EXPANSION_LIMIT"
    assert caught.value.diagnostic.details["estimatedPathCommands"] > 1_000


def test_non_scaling_stroke_keeps_viewport_width_while_normal_stroke_scales(
    tmp_path: Path,
) -> None:
    template = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
          <path d="M1 5H9" transform="scale(10)" fill="none" stroke="black"
                stroke-width="2" {effect}/>
        </svg>
    """
    normal = _compile(tmp_path, template.format(effect=""))
    non_scaling = _compile(
        tmp_path,
        template.format(effect='vector-effect="non-scaling-stroke"'),
    )
    assert normal.bounds == pytest.approx((10, 40, 90, 60))
    assert non_scaling.bounds == pytest.approx((10, 49, 90, 51))
    assert normal.issues == non_scaling.issues == ()


def test_object_bbox_clip_uses_original_group_geometry_before_stroke_expansion(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 30 30">
          <defs>
            <clipPath id="half" clipPathUnits="objectBoundingBox">
              <rect width=".5" height="1"/>
            </clipPath>
          </defs>
          <g clip-path="url(#half)">
            <rect width="10" height="10"/>
            <path d="M0 5H10" fill="none" stroke="black" stroke-width="10"
                  vector-effect="non-scaling-stroke"/>
          </g>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((10, 10, 15, 20))
    assert glyph.issues == ()


def test_marker_context_paint_orientation_and_user_space_units_are_exact(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <defs>
            <marker id="arrow" markerWidth="4" markerHeight="4" refX="4" refY="2"
                    orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0 0L4 2L0 4z" fill="context-stroke"/>
            </marker>
          </defs>
          <path d="M2 10H18" fill="none" stroke="black" stroke-width="2"
                marker-end="url(#arrow)"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((2, 8, 18, 12))
    assert glyph.paths[-1] == "M14,8 L18,10 L14,12 Z"
    assert glyph.issues == ()


@pytest.mark.parametrize("paint", ["context-fill", "context-stroke"])
def test_context_paint_without_an_instance_context_is_typed(tmp_path: Path, paint: str) -> None:
    content = f"""
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
        <rect width="10" height="10" fill="{paint}"/>
      </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == "SVG_CONTEXT_PAINT_UNREPRESENTABLE"


def test_reversing_mid_marker_uses_incoming_direction_for_zero_vector_sum(
    tmp_path: Path,
) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <defs>
          <marker id="m" markerWidth="4" markerHeight="2" refX="0" refY="1"
                  markerUnits="userSpaceOnUse" orient="auto" overflow="visible">
            <rect width="4" height="2"/>
          </marker>
        </defs>
        <path d="M5 5L10 5L5 5" fill="none" stroke="none" marker-mid="url(#m)"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((10, 4, 14, 6))
    assert glyph.issues == ()


def test_zero_marker_viewbox_disables_the_marker_instance(tmp_path: Path) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <defs>
          <marker id="m" markerWidth="4" markerHeight="4" viewBox="0 0 0 4">
            <rect width="4" height="4"/>
          </marker>
        </defs>
        <path d="M2 5H8" fill="none" stroke="none" marker-end="url(#m)"/>
        <rect x="18" width="1" height="1"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((18, 0, 19, 1))
    assert glyph.issues == ()


def test_marker_container_opacity_is_never_discarded(tmp_path: Path) -> None:
    zero = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>
          <marker id="m" markerWidth="4" markerHeight="4" refX="2" refY="2"
                  markerUnits="userSpaceOnUse" opacity="0">
            <rect width="4" height="4"/>
          </marker></defs>
          <path d="M2 10H16" fill="none" stroke="none" marker-end="url(#m)"/>
          <rect width="2" height="2"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <rect width="2" height="2"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, zero), _compile(tmp_path, expected))

    partial = zero.replace('opacity="0"', 'opacity=".5"')
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, partial)
    assert caught.value.diagnostic.code == "SVG_PARTIAL_ALPHA_APPROXIMATED"


def test_marked_target_opacity_applies_to_target_and_marker_as_one_group(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>
          <marker id="m" markerWidth="4" markerHeight="4" refX="2" refY="2"
                  markerUnits="userSpaceOnUse"><rect width="4" height="4"/></marker>
        </defs><path d="M2 10H16" fill="none" stroke="black" opacity=".5"
                     marker-end="url(#m)"/></svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.diagnostic.code == "SVG_GROUP_OPACITY_APPROXIMATED"


def test_marker_container_clip_is_applied_to_every_instance(tmp_path: Path) -> None:
    clipped = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>
          <clipPath id="half"><rect width="2" height="4"/></clipPath>
          <marker id="m" markerWidth="4" markerHeight="4" refX="2" refY="2"
                  markerUnits="userSpaceOnUse" clip-path="url(#half)">
            <rect width="4" height="4"/>
          </marker></defs>
          <path d="M2 10H16" fill="none" stroke="none" marker-end="url(#m)"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <rect x="14" y="8" width="2" height="4"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, clipped), _compile(tmp_path, expected))


@pytest.mark.parametrize("hidden", ['display="none"', 'opacity="0"'])
def test_hidden_render_ancestor_does_not_suppress_referenced_marker_definition(
    tmp_path: Path, hidden: str
) -> None:
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <g {hidden}><defs>
            <marker id="m" markerWidth="4" markerHeight="4" refX="2" refY="2"
                    markerUnits="userSpaceOnUse"><rect width="4" height="4"/></marker>
          </defs></g>
          <path d="M2 10H16" fill="none" stroke="none" marker-end="url(#m)"/>
          <rect width="1" height="1"/>
        </svg>
    """
    expected = content.replace(f"<g {hidden}>", "<g>")
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_object_bbox_clip_uses_original_group_geometry_before_marker_expansion(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20">
          <defs>
            <clipPath id="half" clipPathUnits="objectBoundingBox">
              <rect width=".5" height="1"/>
            </clipPath>
            <marker id="extension" markerWidth="10" markerHeight="10"
                    refX="0" refY="5" orient="0" markerUnits="userSpaceOnUse">
              <rect width="10" height="10"/>
            </marker>
          </defs>
          <g clip-path="url(#half)">
            <rect width="10" height="10"/>
            <path d="M0 5H10" fill="none" stroke="black"
                  marker-end="url(#extension)"/>
          </g>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((0, 0, 5, 10))
    assert glyph.issues == ()


def test_object_bbox_clip_on_marked_geometry_also_clips_expanded_marker(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 40">
          <defs>
            <clipPath id="half" clipPathUnits="objectBoundingBox">
              <rect width=".5" height="1"/>
            </clipPath>
            <marker id="extension" markerWidth="10" markerHeight="10"
                    refX="0" refY="5" orient="0" markerUnits="userSpaceOnUse">
              <rect width="10" height="10"/>
            </marker>
          </defs>
          <path d="M0 0V10H10" transform="translate(3 4) scale(2)"
                marker-end="url(#extension)"
                clip-path="url(#half)"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((3, 4, 13, 24))
    assert glyph.issues == ()


def test_start_mid_end_markers_and_stroke_width_units_expand_at_every_vertex(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <defs>
            <marker id="dot" markerWidth="2" markerHeight="2" refX="1" refY="1"
                    markerUnits="strokeWidth">
              <circle cx="1" cy="1" r="1" fill="context-stroke"/>
            </marker>
          </defs>
          <path d="M5 5H15V15" fill="none" stroke="black" stroke-width="2"
                marker-start="url(#dot)" marker-mid="url(#dot)"
                marker-end="url(#dot)"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((3, 3, 17, 17))
    assert len(glyph.paths) == 4


def test_arc_marker_tangent_and_zero_length_segments_use_adjacent_direction(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
          <defs>
            <marker id="arrow" markerWidth="4" markerHeight="4" refX="4" refY="2"
                    orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0 0L4 2L0 4z"/>
            </marker>
          </defs>
          <path d="M2 12 A10 10 0 0 1 12 2 L12 2 L22 12" fill="none"
                stroke="black" marker-mid="url(#arrow)" marker-end="url(#arrow)"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx(
        (1.5, -1.378000020980835, 22.354000091552734, 12.354000091552734)
    )
    assert glyph.paths[1] == "M9.07,-1.378 L12,2 L7.539,2.317 Z"
    assert glyph.paths[2] == glyph.paths[1]
    assert glyph.paths[3] == "M20.586,7.757 L22,12 L17.757,10.586 Z"
    assert glyph.issues == ()


def test_arc_cubic_subdivisions_do_not_create_spurious_mid_markers(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20">
          <defs>
            <marker id="dot" markerWidth="2" markerHeight="2" refX="1" refY="1"
                    markerUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="1"/>
            </marker>
          </defs>
          <path d="M5 10 A10 10 0 1 1 25 10" fill="none" stroke="black"
                marker-mid="url(#dot)"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert len(glyph.paths) == 1
    assert glyph.issues == ()


@pytest.mark.parametrize(
    "orient",
    ["90", "90deg", "100grad", "1.5707963267948966rad", ".25turn"],
)
def test_marker_angle_units_are_normalized_losslessly(tmp_path: Path, orient: str) -> None:
    template = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <defs><marker id="m" markerWidth="4" markerHeight="4"
                  refX="0" refY="0" markerUnits="userSpaceOnUse" orient="{orient}">
            <path d="M0 0L4 0L0 2z"/>
          </marker></defs>
          <path d="M2 10L12 10" fill="none" stroke="black" marker-end="url(#m)"/>
        </svg>
    """
    _assert_equivalent(
        _compile(tmp_path, template.format(orient=orient)),
        _compile(tmp_path, template.format(orient="90")),
    )


@pytest.mark.parametrize(
    ("reference", "numeric"),
    [
        ('refX="center" refY="center"', 'refX="2" refY="2"'),
        ('refX="50%" refY="50%"', 'refX="2" refY="2"'),
        ('refX="right" refY="bottom"', 'refX="4" refY="4"'),
    ],
)
def test_marker_reference_keywords_and_percentages_are_normalized(
    tmp_path: Path, reference: str, numeric: str
) -> None:
    template = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>
          <marker id="m" markerWidth="4" markerHeight="4" viewBox="0 0 4 4"
                  markerUnits="userSpaceOnUse" {reference}>
            <rect width="4" height="4"/>
          </marker></defs>
          <path d="M2 10H16" fill="none" stroke="none" marker-end="url(#m)"/>
        </svg>
    """
    _assert_equivalent(
        _compile(tmp_path, template.format(reference=reference)),
        _compile(tmp_path, template.format(reference=numeric)),
    )


def test_absolute_css_units_on_geometry_and_strokes_are_resolved(tmp_path: Path) -> None:
    absolute = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
          <rect x="1cm" y="5pt" width="1in" height="10mm"
                fill="none" stroke="black" stroke-width="2pt"/>
          <circle cx="150px" cy="50px" r="5pt"/>
        </svg>
    """
    numeric = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
          <rect x="37.79527559055118" y="6.666666666666667" width="96"
                height="37.79527559055118" fill="none" stroke="black"
                stroke-width="2.666666666666667"/>
          <circle cx="150" cy="50" r="6.666666666666667"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, absolute), _compile(tmp_path, numeric))


def test_inert_stroke_metrics_do_not_require_a_length_environment(tmp_path: Path) -> None:
    inert = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5" stroke="none"
                stroke-dasharray="1em 2em" stroke-dashoffset="3em"
                pathLength="7" vector-effect="non-scaling-stroke"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, inert), _compile(tmp_path, expected))


def test_multiple_opaque_paints_and_opaque_gradient_are_exact_monochrome_coverage(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 4">
          <defs>
            <linearGradient id="opaque"><stop stop-color="red"/>
              <stop offset="1" stop-color="blue"/></linearGradient>
          </defs>
          <rect width="4" height="4" fill="red"/>
          <rect x="4" width="4" height="4" fill="blue"/>
          <rect x="8" width="4" height="4" fill="url(#opaque)"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((0, 0, 12, 4))
    assert glyph.issues == ()


def test_local_paint_server_fallback_is_accepted_when_the_server_resolves(
    tmp_path: Path,
) -> None:
    with_fallback = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>
          <linearGradient id="g"><stop stop-color="red"/><stop offset="1" stop-color="blue"/></linearGradient>
        </defs><rect x="2" y="3" width="4" height="5" fill="url(#g) hotpink"/></svg>
    """
    without_fallback = with_fallback.replace("url(#g) hotpink", "url(#g)")
    _assert_equivalent(
        _compile(tmp_path, with_fallback),
        _compile(tmp_path, without_fallback),
    )


@pytest.mark.parametrize(
    "pattern",
    [
        '<pattern id="p"/>',
        '<pattern id="p" width="0" height="2"><rect width="2" height="2"/></pattern>',
        '<pattern id="base" width="2" height="2"/><pattern id="p" href="#base"/>',
        '<pattern id="p" width="2" height="2"><rect width="2" height="2" fill="none"/></pattern>',
        '<pattern id="p" width="2" height="2"><rect width="0" height="2"/></pattern>',
        '<pattern id="p" width="2" height="2">'
        '<g opacity="0"><rect width="2" height="2"/></g></pattern>',
    ],
)
def test_empty_or_zero_sized_patterns_are_exactly_unpainted(tmp_path: Path, pattern: str) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 5"><defs>'
        f'{pattern}</defs><rect width="5" height="5" fill="url(#p)"/>'
        '<rect x="7" width="5" height="5"/></svg>'
    )
    expected = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 5">'
        '<rect x="7" width="5" height="5"/></svg>'
    )
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_zero_pattern_viewbox_is_exactly_unpainted(tmp_path: Path) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 5">
        <defs>
          <pattern id="p" width="2" height="2" viewBox="0 0 0 2">
            <rect width="2" height="2"/>
          </pattern>
        </defs>
        <rect width="5" height="5" fill="url(#p)"/>
        <rect x="10" width="5" height="5"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((10, 0, 15, 5))
    assert glyph.issues == ()


def test_gradient_stop_current_color_and_transparent_alpha_are_computed(
    tmp_path: Path,
) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 5">
          <defs>
            <linearGradient id="g" color="transparent" stop-color="transparent">
              <stop stop-color="currentColor"/>
              <stop offset="1" stop-color="inherit"/>
            </linearGradient>
          </defs>
          <rect width="5" height="5" fill="url(#g)"/>
          <rect x="7" width="5" height="5"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 5">
          <rect x="7" width="5" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


@pytest.mark.parametrize(
    ("stops", "expected_x"),
    [
        ('<stop/><stop offset="1" stop-opacity="0"/>', 10),
        ('<stop stop-opacity="0"/><stop offset="1"/>', 0),
    ],
)
def test_degenerate_linear_gradient_uses_the_last_stop_exactly(
    tmp_path: Path, stops: str, expected_x: int
) -> None:
    content = f"""
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 5">
        <defs>
          <linearGradient id="g" x1="25%" y1="50%" x2="25%" y2="50%">
            {stops}
          </linearGradient>
        </defs>
        <rect width="5" height="5" fill="url(#g)"/>
        <rect x="10" width="5" height="5"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((expected_x, 0, 15, 5))
    assert glyph.issues == ()


def test_coincident_radial_gradient_circles_are_exactly_unpainted(tmp_path: Path) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 5">
        <defs>
          <radialGradient id="g" cx="50%" cy="50%" r="50%"
                          fx="50%" fy="50%" fr="50%">
            <stop/><stop offset="1"/>
          </radialGradient>
        </defs>
        <rect width="5" height="5" fill="url(#g)"/>
        <rect x="10" width="5" height="5"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((10, 0, 15, 5))
    assert glyph.issues == ()


def test_noncovering_radial_gradient_requires_explicit_painted_shape_loss(
    tmp_path: Path,
) -> None:
    content = """
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10">
        <defs>
          <radialGradient id="g" gradientUnits="userSpaceOnUse"
                          cx="5" cy="5" r="2" fx="10" fy="5" fr="0">
            <stop/><stop offset="1"/>
          </radialGradient>
        </defs>
        <rect width="12" height="10" fill="url(#g)"/>
        <rect x="18" width="1" height="1"/>
      </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.diagnostic.code == "SVG_GRADIENT_COVERAGE_APPROXIMATED"

    glyph = _compile(tmp_path, content, lossy=LossyPolicy.CONVERT)
    assert glyph.bounds == pytest.approx((0, 0, 19, 10))
    issue = next(issue for issue in glyph.issues if issue.feature == "radial-gradient-coverage")
    assert issue.details["approximation"] == "painted-shape-silhouette"


@pytest.mark.parametrize(
    ("reference", "definition", "expected_x"),
    [
        ("url(#missing)", "", 10),
        ("url(#missing) none", "", 10),
        ("url(#missing) red", "", 0),
        ("url(#wrong)", '<path id="wrong" d="M0 0h1v1z"/>', 10),
        ("url(#wrong) red", '<path id="wrong" d="M0 0h1v1z"/>', 0),
    ],
)
def test_invalid_paint_server_reference_uses_svg_fallback_exactly(
    tmp_path: Path, reference: str, definition: str, expected_x: int
) -> None:
    content = f"""
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 15 5">
        <defs>{definition}</defs>
        <rect width="5" height="5" fill="{reference}"/>
        <rect x="10" width="5" height="5"/>
      </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((expected_x, 0, 15, 5))
    assert glyph.issues == ()


@pytest.mark.parametrize(
    "opacities",
    [("1", ".9999999999"), (".9999999999", "1")],
)
def test_gradient_alpha_fidelity_never_uses_numeric_tolerance(
    tmp_path: Path, opacities: tuple[str, str]
) -> None:
    first, second = opacities
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
        f'<linearGradient id="g"><stop stop-opacity="{first}"/>'
        f'<stop offset="1" stop-opacity="{second}"/></linearGradient></defs>'
        '<rect width="10" height="10" fill="url(#g)"/></svg>'
    )
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.diagnostic.code == "SVG_GRADIENT_ALPHA_APPROXIMATED"


def test_css_color_four_alpha_is_part_of_the_typed_fidelity_policy(tmp_path: Path) -> None:
    direct = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect width="10" height="10" fill="color(display-p3 1 0 0 / .5)"/>
        </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, direct)
    assert caught.value.diagnostic.code == "SVG_PARTIAL_ALPHA_APPROXIMATED"

    gradient = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>
          <linearGradient id="g">
            <stop stop-color="oklab(50% 0 0 / 0)"/>
            <stop offset="1" stop-color="oklab(50% 0 0 / 1)"/>
          </linearGradient></defs>
          <rect width="10" height="10" fill="url(#g)"/>
        </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, gradient)
    assert caught.value.diagnostic.code == "SVG_GRADIENT_ALPHA_APPROXIMATED"

    opaque = direct.replace(" / .5", "")
    assert _compile(tmp_path, opaque).issues == ()


def test_partial_alpha_fully_overpainted_by_opaque_geometry_is_still_exact(tmp_path: Path) -> None:
    content = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
          <rect width="10" height="10" opacity=".5"/>
          <rect width="10" height="10"/>
        </svg>
    """
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((0, 0, 10, 10))
    assert glyph.issues == ()


@pytest.mark.parametrize(
    "lossy_region",
    [
        (
            '<defs><linearGradient id="g"><stop stop-opacity="0"/>'
            '<stop offset="1" stop-opacity="1"/></linearGradient></defs>'
            '<rect width="10" height="10" fill="url(#g)"/>'
        ),
        (
            '<defs><pattern id="p" width="2" height="2" patternUnits="userSpaceOnUse">'
            '<rect width="1" height="1"/></pattern></defs>'
            '<rect width="10" height="10" fill="url(#p)"/>'
        ),
        ('<g opacity=".5"><rect width="4" height="10"/><rect x="6" width="4" height="10"/></g>'),
    ],
)
def test_later_opaque_paint_eliminates_deferred_lossy_regions(
    tmp_path: Path,
    lossy_region: str,
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'{lossy_region}<rect width="10" height="10"/></svg>'
    )
    glyph = _compile(tmp_path, content)
    assert glyph.bounds == pytest.approx((0, 0, 10, 10))
    assert glyph.issues == ()


@pytest.mark.parametrize("precision", [0, 1, 3, 6])
@pytest.mark.parametrize(
    ("content", "code"),
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '<rect width="10" height="10" opacity=".0004"/></svg>',
            "SVG_PARTIAL_ALPHA_APPROXIMATED",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '<rect width="10" height="10" opacity=".9996"/></svg>',
            "SVG_PARTIAL_ALPHA_APPROXIMATED",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>'
            '<pattern id="p" width="2" height="2"><rect width="1" height="1"/>'
            '</pattern></defs><rect width="10" height="10" fill="url(#p)"/></svg>',
            "SVG_PATTERN_APPROXIMATED",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs>'
            '<linearGradient id="g"><stop stop-opacity="0"/>'
            '<stop offset="1" stop-opacity="1"/></linearGradient></defs>'
            '<rect width="10" height="10" fill="url(#g)"/></svg>',
            "SVG_GRADIENT_ALPHA_APPROXIMATED",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '<g opacity=".0004"><rect width="4" height="10"/>'
            '<rect x="6" width="4" height="10"/></g></svg>',
            "SVG_GROUP_OPACITY_APPROXIMATED",
        ),
    ],
)
def test_alpha_policy_is_independent_of_geometry_precision(
    tmp_path: Path,
    precision: int,
    content: str,
    code: str,
) -> None:
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content, precision=precision)
    assert caught.value.diagnostic.code == code

    converted = _compile(
        tmp_path,
        content,
        lossy=LossyPolicy.CONVERT,
        precision=precision,
    )
    assert converted.paths
    assert {issue.code for issue in converted.issues} == {code}


@pytest.mark.parametrize("color", [f"#{value:06x}" for value in range(1, 16)])
def test_source_colors_cannot_forge_internal_lossy_provenance(tmp_path: Path, color: str) -> None:
    colored = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<rect x="1" y="2" width="4" height="5" fill="{color}"/>'
        "</svg>"
    )
    black = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect x="1" y="2" width="4" height="5" fill="#000000"/>'
        "</svg>"
    )
    _assert_equivalent(_compile(tmp_path, colored), _compile(tmp_path, black))


@pytest.mark.parametrize(
    ("content", "code", "feature"),
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" opacity=".5"/></svg>',
            "SVG_PARTIAL_ALPHA_APPROXIMATED",
            "fractional-alpha",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
            '<linearGradient id="g"><stop stop-color="red" stop-opacity="0"/>'
            '<stop offset="1" stop-color="blue"/></linearGradient></defs>'
            '<rect width="10" height="10" fill="url(#g)"/></svg>',
            "SVG_GRADIENT_ALPHA_APPROXIMATED",
            "spatial-gradient-alpha",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
            '<pattern id="p" width="2" height="2" patternUnits="userSpaceOnUse">'
            '<rect width="1" height="1"/></pattern></defs>'
            '<rect width="10" height="10" fill="url(#p)"/></svg>',
            "SVG_PATTERN_APPROXIMATED",
            "pattern-paint",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<g opacity=".5"><rect width="4" height="4"/>'
            '<rect x="6" width="4" height="4"/></g></svg>',
            "SVG_GROUP_OPACITY_APPROXIMATED",
            "group-opacity",
        ),
    ],
)
def test_lossy_features_require_opt_in_and_emit_typed_conversion_issues(
    tmp_path: Path,
    content: str,
    code: str,
    feature: str,
) -> None:
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content)
    assert caught.value.classification is SvgFeatureClass.LOSSY
    assert caught.value.feature == feature
    assert caught.value.diagnostic.code == code

    glyph = _compile(tmp_path, content, lossy=LossyPolicy.CONVERT)
    assert glyph.paths
    assert len(glyph.issues) == 1
    issue = glyph.issues[0]
    assert issue.code == code
    assert issue.feature == feature
    assert issue.classification is SvgFeatureClass.LOSSY
    assert issue.action is IssueAction.CONVERTED


def test_pinned_font_text_is_shaped_and_outlined_deterministically(
    tmp_path: Path,
    pinned_text_font: tuple[str, TextFont],
) -> None:
    family, font = pinned_text_font
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">
          <text x="20" y="15" text-anchor="middle" font-family="{family}"
                font-size="10">AA</text>
        </svg>
    """
    first = _compile(tmp_path, content, text_fonts={family: font})
    second = _compile(tmp_path, content, text_fonts={family: font})
    assert first == second
    assert first.bounds == pytest.approx((15, 8, 25, 15))
    assert first.paths == (
        "M15,15 L17,8 L19,15 L18,15 L17.5,13 L16.5,13 L16,15 Z",
        "M21,15 L23,8 L25,15 L24,15 L23.5,13 L22.5,13 L22,15 Z",
    )
    assert first.issues == ()


def test_pinned_text_absolute_css_lengths_are_resolved(
    tmp_path: Path,
    pinned_text_font: tuple[str, TextFont],
) -> None:
    family, font = pinned_text_font
    absolute = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 40">
          <text x="1in" y="7.5mm" dx="3pt" dy="2px"
                font-family="{family}" font-size="7.5pt">A</text>
        </svg>
    """
    numeric = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 40">
          <text x="96" y="28.34645669291339" dx="4" dy="2"
                font-family="{family}" font-size="10">A</text>
        </svg>
    """
    _assert_equivalent(
        _compile(tmp_path, absolute, text_fonts={family: font}),
        _compile(tmp_path, numeric, text_fonts={family: font}),
    )


@pytest.mark.parametrize(
    "attributes",
    [
        'fill="none" stroke="none"',
        'opacity="0"',
        'font-size="0"',
    ],
)
def test_provably_invisible_text_needs_no_font_environment(tmp_path: Path, attributes: str) -> None:
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <text font-family="Not Pinned" {attributes}>Anything</text>
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    expected = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <rect x="2" y="3" width="4" height="5"/>
        </svg>
    """
    _assert_equivalent(_compile(tmp_path, content), _compile(tmp_path, expected))


def test_pinned_font_fallback_list_selects_first_available_face(
    tmp_path: Path,
    pinned_text_font: tuple[str, TextFont],
) -> None:
    family, font = pinned_text_font
    fallback = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">
          <text x="20" y="15" text-anchor="middle"
                font-family="Missing, '{family}'" font-size="10">AA</text>
        </svg>
    """
    direct = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 20">
          <text x="20" y="15" text-anchor="middle"
                font-family="{family}" font-size="10">AA</text>
        </svg>
    """
    _assert_equivalent(
        _compile(tmp_path, fallback, text_fonts={family: font}),
        _compile(tmp_path, direct, text_fonts={family: font}),
    )


def test_text_outlining_preserves_dash_and_vector_effect_on_every_glyph_path(
    pinned_text_font: tuple[str, TextFont],
) -> None:
    family, font = pinned_text_font
    root = etree.fromstring(
        f"""
        <svg xmlns="http://www.w3.org/2000/svg">
          <text font-family="{family}" stroke-dasharray="2 1"
                stroke-dashoffset=".5" vector-effect="non-scaling-stroke">AA</text>
        </svg>
        """.encode()
    )

    outline_text(
        root,
        text_fonts={family: font},
        source_id="icon.svg",
        max_expanded_elements=32,
        max_expanded_bytes=16_384,
        max_path_commands=1_000,
    )

    paths = root.xpath("//svg:path", namespaces={"svg": "http://www.w3.org/2000/svg"})
    assert len(paths) == 2
    assert all(path.get("stroke-dasharray") == "2 1" for path in paths)
    assert all(path.get("stroke-dashoffset") == ".5" for path in paths)
    assert all(path.get("vector-effect") == "non-scaling-stroke" for path in paths)


@pytest.mark.parametrize(
    ("attributes", "text", "code", "feature"),
    [
        (
            'unicode-bidi="plaintext"',
            "A",
            "SVG_TEXT_BIDI_UNREPRESENTABLE",
            "bidi-paragraph-layout",
        ),
        ("", "A\u0391", "SVG_TEXT_SCRIPT_UNREPRESENTABLE", "mixed-script-text"),
    ],
)
def test_single_run_text_rejects_layout_that_requires_segmentation(
    tmp_path: Path,
    pinned_text_font: tuple[str, TextFont],
    attributes: str,
    text: str,
    code: str,
    feature: str,
) -> None:
    family, font = pinned_text_font
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <text x="2" y="15" font-family="{family}" font-size="10"
                {attributes}>{text}</text>
        </svg>
    """

    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content, text_fonts={family: font})

    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == code
    assert caught.value.feature == feature


def test_text_shaping_is_bounded_before_a_long_run_is_materialized(
    tmp_path: Path,
    pinned_text_font: tuple[str, TextFont],
) -> None:
    family, font = pinned_text_font
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 20">
          <text x="2" y="15" font-family="{family}" font-size="10">{"A" * 100}</text>
        </svg>
    """

    with pytest.raises(IconFontError) as caught:
        _compile(
            tmp_path,
            content,
            text_fonts={family: font},
            max_expanded_elements=3,
        )

    assert caught.value.diagnostic.code == "SVG_EXPANSION_LIMIT"
    assert caught.value.diagnostic.details == {
        "phase": "text-outlining",
        "maxExpandedElements": 3,
        "maxExpandedBytes": 4 * 1024 * 1024,
        "shapedGlyphs": 100,
    }


@pytest.mark.parametrize("kind", ["use", "clip"])
def test_deep_local_reference_chains_hit_budget_without_python_recursion(
    tmp_path: Path, kind: str
) -> None:
    count = 1_050
    if kind == "use":
        chain = [f'<use id="n{index}" href="#n{index - 1}"/>' for index in range(1, count)]
        base = '<rect id="n0" width="2" height="2"/>'
        painted = f'<use href="#n{count - 1}"/>'
    else:
        chain = [
            f'<clipPath id="n{index}" clip-path="url(#n{index - 1})">'
            '<rect width="2" height="2"/></clipPath>'
            for index in range(1, count)
        ]
        base = '<clipPath id="n0"><rect width="2" height="2"/></clipPath>'
        painted = f'<rect width="2" height="2" clip-path="url(#n{count - 1})"/>'
    definitions = "".join(reversed(chain)) + base
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2">'
        f"<defs>{definitions}</defs>{painted}</svg>"
    )
    with pytest.raises(IconFontError) as caught:
        _compile(tmp_path, content, max_expanded_elements=500)
    assert caught.value.diagnostic.code == "SVG_EXPANSION_LIMIT"


def test_deep_acyclic_gradient_template_chain_is_iterative(tmp_path: Path) -> None:
    count = 1_050
    chain = [f'<linearGradient id="g{index}" href="#g{index - 1}"/>' for index in range(1, count)]
    definitions = "".join(reversed(chain)) + '<linearGradient id="g0"><stop/></linearGradient>'
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2">'
        f'<defs>{definitions}</defs><rect width="2" height="2" fill="url(#g{count - 1})"/>'
        "</svg>"
    )
    glyph = _compile(tmp_path, content, max_expanded_elements=5_000)
    assert glyph.bounds == pytest.approx((0, 0, 2, 2))
    assert glyph.issues == ()


@pytest.mark.parametrize(
    ("max_expanded_bytes", "max_path_commands", "code"),
    [
        (200, 100_000, "SVG_EXPANSION_LIMIT"),
        (4 * 1024 * 1024, 2, "SVG_TOO_MANY_PATH_COMMANDS"),
    ],
)
def test_outlined_text_obeys_byte_and_path_work_limits(
    tmp_path: Path,
    pinned_text_font: tuple[str, TextFont],
    max_expanded_bytes: int,
    max_path_commands: int,
    code: str,
) -> None:
    family, font = pinned_text_font
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <text x="2" y="15" font-family="{family}" font-size="10">A</text>
        </svg>
    """
    with pytest.raises(IconFontError) as caught:
        _compile(
            tmp_path,
            content,
            text_fonts={family: font},
            max_expanded_bytes=max_expanded_bytes,
            max_path_commands=max_path_commands,
        )

    assert caught.value.diagnostic.code == code
    assert caught.value.diagnostic.details["phase"] == "text-outlining"


@pytest.mark.parametrize(
    ("text", "code", "feature"),
    [
        ("B", "SVG_TEXT_GLYPH_UNREPRESENTABLE", "missing-text-glyph"),
        ("A", "SVG_TEXT_FONT_UNREPRESENTABLE", "unpinned-text-font"),
    ],
)
def test_text_outlining_rejects_only_unreproducible_font_cases(
    tmp_path: Path,
    pinned_text_font: tuple[str, TextFont],
    text: str,
    code: str,
    feature: str,
) -> None:
    family, font = pinned_text_font
    configured_fonts = {family: font} if feature == "missing-text-glyph" else {}
    content = f"""
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
          <text x="2" y="15" font-family="{family}" font-size="10">{text}</text>
        </svg>
    """
    with pytest.raises(SvgFeatureError) as caught:
        _compile(tmp_path, content, text_fonts=configured_fonts)
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.diagnostic.code == code
    assert caught.value.feature == feature
