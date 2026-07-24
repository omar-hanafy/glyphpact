from __future__ import annotations

import json

import pytest
from conftest import write_svg

import glyphpact.cli as cli_module
from glyphpact.cli import main
from glyphpact.errors import BatchError, Diagnostic, IconFontError

LOSSY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<rect x="2" y="2" width="20" height="20" opacity=".5"/>'
    "</svg>"
)
UNREPRESENTABLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<defs><filter id="blur"><feGaussianBlur stdDeviation="1"/></filter></defs>'
    '<rect x="2" y="2" width="20" height="20" filter="url(#blur)"/>'
    "</svg>"
)


def test_cli_json_build_and_check(tmp_path, simple_svg: str, capsys) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "home.svg", simple_svg)

    assert (
        main(
            [
                str(inputs),
                "--output",
                str(output),
                "--name",
                "CliIcons",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schemaVersion"] == 2
    assert payload["status"] == "ok"
    assert payload["mode"] == "build"
    assert payload["quality"] == "lossless"
    assert payload["policy"] == {"lossy": "error", "unrepresentable": "error"}
    assert payload["discoveredIconCount"] == 1
    assert payload["glyphCount"] == 1
    assert payload["losslessGlyphCount"] == 1
    assert payload["approximatedGlyphCount"] == 0
    assert payload["skippedIconCount"] == 0
    assert payload["issueCount"] == 0
    assert payload["issues"] == []

    assert (
        main(
            [
                str(inputs),
                "--output",
                str(output),
                "--name",
                "CliIcons",
                "--check",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["mode"] == "check"


def test_cli_json_v2_reports_approved_lossy_and_skipped_outcomes(
    tmp_path, simple_svg: str, capsys
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(inputs, "lossy.svg", LOSSY_SVG)
    write_svg(inputs, "unsupported.svg", UNREPRESENTABLE_SVG)
    args = [
        str(inputs),
        "--output",
        str(output),
        "--name",
        "CliIcons",
        "--jobs",
        "1",
        "--lossy",
        "convert",
        "--unrepresentable",
        "skip",
        "--json",
    ]

    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schemaVersion"] == 2
    assert payload["status"] == "ok"
    assert payload["mode"] == "build"
    assert payload["quality"] == "partial"
    assert payload["policy"] == {"lossy": "convert", "unrepresentable": "skip"}
    assert payload["discoveredIconCount"] == 3
    assert payload["glyphCount"] == 2
    assert payload["losslessGlyphCount"] == 1
    assert payload["approximatedGlyphCount"] == 1
    assert payload["skippedIconCount"] == 1
    assert payload["issueCount"] == len(payload["issues"]) == 3
    assert {(issue["classification"], issue["action"]) for issue in payload["issues"]} == {
        ("lossy", "converted"),
        ("unrepresentable", "skipped"),
    }

    assert main([*args, "--check"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["schemaVersion"] == 2
    assert checked["mode"] == "check"
    assert checked["quality"] == "partial"
    assert checked["issues"] == payload["issues"]


def test_cli_check_rejects_partial_output_under_stricter_policy(
    tmp_path, simple_svg: str, capsys
) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(inputs, "lossy.svg", LOSSY_SVG)
    write_svg(inputs, "unsupported.svg", UNREPRESENTABLE_SVG)
    common = [str(inputs), "-o", str(output), "-n", "CliIcons", "--jobs", "1", "--json"]

    assert main([*common, "--lossy", "convert", "--unrepresentable", "skip"]) == 0
    capsys.readouterr()
    before = (output / "iconfont.report.json").read_bytes()

    assert main([*common, "--check"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "error"
    assert {error["details"]["classification"] for error in payload["errors"]} == {
        "lossy",
        "unrepresentable",
    }
    assert (output / "iconfont.report.json").read_bytes() == before


def test_cli_config_overrides_each_policy_axis_independently(
    tmp_path, simple_svg: str, capsys
) -> None:
    inputs = tmp_path / "icons"
    write_svg(inputs, "good.svg", simple_svg)
    write_svg(inputs, "lossy.svg", LOSSY_SVG)
    write_svg(inputs, "unsupported.svg", UNREPRESENTABLE_SVG)
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "fontFamily": "CliIcons",
                "jobs": 1,
                "policy": {"lossy": "convert", "unrepresentable": "skip"},
            }
        ),
        encoding="utf-8",
    )
    common = ["--config", str(config_path), "--check", "--json"]

    assert main(["--config", str(config_path), "--json"]) == 0
    capsys.readouterr()

    assert main([*common, "--lossy", "error"]) == 2
    lossy_error = json.loads(capsys.readouterr().out)
    assert {
        error["details"]["classification"]
        for error in lossy_error["errors"]
        if error["details"].get("action") != "skipped"
    } == {"lossy"}
    assert any(error["details"].get("action") == "skipped" for error in lossy_error["errors"])

    assert main([*common, "--unrepresentable", "error"]) == 2
    unrepresentable_error = json.loads(capsys.readouterr().out)
    assert {error["details"]["classification"] for error in unrepresentable_error["errors"]} == {
        "unrepresentable"
    }


def test_cli_json_reports_stable_diagnostic(tmp_path, capsys) -> None:
    missing = tmp_path / "missing"
    assert main([str(missing), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "error",
        "errorCount": 1,
        "errors": [
            {
                "code": "INPUT_NOT_FOUND",
                "message": "The input path is not a file or directory.",
                "source": str(missing.resolve()),
            }
        ],
    }


def test_cli_check_drift_uses_exit_3(tmp_path, simple_svg: str, capsys) -> None:
    inputs = tmp_path / "icons"
    output = tmp_path / "generated"
    write_svg(inputs, "home.svg", simple_svg)
    args = [str(inputs), "-o", str(output), "-n", "CliIcons", "--json"]
    assert main(args) == 0
    capsys.readouterr()
    (output / "cli_icons.dart").write_text("stale", encoding="utf-8")

    assert main([*args, "--check"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["code"] == "OUTPUT_OUT_OF_DATE"


def test_cli_argument_errors_honor_json_mode(capsys) -> None:
    assert main(["--jobs", "not-an-integer", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["errors"][0]["code"] == "CLI_ARGUMENT_INVALID"


def test_empty_diagnostic_batches_are_unrepresentable() -> None:
    with pytest.raises(ValueError, match="at least one diagnostic"):
        BatchError(())


@pytest.mark.parametrize(
    "diagnostic",
    [
        lambda: Diagnostic("lowercase", "message"),
        lambda: Diagnostic("VALID_CODE", ""),
        lambda: Diagnostic("VALID_CODE", "message", details={"value": float("nan")}),
        lambda: Diagnostic("VALID_CODE", "message", details={"value": object()}),
    ],
)
def test_invalid_diagnostics_are_unrepresentable(diagnostic) -> None:
    with pytest.raises(ValueError):
        diagnostic()


def test_cli_json_diagnostic_serialization_fails_closed(tmp_path, monkeypatch, capsys) -> None:
    error = IconFontError("TEST_ERROR", "Synthetic typed error.")
    error.diagnostic.details["path"] = tmp_path

    def fail_build(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(cli_module, "build", fail_build)

    result = main(
        [
            str(tmp_path / "icons"),
            "--output",
            str(tmp_path / "generated"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload == {
        "status": "error",
        "errorCount": 1,
        "errors": [
            {
                "code": "INTERNAL_ERROR",
                "message": "An error diagnostic could not be serialized safely.",
                "hint": "Re-run with --verbose and report this failure.",
            }
        ],
    }
