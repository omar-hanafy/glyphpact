from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

from . import __version__
from .builder import BuildResult, build
from .config import (
    BuildConfig,
    ConversionPolicy,
    LossyPolicy,
    UnrepresentablePolicy,
    load_config,
    parse_codepoint,
)
from .errors import BatchError, Diagnostic, IconFontError
from .identity import CLI_NAME, DEBUG_ENVIRONMENT_VARIABLE


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise IconFontError("CLI_ARGUMENT_INVALID", message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog=CLI_NAME,
        description=(
            "Compile SVG files recursively into a deterministic OpenType icon font and "
            "a const Flutter IconData API."
        ),
    )
    parser.add_argument("input", nargs="?", help="SVG file or directory (recursive)")
    parser.add_argument("-c", "--config", type=Path, help="JSON config file")
    parser.add_argument("-o", "--output", type=Path, help="Dedicated generated output directory")
    parser.add_argument("-n", "--name", "--font-family", dest="font_family")
    parser.add_argument("--class-name", help="Generated Dart provider class")
    parser.add_argument("--font-package", help="Dart package containing the font, if any")
    parser.add_argument("-s", "--start-code", "--start-codepoint", dest="start_codepoint")
    parser.add_argument("-u", "--units-per-em", type=int)
    parser.add_argument("--precision", type=int)
    parser.add_argument("-j", "--jobs", type=int, help="Worker processes (default: up to 8)")
    parser.add_argument(
        "--padding",
        type=float,
        help="Fractional padding on every side of the em square (0 <= value < 0.5)",
    )
    parser.add_argument(
        "--clip-to-viewbox",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Clip painted geometry to the SVG viewBox (default: true)",
    )
    parser.add_argument(
        "--lossy",
        choices=tuple(policy.value for policy in LossyPolicy),
        help="Lossy SVG handling: error (default) or explicit convert",
    )
    parser.add_argument(
        "--unrepresentable",
        choices=tuple(policy.value for policy in UnrepresentablePolicy),
        help="Unrepresentable SVG handling: error (default) or explicit skip",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify generated artifacts without changing the owned output tree",
    )
    parser.add_argument(
        "--adopt-output",
        action="store_true",
        help="Explicitly replace a non-empty output directory that lacks an ownership marker",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _resolve_config(args: argparse.Namespace) -> BuildConfig:
    if args.config is not None:
        config = load_config(args.config)
    else:
        if args.input is None:
            raise IconFontError(
                "INPUT_REQUIRED",
                "Provide an SVG file/directory or --config.",
            )
        config = BuildConfig(
            input_path=Path(args.input),
            output_dir=args.output or Path("generated/icon_font"),
            font_family=args.font_family if args.font_family is not None else "AppIcons",
            class_name=args.class_name,
            font_package=args.font_package,
            start_codepoint=(
                parse_codepoint(args.start_codepoint)
                if args.start_codepoint is not None
                else 0xE000
            ),
            units_per_em=args.units_per_em if args.units_per_em is not None else 1000,
            precision=args.precision if args.precision is not None else 3,
            jobs=args.jobs if args.jobs is not None else 0,
            padding=args.padding if args.padding is not None else 0.0,
            clip_to_viewbox=(args.clip_to_viewbox if args.clip_to_viewbox is not None else True),
            policy=ConversionPolicy(
                lossy=LossyPolicy(args.lossy or LossyPolicy.ERROR.value),
                unrepresentable=UnrepresentablePolicy(
                    args.unrepresentable or UnrepresentablePolicy.ERROR.value
                ),
            ),
        )
        return config.validated()

    return replace(
        config,
        input_path=Path(args.input) if args.input is not None else config.input_path,
        output_dir=args.output if args.output is not None else config.output_dir,
        font_family=args.font_family if args.font_family is not None else config.font_family,
        class_name=args.class_name if args.class_name is not None else config.class_name,
        font_package=(args.font_package if args.font_package is not None else config.font_package),
        start_codepoint=(
            parse_codepoint(args.start_codepoint)
            if args.start_codepoint is not None
            else config.start_codepoint
        ),
        units_per_em=(args.units_per_em if args.units_per_em is not None else config.units_per_em),
        precision=args.precision if args.precision is not None else config.precision,
        jobs=args.jobs if args.jobs is not None else config.jobs,
        padding=args.padding if args.padding is not None else config.padding,
        clip_to_viewbox=(
            args.clip_to_viewbox if args.clip_to_viewbox is not None else config.clip_to_viewbox
        ),
        policy=ConversionPolicy(
            lossy=LossyPolicy(args.lossy) if args.lossy is not None else config.policy.lossy,
            unrepresentable=(
                UnrepresentablePolicy(args.unrepresentable)
                if args.unrepresentable is not None
                else config.policy.unrepresentable
            ),
        ),
    ).validated()


def _result_dict(result: BuildResult) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "status": "ok",
        "mode": "check" if result.checked else "build",
        "quality": result.quality,
        "policy": {
            "lossy": result.policy.lossy.value,
            "unrepresentable": result.policy.unrepresentable.value,
        },
        "discoveredIconCount": result.discovered_icon_count,
        "glyphCount": result.glyph_count,
        "losslessGlyphCount": result.lossless_glyph_count,
        "approximatedGlyphCount": result.approximated_glyph_count,
        "skippedIconCount": result.skipped_icon_count,
        "issueCount": len(result.issues),
        "issues": [issue.to_dict() for issue in result.issues],
        "fontSha256": result.font_sha256,
        "output": str(result.output_dir),
        "font": str(result.font_path),
        "layerFonts": [str(path) for path in result.layer_font_paths],
        "dart": str(result.dart_path),
        "lock": str(result.lock_path),
        "report": str(result.report_path),
    }


def _render_success(result: BuildResult) -> str:
    verb = "Verified" if result.checked else "Built"
    return "\n".join(
        [
            (
                f"{verb} {result.glyph_count} of {result.discovered_icon_count} discovered "
                f"icon(s): {result.lossless_glyph_count} lossless, "
                f"{result.approximated_glyph_count} approximated, "
                f"{result.skipped_icon_count} skipped."
            ),
            (
                f"Policy: lossy={result.policy.lossy.value}, "
                f"unrepresentable={result.policy.unrepresentable.value}"
            ),
            *(issue.render() for issue in result.issues),
            f"Font:   {result.font_path}",
            *(f"Layer:  {path}" for path in result.layer_font_paths),
            f"Dart:   {result.dart_path}",
            f"Lock:   {result.lock_path}",
            f"Report: {result.report_path}",
            f"SHA256: {result.font_sha256}",
        ]
    )


def _emit_errors(diagnostics: Sequence[Diagnostic], *, json_output: bool) -> bool:
    if json_output:
        try:
            rendered = json.dumps(
                {
                    "status": "error",
                    "errorCount": len(diagnostics),
                    "errors": [diagnostic.to_dict() for diagnostic in diagnostics],
                },
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
        except Exception:
            rendered = json.dumps(
                {
                    "status": "error",
                    "errorCount": 1,
                    "errors": [
                        {
                            "code": "INTERNAL_ERROR",
                            "message": "An error diagnostic could not be serialized safely.",
                            "hint": "Re-run with --verbose and report this failure.",
                        }
                    ],
                },
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            print(rendered)
            return False
        print(rendered)
        return True
    for diagnostic in diagnostics:
        print(diagnostic.render(), file=sys.stderr)
    return True


def _contains_internal_error(diagnostics: Sequence[Diagnostic]) -> bool:
    return any(diagnostic.code.startswith("INTERNAL_") for diagnostic in diagnostics)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    json_output = "--json" in raw_args
    verbose = "--verbose" in raw_args or "-v" in raw_args
    try:
        args = parser.parse_args(raw_args)
        json_output = args.json
        verbose = args.verbose
        if args.quiet and args.json:
            parser.error("--quiet and --json cannot be combined")
        config = _resolve_config(args)
        result = build(config, check=args.check, adopt_output=args.adopt_output)
        if args.json:
            print(json.dumps(_result_dict(result), indent=2, allow_nan=False))
        elif not args.quiet:
            print(_render_success(result))
        return 0
    except BatchError as error:
        emitted = _emit_errors(error.diagnostics, json_output=json_output)
        return 1 if not emitted or _contains_internal_error(error.diagnostics) else 2
    except IconFontError as error:
        emitted = _emit_errors((error.diagnostic,), json_output=json_output)
        if not emitted or _contains_internal_error((error.diagnostic,)):
            return 1
        return 3 if error.diagnostic.code == "OUTPUT_OUT_OF_DATE" else 2
    except Exception as error:
        diagnostic = Diagnostic(
            code="INTERNAL_ERROR",
            message=str(error) or error.__class__.__name__,
            hint="Re-run with --verbose and report the traceback.",
        )
        _emit_errors((diagnostic,), json_output=json_output)
        if verbose or os.environ.get(DEBUG_ENVIRONMENT_VARIABLE) == "1":
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
