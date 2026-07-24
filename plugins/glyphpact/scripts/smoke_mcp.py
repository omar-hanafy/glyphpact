#!/usr/bin/env python3
"""Connect to a packaged GlyphPact MCP server and verify its public surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from _bundle import BundleError, plugin_root, verify_plugin_bundle
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "audit_icon_pack",
    "build_icon_font",
    "check_icon_font",
    "read_icon_report",
}
EXPECTED_RESOURCES = {
    "glyphpact://schema/cli-result",
    "glyphpact://schema/config",
    "glyphpact://schema/report",
}
EXPECTED_SNAPSHOT_LIMITS = {
    "idleTtlSeconds": 15 * 60,
    "maxAgeSeconds": 60 * 60,
    "maxSnapshots": 8,
    "maxSnapshotBytes": 64 * 1024 * 1024,
    "maxTotalSnapshotBytes": 128 * 1024 * 1024,
    "maxPageSize": 500,
    "maxPageBytes": 1024 * 1024,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the bundled GlyphPact MCP server.")
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=plugin_root(),
        help="Plugin root to test, including a copied installed-cache fixture.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Maximum seconds for MCP startup and discovery.",
    )
    return parser.parse_args()


def _load_server(root: Path) -> StdioServerParameters:
    try:
        document = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        server = document["mcpServers"]["glyphpact"]
        command = server["command"]
        args = server["args"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise BundleError(f"Cannot read GlyphPact MCP configuration: {error}") from error
    if (
        not isinstance(command, str)
        or not isinstance(args, list)
        or not all(isinstance(value, str) for value in args)
    ):
        raise BundleError("GlyphPact MCP command and args must be strings.")
    executable = shutil.which(command)
    if executable is None:
        raise BundleError(f"MCP command is not available on PATH: {command}")

    root_text = str(root)
    expanded_args = [value.replace("${CLAUDE_PLUGIN_ROOT}", root_text) for value in args]
    if any("${" in value for value in expanded_args):
        raise BundleError("MCP configuration contains an unresolved variable.")
    environment = dict(os.environ)
    environment["CLAUDE_PLUGIN_ROOT"] = root_text
    return StdioServerParameters(
        command=executable,
        args=expanded_args,
        env=environment,
    )


async def _smoke(root: Path) -> dict[str, Any]:
    parameters = _load_server(root)
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialization = await session.initialize()
        tools = await session.list_tools()
        resources = await session.list_resources()
        with tempfile.TemporaryDirectory(
            prefix="glyphpact-mcp-smoke-",
            dir=Path(tempfile.gettempdir()).resolve(),
        ) as temporary:
            source = Path(temporary) / "single.svg"
            source.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                '<path d="M2 2h20v20H2z"/></svg>',
                encoding="utf-8",
            )
            audit_result = await session.call_tool(
                "audit_icon_pack",
                arguments={
                    "input_path": str(source),
                    "jobs": 1,
                    "offset": 0,
                    "limit": 1,
                    "timeout_seconds": 60,
                },
            )
            unsafe = Path(temporary) / "unsafe"
            unsafe.mkdir()
            for index in range(2):
                (unsafe / f"unsafe_{index}.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                    '<script>alert("no")</script><path d="M2 2h20v20H2z"/></svg>',
                    encoding="utf-8",
                )
            initial_failure_result = await session.call_tool(
                "audit_icon_pack",
                arguments={
                    "input_path": str(unsafe),
                    "jobs": 1,
                    "offset": 0,
                    "limit": 1,
                    "timeout_seconds": 60,
                },
            )
            if initial_failure_result.isError or not isinstance(
                initial_failure_result.structuredContent, dict
            ):
                raise BundleError("MCP failure audit did not create a structured snapshot.")
            initial_failure = initial_failure_result.structuredContent
            failure_snapshot = initial_failure.get("snapshot")
            initial_findings = initial_failure.get("findings")
            if not isinstance(failure_snapshot, dict) or not isinstance(initial_findings, dict):
                raise BundleError("MCP failure audit did not return snapshot paging metadata.")
            snapshot_id = failure_snapshot.get("id")
            next_offset = initial_findings.get("nextOffset")
            if not isinstance(snapshot_id, str) or next_offset != 1:
                raise BundleError(
                    "MCP failure audit returned invalid snapshot paging metadata: "
                    f"snapshot={failure_snapshot!r}, findings={initial_findings!r}."
                )

            shutil.rmtree(unsafe)
            paged_failure_result = await session.call_tool(
                "audit_icon_pack",
                arguments={
                    "snapshot_id": snapshot_id,
                    "offset": next_offset,
                    "limit": 1,
                },
            )
            release_result = await session.call_tool(
                "audit_icon_pack",
                arguments={
                    "snapshot_id": snapshot_id,
                    "release_snapshot": True,
                },
            )
            released_page_result = await session.call_tool(
                "audit_icon_pack",
                arguments={"snapshot_id": snapshot_id},
            )

    tool_names = {tool.name for tool in tools.tools}
    if tool_names != EXPECTED_TOOLS:
        raise BundleError(
            "MCP tools differ from the public contract: " + ", ".join(sorted(tool_names))
        )
    tools_by_name = {tool.name: tool for tool in tools.tools}
    check_annotations = tools_by_name["check_icon_font"].annotations
    if (
        check_annotations is None
        or check_annotations.readOnlyHint is not False
        or check_annotations.destructiveHint is not False
    ):
        raise BundleError(
            "check_icon_font must advertise readOnlyHint=false and destructiveHint=false."
        )
    resource_uris = {str(resource.uri) for resource in resources.resources}
    if resource_uris != EXPECTED_RESOURCES:
        raise BundleError(
            "MCP schema resources differ from the public contract: "
            + ", ".join(sorted(resource_uris))
        )
    if audit_result.isError or not isinstance(audit_result.structuredContent, dict):
        raise BundleError("MCP single-SVG audit did not return structured success.")
    if initialization.serverInfo.version != "1.0.0":
        raise BundleError(
            "MCP server version differs from the bundled GlyphPact release: "
            f"{initialization.serverInfo.version!r}."
        )
    audit = audit_result.structuredContent
    audit_payload = audit.get("result")
    findings = audit.get("findings")
    if (
        audit.get("ok") is not True
        or audit.get("temporaryArtifactsRemoved") is not True
        or not isinstance(audit_payload, dict)
        or audit_payload.get("glyphCount") != 1
        or not isinstance(findings, dict)
        or findings.get("total") != 0
    ):
        raise BundleError("MCP single-SVG audit contract did not pass.")
    if paged_failure_result.isError or not isinstance(paged_failure_result.structuredContent, dict):
        raise BundleError("MCP paged failure audit did not return structured evidence.")
    paged_failure = paged_failure_result.structuredContent
    failure_payload = paged_failure.get("result")
    failure_findings = paged_failure.get("findings")
    paged_snapshot = paged_failure.get("snapshot")
    failure_items = failure_findings.get("items") if isinstance(failure_findings, dict) else None
    if (
        paged_failure.get("ok") is not False
        or not isinstance(failure_payload, dict)
        or failure_payload.get("errorCount") != 2
        or "errors" in failure_payload
        or not isinstance(failure_findings, dict)
        or failure_findings.get("kind") != "errors"
        or failure_findings.get("total") != 2
        or failure_findings.get("offset") != 1
        or failure_findings.get("nextOffset") is not None
        or not isinstance(failure_items, list)
        or len(failure_items) != 1
        or not isinstance(paged_snapshot, dict)
        or paged_snapshot.get("id") != snapshot_id
    ):
        raise BundleError("MCP paged failure audit contract did not pass.")
    if any(
        failure_snapshot.get(field) != expected
        for field, expected in EXPECTED_SNAPSHOT_LIMITS.items()
    ):
        raise BundleError("MCP audit snapshot limits differ from the public contract.")
    if release_result.isError or not isinstance(release_result.structuredContent, dict):
        raise BundleError("MCP audit snapshot release did not return structured success.")
    released = release_result.structuredContent
    released_snapshot = released.get("snapshot")
    if (
        released.get("ok") is not True
        or released.get("state") != "released"
        or not isinstance(released_snapshot, dict)
        or released_snapshot.get("id") != snapshot_id
        or released_snapshot.get("released") is not True
    ):
        raise BundleError("MCP audit snapshot was not explicitly released.")
    if released_page_result.isError is not True:
        raise BundleError("Released MCP audit snapshot remained available.")
    return {
        "status": "ok",
        "serverName": initialization.serverInfo.name,
        "serverVersion": initialization.serverInfo.version,
        "tools": sorted(tool_names),
        "toolSafety": {
            "check_icon_font": {
                "readOnlyHint": False,
                "destructiveHint": False,
            }
        },
        "resources": sorted(resource_uris),
        "singleSvgAudit": {
            "glyphCount": audit_payload["glyphCount"],
            "quality": audit_payload["quality"],
            "findingCount": findings["total"],
            "temporaryArtifactsRemoved": True,
        },
        "pagedFailureAudit": {
            "errorCount": failure_payload["errorCount"],
            "returnedFindingCount": len(failure_items),
            "totalFindingCount": failure_findings["total"],
            "offset": failure_findings["offset"],
            "stableAfterSourceRemoval": True,
            "snapshotReleased": True,
            "unavailableAfterRelease": True,
            "snapshotLimits": EXPECTED_SNAPSHOT_LIMITS,
        },
    }


def main() -> int:
    args = parse_args()
    root = args.plugin_root.expanduser().resolve()
    verify_plugin_bundle(root)
    if args.timeout <= 0:
        raise BundleError("--timeout must be positive.")
    result = asyncio.run(asyncio.wait_for(_smoke(root), timeout=args.timeout))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BundleError, asyncio.TimeoutError) as error:
        raise SystemExit(f"MCP smoke error: {error}") from error
