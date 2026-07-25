# GlyphPact agent plugin

GlyphPact gives Claude Code and Codex the same deterministic SVG-to-Flutter
compiler through two surfaces:

- an MCP server for auditing, building, checking, and reading large icon-pack
  reports
- the `sync-flutter-svg-icons` skill for project wiring, compatibility,
  diagnostics, and rendered Flutter verification

The plugin bundles the exact `glyphpact` 1.0.1 wheel used by its MCP server.
It does not depend on a source checkout or a globally installed GlyphPact CLI.

## Requirements

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/) on `PATH`
- Flutter only when wiring or rendering generated artifacts
- Network access on the first MCP start so uv can resolve the pinned official
  Python MCP SDK, JSON Schema validator, and the wheel's declared dependencies;
  later starts reuse uv's cache

## Install

Add the public repository as a marketplace once, then install the plugin.

Claude Code:

```bash
claude plugin marketplace add omar-hanafy/glyphpact
claude plugin install glyphpact@glyphpact
```

Codex:

```bash
codex plugin marketplace add omar-hanafy/glyphpact
codex plugin add glyphpact@glyphpact
```

Start a new session after installation. Claude Code can also reload plugins in
the current session with `/reload-plugins`.

Do not add a second personal MCP configuration. The installed plugin starts the
bundled server automatically.

## Agent surfaces

The MCP server exposes:

- `audit_icon_pack`: compile once into disposable storage, then page and
  release a stable local findings snapshot without changing the project
- `build_icon_font`: publish the output declared by a checked-in config
- `check_icon_font`: prove that committed generated artifacts match their
  sources and config without rewriting generated artifacts
- `read_icon_report`: page through full diagnostics without flooding the
  agent's context

It also exposes the config, report, and CLI-result schemas as MCP resources.

When an audit has findings, follow `snapshot.id` and
`findings.nextOffset` to request later pages without recompiling the pack.
Release the snapshot through the same tool with `release_snapshot=true`.
Each page is capped at 500 findings and 1 MiB. A snapshot is capped at 64 MiB,
expires after 15 idle minutes or one hour of total age, and lives in a private
cache limited to 8 snapshots and 128 MiB total. Release promptly rather than
relying on expiry or oldest-snapshot eviction.

The skill guides the agent through the complete project workflow:

1. inspect the Flutter project and existing generated ABI
2. audit with strict defaults
3. request an explicit policy decision for every approximation or omission
4. build and check reproducibly
5. wire exact font families and artifact paths
6. analyze, build, launch, and visually compare the rendered glyphs

## Privacy and mutation boundary

GlyphPact runs locally. The MCP tools receive filesystem paths selected by the
agent and do not upload SVGs. `audit_icon_pack`, schema resources, and report
reads do not change project files. `check_icon_font` never rewrites generated
artifacts, but it may create the output parent directory and leaves the
persistent `.<output>.glyphpact.lock` coordination file.

`build_icon_font` writes only to the output directory declared by the supplied
config. GlyphPact refuses to replace a non-empty directory it does not own
unless the caller explicitly opts into `adopt_output`.

## Maintainer bundle workflow

Build the release wheel from the repository root, then synchronize that exact
artifact into the plugin:

```bash
SOURCE_DATE_EPOCH=0 uv build --wheel --out-dir dist
python plugins/glyphpact/scripts/sync_wheel.py \
  dist/glyphpact-1.0.1-py3-none-any.whl
python plugins/glyphpact/scripts/sync_wheel.py --check \
  dist/glyphpact-1.0.1-py3-none-any.whl
python plugins/glyphpact/scripts/verify_bundle.py
python plugins/glyphpact/scripts/validate_plugin.py
```

`sync_wheel.py` verifies the distribution name and version inside wheel
metadata, copies it atomically, and writes a matching SHA-256 file. It refuses
unexpected wheel files rather than deleting them.

During development, validate the manifest and skill before the wheel exists:

```bash
python plugins/glyphpact/scripts/verify_bundle.py --allow-missing-wheel
python /path/to/plugin-creator/scripts/validate_plugin.py plugins/glyphpact
python /path/to/skill-creator/scripts/quick_validate.py \
  plugins/glyphpact/skills/sync-flutter-svg-icons
```

Smoke-test the installed MCP surface using the pinned client SDK:

```bash
uv run --no-project --isolated \
  --with-requirements plugins/glyphpact/dist/mcp-requirements.txt \
  python plugins/glyphpact/scripts/smoke_mcp.py
```

Pass `--plugin-root` to test a copied plugin-cache fixture. The smoke test
expands the plugin-root variable exactly as a host does, starts the bundled
wheel, initializes an MCP client session, verifies all four public tools and
schema resources, and runs a lossless single-SVG audit through the packaged
protocol. It also proves that a multi-error audit returns one requested page
instead of flooding the client with the full failure set, remains stable after
the source fixture is removed, and can be released explicitly.

Run the bundled CLI directly when debugging a packaged release:

```bash
python plugins/glyphpact/scripts/run_glyphpact.py --version
```

## Support

If GlyphPact saves you time, you can
[support ongoing maintenance](https://buymeacoffee.com/omar.hanafy).
