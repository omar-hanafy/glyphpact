from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
from io import BytesIO
from pathlib import Path, PurePosixPath

import pathops
import pytest
from conftest import write_svg
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont

import glyphpact.discovery as discovery_module
from glyphpact.builder import build
from glyphpact.config import (
    BuildConfig,
    ConversionPolicy,
    IconOverride,
    LossyPolicy,
    load_config,
)
from glyphpact.discovery import SvgSource, discover_svg_sources
from glyphpact.errors import (
    BatchError,
    IconFontError,
    IssueAction,
    SvgFeatureClass,
    SvgFeatureError,
)
from glyphpact.font_builder import _validate_sfnt_checksums
from glyphpact.manifest import _CodepointAllocator, load_lock
from glyphpact.naming import validate_class_name, validate_dart_name
from glyphpact.output_lock import output_lock
from glyphpact.publisher import (
    MARKER,
    _create_transaction_backup,
    marker_bytes,
    recover_output,
    verify_output_ownership,
)
from glyphpact.svg_compiler import compile_svg

SQUARE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 2h20v20H2z"/></svg>'
)


def _config(input_dir: Path, output_dir: Path, **kwargs: object) -> BuildConfig:
    return BuildConfig(
        input_path=input_dir,
        output_dir=output_dir,
        font_family="Hardening Icons",
        class_name="HardeningIcons",
        jobs=1,
        **kwargs,
    ).validated()


def _lock(output_dir: Path) -> dict[str, object]:
    return json.loads((output_dir / "iconfont.lock.json").read_text(encoding="utf-8"))


def _codepoints(output_dir: Path) -> dict[str, str]:
    glyphs = _lock(output_dir)["glyphs"]
    assert isinstance(glyphs, list)
    return {glyph["source"]: glyph["codepoint"] for glyph in glyphs}


def _retired_pack(tmp_path: Path) -> tuple[Path, Path, BuildConfig]:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    first = write_svg(inputs, "a.svg", SQUARE_SVG)
    write_svg(inputs, "b.svg", SQUARE_SVG.replace("20v20", "18v18"))
    config = _config(inputs, output)
    build(config)
    first.unlink()
    build(config)
    return inputs, output, config


def _source(content: str) -> SvgSource:
    data = content.encode("utf-8")
    return SvgSource(
        path=Path("icon.svg"),
        source_id="icon.svg",
        content=content,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
    )


def _compiler_config(tmp_path: Path, **kwargs: object) -> BuildConfig:
    return _config(tmp_path / "input", tmp_path / "output", **kwargs)


def _batch_codes(error: BatchError) -> list[str]:
    return [diagnostic.code for diagnostic in error.diagnostics]


def _font_bytes(tmp_path: Path) -> bytes:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", SQUARE_SVG)
    return build(_config(inputs, output)).font_path.read_bytes()


def _sfnt_entry(data: bytes | bytearray, wanted: bytes) -> tuple[int, int]:
    table_count = struct.unpack(">H", data[4:6])[0]
    for index in range(table_count):
        entry_offset = 12 + index * 16
        if data[entry_offset : entry_offset + 4] == wanted:
            table_offset = struct.unpack(">I", data[entry_offset + 8 : entry_offset + 12])[0]
            return entry_offset, table_offset
    raise AssertionError(f"Missing table {wanted!r}")


def _validate_checksum_bytes(data: bytes) -> None:
    font = TTFont(
        BytesIO(data),
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
    )
    try:
        _validate_sfnt_checksums(data, font)
    finally:
        font.close()


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")


def test_partial_lock_fails_closed_without_republishing(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", SQUARE_SVG)
    result = build(_config(inputs, output))
    font_before = result.font_path.read_bytes()
    dart_before = result.dart_path.read_bytes()
    partial = b'{"schemaVersion": 1}\n'
    result.lock_path.write_bytes(partial)

    with pytest.raises(IconFontError) as caught:
        build(_config(inputs, output))

    assert caught.value.diagnostic.code == "LOCK_KEY_MISSING"
    assert result.lock_path.read_bytes() == partial
    assert result.font_path.read_bytes() == font_before
    assert result.dart_path.read_bytes() == dart_before


def test_established_output_missing_lock_cannot_reset_abi(tmp_path: Path) -> None:
    _, output, config = _retired_pack(tmp_path)
    before = _lock(output)
    dart_before = (output / "hardening_icons.dart").read_bytes()
    (output / "iconfont.lock.json").unlink()

    with pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == "LOCK_MISSING"
    assert not (output / "iconfont.lock.json").exists()
    assert (output / "hardening_icons.dart").read_bytes() == dart_before
    assert before["retired"]


def test_interrupted_swap_recovers_lock_before_allocating(tmp_path: Path) -> None:
    _, output, config = _retired_pack(tmp_path)
    before = _lock(output)
    backup = output.parent / f".{output.name}.backup"
    os.replace(output, backup)

    build(config)

    after = _lock(output)
    assert after["glyphs"] == before["glyphs"]
    assert after["retired"] == before["retired"]
    assert _codepoints(output)["b.svg"] == "0xE001"
    assert not backup.exists()


def test_rename_prefers_still_active_glyph_over_identical_retired_glyph(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    active = write_svg(inputs, "a.svg", SQUARE_SVG)
    retired = write_svg(inputs, "b.svg", SQUARE_SVG)
    config = _config(inputs, output)
    build(config)
    original = _lock(output)
    retired.unlink()
    build(config)

    active.rename(inputs / "c.svg")
    build(config)

    after = _lock(output)
    glyphs = after["glyphs"]
    tombstones = after["retired"]
    assert isinstance(glyphs, list)
    assert isinstance(tombstones, list)
    original_by_source = {glyph["source"]: glyph for glyph in original["glyphs"]}
    assert glyphs[0]["source"] == "c.svg"
    assert glyphs[0]["codepoint"] == original_by_source["a.svg"]["codepoint"]
    assert glyphs[0]["name"] == original_by_source["a.svg"]["name"]
    assert [glyph["source"] for glyph in tombstones] == ["b.svg"]


def test_corrupt_current_lock_preserves_valid_recovery_backup(tmp_path: Path) -> None:
    _, output, config = _retired_pack(tmp_path)
    backup = output.parent / f".{output.name}.backup"
    shutil.copytree(output, backup)
    (output / "iconfont.lock.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == "LOCK_READ_FAILED"
    assert backup.is_dir()
    assert _codepoints(backup)["b.svg"] == "0xE001"


def test_unowned_backup_is_never_consumed_or_deleted(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    backup = tmp_path / ".generated.backup"
    write_svg(inputs, "icon.svg", SQUARE_SVG)
    backup.mkdir()
    precious = backup / "precious.txt"
    precious.write_text("keep me", encoding="utf-8")

    with pytest.raises(IconFontError) as caught:
        build(_config(inputs, output))

    assert caught.value.diagnostic.code == "OUTPUT_NOT_OWNED"
    assert precious.read_text(encoding="utf-8") == "keep me"
    assert not output.exists()


def test_interrupted_adoption_restores_foreign_output_without_claiming_it(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    output.mkdir()
    precious = output / "precious.txt"
    precious.write_text("keep me", encoding="utf-8")
    backup = tmp_path / ".generated.backup"
    previous = _create_transaction_backup(output, backup)
    os.replace(output, previous)

    recover_output(output)

    assert (output / "precious.txt").read_text(encoding="utf-8") == "keep me"
    assert not backup.exists()
    with pytest.raises(IconFontError) as caught:
        verify_output_ownership(output, adopt=False)
    assert caught.value.diagnostic.code == "OUTPUT_NOT_OWNED"


def test_equivalent_solid_paint_aliases_are_one_paint(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 10">'
        '<rect x="0" width="8" height="8" fill="black"/>'
        '<rect x="10" width="8" height="8" fill="#000"/>'
        '<rect x="20" width="8" height="8" fill="rgb(0 0 0)"/>'
        '<rect x="30" width="8" height="8" fill="hsl(0 0% 0%)"/>'
        "</svg>"
    )

    glyph = compile_svg(_source(content), _compiler_config(tmp_path))

    assert glyph.paths


def test_irrelevant_dash_hint_on_fill_only_geometry_is_removed(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<path style="fill:black;stroke-dasharray:1,3" d="M1 1h8v8H1z"/>'
        "</svg>"
    )

    assert compile_svg(_source(content), _compiler_config(tmp_path)).paths


@pytest.mark.parametrize(
    "declaration",
    [
        'clip-rule="evenodd"',
        'style="clip-rule:evenodd"',
        "",
    ],
)
def test_inherited_clip_rule_is_materialized_on_clip_geometry(
    tmp_path: Path, declaration: str
) -> None:
    group_start = '<g clip-rule="evenodd">' if not declaration else ""
    group_end = "</g>" if group_start else ""
    content = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" {declaration}>'
        f'{group_start}<defs><clipPath id="c">'
        '<path d="M0 0h10v10H0zM2 2h6v6H2z"/>'
        "</clipPath></defs>"
        '<path clip-path="url(#c)" d="M0 0h10v10H0z"/>'
        f"{group_end}</svg>"
    )

    glyph = compile_svg(_source(content), _compiler_config(tmp_path))
    outline = pathops.Path()
    parse_path(glyph.paths[0], outline.getPen())

    assert outline.contains((1, 1))
    assert not outline.contains((5, 5))


@pytest.mark.parametrize(
    ("target_attribute", "expected_bounds"),
    [
        ('display="none"', (2.0, 2.0, 4.0, 4.0)),
        ('clip-path="url(#b)"', (2.0, 2.0, 6.0, 6.0)),
    ],
)
def test_use_inside_clip_path_preserves_target_semantics(
    tmp_path: Path,
    target_attribute: str,
    expected_bounds: tuple[float, float, float, float],
) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs>'
        '<clipPath id="b"><rect x="2" y="2" width="4" height="4"/></clipPath>'
        f'<path id="p" {target_attribute} d="M0 0h8v8H0z"/>'
        '<clipPath id="a"><use href="#p"/><rect x="2" y="2" width="2" height="2"/>'
        "</clipPath></defs>"
        '<path clip-path="url(#a)" d="M0 0h10v10H0z"/></svg>'
    )

    glyph = compile_svg(_source(content), _compiler_config(tmp_path))

    assert glyph.bounds == pytest.approx(expected_bounds)
    assert glyph.issues == ()


@pytest.mark.parametrize(
    ("font_file", "dart_file"),
    [
        ("same.otf", "SAME.OTF"),
        ("caf\u00e9.otf", "cafe\u0301.otf"),
        ("nested", "nested/icons.dart"),
    ],
)
def test_artifact_paths_reject_portability_and_nesting_collisions(
    tmp_path: Path,
    font_file: str,
    dart_file: str,
) -> None:
    with pytest.raises(IconFontError) as caught:
        _config(
            tmp_path / "input",
            tmp_path / "output",
            font_file=PurePosixPath(font_file),
            dart_file=PurePosixPath(dart_file),
        )

    assert caught.value.diagnostic.code == "OUTPUT_ARTIFACT_CONFLICT"


def test_artifact_path_cannot_replace_ownership_marker(tmp_path: Path) -> None:
    with pytest.raises(IconFontError) as caught:
        _config(
            tmp_path / "input",
            tmp_path / "output",
            font_file=PurePosixPath(MARKER.upper()),
        )

    assert caught.value.diagnostic.code == "OUTPUT_ARTIFACT_CONFLICT"


@pytest.mark.parametrize(
    "value",
    [
        r"C:\escape.otf",
        r"\\server\share\escape.otf",
        "CON.otf",
        "COM¹.otf",
        "LPT².otf",
        "CONIN$.otf",
        "folder/name. ",
        "folder/name:bad.otf",
        r"folder\escape.otf",
    ],
)
def test_artifact_paths_reject_nonportable_windows_forms(tmp_path: Path, value: str) -> None:
    with pytest.raises(IconFontError) as caught:
        _config(
            tmp_path / "input",
            tmp_path / "output",
            font_file=PurePosixPath(value),
        )

    assert caught.value.diagnostic.code == "OUTPUT_PATH_UNSAFE"


def test_config_rejects_wrong_artifact_path_type(tmp_path: Path) -> None:
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        json.dumps({"input": "icons", "output": "generated", "fontFile": False}),
        encoding="utf-8",
    )

    with pytest.raises(IconFontError) as caught:
        load_config(config_path)

    assert caught.value.diagnostic.code == "CONFIG_TYPE_INVALID"


def test_config_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        '{"input":"icons","input":"other-icons","output":"generated"}',
        encoding="utf-8",
    )

    with pytest.raises(IconFontError) as caught:
        load_config(config_path)

    assert caught.value.diagnostic.code == "JSON_DUPLICATE_KEY"


def test_lock_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    lock_path = tmp_path / "iconfont.lock.json"
    lock_path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")

    with pytest.raises(IconFontError) as caught:
        load_lock(lock_path)

    assert caught.value.diagnostic.code == "LOCK_DUPLICATE_KEY"


def test_live_lock_symlink_is_rejected_before_reading_external_state(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", SQUARE_SVG)
    config = _config(inputs, output)
    result = build(config)
    external_lock = tmp_path / "external.lock.json"
    shutil.copy2(result.lock_path, external_lock)
    result.lock_path.unlink()
    _symlink_or_skip(result.lock_path, external_lock)

    with pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == "OUTPUT_SYMLINK_FORBIDDEN"
    assert result.lock_path.is_symlink()
    assert json.loads(external_lock.read_text(encoding="utf-8"))["glyphs"]


def test_configured_input_root_symlink_is_rejected(tmp_path: Path) -> None:
    real_input = tmp_path / "real-input"
    real_input.mkdir()
    write_svg(real_input, "icon.svg", SQUARE_SVG)
    linked_input = tmp_path / "linked-input"
    _symlink_or_skip(linked_input, real_input, directory=True)

    with pytest.raises(IconFontError) as caught:
        _config(linked_input, tmp_path / "output")

    assert caught.value.diagnostic.code == "INPUT_SYMLINK_FORBIDDEN"


def test_configured_output_root_symlink_is_rejected(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    inputs.mkdir()
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    linked_output = tmp_path / "linked-output"
    _symlink_or_skip(linked_output, real_output, directory=True)

    with pytest.raises(IconFontError) as caught:
        _config(inputs, linked_output)

    assert caught.value.diagnostic.code == "OUTPUT_PATH_INVALID"


def test_configured_input_rejects_symlinked_ancestor_component(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_input = real_parent / "icons"
    real_input.mkdir(parents=True)
    write_svg(real_input, "icon.svg", SQUARE_SVG)
    linked_parent = tmp_path / "linked-parent"
    _symlink_or_skip(linked_parent, real_parent, directory=True)

    with pytest.raises(IconFontError) as caught:
        _config(linked_parent / "icons", tmp_path / "output")

    assert caught.value.diagnostic.code == "INPUT_SYMLINK_FORBIDDEN"


def test_configured_output_rejects_symlinked_ancestor_component(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    inputs.mkdir()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    _symlink_or_skip(linked_parent, real_parent, directory=True)

    with pytest.raises(IconFontError) as caught:
        _config(inputs, linked_parent / "generated")

    assert caught.value.diagnostic.code == "OUTPUT_PATH_INVALID"


@pytest.mark.parametrize(
    ("path_kind", "expected_code"),
    [("input", "INPUT_SYMLINK_FORBIDDEN"), ("output", "OUTPUT_PATH_INVALID")],
)
def test_missing_then_parent_segments_cannot_hide_symlink_ancestors(
    tmp_path: Path, path_kind: str, expected_code: str
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    _symlink_or_skip(linked_parent, real_parent, directory=True)
    disguised = tmp_path / "missing" / ".." / "linked-parent" / "nested"
    input_path = disguised if path_kind == "input" else tmp_path / "icons"
    output_path = disguised if path_kind == "output" else tmp_path / "generated"

    with pytest.raises(IconFontError) as caught:
        _config(input_path, output_path)

    assert caught.value.diagnostic.code == expected_code


@pytest.mark.parametrize(
    ("input_parts", "output_parts"),
    [
        (("tree",), ("tree",)),
        (("tree",), ("tree", "generated")),
        (("tree", "icons"), ("tree",)),
    ],
)
def test_input_and_output_trees_cannot_overlap(
    tmp_path: Path,
    input_parts: tuple[str, ...],
    output_parts: tuple[str, ...],
) -> None:
    input_path = tmp_path.joinpath(*input_parts)
    output_path = tmp_path.joinpath(*output_parts)

    with pytest.raises(IconFontError) as caught:
        _config(input_path, output_path)

    assert caught.value.diagnostic.code == "OUTPUT_OVERLAPS_INPUT"


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "{}",
        '{"schemaVersion": true, "owner": "glyphpact"}',
        '{"schemaVersion": 2, "owner": "glyphpact"}',
        '{"schemaVersion": 1, "owner": "somebody-else"}',
        '{"schemaVersion": 1, "owner": "glyphpact", "extra": true}',
        '{"schemaVersion": 1, "owner": "somebody-else", "owner": "glyphpact"}',
        "{broken",
    ],
)
def test_output_marker_schema_is_exact_and_type_safe(tmp_path: Path, payload: str) -> None:
    output = tmp_path / "generated"
    output.mkdir()
    (output / MARKER).write_text(payload, encoding="utf-8")

    with pytest.raises(IconFontError) as caught:
        verify_output_ownership(output, adopt=False)

    assert caught.value.diagnostic.code == "OUTPUT_MARKER_INVALID"


def test_output_marker_symlink_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    output.mkdir()
    external = tmp_path / "marker.json"
    external.write_bytes(marker_bytes())
    _symlink_or_skip(output / MARKER, external)

    with pytest.raises(IconFontError) as caught:
        verify_output_ownership(output, adopt=False)

    assert caught.value.diagnostic.code == "OUTPUT_MARKER_INVALID"


def test_generated_font_explicitly_allows_embedding_and_subsetting(tmp_path: Path) -> None:
    data = _font_bytes(tmp_path)
    font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
    try:
        assert font["OS/2"].fsType == 0
    finally:
        font.close()


@pytest.mark.parametrize("tag", [b"OS/2", b"name", b"post"])
def test_font_validation_rejects_bad_checksum_in_every_required_table(
    tmp_path: Path,
    tag: bytes,
) -> None:
    data = bytearray(_font_bytes(tmp_path))
    entry_offset, _ = _sfnt_entry(data, tag)
    checksum = struct.unpack(">I", data[entry_offset + 4 : entry_offset + 8])[0]
    data[entry_offset + 4 : entry_offset + 8] = struct.pack(">I", checksum ^ 1)

    with pytest.raises(IconFontError) as caught:
        _validate_checksum_bytes(bytes(data))

    assert caught.value.diagnostic.code == "FONT_CHECKSUM_MISMATCH"


def test_font_validation_rejects_bad_whole_font_checksum_adjustment(tmp_path: Path) -> None:
    data = bytearray(_font_bytes(tmp_path))
    _, table_offset = _sfnt_entry(data, b"head")
    adjustment_offset = table_offset + 8
    adjustment = struct.unpack(">I", data[adjustment_offset : adjustment_offset + 4])[0]
    data[adjustment_offset : adjustment_offset + 4] = struct.pack(">I", adjustment ^ 1)

    with pytest.raises(IconFontError) as caught:
        _validate_checksum_bytes(bytes(data))

    assert caught.value.diagnostic.code == "FONT_CHECKSUM_ADJUSTMENT_INVALID"


@pytest.mark.parametrize("name", ["runtimeType", "hashCode", "toString", "noSuchMethod"])
def test_explicit_icon_name_cannot_shadow_object_member(name: str) -> None:
    with pytest.raises(IconFontError) as caught:
        validate_dart_name(name)

    assert caught.value.diagnostic.code == "DART_NAME_INHERITED"


@pytest.mark.parametrize("name", ["String", "IconData", "HardeningIcons"])
def test_icon_name_cannot_break_generated_dart_symbol_table(tmp_path: Path, name: str) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", SQUARE_SVG)

    with pytest.raises(IconFontError):
        build(
            _config(
                inputs,
                output,
                icons={"icon.svg": IconOverride(name=name)},
            )
        )

    assert not output.exists()


@pytest.mark.parametrize("name", ["Function", "String", "IconData"])
def test_class_name_cannot_shadow_generated_or_core_type(name: str) -> None:
    with pytest.raises(IconFontError) as caught:
        validate_class_name(name)

    assert caught.value.diagnostic.code == "CLASS_NAME_CONFLICT"


def test_calibrated_dash_path_length_is_typed_unrepresentable(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 10">'
        '<path pathLength="10" d="M0 5H100" fill="none" stroke="black" '
        'stroke-width="2" stroke-dasharray="10 10"/>'
        "</svg>"
    )

    with pytest.raises(SvgFeatureError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_PATH_LENGTH_DASH_UNREPRESENTABLE"
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE
    assert caught.value.feature == "calibrated-dash-lengths"


def test_inert_path_length_is_removed_without_geometry_change(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<path pathLength="100" d="M1 2h8v6H1z"/>'
        "</svg>"
    )

    glyph = compile_svg(_source(content), _compiler_config(tmp_path))

    assert glyph.bounds == pytest.approx((1.0, 2.0, 9.0, 8.0))
    assert glyph.issues == ()


def test_duplicate_local_svg_ids_are_rejected_before_use_resolution(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<defs><path id="p" d="M1 1h2v2z"/><path id="p" d="M18 18h2v2z"/></defs>'
        '<use href="#p"/></svg>'
    )

    with pytest.raises(IconFontError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_ID_DUPLICATE"


def test_duplicate_id_hidden_in_pruned_metadata_is_still_rejected(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<metadata id="p"/><path id="p" d="M1 1h2v2z"/><use href="#p"/></svg>'
    )

    with pytest.raises(IconFontError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_ID_DUPLICATE"


@pytest.mark.parametrize(
    "paint",
    [
        "#00000080",
        "rgba(0,0,0,0.5)",
        "rgb(0 0 0 / 50%)",
        "rgb(255,0,0,0.5)",
        "hsl(0,100%,50%,0.5)",
    ],
)
def test_fractional_alpha_requires_explicit_lossy_policy(tmp_path: Path, paint: str) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path fill="{paint}" d="M0 0h10v10H0z"/>'
        "</svg>"
    )

    with pytest.raises(SvgFeatureError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_PARTIAL_ALPHA_APPROXIMATED"
    assert caught.value.classification is SvgFeatureClass.LOSSY
    assert caught.value.feature == "fractional-alpha"

    glyph = compile_svg(
        _source(content),
        _compiler_config(
            tmp_path,
            policy=ConversionPolicy(lossy=LossyPolicy.CONVERT),
        ),
    )

    assert glyph.bounds == pytest.approx((0.0, 0.0, 10.0, 10.0))
    assert len(glyph.issues) == 1
    issue = glyph.issues[0]
    assert issue.code == "SVG_PARTIAL_ALPHA_APPROXIMATED"
    assert issue.classification is SvgFeatureClass.LOSSY
    assert issue.action is IssueAction.CONVERTED
    assert issue.feature == "fractional-alpha"


def test_transparent_paint_is_typed_as_an_empty_silhouette(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path fill="transparent" d="M0 0h10v10H0z"/>'
        "</svg>"
    )

    with pytest.raises(SvgFeatureError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_EMPTY_OUTLINE"
    assert caught.value.classification is SvgFeatureClass.UNREPRESENTABLE


def test_fractional_alpha_fully_covered_later_is_lossless(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<path opacity=".5" d="M0 0h10v10H0z"/>'
        '<path d="M0 0h10v10H0z"/>'
        "</svg>"
    )

    glyph = compile_svg(_source(content), _compiler_config(tmp_path))

    assert glyph.bounds == pytest.approx((0.0, 0.0, 10.0, 10.0))
    assert glyph.issues == ()


def test_inherited_current_color_is_materialized_losslessly(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<g color="#c0ffee"><path fill="currentColor" d="M2 3h10v8H2z"/></g>'
        "</svg>"
    )

    glyph = compile_svg(_source(content), _compiler_config(tmp_path))

    assert glyph.bounds == pytest.approx((2.0, 3.0, 12.0, 11.0))
    assert glyph.issues == ()


def test_malformed_svg_namespace_is_a_stable_conversion_error(tmp_path: Path) -> None:
    content = '<svg viewBox="0 0 24 24"><path d="M0 0h10v10z"/></svg>'

    with pytest.raises(IconFontError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_ROOT_INVALID"


def test_raw_svg_byte_limit_fails_the_batch_without_output(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "large.svg", SQUARE_SVG)

    with pytest.raises(BatchError) as caught:
        build(_config(inputs, output, max_file_bytes=32))

    assert _batch_codes(caught.value) == ["SVG_TOO_LARGE"]
    assert not output.exists()


def test_xml_element_limit_is_enforced(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "elements.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<g><path d="M0 0h10v10z"/></g></svg>',
    )

    with pytest.raises(BatchError) as caught:
        build(_config(inputs, output, max_elements=2))

    assert _batch_codes(caught.value) == ["SVG_TOO_MANY_ELEMENTS"]
    assert not output.exists()


def test_element_limit_counts_foreign_metadata_before_pruning(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:meta="urn:metadata" '
        'viewBox="0 0 24 24">'
        "<meta:wrapper><meta:item/><meta:item/><meta:item/><meta:item/></meta:wrapper>"
        '<path d="M0 0h10v10z"/></svg>'
    )

    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(content),
            _compiler_config(tmp_path, max_elements=4),
        )

    assert caught.value.diagnostic.code == "SVG_TOO_MANY_ELEMENTS"


def test_canonical_path_command_limit_is_enforced(tmp_path: Path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M0 0h10v10H0z"/>'
        "</svg>"
    )

    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(content),
            _compiler_config(tmp_path, max_path_commands=2),
        )

    assert caught.value.diagnostic.code == "SVG_TOO_MANY_PATH_COMMANDS"


def test_raw_path_work_is_bounded_before_canonicalization(tmp_path: Path) -> None:
    segments = "".join(f"L{index % 10} {(index * 3) % 10}" for index in range(100))
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        f'<path fill="red" d="M0 0{segments}z"/>'
        '<path fill="blue" d="M1 1h1v1z"/></svg>'
    )

    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(content),
            _compiler_config(tmp_path, max_path_commands=2),
        )

    assert caught.value.diagnostic.code == "SVG_RAW_PATH_LIMIT"


def test_compiled_files_consume_the_aggregate_path_work_budget(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    for index in range(3):
        write_svg(
            inputs,
            f"invalid-{index}.svg",
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<path fill="red" d="M0 0h2v2z"/><path fill="blue" d="M4 4h2v2z"/>'
            "</svg>",
        )

    with pytest.raises(IconFontError) as caught:
        build(
            _config(
                inputs,
                tmp_path / "generated",
                max_path_commands=2,
                max_total_path_commands=2,
            )
        )

    assert caught.value.diagnostic.code == "SVG_BATCH_TOO_COMPLEX"
    assert not (tmp_path / "generated").exists()


@pytest.mark.parametrize("element", ["path", "g"])
def test_namespace_reset_visual_elements_are_not_treated_as_svg(
    tmp_path: Path, element: str
) -> None:
    child = (
        '<path xmlns="" d="M0 0h10v10z"/>'
        if element == "path"
        else '<g xmlns=""><path d="M0 0h10v10z"/></g>'
    )
    content = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">{child}</svg>'

    with pytest.raises(IconFontError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_NAMESPACE_INVALID"


def test_svg_nesting_limit_is_enforced(tmp_path: Path) -> None:
    groups = "<g>" * 129
    closes = "</g>" * 129
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'{groups}<path d="M0 0h10v10z"/>{closes}</svg>'
    )

    with pytest.raises(IconFontError) as caught:
        compile_svg(_source(content), _compiler_config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_TOO_DEEP"


class _CountingSet(set[int]):
    def __init__(self, values: range) -> None:
        super().__init__(values)
        self.contains_calls = 0

    def __contains__(self, value: object) -> bool:
        self.contains_calls += 1
        return super().__contains__(value)


def test_codepoint_allocator_advances_monotonically_in_linear_membership_checks() -> None:
    start = 0xF0000
    occupied = 5_000
    allocations = 1_000
    used = _CountingSet(range(start, start + occupied))
    allocator = _CodepointAllocator(used, start)

    assigned = [allocator.allocate() for _ in range(allocations)]

    assert assigned == list(range(start + occupied, start + occupied + allocations))
    assert used.contains_calls <= occupied + allocations


def test_concurrent_build_of_same_output_fails_with_busy_diagnostic(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", SQUARE_SVG)
    config = _config(inputs, output)

    with output_lock(config.output_dir), pytest.raises(IconFontError) as caught:
        build(config)

    assert caught.value.diagnostic.code == "OUTPUT_BUSY"
    assert not output.exists()
    assert build(config).glyph_count == 1


def test_check_mode_does_not_create_or_modify_generated_output(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    icon = write_svg(inputs, "icon.svg", SQUARE_SVG)
    config = _config(inputs, output)
    source_before = icon.read_bytes()

    with pytest.raises(IconFontError) as caught:
        build(config, check=True)

    assert caught.value.diagnostic.code == "OUTPUT_OUT_OF_DATE"
    assert icon.read_bytes() == source_before
    assert not output.exists()


def test_total_input_budget_counts_rejected_file_bytes(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    inputs.mkdir()
    for index in range(3):
        (inputs / f"bad-{index}.svg").write_bytes(b"x" * 17)

    with pytest.raises(IconFontError) as caught:
        discover_svg_sources(
            inputs,
            max_bytes=16,
            max_total_bytes=16,
            max_icons=10,
            max_entries=10,
        )

    assert caught.value.diagnostic.code == "SVG_BATCH_TOO_LARGE"


def test_discovery_budget_counts_unrelated_files_before_sorting(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    inputs.mkdir()
    for index in range(4):
        (inputs / f"unrelated-{index}.txt").write_text("x", encoding="utf-8")
    write_svg(inputs, "icon.svg", SQUARE_SVG)

    with pytest.raises(IconFontError) as caught:
        discover_svg_sources(
            inputs,
            max_bytes=1024,
            max_total_bytes=4096,
            max_icons=10,
            max_entries=4,
        )

    assert caught.value.diagnostic.code == "INPUT_TREE_TOO_LARGE"


def test_discovery_rejects_directory_swap_before_descriptor_read(
    tmp_path: Path, monkeypatch
) -> None:
    inputs = tmp_path / "icons"
    scanned_directory = inputs / "category"
    write_svg(scanned_directory, "icon.svg", SQUARE_SVG)
    external_directory = tmp_path / "external"
    write_svg(
        external_directory,
        "icon.svg",
        SQUARE_SVG.replace("M2 2h20v20H2z", "M0 0h24v24H0z"),
    )
    parked_directory = tmp_path / "scanned-original"
    original_read = discovery_module._read_svg
    swapped = False

    def swap_then_read(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            scanned_directory.rename(parked_directory)
            _symlink_or_skip(scanned_directory, external_directory, directory=True)
            swapped = True
        return original_read(*args, **kwargs)

    monkeypatch.setattr(discovery_module, "_read_svg", swap_then_read)

    with pytest.raises(BatchError) as caught:
        discover_svg_sources(
            inputs,
            max_bytes=1024,
            max_total_bytes=4096,
            max_icons=10,
            max_entries=10,
        )

    assert _batch_codes(caught.value) == ["SVG_SOURCE_CHANGED"]


def test_check_reports_extra_empty_directories_without_reading_contents(tmp_path: Path) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", SQUARE_SVG)
    config = _config(inputs, output)
    build(config)
    (output / "unexpected-empty-directory").mkdir()

    with pytest.raises(IconFontError) as caught:
        build(config, check=True)

    assert caught.value.diagnostic.code == "OUTPUT_OUT_OF_DATE"
    assert caught.value.diagnostic.details["extra"] == ["unexpected-empty-directory"]


@pytest.mark.parametrize("character", ["\x7f", "\u2028", "\u2029"])
def test_source_ids_reject_every_lock_forbidden_character(tmp_path: Path, character: str) -> None:
    inputs = tmp_path / "icons"
    write_svg(inputs, f"bad{character}name.svg", SQUARE_SVG)

    with pytest.raises(BatchError) as caught:
        build(_config(inputs, tmp_path / "generated"))

    assert _batch_codes(caught.value) == ["SOURCE_PATH_CONTROL_CHARACTER"]


def test_coordination_lock_rejects_symbolic_link(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    target = tmp_path / "external.lock"
    target.write_bytes(b"external")
    lock_path = tmp_path / ".generated.glyphpact.lock"
    _symlink_or_skip(lock_path, target)

    with pytest.raises(IconFontError) as caught, output_lock(output):
        pass

    assert caught.value.diagnostic.code == "OUTPUT_LOCK_FAILED"
