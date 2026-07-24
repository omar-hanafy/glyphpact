from __future__ import annotations

from collections.abc import Iterable

WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
    | {f"COM{index}" for index in "¹²³"}
    | {f"LPT{index}" for index in "¹²³"}
)


def has_forbidden_text_character(value: str) -> bool:
    """Return whether text cannot safely cross JSON, Dart, and terminal boundaries."""
    return any(
        ord(character) < 32 or 0x7F <= ord(character) <= 0x9F or ord(character) in {0x2028, 0x2029}
        for character in value
    )


def first_nonportable_part(parts: Iterable[str]) -> str | None:
    for part in parts:
        if (
            part.endswith((" ", "."))
            or any(character in part for character in '<>:"\\|?*')
            or has_forbidden_text_character(part)
            or len(part.encode("utf-8")) > 255
            or part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
        ):
            return part
    return None
