#!/usr/bin/env python3
"""Validate and atomically synchronize a GlyphPact release wheel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bundle import (
    BundleError,
    plugin_root,
    sync_wheel,
    verify_source_matches_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize the exact GlyphPact 1.0.0 wheel into this plugin."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the built wheel matches the bundle without changing files.",
    )
    parser.add_argument("wheel", type=Path, help="Freshly built glyphpact 1.0.0 wheel")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    identity = (
        verify_source_matches_bundle(args.wheel, plugin_root())
        if args.check
        else sync_wheel(args.wheel, plugin_root())
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "mode": "check" if args.check else "sync",
                "name": identity.name,
                "version": identity.version,
                "bytes": identity.size,
                "sha256": identity.sha256,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BundleError as error:
        raise SystemExit(f"bundle error: {error}") from error
