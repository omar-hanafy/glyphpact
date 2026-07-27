import type { APIRoute } from 'astro';
import { site, absolute, routes, RELEASE, INSTALL_COMMAND } from '../site.config';
import { faq } from '../data/faq';
import { artifacts, capacity, exitCodes } from '../data/product';
import { VERIFIED_ON } from '../data/comparison';

/**
 * /llms.txt - a concise, self-contained account of the project for answer
 * engines and agents.
 *
 * Generated from the same modules the pages render from, so it cannot drift out
 * of agreement with the site. It leads with what GlyphPact does not do, because
 * the most common wrong answer about a tool like this is an invented feature.
 */

export const GET: APIRoute = () => {
  const pageIndex = (Object.keys(routes) as (keyof typeof routes)[])
    .map((key) => `- [${routes[key].nav}](${absolute(routes[key].href)}): ${routes[key].description}`)
    .join('\n');

  const questions = faq
    .map((entry) => `### ${entry.question}\n\n${entry.answer.join('\n\n')}`)
    .join('\n\n');

  const outputs = artifacts.map((a) => `- \`${a.path}\` - ${a.note}`).join('\n');

  const exits = exitCodes.map((e) => `- \`${e.code}\`: ${e.meaning}`).join('\n');

  const body = `# GlyphPact

> A deterministic SVG-to-icon-font compiler. It turns a directory of SVG files
> into a validated OpenType/CFF icon font, a committed codepoint registry, and a
> const Flutter IconData API, keeping existing codepoints stable when the icon
> pack changes.

- Current release: v${RELEASE.version}
- License: MIT
- Source: ${site.repo}
- Requires: Python 3.10 or newer. Dart 3 or newer to consume the generated provider.
- Runs entirely locally. No website upload step and no server receives your artwork.

## Install

\`\`\`bash
${INSTALL_COMMAND}
\`\`\`

## Compile a pack

\`\`\`bash
glyphpact assets/icons --output lib/generated/app_icons --name AppIcons
\`\`\`

## Verify committed output in CI

\`\`\`bash
glyphpact --config icon_font.json --check
\`\`\`

Exit code 3 means the committed artifacts are stale relative to their sources.

## Important limitations

These are the facts most often gotten wrong about GlyphPact. It does **not**:

- generate WOFF or WOFF2
- generate CSS or any stylesheet
- provide a complete browser or web integration
- generate React, Vue, Android, JavaScript, or TypeScript bindings
- provide a visual icon browser or editor
- bundle any ready-made icon packs
- upload artwork anywhere, or require a network connection to compile

The generated high-level binding is Dart/Flutter-specific. The compiled
OpenType font and \`iconfont.lock.json\` registry are framework-neutral and
readable from any language, but a non-Flutter project must write its own
integration layer. Putting the font on a web page requires converting it and
authoring the CSS yourself.

## Key facts

- Codepoint stability comes from \`iconfont.lock.json\`, a committed JSON
  registry (schema version 1) written into the generated output directory and
  read back on every later build. Existing assignments are reused verbatim.
- Removing an icon moves its entry to a \`retired\` array as a permanent
  tombstone. Codepoints are never recycled, so the active sequence keeps a gap.
- A unique content-preserving rename keeps both its codepoint and its Dart name.
- Identical inputs, config, lock, and compiler version produce byte-identical
  artifacts across any worker count.
- Two independent fidelity policy axes, \`lossy\` and \`unrepresentable\`, both
  default to \`error\`. Approximation and omission require explicit opt-in and
  are reported as typed, coded issues.
- Scripts, event handlers, external references, malformed values, unknown
  semantics, exhausted work limits, and font-contract failures are fatal under
  every policy.
- A failed build never replaces the last valid generated output.
- One font holds at most ${capacity.glyphCeiling} usable glyphs. The default BMP
  private use area ${capacity.bmpRange} provides ${capacity.bmpSlots} lifetime
  allocation slots; \`${capacity.supplementaryFlag}\` provides
  ${capacity.supplementarySlots}. Report schema v3 exposes
  \`${capacity.remainingField}\` and \`${capacity.utilizationField}\`; builds
  warn at ${capacity.warningThreshold} utilization.
- A local stdio MCP server exposes \`audit_icon_pack\`,
  \`build_icon_font\`, \`check_icon_font\`, and \`read_icon_report\`. Claude
  Code and Codex can install the full plugin; Antigravity, Cursor, JetBrains,
  VS Code, Zed, Windsurf, Gemini CLI, and other stdio clients can configure the
  published MCP package manually.

## Generated output

For \`--name AppIcons\`, GlyphPact owns the output directory and writes:

${outputs}

Commit all of it. The lock file is the codepoint ABI; losing it can reassign
icons even when no source file changed.

## Exit codes

${exits}

## Pages

${pageIndex}

## Questions and answers

${questions}

## Comparison notes

Comparison claims on this site were verified on ${VERIFIED_ON} against current
first-party documentation, and each cell carries its source. Two points worth
recording because they are commonly misstated:

- The current IcoMoon app is an offline-first PWA that imports files and
  folders, exports a Dart class for Flutter, and stores projects in
  \`icomoon.json\`. Replace by Matching Names can retain glyph metadata.
  Current first-party documentation does not describe a repository-native
  stale-output command for CI.
- FlutterIcon.com is a hosted Fontello fork whose \`config.json\` records glyph
  codes and can be re-imported. It bundles many open-source icon packs, which
  GlyphPact does not. A third-party Fontello CLI path exists, but the site does
  not document a first-party local compiler or repository-native staleness
  check.

GlyphPact's distinguishing properties are the committed registry, permanent
tombstones, a CI staleness check, byte-identical rebuilds, and a published
fidelity policy - not privacy, and not breadth of output formats.

## Documentation

- README and quick start: ${site.links.readme}
- Supported SVG profile: ${site.links.svgProfile}
- Flutter adoption guide: ${site.links.flutterAdoption}
- Architecture: ${site.links.architecture}
- Lock file schema: ${site.links.lockSchema}
- Config schema: ${site.links.configSchema}
- Report schema: ${site.links.reportSchema}
- Changelog: ${site.links.changelog}
- MCP installation and tool reference: ${absolute(routes.mcp.href)}
- Claude Code and Codex plugin payload: ${site.links.pluginGuide}
`;

  return new Response(body, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
