from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path, PurePosixPath

from .errors import IconFontError
from .identity import (
    GENERATOR_ID,
    OUTPUT_MARKER,
    OUTPUT_MARKER_IDENTITIES,
    TRANSACTION_MARKER,
    TRANSACTION_MARKER_IDENTITIES,
)

MARKER = OUTPUT_MARKER
_TRANSACTION_MARKER = TRANSACTION_MARKER
_TRANSACTION_PREVIOUS = "previous"
_MAX_OUTPUT_ENTRIES = 100_000


def marker_bytes() -> bytes:
    return (f'{{\n  "schemaVersion": 1,\n  "owner": "{GENERATOR_ID}"\n}}\n').encode()


def _transaction_marker_bytes() -> bytes:
    return (
        '{\n  "schemaVersion": 1,\n'
        f'  "owner": "{GENERATOR_ID}",\n'
        '  "kind": "output-transaction"\n'
        "}\n"
    ).encode()


def _fsync_file(path: Path) -> None:
    # Windows rejects fsync on a descriptor opened read-only with EBADF.
    # Generated files are owned by this transaction, so keep the handle
    # writable while flushing it on every supported platform.
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


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


def _safe_relative_text(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("ascii", "backslashreplace").decode("ascii")
    return value


def _scan_output_tree(root: Path) -> tuple[dict[str, Path], set[str], set[str]]:
    """Classify a generated tree without following links or reading file contents."""
    try:
        root_status = root.lstat()
    except OSError as error:
        raise IconFontError("OUTPUT_TREE_READ_FAILED", str(error), source=str(root)) from error
    is_junction = getattr(root, "is_junction", lambda: False)
    if (
        stat.S_ISLNK(root_status.st_mode)
        or _is_reparse_point(root_status)
        or is_junction()
        or not stat.S_ISDIR(root_status.st_mode)
        or _is_mount(root)
    ):
        raise IconFontError(
            "OUTPUT_PATH_INVALID",
            "The generated output root must be a real, unmounted directory.",
            source=str(root),
        )

    files: dict[str, Path] = {}
    directories: set[str] = set()
    special_entries: set[str] = set()

    pending_directories = [root]
    entry_count = 0
    while pending_directories:
        directory = pending_directories.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = []
                for entry in iterator:
                    entry_count += 1
                    if entry_count > _MAX_OUTPUT_ENTRIES:
                        raise IconFontError(
                            "OUTPUT_TREE_TOO_LARGE",
                            f"Generated output cannot exceed {_MAX_OUTPUT_ENTRIES} entries.",
                            source=str(root),
                        )
                    entries.append(entry)
        except OSError as error:
            raise IconFontError(
                "OUTPUT_TREE_READ_FAILED", str(error), source=str(directory)
            ) from error
        child_directories: list[Path] = []
        for entry in sorted(entries, key=lambda value: os.fsencode(value.name)):
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise IconFontError(
                    "OUTPUT_TREE_READ_FAILED", str(error), source=str(path)
                ) from error
            entry_is_junction = getattr(path, "is_junction", lambda: False)
            if stat.S_ISLNK(status.st_mode) or _is_reparse_point(status) or entry_is_junction():
                raise IconFontError(
                    "OUTPUT_SYMLINK_FORBIDDEN",
                    "Generated output cannot contain symbolic links, junctions, or reparse points.",
                    source=str(path),
                )
            if stat.S_ISDIR(status.st_mode):
                if _is_mount(path):
                    raise IconFontError(
                        "OUTPUT_MOUNT_FORBIDDEN",
                        "Generated output cannot contain nested mount points.",
                        source=str(path),
                    )
                directories.add(relative)
                child_directories.append(path)
            elif stat.S_ISREG(status.st_mode):
                if status.st_nlink != 1:
                    raise IconFontError(
                        "OUTPUT_HARDLINK_FORBIDDEN",
                        "Generated output files cannot be hard-linked.",
                        source=str(path),
                    )
                files[relative] = path
            else:
                special_entries.add(relative)
        pending_directories.extend(reversed(child_directories))
    return files, directories, special_entries


def _expected_directories(paths: set[str]) -> set[str]:
    result: set[str] = set()
    for value in paths:
        parent = PurePosixPath(value).parent
        while parent != PurePosixPath("."):
            result.add(parent.as_posix())
            parent = parent.parent
    return result


def _matches_expected_file(path: Path, expected: bytes) -> bool:
    try:
        status = path.lstat()
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1
            or status.st_size != len(expected)
        ):
            return False
        with path.open("rb") as stream:
            return stream.read(len(expected) + 1) == expected
    except OSError as error:
        raise IconFontError("OUTPUT_TREE_READ_FAILED", str(error), source=str(path)) from error


def _artifact_diff(
    root: Path, artifacts: Mapping[PurePosixPath, bytes]
) -> tuple[list[str], list[str], list[str]]:
    expected = {path.as_posix(): data for path, data in artifacts.items()}
    if not root.exists() and not root.is_symlink():
        return sorted(expected), [], []
    files, directories, special_entries = _scan_output_tree(root)
    expected_paths = set(expected)
    missing = sorted(expected_paths - set(files))
    extra_raw = (
        (set(files) - expected_paths)
        | (directories - _expected_directories(expected_paths))
        | special_entries
    )
    extra = sorted(_safe_relative_text(value) for value in extra_raw)
    changed = sorted(
        path
        for path in expected_paths & set(files)
        if not _matches_expected_file(files[path], expected[path])
    )
    return missing, extra, changed


def validate_output_tree(root: Path) -> None:
    _scan_output_tree(root)


def compare_artifacts(output_dir: Path, artifacts: Mapping[PurePosixPath, bytes]) -> None:
    missing, extra, changed = _artifact_diff(output_dir, artifacts)
    if missing or extra or changed:
        raise IconFontError(
            "OUTPUT_OUT_OF_DATE",
            "Generated output does not match the current inputs and lock state.",
            details={"missing": missing, "extra": extra, "changed": changed},
            hint="Run the same command without --check and commit the resulting output.",
        )


def _find_identity_marker(
    root: Path,
    identities: tuple[tuple[str, str], ...],
    *,
    error_code: str,
    label: str,
) -> tuple[Path, str] | None:
    matches = [
        (root / filename, owner)
        for filename, owner in identities
        if (root / filename).exists() or (root / filename).is_symlink()
    ]
    if len(matches) > 1:
        raise IconFontError(
            error_code,
            f"The {label} contains conflicting current and legacy identity markers.",
            source=str(root),
        )
    return matches[0] if matches else None


def verify_output_ownership(output_dir: Path, *, adopt: bool) -> bool:
    if not output_dir.exists():
        return False
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise IconFontError(
            "OUTPUT_PATH_INVALID",
            "The output path must be a real directory.",
            source=str(output_dir),
        )
    if not any(output_dir.iterdir()):
        return False
    marker_identity = _find_identity_marker(
        output_dir,
        OUTPUT_MARKER_IDENTITIES,
        error_code="OUTPUT_MARKER_INVALID",
        label="output directory",
    )
    marker = marker_identity[0] if marker_identity is not None else output_dir / MARKER
    expected_owner = marker_identity[1] if marker_identity is not None else GENERATOR_ID
    if marker.is_symlink():
        raise IconFontError(
            "OUTPUT_MARKER_INVALID",
            "The output ownership marker cannot be a symbolic link.",
            source=str(marker),
        )
    if not marker.is_file() and not adopt:
        raise IconFontError(
            "OUTPUT_NOT_OWNED",
            "Refusing to replace a non-empty directory not owned by this compiler.",
            source=str(output_dir),
            hint="Choose a dedicated output directory or pass --adopt-output once.",
        )
    if marker.is_file():

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise IconFontError(
                        "OUTPUT_MARKER_INVALID",
                        "The output ownership marker contains a duplicate JSON key.",
                        source=str(marker),
                    )
                result[key] = value
            return result

        try:
            if marker.stat().st_size > 4_096:
                raise IconFontError(
                    "OUTPUT_MARKER_INVALID",
                    "The output ownership marker exceeds 4096 bytes.",
                    source=str(marker),
                )
            payload = json.loads(
                marker.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
            )
        except IconFontError:
            raise
        except (OSError, UnicodeError, ValueError, RecursionError) as error:
            raise IconFontError("OUTPUT_MARKER_INVALID", str(error), source=str(marker)) from error
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schemaVersion", "owner"}
            or type(payload["schemaVersion"]) is not int
            or payload["schemaVersion"] != 1
            or type(payload["owner"]) is not str
            or payload["owner"] != expected_owner
        ):
            raise IconFontError(
                "OUTPUT_MARKER_INVALID",
                "The output ownership marker schema is not recognized.",
                source=str(marker),
            )
        return True
    return False


def _is_transaction_backup(backup: Path) -> bool:
    marker_identity = _find_identity_marker(
        backup,
        TRANSACTION_MARKER_IDENTITIES,
        error_code="OUTPUT_TRANSACTION_INVALID",
        label="output transaction",
    )
    if marker_identity is None:
        return False
    marker, expected_owner = marker_identity
    if marker.is_symlink() or not marker.is_file():
        raise IconFontError(
            "OUTPUT_TRANSACTION_INVALID",
            "The output transaction marker must be a regular file.",
            source=str(marker),
        )

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise IconFontError(
                    "OUTPUT_TRANSACTION_INVALID",
                    "The output transaction marker contains a duplicate JSON key.",
                    source=str(marker),
                )
            result[key] = value
        return result

    try:
        if marker.stat().st_size > 4_096:
            raise IconFontError(
                "OUTPUT_TRANSACTION_INVALID",
                "The output transaction marker exceeds 4096 bytes.",
                source=str(marker),
            )
        payload = json.loads(
            marker.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except IconFontError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise IconFontError("OUTPUT_TRANSACTION_INVALID", str(error), source=str(marker)) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schemaVersion", "owner", "kind"}
        or type(payload["schemaVersion"]) is not int
        or payload["schemaVersion"] != 1
        or type(payload["owner"]) is not str
        or payload["owner"] != expected_owner
        or type(payload["kind"]) is not str
        or payload["kind"] != "output-transaction"
    ):
        raise IconFontError(
            "OUTPUT_TRANSACTION_INVALID",
            "The output transaction marker schema is not recognized.",
            source=str(marker),
        )
    return True


def _remove_backup(backup: Path, output_dir: Path) -> None:
    try:
        shutil.rmtree(backup)
        _fsync_directory(output_dir.parent)
    except OSError as error:
        raise IconFontError(
            "OUTPUT_RECOVERY_FAILED",
            str(error),
            source=str(backup),
            hint="The committed output is intact, but its old transaction could not be removed.",
        ) from error


def _validate_current_recovery_output(
    output_dir: Path, backup: Path, lock_path: Path | None
) -> None:
    verify_output_ownership(output_dir, adopt=False)
    validate_output_tree(output_dir)
    if lock_path is None or not lock_path.is_file() or lock_path.is_symlink():
        raise IconFontError(
            "OUTPUT_RECOVERY_REQUIRED",
            "Current output and its backup both exist, but the current lock cannot be trusted.",
            source=str(backup),
            hint="Keep both directories and inspect which lock file is the last valid ABI state.",
        )
    from .manifest import load_lock

    load_lock(lock_path)


def _recover_transaction_backup(
    output_dir: Path,
    backup: Path,
    *,
    lock_path: Path | None,
    read_only: bool,
) -> None:
    validate_output_tree(backup)
    previous = backup / _TRANSACTION_PREVIOUS
    previous_exists = previous.exists() or previous.is_symlink()
    if not previous_exists:
        if not output_dir.exists() and not output_dir.is_symlink():
            raise IconFontError(
                "OUTPUT_TRANSACTION_INVALID",
                "The output transaction has neither a current nor a previous tree.",
                source=str(backup),
            )
        if not read_only:
            _remove_backup(backup, output_dir)
        return

    if output_dir.exists() or output_dir.is_symlink():
        _validate_current_recovery_output(output_dir, backup, lock_path)
        if not read_only:
            _remove_backup(backup, output_dir)
        return
    if read_only:
        raise IconFontError(
            "OUTPUT_RECOVERY_REQUIRED",
            "An interrupted output transaction must be recovered before checking.",
            source=str(backup),
            hint="Run the build without --check once to restore the previous output safely.",
        )
    try:
        os.replace(previous, output_dir)
        _fsync_directory(backup)
        _fsync_directory(output_dir.parent)
        shutil.rmtree(backup)
        _fsync_directory(output_dir.parent)
    except OSError as error:
        raise IconFontError("OUTPUT_RECOVERY_FAILED", str(error), source=str(backup)) from error


def _create_transaction_backup(output_dir: Path, backup: Path) -> Path:
    parent = output_dir.parent
    container = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.transaction-", dir=parent))
    try:
        marker = container / _TRANSACTION_MARKER
        marker.write_bytes(_transaction_marker_bytes())
        marker.chmod(0o644)
        _fsync_file(marker)
        container.chmod(0o755)
        _fsync_directory(container)
        os.replace(container, backup)
        _fsync_directory(parent)
    except Exception:
        if container.exists():
            shutil.rmtree(container, ignore_errors=True)
        raise
    return backup / _TRANSACTION_PREVIOUS


def recover_output(
    output_dir: Path,
    *,
    lock_path: Path | None = None,
    read_only: bool = False,
) -> None:
    backup = output_dir.parent / f".{output_dir.name}.backup"
    if not backup.exists() and not backup.is_symlink():
        return
    if _is_transaction_backup(backup):
        _recover_transaction_backup(
            output_dir,
            backup,
            lock_path=lock_path,
            read_only=read_only,
        )
        return
    verify_output_ownership(backup, adopt=False)
    validate_output_tree(backup)
    if output_dir.exists():
        _validate_current_recovery_output(output_dir, backup, lock_path)
        if not read_only:
            _remove_backup(backup, output_dir)
        return
    if read_only:
        raise IconFontError(
            "OUTPUT_RECOVERY_REQUIRED",
            "An interrupted output transaction must be recovered before checking.",
            source=str(backup),
            hint="Run the build without --check once to restore the last committed lock safely.",
        )
    try:
        os.replace(backup, output_dir)
        _fsync_directory(output_dir.parent)
    except OSError as error:
        raise IconFontError(
            "OUTPUT_RECOVERY_FAILED",
            str(error),
            source=str(backup),
        ) from error


def publish_artifacts(
    output_dir: Path,
    artifacts: Mapping[PurePosixPath, bytes],
    *,
    adopt: bool = False,
) -> None:
    recover_output(output_dir)
    verify_output_ownership(output_dir, adopt=adopt)
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    backup = parent / f".{output_dir.name}.backup"

    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=parent))
    try:
        for relative, data in artifacts.items():
            target = stage.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o644)
            _fsync_file(target)
        for directory in sorted(
            (path for path in stage.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o755)
            _fsync_directory(directory)
        stage.chmod(0o755)
        _fsync_directory(stage)
        _fsync_directory(parent)
        missing, extra, changed = _artifact_diff(stage, artifacts)
        if missing or extra or changed:
            raise IconFontError(
                "OUTPUT_STAGE_CORRUPT",
                "The staged output tree did not verify before publication.",
                details={"missing": missing, "extra": extra, "changed": changed},
            )

        had_output = output_dir.exists()
        if had_output:
            validate_output_tree(output_dir)
            previous = _create_transaction_backup(output_dir, backup)
            os.replace(output_dir, previous)
            _fsync_directory(backup)
            _fsync_directory(parent)
        try:
            os.replace(stage, output_dir)
            _fsync_directory(parent)
        except Exception:
            previous = backup / _TRANSACTION_PREVIOUS
            if had_output and previous.exists() and not output_dir.exists():
                os.replace(previous, output_dir)
                _fsync_directory(backup)
                _fsync_directory(parent)
                shutil.rmtree(backup)
                _fsync_directory(parent)
            raise
        if backup.exists():
            with suppress(OSError):
                shutil.rmtree(backup)
                _fsync_directory(parent)
    except IconFontError:
        raise
    except OSError as error:
        raise IconFontError("OUTPUT_PUBLISH_FAILED", str(error), source=str(output_dir)) from error
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
