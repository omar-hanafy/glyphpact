#!/usr/bin/env python3
"""Benchmark GlyphPact against a local SVG pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


def _artifact_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _source_stats(root: Path) -> tuple[int, int]:
    sources = (
        [root]
        if root.is_file()
        else sorted(path for path in root.rglob("*") if path.suffix.casefold() == ".svg")
    )
    files = [path for path in sources if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark fresh GlyphPact builds and compare artifact digests."
    )
    parser.add_argument("input", type=Path, help="SVG file or directory")
    parser.add_argument(
        "--command",
        default="glyphpact",
        help='Command prefix, for example "uv run glyphpact"',
    )
    parser.add_argument("--jobs", nargs="+", type=int, default=[1, 8])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--name", default="BenchmarkIcons")
    args = parser.parse_args()

    source = args.input.resolve()
    if not source.exists():
        parser.error(f"input does not exist: {source}")
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if any(jobs < 1 or jobs > 61 for jobs in args.jobs):
        parser.error("--jobs values must be between 1 and 61")

    command = shlex.split(args.command)
    if not command:
        parser.error("--command must not be empty")

    svg_count, input_bytes = _source_stats(source)
    results: dict[str, object] = {
        "input": str(source),
        "svgCount": svg_count,
        "inputBytes": input_bytes,
        "runs": args.runs,
        "measurements": [],
    }
    all_digests: set[str] = set()
    measurements: list[dict[str, object]] = []

    for jobs in args.jobs:
        durations: list[float] = []
        digests: list[str] = []
        for _ in range(args.runs):
            with tempfile.TemporaryDirectory(prefix="glyphpact-benchmark-") as temporary:
                output = Path(temporary).resolve(strict=True) / "output"
                invocation = [
                    *command,
                    str(source),
                    "--output",
                    str(output),
                    "--name",
                    args.name,
                    "--jobs",
                    str(jobs),
                    "--json",
                ]
                started = time.perf_counter()
                completed = subprocess.run(
                    invocation,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                duration = time.perf_counter() - started
                if completed.returncode != 0:
                    raise SystemExit(
                        f"GlyphPact exited with {completed.returncode}:\n"
                        f"{completed.stderr or completed.stdout}"
                    )
                durations.append(duration)
                artifact_digest = _artifact_digest(output)
                digests.append(artifact_digest)
                all_digests.add(artifact_digest)

        measurements.append(
            {
                "jobs": jobs,
                "seconds": [round(duration, 6) for duration in durations],
                "medianSeconds": round(statistics.median(durations), 6),
                "artifactDigests": digests,
            }
        )

    results["measurements"] = measurements
    results["byteIdentical"] = len(all_digests) == 1
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
