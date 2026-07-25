from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import glyphpact.svg_compiler as svg_compiler_module
from glyphpact.config import BuildConfig
from glyphpact.discovery import SvgSource
from glyphpact.errors import IconFontError
from glyphpact.svg_compiler import compile_svg


def _source(content: str, source_id: str = "icon.svg") -> SvgSource:
    data = content.encode()
    return SvgSource(
        path=Path(source_id),
        source_id=source_id,
        content=content,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
    )


def _config(tmp_path) -> BuildConfig:
    return BuildConfig(
        input_path=tmp_path / "input",
        output_dir=tmp_path / "out",
    ).validated()


@pytest.mark.parametrize(
    "content",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 24 12"><path d="M10 20h24v12H10z"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g transform="translate(2 3)"><circle cx="5" cy="5" r="3"/><rect x="10" y="2" width="5" height="7"/></g></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 2L22 22" fill="none" stroke="black" stroke-width="2" stroke-linecap="round"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><defs><path id="p" d="M1 1h4v4H1z"/></defs><use href="#p" x="8" y="9"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><defs><clipPath id="c"><circle cx="12" cy="12" r="5"/></clipPath></defs><rect width="24" height="24" clip-path="url(#c)"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill-rule="evenodd" d="M0 0h24v24H0zM4 4v16h16V4z"/></svg>',
    ],
)
def test_supported_svg_semantics_compile(tmp_path, content: str) -> None:
    glyph = compile_svg(_source(content), _config(tmp_path))
    assert glyph.paths
    assert glyph.path_command_count > 0
    assert glyph.bounds[2] > glyph.bounds[0]
    assert glyph.bounds[3] > glyph.bounds[1]
    assert set(glyph.fill_rules) == {"nonzero"}


def test_xml_declaration_is_accepted(tmp_path) -> None:
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M0 0h24v24H0z"/></svg>'
    )

    assert compile_svg(_source(content), _config(tmp_path)).paths


@pytest.mark.parametrize(
    "content",
    [
        "not xml",
        '<svg xmlns="http://www.w3.org/2000/svg"><path></svg>',
    ],
)
def test_malformed_xml_has_a_stable_diagnostic(tmp_path, content: str) -> None:
    with pytest.raises(IconFontError) as caught:
        compile_svg(_source(content), _config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_XML_MALFORMED"
    assert caught.value.diagnostic.message == "The input is not a well-formed XML document."
    assert caught.value.diagnostic.details["line"] >= 1
    assert caught.value.diagnostic.details["column"] >= 1


def test_xml_parser_resource_diagnostic_does_not_leak_to_the_next_document(tmp_path) -> None:
    groups = "<g>" * 300
    closes = "</g>" * 300
    overdeep = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'{groups}<path d="M0 0h10v10z"/>{closes}</svg>'
    )

    with pytest.raises(IconFontError) as depth_caught:
        compile_svg(_source(overdeep), _config(tmp_path))
    with pytest.raises(IconFontError) as malformed_caught:
        compile_svg(_source("not xml"), _config(tmp_path))

    assert depth_caught.value.diagnostic.code == "SVG_TOO_DEEP"
    assert malformed_caught.value.diagnostic.code == "SVG_XML_MALFORMED"


def test_well_formed_non_svg_xml_has_a_root_diagnostic(tmp_path) -> None:
    with pytest.raises(IconFontError) as caught:
        compile_svg(_source("<html/>"), _config(tmp_path))

    assert caught.value.diagnostic.code == "SVG_ROOT_INVALID"


def test_unexpected_conversion_failure_is_typed_as_internal(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_parse(_content: str):
        raise RuntimeError("raw upstream failure")

    monkeypatch.setattr(svg_compiler_module.SVG, "fromstring", staticmethod(fail_parse))

    with pytest.raises(IconFontError) as caught:
        compile_svg(
            _source(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                '<path d="M0 0h24v24H0z"/></svg>'
            ),
            _config(tmp_path),
        )

    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "INTERNAL_CONVERSION_ERROR"
    assert diagnostic.details == {"exceptionType": "RuntimeError"}
    assert "raw upstream failure" not in diagnostic.render()


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (
            '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>',
            "SVG_DTD_FORBIDDEN",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><script>alert(1)</script><path d="M0 0h1v1z"/></svg>',
            "SVG_SCRIPT_FORBIDDEN",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path onclick="x()" d="M0 0h1v1z"/></svg>',
            "SVG_EVENT_HANDLER_FORBIDDEN",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><foo/></svg>',
            "SVG_ELEMENT_UNSUPPORTED",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path filter="url(#x)" d="M0 0h1v1z"/></svg>',
            "SVG_REFERENCE_NOT_FOUND",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><use href="https://example.com/x.svg#p"/></svg>',
            "SVG_EXTERNAL_REFERENCE",
        ),
    ],
)
def test_malformed_or_unsafe_semantics_are_hard_errors(tmp_path, content: str, code: str) -> None:
    with pytest.raises(IconFontError) as caught:
        compile_svg(_source(content), _config(tmp_path))
    assert caught.value.diagnostic.code == code


def test_inkscape_noop_editor_hint_is_accepted(tmp_path) -> None:
    content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path style="-inkscape-stroke:none;fill:black" d="M0 0h4v4z"/>'
        "</svg>"
    )
    assert compile_svg(_source(content), _config(tmp_path)).paths
