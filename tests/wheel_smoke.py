from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import fields
from importlib.resources import files
from inspect import Parameter, signature
from pathlib import Path


def main() -> None:
    import glyphpact

    assert glyphpact.__version__ == "1.1.0"
    released_config_positionals = (
        "input_path",
        "output_dir",
        "font_family",
        "class_name",
        "font_package",
        "start_codepoint",
        "units_per_em",
        "precision",
        "padding",
        "clip_to_viewbox",
        "policy",
        "max_file_bytes",
        "max_total_input_bytes",
        "max_icons",
        "max_discovery_entries",
        "max_elements",
        "max_expanded_elements",
        "max_expanded_bytes",
        "max_path_commands",
        "max_total_path_commands",
        "jobs",
        "font_file",
        "dart_file",
        "lock_file",
        "report_file",
        "copyright",
        "text_fonts",
        "icons",
    )
    assert glyphpact.BuildConfig.__match_args__ == released_config_positionals
    catalog_parameter = signature(glyphpact.BuildConfig).parameters["catalog"]
    assert catalog_parameter.kind is Parameter.KEYWORD_ONLY
    assert catalog_parameter.default is False
    assert tuple(field.name for field in fields(glyphpact.BuildResult)) == (
        "output_dir",
        "font_path",
        "dart_path",
        "lock_path",
        "report_path",
        "layer_font_paths",
        "glyph_count",
        "discovered_icon_count",
        "lossless_glyph_count",
        "approximated_glyph_count",
        "skipped_icon_count",
        "issues",
        "policy",
        "font_sha256",
        "checked",
        "codepoints_remaining",
        "range_utilization",
        "warnings",
    )
    assert glyphpact.BuildResult.__match_args__ == (
        "output_dir",
        "font_path",
        "dart_path",
        "lock_path",
        "report_path",
        "layer_font_paths",
        "glyph_count",
        "discovered_icon_count",
        "lossless_glyph_count",
        "approximated_glyph_count",
        "skipped_icon_count",
        "issues",
        "policy",
        "font_sha256",
        "checked",
    )
    schema_root = files("glyphpact").joinpath("schema")
    required_schemas = {
        "cli-result.schema.json",
        "icon-font-config.schema.json",
        "icon-font-lock.schema.json",
        "icon-font-report.schema.json",
        "ownership-marker.schema.json",
    }
    assert required_schemas <= {item.name for item in schema_root.iterdir()}

    with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        root = Path(temporary)
        inputs = root / "icons"
        inputs.mkdir()
        (inputs / "smoke.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<path d="M1 1h8v8H1z"/></svg>',
            encoding="utf-8",
        )
        output = root / "generated"
        config = root / "icon_font.json"
        config.write_text(
            json.dumps(
                {
                    "input": "icons",
                    "output": "generated",
                    "fontFamily": "WheelSmokeIcons",
                    "className": "WheelSmokeIcons",
                    "catalog": True,
                }
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "glyphpact.cli",
                "--config",
                str(config),
                "--json",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        assert result["status"] == "ok"
        assert result["glyphCount"] == 1
        assert (output / "fonts" / "WheelSmokeIcons.otf").is_file()
        dart_path = output / "wheel_smoke_icons.dart"
        dart = dart_path.read_text(encoding="utf-8")
        assert "abstract final class WheelSmokeIconsCatalog" in dart
        assert "static const Map<String, flutter.IconData> byName" in dart
        report = json.loads((output / "iconfont.report.json").read_text(encoding="utf-8"))
        assert report["schemaVersion"] == 3
        assert report["codepointsRemaining"] == 6_399
        assert report["rangeUtilization"] == 1 / 6_400
        assert set(report["dart"]) == {"className", "file", "fontPackage"}

        checked = subprocess.run(
            [
                sys.executable,
                "-m",
                "glyphpact.cli",
                "--config",
                str(config),
                "--check",
                "--json",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(checked.stdout)["status"] == "ok"


if __name__ == "__main__":
    main()
