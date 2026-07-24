from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import PurePosixPath

from .errors import IconFontError

_DART_RESERVED = frozenset(
    {
        "abstract",
        "as",
        "assert",
        "async",
        "augment",
        "await",
        "base",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "covariant",
        "default",
        "deferred",
        "do",
        "dynamic",
        "else",
        "enum",
        "export",
        "extends",
        "extension",
        "external",
        "factory",
        "false",
        "final",
        "finally",
        "for",
        "get",
        "hide",
        "if",
        "implements",
        "import",
        "in",
        "interface",
        "is",
        "late",
        "library",
        "mixin",
        "native",
        "new",
        "null",
        "of",
        "on",
        "operator",
        "part",
        "required",
        "rethrow",
        "return",
        "sealed",
        "set",
        "show",
        "static",
        "super",
        "switch",
        "sync",
        "this",
        "throw",
        "true",
        "try",
        "type",
        "typedef",
        "var",
        "void",
        "when",
        "while",
        "with",
        "yield",
    }
)

_DART_INHERITED_MEMBERS = frozenset({"hashCode", "noSuchMethod", "runtimeType", "toString"})

_DART_CLASS_CONFLICTS = frozenset(
    {
        "BigInt",
        "DateTime",
        "Duration",
        "Enum",
        "Function",
        "Future",
        "IconData",
        "Iterable",
        "List",
        "Map",
        "Never",
        "Null",
        "Object",
        "Pattern",
        "Record",
        "RegExp",
        "Runes",
        "Set",
        "StackTrace",
        "Stopwatch",
        "Stream",
        "String",
        "StringBuffer",
        "Symbol",
        "Type",
        "Uri",
    }
)

_IDENTIFIER = re.compile(r"^[a-z][A-Za-z0-9_]*$")
_CLASS_IDENTIFIER = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
_MAX_GENERATED_IDENTIFIER_LENGTH = 40


def _bounded_identifier(value: str, source: str) -> str:
    if len(value) <= _MAX_GENERATED_IDENTIFIER_LENGTH:
        return value
    suffix = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return value[: _MAX_GENERATED_IDENTIFIER_LENGTH - len(suffix)] + suffix


def _ascii_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", normalized)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    return [word for word in re.split(r"[^A-Za-z0-9]+", normalized) if word]


def derive_dart_name(source: str) -> str:
    path = PurePosixPath(source)
    stem = path.name
    if stem.lower().endswith(".svg"):
        stem = stem[:-4]
    words: list[str] = []
    for part in (*path.parts[:-1], stem):
        words.extend(_ascii_words(part))
    if not words:
        raise IconFontError(
            "DART_NAME_EMPTY",
            "The source path cannot be converted to an ASCII Dart identifier.",
            source=source,
            hint="Set an explicit name for this icon in the config file.",
        )

    first = words[0].lower()
    identifier = first + "".join(word[:1].upper() + word[1:].lower() for word in words[1:])
    if identifier[0].isdigit():
        identifier = "icon" + identifier[:1].upper() + identifier[1:]
    if identifier in _DART_RESERVED or identifier in _DART_INHERITED_MEMBERS:
        identifier += "Icon"
    identifier = _bounded_identifier(identifier, source)
    validate_dart_name(identifier, source=source)
    return identifier


def validate_dart_name(value: str, *, source: str | None = None) -> str:
    if not _IDENTIFIER.fullmatch(value) or value.startswith("_"):
        raise IconFontError(
            "DART_NAME_INVALID",
            f"{value!r} is not a public lowerCamelCase Dart identifier.",
            source=source,
        )
    if len(value) > _MAX_GENERATED_IDENTIFIER_LENGTH:
        raise IconFontError(
            "DART_NAME_TOO_LONG",
            f"Dart icon names cannot exceed {_MAX_GENERATED_IDENTIFIER_LENGTH} characters.",
            source=source,
        )
    if value in _DART_RESERVED:
        raise IconFontError(
            "DART_NAME_RESERVED",
            f"{value!r} is a reserved Dart word.",
            source=source,
        )
    if value in _DART_INHERITED_MEMBERS:
        raise IconFontError(
            "DART_NAME_INHERITED",
            f"{value!r} conflicts with a member inherited from Object.",
            source=source,
        )
    return value


def derive_class_name(font_family: str) -> str:
    words = _ascii_words(font_family)
    if not words:
        raise IconFontError(
            "CLASS_NAME_EMPTY",
            "The font family cannot be converted to a Dart class name.",
            hint="Set className explicitly in the config file.",
        )
    value = "".join(word[:1].upper() + word[1:] for word in words)
    if value[0].isdigit():
        value = "Icons" + value
    value = _bounded_identifier(value, font_family)
    return validate_class_name(value)


def validate_class_name(value: str) -> str:
    if not _CLASS_IDENTIFIER.fullmatch(value):
        raise IconFontError(
            "CLASS_NAME_INVALID",
            f"{value!r} is not a public UpperCamelCase Dart class identifier.",
        )
    if len(value) > _MAX_GENERATED_IDENTIFIER_LENGTH:
        raise IconFontError(
            "CLASS_NAME_TOO_LONG",
            f"Dart class names cannot exceed {_MAX_GENERATED_IDENTIFIER_LENGTH} characters.",
        )
    if value.lower() in _DART_RESERVED:
        raise IconFontError(
            "CLASS_NAME_RESERVED",
            f"{value!r} conflicts with a Dart reserved word.",
        )
    if value in _DART_CLASS_CONFLICTS:
        raise IconFontError(
            "CLASS_NAME_CONFLICT",
            f"{value!r} conflicts with a Dart core or generated API type.",
        )
    return value


def snake_case(value: str) -> str:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def dart_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("$", "\\$")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f"'{escaped}'"
