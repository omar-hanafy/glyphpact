from __future__ import annotations

import copy
import hashlib
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
PUBLISHED_REPORT_V2_SHA256 = "b5327cd0d8a48dad2487cfcf2440b4f8f6713bc50c9d59c807a0c9b864286a61"
PUBLISHED_REPORT_V1_SHA256 = "7d4bbfbeb54ee76bf4702f129a882cb0a9ee1ff78ec036cb858f0a141f9b7ceb"
PUBLISHED_REPORT_DEFS_SHA256 = "7e9b6d20a6a2b88b3032527b56342f780fa4dfad4c01ea8622926c3a3ee6d25a"


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_schema(name))


def _records(items: list[dict[str, Any]]) -> Counter[str]:
    return Counter(json.dumps(item, sort_keys=True) for item in items)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _as_report_v2(report: dict[str, Any]) -> dict[str, Any]:
    legacy = copy.deepcopy(report)
    legacy["schemaVersion"] = 2
    legacy.pop("codepointsRemaining")
    legacy.pop("rangeUtilization")
    return legacy


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


def test_catalog_is_config_only_and_report_versions_remain_closed() -> None:
    config_schema = _schema("icon-font-config.schema.json")
    catalog = config_schema["properties"]["catalog"]
    assert catalog["type"] == "boolean"
    assert catalog["default"] is False
    validator = _validator("icon-font-config.schema.json")
    assert validator.is_valid({"input": "icons", "output": "generated", "catalog": True})
    assert not validator.is_valid(
        {"input": "icons", "output": "generated", "catalogFile": "icons.catalog.dart"}
    )

    report_schema = _schema("icon-font-report.schema.json")
    assert [entry["$ref"] for entry in report_schema["oneOf"]] == [
        "#/$defs/reportV3",
        "#/$defs/reportV2",
        "#/$defs/reportV1",
    ]
    dart_schema = report_schema["$defs"]["dart"]
    assert dart_schema["additionalProperties"] is False
    assert set(dart_schema["required"]) == {"className", "file", "fontPackage"}
    assert set(dart_schema["properties"]) == {"className", "file", "fontPackage"}
    assert _canonical_sha256(report_schema["$defs"]["reportV2"]) == PUBLISHED_REPORT_V2_SHA256
    assert _canonical_sha256(report_schema["$defs"]["reportV1"]) == PUBLISHED_REPORT_V1_SHA256
    published_defs = {
        name: definition
        for name, definition in report_schema["$defs"].items()
        if name != "reportV3"
    }
    assert _canonical_sha256(published_defs) == PUBLISHED_REPORT_DEFS_SHA256


def test_catalog_enabled_report_validates_against_report_v3(
    tmp_path: Path, simple_svg: str, capsys
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "icon.svg", simple_svg)

    assert (
        main(
            [
                str(inputs),
                "--output",
                str(output),
                "--name",
                "SchemaIcons",
                "--catalog",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    report = json.loads((output / "iconfont.report.json").read_text(encoding="utf-8"))

    assert report["schemaVersion"] == 3
    assert report["codepointsRemaining"] == 6_399
    assert report["rangeUtilization"] == 1 / 6_400
    validator = _validator("icon-font-report.schema.json")
    validator.validate(report)

    legacy_v2 = _as_report_v2(report)
    validator.validate(legacy_v2)

    v2_with_new_field = copy.deepcopy(legacy_v2)
    v2_with_new_field["codepointsRemaining"] = 6_399
    assert not validator.is_valid(v2_with_new_field)
    v3_without_capacity = copy.deepcopy(report)
    v3_without_capacity.pop("rangeUtilization")
    assert not validator.is_valid(v3_without_capacity)

    report_schema = _schema("icon-font-report.schema.json")
    v1_properties = report_schema["$defs"]["reportV1"]["properties"]
    glyph_v1_properties = report_schema["$defs"]["glyphV1"]["properties"]
    legacy_v1 = {key: copy.deepcopy(value) for key, value in report.items() if key in v1_properties}
    legacy_v1["schemaVersion"] = 1
    legacy_v1["glyphs"] = [
        {key: copy.deepcopy(value) for key, value in glyph.items() if key in glyph_v1_properties}
        for glyph in report["glyphs"]
    ]
    validator.validate(legacy_v1)


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
    report_validator = _validator("icon-font-report.schema.json")
    report_validator.validate(report)
    report_validator.validate(_as_report_v2(report))


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
    consumed = report["glyphCount"] + report["retiredCodepointCount"]
    assert report["codepointsRemaining"] + consumed == 6_400
    assert report["rangeUtilization"] == consumed / 6_400
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
    report_validator = _validator("icon-font-report.schema.json")
    report_validator.validate(report)
    report_validator.validate(_as_report_v2(report))

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
