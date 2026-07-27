/**
 * Verified product facts.
 *
 * These facts are checked against the current GlyphPact source, schemas, and
 * integration tests rather than copied from marketing prose. Historical
 * observed fixtures identify the exact release that produced them.
 */

/* ------------------------------------------------------- generated output */

export interface Artifact {
  path: string;
  note: string;
  /** Framework-neutral artifacts are highlighted; the Dart binding is not. */
  scope: 'universal' | 'flutter' | 'meta';
}

/**
 * The owned output tree for `--name AppIcons`, as observed. The coordination
 * lock is listed because it really appears, as a sibling of the output
 * directory rather than inside it - a detail the README calls out and a
 * `.gitignore` needs to know about.
 */
export const artifacts: Artifact[] = [
  {
    path: 'fonts/AppIcons.otf',
    note: 'Validated OpenType/CFF font. Framework-neutral.',
    scope: 'universal',
  },
  {
    path: 'iconfont.lock.json',
    note: 'Codepoint registry and provenance. Schema version 1. Commit this.',
    scope: 'universal',
  },
  {
    path: 'app_icons.dart',
    note: 'const Flutter IconData provider and optional name-keyed catalog. Dart-specific.',
    scope: 'flutter',
  },
  {
    path: 'layer_fonts/layer_*.otf',
    note: 'Optional solid-alpha paint-order layers, for icons that opt in.',
    scope: 'universal',
  },
  {
    path: 'iconfont.report.json',
    note: 'Deterministic build report and stable code-generation input. Schema version 3.',
    scope: 'meta',
  },
  {
    path: 'ATTRIBUTION.md',
    note: 'Declared artwork authorship, licences, and unattributed count.',
    scope: 'meta',
  },
  {
    path: '.glyphpact.json',
    note: 'Ownership marker. GlyphPact refuses to overwrite a directory without it.',
    scope: 'meta',
  },
];

/** Observed sibling of the output directory, not part of the owned tree. */
export const coordinationLock = '.app_icons.glyphpact.lock';

/* ---------------------------------------------------------- lock file diff */

export type DiffKind = 'meta' | 'hunk' | 'context' | 'add' | 'del' | 'hold';

export interface DiffLine {
  kind: DiffKind;
  text: string;
}

/**
 * A real `git diff` of iconfont.lock.json after adding four icons to a
 * two-icon pack.
 *
 * The point is what is *not* marked as changed. `actions/add.svg` sorts before
 * every pre-existing file, and `arrows/back.svg` is now the third source
 * alphabetically rather than the first - yet `back` still holds 0xE000. New
 * sources took 0xE002 upward. Not one existing assignment moved, so no shipped
 * IconData constant changed meaning.
 *
 * Reproduced from an actual run of GlyphPact v1.0.0. The 64-character SHA-256
 * values are abbreviated for width; nothing else is edited.
 */
export const lockDiff: DiffLine[] = [
  { kind: 'meta', text: '--- a/lib/generated/app_icons/iconfont.lock.json' },
  { kind: 'meta', text: '+++ b/lib/generated/app_icons/iconfont.lock.json' },
  { kind: 'hunk', text: '@@ -9,6 +9,30 @@' },
  { kind: 'context', text: '   "unitsPerEm": 1000,' },
  { kind: 'context', text: '   "glyphs": [' },
  { kind: 'context', text: '     {' },
  { kind: 'add', text: '+      "source": "actions/add.svg",' },
  { kind: 'add', text: '+      "name": "actionsAdd",' },
  { kind: 'add', text: '+      "codepoint": "0xE002",' },
  { kind: 'add', text: '+      "sourceSha256": "a169819fd451...",' },
  { kind: 'add', text: '+      "matchTextDirection": false,' },
  { kind: 'add', text: '+      "geometrySha256": "2025c5f8dff2..."' },
  { kind: 'add', text: '+    },' },
  { kind: 'add', text: '+    {' },
  { kind: 'add', text: '+      "source": "arrows/arrow_down.svg",' },
  { kind: 'add', text: '+      "name": "arrowsArrowDown",' },
  { kind: 'add', text: '+      "codepoint": "0xE004",' },
  { kind: 'add', text: '+      "sourceSha256": "b6e87581e2f2...",' },
  { kind: 'add', text: '+      "matchTextDirection": false,' },
  { kind: 'add', text: '+      "geometrySha256": "48a927141186..."' },
  { kind: 'add', text: '+    },' },
  { kind: 'add', text: '+    {' },
  { kind: 'hold', text: '       "source": "arrows/back.svg",' },
  { kind: 'hold', text: '       "name": "back",' },
  { kind: 'hold', text: '       "codepoint": "0xE000",' },
  { kind: 'context', text: '       "sourceSha256": "38121f4ed8a1...",' },
  { kind: 'context', text: '       "matchTextDirection": true,' },
  { kind: 'context', text: '     },' },
  { kind: 'context', text: '     {' },
  { kind: 'hold', text: '       "source": "status/verified.svg",' },
  { kind: 'hold', text: '       "name": "verified",' },
  { kind: 'hold', text: '       "codepoint": "0xE001",' },
  { kind: 'context', text: '     },' },
  { kind: 'add', text: '+    {' },
  { kind: 'add', text: '+      "source": "status/warning.svg",' },
  { kind: 'add', text: '+      "name": "statusWarning",' },
  { kind: 'add', text: '+      "codepoint": "0xE005",' },
  { kind: 'add', text: '+    }' },
  { kind: 'context', text: '   ],' },
  { kind: 'context', text: '   "retired": []' },
];

/**
 * The same pack after `actions/archive.svg` is deleted. Observed output:
 * the codepoint is not reused, it is tombstoned, and 0xE003 becomes a
 * permanent gap in the active sequence.
 */
export const retiredExample = {
  activeAfterRemoval: [
    { source: 'actions/add.svg', codepoint: '0xE002' },
    { source: 'arrows/arrow_down.svg', codepoint: '0xE004' },
    { source: 'arrows/back.svg', codepoint: '0xE000' },
    { source: 'status/verified.svg', codepoint: '0xE001' },
    { source: 'status/warning.svg', codepoint: '0xE005' },
  ],
  retired: { source: 'actions/archive.svg', name: 'actionsArchive', codepoint: '0xE003' },
};

/* -------------------------------------------------------- fidelity policy */

export interface PolicyOutcome {
  lossy: 'error' | 'convert';
  unrepresentable: 'error' | 'skip';
  result: string;
  detail: string;
  isDefault?: boolean;
}

/** The two-axis policy matrix, as documented and as observed. */
export const policyMatrix: PolicyOutcome[] = [
  {
    lossy: 'error',
    unrepresentable: 'error',
    result: 'Lossless only',
    detail:
      'Anything that would be approximated or omitted fails the build instead. This is the default.',
    isDefault: true,
  },
  {
    lossy: 'convert',
    unrepresentable: 'error',
    result: 'Documented approximations allowed',
    detail:
      'Deterministic approximations are emitted and reported. Sources with no faithful conversion still fail.',
  },
  {
    lossy: 'error',
    unrepresentable: 'skip',
    result: 'Omissions allowed',
    detail:
      'Sources outside the profile are dropped and reported. Anything that would be approximated still fails.',
  },
  {
    lossy: 'convert',
    unrepresentable: 'skip',
    result: 'Approximations and omissions allowed',
    detail: 'Both are permitted, and every one is reported as a typed issue.',
  },
];

/**
 * A real three-source build, run under both policies.
 *
 * `back.svg` is a plain filled path. `ghost.svg` carries `opacity=".5"` that
 * survives to the final coverage. `blurred.svg` applies an feGaussianBlur
 * filter, which a monochrome outline cannot hold at all.
 */
export const policyRun = {
  strict: {
    command: 'glyphpact icons -o generated/app_icons -n AppIcons',
    exitCode: 2,
    lines: [
      {
        state: 'fail' as const,
        code: 'SVG_ATTRIBUTE_UNREPRESENTABLE',
        text: "blurred.svg: Attribute 'filter' has no supported static monochrome conversion.",
      },
      {
        state: 'fail' as const,
        code: 'SVG_ELEMENT_UNREPRESENTABLE',
        text: 'blurred.svg: <filter> has no supported static monochrome outline conversion.',
      },
      {
        state: 'lossy' as const,
        code: 'SVG_PARTIAL_ALPHA_APPROXIMATED',
        text: 'ghost.svg: Surviving fractional alpha was flattened to opaque coverage.',
      },
    ],
    summary: 'Nothing is published. The previous valid output is left untouched.',
  },
  permissive: {
    command:
      'glyphpact icons -o generated/app_icons -n AppIcons --lossy convert --unrepresentable skip',
    exitCode: 0,
    headline: 'Built 2 of 3 discovered icon(s): 1 lossless, 1 approximated, 1 skipped.',
    lines: [
      {
        state: 'fail' as const,
        code: 'SVG_ATTRIBUTE_UNREPRESENTABLE',
        text: "blurred.svg: Attribute 'filter' has no supported static monochrome conversion. (unrepresentable, skipped)",
      },
      {
        state: 'lossy' as const,
        code: 'SVG_PARTIAL_ALPHA_APPROXIMATED',
        text: 'ghost.svg: Surviving fractional alpha was flattened to opaque coverage. (lossy, converted)',
      },
    ],
    summary:
      'Every deviation is a typed record in the JSON result and the report, with a code, a classification, an action, and the feature responsible.',
  },
};

/** Not policy-addressable: fatal regardless of the flags above. */
export const alwaysFatal = [
  'Scripts and event handlers',
  'External references',
  'Malformed or non-finite values',
  'Unknown semantics',
  'Exhausted work limits',
  'Compiler or font-contract failures',
];

/* ----------------------------------------------------------- exit codes */

export const exitCodes = [
  { code: 0, meaning: 'Build or check succeeded' },
  { code: 1, meaning: 'Unexpected internal failure' },
  { code: 2, meaning: 'Config, input, policy, geometry, or font contract failed' },
  { code: 3, meaning: '--check found stale committed output' },
];

/* -------------------------------------------------------------- capacity */

export const capacity = {
  glyphCeiling: '65,534',
  bmpRange: 'U+E000 - U+F8FF',
  bmpSlots: '6,400',
  supplementarySlots: '65,534',
  supplementaryFlag: '--start-codepoint 0xF0000',
  warningThreshold: '80%',
  remainingField: 'codepointsRemaining',
  utilizationField: 'rangeUtilization',
};

/* -------------------------------------------------------- agent workflow */

export const mcpTools = [
  {
    name: 'audit_icon_pack',
    readOnly: true,
    text: 'Audit a file or directory once, then page a stable local snapshot of the findings instead of recompiling.',
  },
  {
    name: 'build_icon_font',
    readOnly: false,
    text: 'Build the output declared by a checked-in config.',
  },
  {
    name: 'check_icon_font',
    readOnly: false,
    text: 'Check committed output for staleness without rewriting generated artifacts.',
  },
  {
    name: 'read_icon_report',
    readOnly: true,
    text: 'Page through large machine-readable reports.',
  },
];

/** Exposed as MCP resources so an agent can validate what it reads. */
export const mcpResources = [
  'glyphpact://schema/config',
  'glyphpact://schema/report',
  'glyphpact://schema/cli-result',
];

/* ------------------------------------------------------- requirements */

export const requirements = {
  python: 'Python 3.10 or newer',
  dart: 'Dart 3 or newer, to consume the generated provider',
  schemas: 'CLI results use schema version 2, reports use schema version 3, and locks use schema version 1',
};
