#!/usr/bin/env python3
"""Run the exact GlyphPact CLI wheel bundled by this plugin."""

from __future__ import annotations

import shutil
import subprocess
import sys

from _bundle import EXPECTED_WHEEL_FILENAME, BundleError, plugin_root, verify_plugin_bundle


def main() -> int:
    root = plugin_root()
    verify_plugin_bundle(root)
    uv = shutil.which("uv")
    if uv is None:
        raise BundleError("uv is required on PATH to run the bundled GlyphPact wheel.")
    command = [
        uv,
        "tool",
        "run",
        "--quiet",
        "--no-progress",
        "--color",
        "never",
        "--no-config",
        "--isolated",
        "--from",
        str(root / "dist" / EXPECTED_WHEEL_FILENAME),
        "glyphpact",
        *sys.argv[1:],
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BundleError as error:
        raise SystemExit(f"bundle error: {error}") from error
