from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from _bundle import (  # noqa: E402
    EXPECTED_CHECKSUM_FILENAME,
    EXPECTED_MCP_REQUIREMENTS,
    EXPECTED_PACKAGE_MEMBERS,
    EXPECTED_SCHEMA_MEMBERS,
    EXPECTED_VERSION,
    EXPECTED_WHEEL_FILENAME,
    BundleError,
    inspect_wheel,
    sync_wheel,
    verify_plugin_bundle,
    verify_source_matches_bundle,
)

EXPECTED_DIST_INFO = f"glyphpact-{EXPECTED_VERSION}.dist-info"


class BundleTest(unittest.TestCase):
    def _write_plugin_root(self, root: Path) -> None:
        dist = root / "dist"
        dist.mkdir(parents=True)
        (dist / "mcp-requirements.txt").write_text(
            "\n".join(EXPECTED_MCP_REQUIREMENTS) + "\n",
            encoding="utf-8",
        )

    def _write_wheel(
        self,
        path: Path,
        *,
        name: str = "glyphpact",
        version: str = EXPECTED_VERSION,
        omit: set[str] | None = None,
        overrides: dict[str, str | bytes] | None = None,
    ) -> None:
        dist_info = f"glyphpact-{version}.dist-info"
        members: dict[str, str | bytes] = {
            member: '"""Structurally valid fixture module."""\n'
            for member in EXPECTED_PACKAGE_MEMBERS
            if member.endswith(".py")
        }
        members.update(
            {
                "glyphpact/__init__.py": f'__version__ = "{version}"\n',
                "glyphpact/__main__.py": (
                    "from .cli import main\n\n"
                    'if __name__ == "__main__":\n'
                    "    raise SystemExit(main())\n"
                ),
                "glyphpact/builder.py": "def build(*args, **kwargs):\n    return None\n",
                "glyphpact/cli.py": "def main():\n    return 0\n",
                "glyphpact/config.py": "def load_config(path):\n    return path\n",
                "glyphpact/mcp_server.py": (
                    "def create_server():\n    return object()\n\ndef main():\n    return None\n"
                ),
                "glyphpact/mcp_tools.py": (
                    "async def audit_icon_pack():\n"
                    "    return {}\n\n"
                    "async def build_icon_font():\n"
                    "    return {}\n\n"
                    "async def check_icon_font():\n"
                    "    return {}\n\n"
                    "def read_icon_report():\n"
                    "    return {}\n"
                ),
                "glyphpact/py.typed": b"",
                **{
                    member: json.dumps(
                        {
                            "$schema": "https://json-schema.org/draft/2020-12/schema",
                            "type": "object",
                        }
                    )
                    for member in EXPECTED_SCHEMA_MEMBERS
                },
                f"{dist_info}/METADATA": (
                    f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
                ),
                f"{dist_info}/WHEEL": (
                    "Wheel-Version: 1.0\n"
                    "Generator: test\n"
                    "Root-Is-Purelib: true\n"
                    "Tag: py3-none-any\n"
                ),
                f"{dist_info}/entry_points.txt": (
                    "[console_scripts]\n"
                    "glyphpact = glyphpact.cli:main\n"
                    "glyphpact-mcp = glyphpact.mcp_server:main\n"
                ),
                f"{dist_info}/licenses/LICENSE": "MIT License\n",
                f"{dist_info}/licenses/NOTICE": "GlyphPact test fixture\n",
                f"{dist_info}/RECORD": "glyphpact/__init__.py,,\n",
            }
        )
        members.update(overrides or {})
        omitted = omit or set()
        with zipfile.ZipFile(path, "w") as archive:
            for member, value in sorted(members.items()):
                if member not in omitted:
                    archive.writestr(member, value)

    def test_sync_and_verify_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_plugin_root(root)
            source = root / "fresh.whl"
            self._write_wheel(source)

            identity = sync_wheel(source, root)
            verified = verify_plugin_bundle(root)

            self.assertEqual(verified, identity)
            wheel = root / "dist" / EXPECTED_WHEEL_FILENAME
            expected_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            self.assertEqual(identity.sha256, expected_digest)
            self.assertEqual(
                (root / "dist" / EXPECTED_CHECKSUM_FILENAME).read_text(),
                f"{expected_digest}  {EXPECTED_WHEEL_FILENAME}\n",
            )

    def test_fixture_exposes_importable_console_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "fixture.whl"
            self._write_wheel(wheel)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {str(wheel)!r}); "
                        "from glyphpact.cli import main as cli; "
                        "from glyphpact.mcp_server import main as mcp; "
                        "assert callable(cli) and callable(mcp)"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_distribution_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "wrong.whl"
            self._write_wheel(wheel, name="another-project")
            with self.assertRaisesRegex(BundleError, "Expected distribution"):
                inspect_wheel(wheel)

    def test_missing_required_runtime_contents_are_rejected(self) -> None:
        missing_members = (
            "glyphpact/mcp_server.py",
            "glyphpact/mcp_tools.py",
            "glyphpact/schema/icon-font-report.schema.json",
            f"{EXPECTED_DIST_INFO}/entry_points.txt",
        )
        for missing in missing_members:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                wheel = Path(temporary) / "missing.whl"
                self._write_wheel(wheel, omit={missing})
                with self.assertRaisesRegex(BundleError, "missing required member"):
                    inspect_wheel(wheel)

    def test_malformed_runtime_contents_are_rejected(self) -> None:
        cases = (
            (
                {"glyphpact/mcp_server.py": "def main(:\n"},
                "Python module is malformed",
            ),
            (
                {"glyphpact/schema/icon-font-report.schema.json": "{"},
                "schema is malformed",
            ),
            (
                {f"{EXPECTED_DIST_INFO}/entry_points.txt": "[console_scripts\n"},
                "entry_points.txt is malformed",
            ),
        )
        for overrides, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                wheel = Path(temporary) / "malformed.whl"
                self._write_wheel(wheel, overrides=overrides)
                with self.assertRaisesRegex(BundleError, message):
                    inspect_wheel(wheel)

    def test_wrong_or_incomplete_mcp_contract_is_rejected(self) -> None:
        cases = (
            (
                {
                    f"{EXPECTED_DIST_INFO}/entry_points.txt": (
                        "[console_scripts]\n"
                        "glyphpact = glyphpact.cli:main\n"
                        "glyphpact-mcp = glyphpact.cli:main\n"
                    )
                },
                "console entry point 'glyphpact-mcp'",
            ),
            (
                {"glyphpact/mcp_tools.py": ("async def audit_icon_pack():\n    return {}\n")},
                "missing function",
            ),
        )
        for overrides, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                wheel = Path(temporary) / "invalid-contract.whl"
                self._write_wheel(wheel, overrides=overrides)
                with self.assertRaisesRegex(BundleError, message):
                    inspect_wheel(wheel)

    def test_non_wheel_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "broken.whl"
            wheel.write_bytes(b"not a zip archive")
            with self.assertRaisesRegex(BundleError, "Cannot read wheel metadata"):
                inspect_wheel(wheel)

    def test_missing_wheel_is_only_allowed_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_plugin_root(root)
            self.assertIsNone(verify_plugin_bundle(root, allow_missing_wheel=True))
            with self.assertRaisesRegex(BundleError, "Missing bundled wheel"):
                verify_plugin_bundle(root)

    def test_runtime_requirements_must_be_complete_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_plugin_root(root)
            (root / "dist" / "mcp-requirements.txt").write_text(
                f"{EXPECTED_MCP_REQUIREMENTS[-1]}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BundleError, "pinned requirements"):
                verify_plugin_bundle(root, allow_missing_wheel=True)

    def test_checksum_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_plugin_root(root)
            source = root / "fresh.whl"
            self._write_wheel(source)
            sync_wheel(source, root)
            (root / "dist" / EXPECTED_CHECKSUM_FILENAME).write_text(
                f"{'0' * 64}  {EXPECTED_WHEEL_FILENAME}\n"
            )
            with self.assertRaisesRegex(BundleError, "checksum does not match"):
                verify_plugin_bundle(root)

    def test_unexpected_release_artifact_is_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_plugin_root(root)
            source = root / "fresh.whl"
            self._write_wheel(source)
            unexpected = root / "dist" / "glyphpact-0.9.0-py3-none-any.whl"
            self._write_wheel(unexpected, version="0.9.0")
            with self.assertRaisesRegex(BundleError, "unexpected release artifacts"):
                sync_wheel(source, root)
            self.assertTrue(unexpected.exists())

    def test_check_detects_a_stale_bundle_without_replacing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_plugin_root(root)
            first = root / "first.whl"
            second = root / "second.whl"
            self._write_wheel(first)
            self._write_wheel(second)
            with zipfile.ZipFile(second, "a") as archive:
                archive.writestr("glyphpact/changed.txt", "changed")
            synced = sync_wheel(first, root)

            self.assertEqual(verify_source_matches_bundle(first, root), synced)
            with self.assertRaisesRegex(BundleError, "does not match"):
                verify_source_matches_bundle(second, root)
            self.assertEqual(verify_plugin_bundle(root), synced)


if __name__ == "__main__":
    unittest.main()
