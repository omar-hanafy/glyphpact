from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from conftest import write_svg
from jsonschema import Draft202012Validator

from glyphpact.cli import main

PROJECT_ROOT = Path(__file__).parents[1]
SCHEMA_ROOT = PROJECT_ROOT / "schema"


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_schema(name))


def _records(items: list[dict[str, Any]]) -> Counter[str]:
    return Counter(json.dumps(item, sort_keys=True) for item in items)


def test_published_schemas_are_valid_draft_2020_12_and_example_config_conforms() -> None:
    for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))

    config_validator = _validator("icon-font-config.schema.json")
    example = json.loads((PROJECT_ROOT / "examples" / "icon_font.json").read_text(encoding="utf-8"))
    config_validator.validate(example)

    assert not config_validator.is_valid({"input": "icons", "output": "generated", "className": ""})
    assert not config_validator.is_valid(
        {"input": "icons", "output": "generated", "startCodepoint": " 0xE000 "}
    )


@pytest.mark.parametrize(
    ("case", "extra_svg", "policy_args", "quality"),
    [
        ("lossless", None, [], "lossless"),
        (
            "approximated",
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect x="2" y="2" width="20" height="20" opacity=".5"/></svg>',
            ["--lossy", "convert"],
            "approximated",
        ),
        (
            "partial",
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<defs><filter id="blur"><feGaussianBlur stdDeviation="1"/></filter></defs>'
            '<rect x="2" y="2" width="20" height="20" filter="url(#blur)"/></svg>',
            ["--unrepresentable", "skip"],
            "partial",
        ),
    ],
)
def test_each_success_quality_validates_against_cli_and_report_schemas(
    tmp_path: Path,
    simple_svg: str,
    capsys,
    case: str,
    extra_svg: str | None,
    policy_args: list[str],
    quality: str,
) -> None:
    inputs = tmp_path / case / "icons"
    output = tmp_path / case / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    if extra_svg is not None:
        write_svg(inputs, f"{case}.svg", extra_svg)

    assert (
        main(
            [
                str(inputs),
                "--output",
                str(output),
                "--name",
                "SchemaIcons",
                "--jobs",
                "1",
                *policy_args,
                "--json",
            ]
        )
        == 0
    )
    cli_payload = json.loads(capsys.readouterr().out)
    report = json.loads((output / "iconfont.report.json").read_text(encoding="utf-8"))

    assert cli_payload["quality"] == report["quality"] == quality
    _validator("cli-result.schema.json").validate(cli_payload)
    _validator("icon-font-report.schema.json").validate(report)


def test_current_mixed_outcome_payloads_validate_and_preserve_semantic_counts(
    tmp_path: Path, simple_svg: str, capsys
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(
        inputs,
        "lossy.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<rect x="2" y="2" width="20" height="20" opacity=".5"/></svg>',
    )
    write_svg(
        inputs,
        "skipped.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<defs><filter id="blur"><feGaussianBlur stdDeviation="1"/></filter></defs>'
        '<rect x="2" y="2" width="20" height="20" filter="url(#blur)"/></svg>',
    )

    assert (
        main(
            [
                str(inputs),
                "--output",
                str(output),
                "--name",
                "SchemaIcons",
                "--jobs",
                "1",
                "--lossy",
                "convert",
                "--unrepresentable",
                "skip",
                "--json",
            ]
        )
        == 0
    )
    cli_payload = json.loads(capsys.readouterr().out)
    report = json.loads((output / "iconfont.report.json").read_text(encoding="utf-8"))
    lock = json.loads((output / "iconfont.lock.json").read_text(encoding="utf-8"))
    marker = json.loads((output / ".glyphpact.json").read_text(encoding="utf-8"))

    _validator("cli-result.schema.json").validate(cli_payload)
    _validator("icon-font-report.schema.json").validate(report)
    _validator("icon-font-lock.schema.json").validate(lock)
    _validator("ownership-marker.schema.json").validate(marker)

    assert cli_payload["discoveredIconCount"] == (
        cli_payload["glyphCount"] + cli_payload["skippedIconCount"]
    )
    assert cli_payload["glyphCount"] == (
        cli_payload["losslessGlyphCount"] + cli_payload["approximatedGlyphCount"]
    )
    assert cli_payload["issueCount"] == len(cli_payload["issues"])

    assert report["discoveredIconCount"] == report["glyphCount"] + report["skippedIconCount"]
    assert report["glyphCount"] == len(report["glyphs"])
    assert report["skippedIconCount"] == len(report["skippedIcons"])
    assert report["losslessGlyphCount"] == sum(
        glyph["conversion"] == "lossless" for glyph in report["glyphs"]
    )
    assert report["approximatedGlyphCount"] == sum(
        glyph["conversion"] == "approximated" for glyph in report["glyphs"]
    )
    assert report["issueCount"] == len(report["issues"])
    nested_issues = [issue for glyph in report["glyphs"] for issue in glyph["issues"]]
    nested_issues.extend(
        issue for skipped_icon in report["skippedIcons"] for issue in skipped_icon["issues"]
    )
    assert _records(report["issues"]) == _records(nested_issues)
    assert cli_payload["issues"] == report["issues"]

    cli_validator = _validator("cli-result.schema.json")
    impossible_cli = copy.deepcopy(cli_payload)
    impossible_cli["quality"] = "lossless"
    assert not cli_validator.is_valid(impossible_cli)
    impossible_cli = copy.deepcopy(cli_payload)
    impossible_cli["policy"]["lossy"] = "error"
    assert not cli_validator.is_valid(impossible_cli)
    impossible_cli = copy.deepcopy(cli_payload)
    impossible_cli["policy"]["unrepresentable"] = "error"
    assert not cli_validator.is_valid(impossible_cli)
    impossible_cli = copy.deepcopy(cli_payload)
    impossible_cli["approximatedGlyphCount"] = 0
    assert not cli_validator.is_valid(impossible_cli)
    impossible_cli = copy.deepcopy(cli_payload)
    impossible_cli["skippedIconCount"] = 0
    assert not cli_validator.is_valid(impossible_cli)
    impossible_cli = copy.deepcopy(cli_payload)
    impossible_cli["issueCount"] = 0
    assert not cli_validator.is_valid(impossible_cli)

    report_validator = _validator("icon-font-report.schema.json")
    impossible_report = copy.deepcopy(report)
    impossible_report["quality"] = "lossless"
    assert not report_validator.is_valid(impossible_report)
    impossible_report = copy.deepcopy(report)
    approximated = next(
        glyph for glyph in impossible_report["glyphs"] if glyph["conversion"] == "approximated"
    )
    approximated["conversion"] = "lossless"
    assert not report_validator.is_valid(impossible_report)
    impossible_report = copy.deepcopy(report)
    impossible_report["approximatedGlyphCount"] = 0
    assert not report_validator.is_valid(impossible_report)
    impossible_report = copy.deepcopy(report)
    impossible_report["skippedIconCount"] = 0
    assert not report_validator.is_valid(impossible_report)
    impossible_report = copy.deepcopy(report)
    impossible_report["issueCount"] = 0
    assert not report_validator.is_valid(impossible_report)


def test_scoped_layered_fallback_validates_under_global_strict_lossy_policy(
    tmp_path: Path,
    capsys,
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(
        inputs,
        "bulk.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path opacity=".4" d="M1 1h8v8H1z"/>'
        '<path d="M12 12h8v8h-8z"/></svg>',
    )
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "policy": {"lossy": "error", "unrepresentable": "error"},
                "icons": {
                    "bulk.svg": {
                        "partialAlpha": {
                            "mode": "layers",
                            "fallback": "silhouette",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert main(["--config", str(config_path), "--jobs", "1", "--json"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    report = json.loads((output / "iconfont.report.json").read_text(encoding="utf-8"))

    assert cli_payload["policy"]["lossy"] == "error"
    assert cli_payload["approximatedGlyphCount"] == 1
    assert len(cli_payload["layerFonts"]) == 2
    assert report["glyphs"][0]["layeredRendering"]["lossless"] is True
    _validator("cli-result.schema.json").validate(cli_payload)
    _validator("icon-font-report.schema.json").validate(report)

    forged_cli = copy.deepcopy(cli_payload)
    forged_cli["issues"][0]["details"].pop("scope")
    assert not _validator("cli-result.schema.json").is_valid(forged_cli)
    forged_report = copy.deepcopy(report)
    forged_report["issues"][0]["details"].pop("scope")
    forged_report["glyphs"][0]["issues"][0]["details"].pop("scope")
    assert not _validator("icon-font-report.schema.json").is_valid(forged_report)

    crossed_cli = copy.deepcopy(cli_payload)
    crossed_cli["issues"][0]["details"]["approximation"] = "opaque-only"
    assert not _validator("cli-result.schema.json").is_valid(crossed_cli)
    crossed_report = copy.deepcopy(report)
    crossed_report["issues"][0]["details"]["approximation"] = "opaque-only"
    crossed_report["glyphs"][0]["issues"][0]["details"]["approximation"] = "opaque-only"
    assert not _validator("icon-font-report.schema.json").is_valid(crossed_report)


def test_current_cli_failure_payload_validates(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing"
    output = tmp_path / "generated"

    assert main([str(missing), "--output", str(output), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)

    _validator("cli-result.schema.json").validate(payload)
    assert payload["errorCount"] == len(payload["errors"])
