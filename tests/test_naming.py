from __future__ import annotations

import pytest

from glyphpact.errors import IconFontError
from glyphpact.naming import (
    dart_string,
    derive_class_name,
    derive_dart_name,
    snake_case,
    validate_dart_name,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("home.svg", "home"),
        ("actions/arrow-left.svg", "actionsArrowLeft"),
        ("2fa.svg", "icon2fa"),
        ("class.svg", "classIcon"),
        ("Über Cool.SVG", "uberCool"),
        ("runtime-type.svg", "runtimeTypeIcon"),
    ],
)
def test_derive_dart_name(source: str, expected: str) -> None:
    assert derive_dart_name(source) == expected


def test_non_ascii_only_name_requires_override() -> None:
    with pytest.raises(IconFontError, match="DART_NAME_EMPTY"):
        derive_dart_name("🦾.svg")


def test_explicit_name_must_be_public_and_not_reserved() -> None:
    for value in ("_private", "2fast", "class", "has-hyphen"):
        with pytest.raises(IconFontError):
            validate_dart_name(value)


def test_class_and_filename_derivation() -> None:
    assert derive_class_name("My excellent icons") == "MyExcellentIcons"
    assert snake_case("HTTPStatusIcons") == "http_status_icons"


def test_dart_string_escapes_interpolation_and_quotes() -> None:
    assert dart_string("a'b\\c$d") == "'a\\'b\\\\c\\$d'"
