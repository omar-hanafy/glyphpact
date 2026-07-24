from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from glyphpact import mcp_tools
from glyphpact.mcp_tools import (
    _AUDIT_SNAPSHOTS,
    _AuditSnapshotStore,
    _CapturedStream,
    _CliStdoutLimitExceeded,
    _read_bounded_stream,
    _response_from_process,
    audit_icon_pack,
    build_icon_font,
    check_icon_font,
    read_icon_report,
)


@pytest.fixture(autouse=True)
def _clear_audit_snapshots() -> None:
    _AUDIT_SNAPSHOTS.clear()
    yield
    _AUDIT_SNAPSHOTS.clear()


def _write_pack(tmp_path: Path) -> tuple[Path, Path]:
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "square.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M2 2h20v20H2z"/></svg>',
        encoding="utf-8",
    )
    config = tmp_path / "icon_font.json"
    config.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "fontFamily": "TestIcons",
                "className": "TestIcons",
            }
        ),
        encoding="utf-8",
    )
    return icons, config


def test_audit_is_strict_and_removes_temporary_artifacts(tmp_path: Path) -> None:
    icons, _ = _write_pack(tmp_path)
    result = asyncio.run(audit_icon_pack(input_path=str(icons), jobs=1))

    assert result["ok"] is True
    assert result["state"] == "success"
    assert result["temporaryArtifactsRemoved"] is True
    payload = result["result"]
    assert payload["quality"] == "lossless"
    assert payload["glyphCount"] == 1
    assert "output" not in payload
    assert "font" not in payload
    assert result["findings"] == {
        "kind": "issues",
        "total": 0,
        "offset": 0,
        "limit": 100,
        "returned": 0,
        "nextOffset": None,
        "byteLimited": False,
        "items": [],
    }


def test_audit_accepts_one_svg_file(tmp_path: Path) -> None:
    icons, _ = _write_pack(tmp_path)

    result = asyncio.run(audit_icon_pack(input_path=str(icons / "square.svg"), jobs=1))

    assert result["ok"] is True
    assert result["result"]["glyphCount"] == 1


def test_audit_pages_failures_without_flooding_the_result(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    for index in range(3):
        (icons / f"unsafe_{index}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<script>alert("no")</script><path d="M2 2h20v20H2z"/></svg>',
            encoding="utf-8",
        )

    result = asyncio.run(audit_icon_pack(input_path=str(icons), jobs=1, offset=1, limit=1))

    assert result["ok"] is False
    assert "errors" not in result["result"]
    assert result["result"]["errorCount"] == 3
    assert result["findings"]["kind"] == "errors"
    assert result["findings"]["total"] == 3
    assert result["findings"]["offset"] == 1
    assert len(result["findings"]["items"]) == 1


def test_build_check_and_paginated_report(tmp_path: Path) -> None:
    _, config = _write_pack(tmp_path)

    built = asyncio.run(build_icon_font(str(config)))
    assert built["ok"] is True
    checked = asyncio.run(check_icon_font(str(config)))
    assert checked["ok"] is True

    report_path = tmp_path / "generated" / "iconfont.report.json"
    report = read_icon_report(str(report_path), offset=0, limit=1)
    assert report["summary"]["quality"] == "lossless"
    assert report["glyphs"]["total"] == 1
    assert report["glyphs"]["items"][0]["source"] == "square.svg"


def test_check_maps_drift_to_stale(tmp_path: Path) -> None:
    _, config = _write_pack(tmp_path)
    assert asyncio.run(build_icon_font(str(config)))["ok"] is True
    dart_path = tmp_path / "generated" / "test_icons.dart"
    dart_path.write_text(
        dart_path.read_text(encoding="utf-8") + "// drift\n",
        encoding="utf-8",
    )

    checked = asyncio.run(check_icon_font(str(config)))

    assert checked["ok"] is False
    assert checked["state"] == "stale"
    assert checked["exitCode"] == 3
    assert "errors" not in checked["result"]
    assert checked["findings"]["items"][0]["code"] == "OUTPUT_OUT_OF_DATE"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "exactly one"),
        ({"input_path": "relative"}, "absolute"),
        ({"input_path": "/definitely/missing/glyphpact"}, "cannot be resolved"),
        ({"classification": "fatal"}, "classification"),
    ],
)
def test_mcp_inputs_fail_closed(
    tmp_path: Path,
    arguments: dict[str, str],
    message: str,
) -> None:
    if "classification" in arguments:
        _, config = _write_pack(tmp_path)
        assert asyncio.run(build_icon_font(str(config)))["ok"] is True
        report = tmp_path / "generated" / "iconfont.report.json"
        with pytest.raises(ValueError, match=message):
            read_icon_report(str(report), **arguments)
        return
    with pytest.raises(ValueError, match=message):
        asyncio.run(audit_icon_pack(**arguments))


def test_audit_preserves_top_level_symlink_for_canonical_rejection(tmp_path: Path) -> None:
    icons, _ = _write_pack(tmp_path)
    linked = tmp_path / "linked.svg"
    try:
        linked.symlink_to(icons / "square.svg")
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")

    result = asyncio.run(audit_icon_pack(input_path=str(linked), jobs=1))

    assert result["ok"] is False
    assert result["findings"]["items"][0]["code"] == "INPUT_SYMLINK_FORBIDDEN"


def test_child_cli_cannot_be_shadowed_by_working_directory_or_pythonpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    icons, _ = _write_pack(tmp_path)
    hostile = tmp_path / "hostile"
    package = hostile / "glyphpact"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    sentinel = hostile / "executed.txt"
    (package / "__main__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
        'print(\'{"status":"error","errorCount":1,"errors":['
        '{"code":"CWD_PACKAGE_EXECUTED","message":"shadow package ran"}]}\')\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(hostile)
    monkeypatch.setenv("PYTHONPATH", str(hostile))

    result = asyncio.run(audit_icon_pack(input_path=str(icons), jobs=1))

    assert result["ok"] is True
    assert result["result"]["glyphCount"] == 1
    assert not sentinel.exists()


@pytest.mark.parametrize(
    ("returncode", "payload"),
    [
        (
            0,
            {
                "status": "error",
                "errorCount": 1,
                "errors": [{"code": "FORGED_FAILURE", "message": "not success"}],
            },
        ),
        (
            2,
            {
                "status": "ok",
                "mode": "build",
                "glyphCount": 1,
                "fontSha256": "0" * 64,
                "output": "/tmp/output",
                "font": "/tmp/output/font.otf",
                "dart": "/tmp/output/icons.dart",
                "lock": "/tmp/output/lock.json",
                "report": "/tmp/output/report.json",
            },
        ),
    ],
)
def test_process_response_rejects_exit_status_disagreement(
    returncode: int,
    payload: dict[str, object],
) -> None:
    with pytest.raises(RuntimeError, match=r"exit code.*status disagree"):
        _response_from_process(
            returncode=returncode,
            stdout=json.dumps(payload).encode(),
            stderr=_CapturedStream(data=b"", truncated=False),
        )


def test_subprocess_stream_capture_is_bounded() -> None:
    async def exercise() -> None:
        stdout = asyncio.StreamReader()
        stdout.feed_data(b"x" * 17)
        stdout.feed_eof()
        with pytest.raises(_CliStdoutLimitExceeded):
            await _read_bounded_stream(stdout, maximum_bytes=16, fail_on_excess=True)

        stderr = asyncio.StreamReader()
        stderr.feed_data(b"y" * 17)
        stderr.feed_eof()
        captured = await _read_bounded_stream(stderr, maximum_bytes=16, fail_on_excess=False)
        assert captured == _CapturedStream(data=b"y" * 16, truncated=True)

    asyncio.run(exercise())


def test_cli_stdout_limit_returns_one_typed_bounded_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    icons, _ = _write_pack(tmp_path)
    monkeypatch.setattr(mcp_tools, "_MAX_CLI_STDOUT_BYTES", 64)

    result = asyncio.run(audit_icon_pack(input_path=str(icons), jobs=1))

    assert result["ok"] is False
    assert result["state"] == "error"
    assert result["temporaryArtifactsRemoved"] is True
    assert result["findings"]["total"] == 1
    assert result["findings"]["items"][0]["code"] == "MCP_CLI_OUTPUT_TOO_LARGE"


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree teardown contract")
def test_windows_timeout_cleanup_terminates_descendant_processes() -> None:
    import ctypes

    def process_exists(process_id: int) -> bool:
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True

    async def exercise() -> None:
        parent = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            (
                "import subprocess,sys,time;"
                "child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(60)']);"
                "print(child.pid,flush=True);time.sleep(60)"
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
        )
        assert parent.stdout is not None
        child_id = int((await asyncio.wait_for(parent.stdout.readline(), timeout=10)).decode())
        try:
            await mcp_tools._terminate_process(parent)
            assert parent.returncode is not None
            for _ in range(20):
                if not process_exists(child_id):
                    break
                await asyncio.sleep(0.05)
            assert not process_exists(child_id)
        finally:
            if parent.returncode is None:
                await mcp_tools._terminate_process(parent)

    asyncio.run(exercise())


def test_audit_pages_one_stable_snapshot_and_releases_it(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    for index in range(3):
        (icons / f"unsafe_{index}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<script>alert("no")</script><path d="M2 2h20v20H2z"/></svg>',
            encoding="utf-8",
        )

    first = asyncio.run(audit_icon_pack(input_path=str(icons), jobs=1, limit=1))
    snapshot_id = first["snapshot"]["id"]
    assert first["findings"]["items"][0]["source"] == "unsafe_0.svg"
    assert first["findings"]["nextOffset"] == 1

    for path in icons.glob("*.svg"):
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M2 2h20v20H2z"/></svg>',
            encoding="utf-8",
        )

    second = asyncio.run(audit_icon_pack(snapshot_id=snapshot_id, offset=1, limit=1))
    assert second["findings"]["items"][0]["source"] == "unsafe_1.svg"
    assert second["findings"]["total"] == 3
    released = asyncio.run(audit_icon_pack(snapshot_id=snapshot_id, release_snapshot=True))
    assert released == {
        "ok": True,
        "state": "released",
        "snapshot": {"id": snapshot_id, "released": True},
    }
    with pytest.raises(ValueError, match="unknown or expired"):
        asyncio.run(audit_icon_pack(snapshot_id=snapshot_id))


def test_audit_snapshot_store_enforces_idle_ttl_and_count_limit() -> None:
    now = [100.0]
    store = _AuditSnapshotStore(
        clock=lambda: now[0],
        max_snapshots=1,
        max_snapshot_bytes=1024,
        max_total_bytes=1024,
        idle_ttl_seconds=10,
        max_age_seconds=100,
    )
    try:
        first = store.create(
            findings=[{"code": "FIRST"}],
            finding_kind="errors",
            base_response={"ok": False},
        )
        second = store.create(
            findings=[{"code": "SECOND"}],
            finding_kind="errors",
            base_response={"ok": False},
        )
        with pytest.raises(ValueError, match="unknown or expired"):
            store.get(first.identifier)
        assert store.get(second.identifier).identifier == second.identifier

        now[0] += 11
        with pytest.raises(ValueError, match="unknown or expired"):
            store.get(second.identifier)
    finally:
        store.clear()


def test_build_failure_findings_are_count_and_byte_bounded(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    for index in range(110):
        (icons / f"unsafe_{index:03}.svg").write_bytes(b"\xff")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "fontFamily": "TestIcons",
                "jobs": 1,
            }
        ),
        encoding="utf-8",
    )

    result = asyncio.run(build_icon_font(str(config)))

    assert result["ok"] is False
    assert "errors" not in result["result"]
    assert result["result"]["errorCount"] == 110
    assert result["findings"]["total"] == 110
    assert result["findings"]["returned"] == 100
    assert result["findings"]["nextOffset"] is None
    assert result["findings"]["omitted"] == 10
    assert result["findings"]["pageableFromReport"] is False
    assert len(json.dumps(result).encode()) < mcp_tools._MAX_PAGE_BYTES + 32_768


@pytest.mark.parametrize(
    "forged_value",
    [float("nan"), float("inf"), float("-inf"), "\ud800"],
)
def test_report_reader_rejects_non_interoperable_json_scalars(
    tmp_path: Path,
    forged_value: object,
) -> None:
    _, config = _write_pack(tmp_path)
    assert asyncio.run(build_icon_font(str(config)))["ok"] is True
    report_path = tmp_path / "generated" / "iconfont.report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["glyphs"][0]["viewBox"][0] = forged_value
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"strict interoperable JSON|lone Unicode surrogate"):
        read_icon_report(str(report_path))
