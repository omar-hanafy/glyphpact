"""GlyphPact's local stdio MCP server."""

from __future__ import annotations

from typing import Any

from . import __version__
from .mcp_tools import (
    audit_icon_pack,
    build_icon_font,
    check_icon_font,
    read_icon_report,
    schema_resource,
)


def create_server() -> Any:
    """Create the FastMCP server while keeping MCP optional for CLI-only users."""

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "GlyphPact's MCP server requires the optional dependency: install 'glyphpact[mcp]'."
        ) from error

    server = FastMCP(
        "GlyphPact",
        instructions=(
            "Audit before building. Keep lossy and unrepresentable handling strict unless the "
            "user explicitly accepts a reported conversion policy. Preserve existing lock files "
            "and use check_icon_font after every published build. Page an audit with its returned "
            "snapshot_id, then release that snapshot explicitly."
        ),
    )
    # FastMCP 1.28 does not expose its low-level server version in the public
    # constructor. Set the implementation version explicitly so initialize
    # reports GlyphPact's release rather than the MCP SDK's release.
    server._mcp_server.version = __version__
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    server.tool(title="Audit an SVG icon pack", annotations=read_only)(audit_icon_pack)
    server.tool(
        title="Build a Flutter icon font",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )(build_icon_font)
    server.tool(
        title="Check generated icon artifacts",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )(check_icon_font)
    server.tool(title="Read a generated icon report", annotations=read_only)(read_icon_report)

    @server.resource(
        "glyphpact://schema/config",
        name="GlyphPact config schema",
        mime_type="application/schema+json",
    )
    def config_schema() -> str:
        return schema_resource("icon-font-config.schema.json")

    @server.resource(
        "glyphpact://schema/report",
        name="GlyphPact report schema",
        mime_type="application/schema+json",
    )
    def report_schema() -> str:
        return schema_resource("icon-font-report.schema.json")

    @server.resource(
        "glyphpact://schema/cli-result",
        name="GlyphPact CLI result schema",
        mime_type="application/schema+json",
    )
    def cli_result_schema() -> str:
        return schema_resource("cli-result.schema.json")

    return server


def main() -> None:
    """Run the local stdio MCP transport."""

    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
