from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path


def main() -> None:
    import glyphpact

    assert glyphpact.__version__ == "1.0.1"
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
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "glyphpact.cli",
                str(inputs),
                "--output",
                str(output),
                "--name",
                "WheelSmokeIcons",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        assert result["status"] == "ok"
        assert result["glyphCount"] == 1
        assert (output / "fonts" / "WheelSmokeIcons.otf").is_file()
        assert (output / "wheel_smoke_icons.dart").is_file()


if __name__ == "__main__":
    main()
