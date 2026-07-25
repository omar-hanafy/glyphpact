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

_BRAND_ASSETS = ("glyphpact-icon.svg", "glyphpact-mark.svg")
_BRAND_DISPLAY_NAME = "GlyphPact"
_BRAND_HOMEPAGE = "https://omar-hanafy.github.io/glyphpact/"
_CODEX_BRAND_INTERFACE = {
    "displayName": _BRAND_DISPLAY_NAME,
    "brandColor": "#22D3EE",
    "logo": "./assets/glyphpact-icon.svg",
    "composerIcon": "./assets/glyphpact-mark.svg",
}


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
        if manifest.get("homepage") != _BRAND_HOMEPAGE:
            raise BundleError(f"{label} manifest homepage must be {_BRAND_HOMEPAGE!r}.")

    if claude.get("displayName") != _BRAND_DISPLAY_NAME:
        raise BundleError(f"Claude Code manifest displayName must be {_BRAND_DISPLAY_NAME!r}.")

    interface = codex.get("interface")
    if not isinstance(interface, dict):
        raise BundleError("Codex manifest interface must be an object.")
    for key, expected in _CODEX_BRAND_INTERFACE.items():
        if interface.get(key) != expected:
            raise BundleError(f"Codex interface.{key} must be {expected!r}.")

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


def _verify_brand_assets(root: Path) -> bool:
    assets = root / "assets"
    for filename in _BRAND_ASSETS:
        asset = assets / filename
        if not asset.is_file() or asset.is_symlink():
            raise BundleError(f"Plugin brand asset must be a regular file: {asset}.")
        try:
            content = asset.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise BundleError(f"Cannot read plugin brand asset {asset}: {error}") from error
        if "<svg" not in content or "viewBox=" not in content:
            raise BundleError(f"Plugin brand asset is not a self-contained SVG: {asset}.")

    repository_brand = root.parent.parent / "brand"
    if not repository_brand.exists():
        return False
    if not repository_brand.is_dir():
        raise BundleError(f"Repository brand path is not a directory: {repository_brand}.")
    for filename in _BRAND_ASSETS:
        canonical = repository_brand / filename
        plugin_copy = assets / filename
        try:
            canonical_bytes = canonical.read_bytes()
            plugin_bytes = plugin_copy.read_bytes()
        except OSError as error:
            raise BundleError(
                f"Cannot compare canonical plugin brand asset {filename}: {error}"
            ) from error
        if plugin_bytes != canonical_bytes:
            raise BundleError(
                f"Plugin brand asset {plugin_copy} does not match canonical {canonical}."
            )
    return True


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
    if claude_entry.get("displayName") != _BRAND_DISPLAY_NAME:
        raise BundleError(f"Claude Code marketplace displayName must be {_BRAND_DISPLAY_NAME!r}.")

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
    canonical_brand_verified = _verify_brand_assets(root)
    marketplaces_verified = _verify_marketplaces(root)
    identity = verify_plugin_bundle(root, allow_missing_wheel=args.allow_missing_wheel)
    result: dict[str, Any] = {
        "status": "ok",
        "pluginVersion": EXPECTED_VERSION,
        "runtimeRequirements": list(EXPECTED_MCP_REQUIREMENTS),
        "wheel": "missing-development-artifact" if identity is None else EXPECTED_WHEEL_FILENAME,
        "marketplaces": "verified" if marketplaces_verified else "not-present-in-plugin-cache",
        "brandAssets": "canonical-match" if canonical_brand_verified else "self-contained",
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
