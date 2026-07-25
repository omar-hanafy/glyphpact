from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, cast

from .errors import IconFontError
from .identity import LEGACY_OUTPUT_MARKERS, OUTPUT_MARKER
from .naming import derive_class_name, snake_case, validate_class_name, validate_dart_name
from .portable_paths import first_nonportable_part, has_forbidden_text_character

PUA_RANGES: tuple[tuple[int, int], ...] = (
    (0xE000, 0xF8FF),
    (0xF0000, 0xFFFFD),
    (0x100000, 0x10FFFD),
)
MAX_TEXT_FONTS = 64
MAX_TEXT_FONT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_TEXT_FONT_BYTES = 256 * 1024 * 1024

_CONFIG_KEYS = frozenset(
    {
        "$schema",
        "input",
        "output",
        "fontFamily",
        "className",
        "fontPackage",
        "startCodepoint",
        "textFonts",
        "unitsPerEm",
        "precision",
        "padding",
        "clipToViewBox",
        "policy",
        "maxFileBytes",
        "maxTotalInputBytes",
        "maxIcons",
        "maxDiscoveryEntries",
        "maxElements",
        "maxExpandedElements",
        "maxExpandedBytes",
        "maxPathCommands",
        "maxTotalPathCommands",
        "jobs",
        "fontFile",
        "dartFile",
        "lockFile",
        "reportFile",
        "copyright",
        "icons",
    }
)

_ICON_KEYS = frozenset(
    {
        "name",
        "matchTextDirection",
        "partialAlpha",
        "author",
        "license",
        "sourceUrl",
        "copyright",
    }
)

_OWNERSHIP_MARKER = PurePosixPath(OUTPUT_MARKER)
_FIXED_ARTIFACTS = frozenset(
    {
        _OWNERSHIP_MARKER,
        *(PurePosixPath(marker) for marker in LEGACY_OUTPUT_MARKERS),
        PurePosixPath("ATTRIBUTION.md"),
        PurePosixPath("layer_fonts"),
    }
)


class LossyPolicy(str, Enum):
    ERROR = "error"
    CONVERT = "convert"


class UnrepresentablePolicy(str, Enum):
    ERROR = "error"
    SKIP = "skip"


class PartialAlphaMode(str, Enum):
    LAYERS = "layers"


class PartialAlphaFallback(str, Enum):
    SILHOUETTE = "silhouette"
    OPAQUE_ONLY = "opaque-only"


@dataclass(frozen=True)
class PartialAlphaConfig:
    mode: PartialAlphaMode = PartialAlphaMode.LAYERS
    fallback: PartialAlphaFallback = PartialAlphaFallback.SILHOUETTE

    def validated(self, *, source: str | None = None) -> PartialAlphaConfig:
        try:
            mode = PartialAlphaMode(self.mode)
        except (TypeError, ValueError) as error:
            raise IconFontError(
                "PARTIAL_ALPHA_MODE_INVALID",
                "Icon partialAlpha.mode must be 'layers'.",
                source=source,
            ) from error
        try:
            fallback = PartialAlphaFallback(self.fallback)
        except (TypeError, ValueError) as error:
            raise IconFontError(
                "PARTIAL_ALPHA_FALLBACK_INVALID",
                "Icon partialAlpha.fallback must be 'silhouette' or 'opaque-only'.",
                source=source,
            ) from error
        return PartialAlphaConfig(mode=mode, fallback=fallback)


@dataclass(frozen=True)
class ConversionPolicy:
    lossy: LossyPolicy = LossyPolicy.ERROR
    unrepresentable: UnrepresentablePolicy = UnrepresentablePolicy.ERROR

    def validated(self) -> ConversionPolicy:
        try:
            lossy = LossyPolicy(self.lossy)
        except (TypeError, ValueError) as error:
            raise IconFontError(
                "CONVERSION_POLICY_INVALID",
                "policy.lossy must be 'error' or 'convert'.",
            ) from error
        try:
            unrepresentable = UnrepresentablePolicy(self.unrepresentable)
        except (TypeError, ValueError) as error:
            raise IconFontError(
                "CONVERSION_POLICY_INVALID",
                "policy.unrepresentable must be 'error' or 'skip'.",
            ) from error
        return ConversionPolicy(lossy=lossy, unrepresentable=unrepresentable)


def parse_codepoint(value: str | int) -> int:
    if isinstance(value, bool):
        raise IconFontError("CODEPOINT_INVALID", "A codepoint must be an integer, not a boolean.")
    if type(value) is int:
        result = value
    elif type(value) is str:
        text = value
        if text != text.strip():
            raise IconFontError(
                "CODEPOINT_INVALID",
                f"{value!r} cannot contain surrounding whitespace.",
            )
        base = 16 if text.lower().startswith("0x") else 10
        digits = text[2:] if base == 16 else text
        pattern = r"[0-9a-fA-F]+" if base == 16 else r"[0-9]+"
        if not re.fullmatch(pattern, digits):
            raise IconFontError("CODEPOINT_INVALID", f"{value!r} is not a complete codepoint.")
        maximum_digits = 6 if base == 16 else 7
        if len(digits) > maximum_digits:
            raise IconFontError("CODEPOINT_INVALID", f"{value!r} is too long for Unicode.")
        try:
            result = int(digits, base)
        except ValueError as error:
            raise IconFontError("CODEPOINT_INVALID", f"{value!r} is not a codepoint.") from error
    else:
        raise IconFontError("CODEPOINT_INVALID", "A codepoint must be a string or integer.")
    if private_use_range(result) is None:
        raise IconFontError(
            "CODEPOINT_NOT_PRIVATE_USE",
            f"U+{result:04X} is not in a Unicode private-use range.",
            hint="Use U+E000..U+F8FF, U+F0000..U+FFFFD, or U+100000..U+10FFFD.",
        )
    return result


def validate_text(value: str, label: str, *, source: str | None = None) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise IconFontError(
            "TEXT_INVALID",
            f"{label} must contain only Unicode scalar values.",
            source=source,
        ) from error
    if has_forbidden_text_character(value):
        raise IconFontError(
            "TEXT_INVALID",
            f"{label} cannot contain control or line-separator characters.",
            source=source,
        )
    return value


def private_use_range(codepoint: int) -> tuple[int, int] | None:
    return next((bounds for bounds in PUA_RANGES if bounds[0] <= codepoint <= bounds[1]), None)


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            validate_text(key, "JSON object key", source=str(path))
            if key in result:
                raise IconFontError(
                    "JSON_DUPLICATE_KEY",
                    f"Duplicate JSON key {key!r}.",
                    source=str(path),
                )
            result[key] = value
        return result

    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise IconFontError(
                "CONFIG_TOO_LARGE",
                "The config file exceeds the 4 MiB parsing limit.",
                source=str(path),
            )
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except IconFontError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise IconFontError(
            "CONFIG_READ_FAILED",
            str(error),
            source=str(path),
        ) from error
    if not isinstance(value, dict):
        raise IconFontError("CONFIG_INVALID", "The config root must be a JSON object.")
    return value


def _relative_output_path(value: str, key: str) -> PurePosixPath:
    validate_text(value, key)
    value = unicodedata.normalize("NFC", value)
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    unsafe_part = first_nonportable_part(path.parts)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in path.parts
        or not path.name
        or len(value.encode("utf-8")) > 4_096
        or unsafe_part is not None
    ):
        raise IconFontError(
            "OUTPUT_PATH_UNSAFE",
            f"{key} must be a portable relative path inside the output directory: {value!r}.",
        )
    return path


def _artifact_path(
    raw: Mapping[str, Any], key: str, default: PurePosixPath | None
) -> PurePosixPath | None:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, str):
        raise IconFontError("CONFIG_TYPE_INVALID", f"{key} must be a string.")
    return _relative_output_path(value, key)


def _validate_artifact_paths(paths: Mapping[str, PurePosixPath]) -> None:
    items = tuple(paths.items())
    for key, path in items:
        path_parts = tuple(part.casefold() for part in path.parts)
        for fixed in _FIXED_ARTIFACTS:
            fixed_parts = tuple(part.casefold() for part in fixed.parts)
            common = min(len(path_parts), len(fixed_parts))
            if path_parts[:common] == fixed_parts[:common]:
                raise IconFontError(
                    "OUTPUT_ARTIFACT_CONFLICT",
                    f"{key} conflicts with compiler-owned artifact {fixed}.",
                )
    for index, (left_key, left) in enumerate(items):
        for right_key, right in items[index + 1 :]:
            left_parts = tuple(part.casefold() for part in left.parts)
            right_parts = tuple(part.casefold() for part in right.parts)
            common = min(len(left_parts), len(right_parts))
            if left_parts[:common] == right_parts[:common]:
                raise IconFontError(
                    "OUTPUT_ARTIFACT_CONFLICT",
                    f"{left_key} ({left}) conflicts with {right_key} ({right}).",
                    hint="Every generated artifact must have a distinct, non-nested path.",
                )


def _optional_string(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IconFontError("CONFIG_TYPE_INVALID", f"{key} must be a string or null.")
    return validate_text(value, key)


def _first_symlink_component(path: Path) -> Path | None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            status = current.lstat()
        except FileNotFoundError:
            break
        flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        is_reparse = bool(flag and getattr(status, "st_file_attributes", 0) & flag)
        is_junction = getattr(current, "is_junction", lambda: False)
        if stat.S_ISLNK(status.st_mode) or is_reparse or is_junction():
            return current
    return None


def _validate_filesystem_path_length(path: Path, label: str) -> None:
    encoded = str(path).encode("utf-8")
    if len(encoded) > 4_096:
        raise IconFontError(
            f"{label.upper()}_PATH_INVALID",
            f"The configured {label} path exceeds the 4096-byte portability limit.",
        )
    if any(len(part.encode("utf-8")) > 255 for part in path.parts):
        raise IconFontError(
            f"{label.upper()}_PATH_INVALID",
            f"The configured {label} path contains a component longer than 255 bytes.",
        )


def _hash_bounded_regular_file(path: Path, max_bytes: int) -> tuple[str, int]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise OSError("Pinned text fonts must be regular files.")
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(min(1024 * 1024, max_bytes - total + 1)):
                total += len(chunk)
                if total > max_bytes:
                    raise OSError(f"Pinned text font exceeds the {max_bytes}-byte read limit.")
                digest.update(chunk)
        return digest.hexdigest(), total
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class IconOverride:
    name: str | None = None
    match_text_direction: bool | None = None
    partial_alpha: PartialAlphaConfig | None = None
    author: str | None = None
    license: str | None = None
    source_url: str | None = None
    copyright: str | None = None

    @property
    def metadata(self) -> dict[str, str]:
        values = {
            "author": self.author,
            "license": self.license,
            "sourceUrl": self.source_url,
            "copyright": self.copyright,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True)
class TextFont:
    path: Path
    sha256: str


@dataclass(frozen=True)
class BuildConfig:
    input_path: Path
    output_dir: Path
    font_family: str = "AppIcons"
    class_name: str | None = None
    font_package: str | None = None
    start_codepoint: int = 0xE000
    units_per_em: int = 1000
    precision: int = 3
    padding: float = 0.0
    clip_to_viewbox: bool = True
    policy: ConversionPolicy = field(default_factory=ConversionPolicy)
    max_file_bytes: int = 4 * 1024 * 1024
    max_total_input_bytes: int = 64 * 1024 * 1024
    max_icons: int = 65_534
    max_discovery_entries: int = 100_000
    max_elements: int = 10_000
    max_expanded_elements: int = 2_048
    max_expanded_bytes: int = 4 * 1024 * 1024
    max_path_commands: int = 100_000
    max_total_path_commands: int = 1_000_000
    jobs: int = 0
    font_file: PurePosixPath | None = None
    dart_file: PurePosixPath | None = None
    lock_file: PurePosixPath = field(default_factory=lambda: PurePosixPath("iconfont.lock.json"))
    report_file: PurePosixPath = field(
        default_factory=lambda: PurePosixPath("iconfont.report.json")
    )
    copyright: str | None = None
    text_fonts: Mapping[str, TextFont] = field(default_factory=dict)
    icons: Mapping[str, IconOverride] = field(default_factory=dict)

    def validated(self) -> BuildConfig:
        for key, string_value in (
            ("fontFamily", self.font_family),
            ("className", self.class_name),
            ("fontPackage", self.font_package),
            ("copyright", self.copyright),
        ):
            invalid = (
                type(string_value) is not str
                if key == "fontFamily"
                else string_value is not None and type(string_value) is not str
            )
            if invalid:
                suffix = "." if key == "fontFamily" else " or null."
                raise IconFontError(
                    "CONFIG_TYPE_INVALID",
                    f"{key} must be a string{suffix}",
                )
        if type(self.clip_to_viewbox) is not bool:
            raise IconFontError("CONFIG_TYPE_INVALID", "clipToViewBox must be boolean.")
        if not isinstance(self.policy, ConversionPolicy):
            raise IconFontError("CONFIG_TYPE_INVALID", "policy must be a ConversionPolicy.")
        for key, integer_value in (
            ("startCodepoint", self.start_codepoint),
            ("unitsPerEm", self.units_per_em),
            ("precision", self.precision),
            ("maxFileBytes", self.max_file_bytes),
            ("maxTotalInputBytes", self.max_total_input_bytes),
            ("maxIcons", self.max_icons),
            ("maxDiscoveryEntries", self.max_discovery_entries),
            ("maxElements", self.max_elements),
            ("maxExpandedElements", self.max_expanded_elements),
            ("maxExpandedBytes", self.max_expanded_bytes),
            ("maxPathCommands", self.max_path_commands),
            ("maxTotalPathCommands", self.max_total_path_commands),
            ("jobs", self.jobs),
        ):
            if type(integer_value) is not int:
                raise IconFontError("CONFIG_TYPE_INVALID", f"{key} must be an integer.")
        if type(self.padding) not in {int, float}:
            raise IconFontError("CONFIG_TYPE_INVALID", "padding must be a number.")

        family = validate_text(self.font_family, "fontFamily").strip()
        if not family or len(family) > 63 or any(ord(ch) < 32 for ch in family):
            raise IconFontError(
                "FONT_FAMILY_INVALID",
                "fontFamily must contain 1 to 63 printable characters.",
            )
        class_name = validate_class_name(
            self.class_name if self.class_name is not None else derive_class_name(family)
        )
        if self.font_package is not None and not re.fullmatch(
            r"[a-z][a-z0-9_]*", self.font_package
        ):
            raise IconFontError(
                "FONT_PACKAGE_INVALID",
                "fontPackage must be a valid lower_snake_case Dart package name.",
            )
        if not 16 <= self.units_per_em <= 16_384:
            raise IconFontError(
                "UNITS_PER_EM_INVALID",
                "unitsPerEm must be between 16 and 16384.",
            )
        if not 0 <= self.precision <= 6:
            raise IconFontError("PRECISION_INVALID", "precision must be between 0 and 6.")
        padding = float(self.padding)
        if not math.isfinite(padding) or not 0 <= padding < 0.5:
            raise IconFontError("PADDING_INVALID", "padding must be at least 0 and below 0.5.")
        for key, limit_value in (
            ("maxFileBytes", self.max_file_bytes),
            ("maxTotalInputBytes", self.max_total_input_bytes),
            ("maxIcons", self.max_icons),
            ("maxDiscoveryEntries", self.max_discovery_entries),
            ("maxElements", self.max_elements),
            ("maxExpandedElements", self.max_expanded_elements),
            ("maxExpandedBytes", self.max_expanded_bytes),
            ("maxPathCommands", self.max_path_commands),
            ("maxTotalPathCommands", self.max_total_path_commands),
        ):
            if limit_value <= 0:
                raise IconFontError("CONFIG_RANGE_INVALID", f"{key} must be positive.")
        maximums = {
            "maxFileBytes": 64 * 1024 * 1024,
            "maxTotalInputBytes": 1024 * 1024 * 1024,
            "maxDiscoveryEntries": 1_000_000,
            "maxElements": 1_000_000,
            "maxExpandedElements": 1_000_000,
            "maxExpandedBytes": 1024 * 1024 * 1024,
            "maxPathCommands": 10_000_000,
            "maxTotalPathCommands": 20_000_000,
        }
        configured_limits = {
            "maxFileBytes": self.max_file_bytes,
            "maxTotalInputBytes": self.max_total_input_bytes,
            "maxDiscoveryEntries": self.max_discovery_entries,
            "maxElements": self.max_elements,
            "maxExpandedElements": self.max_expanded_elements,
            "maxExpandedBytes": self.max_expanded_bytes,
            "maxPathCommands": self.max_path_commands,
            "maxTotalPathCommands": self.max_total_path_commands,
        }
        for key, maximum in maximums.items():
            if configured_limits[key] > maximum:
                raise IconFontError(
                    "CONFIG_RANGE_INVALID",
                    f"{key} cannot exceed {maximum}.",
                )
        if self.max_file_bytes > self.max_total_input_bytes:
            raise IconFontError(
                "CONFIG_RANGE_INVALID",
                "maxFileBytes cannot exceed maxTotalInputBytes.",
            )
        if self.max_icons > 65_534:
            raise IconFontError(
                "CONFIG_RANGE_INVALID",
                "maxIcons cannot exceed the OpenType glyph limit of 65,534.",
            )
        jobs = self.jobs or min(8, os.cpu_count() or 1)
        if not 1 <= jobs <= 61:
            raise IconFontError("JOBS_INVALID", "jobs must be between 1 and 61, or 0 for auto.")
        start_codepoint = parse_codepoint(self.start_codepoint)
        policy = self.policy.validated()

        normalized_icons: dict[str, IconOverride] = {}
        for source, override in self.icons.items():
            if not isinstance(override, IconOverride):
                raise IconFontError(
                    "CONFIG_TYPE_INVALID",
                    "icons must map source paths to IconOverride values.",
                )
            validate_text(source, "icon override source")
            normalized = unicodedata.normalize("NFC", PurePosixPath(source).as_posix())
            if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
                raise IconFontError(
                    "ICON_SOURCE_INVALID",
                    f"Icon override path {source!r} is unsafe.",
                )
            if len(normalized.encode("utf-8")) > 4_096:
                raise IconFontError(
                    "ICON_SOURCE_INVALID",
                    f"Icon override path {source!r} exceeds the portability limit.",
                )
            if first_nonportable_part(PurePosixPath(normalized).parts) is not None:
                raise IconFontError(
                    "ICON_SOURCE_INVALID",
                    f"Icon override path {source!r} is not portable across platforms.",
                )
            if normalized in normalized_icons:
                raise IconFontError(
                    "ICON_SOURCE_COLLISION",
                    f"Multiple icon override paths normalize to {normalized!r}.",
                )
            if override.name is not None:
                validate_dart_name(override.name, source=normalized)
            partial_alpha = override.partial_alpha
            if partial_alpha is not None:
                if not isinstance(partial_alpha, PartialAlphaConfig):
                    raise IconFontError(
                        "CONFIG_TYPE_INVALID",
                        "Icon partial_alpha must be a PartialAlphaConfig or null.",
                        source=normalized,
                    )
                partial_alpha = partial_alpha.validated(source=normalized)
            for metadata_key, metadata_value in override.metadata.items():
                validate_text(
                    metadata_value,
                    f"icons[{normalized!r}].{metadata_key}",
                    source=normalized,
                )
            normalized_icons[normalized] = replace(override, partial_alpha=partial_alpha)

        normalized_text_fonts: dict[str, TextFont] = {}
        folded_text_families: set[str] = set()
        if len(self.text_fonts) > MAX_TEXT_FONTS:
            raise IconFontError(
                "TEXT_FONT_LIMIT",
                f"textFonts cannot contain more than {MAX_TEXT_FONTS} pinned faces.",
            )
        total_text_font_bytes = 0
        for raw_family, text_font in self.text_fonts.items():
            if not isinstance(raw_family, str) or not isinstance(text_font, TextFont):
                raise IconFontError(
                    "TEXT_FONT_INVALID",
                    "textFonts must map family strings to TextFont values.",
                )
            family_name = unicodedata.normalize(
                "NFC", validate_text(raw_family, "textFonts family").strip()
            )
            if not family_name or len(family_name) > 127:
                raise IconFontError(
                    "TEXT_FONT_FAMILY_INVALID",
                    "Text font family names must contain 1 to 127 characters.",
                )
            if family_name.casefold() in folded_text_families:
                raise IconFontError(
                    "TEXT_FONT_FAMILY_COLLISION",
                    f"Duplicate text font family {family_name!r}.",
                )
            if re.fullmatch(r"[0-9a-fA-F]{64}", text_font.sha256) is None:
                raise IconFontError(
                    "TEXT_FONT_HASH_INVALID",
                    f"textFonts[{family_name!r}].sha256 must be a SHA-256 digest.",
                )
            try:
                lexical_font = Path(os.path.abspath(text_font.path))
                _validate_filesystem_path_length(lexical_font, "text font")
                font_symlink = _first_symlink_component(lexical_font)
                font_path = lexical_font.resolve()
                status = font_path.stat()
            except IconFontError:
                raise
            except (OSError, ValueError) as error:
                raise IconFontError(
                    "TEXT_FONT_READ_FAILED",
                    str(error),
                    source=str(text_font.path),
                ) from error
            if font_symlink is not None:
                raise IconFontError(
                    "TEXT_FONT_SYMLINK_FORBIDDEN",
                    "Pinned text fonts cannot traverse symbolic links.",
                    source=str(font_symlink),
                )
            if not stat.S_ISREG(status.st_mode) or status.st_size > MAX_TEXT_FONT_BYTES:
                raise IconFontError(
                    "TEXT_FONT_READ_FAILED",
                    "Pinned text fonts must be regular files no larger than 64 MiB.",
                    source=str(font_path),
                )
            total_text_font_bytes += status.st_size
            if total_text_font_bytes > MAX_TOTAL_TEXT_FONT_BYTES:
                raise IconFontError(
                    "TEXT_FONT_LIMIT",
                    "Pinned text fonts exceed the 256 MiB aggregate input limit.",
                    source=str(font_path),
                )
            try:
                digest, actual_size = _hash_bounded_regular_file(font_path, MAX_TEXT_FONT_BYTES)
            except OSError as error:
                raise IconFontError(
                    "TEXT_FONT_READ_FAILED", str(error), source=str(font_path)
                ) from error
            total_text_font_bytes += actual_size - status.st_size
            if total_text_font_bytes > MAX_TOTAL_TEXT_FONT_BYTES:
                raise IconFontError(
                    "TEXT_FONT_LIMIT",
                    "Pinned text fonts exceed the 256 MiB aggregate input limit.",
                    source=str(font_path),
                )
            if digest != text_font.sha256.casefold():
                raise IconFontError(
                    "TEXT_FONT_HASH_MISMATCH",
                    f"Pinned text font hash is {digest}, not {text_font.sha256.casefold()}.",
                    source=str(font_path),
                )
            normalized_text_fonts[family_name] = TextFont(font_path, digest)
            folded_text_families.add(family_name.casefold())

        if self.copyright is not None:
            validate_text(self.copyright, "copyright")
        validate_text(str(self.input_path), "input path")
        validate_text(str(self.output_dir), "output path")
        _validate_filesystem_path_length(self.input_path, "input")
        _validate_filesystem_path_length(self.output_dir, "output")

        font_file = self.font_file or PurePosixPath("fonts") / f"{class_name}.otf"
        dart_file = self.dart_file or PurePosixPath(f"{snake_case(class_name)}.dart")
        normalized_artifacts = {
            "fontFile": _relative_output_path(font_file.as_posix(), "fontFile"),
            "dartFile": _relative_output_path(dart_file.as_posix(), "dartFile"),
            "lockFile": _relative_output_path(self.lock_file.as_posix(), "lockFile"),
            "reportFile": _relative_output_path(self.report_file.as_posix(), "reportFile"),
        }
        _validate_artifact_paths(normalized_artifacts)
        try:
            lexical_input = Path(os.path.abspath(self.input_path))
            _validate_filesystem_path_length(lexical_input, "input")
            input_symlink = _first_symlink_component(lexical_input)
            input_path = lexical_input.resolve()
        except IconFontError:
            raise
        except (OSError, ValueError) as error:
            raise IconFontError(
                "INPUT_PATH_INVALID", str(error), source=str(self.input_path)
            ) from error
        try:
            lexical_output = Path(os.path.abspath(self.output_dir))
            _validate_filesystem_path_length(lexical_output, "output")
            output_symlink = _first_symlink_component(lexical_output)
            output_dir = lexical_output.resolve()
        except IconFontError:
            raise
        except (OSError, ValueError) as error:
            raise IconFontError(
                "OUTPUT_PATH_INVALID", str(error), source=str(self.output_dir)
            ) from error
        if input_symlink is not None:
            raise IconFontError(
                "INPUT_SYMLINK_FORBIDDEN",
                "The configured input path cannot traverse a symbolic link.",
                source=str(input_symlink),
            )
        if output_symlink is not None:
            raise IconFontError(
                "OUTPUT_PATH_INVALID",
                "The configured output path cannot traverse a symbolic link.",
                source=str(output_symlink),
            )
        for family_name, text_font in normalized_text_fonts.items():
            if text_font.path == output_dir or output_dir in text_font.path.parents:
                raise IconFontError(
                    "TEXT_FONT_OUTPUT_CONFLICT",
                    f"Pinned text font {family_name!r} is inside the generated output tree.",
                    source=str(text_font.path),
                    hint="Store source fonts outside output so publication cannot delete them.",
                )
        if (
            output_dir == input_path
            or output_dir in input_path.parents
            or input_path in output_dir.parents
        ):
            raise IconFontError(
                "OUTPUT_OVERLAPS_INPUT",
                "The input and output trees cannot contain one another.",
                source=str(output_dir),
                hint="Choose a dedicated generated directory outside the SVG source tree.",
            )
        return BuildConfig(
            input_path=input_path,
            output_dir=output_dir,
            font_family=family,
            class_name=class_name,
            font_package=self.font_package,
            start_codepoint=start_codepoint,
            units_per_em=self.units_per_em,
            precision=self.precision,
            padding=padding,
            clip_to_viewbox=self.clip_to_viewbox,
            policy=policy,
            max_file_bytes=self.max_file_bytes,
            max_total_input_bytes=self.max_total_input_bytes,
            max_icons=self.max_icons,
            max_discovery_entries=self.max_discovery_entries,
            max_elements=self.max_elements,
            max_expanded_elements=self.max_expanded_elements,
            max_expanded_bytes=self.max_expanded_bytes,
            max_path_commands=self.max_path_commands,
            max_total_path_commands=self.max_total_path_commands,
            jobs=jobs,
            font_file=normalized_artifacts["fontFile"],
            dart_file=normalized_artifacts["dartFile"],
            lock_file=normalized_artifacts["lockFile"],
            report_file=normalized_artifacts["reportFile"],
            copyright=self.copyright,
            text_fonts=normalized_text_fonts,
            icons=normalized_icons,
        )


def load_config(path: Path) -> BuildConfig:
    raw = _load_json(path)
    unknown = set(raw) - _CONFIG_KEYS
    if unknown:
        raise IconFontError(
            "CONFIG_KEY_UNKNOWN",
            f"Unknown config key(s): {', '.join(sorted(unknown))}.",
            source=str(path),
        )
    base = path.resolve().parent
    if not isinstance(raw.get("input"), str):
        raise IconFontError("CONFIG_INPUT_REQUIRED", "The config must define string input.")
    if not isinstance(raw.get("output"), str):
        raise IconFontError("CONFIG_OUTPUT_REQUIRED", "The config must define string output.")

    validate_text(raw["input"], "input")
    validate_text(raw["output"], "output")
    if "$schema" in raw:
        if not isinstance(raw["$schema"], str):
            raise IconFontError("CONFIG_TYPE_INVALID", "$schema must be a string.")
        validate_text(raw["$schema"], "$schema")

    raw_icons = raw.get("icons", {})
    if not isinstance(raw_icons, dict):
        raise IconFontError("CONFIG_TYPE_INVALID", "icons must be an object.")
    icons: dict[str, IconOverride] = {}
    for source, value in raw_icons.items():
        if not isinstance(source, str) or not isinstance(value, dict):
            raise IconFontError("CONFIG_TYPE_INVALID", "Each icons entry must be an object.")
        extra = set(value) - _ICON_KEYS
        if extra:
            raise IconFontError(
                "CONFIG_KEY_UNKNOWN",
                f"Unknown icon key(s) for {source}: {', '.join(sorted(extra))}.",
            )
        rtl = value.get("matchTextDirection")
        if rtl is not None and not isinstance(rtl, bool):
            raise IconFontError(
                "CONFIG_TYPE_INVALID",
                f"icons[{source!r}].matchTextDirection must be boolean.",
            )
        raw_partial_alpha = value.get("partialAlpha")
        if raw_partial_alpha is not None and not isinstance(raw_partial_alpha, dict):
            raise IconFontError(
                "CONFIG_TYPE_INVALID",
                f"icons[{source!r}].partialAlpha must be an object or null.",
            )
        partial_alpha = None
        if raw_partial_alpha is not None:
            unknown_partial_alpha = set(raw_partial_alpha) - {"mode", "fallback"}
            if unknown_partial_alpha:
                raise IconFontError(
                    "CONFIG_KEY_UNKNOWN",
                    f"Unknown partialAlpha key(s) for {source}: "
                    + ", ".join(sorted(unknown_partial_alpha))
                    + ".",
                )
            raw_mode = raw_partial_alpha.get("mode")
            raw_fallback = raw_partial_alpha.get("fallback", PartialAlphaFallback.SILHOUETTE.value)
            if not isinstance(raw_mode, str) or not isinstance(raw_fallback, str):
                raise IconFontError(
                    "CONFIG_TYPE_INVALID",
                    f"icons[{source!r}].partialAlpha values must be strings.",
                )
            partial_alpha = PartialAlphaConfig(
                mode=cast(PartialAlphaMode, raw_mode),
                fallback=cast(PartialAlphaFallback, raw_fallback),
            ).validated(source=source)
        icons[source] = IconOverride(
            name=_optional_string(value.get("name"), f"icons[{source!r}].name"),
            match_text_direction=rtl,
            partial_alpha=partial_alpha,
            author=_optional_string(value.get("author"), f"icons[{source!r}].author"),
            license=_optional_string(value.get("license"), f"icons[{source!r}].license"),
            source_url=_optional_string(value.get("sourceUrl"), f"icons[{source!r}].sourceUrl"),
            copyright=_optional_string(value.get("copyright"), f"icons[{source!r}].copyright"),
        )

    raw_policy = raw.get("policy", {})
    if not isinstance(raw_policy, dict):
        raise IconFontError("CONFIG_TYPE_INVALID", "policy must be an object.")
    unknown_policy_keys = set(raw_policy) - {"lossy", "unrepresentable"}
    if unknown_policy_keys:
        raise IconFontError(
            "CONFIG_KEY_UNKNOWN",
            "Unknown policy key(s): " + ", ".join(sorted(unknown_policy_keys)) + ".",
        )
    lossy = raw_policy.get("lossy", LossyPolicy.ERROR.value)
    unrepresentable = raw_policy.get("unrepresentable", UnrepresentablePolicy.ERROR.value)
    if not isinstance(lossy, str) or not isinstance(unrepresentable, str):
        raise IconFontError(
            "CONFIG_TYPE_INVALID",
            "policy values must be strings.",
        )
    policy = ConversionPolicy(
        lossy=cast(LossyPolicy, lossy),
        unrepresentable=cast(UnrepresentablePolicy, unrepresentable),
    ).validated()

    raw_text_fonts = raw.get("textFonts", {})
    if not isinstance(raw_text_fonts, dict):
        raise IconFontError("CONFIG_TYPE_INVALID", "textFonts must be an object.")
    text_fonts: dict[str, TextFont] = {}
    for family_name, value in raw_text_fonts.items():
        if not isinstance(family_name, str) or not isinstance(value, dict):
            raise IconFontError(
                "CONFIG_TYPE_INVALID",
                "Each textFonts entry must be an object.",
            )
        unknown_font_keys = set(value) - {"file", "sha256"}
        if unknown_font_keys:
            raise IconFontError(
                "CONFIG_KEY_UNKNOWN",
                f"Unknown textFonts key(s) for {family_name}: "
                + ", ".join(sorted(unknown_font_keys))
                + ".",
            )
        file_value = value.get("file")
        hash_value = value.get("sha256")
        if not isinstance(file_value, str) or not isinstance(hash_value, str):
            raise IconFontError(
                "CONFIG_TYPE_INVALID",
                f"textFonts[{family_name!r}] requires string file and sha256 values.",
            )
        text_fonts[family_name] = TextFont(base / file_value, hash_value)

    def integer(key: str, default: int) -> int:
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise IconFontError("CONFIG_TYPE_INVALID", f"{key} must be an integer.")
        return value

    def number(key: str, default: float) -> float:
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IconFontError("CONFIG_TYPE_INVALID", f"{key} must be a number.")
        return float(value)

    def boolean(key: str, default: bool) -> bool:
        value = raw.get(key, default)
        if not isinstance(value, bool):
            raise IconFontError("CONFIG_TYPE_INVALID", f"{key} must be boolean.")
        return value

    if "fontFamily" in raw and not isinstance(raw["fontFamily"], str):
        raise IconFontError("CONFIG_TYPE_INVALID", "fontFamily must be a string.")
    start = parse_codepoint(raw.get("startCodepoint", "0xE000"))
    config = BuildConfig(
        input_path=base / raw["input"],
        output_dir=base / raw["output"],
        font_family=raw.get("fontFamily", "AppIcons"),
        class_name=_optional_string(raw.get("className"), "className"),
        font_package=_optional_string(raw.get("fontPackage"), "fontPackage"),
        start_codepoint=start,
        units_per_em=integer("unitsPerEm", 1000),
        precision=integer("precision", 3),
        padding=number("padding", 0.0),
        clip_to_viewbox=boolean("clipToViewBox", True),
        policy=policy,
        max_file_bytes=integer("maxFileBytes", 4 * 1024 * 1024),
        max_total_input_bytes=integer("maxTotalInputBytes", 64 * 1024 * 1024),
        max_icons=integer("maxIcons", 65_534),
        max_discovery_entries=integer("maxDiscoveryEntries", 100_000),
        max_elements=integer("maxElements", 10_000),
        max_expanded_elements=integer("maxExpandedElements", 2_048),
        max_expanded_bytes=integer("maxExpandedBytes", 4 * 1024 * 1024),
        max_path_commands=integer("maxPathCommands", 100_000),
        max_total_path_commands=integer("maxTotalPathCommands", 1_000_000),
        jobs=integer("jobs", 0),
        font_file=_artifact_path(raw, "fontFile", None),
        dart_file=_artifact_path(raw, "dartFile", None),
        lock_file=cast(
            PurePosixPath,
            _artifact_path(raw, "lockFile", PurePosixPath("iconfont.lock.json")),
        ),
        report_file=cast(
            PurePosixPath,
            _artifact_path(raw, "reportFile", PurePosixPath("iconfont.report.json")),
        ),
        copyright=_optional_string(raw.get("copyright"), "copyright"),
        text_fonts=text_fonts,
        icons=icons,
    )
    return config.validated()
