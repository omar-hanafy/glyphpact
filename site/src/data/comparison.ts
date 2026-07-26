/**
 * Comparison data - one structured source for every comparison surface.
 *
 * Ground rules, applied to every cell below:
 *
 * - Each claim was checked against current first-party documentation or
 *   current behaviour on the date in `VERIFIED_ON`, and carries the source
 *   that supports it.
 * - Ambiguity is preserved. Where a project's behaviour depends on how it is
 *   used, the cell says `conditional` and explains the condition, rather than
 *   being forced into a yes or no.
 * - Where first-party documentation is silent, the cell says `undocumented`.
 *   That is a statement about the documentation, not an accusation.
 * - Nothing here is written to make an alternative look worse than it is.
 *   IcoMoon processes artwork in the browser without uploading it, and this
 *   data says so, because it is true and it matters.
 */

export const VERIFIED_ON = '2026-07-25';

export type Support =
  /** Supported directly, without user-maintained bookkeeping. */
  | 'yes'
  /** Not supported. */
  | 'no'
  /** Supported only under a stated condition. */
  | 'conditional'
  /** Achievable, but the user maintains the mapping by hand. */
  | 'manual'
  /** First-party documentation does not state a behaviour either way. */
  | 'undocumented';

export interface Source {
  label: string;
  href: string;
}

export interface Cell {
  support: Support;
  /** Short cell text. Must stand on its own when read out of context. */
  value: string;
  /** The condition, caveat, or evidence. Rendered under the value. */
  note?: string;
}

export interface Tool {
  id: string;
  name: string;
  /** What the tool fundamentally is. Shown under the column header. */
  kind: string;
  href: string;
  sources: Source[];
  isSelf?: boolean;
}

export interface Dimension {
  id: string;
  label: string;
  /** Why this dimension matters. Keeps the table from reading as scorekeeping. */
  why: string;
  cells: Record<string, Cell>;
}

export const tools: Tool[] = [
  {
    id: 'glyphpact',
    name: 'GlyphPact',
    kind: 'Local CLI compiler',
    href: 'https://github.com/omar-hanafy/glyphpact',
    isSelf: true,
    sources: [
      { label: 'README', href: 'https://github.com/omar-hanafy/glyphpact#readme' },
      {
        label: 'SVG profile',
        href: 'https://github.com/omar-hanafy/glyphpact/blob/v1.0.0/docs/svg-profile.md',
      },
    ],
  },
  {
    id: 'icomoon',
    name: 'IcoMoon',
    kind: 'Browser app',
    href: 'https://icomoon.io/',
    sources: [
      { label: 'IcoMoon docs', href: 'https://icomoon.io/docs' },
      { label: 'IcoMoon FAQ', href: 'https://icomoon.io/old-faq' },
    ],
  },
  {
    id: 'fluttericon',
    name: 'FlutterIcon.com',
    kind: 'Hosted Fontello fork',
    href: 'https://www.fluttericon.com/',
    sources: [
      { label: 'FlutterIcon', href: 'https://www.fluttericon.com/' },
      { label: 'polyicon source', href: 'https://github.com/ilikerobots/polyicon' },
      { label: 'Fontello API', href: 'https://github.com/fontello/fontello' },
    ],
  },
  {
    id: 'icon_font_generator',
    name: 'icon_font_generator',
    kind: 'Dart CLI',
    href: 'https://pub.dev/packages/icon_font_generator',
    sources: [
      { label: 'pub.dev page', href: 'https://pub.dev/packages/icon_font_generator' },
      { label: 'Source', href: 'https://github.com/ScerIO/icon_font_generator' },
    ],
  },
  {
    id: 'fantasticon',
    name: 'Fantasticon',
    kind: 'Node CLI',
    href: 'https://github.com/tancredi/fantasticon',
    sources: [{ label: 'README', href: 'https://github.com/tancredi/fantasticon' }],
  },
];

export const dimensions: Dimension[] = [
  {
    id: 'stable-codepoints',
    label: 'Existing codepoints survive a pack change',
    why: 'If an assignment moves, shipped application code renders the wrong glyph.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: 'Committed lock file',
        note: '`iconfont.lock.json` is generated into the output tree and read on every later build. Removed icons leave a tombstone in `retired` instead of freeing the codepoint.',
      },
      icomoon: {
        support: 'conditional',
        value: 'If you re-import selection.json',
        note: 'The FAQ states the codes of previously selected glyphs will not change when the previous `selection.json` is imported, and that "newly imported SVGs do not have any codes assigned to them", so re-importing and reselecting everything "would most likely result in different codes". Stability depends on keeping that file and importing it every time.',
      },
      fluttericon: {
        support: 'conditional',
        value: 'If you re-import config.json',
        note: 'Inherits the Fontello session model, where the downloaded `config.json` records each glyph code and can be imported again. Stability depends on retaining and re-importing that file.',
      },
      icon_font_generator: {
        support: 'undocumented',
        value: 'No documented mechanism',
        note: 'Neither the pub.dev page nor the README documents a lock file or persistence mechanism. Published examples show codepoints running sequentially from `0xe000` in glyph order.',
      },
      fantasticon: {
        support: 'manual',
        value: 'Hand-pinned in config',
        note: 'A `codepoints` map in the config assigns fixed values, so stability is achievable. The map is maintained by hand rather than generated and updated by the tool.',
      },
    },
  },
  {
    id: 'ci-check',
    label: 'CI can prove committed output is current',
    why: 'Generated artifacts drift from sources silently unless something fails the build.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: '`--check` exits 3 when stale',
        note: 'Rebuilds a candidate artifact set and compares it without rewriting the owned output tree. Verified: exit 0 on current output, exit 3 after a source edit.',
      },
      icomoon: {
        support: 'no',
        value: 'No CLI to run in CI',
        note: 'The documentation describes a browser application, with no command-line interface.',
      },
      fluttericon: {
        support: 'no',
        value: 'No first-party staleness check',
        note: 'The third-party `fontello-cli` can install a config against a host, but neither it nor the site offers a check that fails on stale committed output.',
      },
      icon_font_generator: {
        support: 'no',
        value: 'Not offered',
        note: 'The CLI generates output. No check or verify mode is documented.',
      },
      fantasticon: {
        support: 'no',
        value: 'Not offered',
        note: 'No check or verify mode is documented.',
      },
    },
  },
  {
    id: 'local',
    label: 'Runs entirely on your machine',
    why: 'Unreleased or licensed artwork often cannot leave the building.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: 'Local CLI, no network step',
        note: 'A Python command-line compiler. No website step, no project service, no server that receives artwork.',
      },
      icomoon: {
        support: 'yes',
        value: 'In-browser, not uploaded',
        note: 'The FAQ states that "when you import SVG files or when you generate a font, everything happens in your browser", and that SVGs are not uploaded unless you opt into paid project storage. It also documents working offline after preloading the generate pages.',
      },
      fluttericon: {
        support: 'no',
        value: 'Hosted service session',
        note: 'A hosted web application in the Fontello lineage, where the font configuration is posted to the service and held in a server-side session.',
      },
      icon_font_generator: {
        support: 'yes',
        value: 'Local CLI',
        note: 'Runs locally. Described as written fully in Dart with no external dependency.',
      },
      fantasticon: {
        support: 'yes',
        value: 'Local CLI',
        note: 'Runs locally on Node.',
      },
    },
  },
  {
    id: 'deterministic',
    label: 'Byte-identical rebuilds',
    why: 'Non-reproducible artifacts turn every rebuild into an unreviewable diff.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: 'Same bytes across worker counts',
        note: 'Same inputs, config, lock, and compiler version produce byte-identical artifacts. Verified: identical SHA-256 across default, 1, and 4 worker processes.',
      },
      icomoon: { support: 'undocumented', value: 'Not documented' },
      fluttericon: { support: 'undocumented', value: 'Not documented' },
      icon_font_generator: { support: 'undocumented', value: 'Not documented' },
      fantasticon: { support: 'undocumented', value: 'Not documented' },
    },
  },
  {
    id: 'fidelity',
    label: 'Explicit policy for SVG a font cannot hold',
    why: 'An icon font stores monochrome coverage. Something has to decide what happens to a blur or a half-transparent fill.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: 'Two policy axes, both strict by default',
        note: '`lossy` and `unrepresentable` each default to `error`. Approximations and omissions require explicit opt-in and are reported as typed, coded issues.',
      },
      icomoon: { support: 'undocumented', value: 'No published policy' },
      fluttericon: { support: 'undocumented', value: 'No published policy' },
      icon_font_generator: {
        support: 'undocumented',
        value: 'No published policy',
        note: 'Exposes `--[no-]normalize` and `--[no-]ignore-shapes` flags, but documents no classification of unsupported input.',
      },
      fantasticon: { support: 'undocumented', value: 'No published policy' },
    },
  },
  {
    id: 'flutter',
    label: 'Generates a Flutter IconData API',
    why: 'Hand-written IconData constants are the place codepoint drift actually bites.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: 'Const class, tree-shakeable',
        note: 'Emits a `@staticIconProvider` class of `const IconData` values, with `fontPackage` handling and optional layered-icon widgets.',
      },
      icomoon: {
        support: 'no',
        value: 'No Dart output',
        note: 'Documented export targets are Font, SVG, SVG sprite, Elm, React, Vue, Tiles, PNG, Favicon, and CSH.',
      },
      fluttericon: {
        support: 'yes',
        value: 'Dart icon class',
        note: 'Purpose-built for Flutter: exports a font plus a Dart icon class.',
      },
      icon_font_generator: {
        support: 'yes',
        value: 'Dart icon class',
        note: 'Generates an OTF font and a Flutter-compatible class.',
      },
      fantasticon: {
        support: 'no',
        value: 'Web asset types only',
        note: 'Generates CSS, SCSS, SASS, HTML, JSON, and TypeScript. No Dart or Flutter output.',
      },
    },
  },
  {
    id: 'web-output',
    label: 'Web assets: WOFF2 and CSS',
    why: 'The honest place GlyphPact is behind. If you need a web icon font today, these tools already do it.',
    cells: {
      glyphpact: {
        support: 'no',
        value: 'OpenType/CFF only',
        note: 'Emits a `.otf` font and the lock registry. No WOFF, no WOFF2, no generated CSS. Web use means converting the font and writing the CSS yourself.',
      },
      icomoon: {
        support: 'yes',
        value: 'Fonts plus CSS',
        note: 'Documented export targets include a web font pack and further asset types.',
      },
      fluttericon: {
        support: 'yes',
        value: 'Web font pack',
        note: 'Fontello lineage produces web font formats alongside the Flutter output.',
      },
      icon_font_generator: { support: 'no', value: 'OTF only' },
      fantasticon: {
        support: 'yes',
        value: 'WOFF2, WOFF, TTF, EOT, SVG, CSS',
        note: 'Documented font formats are EOT, WOFF2, WOFF, TTF, and SVG, with CSS, SCSS, SASS, HTML, JSON, and TS asset types.',
      },
    },
  },
  {
    id: 'attribution',
    label: 'Generates an attribution record',
    why: 'Third-party icon licences usually require attribution, and audits ask for it.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: '`ATTRIBUTION.md` per build',
        note: 'Carries declared author, licence, and source URL per glyph, and counts emitted icons with no declared provenance. It does not verify ownership.',
      },
      icomoon: { support: 'undocumented', value: 'Not documented' },
      fluttericon: {
        support: 'conditional',
        value: 'Bundled-pack licences',
        note: 'Ships licence information for the open-source packs it bundles. Not an attribution file generated from your own artwork metadata.',
      },
      icon_font_generator: { support: 'no', value: 'Not offered' },
      fantasticon: { support: 'no', value: 'Not offered' },
    },
  },
  {
    id: 'runtime',
    label: 'Required runtime',
    why: 'A toolchain you do not already run is a toolchain you have to maintain.',
    cells: {
      glyphpact: { support: 'yes', value: 'Python 3.10+', note: 'Dart 3+ only to consume the generated provider.' },
      icomoon: { support: 'yes', value: 'A browser' },
      fluttericon: { support: 'yes', value: 'A browser', note: 'Optional third-party CLI needs Node.' },
      icon_font_generator: { support: 'yes', value: 'Dart' },
      fantasticon: { support: 'yes', value: 'Node 16+' },
    },
  },
  {
    id: 'agent',
    label: 'Coding-agent integration',
    why: 'Icon work is increasingly delegated, and an agent needs typed results rather than screenshots.',
    cells: {
      glyphpact: {
        support: 'yes',
        value: 'Local stdio MCP server',
        note: 'Claude Code and Codex can install the full plugin. Other stdio MCP clients can configure the published server directly. It exposes four tools plus the config, report, and inner CLI-result schemas.',
      },
      icomoon: { support: 'no', value: 'Not offered' },
      fluttericon: { support: 'no', value: 'Not offered' },
      icon_font_generator: { support: 'no', value: 'Not offered' },
      fantasticon: { support: 'no', value: 'Not offered' },
    },
  },
];

/** Column sets for the narrower per-page tables. */
export const columnSets = {
  home: ['glyphpact', 'icomoon', 'fluttericon', 'icon_font_generator', 'fantasticon'],
  icomoon: ['glyphpact', 'icomoon'],
  fluttericon: ['glyphpact', 'fluttericon', 'icon_font_generator'],
} as const;

export const toolById = (id: string): Tool => {
  const found = tools.find((t) => t.id === id);
  if (!found) throw new Error(`Unknown comparison tool: ${id}`);
  return found;
};

/** Human-readable label for a support level, used for the accessible name. */
export const supportLabel: Record<Support, string> = {
  yes: 'Supported',
  no: 'Not supported',
  conditional: 'Conditional',
  manual: 'Manual',
  undocumented: 'Not documented',
};
