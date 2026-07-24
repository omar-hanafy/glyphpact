"""Shared validation for the GlyphPact plugin's bundled compiler wheel."""

from __future__ import annotations

import ast
import configparser
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path, PurePosixPath

EXPECTED_DISTRIBUTION = "glyphpact"
EXPECTED_VERSION = "1.0.0"
EXPECTED_WHEEL_FILENAME = "glyphpact-1.0.0-py3-none-any.whl"
EXPECTED_CHECKSUM_FILENAME = f"{EXPECTED_WHEEL_FILENAME}.sha256"
EXPECTED_MCP_REQUIREMENTS = (
    "jsonschema==4.26.0",
    "mcp==1.28.1",
)
EXPECTED_PACKAGE_MEMBERS = frozenset(
    {
        "glyphpact/__init__.py",
        "glyphpact/__main__.py",
        "glyphpact/attribution.py",
        "glyphpact/builder.py",
        "glyphpact/cli.py",
        "glyphpact/config.py",
        "glyphpact/css_cascade.py",
        "glyphpact/dart_generator.py",
        "glyphpact/discovery.py",
        "glyphpact/errors.py",
        "glyphpact/font_builder.py",
        "glyphpact/identity.py",
        "glyphpact/manifest.py",
        "glyphpact/mcp_server.py",
        "glyphpact/mcp_tools.py",
        "glyphpact/naming.py",
        "glyphpact/output_lock.py",
        "glyphpact/portable_paths.py",
        "glyphpact/publisher.py",
        "glyphpact/py.typed",
        "glyphpact/svg_compiler.py",
        "glyphpact/text_outliner.py",
        "glyphpact/version.py",
    }
)
EXPECTED_SCHEMA_MEMBERS = frozenset(
    {
        "glyphpact/schema/cli-result.schema.json",
        "glyphpact/schema/icon-font-config.schema.json",
        "glyphpact/schema/icon-font-lock.schema.json",
        "glyphpact/schema/icon-font-report.schema.json",
        "glyphpact/schema/ownership-marker.schema.json",
    }
)
EXPECTED_CONSOLE_SCRIPTS = {
    "glyphpact": "glyphpact.cli:main",
    "glyphpact-mcp": "glyphpact.mcp_server:main",
}
EXPECTED_MODULE_FUNCTIONS = {
    "glyphpact/builder.py": {"build"},
    "glyphpact/cli.py": {"main"},
    "glyphpact/config.py": {"load_config"},
    "glyphpact/mcp_server.py": {"create_server", "main"},
    "glyphpact/mcp_tools.py": {
        "audit_icon_pack",
        "build_icon_font",
        "check_icon_font",
        "read_icon_report",
    },
}


class BundleError(RuntimeError):
    """Report an invalid or unsafe plugin bundle."""


@dataclass(frozen=True)
class WheelIdentity:
    name: str
    version: str
    sha256: str
    size: int


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _normalized_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_utf8(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeError as error:
        raise BundleError(f"{label} is not valid UTF-8.") from error


def _validate_python_member(name: str, value: bytes) -> None:
    source = _decode_utf8(value, name)
    if not source.strip():
        raise BundleError(f"Required Python module is empty: {name}.")
    try:
        tree = ast.parse(source, filename=name)
    except SyntaxError as error:
        raise BundleError(f"Required Python module is malformed: {name}: {error}") from error
    required_functions = EXPECTED_MODULE_FUNCTIONS.get(name)
    if required_functions is None:
        return
    defined = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = sorted(required_functions - defined)
    if missing:
        raise BundleError(
            f"Required Python module {name} is missing function(s): {', '.join(missing)}."
        )


def _validate_schema_member(name: str, value: bytes) -> None:
    try:
        schema = json.loads(_decode_utf8(value, name))
    except json.JSONDecodeError as error:
        raise BundleError(f"Packaged schema is malformed: {name}: {error}") from error
    if not isinstance(schema, dict) or not isinstance(schema.get("$schema"), str):
        raise BundleError(f"Packaged schema has no JSON Schema dialect: {name}.")


def _validate_entry_points(value: bytes) -> None:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(_decode_utf8(value, "entry_points.txt"))
    except configparser.Error as error:
        raise BundleError(f"Wheel entry_points.txt is malformed: {error}") from error
    if not parser.has_section("console_scripts"):
        raise BundleError("Wheel entry_points.txt has no [console_scripts] section.")
    actual = dict(parser.items("console_scripts"))
    for command, target in EXPECTED_CONSOLE_SCRIPTS.items():
        if actual.get(command) != target:
            raise BundleError(f"Wheel console entry point {command!r} must target {target!r}.")


def inspect_wheel(path: Path) -> WheelIdentity:
    candidate = path.expanduser().resolve()
    if not candidate.is_file():
        raise BundleError(f"Wheel does not exist: {candidate}")
    if candidate.suffix != ".whl":
        raise BundleError(f"Expected a .whl file: {candidate}")
    if candidate.stat().st_size <= 0:
        raise BundleError(f"Wheel is empty: {candidate}")

    try:
        with zipfile.ZipFile(candidate) as archive:
            names = [info.filename for info in archive.infolist()]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                raise BundleError(
                    "Wheel contains duplicate archive member(s): " + ", ".join(duplicates)
                )
            unsafe = sorted(
                name
                for name in names
                if (
                    "\\" in name
                    or PurePosixPath(name).is_absolute()
                    or ".." in PurePosixPath(name).parts
                )
            )
            if unsafe:
                raise BundleError("Wheel contains unsafe archive member(s): " + ", ".join(unsafe))
            metadata_names = [
                name
                for name in names
                if name.endswith(".dist-info/METADATA") and not name.startswith("/")
            ]
            if len(metadata_names) != 1:
                raise BundleError(
                    "Wheel must contain exactly one .dist-info/METADATA file; "
                    f"found {len(metadata_names)}."
                )
            dist_info = metadata_names[0].removesuffix("METADATA")
            required_members = {
                *EXPECTED_PACKAGE_MEMBERS,
                *EXPECTED_SCHEMA_MEMBERS,
                metadata_names[0],
                f"{dist_info}WHEEL",
                f"{dist_info}entry_points.txt",
                f"{dist_info}licenses/LICENSE",
                f"{dist_info}licenses/NOTICE",
                f"{dist_info}RECORD",
            }
            missing_members = sorted(required_members - set(names))
            if missing_members:
                raise BundleError(
                    "Wheel is missing required member(s): " + ", ".join(missing_members)
                )
            members = {name: archive.read(name) for name in required_members}
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise BundleError(f"Cannot read wheel metadata: {error}") from error

    metadata_bytes = members[metadata_names[0]]
    try:
        metadata = Parser().parsestr(metadata_bytes.decode("utf-8"))
    except UnicodeError as error:
        raise BundleError("Wheel METADATA is not valid UTF-8.") from error
    name = metadata.get("Name", "").strip()
    version = metadata.get("Version", "").strip()
    if _normalized_distribution(name) != EXPECTED_DISTRIBUTION:
        raise BundleError(f"Expected distribution {EXPECTED_DISTRIBUTION!r}, found {name!r}.")
    if version != EXPECTED_VERSION:
        raise BundleError(f"Expected version {EXPECTED_VERSION!r}, found {version!r}.")

    for member in sorted(EXPECTED_PACKAGE_MEMBERS - {"glyphpact/py.typed"}):
        _validate_python_member(member, members[member])
    for member in sorted(EXPECTED_SCHEMA_MEMBERS):
        _validate_schema_member(member, members[member])
    _validate_entry_points(members[f"{dist_info}entry_points.txt"])
    for member in (
        f"{dist_info}WHEEL",
        f"{dist_info}licenses/LICENSE",
        f"{dist_info}licenses/NOTICE",
        f"{dist_info}RECORD",
    ):
        if not members[member]:
            raise BundleError(f"Wheel member is empty: {member}.")

    return WheelIdentity(
        name=name,
        version=version,
        sha256=_sha256(candidate),
        size=candidate.stat().st_size,
    )


def _require_expected_dist_contents(dist_dir: Path) -> None:
    allowed_wheels = {EXPECTED_WHEEL_FILENAME}
    allowed_checksums = {EXPECTED_CHECKSUM_FILENAME}
    unexpected = sorted(
        [
            *(path.name for path in dist_dir.glob("*.whl") if path.name not in allowed_wheels),
            *(
                path.name
                for path in dist_dir.glob("*.whl.sha256")
                if path.name not in allowed_checksums
            ),
        ]
    )
    if unexpected:
        raise BundleError(
            "Refusing to modify a dist directory with unexpected release artifacts: "
            + ", ".join(unexpected)
        )


def _atomic_write_bytes(destination: Path, value: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def sync_wheel(source: Path, destination_root: Path) -> WheelIdentity:
    root = destination_root.expanduser().resolve()
    dist_dir = root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    _require_expected_dist_contents(dist_dir)

    source_path = source.expanduser().resolve()
    destination = dist_dir / EXPECTED_WHEEL_FILENAME
    if source_path == destination.resolve():
        raise BundleError("Source wheel is already the plugin bundle destination.")
    source_identity = inspect_wheel(source_path)

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{EXPECTED_WHEEL_FILENAME}.",
        suffix=".whl",
        dir=dist_dir,
    )
    temporary = Path(temporary_name)
    try:
        with source_path.open("rb") as source_stream, os.fdopen(handle, "wb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        os.chmod(temporary, 0o644)
        copied_identity = inspect_wheel(temporary)
        if copied_identity != source_identity:
            raise BundleError("Source wheel changed while it was being copied.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    checksum = f"{source_identity.sha256}  {EXPECTED_WHEEL_FILENAME}\n".encode()
    _atomic_write_bytes(dist_dir / EXPECTED_CHECKSUM_FILENAME, checksum)

    verified = verify_plugin_bundle(root)
    if verified is None:
        raise BundleError("Bundle verification unexpectedly found no wheel.")
    return verified


def verify_source_matches_bundle(source: Path, destination_root: Path) -> WheelIdentity:
    source_identity = inspect_wheel(source)
    bundled_identity = verify_plugin_bundle(destination_root)
    if bundled_identity is None:
        raise BundleError("Bundle verification unexpectedly found no wheel.")
    if source_identity != bundled_identity:
        raise BundleError(
            "Freshly built wheel does not match the plugin bundle. "
            "Run scripts/sync_wheel.py without --check to synchronize it."
        )
    return bundled_identity


def verify_plugin_bundle(
    destination_root: Path,
    *,
    allow_missing_wheel: bool = False,
) -> WheelIdentity | None:
    root = destination_root.expanduser().resolve()
    dist_dir = root / "dist"
    requirement_path = dist_dir / "mcp-requirements.txt"
    if not requirement_path.is_file():
        raise BundleError(f"Missing MCP requirements file: {requirement_path}")
    requirement_lines = tuple(
        line.strip()
        for line in requirement_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if requirement_lines != EXPECTED_MCP_REQUIREMENTS:
        raise BundleError(
            "mcp-requirements.txt must contain exactly the pinned requirements "
            f"{EXPECTED_MCP_REQUIREMENTS!r}; found {requirement_lines!r}."
        )

    _require_expected_dist_contents(dist_dir)
    wheel_path = dist_dir / EXPECTED_WHEEL_FILENAME
    checksum_path = dist_dir / EXPECTED_CHECKSUM_FILENAME
    if not wheel_path.exists():
        if checksum_path.exists():
            raise BundleError("Checksum exists without its wheel.")
        if allow_missing_wheel:
            return None
        raise BundleError(f"Missing bundled wheel: {wheel_path}. Run scripts/sync_wheel.py first.")
    if not checksum_path.is_file():
        raise BundleError(f"Missing wheel checksum: {checksum_path}")

    identity = inspect_wheel(wheel_path)
    expected_checksum_line = f"{identity.sha256}  {EXPECTED_WHEEL_FILENAME}\n"
    try:
        checksum_text = checksum_path.read_text(encoding="ascii")
    except UnicodeError as error:
        raise BundleError("Wheel checksum is not ASCII.") from error
    if checksum_text != expected_checksum_line:
        raise BundleError("Wheel checksum does not match the bundled artifact.")
    return identity
