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
    title: 'GlyphPact - deterministic SVG-to-icon-font compiler',
    description:
      'GlyphPact compiles a directory of SVG files into a validated OpenType icon font, a committed codepoint registry, and a const Flutter IconData API. Existing codepoints stay fixed when the pack changes.',
    short: 'Overview',
    inNav: false,
  },
  codepoints: {
    href: '/stable-codepoints/',
    nav: 'Stable codepoints',
    title: 'Why icon-font codepoints change, and how to stop it',
    description:
      'Icon-font codepoints shift because most generators assign them from the current file list. A committed codepoint registry makes assignments permanent, so an existing IconData never renders a different glyph.',
    short: 'stable codepoints',
    inNav: true,
  },
  flutter: {
    href: '/flutter/',
    nav: 'Flutter',
    title: 'Flutter icon font generator with stable IconData codepoints',
    description:
      'Compile SVG files into an OpenType font and a tree-shakeable const Flutter IconData class. Covers pubspec registration, font packages, layered icons, semantics, and CI staleness checks.',
    short: 'Flutter integration',
    inNav: true,
  },
  mcp: {
    href: '/mcp/',
    nav: 'MCP',
    title: 'Install and use the GlyphPact MCP server',
    description:
      'Install GlyphPact MCP in Claude Code, Codex, Antigravity, Cursor, JetBrains, VS Code, Zed, Windsurf, Gemini CLI, and other local stdio clients. Includes setup, tools, prompts, workflow, and safety boundaries.',
    short: 'MCP integration',
    inNav: true,
  },
  vsIcomoon: {
    href: '/vs/icomoon/',
    nav: 'vs IcoMoon',
    title: 'GlyphPact vs IcoMoon: a fair comparison',
    description:
      'IcoMoon is a browser icon-font app that keeps codepoints when you re-import selection.json. GlyphPact is a CLI compiler that keeps them in a committed lock file a CI job can verify. What each is actually for.',
    short: 'IcoMoon comparison',
    inNav: true,
  },
  vsFlutterIcon: {
    href: '/vs/fluttericon/',
    nav: 'vs FlutterIcon',
    title: 'GlyphPact vs FlutterIcon.com: a fair comparison',
    description:
      'FlutterIcon.com is a hosted Fontello fork that generates Flutter icon fonts from a browser session. GlyphPact is a local CLI compiler with a committed codepoint registry. Where each one fits.',
    short: 'FlutterIcon comparison',
    inNav: true,
  },
};

export const navRoutes = (Object.keys(routes) as RouteKey[]).filter((k) => routes[k].inNav);
