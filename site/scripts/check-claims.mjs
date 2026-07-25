/**
 * Guardrail against publishing claims the product does not support.
 *
 * The brief for this site forbids advertising output GlyphPact does not
 * generate. Prose is easy to get right once and easy to break later, so the
 * rule is enforced mechanically instead of by memory.
 *
 * Two kinds of check:
 *
 *  1. The advertised release version must correspond to a real git tag. This
 *     stops the site announcing a release that was never published, which is
 *     the most damaging inaccuracy it could carry.
 *  2. Built HTML must not claim unsupported outputs. Some forbidden terms
 *     legitimately appear while *denying* support ("no WOFF2", "does not
 *     generate CSS"), so each match is checked against its surrounding
 *     sentence for a negation before being reported.
 *
 * Run after a build: node scripts/check-claims.mjs
 */

import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { execSync } from 'node:child_process';

const DIST = 'dist';
const failures = [];
const notes = [];

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
      failures.push(
        `The site advertises v${version}, but no matching git tag "v${version}" exists. ` +
          `Tags found: ${tagList.join(', ') || '(none)'}. ` +
          'The site must only advertise a published release.',
      );
    } else {
      notes.push(`Advertised release v${version} matches git tag v${version}.`);
    }
  }

  // The install command must pin the same version.
  if (!configSource.includes('.git@${TAG}') && !configSource.includes(`.git@v${version}`)) {
    failures.push('The install command does not appear to pin the advertised release tag.');
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
