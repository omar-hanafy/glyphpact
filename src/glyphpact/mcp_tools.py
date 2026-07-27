"""MCP-facing operations backed by the canonical GlyphPact CLI contract."""

from __future__ import annotations

import asyncio
import atexit
import copy
import json
import math
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

_MAX_STDERR_BYTES = 8_192
_MAX_CLI_STDOUT_BYTES = 64 * 1024 * 1024
_MAX_REPORT_BYTES = 128 * 1024 * 1024
_MAX_PAGE_SIZE = 500
_MAX_PAGE_BYTES = 1024 * 1024
_MAX_AUDIT_SNAPSHOT_BYTES = _MAX_CLI_STDOUT_BYTES
_MAX_AUDIT_SNAPSHOT_TOTAL_BYTES = 2 * _MAX_AUDIT_SNAPSHOT_BYTES
_MAX_AUDIT_SNAPSHOTS = 8
_AUDIT_SNAPSHOT_IDLE_TTL_SECONDS = 15 * 60
_AUDIT_SNAPSHOT_MAX_AGE_SECONDS = 60 * 60
_SNAPSHOT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_PATH_RESULT_KEYS = frozenset({"output", "font", "layerFonts", "dart", "lock", "report"})


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number {value!r} is forbidden.")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _validate_json_scalars(value: Any) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("JSON text contains a lone Unicode surrogate.") from error
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite.")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_scalars(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_json_scalars(key)
            _validate_json_scalars(item)
        return
    raise ValueError(f"Unsupported JSON value type {type(value).__name__}.")


def _strict_json_loads(value: str | bytes, *, label: str) -> Any:
    try:
        result = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        _validate_json_scalars(result)
        return result
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ValueError(f"{label} is not strict interoperable JSON: {error}") from error


def _bounded_integer(
    value: int,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} through {maximum}.")
    return value


def _existing_absolute_path(
    value: str,
    label: str,
    *,
    kind: Literal["file", "directory", "file-or-directory"] = "file",
    preserve_spelling: bool = False,
) -> Path:
    if type(value) is not str or not value:
        raise ValueError(f"{label} must be a non-empty absolute path.")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute so agent working directories cannot alter it.")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"{label} cannot be resolved: {error}") from error
    if kind == "directory" and not resolved.is_dir():
        raise ValueError(f"{label} must identify an existing directory.")
    if kind == "file" and not resolved.is_file():
        raise ValueError(f"{label} must identify an existing regular file.")
    if kind == "file-or-directory" and not (resolved.is_file() or resolved.is_dir()):
        raise ValueError(f"{label} must identify an existing regular file or directory.")
    # Input spelling is security-relevant to the canonical compiler: it rejects
    # every symbolic-link, junction, and reparse-point component. Preserve the
    # caller's absolute spelling so resolving here cannot erase that evidence.
    return path if preserve_spelling else resolved


def _schema_text(filename: str) -> str:
    installed = files("glyphpact").joinpath("schema").joinpath(filename)
    try:
        return installed.read_text(encoding="utf-8")
    except FileNotFoundError:
        source_checkout = Path(__file__).resolve().parents[2] / "schema" / filename
        return source_checkout.read_text(encoding="utf-8")


def schema_resource(filename: str) -> str:
    """Return an installed GlyphPact JSON Schema."""

    if filename not in {
        "cli-result.schema.json",
        "icon-font-config.schema.json",
        "icon-font-report.schema.json",
    }:
        raise ValueError("Unknown GlyphPact schema resource.")
    return _schema_text(filename)


def _validated_cli_payload(stdout: bytes) -> dict[str, Any]:
    try:
        value = _strict_json_loads(stdout, label="GlyphPact CLI output")
    except ValueError as error:
        raise RuntimeError("GlyphPact returned invalid JSON to its MCP adapter.") from error
    if type(value) is not dict:
        raise RuntimeError("GlyphPact returned a non-object JSON result to its MCP adapter.")
    try:
        from jsonschema import Draft202012Validator
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "The MCP runtime is incomplete. Install GlyphPact with its mcp extra."
        ) from error
    schema = json.loads(_schema_text("cli-result.schema.json"))
    Draft202012Validator(schema).validate(value)
    return value


class _CliStdoutLimitExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class _CapturedStream:
    data: bytes
    truncated: bool


async def _read_bounded_stream(
    stream: asyncio.StreamReader,
    *,
    maximum_bytes: int,
    fail_on_excess: bool,
) -> _CapturedStream:
    chunks: list[bytes] = []
    captured = 0
    truncated = False
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        remaining = maximum_bytes - captured
        if remaining > 0:
            kept = chunk[:remaining]
            chunks.append(kept)
            captured += len(kept)
        if len(chunk) > max(remaining, 0):
            truncated = True
            if fail_on_excess:
                raise _CliStdoutLimitExceeded(f"GlyphPact CLI JSON exceeded {maximum_bytes} bytes.")
    return _CapturedStream(data=b"".join(chunks), truncated=truncated)


def _windows_system_executable(filename: str) -> Path:
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    if not system_root:
        raise RuntimeError(
            "Windows process-tree cleanup requires the SystemRoot or WINDIR environment variable."
        )
    executable = Path(system_root) / "System32" / filename
    if not executable.is_file():
        raise RuntimeError(f"Windows process-tree cleanup executable is missing: {executable}")
    return executable


async def _kill_parent_bounded(
    process: asyncio.subprocess.Process,
    *,
    context: str,
) -> None:
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError as error:
        raise RuntimeError(f"{context}; the compiler parent also resisted termination.") from error


async def _terminate_windows_process_tree(process: asyncio.subprocess.Process) -> None:
    try:
        taskkill = _windows_system_executable("taskkill.exe")
    except RuntimeError:
        await _kill_parent_bounded(
            process,
            context="Windows process-tree cleanup is unavailable",
        )
        raise

    try:
        killer = await asyncio.create_subprocess_exec(
            str(taskkill),
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        await _kill_parent_bounded(
            process,
            context="Windows taskkill could not be launched",
        )
        raise RuntimeError(
            "Windows taskkill could not be launched for compiler cleanup."
        ) from error
    try:
        _, stderr = await asyncio.wait_for(killer.communicate(), timeout=10)
    except TimeoutError as error:
        with suppress(ProcessLookupError):
            killer.kill()
        with suppress(ProcessLookupError, TimeoutError):
            await asyncio.wait_for(killer.wait(), timeout=5)
        await _kill_parent_bounded(
            process,
            context="Windows taskkill timed out",
        )
        raise RuntimeError(
            "Windows taskkill timed out while terminating the compiler tree."
        ) from error
    if killer.returncode != 0:
        rendered = stderr.decode("utf-8", errors="replace").strip()[:_MAX_STDERR_BYTES]
        try:
            # taskkill reports a nonzero status when a short-lived process
            # exits while its tree is being enumerated. Preserve the original
            # bounded MCP result when the asyncio process has already observed
            # that clean exit.
            await asyncio.wait_for(process.wait(), timeout=0.5)
            return
        except TimeoutError:
            await _kill_parent_bounded(
                process,
                context="Windows taskkill could not guarantee worker cleanup",
            )
        raise RuntimeError(
            "Windows taskkill could not guarantee compiler worker cleanup"
            + (f": {rendered}" if rendered else ".")
        )
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError as error:
        await _kill_parent_bounded(
            process,
            context="Windows process tree remained alive after taskkill",
        )
        raise RuntimeError(
            "Windows compiler parent remained alive after process-tree termination."
        ) from error


def _signal_process_group(process_id: int, signal_name: str) -> None:
    kill_group = getattr(os, "killpg", None)
    signal_value = getattr(signal, signal_name, None)
    if not callable(kill_group) or signal_value is None:
        raise RuntimeError("POSIX process-group signaling is unavailable.")
    kill_group(process_id, signal_value)


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        with suppress(ProcessLookupError):
            _signal_process_group(process.pid, "SIGTERM")
    else:
        await _terminate_windows_process_tree(process)
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
        return
    except TimeoutError:
        pass
    if os.name == "posix":
        with suppress(ProcessLookupError):
            _signal_process_group(process.pid, "SIGKILL")
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except ProcessLookupError:
        return
    except TimeoutError as error:
        raise RuntimeError("The compiler process group resisted SIGKILL.") from error


async def _terminate_and_settle(
    process: asyncio.subprocess.Process,
    tasks: tuple[asyncio.Task[Any], ...],
) -> None:
    try:
        await _terminate_process(process)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _adapter_error(
    code: str,
    message: str,
    *,
    exit_code: int | None,
    state: str = "error",
    hint: str | None = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {"code": code, "message": message}
    if hint is not None:
        diagnostic["hint"] = hint
    return {
        "ok": False,
        "state": state,
        "exitCode": exit_code,
        "result": {
            "status": "error",
            "errorCount": 1,
            "errors": [diagnostic],
        },
    }


def _response_from_process(
    *,
    returncode: int,
    stdout: bytes,
    stderr: _CapturedStream,
) -> dict[str, Any]:
    payload = _validated_cli_payload(stdout)
    payload_succeeded = payload.get("status") == "ok"
    process_succeeded = returncode == 0
    if payload_succeeded != process_succeeded:
        raise RuntimeError(
            "GlyphPact's process exit code and validated JSON status disagree; "
            "the MCP adapter refused the forged result."
        )

    state = "success"
    if returncode == 3 and any(
        error.get("code") == "OUTPUT_OUT_OF_DATE"
        for error in payload.get("errors", [])
        if isinstance(error, dict)
    ):
        state = "stale"
    elif returncode != 0:
        state = "error"
    response: dict[str, Any] = {
        "ok": process_succeeded,
        "state": state,
        "exitCode": returncode,
        "result": payload,
    }
    rendered_stderr = stderr.data.decode("utf-8", errors="replace").strip()
    if rendered_stderr:
        response["stderr"] = rendered_stderr
        response["stderrTruncated"] = stderr.truncated
    return response


def _trusted_python_executable() -> Path:
    executable = Path(sys.executable)
    if not executable.is_absolute() or not executable.is_file():
        raise RuntimeError(
            "GlyphPact MCP requires an absolute existing Python interpreter for child isolation."
        )
    return executable


async def _run_cli(arguments: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    timeout_seconds = _bounded_integer(
        timeout_seconds,
        "timeout_seconds",
        minimum=1,
        maximum=3_600,
    )
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")
    }
    with tempfile.TemporaryDirectory(prefix="glyphpact-mcp-cwd-") as safe_working_directory:
        process = await asyncio.create_subprocess_exec(
            str(_trusted_python_executable()),
            "-I",
            "-X",
            "utf8",
            "-m",
            "glyphpact",
            *arguments,
            "--json",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=safe_working_directory,
            env=environment,
            start_new_session=os.name == "posix",
            creationflags=(
                int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
            ),
        )
        assert process.stdout is not None
        assert process.stderr is not None
        tasks = (
            asyncio.create_task(
                _read_bounded_stream(
                    process.stdout,
                    maximum_bytes=_MAX_CLI_STDOUT_BYTES,
                    fail_on_excess=True,
                )
            ),
            asyncio.create_task(
                _read_bounded_stream(
                    process.stderr,
                    maximum_bytes=_MAX_STDERR_BYTES,
                    fail_on_excess=False,
                )
            ),
            asyncio.create_task(process.wait()),
        )
        collection = asyncio.gather(*tasks)
        try:
            stdout, stderr, returncode = await asyncio.wait_for(
                collection,
                timeout=timeout_seconds,
            )
        except TimeoutError:
            await _terminate_and_settle(process, tasks)
            return _adapter_error(
                "MCP_OPERATION_TIMEOUT",
                f"GlyphPact did not finish within {timeout_seconds} seconds.",
                exit_code=None,
                state="timeout",
                hint="Increase timeout_seconds only for a trusted, bounded icon pack.",
            )
        except _CliStdoutLimitExceeded:
            await _terminate_and_settle(process, tasks)
            return _adapter_error(
                "MCP_CLI_OUTPUT_TOO_LARGE",
                f"GlyphPact CLI JSON exceeded the {_MAX_CLI_STDOUT_BYTES}-byte MCP limit.",
                exit_code=process.returncode,
                hint="Split an unusually diagnostic-heavy pack into smaller audit batches.",
            )
        except asyncio.CancelledError:
            await _terminate_and_settle(process, tasks)
            raise
        except Exception:
            await _terminate_and_settle(process, tasks)
            raise

    assert isinstance(stdout, _CapturedStream)
    assert isinstance(stderr, _CapturedStream)
    assert isinstance(returncode, int)
    return _response_from_process(
        returncode=returncode,
        stdout=stdout.data,
        stderr=stderr,
    )


@dataclass
class _AuditSnapshot:
    identifier: str
    path: Path
    offsets: tuple[int, ...]
    base_response: dict[str, Any]
    finding_kind: str
    size: int
    created_at: float
    last_accessed_at: float


class _AuditSnapshotStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_snapshots: int = _MAX_AUDIT_SNAPSHOTS,
        max_snapshot_bytes: int = _MAX_AUDIT_SNAPSHOT_BYTES,
        max_total_bytes: int = _MAX_AUDIT_SNAPSHOT_TOTAL_BYTES,
        idle_ttl_seconds: int = _AUDIT_SNAPSHOT_IDLE_TTL_SECONDS,
        max_age_seconds: int = _AUDIT_SNAPSHOT_MAX_AGE_SECONDS,
    ) -> None:
        self._clock = clock
        self._max_snapshots = max_snapshots
        self._max_snapshot_bytes = max_snapshot_bytes
        self._max_total_bytes = max_total_bytes
        self._idle_ttl_seconds = idle_ttl_seconds
        self._max_age_seconds = max_age_seconds
        self._root: Path | None = None
        self._snapshots: dict[str, _AuditSnapshot] = {}

    def _ensure_root(self) -> Path:
        if self._root is None:
            self._root = Path(tempfile.mkdtemp(prefix="glyphpact-mcp-snapshots-"))
            os.chmod(self._root, 0o700)
        return self._root

    def _expired(self, snapshot: _AuditSnapshot, now: float) -> bool:
        return (
            now - snapshot.last_accessed_at >= self._idle_ttl_seconds
            or now - snapshot.created_at >= self._max_age_seconds
        )

    def _remove(self, identifier: str) -> bool:
        snapshot = self._snapshots.pop(identifier, None)
        if snapshot is None:
            return False
        with suppress(OSError):
            snapshot.path.unlink()
        return True

    def _purge_expired(self, now: float) -> None:
        for identifier, snapshot in tuple(self._snapshots.items()):
            if self._expired(snapshot, now):
                self._remove(identifier)

    def _total_size(self) -> int:
        return sum(snapshot.size for snapshot in self._snapshots.values())

    def _evict_oldest(self) -> None:
        if not self._snapshots:
            return
        oldest = min(
            self._snapshots.values(),
            key=lambda snapshot: (snapshot.last_accessed_at, snapshot.created_at),
        )
        self._remove(oldest.identifier)

    def create(
        self,
        *,
        findings: list[Any],
        finding_kind: str,
        base_response: dict[str, Any],
    ) -> _AuditSnapshot:
        now = self._clock()
        self._purge_expired(now)
        identifier = secrets.token_hex(16)
        path = self._ensure_root() / f"{identifier}.ndjson"
        offsets: list[int] = []
        size = 0
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                for finding in findings:
                    _validate_json_scalars(finding)
                    rendered = (
                        json.dumps(
                            finding,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                    if size + len(rendered) > self._max_snapshot_bytes:
                        raise ValueError(
                            "Audit findings exceed the stable snapshot byte limit; "
                            "split the diagnostic-heavy pack."
                        )
                    offsets.append(size)
                    stream.write(rendered)
                    size += len(rendered)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            with suppress(OSError):
                path.unlink()
            raise

        while (
            len(self._snapshots) >= self._max_snapshots
            or self._total_size() + size > self._max_total_bytes
        ):
            if not self._snapshots:
                with suppress(OSError):
                    path.unlink()
                raise ValueError("Audit findings exceed the total stable snapshot byte limit.")
            self._evict_oldest()

        snapshot = _AuditSnapshot(
            identifier=identifier,
            path=path,
            offsets=tuple(offsets),
            base_response=copy.deepcopy(base_response),
            finding_kind=finding_kind,
            size=size,
            created_at=now,
            last_accessed_at=now,
        )
        self._snapshots[identifier] = snapshot
        return snapshot

    def get(self, identifier: str) -> _AuditSnapshot:
        if not _SNAPSHOT_ID_PATTERN.fullmatch(identifier):
            raise ValueError("snapshot_id must be a 32-character lowercase hexadecimal token.")
        now = self._clock()
        self._purge_expired(now)
        snapshot = self._snapshots.get(identifier)
        if snapshot is None:
            raise ValueError("snapshot_id is unknown or expired; run a new audit.")
        snapshot.last_accessed_at = now
        return snapshot

    def page(self, identifier: str, offset: int, limit: int) -> dict[str, Any]:
        snapshot = self.get(identifier)
        end = min(offset + limit, len(snapshot.offsets))
        items: list[Any] = []
        with snapshot.path.open("rb") as stream:
            for index in range(offset, end):
                stream.seek(snapshot.offsets[index])
                line = stream.readline()
                items.append(_strict_json_loads(line, label="Audit snapshot finding"))
        return _page(
            items,
            offset=offset,
            limit=limit,
            total=len(snapshot.offsets),
            items_are_page=True,
        )

    def metadata(self, snapshot: _AuditSnapshot) -> dict[str, Any]:
        now = self._clock()
        remaining = min(
            self._idle_ttl_seconds - (now - snapshot.last_accessed_at),
            self._max_age_seconds - (now - snapshot.created_at),
        )
        return {
            "id": snapshot.identifier,
            "expiresInSeconds": max(0, int(remaining)),
            "idleTtlSeconds": self._idle_ttl_seconds,
            "maxAgeSeconds": self._max_age_seconds,
            "maxSnapshots": self._max_snapshots,
            "maxSnapshotBytes": self._max_snapshot_bytes,
            "maxTotalSnapshotBytes": self._max_total_bytes,
            "maxPageSize": _MAX_PAGE_SIZE,
            "maxPageBytes": _MAX_PAGE_BYTES,
            "release": "Call audit_icon_pack with snapshot_id and release_snapshot=true.",
        }

    def release(self, identifier: str) -> bool:
        if not _SNAPSHOT_ID_PATTERN.fullmatch(identifier):
            raise ValueError("snapshot_id must be a 32-character lowercase hexadecimal token.")
        self._purge_expired(self._clock())
        return self._remove(identifier)

    def clear(self) -> None:
        self._snapshots.clear()
        if self._root is not None:
            with suppress(OSError):
                shutil.rmtree(self._root)
            self._root = None


_AUDIT_SNAPSHOTS = _AuditSnapshotStore()
atexit.register(_AUDIT_SNAPSHOTS.clear)


def _audit_snapshot_response(
    snapshot: _AuditSnapshot,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    response = copy.deepcopy(snapshot.base_response)
    response["findings"] = {
        "kind": snapshot.finding_kind,
        **_AUDIT_SNAPSHOTS.page(snapshot.identifier, offset, limit),
    }
    response["snapshot"] = _AUDIT_SNAPSHOTS.metadata(snapshot)
    return response


async def audit_icon_pack(
    input_path: str | None = None,
    config_path: str | None = None,
    snapshot_id: str | None = None,
    release_snapshot: bool = False,
    lossy: str = "error",
    unrepresentable: str = "error",
    jobs: int = 0,
    timeout_seconds: int = 300,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Create, page, or explicitly release a stable bounded audit snapshot."""

    if type(release_snapshot) is not bool:
        raise ValueError("release_snapshot must be boolean.")
    paging_snapshot = snapshot_id is not None
    if paging_snapshot:
        if type(snapshot_id) is not str:
            raise ValueError("snapshot_id must be a string or null.")
        if input_path is not None or config_path is not None:
            raise ValueError("Do not provide input_path or config_path when paging a snapshot.")
    elif release_snapshot:
        raise ValueError("release_snapshot requires snapshot_id.")
    elif (input_path is None) == (config_path is None):
        raise ValueError("Provide exactly one of input_path or config_path.")
    if lossy not in {"error", "convert"}:
        raise ValueError("lossy must be 'error' or 'convert'.")
    if unrepresentable not in {"error", "skip"}:
        raise ValueError("unrepresentable must be 'error' or 'skip'.")
    jobs = _bounded_integer(jobs, "jobs", minimum=0, maximum=64)
    offset = _bounded_integer(offset, "offset", minimum=0, maximum=65_534)
    limit = _bounded_integer(limit, "limit", minimum=1, maximum=_MAX_PAGE_SIZE)

    if paging_snapshot:
        assert snapshot_id is not None
        if release_snapshot:
            if not _AUDIT_SNAPSHOTS.release(snapshot_id):
                raise ValueError("snapshot_id is unknown or expired; it was not released.")
            return {
                "ok": True,
                "state": "released",
                "snapshot": {"id": snapshot_id, "released": True},
            }
        snapshot = _AUDIT_SNAPSHOTS.get(snapshot_id)
        return _audit_snapshot_response(snapshot, offset=offset, limit=limit)

    source_arguments: list[str]
    if config_path is not None:
        config = _existing_absolute_path(config_path, "config_path")
        source_arguments = ["--config", str(config)]
    else:
        assert input_path is not None
        source = _existing_absolute_path(
            input_path,
            "input_path",
            kind="file-or-directory",
            preserve_spelling=True,
        )
        source_arguments = [str(source), "--name", "AuditIcons"]

    with tempfile.TemporaryDirectory(prefix="glyphpact-audit-") as temporary:
        output = Path(temporary).resolve() / "output"
        response = await _run_cli(
            [
                *source_arguments,
                "--output",
                str(output),
                "--lossy",
                lossy,
                "--unrepresentable",
                unrepresentable,
                "--jobs",
                str(jobs),
            ],
            timeout_seconds=timeout_seconds,
        )
        response["temporaryArtifactsRemoved"] = True
        result = response.get("result")
        if isinstance(result, dict):
            finding_key = "issues" if isinstance(result.get("issues"), list) else "errors"
            findings = result.get(finding_key, [])
            assert isinstance(findings, list)
            response["result"] = {
                key: value
                for key, value in result.items()
                if key not in _PATH_RESULT_KEYS and key != finding_key
            }
            if findings:
                snapshot = _AUDIT_SNAPSHOTS.create(
                    findings=findings,
                    finding_kind=finding_key,
                    base_response=response,
                )
                response = _audit_snapshot_response(snapshot, offset=offset, limit=limit)
            else:
                response["findings"] = {
                    "kind": finding_key,
                    **_page(findings, offset, limit),
                }
        return response


def _bound_cli_findings(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result")
    if not isinstance(result, dict):
        return response
    finding_key = "issues" if isinstance(result.get("issues"), list) else "errors"
    findings = result.get(finding_key, [])
    if not isinstance(findings, list):
        return response
    response["result"] = {key: value for key, value in result.items() if key != finding_key}
    page = _page(findings, offset=0, limit=100)
    report_path = result.get("report") if isinstance(result.get("report"), str) else None
    if report_path is None:
        page["omitted"] = max(0, page["total"] - page["returned"])
        page["nextOffset"] = None
    response["findings"] = {
        "kind": finding_key,
        **page,
        "pageableFromReport": report_path is not None,
        "fullReportPath": report_path,
    }
    return response


async def build_icon_font(
    config_path: str,
    adopt_output: bool = False,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Build and transactionally publish a configured Flutter icon font."""

    config = _existing_absolute_path(config_path, "config_path")
    if type(adopt_output) is not bool:
        raise ValueError("adopt_output must be boolean.")
    arguments = ["--config", str(config)]
    if adopt_output:
        arguments.append("--adopt-output")
    return _bound_cli_findings(await _run_cli(arguments, timeout_seconds=timeout_seconds))


async def check_icon_font(
    config_path: str,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Verify generated artifacts without rewriting them.

    The compiler may create its persistent sibling coordination lock.
    """

    config = _existing_absolute_path(config_path, "config_path")
    return _bound_cli_findings(
        await _run_cli(
            ["--config", str(config), "--check"],
            timeout_seconds=timeout_seconds,
        )
    )


def _load_report(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"report_path cannot be opened safely: {error}") from error
    try:
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("report_path must remain a regular file while it is read.")
            if before.st_size > _MAX_REPORT_BYTES:
                raise ValueError("report_path exceeds the 128 MiB MCP read limit.")
            raw = stream.read(_MAX_REPORT_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > _MAX_REPORT_BYTES:
            raise ValueError("report_path exceeds the 128 MiB MCP read limit.")
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(raw) != after.st_size
        ):
            raise ValueError("report_path changed while it was being read.")
    except OSError as error:
        raise ValueError(f"report_path cannot be inspected: {error}") from error

    try:
        value = _strict_json_loads(
            raw.decode("utf-8"),
            label="report_path",
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f"report_path is not readable GlyphPact JSON: {error}") from error
    if type(value) is not dict:
        raise ValueError("report_path must contain a JSON object.")
    try:
        from jsonschema import Draft202012Validator
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "The MCP runtime is incomplete. Install GlyphPact with its mcp extra."
        ) from error
    schema = json.loads(_schema_text("icon-font-report.schema.json"))
    Draft202012Validator(schema).validate(value)
    return value


def _oversize_item_summary(item: Any, serialized_bytes: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "code": "MCP_FINDING_DETAILS_OMITTED",
        "message": (
            f"One finding required {serialized_bytes} serialized bytes, so its details were "
            "omitted from the bounded MCP page."
        ),
        "serializedBytes": serialized_bytes,
    }
    if isinstance(item, dict):
        for key in ("code", "source", "classification", "action", "feature"):
            value = item.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                summary[f"original{key[0].upper()}{key[1:]}"] = value
    return summary


def _page(
    items: list[Any],
    offset: int,
    limit: int,
    *,
    total: int | None = None,
    items_are_page: bool = False,
) -> dict[str, Any]:
    total_items = len(items) if total is None else total
    candidates = items[:limit] if items_are_page else items[offset : offset + limit]
    page_items: list[Any] = []
    page_bytes = 2
    byte_limited = False
    for item in candidates:
        rendered_bytes = len(
            json.dumps(
                item,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        candidate = item
        if rendered_bytes + 2 > _MAX_PAGE_BYTES:
            candidate = _oversize_item_summary(item, rendered_bytes)
            rendered_bytes = len(json.dumps(candidate, separators=(",", ":")).encode("utf-8"))
            byte_limited = True
        separator_bytes = 1 if page_items else 0
        if page_items and page_bytes + separator_bytes + rendered_bytes > _MAX_PAGE_BYTES:
            byte_limited = True
            break
        page_items.append(candidate)
        page_bytes += separator_bytes + rendered_bytes

    next_offset = offset + len(page_items)
    if next_offset >= total_items:
        next_offset_value: int | None = None
    else:
        next_offset_value = next_offset
    return {
        "total": total_items,
        "offset": offset,
        "limit": limit,
        "returned": len(page_items),
        "nextOffset": next_offset_value,
        "byteLimited": byte_limited,
        "items": page_items,
    }


def read_icon_report(
    report_path: str,
    classification: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Validate and page through a GlyphPact report without dumping an entire large pack."""

    report = _existing_absolute_path(report_path, "report_path")
    if classification not in {None, "lossy", "unrepresentable"}:
        raise ValueError("classification must be 'lossy', 'unrepresentable', or null.")
    offset = _bounded_integer(offset, "offset", minimum=0, maximum=65_534)
    limit = _bounded_integer(limit, "limit", minimum=1, maximum=_MAX_PAGE_SIZE)
    payload = _load_report(report)
    issues = payload.get("issues", [])
    glyphs = payload.get("glyphs", [])
    skipped = payload.get("skippedIcons", [])
    if (
        not isinstance(issues, list)
        or not isinstance(glyphs, list)
        or not isinstance(skipped, list)
    ):
        raise RuntimeError("The validated report contains unexpected collection types.")
    if classification is not None:
        issues = [
            issue
            for issue in issues
            if isinstance(issue, dict) and issue.get("classification") == classification
        ]
    summary_keys = (
        "schemaVersion",
        "generator",
        "generatorVersion",
        "status",
        "quality",
        "policy",
        "discoveredIconCount",
        "glyphCount",
        "losslessGlyphCount",
        "approximatedGlyphCount",
        "skippedIconCount",
        "issueCount",
        "retiredCodepointCount",
        "codepointsRemaining",
        "rangeUtilization",
        "font",
        "layerFonts",
        "dart",
        "lockFile",
        "attributionFile",
    )
    return {
        "summary": {key: payload[key] for key in summary_keys if key in payload},
        "issues": _page(issues, offset, limit),
        "glyphs": _page(glyphs, offset, limit),
        "skippedIcons": _page(skipped, offset, limit),
    }
