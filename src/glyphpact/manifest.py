from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from .config import BuildConfig, IconOverride, private_use_range, validate_text
from .discovery import SvgSource
from .errors import IconFontError
from .identity import ACCEPTED_GENERATOR_IDS, GENERATOR_ID, PRODUCT_NAME
from .naming import derive_dart_name, validate_dart_name
from .portable_paths import first_nonportable_part
from .version import __version__

LOCK_SCHEMA_VERSION = 1
MAX_LOCK_BYTES = 64 * 1024 * 1024

_LOCK_KEYS = frozenset(
    {
        "schemaVersion",
        "generator",
        "generatorVersion",
        "fontFamily",
        "className",
        "fontPackage",
        "startCodepoint",
        "unitsPerEm",
        "glyphs",
        "retired",
    }
)


def format_codepoint(value: int) -> str:
    return f"0x{value:X}"


@dataclass(frozen=True)
class LockGlyph:
    source: str
    name: str
    codepoint: int
    source_sha256: str
    geometry_sha256: str | None = None
    match_text_direction: bool = False
    metadata: Mapping[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": self.source,
            "name": self.name,
            "codepoint": format_codepoint(self.codepoint),
            "sourceSha256": self.source_sha256,
            "matchTextDirection": self.match_text_direction,
        }
        if self.geometry_sha256 is not None:
            result["geometrySha256"] = self.geometry_sha256
        if self.metadata:
            result["metadata"] = dict(sorted(self.metadata.items()))
        return result


@dataclass(frozen=True)
class LockState:
    active: tuple[LockGlyph, ...] = ()
    retired: tuple[LockGlyph, ...] = ()


def _load_json(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            validate_text(key, "lock JSON object key", source=str(path))
            if key in result:
                raise IconFontError(
                    "LOCK_DUPLICATE_KEY",
                    f"Duplicate JSON key {key!r}.",
                    source=str(path),
                )
            result[key] = value
        return result

    try:
        if path.stat().st_size > MAX_LOCK_BYTES:
            raise IconFontError(
                "LOCK_TOO_LARGE",
                "The codepoint lock exceeds the 64 MiB parsing limit.",
                source=str(path),
            )
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except IconFontError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise IconFontError("LOCK_READ_FAILED", str(error), source=str(path)) from error


def _parse_hash(value: Any, key: str, source: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9A-Fa-f]{64}", value) is None:
        raise IconFontError(
            "LOCK_HASH_INVALID",
            f"{key} must be a 64-character SHA-256 hex digest.",
            source=source,
        )
    return value.lower()


def _parse_codepoint(value: Any, source: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"0x[0-9A-F]+", value) is None:
        raise IconFontError(
            "LOCK_CODEPOINT_INVALID",
            "codepoint must use the 0xE000 string form.",
            source=source,
        )
    try:
        result = int(value[2:], 16)
    except ValueError as error:
        raise IconFontError(
            "LOCK_CODEPOINT_INVALID", f"Invalid codepoint {value!r}.", source=source
        ) from error
    if private_use_range(result) is None:
        raise IconFontError(
            "LOCK_CODEPOINT_INVALID",
            f"U+{result:04X} is outside Unicode private-use ranges.",
            source=source,
        )
    return result


def _parse_glyph(value: Any, lock_path: Path) -> LockGlyph:
    if not isinstance(value, dict):
        raise IconFontError("LOCK_GLYPH_INVALID", "Each glyph entry must be an object.")
    allowed = {
        "source",
        "name",
        "codepoint",
        "sourceSha256",
        "geometrySha256",
        "matchTextDirection",
        "metadata",
    }
    unknown = set(value) - allowed
    required = {"source", "name", "codepoint", "sourceSha256", "matchTextDirection"}
    missing = required - set(value)
    if unknown:
        raise IconFontError(
            "LOCK_KEY_UNKNOWN",
            f"Unknown glyph key(s): {', '.join(sorted(unknown))}.",
            source=str(lock_path),
        )
    if missing:
        raise IconFontError(
            "LOCK_GLYPH_KEY_MISSING",
            f"Required glyph key(s) are missing: {', '.join(sorted(missing))}.",
            source=str(lock_path),
        )
    source = value.get("source")
    name = value.get("name")
    if not isinstance(source, str) or not source:
        raise IconFontError("LOCK_SOURCE_INVALID", "A lock glyph source must be a string.")
    validate_text(source, "lock glyph source", source=str(lock_path))
    normalized_source = unicodedata.normalize("NFC", PurePosixPath(source).as_posix())
    if (
        normalized_source != source
        or PurePosixPath(source).is_absolute()
        or ".." in PurePosixPath(source).parts
        or len(source.encode("utf-8")) > 4_096
        or any(ord(character) < 32 for character in source)
        or first_nonportable_part(PurePosixPath(source).parts) is not None
    ):
        raise IconFontError(
            "LOCK_SOURCE_INVALID",
            "A lock glyph source must be a normalized, portable relative path.",
            source=source,
        )
    if not isinstance(name, str):
        raise IconFontError("LOCK_NAME_INVALID", "A lock glyph name must be a string.")
    validate_dart_name(name, source=source)
    rtl = value["matchTextDirection"]
    if not isinstance(rtl, bool):
        raise IconFontError(
            "LOCK_RTL_INVALID", "matchTextDirection must be boolean.", source=source
        )
    metadata = value.get("metadata")
    if metadata is not None and (
        not isinstance(metadata, dict)
        or not all(isinstance(key, str) and isinstance(item, str) for key, item in metadata.items())
    ):
        raise IconFontError(
            "LOCK_METADATA_INVALID",
            "metadata must map strings to strings.",
            source=source,
        )
    if metadata is not None:
        for key, item in metadata.items():
            validate_text(key, "lock metadata key", source=source)
            validate_text(item, f"lock metadata {key!r}", source=source)
    geometry = value.get("geometrySha256")
    return LockGlyph(
        source=source,
        name=name,
        codepoint=_parse_codepoint(value.get("codepoint"), source),
        source_sha256=_parse_hash(value.get("sourceSha256"), "sourceSha256", source),
        geometry_sha256=(
            _parse_hash(geometry, "geometrySha256", source) if geometry is not None else None
        ),
        match_text_direction=rtl,
        metadata=metadata,
    )


def _validate_unique(glyphs: Iterable[LockGlyph]) -> None:
    sources: dict[str, LockGlyph] = {}
    folded_sources: dict[str, LockGlyph] = {}
    names: dict[str, LockGlyph] = {}
    codepoints: dict[int, LockGlyph] = {}
    for glyph in glyphs:
        collisions = (
            (sources.get(glyph.source), "source"),
            (folded_sources.get(glyph.source.casefold()), "portable source path"),
            (names.get(glyph.name), "Dart name"),
            (codepoints.get(glyph.codepoint), "codepoint"),
        )
        for previous, label in collisions:
            if previous is not None:
                raise IconFontError(
                    "LOCK_COLLISION",
                    f"Duplicate {label} between {previous.source!r} and {glyph.source!r}.",
                )
        sources[glyph.source] = glyph
        folded_sources[glyph.source.casefold()] = glyph
        names[glyph.name] = glyph
        codepoints[glyph.codepoint] = glyph


def load_lock(
    path: Path,
    *,
    expected_start_codepoint: int | None = None,
) -> LockState:
    if path.is_symlink():
        raise IconFontError(
            "LOCK_SYMLINK_FORBIDDEN",
            "The codepoint lock file cannot be a symbolic link.",
            source=str(path),
        )
    if not path.exists():
        return LockState()
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise IconFontError("LOCK_INVALID", "The lock root must be an object.")
    unknown = set(raw) - _LOCK_KEYS
    missing = _LOCK_KEYS - set(raw)
    if unknown:
        raise IconFontError(
            "LOCK_KEY_UNKNOWN",
            f"Unknown lock key(s): {', '.join(sorted(unknown))}.",
            source=str(path),
        )
    if missing:
        raise IconFontError(
            "LOCK_KEY_MISSING",
            f"Required lock key(s) are missing: {', '.join(sorted(missing))}.",
            source=str(path),
            hint="Restore the committed lock file. Never regenerate it from a partial copy.",
        )
    if type(raw.get("schemaVersion")) is not int or raw["schemaVersion"] != LOCK_SCHEMA_VERSION:
        raise IconFontError(
            "LOCK_VERSION_UNSUPPORTED",
            f"Expected schemaVersion {LOCK_SCHEMA_VERSION}.",
            source=str(path),
        )
    if not isinstance(raw["generator"], str) or raw["generator"] not in ACCEPTED_GENERATOR_IDS:
        raise IconFontError(
            "LOCK_GENERATOR_INVALID",
            f"The lock was not created by {PRODUCT_NAME}.",
            source=str(path),
        )
    for key in ("generatorVersion", "fontFamily", "className"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise IconFontError(
                "LOCK_INVALID",
                f"{key} must be a non-empty string.",
                source=str(path),
            )
        validate_text(raw[key], key, source=str(path))
    if raw["fontPackage"] is not None and not isinstance(raw["fontPackage"], str):
        raise IconFontError(
            "LOCK_INVALID",
            "fontPackage must be a string or null.",
            source=str(path),
        )
    if isinstance(raw["fontPackage"], str):
        validate_text(raw["fontPackage"], "fontPackage", source=str(path))
    start_codepoint = _parse_codepoint(raw["startCodepoint"], str(path))
    if expected_start_codepoint is not None and start_codepoint != expected_start_codepoint:
        raise IconFontError(
            "LOCK_START_CODEPOINT_MISMATCH",
            (
                f"The lock startCodepoint {format_codepoint(start_codepoint)} does not "
                "match the configured "
                f"{format_codepoint(expected_start_codepoint)}."
            ),
            source=str(path),
            hint=(
                "Restore the established startCodepoint. To use another range, create a "
                "new font family, output directory, and lock."
            ),
        )
    if (
        isinstance(raw["unitsPerEm"], bool)
        or not isinstance(raw["unitsPerEm"], int)
        or not 16 <= raw["unitsPerEm"] <= 16_384
    ):
        raise IconFontError(
            "LOCK_INVALID",
            "unitsPerEm must be an integer between 16 and 16384.",
            source=str(path),
        )
    active_raw = raw["glyphs"]
    retired_raw = raw["retired"]
    if not isinstance(active_raw, list) or not isinstance(retired_raw, list):
        raise IconFontError("LOCK_INVALID", "glyphs and retired must be arrays.")
    active = tuple(_parse_glyph(value, path) for value in active_raw)
    retired = tuple(_parse_glyph(value, path) for value in retired_raw)
    _validate_unique((*active, *retired))
    bounds = private_use_range(start_codepoint)
    assert bounds is not None
    for glyph in (*active, *retired):
        if not start_codepoint <= glyph.codepoint <= bounds[1]:
            raise IconFontError(
                "LOCK_CODEPOINT_RANGE_MISMATCH",
                (
                    f"{glyph.source!r} uses {format_codepoint(glyph.codepoint)}, outside "
                    f"the lock allocation window {format_codepoint(start_codepoint)} "
                    f"through {format_codepoint(bounds[1])}."
                ),
                source=str(path),
                hint="Restore the committed lock file. Do not mix private-use ranges.",
            )
    return LockState(active=active, retired=retired)


class _CodepointAllocator:
    def __init__(self, used: set[int], start: int, *, established: bool) -> None:
        self._used = used
        self._next = start
        self._established = established
        bounds = private_use_range(start)
        assert bounds is not None
        self._end = bounds[1]

    def allocate(self) -> int:
        while self._next <= self._end and self._next in self._used:
            self._next += 1
        if self._next > self._end:
            raise IconFontError(
                "CODEPOINT_RANGE_EXHAUSTED",
                f"No private-use codepoint remains through U+{self._end:04X}.",
                hint=(
                    (
                        "Create another stable font family, output directory, and lock "
                        "before adding more icons. Never recycle retired codepoints."
                    )
                    if self._established
                    else (
                        "Choose a supplementary private-use startCodepoint such as "
                        "U+F0000 before publishing this new pack."
                    )
                ),
            )
        result = self._next
        self._used.add(result)
        self._next += 1
        return result


def assign_glyphs(
    sources: Iterable[SvgSource],
    previous: LockState,
    config: BuildConfig,
) -> LockState:
    sources = tuple(sources)
    old_by_source = {glyph.source: glyph for glyph in (*previous.active, *previous.retired)}
    current_sources = {source.source_id for source in sources}
    current_hash_counts: dict[str, int] = {}
    for source in sources:
        current_hash_counts[source.sha256] = current_hash_counts.get(source.sha256, 0) + 1
    active_rename_candidates: dict[str, list[LockGlyph]] = {}
    retired_rename_candidates: dict[str, list[LockGlyph]] = {}
    for glyph in previous.active:
        if glyph.source not in current_sources:
            active_rename_candidates.setdefault(glyph.source_sha256, []).append(glyph)
    for glyph in previous.retired:
        if glyph.source not in current_sources:
            retired_rename_candidates.setdefault(glyph.source_sha256, []).append(glyph)
    used = {glyph.codepoint for glyph in (*previous.active, *previous.retired)}
    allocator = _CodepointAllocator(
        used,
        config.start_codepoint,
        established=bool(previous.active or previous.retired),
    )
    active: list[LockGlyph] = []
    active_sources: set[str] = set()
    renamed_from: set[str] = set()

    for source in sources:
        active_sources.add(source.source_id)
        old = old_by_source.get(source.source_id)
        if old is None and current_hash_counts[source.sha256] == 1:
            active_candidates = [
                glyph
                for glyph in active_rename_candidates.get(source.sha256, [])
                if glyph.source not in renamed_from
            ]
            candidates = active_candidates
            if not candidates:
                candidates = [
                    glyph
                    for glyph in retired_rename_candidates.get(source.sha256, [])
                    if glyph.source not in renamed_from
                ]
            if len(candidates) == 1:
                old = candidates[0]
                renamed_from.add(old.source)
        override: IconOverride = config.icons.get(source.source_id, IconOverride())
        name = override.name or (old.name if old else derive_dart_name(source.source_id))
        rtl = (
            override.match_text_direction
            if override.match_text_direction is not None
            else (old.match_text_direction if old else False)
        )
        metadata = override.metadata or (old.metadata if old else None)
        active.append(
            LockGlyph(
                source=source.source_id,
                name=name,
                codepoint=old.codepoint if old else allocator.allocate(),
                source_sha256=source.sha256,
                geometry_sha256=old.geometry_sha256 if old else None,
                match_text_direction=rtl,
                metadata=metadata,
            )
        )

    retired_by_source = {glyph.source: glyph for glyph in previous.retired}
    for glyph in previous.active:
        if glyph.source not in active_sources and glyph.source not in renamed_from:
            retired_by_source[glyph.source] = glyph
    for source_id in (*active_sources, *renamed_from):
        retired_by_source.pop(source_id, None)

    _validate_unique((*active, *retired_by_source.values()))
    return LockState(
        active=tuple(sorted(active, key=lambda glyph: glyph.source.encode("utf-8"))),
        retired=tuple(
            sorted(retired_by_source.values(), key=lambda glyph: glyph.source.encode("utf-8"))
        ),
    )


def with_geometry_digests(state: LockState, digests: Mapping[str, str]) -> LockState:
    return replace(
        state,
        active=tuple(
            replace(glyph, geometry_sha256=digests[glyph.source])
            if glyph.source in digests
            else glyph
            for glyph in state.active
        ),
    )


def finalize_glyphs(
    state: LockState,
    *,
    emitted_sources: frozenset[str],
    skipped_sources: frozenset[str],
) -> LockState:
    """Finalize assigned glyphs so every current source is emitted or tombstoned."""

    assigned_sources = {glyph.source for glyph in state.active}
    if emitted_sources & skipped_sources:
        raise IconFontError(
            "INTERNAL_OUTCOME_COLLISION",
            "A source cannot be both emitted and skipped.",
        )
    if emitted_sources | skipped_sources != assigned_sources:
        raise IconFontError(
            "INTERNAL_OUTCOME_INCOMPLETE",
            "Every assigned source must have exactly one final conversion outcome.",
        )

    active = tuple(glyph for glyph in state.active if glyph.source in emitted_sources)
    retired_by_source = {glyph.source: glyph for glyph in state.retired}
    for glyph in state.active:
        if glyph.source in skipped_sources:
            retired_by_source[glyph.source] = replace(glyph, geometry_sha256=None)
    for source in emitted_sources:
        retired_by_source.pop(source, None)

    retired = tuple(
        sorted(retired_by_source.values(), key=lambda glyph: glyph.source.encode("utf-8"))
    )
    _validate_unique((*active, *retired))
    return LockState(active=active, retired=retired)


def lock_json(state: LockState, config: BuildConfig) -> bytes:
    payload = {
        "schemaVersion": LOCK_SCHEMA_VERSION,
        "generator": GENERATOR_ID,
        "generatorVersion": __version__,
        "fontFamily": config.font_family,
        "className": config.class_name,
        "fontPackage": config.font_package,
        "startCodepoint": format_codepoint(config.start_codepoint),
        "unitsPerEm": config.units_per_em,
        "glyphs": [glyph.to_dict() for glyph in state.active],
        "retired": [glyph.to_dict() for glyph in state.retired],
    }
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_LOCK_BYTES:
        raise IconFontError(
            "LOCK_TOO_LARGE",
            "The generated codepoint lock exceeds the 64 MiB reload limit.",
            hint=(
                "Shorten source paths or metadata, split the icon pack, or start an explicitly "
                "breaking new font-family and lock epoch."
            ),
        )
    return encoded
