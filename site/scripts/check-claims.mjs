/**
 * Guardrail against publishing claims the product does not support.
 *
 * The brief for this site forbids advertising output GlyphPact does not
 * generate. Prose is easy to get right once and easy to break later, so the
 * rule is enforced mechanically instead of by memory.
 *
 * Two kinds of check:
 *
 *  1. The advertised release version must correspond to a real git tag. Pull
 *     source previews may explicitly allow the package's unreleased version
 *     when it also has a changelog entry. The Pages workflow separately
 *     requires a successful Release run, exact tag SHA, and matching PyPI
 *     version before deployment.
 *  2. Built HTML must not claim unsupported outputs. Some forbidden terms
 *     legitimately appear while *denying* support ("no WOFF2", "does not
 *     generate CSS"), so each match is checked against its surrounding
 *     sentence for a negation before being reported.
 *
 * Run after a build: node scripts/check-claims.mjs
 */

import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, extname } from 'node:path';
import { execSync } from 'node:child_process';

const DIST = 'dist';
const failures = [];
const notes = [];
const allowUnreleasedVersion =
  process.env.GLYPHPACT_ALLOW_UNRELEASED_SITE_VERSION === '1';

/* ---------------------------------------- preserved comparison evidence */

const comparisonRoot = '../examples/fluttericon-evenodd-comparison';
const evidenceFiles = {
  'site screenshot': {
    path: 'public/images/comparisons/fluttericon-evenodd-comparison.png',
    sha256: '9f1e72cbfb94f606e4e2bd72c866117e995bff4ad98367505e3df8576074e894',
  },
  'public DEV article cover': {
    path: 'public/images/comparisons/fluttericon-glyphpact-cover-2x.png',
    sha256: '0660eb4340aed9c62d75a764efba63e9b60338d538fa204fe7b98d3c524d8d81',
  },
  'public DEV article comparison table': {
    path: 'public/images/comparisons/fluttericon-glyphpact-table-2x.png',
    sha256: '6b245024d7fa217a51f95f8de9ce225cc5187d6c08b865b6fbcc7625402f4813',
  },
  'article graphics golden test': {
    path: `${comparisonRoot}/test/article_graphics_test.dart`,
    sha256: '96610c53328819fdb0a408b035e30dcbe92ec06a8f0b898b03d06b5b30e490ba',
  },
  'expected DEV article cover': {
    path: `${comparisonRoot}/test/goldens/glyphpact-dev-cover-2x.png`,
    sha256: '0660eb4340aed9c62d75a764efba63e9b60338d538fa204fe7b98d3c524d8d81',
  },
  'expected DEV article comparison table': {
    path: `${comparisonRoot}/test/goldens/glyphpact-dev-comparison-v3-2x.png`,
    sha256: '6b245024d7fa217a51f95f8de9ce225cc5187d6c08b865b6fbcc7625402f4813',
  },
  '2x source screenshot': {
    path: `${comparisonRoot}/evidence/comparison-source-2x.png`,
    sha256: '6eef4debc424f8a1070bfaa9f01020e337da14044850a107768761cfd63503b2',
  },
  'FlutterIcon TTF': {
    path: `${comparisonRoot}/assets/fluttericon/fonts/FlutterIcon.ttf`,
    sha256: '895a37577544348719553dc43adf43ebdb95ccdc7f41655d8d8837f5e1459607',
  },
  'GlyphPact OTF': {
    path: `${comparisonRoot}/lib/generated/glyphpact/fonts/GlyphPactIcons.otf`,
    sha256: '26a6c71d001d303d31ebedee5857baa58c9399499f77f32e1925d71c556eeea0',
  },
  'public FlutterIcon TTF': {
    path: 'public/fonts/comparisons/FlutterIcon.ttf',
    sha256: '895a37577544348719553dc43adf43ebdb95ccdc7f41655d8d8837f5e1459607',
  },
  'public GlyphPact OTF': {
    path: 'public/fonts/comparisons/GlyphPactIcons.otf',
    sha256: '26a6c71d001d303d31ebedee5857baa58c9399499f77f32e1925d71c556eeea0',
  },
  'Chat Bold fixture SVG': {
    path: `${comparisonRoot}/assets/source_svg/Chat Bold.svg`,
    sha256: 'b5f61cf41dabe05e951a168e326c978e0df1629c41e290383ff0768c513f5596',
  },
  'public Chat Bold SVG': {
    path: 'public/images/comparisons/source-svg/chat-bold.svg',
    sha256: 'b5f61cf41dabe05e951a168e326c978e0df1629c41e290383ff0768c513f5596',
  },
  'Location Bold fixture SVG': {
    path: `${comparisonRoot}/assets/source_svg/Location Bold.svg`,
    sha256: 'e94b5515ac6fdd17f56cc6eac61505772b2f49485fecec53712076fa26b51246',
  },
  'public Location Bold SVG': {
    path: 'public/images/comparisons/source-svg/location-bold.svg',
    sha256: 'e94b5515ac6fdd17f56cc6eac61505772b2f49485fecec53712076fa26b51246',
  },
  'Mail Bold fixture SVG': {
    path: `${comparisonRoot}/assets/source_svg/Mail Bold.svg`,
    sha256: 'b349f283ef049a50afd848214e7cc52e9cb4dda2e291a590c2f53968855b62b9',
  },
  'public Mail Bold SVG': {
    path: 'public/images/comparisons/source-svg/mail-bold.svg',
    sha256: 'b349f283ef049a50afd848214e7cc52e9cb4dda2e291a590c2f53968855b62b9',
  },
};

for (const [label, evidence] of Object.entries(evidenceFiles)) {
  if (!existsSync(evidence.path)) {
    failures.push(`Missing preserved comparison ${label}: ${evidence.path}.`);
    continue;
  }
  const actual = createHash('sha256').update(readFileSync(evidence.path)).digest('hex');
  if (actual !== evidence.sha256) {
    failures.push(
      `Preserved comparison ${label} changed. Expected SHA-256 ${evidence.sha256}, got ${actual}.`,
    );
  }
}

const sourceFixtures = ['Chat Bold.svg', 'Location Bold.svg', 'Mail Bold.svg'];
for (const file of sourceFixtures) {
  const source = `${comparisonRoot}/assets/source_svg/${file}`;
  if (!existsSync(source)) {
    failures.push(`Missing comparison SVG fixture: ${source}.`);
    continue;
  }
  const svg = readFileSync(source, 'utf8');
  if (!svg.includes('fill-rule="evenodd"') || !svg.includes('clip-rule="evenodd"')) {
    failures.push(`${source} must retain its even-odd fill and clip rules.`);
  }
}

const comparisonReportPath =
  `${comparisonRoot}/lib/generated/glyphpact/iconfont.report.json`;
if (!existsSync(comparisonReportPath)) {
  failures.push(`Missing historical comparison report: ${comparisonReportPath}.`);
} else {
  const report = JSON.parse(readFileSync(comparisonReportPath, 'utf8'));
  if (
    report.generatorVersion !== '1.0.1' ||
    report.quality !== 'lossless' ||
    report.glyphCount !== 3 ||
    report.losslessGlyphCount !== 3 ||
    report.approximatedGlyphCount !== 0 ||
    report.skippedIconCount !== 0 ||
    report.issueCount !== 0
  ) {
    failures.push(
      'Historical comparison report must remain GlyphPact 1.0.1 with 3 lossless glyphs and 0 approximated, skipped, or reported issues.',
    );
  }
}

if (!failures.length) {
  notes.push('Preserved FlutterIcon comparison fixtures and hashes are intact.');
}

/* ------------------------------------------------- 1. version vs git tag */

const configSource = readFileSync('src/site.config.ts', 'utf8');
const versionMatch = configSource.match(/version:\s*'([^']+)'/);

if (!versionMatch) {
  failures.push('Could not find RELEASE.version in src/site.config.ts.');
} else {
  const version = versionMatch[1];
  let tags = '';
  try {
    tags = execSync('git tag --list', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  } catch {
    notes.push('git tags unavailable (shallow clone?); skipped the release-tag check.');
  }

  if (tags) {
    const tagList = tags.split('\n').map((t) => t.trim()).filter(Boolean);
    if (!tagList.includes(`v${version}`)) {
      if (allowUnreleasedVersion) {
        const pyproject = readFileSync('../pyproject.toml', 'utf8');
        const packageVersion = pyproject.match(/^version = "([^"]+)"$/m)?.[1];
        const changelog = readFileSync('../CHANGELOG.md', 'utf8');
        if (packageVersion !== version || !changelog.includes(`## ${version} -`)) {
          failures.push(
            `Unreleased site version v${version} must match pyproject.toml and ` +
              'have a dated CHANGELOG.md entry.',
          );
        } else {
          notes.push(
            `Source preview v${version} matches the source package and changelog; ` +
              'the production release tag is still required.',
          );
        }
      } else {
        failures.push(
          `The site advertises v${version}, but no matching git tag "v${version}" exists. ` +
            `Tags found: ${tagList.join(', ') || '(none)'}. ` +
            'The site must only advertise a published release.',
        );
      }
    } else {
      notes.push(`Advertised release v${version} matches git tag v${version}.`);
    }
  }

  if (!configSource.includes("INSTALL_COMMAND = 'uv tool install glyphpact'")) {
    failures.push('The public install command must be exactly "uv tool install glyphpact".');
  }
  if (configSource.includes('git+')) {
    failures.push('The public install command must resolve from PyPI, not a Git repository.');
  }

  const flutterSource = readFileSync('src/pages/flutter.astro', 'utf8');
  if (!flutterSource.includes('uv tool install glyphpact==${RELEASE.version}')) {
    failures.push('The Flutter CI example must pin the advertised PyPI release.');
  }
  if (flutterSource.includes('git+')) {
    failures.push('The Flutter CI example must install from PyPI, not a Git repository.');
  }
}

/* ------------------------------------------- 2. forbidden output claims */

/**
 * Affirmative claims of output GlyphPact does not produce.
 *
 * Matching whole constructions rather than bare keywords is what makes this
 * check usable. The site legitimately says "WOFF2" many times - in an FAQ
 * question, in a list of things it does not do, and in comparison cells
 * describing other tools. Only a claim shaped like "generates WOFF2" is a
 * problem, and even then the surrounding window is checked for a denial or a
 * competitor subject.
 */
const FORBIDDEN = [
  {
    pattern:
      /\b(generate|generates|emit|emits|output|outputs|produce|produces|export|exports|support|supports|include|includes|ship|ships|write|writes|provide|provides)\s+(?:a\s+|an\s+|the\s+|and\s+|,\s*)*(woff2?|css|scss|sass|stylesheets?|eot)\b/g,
    label: 'web font or stylesheet output',
  },
  {
    pattern: /\b(woff2?|css|stylesheet)\s+(output|support|generation|generator)\b/g,
    label: 'web font or stylesheet output',
  },
  {
    pattern: /\b(react|vue|angular|android|kotlin|swift|javascript|typescript|web)\s+bindings?\b/g,
    label: 'a binding GlyphPact does not generate',
  },
  {
    pattern:
      /\b(generate|generates|emit|emits|provide|provides)\s+(?:a\s+|an\s+|the\s+)?(react|vue|android|javascript|typescript)\b/g,
    label: 'a binding GlyphPact does not generate',
  },
  { pattern: /\bworks everywhere\b/g, label: 'unbounded portability claim' },
  { pattern: /\bworks (?:with|on) any (?:framework|platform|language)\b/g, label: 'unbounded portability claim' },
  { pattern: /\bcomplete (?:browser|web) integration\b/g, label: 'complete web integration claim' },
];

/**
 * Phrases that mark the surrounding text as denying the capability.
 *
 * Deliberately multi-word. An earlier version accepted bare cues like "never"
 * and "only", which appear all over this site - the headline alone contains
 * "should never move" - and they silently suppressed real violations. Every
 * entry here has to be a phrase that only shows up when something is being
 * ruled out.
 */
const NEGATIONS = [
  'does not',
  'do not',
  "doesn't",
  'did not',
  'will not',
  'cannot',
  "can't",
  'no woff',
  'no css',
  'no generated',
  'not generate',
  'never generates',
  'nor does',
  'neither ',
  'lacks',
  'without generating',
  'must not',
  'deliberately lacks',
  // The FAQ asks about these capabilities in order to deny them.
  'does glyphpact generate',
];

/**
 * Subtrees explicitly marked as describing third-party capabilities are
 * excluded wholesale, which is more reliable than trying to infer the subject
 * of a sentence from nearby product names. Bare names are a poor signal here:
 * the site navigation mentions IcoMoon on every page, so name-matching would
 * exempt anything near the top of any page.
 */
const THIRD_PARTY_ATTR = 'data-claims="third-party"';

/**
 * Reduce a built page to the prose that makes first-party claims: the contents
 * of <main>, minus any subtree marked as third-party.
 *
 * Restricting to <main> also removes the navigation and footer, which repeat on
 * every page and would otherwise sit inside the context window of anything near
 * the top of the document.
 */
function claimText(html) {
  const main = html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/i);
  let body = main ? main[1] : html;

  // Drop marked third-party subtrees. Figures do not nest here, so matching to
  // the next </figure> is sufficient and avoids a real HTML parser.
  body = body.replace(
    new RegExp(`<figure[^>]*${THIRD_PARTY_ATTR}[^>]*>[\\s\\S]*?</figure>`, 'gi'),
    ' ',
  );

  return body
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&[a-z]+;/gi, ' ')
    .replace(/\s+/g, ' ');
}

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (['.html', '.txt'].includes(extname(full))) out.push(full);
  }
  return out;
}

if (!existsSync(DIST)) {
  failures.push(`No ${DIST}/ directory. Run the build before checking claims.`);
} else {
  const files = walk(DIST);
  notes.push(`Scanned ${files.length} built HTML and text file(s) for unsupported claims.`);

  for (const file of files) {
    const raw = readFileSync(file, 'utf8');
    if (raw.includes('uv tool install git+')) {
      failures.push(`${file}: contains a legacy Git install command.`);
    }
  }

  /**
   * A character window around the match, rather than a sentence. Denials often
   * sit just outside sentence boundaries - a list of "it does not:" bullets, or
   * an FAQ answer beginning "No." after the question - and a window catches
   * those where sentence splitting does not.
   */
  const BEFORE = 320;
  const AFTER = 320;

  for (const file of files) {
    const raw = readFileSync(file, 'utf8');
    const text = (extname(file) === '.html' ? claimText(raw) : raw)
      .toLowerCase()
      // Markdown emphasis would otherwise hide a denial: llms.txt writes
      // "it does **not**:", and "does not" must still match.
      .replace(/\*/g, '');

    for (const { pattern, label } of FORBIDDEN) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(text)) !== null) {
        const at = match.index;
        const window = text.slice(Math.max(0, at - BEFORE), at + AFTER);

        if (NEGATIONS.some((n) => window.includes(n))) continue;

        failures.push(
          `${file}: possible unsupported claim of ${label}.\n` +
            `    Matched: "${match[0]}"\n` +
            `    Context: "...${text.slice(Math.max(0, at - 90), at + 120).trim()}..."`,
        );
      }
    }
  }
}

/* ----------------------------------------------------------------- report */

for (const note of notes) console.log(`  ok  ${note}`);

if (failures.length) {
  console.error(`\ncheck:claims failed with ${failures.length} problem(s):\n`);
  for (const failure of failures) console.error(`  x  ${failure}`);
  console.error('');
  process.exit(1);
}

console.log('\ncheck:claims passed.\n');
