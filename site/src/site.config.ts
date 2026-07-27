/**
 * Central site metadata, release facts, and URL construction.
 *
 * Two rules keep this file load-bearing rather than decorative:
 *
 * 1. No template hardcodes an origin or the `/glyphpact` base path. Internal
 *    links go through `path()`; anything a crawler or social card consumes
 *    goes through `absolute()`.
 * 2. Every product claim on the site traces to something in this repository.
 *    `RELEASE.version` is asserted against a real git tag by
 *    `scripts/check-claims.mjs`. The deployment workflow additionally requires
 *    a successful Release run, the exact released SHA, and the matching PyPI
 *    version. Source previews may use the matching source/changelog version
 *    before its tag exists.
 */

/** Configured in astro.config.mjs; Astro exposes it here. */
const ORIGIN = import.meta.env.SITE ?? 'https://omar-hanafy.github.io';

/** Astro normalises this to a leading and trailing slash, e.g. `/glyphpact/`. */
const BASE = import.meta.env.BASE_URL ?? '/';

/**
 * The release represented by this source snapshot.
 *
 * Deliberately explicit rather than read from src/glyphpact/version.py: the
 * source tree can carry an unreleased version bump. Production check:claims
 * fails if this value has no matching `v<version>` git tag, while deployment
 * also requires the successful package release. Source previews require it to
 * match pyproject.toml and a dated changelog entry.
 */
export const RELEASE = {
  version: '1.1.0',
  /** Verified by direct inspection of this repository on this date. */
  verifiedOn: '2026-07-27',
} as const;

const REPO = 'https://github.com/omar-hanafy/glyphpact';
const TAG = `v${RELEASE.version}`;

/** Link to a repository file, pinned to the release tag as the README does. */
export const repoFile = (p: string) => `${REPO}/blob/${TAG}/${p}`;
/** Link to a repository directory, pinned to the release tag. */
export const repoTree = (p: string) => `${REPO}/tree/${TAG}/${p}`;

export const site = {
  name: 'GlyphPact',
  /** Used as the `<title>` suffix and in structured data. */
  tagline: 'Deterministic SVG-to-icon-font compiler',
  origin: ORIGIN,
  repo: REPO,
  author: {
    name: 'Omar Hanafy',
    url: 'https://github.com/omar-hanafy',
  },
  license: 'MIT',
  links: {
    repo: REPO,
    support: 'https://buymeacoffee.com/omar.hanafy',
    issues: `${REPO}/issues`,
    releases: `${REPO}/releases`,
    readme: `${REPO}#readme`,
    changelog: repoFile('CHANGELOG.md'),
    license: repoFile('LICENSE'),
    security: repoFile('SECURITY.md'),
    contributing: repoFile('CONTRIBUTING.md'),
    notice: repoFile('NOTICE'),
    svgProfile: repoFile('docs/svg-profile.md'),
    flutterAdoption: repoFile('docs/flutter-adoption.md'),
    architecture: repoFile('docs/architecture.md'),
    benchmarking: repoFile('docs/benchmarking.md'),
    pluginGuide: repoFile('plugins/glyphpact/README.md'),
    examples: repoTree('examples'),
    flutterIconComparison:
      `${REPO}/tree/main/examples/fluttericon-evenodd-comparison`,
    layeredExample: repoFile('examples/layered_icon_font.json'),
    lockSchema: repoFile('schema/icon-font-lock.schema.json'),
    configSchema: repoFile('schema/icon-font-config.schema.json'),
    reportSchema: repoFile('schema/icon-font-report.schema.json'),
  },
} as const;

/** The install command shown across the site. Verified against README.md. */
export const INSTALL_COMMAND = 'uv tool install glyphpact';

/* ------------------------------------------------------------------ URLs */

/**
 * Build a base-aware root-relative path for an internal link.
 *
 * `path('/flutter/')` -> `/glyphpact/flutter/`
 * `path('/')`         -> `/glyphpact/`
 */
export function path(p = '/'): string {
  const base = BASE.endsWith('/') ? BASE.slice(0, -1) : BASE;
  const rest = p.startsWith('/') ? p : `/${p}`;
  const joined = `${base}${rest}`;
  return joined.startsWith('/') ? joined : `/${joined}`;
}

/**
 * Build an absolute URL. Required for canonical links, Open Graph, social
 * cards, structured data, and the sitemap - relative values break all five.
 */
export function absolute(p = '/'): string {
  return new URL(path(p), ORIGIN).href;
}

/* ---------------------------------------------------------------- routes */

export type RouteKey =
  | 'home'
  | 'bulk'
  | 'flutter'
  | 'mcp'
  | 'codepoints'
  | 'vsIcomoon'
  | 'vsFlutterIcon';

/**
 * Every indexable route, in one place. Drives navigation, breadcrumbs,
 * internal cross-links, and /llms.txt, so a new page cannot be added to the
 * site while staying invisible to any one of them.
 */
export const routes: Record<RouteKey, {
  href: string;
  /** Navigation label. */
  nav: string;
  /** Full page title, without the site-name suffix. */
  title: string;
  /** Meta description and the one-line summary in /llms.txt. */
  description: string;
  /** Short label for breadcrumbs and inline cross-links. */
  short: string;
  /** Shown in the header nav. */
  inNav: boolean;
}> = {
  home: {
    href: '/',
    nav: 'Overview',
    title: 'GlyphPact: local SVG-to-Flutter icon font compiler',
    description:
      'Compile SVG folders into validated icon fonts and const Flutter IconData with stable codepoints, explicit diagnostics, reproducible builds, CI, and MCP.',
    short: 'Overview',
    inNav: false,
  },
  bulk: {
    href: '/bulk-svg-to-flutter-icons/',
    nav: 'Bulk SVG',
    title: 'Bulk SVG to Flutter icons with a local CLI',
    description:
      'Compile SVG folders recursively into an OpenType icon font and const Flutter IconData. Keep codepoints stable, audit SVGs, and verify generated output in CI.',
    short: 'bulk SVG guide',
    inNav: true,
  },
  codepoints: {
    href: '/stable-codepoints/',
    nav: 'Stable codepoints',
    title: 'Add Flutter icons without changing existing codepoints',
    description:
      'Add new SVGs to a Flutter icon font without renumbering existing IconData. See how a committed lock handles growth from 3 icons to 5, 10, and 100.',
    short: 'stable codepoints',
    inNav: true,
  },
  flutter: {
    href: '/flutter/',
    nav: 'Flutter',
    title: 'Use a custom icon font in Flutter: pubspec, IconData, and CI',
    description:
      'Wire a generated OpenType icon font into Flutter with pubspec.yaml, const IconData, semantics, packages, tree shaking, and CI staleness checks.',
    short: 'Flutter integration',
    inNav: true,
  },
  mcp: {
    href: '/mcp/',
    nav: 'MCP',
    title: 'GlyphPact MCP server for SVG-to-Flutter icon automation',
    description:
      'Use GlyphPact from Codex, Claude Code, Cursor, and other MCP clients to audit SVG packs, build Flutter icon fonts, and check generated output locally.',
    short: 'MCP integration',
    inNav: true,
  },
  vsIcomoon: {
    href: '/vs/icomoon/',
    nav: 'vs IcoMoon',
    title: 'IcoMoon alternative for repository-managed Flutter icons',
    description:
      'Compare IcoMoon and GlyphPact for Flutter icon fonts: visual editing and broad exports versus a local compiler, committed codepoint lock, and CI checks.',
    short: 'IcoMoon comparison',
    inNav: true,
  },
  vsFlutterIcon: {
    href: '/vs/fluttericon/',
    nav: 'vs FlutterIcon',
    title: 'FlutterIcon.com alternative for local Flutter icon fonts',
    description:
      'A FlutterIcon.com alternative for local SVG compilation, stable codepoints, CI checks, and reproducible Flutter IconData without repeated browser exports.',
    short: 'FlutterIcon comparison',
    inNav: true,
  },
};

export const navRoutes = (Object.keys(routes) as RouteKey[]).filter((k) => routes[k].inNav);
