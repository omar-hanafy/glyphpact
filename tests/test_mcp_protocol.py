from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_server_initializes_and_lists_the_public_contract() -> None:
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "glyphpact.mcp_server"],
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "GlyphPact"
            assert initialized.serverInfo.version == "1.0.0"
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "audit_icon_pack",
                "build_icon_font",
                "check_icon_font",
                "read_icon_report",
            }
            by_name = {tool.name: tool for tool in tools.tools}
            assert by_name["audit_icon_pack"].annotations is not None
            assert by_name["audit_icon_pack"].annotations.readOnlyHint is True
            assert by_name["build_icon_font"].annotations is not None
            assert by_name["build_icon_font"].annotations.destructiveHint is True
            assert by_name["check_icon_font"].annotations is not None
            assert by_name["check_icon_font"].annotations.readOnlyHint is False
            assert by_name["check_icon_font"].annotations.destructiveHint is False
            resources = await session.list_resources()
            assert {str(resource.uri) for resource in resources.resources} == {
                "glyphpact://schema/cli-result",
                "glyphpact://schema/config",
                "glyphpact://schema/report",
            }

    asyncio.run(exercise())


def test_stdio_audit_snapshot_pages_and_releases_without_recompiling(tmp_path: Path) -> None:
    icons = tmp_path / "icons"
    icons.mkdir()
    for index in range(2):
        (icons / f"unsafe_{index}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<script>alert("no")</script><path d="M2 2h20v20H2z"/></svg>',
            encoding="utf-8",
        )

    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "glyphpact.mcp_server"],
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            first = await session.call_tool(
                "audit_icon_pack",
                arguments={"input_path": str(icons), "jobs": 1, "limit": 1},
            )
            assert first.isError is False
            assert isinstance(first.structuredContent, dict)
            snapshot = first.structuredContent["snapshot"]
            assert isinstance(snapshot, dict)
            snapshot_id = snapshot["id"]

            second = await session.call_tool(
                "audit_icon_pack",
                arguments={"snapshot_id": snapshot_id, "offset": 1, "limit": 1},
            )
            assert second.isError is False
            assert isinstance(second.structuredContent, dict)
            assert second.structuredContent["findings"]["items"][0]["source"] == "unsafe_1.svg"

            released = await session.call_tool(
                "audit_icon_pack",
                arguments={"snapshot_id": snapshot_id, "release_snapshot": True},
            )
            assert released.isError is False
            assert isinstance(released.structuredContent, dict)
            assert released.structuredContent["state"] == "released"

            expired = await session.call_tool(
                "audit_icon_pack",
                arguments={"snapshot_id": snapshot_id},
            )
            assert expired.isError is True

    asyncio.run(exercise())
