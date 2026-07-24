#!/usr/bin/env python3
"""Verify the GlyphPact plugin runtime and release metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _bundle import (
    EXPECTED_MCP_REQUIREMENTS,
    EXPECTED_VERSION,
    EXPECTED_WHEEL_FILENAME,
    BundleError,
    plugin_root,
    verify_plugin_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the GlyphPact plugin bundle.")
    parser.add_argument(
        "--allow-missing-wheel",
        action="store_true",
        help="Validate development metadata before the fresh release wheel is synchronized.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BundleError(f"Cannot read JSON file {path}: {error}") from error
    if not isinstance(value, dict):
        raise BundleError(f"Expected a JSON object in {path}.")
    return value


def _verify_manifests(root: Path) -> None:
    codex = _load_json(root / ".codex-plugin" / "plugin.json")
    claude = _load_json(root / ".claude-plugin" / "plugin.json")
    for label, manifest in (("Codex", codex), ("Claude Code", claude)):
        if manifest.get("name") != "glyphpact":
            raise BundleError(f"{label} manifest name must be 'glyphpact'.")
        if manifest.get("version") != EXPECTED_VERSION:
            raise BundleError(f"{label} manifest version must be {EXPECTED_VERSION!r}.")
        if manifest.get("mcpServers") != "./.mcp.json":
            raise BundleError(f"{label} manifest must load ./.mcp.json.")

    mcp = _load_json(root / ".mcp.json")
    server = mcp.get("mcpServers", {}).get("glyphpact")
    if not isinstance(server, dict) or server.get("command") != "uv":
        raise BundleError("MCP config must launch the glyphpact server with uv.")
    args = server.get("args")
    expected_wheel_argument = "${CLAUDE_PLUGIN_ROOT}/dist/" + EXPECTED_WHEEL_FILENAME
    expected_requirements_argument = "${CLAUDE_PLUGIN_ROOT}/dist/mcp-requirements.txt"
    if not isinstance(args, list):
        raise BundleError("MCP config args must be an array.")
    for required in (
        "tool",
        "run",
        "--isolated",
        "--from",
        expected_wheel_argument,
        "--with-requirements",
        expected_requirements_argument,
        "glyphpact-mcp",
    ):
        if required not in args:
            raise BundleError(f"MCP config is missing required argument {required!r}.")


def _plugin_entry(marketplace: dict[str, Any], path: Path) -> dict[str, Any]:
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise BundleError(f"Marketplace plugins must be an array in {path}.")
    matches = [
        entry for entry in plugins if isinstance(entry, dict) and entry.get("name") == "glyphpact"
    ]
    if len(matches) != 1:
        raise BundleError(f"Marketplace {path} must contain exactly one glyphpact entry.")
    return matches[0]


def _verify_marketplaces(root: Path) -> bool:
    repository_root = root.parent.parent
    claude_path = repository_root / ".claude-plugin" / "marketplace.json"
    codex_path = repository_root / ".agents" / "plugins" / "marketplace.json"
    if not claude_path.exists() and not codex_path.exists():
        return False
    if not claude_path.is_file() or not codex_path.is_file():
        raise BundleError("Repository checkout contains only one marketplace catalog.")
    claude = _load_json(claude_path)
    codex = _load_json(codex_path)
    for label, path, marketplace in (
        ("Claude Code", claude_path, claude),
        ("Codex", codex_path, codex),
    ):
        if marketplace.get("name") != "glyphpact":
            raise BundleError(f"{label} marketplace ID must be 'glyphpact' in {path}.")

    claude_entry = _plugin_entry(claude, claude_path)
    if claude_entry.get("source") != "./plugins/glyphpact":
        raise BundleError("Claude Code marketplace source must be ./plugins/glyphpact.")

    codex_entry = _plugin_entry(codex, codex_path)
    if codex_entry.get("source") != {
        "source": "local",
        "path": "./plugins/glyphpact",
    }:
        raise BundleError("Codex marketplace source must be local ./plugins/glyphpact.")
    if codex_entry.get("policy") != {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }:
        raise BundleError("Codex marketplace policy is incomplete or unexpected.")
    if codex_entry.get("category") != "Developer Tools":
        raise BundleError("Codex marketplace category must be 'Developer Tools'.")
    return True


def main() -> int:
    args = parse_args()
    root = plugin_root()
    _verify_manifests(root)
    marketplaces_verified = _verify_marketplaces(root)
    identity = verify_plugin_bundle(root, allow_missing_wheel=args.allow_missing_wheel)
    result: dict[str, Any] = {
        "status": "ok",
        "pluginVersion": EXPECTED_VERSION,
        "runtimeRequirements": list(EXPECTED_MCP_REQUIREMENTS),
        "wheel": "missing-development-artifact" if identity is None else EXPECTED_WHEEL_FILENAME,
        "marketplaces": "verified" if marketplaces_verified else "not-present-in-plugin-cache",
    }
    if identity is not None:
        result.update(
            {
                "wheelBytes": identity.size,
                "wheelSha256": identity.sha256,
            }
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BundleError as error:
        raise SystemExit(f"bundle error: {error}") from error
