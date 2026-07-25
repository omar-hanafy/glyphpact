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

export interface FaqEntry {
  id: string;
  question: string;
  answer: string[];
  more?: { label: string; href: string };
  /** Which pages render this entry. */
  pages: Array<'home' | 'codepoints' | 'flutter' | 'icomoon' | 'fluttericon'>;
}

export const faq: FaqEntry[] = [
  {
    id: 'why-codepoints-change',
    question: 'Why do icon-font codepoints change when icons are added?',
    answer: [
      'Most icon-font generators assign codepoints by walking the current set of source files and handing out values in order, starting from the beginning of a private use area such as U+E000. The assignment is a function of the file list, not a stored decision. Insert an icon whose name sorts early, rename a file, or reorder a selection, and every icon after that point shifts by one.',
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
    pages: ['home', 'icomoon'],
  },
  {
    id: 'uploads',
    question: 'Does GlyphPact upload my SVG files anywhere?',
    answer: [
      'No. Source SVGs are read from disk and all compilation happens in the local process. Nothing is transmitted, so unreleased or licence-restricted artwork never leaves the machine or the build runner.',
    ],
    pages: ['home', 'icomoon'],
  },
  {
    id: 'outside-flutter',
    question: 'Can I use the generated font outside Flutter?',
    answer: [
      'Partly, and the boundary is worth stating precisely. Two of the three outputs are framework-neutral: the compiled OpenType/CFF font is a standard .otf file that any OpenType consumer can use, and iconfont.lock.json is a documented JSON registry mapping each source file to its codepoint, which any language can read.',
      'The third output is not neutral. The generated high-level binding is a Dart file containing const Flutter IconData constants, and the flags that shape it are Dart-specific. There is no generated binding for any other platform.',
      'So a non-Flutter project can consume the font and read codepoints from the lock file, but it will be writing its own integration layer. GlyphPact does not currently ship a ready-made web, React, Android, or JavaScript integration.',
    ],
    pages: ['home', 'flutter'],
  },
  {
    id: 'css-woff2',
    question: 'Does GlyphPact generate CSS or WOFF2?',
    answer: [
      'No. GlyphPact emits an OpenType/CFF .otf font, the lock registry, a machine-readable report, an attribution file, and a Dart provider. It does not produce WOFF, WOFF2, or any stylesheet, and it has no browser integration.',
      'Using the font on the web is possible but manual: convert the .otf to WOFF2 with a separate tool and write the @font-face rule and class names yourself. Codepoints can be read from the lock file. If a turnkey web icon-font pipeline is what you need, a web-first generator is the better fit today.',
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
    more: { label: 'The versioned SVG profile', href: 'https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/docs/svg-profile.md' },
    pages: ['home'],
  },
  {
    id: 'icomoon-alternative',
    question: 'Is GlyphPact an IcoMoon alternative?',
    answer: [
      'For a repository-driven workflow, yes. For a general web icon workflow, not entirely.',
      'GlyphPact overlaps with IcoMoon in turning SVG files into an icon font, and it adds things a browser app cannot: a committed lock file that fixes codepoints, a --check mode that fails CI when generated output goes stale, byte-identical rebuilds, and a generated Flutter IconData API.',
      'IcoMoon does things GlyphPact does not. It exports web font formats and CSS along with React, Vue, and Elm components, it offers a visual editor for browsing and editing glyphs, and it processes artwork in the browser without uploading it. If the goal is a web icon font with a stylesheet, IcoMoon covers ground GlyphPact currently does not.',
    ],
    more: { label: 'Full IcoMoon comparison', href: '/vs/icomoon/' },
    pages: ['home', 'icomoon'],
  },
  {
    id: 'icomoon-codepoints',
    question: 'Does IcoMoon change codepoints when you add icons?',
    answer: [
      'Not if the previous session file is re-imported. IcoMoon documents that the codes of previously selected glyphs will not change when the selection.json file from an earlier download is imported back into the app.',
      'The condition matters, though. IcoMoon also documents that newly imported SVGs arrive with no codes assigned, so re-importing all artwork and reselecting it each time will most likely produce different codes. Stability therefore depends on retaining that file and importing it correctly on every future change, which is a human step in a browser session rather than something a build can verify.',
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
    id: 'tree-shaking',
    question: 'Does the generated Flutter code support icon tree shaking?',
    answer: [
      'The generated provider follows the contract Flutter requires for it. It is emitted as an abstract final class annotated @staticIconProvider, holding only const IconData values whose codepoint, font family, and font package are compile-time constants.',
      'That annotation exists so Flutter can statically verify no IconData is constructed dynamically, which is the condition its font-subsetting step needs. Whether subsetting actually runs is decided by your build: it applies to release builds and can be disabled with --no-tree-shake-icons. Passing non-constant data to Icon elsewhere in your app is what typically defeats it.',
    ],
    more: { label: 'Flutter integration details', href: '/flutter/' },
    pages: ['flutter'],
  },
  {
    id: 'large-packs',
    question: 'How many icons can one GlyphPact font hold?',
    answer: [
      'The practical ceiling for a single font is 65,534 usable glyphs, which is an OpenType glyph-indexing limit that GlyphPact enforces as a per-build icon ceiling.',
      'The allocation range is the tighter constraint in the default configuration. The BMP private use area, U+E000 through U+F8FF, provides 6,400 lifetime slots, and active icons and tombstones both consume them because codepoints are never recycled. For a larger catalogue, start allocation in a supplementary private use area with --start-codepoint 0xF0000, which provides 65,534 slots. Beyond that, split the catalogue into several independently versioned fonts.',
    ],
    pages: ['flutter'],
  },
  {
    id: 'agents',
    question: 'Can Claude Code or Codex drive GlyphPact directly?',
    answer: [
      'Yes. The repository ships an optional plugin for Claude Code and Codex that bundles the release wheel and starts a local stdio MCP server, without needing a source checkout or a global install.',
      'It exposes four tools: audit an SVG file or directory and page a stable local snapshot of the findings, build the output declared by a checked-in config, check committed output for staleness without rewriting artifacts, and page through large machine-readable reports. The config, report, and CLI-result JSON schemas are exposed as MCP resources so an agent can validate what it reads. The audit and report tools are annotated read-only, and the server runs locally over stdio.',
    ],
    more: { label: 'Plugin guide', href: 'https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/plugins/glyphpact/README.md' },
    pages: ['home'],
  },
];

export const faqFor = (page: FaqEntry['pages'][number]) => faq.filter((f) => f.pages.includes(page));
