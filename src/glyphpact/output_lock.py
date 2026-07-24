from __future__ import annotations

import errno
import importlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from .errors import IconFontError
from .identity import OUTPUT_LOCK_SUFFIX


def _is_reparse_point(status: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and getattr(status, "st_file_attributes", 0) & flag)


def _validate_lock_status(status: os.stat_result, lock_path: Path) -> None:
    if (
        not stat.S_ISREG(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or _is_reparse_point(status)
        or status.st_nlink != 1
    ):
        raise IconFontError(
            "OUTPUT_LOCK_FAILED",
            "The output coordination lock must be one regular, unlinked file.",
            source=str(lock_path),
        )


def _lock_file(stream: BinaryIO) -> None:
    if os.name == "nt":
        msvcrt = importlib.import_module("msvcrt")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl = importlib.import_module("fcntl")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(stream: BinaryIO) -> None:
    try:
        if os.name == "nt":
            msvcrt = importlib.import_module("msvcrt")
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl = importlib.import_module("fcntl")
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Closing the descriptor releases an advisory lock even if an explicit
        # unlock fails during interpreter or filesystem teardown.
        pass


@contextmanager
def output_lock(output_dir: Path) -> Iterator[None]:
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = parent / f".{output_dir.name}{OUTPUT_LOCK_SUFFIX}"
    try:
        before_status = lock_path.lstat()
        _validate_lock_status(before_status, lock_path)
    except FileNotFoundError:
        before_status = None
    except IconFontError:
        raise
    except OSError as error:
        raise IconFontError(
            "OUTPUT_LOCK_FAILED",
            str(error),
            source=str(lock_path),
        ) from error
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o666)
    except OSError as error:
        raise IconFontError(
            "OUTPUT_LOCK_FAILED",
            str(error),
            source=str(lock_path),
        ) from error
    try:
        opened_status = os.fstat(descriptor)
        after_status = lock_path.lstat()
        _validate_lock_status(opened_status, lock_path)
        _validate_lock_status(after_status, lock_path)
        if not os.path.samestat(opened_status, after_status) or (
            before_status is not None and not os.path.samestat(before_status, after_status)
        ):
            raise IconFontError(
                "OUTPUT_LOCK_FAILED",
                "The output coordination lock changed while it was being opened.",
                source=str(lock_path),
            )
    except IconFontError:
        os.close(descriptor)
        raise
    except OSError as error:
        os.close(descriptor)
        raise IconFontError("OUTPUT_LOCK_FAILED", str(error), source=str(lock_path)) from error

    stream = os.fdopen(descriptor, "r+b", buffering=0)
    acquired = False
    try:
        try:
            _lock_file(stream)
            locked_status = lock_path.lstat()
            _validate_lock_status(locked_status, lock_path)
            if not os.path.samestat(os.fstat(stream.fileno()), locked_status):
                raise IconFontError(
                    "OUTPUT_LOCK_FAILED",
                    "The output coordination lock changed during acquisition.",
                    source=str(lock_path),
                )
            acquired = True
        except IconFontError:
            raise
        except OSError as error:
            busy_codes = {errno.EACCES, errno.EAGAIN}
            if error.errno in busy_codes or getattr(error, "winerror", None) in {33, 36}:
                raise IconFontError(
                    "OUTPUT_BUSY",
                    "Another compiler process is already building this output directory.",
                    source=str(output_dir),
                    hint="Wait for that process to finish, then retry.",
                ) from error
            raise IconFontError(
                "OUTPUT_LOCK_FAILED",
                str(error),
                source=str(lock_path),
            ) from error
        yield
    finally:
        if acquired:
            _unlock_file(stream)
        stream.close()
