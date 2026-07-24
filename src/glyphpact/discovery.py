from __future__ import annotations

import errno
import hashlib
import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import BatchError, Diagnostic, IconFontError
from .portable_paths import first_nonportable_part, has_forbidden_text_character


@dataclass(frozen=True)
class SvgSource:
    path: Path
    source_id: str
    content: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class _DiscoveredSvg:
    path: Path
    status: os.stat_result


class _SvgReadError(IconFontError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        bytes_read: int,
        source: str | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.bytes_read = bytes_read
        super().__init__(code, message, source=source, hint=hint, details=details)


def _same_discovered_file(
    expected: os.stat_result,
    opened: os.stat_result,
    *,
    windows: bool | None = None,
) -> bool:
    if windows is None:
        windows = os.name == "nt"
    if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino) or (
        opened.st_size,
        opened.st_mtime_ns,
    ) != (expected.st_size, expected.st_mtime_ns):
        return False
    # Windows path-based stat and descriptor-based fstat can report different
    # creation-time values. st_ctime is deprecated there and is not a portable
    # change detector. The file identity, size, and modification time remain
    # binding; POSIX additionally has reliable metadata-change time.
    return windows or opened.st_ctime_ns == expected.st_ctime_ns


def _read_svg(
    discovered: _DiscoveredSvg,
    source_id: str,
    max_bytes: int,
    remaining_total_bytes: int,
) -> SvgSource:
    path = discovered.path
    read_limit = min(max_bytes, remaining_total_bytes) + 1
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        source_changed = error.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
        raise _SvgReadError(
            "SVG_SOURCE_CHANGED" if source_changed else "SVG_READ_FAILED",
            (
                "The SVG became unavailable or changed after filesystem discovery."
                if source_changed
                else str(error)
            ),
            source=source_id,
            bytes_read=0,
            details={"reason": str(error)} if source_changed else None,
        ) from error
    try:
        try:
            before = os.fstat(descriptor)
            expected = discovered.status
            if not stat.S_ISREG(before.st_mode) or not _same_discovered_file(expected, before):
                raise _SvgReadError(
                    "SVG_SOURCE_CHANGED",
                    "The opened SVG is not the regular file observed during discovery.",
                    source=source_id,
                    bytes_read=0,
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(read_limit)
            after = os.fstat(descriptor)
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) != (before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                raise _SvgReadError(
                    "SVG_SOURCE_CHANGED",
                    "The SVG changed while it was being read.",
                    source=source_id,
                    bytes_read=len(data),
                )
        except _SvgReadError:
            raise
        except OSError as error:
            raise _SvgReadError(
                "SVG_READ_FAILED",
                str(error),
                source=source_id,
                bytes_read=read_limit,
            ) from error
    finally:
        os.close(descriptor)
    if len(data) > remaining_total_bytes:
        raise _SvgReadError(
            "SVG_BATCH_TOO_LARGE",
            "The SVG batch exceeds the configured total input limit.",
            source=source_id,
            hint="Split the pack or raise maxTotalInputBytes for trusted assets.",
            bytes_read=len(data),
        )
    if len(data) > max_bytes:
        raise _SvgReadError(
            "SVG_TOO_LARGE",
            f"The file exceeds the {max_bytes}-byte input limit.",
            source=source_id,
            hint="Raise maxFileBytes only for a trusted asset.",
            bytes_read=len(data),
        )
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _SvgReadError(
            "SVG_NOT_UTF8",
            str(error),
            source=source_id,
            bytes_read=len(data),
        ) from error
    return SvgSource(
        path=path,
        source_id=source_id,
        content=content,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
    )


def _relative_id(path: Path, root: Path) -> str:
    relative = path.name if path == root else path.relative_to(root).as_posix()
    normalized = unicodedata.normalize("NFC", relative)
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise IconFontError(
            "SOURCE_PATH_INVALID_UNICODE",
            "SVG paths must contain only Unicode scalar values.",
            source=repr(relative),
        ) from error
    if has_forbidden_text_character(normalized):
        raise IconFontError(
            "SOURCE_PATH_CONTROL_CHARACTER",
            "SVG paths cannot contain control or line-separator characters.",
            source=repr(normalized),
        )
    if len(normalized.encode("utf-8")) > 4_096:
        raise IconFontError(
            "SOURCE_PATH_NOT_PORTABLE",
            "SVG source IDs cannot exceed 4096 UTF-8 bytes.",
            source=repr(normalized),
        )
    if first_nonportable_part(PurePosixPath(normalized).parts) is not None:
        raise IconFontError(
            "SOURCE_PATH_NOT_PORTABLE",
            "SVG paths must be valid on Windows, macOS, and Linux.",
            source=normalized,
        )
    return PurePosixPath(normalized).as_posix()


def _is_reparse_point(status: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and getattr(status, "st_file_attributes", 0) & flag)


def _is_mount(path: Path) -> bool:
    check = getattr(path, "is_mount", None)
    if not callable(check):
        return False
    try:
        return bool(check())
    except NotImplementedError:
        return False


def _walk(root: Path, max_icons: int, max_entries: int) -> list[_DiscoveredSvg]:
    try:
        root_status = root.lstat()
    except FileNotFoundError as error:
        raise IconFontError(
            "INPUT_NOT_FOUND",
            "The input path is not a file or directory.",
            source=str(root),
        ) from error
    except OSError as error:
        raise IconFontError("INPUT_PATH_INVALID", str(error), source=str(root)) from error
    root_is_junction = getattr(root, "is_junction", lambda: False)
    if stat.S_ISLNK(root_status.st_mode) or _is_reparse_point(root_status) or root_is_junction():
        raise IconFontError(
            "INPUT_SYMLINK_FORBIDDEN",
            "The input path cannot be a symbolic link, junction, or reparse point.",
            source=str(root),
        )
    if stat.S_ISREG(root_status.st_mode):
        if root.suffix.lower() != ".svg":
            raise IconFontError(
                "INPUT_NOT_SVG",
                "The input file must have an .svg extension.",
                source=str(root),
            )
        return [_DiscoveredSvg(root, root_status)]
    if not stat.S_ISDIR(root_status.st_mode):
        raise IconFontError(
            "INPUT_NOT_FOUND",
            "The input path is not a file or directory.",
            source=str(root),
        )

    files: list[_DiscoveredSvg] = []
    directories = [root]
    entry_count = 0
    while directories:
        directory = directories.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = []
                for entry in iterator:
                    entry_count += 1
                    if entry_count > max_entries:
                        raise IconFontError(
                            "INPUT_TREE_TOO_LARGE",
                            f"The input tree contains more than {max_entries} filesystem entries.",
                            source=str(root),
                            hint="Remove unrelated files or raise maxDiscoveryEntries.",
                        )
                    entries.append(entry)
        except OSError as error:
            raise IconFontError(
                "INPUT_DIRECTORY_READ_FAILED",
                str(error),
                source=str(directory),
            ) from error
        child_directories: list[Path] = []
        for entry in sorted(entries, key=lambda value: os.fsencode(value.name)):
            path = Path(entry.path)
            try:
                status = path.lstat()
            except OSError as error:
                raise IconFontError("INPUT_PATH_INVALID", str(error), source=str(path)) from error
            entry_is_junction = getattr(path, "is_junction", lambda: False)
            if stat.S_ISLNK(status.st_mode) or _is_reparse_point(status) or entry_is_junction():
                raise IconFontError(
                    "INPUT_SYMLINK_FORBIDDEN",
                    "Links, junctions, and reparse points are not followed during discovery.",
                    source=str(path),
                    hint="Copy the file or directory into the input tree.",
                )
            if stat.S_ISDIR(status.st_mode):
                if _is_mount(path):
                    raise IconFontError(
                        "INPUT_MOUNT_FORBIDDEN",
                        "Nested mount points are not traversed during icon discovery.",
                        source=str(path),
                    )
                child_directories.append(path)
            elif stat.S_ISREG(status.st_mode) and entry.name.lower().endswith(".svg"):
                files.append(_DiscoveredSvg(path, status))
                if len(files) > max_icons:
                    raise IconFontError(
                        "TOO_MANY_ICONS",
                        f"The input contains more than {max_icons} SVG files.",
                        source=str(root),
                        hint="Split the pack into multiple fonts.",
                    )

        directories.extend(reversed(child_directories))
    return files


def discover_svg_sources(
    input_path: Path,
    *,
    max_bytes: int,
    max_total_bytes: int,
    max_icons: int,
    max_entries: int,
) -> tuple[SvgSource, ...]:
    paths = _walk(input_path, max_icons, max_entries)
    if not paths:
        raise IconFontError(
            "NO_SVG_FILES",
            "No SVG files were found recursively.",
            source=str(input_path),
        )

    ids: dict[str, str] = {}
    casefolded: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    sources: list[SvgSource] = []
    total_bytes = 0
    for discovered in paths:
        path = discovered.path
        try:
            source_id = _relative_id(path, input_path)
            if source_id in ids:
                raise IconFontError(
                    "SOURCE_PATH_COLLISION",
                    f"The normalized path collides with {ids[source_id]!r}.",
                    source=source_id,
                )
            folded = source_id.casefold()
            if folded in casefolded:
                raise IconFontError(
                    "SOURCE_PATH_PORTABILITY_COLLISION",
                    f"The path differs only by case from {casefolded[folded]!r}.",
                    source=source_id,
                    hint="Rename one file so the pack works on case-insensitive filesystems.",
                )
            ids[source_id] = str(path)
            casefolded[folded] = source_id
            source = _read_svg(
                discovered,
                source_id,
                max_bytes,
                max_total_bytes - total_bytes,
            )
        except _SvgReadError as error:
            total_bytes += error.bytes_read
            if error.diagnostic.code == "SVG_BATCH_TOO_LARGE" or total_bytes > max_total_bytes:
                raise IconFontError(
                    "SVG_BATCH_TOO_LARGE",
                    f"The SVG batch exceeds the {max_total_bytes}-byte total input limit.",
                    source=str(input_path),
                    hint="Split the pack or raise maxTotalInputBytes for trusted assets.",
                ) from error
            diagnostics.append(error.diagnostic)
            continue
        except IconFontError as error:
            diagnostics.append(error.diagnostic)
            continue
        total_bytes += source.byte_count
        if total_bytes > max_total_bytes:
            raise IconFontError(
                "SVG_BATCH_TOO_LARGE",
                f"The SVG batch exceeds the {max_total_bytes}-byte total input limit.",
                source=str(input_path),
                hint="Split the pack or raise maxTotalInputBytes for trusted assets.",
            )
        sources.append(source)
    if diagnostics:
        raise BatchError(diagnostics)
    return tuple(sorted(sources, key=lambda source: source.source_id.encode("utf-8")))
