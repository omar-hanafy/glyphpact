from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

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
