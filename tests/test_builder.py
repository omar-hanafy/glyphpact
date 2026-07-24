from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from conftest import write_svg
from fontTools.ttLib import TTFont

import glyphpact.builder as builder_module
import glyphpact.font_builder as font_builder_module
from glyphpact.builder import build
from glyphpact.config import (
    BuildConfig,
    ConversionPolicy,
    LossyPolicy,
    TextFont,
    UnrepresentablePolicy,
)
from glyphpact.errors import (
    BatchError,
    IconFontError,
    IssueAction,
    SvgFeatureClass,
    SvgFeatureError,
    conversion_notice,
    skipped_issue,
)
from glyphpact.identity import GENERATOR_ID, LEGACY_IDENTITIES
from glyphpact.publisher import MARKER
from glyphpact.svg_compiler import CanonicalGlyph

LOSSY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<rect x="2" y="2" width="20" height="20" opacity=".5"/>'
    "</svg>"
)
UNREPRESENTABLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<defs><filter id="blur"><feGaussianBlur stdDeviation="1"/></filter></defs>'
    '<rect x="2" y="2" width="20" height="20" filter="url(#blur)"/>'
    "</svg>"
)
UNSAFE_UNREPRESENTABLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<defs><filter id="blur"><feGaussianBlur onload="evil()" '
    'stdDeviation="1"/></filter></defs>'
    '<rect x="2" y="2" width="20" height="20" filter="url(#blur)"/>'
    "</svg>"
)


def _config(input_dir: Path, output_dir: Path, **kwargs) -> BuildConfig:
    return BuildConfig(
        input_path=input_dir,
        output_dir=output_dir,
        font_family="Test Icons",
        class_name="TestIcons",
        **kwargs,
    ).validated()


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _lock(output: Path) -> dict:
    return json.loads((output / "iconfont.lock.json").read_text(encoding="utf-8"))


def _codepoints(output: Path) -> dict[str, str]:
    return {glyph["source"]: glyph["codepoint"] for glyph in _lock(output)["glyphs"]}


def _canonical_glyph(
    *,
    path_command_count: int = 6,
    issues=(),
) -> CanonicalGlyph:
    return CanonicalGlyph(
        paths=("M0,0 L1,0 L1,1 L0,1 L0,0 Z",),
        fill_rules=("nonzero",),
        view_box=(0.0, 0.0, 1.0, 1.0),
        bounds=(0.0, 0.0, 1.0, 1.0),
        source_shape_count=1,
        path_command_count=path_command_count,
        issues=issues,
    )


def test_end_to_end_build_is_reproducible_and_font_is_valid(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "basic.svg", simple_svg)
    write_svg(
        inputs,
        "actions/stroke.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 12h20" fill="none" stroke="black" stroke-width="3" stroke-linecap="round"/></svg>',
    )
    config = _config(inputs, output)

    first = build(config)
    first_tree = _tree(output)
    second = build(config)
    second_tree = _tree(output)

    assert first.font_sha256 == second.font_sha256
    assert first_tree == second_tree
    assert first.glyph_count == 2
    assert first.discovered_icon_count == 2
    assert first.lossless_glyph_count == 2
    assert first.approximated_glyph_count == 0
    assert first.skipped_icon_count == 0
    assert first.issues == ()
    assert first.quality == "lossless"
    assert MARKER in first_tree
    assert build(config, check=True).checked

    font = TTFont(BytesIO(first.font_path.read_bytes()), lazy=False, recalcTimestamp=False)
    assert font.sfntVersion == "OTTO"
    assert font["head"].unitsPerEm == 1000
    assert len(font.getBestCmap()) == 2
    assert {advance for advance, _ in font["hmtx"].metrics.values()} == {1000}
    assert tuple(font["CFF "].cff.topDictIndex[0].FontBBox) == (
        font["head"].xMin,
        0,
        font["head"].xMax,
        1000,
    )
    assert 0 < font["head"].yMin < font["head"].yMax < 1000
    font.close()

    dart = first.dart_path.read_text(encoding="utf-8")
    assert "@flutter.staticIconProvider" in dart
    assert "abstract final class TestIcons" in dart
    assert "static const flutter.IconData actionsStroke" in dart
    assert "fontPackage: _fontPackage" in dart


def test_generated_dart_wraps_long_prefixed_icon_assignments_like_dartfmt(
    tmp_path: Path,
    simple_svg: str,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "this_is_a_deliberately_extremely_long_icon_filename_for_formatter_stability.svg",
        simple_svg,
    )

    result = build(_config(inputs, output))

    dart = result.dart_path.read_text(encoding="utf-8")
    assert (
        "  static const flutter.IconData "
        "thisIsADeliberatelyExtremely8ef8d864668f =\n"
        "      flutter.IconData(\n"
        "        0xE000,\n"
        "        fontFamily: _fontFamily,\n"
        "        fontPackage: _fontPackage,\n"
        "      );"
    ) in dart


def test_cff_vertical_bbox_preserves_svg_position_in_flutter(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "vertical-alignment.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="20" y="10" width="60" height="20"/></svg>',
    )

    result = build(_config(inputs, output))
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["glyphs"][0]["fontBounds"] == [200.0, 700.0, 800.0, 900.0]

    font = TTFont(BytesIO(result.font_path.read_bytes()), lazy=False, recalcTimestamp=False)
    try:
        assert (
            font["head"].xMin,
            font["head"].yMin,
            font["head"].xMax,
            font["head"].yMax,
        ) == (200, 700, 800, 900)
        assert tuple(font["CFF "].cff.topDictIndex[0].FontBBox) == (
            200,
            0,
            800,
            1000,
        )
        assert font["hhea"].ascent == 1000
        assert font["hhea"].descent == 0
    finally:
        font.close()


def test_font_validation_rejects_glyph_dependent_cff_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "inset.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="20" y="10" width="60" height="20"/></svg>',
    )
    monkeypatch.setattr(
        font_builder_module,
        "_stabilize_cff_font_bbox",
        lambda data, _units_per_em: data,
    )

    with pytest.raises(IconFontError) as caught:
        build(_config(inputs, output))

    assert caught.value.diagnostic.code == "FONT_METRICS_MISMATCH"
    assert not output.exists()


def test_codepoints_are_stable_and_tombstones_are_not_reused(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    a = write_svg(inputs, "a.svg", simple_svg)
    write_svg(inputs, "b.svg", simple_svg.replace("20v20", "18v18"))
    config = _config(inputs, output)
    build(config)
    original = _codepoints(output)

    a.unlink()
    build(config)
    retired = _lock(output)["retired"]
    assert retired[0]["source"] == "a.svg"

    write_svg(inputs, "c.svg", simple_svg.replace("20v20", "16v16"))
    build(config)
    after_add = _codepoints(output)
    assert after_add["b.svg"] == original["b.svg"]
    assert after_add["c.svg"] not in original.values()

    write_svg(inputs, "a.svg", simple_svg)
    build(config)
    restored = _codepoints(output)
    assert restored["a.svg"] == original["a.svg"]
    assert not _lock(output)["retired"]


def test_unique_content_rename_preserves_codepoint_and_dart_api(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    original = write_svg(inputs, "old-name.svg", simple_svg)
    config = _config(inputs, output)
    build(config)
    before = _lock(output)["glyphs"][0]

    original.rename(inputs / "new-name.svg")
    build(config)
    after = _lock(output)["glyphs"][0]

    assert after["source"] == "new-name.svg"
    assert after["codepoint"] == before["codepoint"]
    assert after["name"] == before["name"]
    assert not _lock(output)["retired"]


def test_invalid_batch_does_not_touch_last_good_output(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    config = _config(inputs, output)
    build(config)
    before = _tree(output)

    write_svg(
        inputs,
        "bad.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><text>no</text></svg>',
    )
    with pytest.raises(BatchError):
        build(config)
    assert _tree(output) == before


def test_name_collision_fails_before_publication(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "foo-bar.svg", simple_svg)
    write_svg(inputs, "foo_bar.svg", simple_svg)
    with pytest.raises(IconFontError, match="LOCK_COLLISION"):
        build(_config(inputs, output))
    assert not output.exists()


def test_supplementary_private_use_codepoint_generates_format_12_cmap(
    tmp_path, simple_svg: str
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "future.svg", simple_svg)
    result = build(_config(inputs, output, start_codepoint=0xF0000))
    font = TTFont(BytesIO(result.font_path.read_bytes()), lazy=False, recalcTimestamp=False)
    assert 0xF0000 in font.getBestCmap()
    assert any(table.format == 12 for table in font["cmap"].tables)
    font.close()
    assert "0xF0000" in result.dart_path.read_text(encoding="utf-8")


def test_output_directory_requires_explicit_ownership(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)
    output.mkdir()
    (output / "mine.txt").write_text("keep", encoding="utf-8")
    config = _config(inputs, output)
    with pytest.raises(IconFontError, match="OUTPUT_NOT_OWNED"):
        build(config)
    assert (output / "mine.txt").read_text() == "keep"
    build(config, adopt_output=True)
    assert not (output / "mine.txt").exists()
    assert (output / MARKER).is_file()


def test_prebrand_state_migrates_without_codepoint_churn(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)
    config = _config(inputs, output)
    build(config)
    before = _codepoints(output)

    legacy_generator, legacy_marker, _ = LEGACY_IDENTITIES[0]
    lock = _lock(output)
    lock["generator"] = legacy_generator
    (output / "iconfont.lock.json").write_text(
        json.dumps(lock, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / MARKER).rename(output / legacy_marker)
    (output / legacy_marker).write_text(
        json.dumps({"schemaVersion": 1, "owner": legacy_generator}) + "\n",
        encoding="utf-8",
    )

    build(config)

    assert _codepoints(output) == before
    assert _lock(output)["generator"] == GENERATOR_ID
    assert not (output / legacy_marker).exists()
    assert json.loads((output / MARKER).read_text(encoding="utf-8"))["owner"] == GENERATOR_ID


def test_check_mode_reports_drift_without_rewriting(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)
    config = _config(inputs, output)
    result = build(config)
    result.dart_path.write_text("stale", encoding="utf-8")
    with pytest.raises(IconFontError) as caught:
        build(config, check=True)
    assert caught.value.diagnostic.code == "OUTPUT_OUT_OF_DATE"
    assert result.dart_path.read_text() == "stale"


def test_parallel_and_single_worker_builds_are_byte_identical(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    for index in range(20):
        write_svg(inputs, f"icon_{index:02d}.svg", simple_svg)

    serial_output = tmp_path / "serial"
    parallel_output = tmp_path / "parallel"
    serial = build(_config(inputs, serial_output, jobs=1))
    parallel = build(_config(inputs, parallel_output, jobs=2))

    assert serial.font_sha256 == parallel.font_sha256
    assert _tree(serial_output) == _tree(parallel_output)


@pytest.mark.parametrize(
    ("lossy", "unrepresentable", "expected_failure_classes"),
    [
        (
            LossyPolicy.ERROR,
            UnrepresentablePolicy.ERROR,
            {"lossy", "unrepresentable"},
        ),
        (LossyPolicy.ERROR, UnrepresentablePolicy.SKIP, {"lossy"}),
        (LossyPolicy.CONVERT, UnrepresentablePolicy.ERROR, {"unrepresentable"}),
        (LossyPolicy.CONVERT, UnrepresentablePolicy.SKIP, None),
    ],
)
def test_conversion_policy_axes_form_a_complete_two_by_two_matrix(
    tmp_path,
    simple_svg: str,
    lossy: LossyPolicy,
    unrepresentable: UnrepresentablePolicy,
    expected_failure_classes: set[str] | None,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(inputs, "lossy.svg", LOSSY_SVG)
    write_svg(inputs, "unsupported.svg", UNREPRESENTABLE_SVG)
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(lossy=lossy, unrepresentable=unrepresentable),
    )

    if expected_failure_classes is not None:
        with pytest.raises(BatchError) as caught:
            build(config)
        assert {
            diagnostic.details["classification"]
            for diagnostic in caught.value.diagnostics
            if diagnostic.details.get("action") != "skipped"
        } == expected_failure_classes
        if unrepresentable is UnrepresentablePolicy.SKIP:
            assert any(
                diagnostic.details.get("action") == "skipped"
                for diagnostic in caught.value.diagnostics
            )
        assert not output.exists()
        return

    result = build(config)

    assert result.discovered_icon_count == 3
    assert result.glyph_count == 2
    assert result.lossless_glyph_count == 1
    assert result.approximated_glyph_count == 1
    assert result.skipped_icon_count == 1
    assert result.quality == "partial"
    assert result.policy == config.policy
    assert {(issue.classification, issue.action) for issue in result.issues} == {
        (SvgFeatureClass.LOSSY, IssueAction.CONVERTED),
        (SvgFeatureClass.UNREPRESENTABLE, IssueAction.SKIPPED),
    }
    assert sum(issue.classification is SvgFeatureClass.LOSSY for issue in result.issues) == 1
    assert (
        sum(issue.classification is SvgFeatureClass.UNREPRESENTABLE for issue in result.issues) == 2
    )

    lock = _lock(output)
    assert {glyph["source"] for glyph in lock["glyphs"]} == {"good.svg", "lossy.svg"}
    assert [glyph["source"] for glyph in lock["retired"]] == ["unsupported.svg"]
    assert "geometrySha256" not in lock["retired"][0]

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["schemaVersion"] == 2
    assert report["quality"] == "partial"
    assert report["policy"] == {"lossy": "convert", "unrepresentable": "skip"}
    assert report["discoveredIconCount"] == 3
    assert report["glyphCount"] == 2
    assert report["losslessGlyphCount"] == 1
    assert report["approximatedGlyphCount"] == 1
    assert report["skippedIconCount"] == 1
    assert report["issueCount"] == len(result.issues)
    assert report["issues"] == [issue.to_dict() for issue in result.issues]
    assert {glyph["conversion"] for glyph in report["glyphs"]} == {
        "lossless",
        "approximated",
    }
    assert report["skippedIcons"][0]["source"] == "unsupported.svg"
    assert report["skippedIcons"][0]["previouslyEmitted"] is False
    assert "unsupported" not in result.dart_path.read_text(encoding="utf-8")


def test_lossy_conversion_is_typed_and_requires_explicit_opt_in(tmp_path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "lossy.svg", LOSSY_SVG)

    with pytest.raises(BatchError) as caught:
        build(_config(inputs, output, jobs=1))
    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "SVG_PARTIAL_ALPHA_APPROXIMATED"
    ]
    assert not output.exists()

    result = build(
        _config(
            inputs,
            output,
            jobs=1,
            policy=ConversionPolicy(lossy=LossyPolicy.CONVERT),
        )
    )

    assert result.quality == "approximated"
    assert result.lossless_glyph_count == 0
    assert result.approximated_glyph_count == 1
    assert result.skipped_icon_count == 0
    assert len(result.issues) == 1
    assert result.issues[0].classification is SvgFeatureClass.LOSSY
    assert result.issues[0].action is IssueAction.CONVERTED


def test_skipped_source_becomes_tombstone_and_reactivates_same_slot(
    tmp_path, simple_svg: str
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(inputs, "switchable.svg", simple_svg.replace("20v20", "18v18"))
    strict = _config(inputs, output, jobs=1)
    build(strict)
    original = next(
        glyph for glyph in _lock(output)["glyphs"] if glyph["source"] == "switchable.svg"
    )

    write_svg(inputs, "switchable.svg", UNREPRESENTABLE_SVG)
    skip = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(unrepresentable=UnrepresentablePolicy.SKIP),
    )
    partial = build(skip)

    assert partial.glyph_count == 1
    assert partial.skipped_icon_count == 1
    tombstone = next(
        glyph for glyph in _lock(output)["retired"] if glyph["source"] == "switchable.svg"
    )
    assert tombstone["codepoint"] == original["codepoint"]
    assert tombstone["name"] == original["name"]
    assert "geometrySha256" not in tombstone
    report = json.loads(partial.report_path.read_text(encoding="utf-8"))
    assert report["skippedIcons"][0]["previouslyEmitted"] is True

    write_svg(inputs, "switchable.svg", simple_svg.replace("20v20", "16v16"))
    restored = build(skip)
    restored_glyph = next(
        glyph for glyph in _lock(output)["glyphs"] if glyph["source"] == "switchable.svg"
    )

    assert restored.glyph_count == 2
    assert restored.skipped_icon_count == 0
    assert restored_glyph["codepoint"] == original["codepoint"]
    assert restored_glyph["name"] == original["name"]
    assert "geometrySha256" in restored_glyph
    assert not _lock(output)["retired"]


def test_all_skipped_batch_fails_atomically_and_preserves_last_good_output(
    tmp_path, simple_svg: str
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "only.svg", simple_svg)
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(unrepresentable=UnrepresentablePolicy.SKIP),
    )
    build(config)
    before = _tree(output)

    write_svg(inputs, "only.svg", UNREPRESENTABLE_SVG)
    with pytest.raises(BatchError) as caught:
        build(config)

    assert {diagnostic.details["classification"] for diagnostic in caught.value.diagnostics} == {
        "unrepresentable"
    }
    assert {diagnostic.details["action"] for diagnostic in caught.value.diagnostics} == {"skipped"}
    assert _tree(output) == before


def test_hard_security_failure_is_never_downgraded_to_skip(tmp_path, simple_svg: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(inputs, "unsafe-and-unsupported.svg", UNSAFE_UNREPRESENTABLE_SVG)
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(
            lossy=LossyPolicy.CONVERT,
            unrepresentable=UnrepresentablePolicy.SKIP,
        ),
    )

    with pytest.raises(BatchError) as caught:
        build(config)

    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "SVG_EVENT_HANDLER_FORBIDDEN"
    ]
    assert "classification" not in caught.value.diagnostics[0].details
    assert not output.exists()


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            '<rect style="--x:1;stroke:black;stroke-width:banana"/>',
            "SVG_LENGTH_INVALID",
        ),
        (
            "<style>@media screen{rect{fill:black}}</style>"
            "<style>rect:::{fill:black}</style><rect/>",
            "SVG_CSS_SELECTOR_INVALID",
        ),
        (
            "<style>@media screen{rect{fill:url(#missing)}}</style><rect/>",
            "SVG_REFERENCE_NOT_FOUND",
        ),
        (
            '<filter id="f"/><g filter="url(#f)" transform="scale(1e999)"><rect/></g>',
            "SVG_TRANSFORM_INVALID",
        ),
        (
            '<defs><clipPath id="c"><rect/></clipPath><filter id="f"/></defs>'
            '<rect clip-path="url(#f)" filter="url(#f)"/>',
            "SVG_REFERENCE_TARGET_INVALID",
        ),
        (
            '<filter id="f"/><rect filter="url(#f)" fill="url(#missing"/>',
            "SVG_URL_INVALID",
        ),
        (
            '<filter id="f"/><rect filter="url(#f)" fill="u\\72l(https://x)"/>',
            "SVG_URL_INVALID",
        ),
        (
            '<defs><pattern id="p" width="banana"><rect/></pattern></defs>'
            '<text font-family="Unpinned">A</text>',
            "SVG_LENGTH_INVALID",
        ),
        (
            '<defs><linearGradient id="a" href="#b"/>'
            '<linearGradient id="b" href="#a"/><filter id="f"/></defs>'
            '<rect fill="url(#a)" filter="url(#f)"/>',
            "SVG_PAINT_SERVER_CYCLE",
        ),
        (
            '<defs><pattern id="p" width="2" height="2">'
            '<rect width="2" height="2" fill="url(#p)"/></pattern></defs>'
            '<rect fill="url(#p)"/>',
            "SVG_PAINT_SERVER_CYCLE",
        ),
        (
            '<style media="screen">rect{fill:black}</style>'
            "<style>rect{fill-rule:banana}</style><rect/>",
            "SVG_FILL_RULE_INVALID",
        ),
        (
            "<style>@media print { rect { stroke-width:-1 } }</style><rect/>",
            "SVG_LENGTH_INVALID",
        ),
        (
            "<style>@supports (display:block) { rect::: { fill:black } }</style><rect/>",
            "SVG_CSS_SELECTOR_INVALID",
        ),
        (
            '<filter id="f"/><rect filter="url(#f)" width="calc(1px + )"/>',
            "SVG_LENGTH_INVALID",
        ),
        (
            '<filter id="f"/><svg filter="url(#f)" viewBox="0,,0,10,10"><rect/></svg>',
            "SVG_VIEWBOX_INVALID",
        ),
        (
            '<defs><clipPath id="c"/><filter id="f" href="#c"/></defs><rect filter="url(#f)"/>',
            "SVG_REFERENCE_TARGET_INVALID",
        ),
        (
            '<defs><filter id="a" href="#b"/><filter id="b" href="#a"/></defs>'
            '<rect filter="url(#a)"/>',
            "SVG_FILTER_REFERENCE_CYCLE",
        ),
        (
            '<defs><path id="p" d="M0 0h2v2z"/><filter id="f"/></defs>'
            '<rect href="#p" filter="url(#f)"/>',
            "SVG_REFERENCE_OWNER_INVALID",
        ),
    ],
)
def test_every_hard_invalid_beats_skip_and_prevents_partial_publication(
    tmp_path: Path,
    simple_svg: str,
    body: str,
    code: str,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(
        inputs,
        "invalid-and-unrepresentable.svg",
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>',
    )
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(
            lossy=LossyPolicy.CONVERT,
            unrepresentable=UnrepresentablePolicy.SKIP,
        ),
    )

    with pytest.raises(BatchError) as caught:
        build(config)

    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [code]
    assert not output.exists()


def test_invalid_pinned_font_is_parsed_before_any_icon_can_be_skipped(
    tmp_path: Path, simple_svg: str
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(
        inputs,
        "filtered-text.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<defs><filter id="f"><feGaussianBlur stdDeviation="1"/></filter></defs>'
        '<text font-family="Pinned" filter="url(#f)">A</text></svg>',
    )
    font_path = tmp_path / "invalid.ttf"
    font_bytes = b"not a font"
    font_path.write_bytes(font_bytes)
    config = _config(
        inputs,
        output,
        jobs=1,
        text_fonts={
            "Pinned": TextFont(
                path=font_path,
                sha256=hashlib.sha256(font_bytes).hexdigest(),
            )
        },
        policy=ConversionPolicy(unrepresentable=UnrepresentablePolicy.SKIP),
    )

    with pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == "TEXT_FONT_INVALID"
    assert caught.value.diagnostic.details["fontFamily"] == "Pinned"
    assert not output.exists()


def test_each_skipped_or_failed_icon_retains_full_attempted_work_charge(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "a.svg", UNREPRESENTABLE_SVG)
    write_svg(inputs, "b.svg", UNREPRESENTABLE_SVG)
    config = _config(
        inputs,
        output,
        jobs=1,
        max_path_commands=10,
        max_total_path_commands=15,
        policy=ConversionPolicy(unrepresentable=UnrepresentablePolicy.SKIP),
    )

    with pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == "SVG_BATCH_TOO_COMPLEX"
    assert caught.value.diagnostic.details == {
        "pathWork": 20,
        "maxTotalPathCommands": 15,
    }
    assert not output.exists()


def test_failed_batch_keeps_typed_diagnostics_for_policy_approved_skips(
    tmp_path: Path, simple_svg: str
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "a-skip.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<filter id="f"/><rect width="10" height="10" filter="url(#f)"/></svg>',
    )
    write_svg(
        inputs,
        "b-hard.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="banana"/></svg>',
    )
    write_svg(inputs, "c-good.svg", simple_svg)
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(unrepresentable=UnrepresentablePolicy.SKIP),
    )

    with pytest.raises(BatchError) as caught:
        build(config)

    assert {diagnostic.code for diagnostic in caught.value.diagnostics} == {
        "SVG_ATTRIBUTE_UNREPRESENTABLE",
        "SVG_ELEMENT_UNREPRESENTABLE",
        "SVG_LENGTH_INVALID",
    }
    skipped = next(
        diagnostic
        for diagnostic in caught.value.diagnostics
        if diagnostic.details.get("action") == "skipped"
    )
    assert skipped.source == "a-skip.svg"
    assert skipped.details["classification"] == "unrepresentable"
    assert not output.exists()


def test_worker_boundary_rejects_lossy_geometry_under_strict_policy(
    tmp_path: Path, simple_svg: str, monkeypatch
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)

    def compile_with_unapproved_loss(source, _config):
        return _canonical_glyph(
            issues=(
                conversion_notice(
                    "SVG_TEST_LOSS",
                    "Synthetic lossy geometry.",
                    source=source.source_id,
                    feature="test-loss",
                ),
            )
        )

    monkeypatch.setattr(builder_module, "compile_svg", compile_with_unapproved_loss)

    with pytest.raises(BatchError) as caught:
        build(_config(inputs, output, jobs=1))

    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "INTERNAL_POLICY_VIOLATION"
    ]
    assert not output.exists()


@pytest.mark.parametrize(
    ("path_command_count", "issue_source"),
    [(1, "icon.svg"), (6, "different.svg")],
)
def test_worker_boundary_rejects_inconsistent_canonical_geometry(
    tmp_path: Path,
    simple_svg: str,
    monkeypatch,
    path_command_count: int,
    issue_source: str,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)

    def compile_invalid(_source, _config):
        return _canonical_glyph(
            path_command_count=path_command_count,
            issues=(
                conversion_notice(
                    "SVG_TEST_LOSS",
                    "Synthetic lossy geometry.",
                    source=issue_source,
                    feature="test-loss",
                ),
            ),
        )

    monkeypatch.setattr(builder_module, "compile_svg", compile_invalid)
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(lossy=LossyPolicy.CONVERT),
    )

    with pytest.raises(BatchError) as caught:
        build(config)

    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "INTERNAL_WORKER_RESULT_INVALID"
    ]
    assert not output.exists()


@pytest.mark.parametrize("work_charge_delta", [0, -1])
def test_aggregation_rechecks_skip_policy_and_full_work_charge(
    tmp_path: Path,
    simple_svg: str,
    monkeypatch,
    work_charge_delta: int,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)
    strict = work_charge_delta == 0
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(
            unrepresentable=(UnrepresentablePolicy.ERROR if strict else UnrepresentablePolicy.SKIP)
        ),
    )

    def inject_skip(source, worker_config):
        error = SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "synthetic-skip",
            "SVG_TEST_SKIP",
            "Synthetic skipped input.",
            source=source.source_id,
        )
        return builder_module._WorkerSkipped(
            source=source,
            issues=(skipped_issue(error),),
            work_charge=worker_config.max_path_commands + work_charge_delta,
        )

    monkeypatch.setattr(builder_module, "_compile_worker", inject_skip)

    with pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == (
        "INTERNAL_POLICY_VIOLATION" if strict else "INTERNAL_WORKER_RESULT_INVALID"
    )
    assert not output.exists()


def test_aggregation_rejects_worker_source_mismatch(
    tmp_path: Path, simple_svg: str, monkeypatch
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)
    config = _config(
        inputs,
        output,
        jobs=1,
        policy=ConversionPolicy(unrepresentable=UnrepresentablePolicy.SKIP),
    )

    def inject_wrong_source(source, worker_config):
        wrong_source = replace(source, source_id="different.svg")
        error = SvgFeatureError(
            SvgFeatureClass.UNREPRESENTABLE,
            "synthetic-skip",
            "SVG_TEST_SKIP",
            "Synthetic skipped input.",
            source=wrong_source.source_id,
        )
        return builder_module._WorkerSkipped(
            source=wrong_source,
            issues=(skipped_issue(error),),
            work_charge=worker_config.max_path_commands,
        )

    monkeypatch.setattr(builder_module, "_compile_worker", inject_wrong_source)

    with pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == "INTERNAL_WORKER_RESULT_INVALID"
    assert not output.exists()
