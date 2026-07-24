#!/usr/bin/env python3
"""Run repository-local release validation for the GlyphPact agent plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _bundle import BundleError, plugin_root, verify_plugin_bundle
from verify_bundle import _load_json, _verify_manifests, _verify_marketplaces


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BundleError(f"{label} must be a non-empty string.")
    return value


def _validate_codex_interface(root: Path) -> None:
    manifest = _load_json(root / ".codex-plugin" / "plugin.json")
    _require_string(manifest.get("description"), "Codex description")
    author = manifest.get("author")
    if not isinstance(author, dict):
        raise BundleError("Codex author must be an object.")
    _require_string(author.get("name"), "Codex author name")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise BundleError("Codex interface must be an object.")
    for key in (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "defaultPrompt",
    ):
        _require_string(interface.get(key), f"Codex interface.{key}")
    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(value, str) and value for value in capabilities
    ):
        raise BundleError("Codex interface.capabilities must be a non-empty string array.")
    if "$sync-flutter-svg-icons" not in interface["defaultPrompt"]:
        raise BundleError("Codex defaultPrompt must invoke $sync-flutter-svg-icons.")


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BundleError(f"Cannot read skill file {path}: {error}") from error
    lines = text.splitlines()
    if len(lines) < 4 or lines[0] != "---":
        raise BundleError("Skill must begin with YAML frontmatter.")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise BundleError("Skill frontmatter is not closed.") from error
    values: dict[str, str] = {}
    for line in lines[1:closing]:
        if ":" not in line:
            raise BundleError(f"Invalid skill frontmatter line: {line!r}.")
        key, value = line.split(":", 1)
        key = key.strip()
        if key in values:
            raise BundleError(f"Duplicate skill frontmatter key {key!r}.")
        values[key] = value.strip()
    return values


def _validate_skill(root: Path) -> None:
    skill = root / "skills" / "sync-flutter-svg-icons"
    frontmatter = _frontmatter(skill / "SKILL.md")
    if set(frontmatter) != {"name", "description"}:
        raise BundleError("Skill frontmatter must contain only name and description.")
    if frontmatter["name"] != skill.name:
        raise BundleError("Skill name must match its directory.")
    _require_string(frontmatter["description"], "Skill description")

    openai_path = skill / "agents" / "openai.yaml"
    try:
        openai_text = openai_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BundleError(f"Cannot read skill metadata {openai_path}: {error}") from error
    for expected in (
        'display_name: "Sync Flutter SVG Icons"',
        'short_description: "Compile, wire, and verify Flutter SVG icon fonts"',
        "$sync-flutter-svg-icons",
    ):
        if expected not in openai_text:
            raise BundleError(f"Skill metadata is missing {expected!r}.")


def _validate_text_hygiene(root: Path) -> None:
    forbidden = {
        "TO" + "DO": "unfinished placeholder",
        "svg-to-" + "flutter-icon": "retired product name",
        "svg_to_" + "flutter_icon": "retired product name",
        chr(0x2014): "forbidden punctuation",
    }
    suffixes = {".json", ".md", ".py", ".txt", ".yaml"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError as error:
            raise BundleError(f"Text file is not UTF-8: {path}") from error
        for token, label in forbidden.items():
            if token in text:
                raise BundleError(f"{path} contains {label}: {token!r}.")


def main() -> int:
    root = plugin_root()
    _verify_manifests(root)
    if not _verify_marketplaces(root):
        raise BundleError("Repository marketplace catalogs are missing.")
    _validate_codex_interface(root)
    _validate_skill(root)
    _validate_text_hygiene(root)
    identity = verify_plugin_bundle(root)
    if identity is None:
        raise BundleError("Plugin wheel is missing.")
    print(
        json.dumps(
            {
                "status": "ok",
                "plugin": "glyphpact",
                "version": identity.version,
                "wheelSha256": identity.sha256,
                "marketplaces": "verified",
                "skill": "sync-flutter-svg-icons",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BundleError as error:
        raise SystemExit(f"plugin validation error: {error}") from error
