/**
 * FAQ content - one source for the visible answers and the FAQPage JSON-LD.
 *
 * `answer` holds plain-text paragraphs so the rendered HTML and the structured
 * data are generated from the identical strings and cannot drift. Follow-up
 * links live in `more`, which is rendered visibly but is deliberately not part
 * of the schema answer, keeping the structured text clean.
 *
 * Every answer is written to survive extraction. An answer engine quoting one
 * of these in isolation should still be quoting something true and complete,
 * which is why each one restates its subject instead of relying on the
 * question or the surrounding page.
 */

import { site } from '../site.config';

export interface FaqEntry {
  id: string;
  question: string;
  answer: string[];
  more?: { label: string; href: string };
  /** Which pages render this entry. */
  pages: Array<'home' | 'bulk' | 'codepoints' | 'flutter' | 'mcp' | 'icomoon' | 'fluttericon'>;
}

export const faq: FaqEntry[] = [
  {
    id: 'why-codepoints-change',
    question: 'Why do icon-font codepoints change when icons are added?',
    answer: [
      'A generator that derives codepoints from the current source list can shift assignments when the list changes. Insert an icon whose name sorts early, rename a file, or start a new browser import without restoring the previous project, and every icon after that point can move.',
      'The font itself is then internally consistent, so nothing fails at build time. The breakage appears in application code that still refers to the old value: a constant for a back arrow keeps pointing at U+E001 while U+E001 now contains a different glyph. The icon renders, it is simply the wrong picture.',
    ],
    pages: ['home', 'codepoints'],
  },
  {
    id: 'how-glyphpact-keeps-stable',
    question: 'How does GlyphPact keep existing codepoints stable?',
    answer: [
      'GlyphPact writes a lock file, iconfont.lock.json, into the generated output directory and reads it back on every later build. Each entry records the source path, the Dart name, the assigned codepoint, and content hashes. An assignment already in the lock is reused as-is; only genuinely new sources draw new codepoints from the end of the allocated range.',
      'Removing an icon does not free its codepoint. The entry moves to a "retired" list in the same file, leaving a permanent tombstone so the value is never handed to a different picture. Restoring the source later reactivates the original slot, and a unique content-preserving rename keeps both its codepoint and its generated Dart name.',
    ],
    more: { label: 'How the lock file works', href: '/stable-codepoints/' },
    pages: ['home', 'codepoints'],
  },
  {
    id: 'commit-lock',
    question: 'Should iconfont.lock.json be committed to Git?',
    answer: [
      'Yes. The lock file is the codepoint ABI for the generated font, and it only protects existing assignments if the next build can read the same file the previous build wrote. Committing it alongside the generated font, Dart provider, report, and attribution file is the intended workflow.',
      'If the lock is deleted or lost, the next build has no record of prior assignments and will allocate codepoints from scratch, which can reassign icons even when no source file changed.',
    ],
    pages: ['home', 'codepoints', 'flutter'],
  },
  {
    id: 'ci-staleness',
    question: 'How can CI detect stale generated icon output?',
    answer: [
      'Run the same GlyphPact build with the --check flag: glyphpact --config icon_font.json --check. It rebuilds a candidate artifact set from the current sources and compares it against the committed output without rewriting the owned output directory.',
      'Exit code 0 means the committed artifacts are current, and exit code 3 means they are stale, which fails the job. Adding --json produces a stable machine-readable result at schema version 2 so a workflow can inspect glyph counts, the active policy, and typed issues rather than treating every successful run as equivalent.',
    ],
    more: { label: 'CI setup for Flutter projects', href: '/flutter/' },
    pages: ['home', 'flutter'],
  },
  {
    id: 'offline',
    question: 'Does GlyphPact work offline?',
    answer: [
      'Yes. GlyphPact is a command-line compiler that runs locally. Compiling a pack involves no network access: there is no website step, no project service, and no server that receives your artwork. Installation itself needs the network once, to fetch the package.',
    ],
    pages: ['home', 'mcp', 'icomoon'],
  },
  {
    id: 'uploads',
    question: 'Does GlyphPact upload my SVG files anywhere?',
    answer: [
      'No. Source SVGs are read from disk and all compilation happens in the local process. Nothing is transmitted, so unreleased or licence-restricted artwork never leaves the machine or the build runner.',
    ],
    pages: ['home', 'mcp', 'icomoon'],
  },
  {
    id: 'outside-flutter',
    question: 'Can I use the generated font outside Flutter?',
    answer: [
      'Partly, and the boundary is worth stating precisely. The compiled OpenType/CFF font, the lock registry, and iconfont.report.json are framework-neutral. Report schema v3 records every emitted glyph name and codepoint plus the font family, file, hashes, layered metadata, and remaining allocation capacity, so it is the stable lower-level input for another language\'s generator.',
      'The generated high-level binding is Dart-specific: it contains const Flutter IconData values and, when enabled, a name-keyed catalog companion. GlyphPact does not generate a ready-made web, React, Android, or JavaScript binding.',
      'A non-Flutter project can consume the font and generate its own integration from the report. That custom output must live outside GlyphPact\'s owned output directory and needs its own drift check.',
    ],
    pages: ['home', 'flutter'],
  },
  {
    id: 'css-woff2',
    question: 'Does GlyphPact generate CSS or WOFF2?',
    answer: [
      'No. GlyphPact emits an OpenType/CFF .otf font, the lock registry, a machine-readable report, an attribution file, and a Dart provider. It does not produce WOFF, WOFF2, or any stylesheet, and it has no browser integration.',
      'Using the font on the web is possible but manual: convert the .otf to WOFF2 with a separate tool and write the @font-face rule and class names yourself. Active glyph names and codepoints can be read from iconfont.report.json. If a turnkey web icon-font pipeline is what you need, a web-first generator is the better fit today.',
    ],
    pages: ['home'],
  },
  {
    id: 'unsupported-svg',
    question: 'What happens when an SVG contains features an icon font cannot represent?',
    answer: [
      'The source is classified rather than silently approximated. An icon-font glyph stores monochrome alpha coverage, so features like a Gaussian blur filter or surviving fractional transparency have no faithful representation in it.',
      'GlyphPact sorts each source into one of three outcomes. Lossless sources are normalized and emitted automatically. Deterministically approximable sources are emitted only when the lossy policy is set to convert, and are reported as a typed lossy issue. Sources with no faithful conversion are omitted only when the unrepresentable policy is set to skip, and are reported as a typed unrepresentable issue.',
      'Both policies default to error, so by default an affected build fails and prints the diagnostic code, the file, and the feature instead of shipping a wrong-looking icon. Malformed, unsafe, or unknown input, and exhausted resource limits, always fail regardless of policy.',
    ],
    more: { label: 'The versioned SVG profile', href: site.links.svgProfile },
    pages: ['home'],
  },
  {
    id: 'icomoon-alternative',
    question: 'Is GlyphPact an IcoMoon alternative?',
    answer: [
      'Yes, when the requirement is a repository-managed Flutter icon pipeline. Both tools import SVG folders, run locally or offline, and can generate Flutter output.',
      'IcoMoon is stronger for visual editing, bundled libraries, and broad output formats. Its current app exports a Dart class for Flutter, imports files and folders, and can replace glyphs by matching names while retaining their metadata.',
      'GlyphPact is different at the build boundary. It provides a first-party local compiler, a committed codepoint lock with permanent tombstones, typed SVG audit results, byte-identical rebuilds, and a --check command that fails CI when generated output is stale.',
    ],
    more: { label: 'Full IcoMoon comparison', href: '/vs/icomoon/' },
    pages: ['home', 'icomoon'],
  },
  {
    id: 'icomoon-codepoints',
    question: 'Does IcoMoon change codepoints when you add icons?',
    answer: [
      'IcoMoon can preserve existing codepoints. Its current app stores a project in icomoon.json and offers Replace by Matching Names so updated artwork can keep the matching glyph metadata. The older app used selection.json.',
      'That stability depends on retaining and restoring the project, then using the matching-name update workflow correctly. GlyphPact stores the mapping in iconfont.lock.json inside the generated output and reads it automatically on every build.',
      'GlyphPact addresses the same problem differently: the codepoint registry is a file inside the repository, and a --check run in CI fails when committed output no longer matches its sources.',
    ],
    pages: ['icomoon'],
  },
  {
    id: 'fluttericon-alternative',
    question: 'Is GlyphPact a FlutterIcon.com alternative?',
    answer: [
      'Yes, for teams that want icon generation inside the repository and the build. Both produce a Flutter icon font plus a Dart icon class from SVG sources.',
      'The models differ. FlutterIcon.com is a hosted web application in the Fontello lineage: pick or drop icons in a browser session, download a bundle, and keep the config.json if you want the same codepoints next time. It also lets you browse and mix from a set of bundled open-source icon packs, which GlyphPact does not do at all.',
      'GlyphPact is a local CLI with no hosted component. The codepoint registry is committed to the repository, rebuilds are byte-identical, unsupported SVG features are classified against a published policy instead of being approximated silently, and a --check run in CI fails when committed artifacts drift from their sources.',
    ],
    more: { label: 'Full FlutterIcon comparison', href: '/vs/fluttericon/' },
    pages: ['fluttericon'],
  },
  {
    id: 'bulk-folder-to-icondata',
    question: 'Can GlyphPact convert a folder of SVGs to Flutter IconData?',
    answer: [
      'Yes. Point the GlyphPact CLI at an SVG directory and choose an output directory and class name. One build emits an OpenType/CFF icon font, a const Flutter IconData provider, iconfont.lock.json, iconfont.report.json, and ATTRIBUTION.md.',
      'The generated output is meant to be committed. Later builds reuse the lock so adding another SVG batch does not renumber existing IconData constants.',
    ],
    more: { label: 'Bulk SVG workflow', href: '/bulk-svg-to-flutter-icons/' },
    pages: ['home', 'bulk'],
  },
  {
    id: 'bulk-recursive',
    question: 'Does GlyphPact scan nested SVG folders recursively?',
    answer: [
      'Yes. GlyphPact discovers .svg files recursively below the input directory and uses normalized relative paths as source identities. A pack can keep folders such as navigation, status, and social without flattening them before compilation.',
      'Run an audit first when a large pack comes from several designers. The report groups typed findings by source file, and the same directory can then be compiled through the CLI or MCP server.',
    ],
    pages: ['bulk'],
  },
  {
    id: 'hundred-thousand-icons',
    question: 'Can GlyphPact convert 100,000 SVGs into one icon font?',
    answer: [
      'No single GlyphPact font can contain 100,000 usable icon glyphs. GlyphPact enforces the OpenType ceiling of 65,534 usable glyphs per font. The default BMP private use range is smaller, with 6,400 lifetime assignments, and tombstones consume slots because codepoints are never reused.',
      'A complete supplementary private use range provides up to 65,534 assignments. Larger catalogues must be divided into independently versioned fonts. File count alone does not predict build time, so benchmark the real SVG corpus instead of relying on a headline throughput claim.',
    ],
    pages: ['bulk'],
  },
  {
    id: 'fluttericon-compound-path',
    question: 'What does FlutterIcon.com’s “convert to compound path manually” warning mean?',
    answer: [
      'FlutterIcon.com may show: “If image looks not as expected please convert to compound path manually. Skipped tags and attributes: ...” It is an importer warning, not proof that the source SVG is invalid.',
      'An icon font needs glyph outlines. Expanding strokes and flattening artwork into paths can help when tags or attributes cannot be translated, but it is not a universal fix for every valid SVG or every fill-rule problem. Test the generated font in Flutter, not only the browser preview.',
    ],
    more: { label: 'Tested FlutterIcon.com comparison', href: '/vs/fluttericon/' },
    pages: ['bulk', 'fluttericon'],
  },
  {
    id: 'fontello-alternative',
    question: 'Is GlyphPact a Fontello alternative?',
    answer: [
      'Yes for local, repository-controlled Flutter icon generation. GlyphPact compiles your SVG sources locally, keeps codepoints in a committed lock, audits unsupported SVG features, and checks generated output in CI.',
      'Fontello is a better fit when you want its browser catalogue and web-font export workflow. Fontello also has a developer API and third-party CLI tooling, so the distinction is not “automation versus no automation.” The distinction is a first-party repository build and staleness check.',
    ],
    pages: ['bulk', 'fluttericon'],
  },
  {
    id: 'icon-font-or-svg',
    question: 'Should I use an icon font or flutter_svg?',
    answer: [
      'Use an icon font when the artwork is monochrome, is reused throughout the interface, and should behave like text through IconData, IconTheme, and font subsetting. Use flutter_svg when an image needs multiple colours, gradients, filters, animation, or other SVG semantics that a monochrome glyph cannot preserve.',
      'For mixed packs, audit first and keep unsuitable artwork as SVG assets. Converting every file is not the goal; choosing a faithful runtime representation is.',
    ],
    pages: ['bulk', 'flutter'],
  },
  {
    id: 'icon-catalog',
    question: 'Can Flutter code enumerate every generated icon by name?',
    answer: [
      'Yes. Set catalog to true in the checked-in GlyphPact config. The existing generated Dart file then includes a separate AppIconsCatalog companion whose static const byName map contains every emitted IconData in ascending codepoint order. Packs with partial-alpha icons also receive layeredByName for their lossless layered descriptors.',
      'The config switch alone does not enlarge a release. If the catalog is unreachable, Flutter removes it and subsets the font from the individual provider constants the app uses. Reachable byName retains every base glyph, while reachable layeredByName retains those icons\' fallbacks and layer-font glyphs. A catalog referenced only from tests has no release cost.',
      'For another collection shape, order, variable name, or language, use report schema v3 as a build-time input. Report codepoints are 0x... strings, and codepointsRemaining plus rangeUtilization expose the current allocation headroom. Generated Dart should reference the reported provider constants rather than constructing IconData dynamically, and custom generated files must stay outside GlyphPact\'s owned output directory.',
    ],
    more: { label: 'Flutter integration details', href: '/flutter/' },
    pages: ['home', 'flutter'],
  },
  {
    id: 'tree-shaking',
    question: 'Does the generated Flutter code support icon tree shaking?',
    answer: [
      'The generated provider follows the contract Flutter requires for it. It is emitted as an abstract final class annotated @staticIconProvider and has only static const members, including the private font-family strings and IconData values. Partial-alpha packs apply the same annotation to their static-const layered descriptor provider so directly referenced descriptors can be subset independently.',
      'Whether subsetting runs is decided by the release build and can be disabled with --no-tree-shake-icons. The optional catalog companion has only static const members and carries the provider annotation so declaration-only catalogs in this or another package are ignored. Reachable map values remain visible: an unused catalog is removed, while a reachable byName map retains every base glyph it enumerates.',
    ],
    more: { label: 'Flutter integration details', href: '/flutter/' },
    pages: ['flutter'],
  },
  {
    id: 'large-packs',
    question: 'How many icons can one GlyphPact font hold?',
    answer: [
      'The practical ceiling for a single font is 65,534 usable glyphs, which is an OpenType glyph-indexing limit that GlyphPact enforces as a per-build icon ceiling.',
      'The allocation range is the tighter constraint in the default configuration. The BMP private use area, U+E000 through U+F8FF, provides 6,400 lifetime slots, and active icons and tombstones both consume them because codepoints are never recycled. Report schema v3 exposes codepointsRemaining and rangeUtilization, and builds warn at 80% utilization. For a larger catalogue, start a new stable font in a supplementary private use area with --start-codepoint 0xF0000, which provides 65,534 slots. Never change the start codepoint of an established lock; beyond one range, split the catalogue into independently versioned fonts.',
    ],
    pages: ['flutter'],
  },
  {
    id: 'agents',
    question: 'Which coding agents can use the GlyphPact MCP server?',
    answer: [
      'Any client that can start a local stdio MCP server can use GlyphPact. The documented setups cover Claude Code, Codex, Antigravity, Cursor, JetBrains AI Assistant, VS Code, Zed, Windsurf, and Gemini CLI. Clients use different JSON keys, TOML sections, and config locations, but each one launches the same published glyphpact-mcp process.',
      'The server has four tools: audit an SVG file or directory and page a stable local findings snapshot, build the output declared by a config, check generated output for staleness without rewriting the artifact set, and page a published report. It also exposes the config, report, and inner CLI-result JSON Schemas as MCP resources.',
    ],
    more: { label: 'MCP installation and tool reference', href: '/mcp/' },
    pages: ['home', 'mcp'],
  },
  {
    id: 'mcp-plugin-or-manual',
    question: 'Should I install the full plugin or configure MCP manually?',
    answer: [
      'Use the full plugin in Claude Code or Codex when you want the MCP server plus the sync-flutter-svg-icons skill. The skill guides project inspection, codepoint compatibility, Flutter font wiring, analysis, target builds, launch, and rendered glyph comparison. The host starts the bundled MCP server after plugin installation.',
      'Use manual MCP configuration in another stdio client, or when you only want the four MCP tools and three schema resources. A manual entry runs the published glyphpact[mcp] package and does not install the plugin skill.',
    ],
    more: { label: 'Full plugin payload', href: site.links.pluginGuide },
    pages: ['mcp'],
  },
  {
    id: 'mcp-updates',
    question: 'Does a manual MCP configuration update automatically?',
    answer: [
      'No. The manual snippets pin a specific GlyphPact release so the command keeps running the version you chose. When a new release is available, replace the version in the client configuration and restart or reload the server.',
      'Marketplace plugin updates and manual MCP version changes are separate. Installing the full plugin in Claude Code or Codex keeps the MCP server inside the plugin update path; a pasted client configuration remains under the user\'s control.',
    ],
    pages: ['mcp'],
  },
];

export const faqFor = (page: FaqEntry['pages'][number]) => faq.filter((f) => f.pages.includes(page));
