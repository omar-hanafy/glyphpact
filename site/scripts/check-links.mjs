/**
 * Link and metadata check over the built site.
 *
 * The failure this exists to prevent is base-path rot. The site deploys under
 * /glyphpact/, so a single hand-written href="/flutter/" works perfectly in
 * development and 404s in production. That class of bug is invisible in review
 * and trivial to catch mechanically.
 *
 * Also verifies that every page carries the metadata search engines and social
 * cards need, and that the sitemap lists the pages with absolute URLs.
 *
 * Run after a build:
 *   node scripts/check-links.mjs              internal links and metadata
 *   node scripts/check-links.mjs --external   additionally HEAD every external URL
 */

import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';

const DIST = 'dist';
const configuredBase = process.env.SITE_BASE ?? '/glyphpact';
const BASE =
  configuredBase === '/' ? '' : `/${configuredBase.replace(/^\/+|\/+$/g, '')}`;
const ORIGIN = (process.env.SITE_ORIGIN ?? 'https://omar-hanafy.github.io').replace(/\/+$/, '');
const checkExternal = process.argv.includes('--external');

const failures = [];
const warnings = [];
const notes = [];

if (!existsSync(DIST)) {
  console.error(`No ${DIST}/ directory. Run the build first.`);
  process.exit(1);
}

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const allFiles = walk(DIST).map((f) => f.replace(/\\/g, '/'));
const htmlFiles = allFiles.filter((f) => extname(f) === '.html');

/** Does a site-absolute path resolve to something we actually built? */
function resolves(pathname) {
  const rel = pathname.startsWith(BASE) ? pathname.slice(BASE.length) : pathname;
  const clean = rel.split('#')[0].split('?')[0];
  const candidates = [
    `${DIST}${clean}`,
    `${DIST}${clean}index.html`,
    `${DIST}${clean}/index.html`,
    `${DIST}${clean}.html`,
  ].map((p) => p.replace(/\/{2,}/g, '/'));
  return candidates.some((c) => allFiles.includes(c));
}

const externalUrls = new Set();

for (const file of htmlFiles) {
  const html = readFileSync(file, 'utf8');
  const page = file.replace(`${DIST}`, '') || '/';

  /* ------------------------------------------------------------- metadata */

  const title = html.match(/<title>([\s\S]*?)<\/title>/i)?.[1]?.trim();
  if (!title) failures.push(`${page}: missing <title>.`);

  const desc = html.match(/<meta\s+name="description"\s+content="([^"]*)"/i)?.[1];
  if (!desc) failures.push(`${page}: missing meta description.`);
  else if (desc.length < 50 || desc.length > 320) {
    warnings.push(`${page}: meta description is ${desc.length} characters.`);
  }

  const canonical = html.match(/<link\s+rel="canonical"\s+href="([^"]*)"/i)?.[1];
  if (!canonical) failures.push(`${page}: missing canonical link.`);
  else if (!canonical.startsWith(`${ORIGIN}${BASE}`)) {
    failures.push(`${page}: canonical "${canonical}" is not an absolute URL under ${ORIGIN}${BASE}.`);
  }

  for (const prop of ['og:title', 'og:description', 'og:url', 'og:image']) {
    const value = html.match(new RegExp(`<meta\\s+property="${prop}"\\s+content="([^"]*)"`, 'i'))?.[1];
    if (!value) failures.push(`${page}: missing ${prop}.`);
    else if (prop.endsWith(':url') || prop.endsWith(':image')) {
      if (!value.startsWith('https://')) {
        failures.push(`${page}: ${prop} must be absolute, got "${value}".`);
      } else if (prop.endsWith(':image') && !resolves(new URL(value).pathname)) {
        failures.push(`${page}: ${prop} points at ${value}, which was not built.`);
      }
    }
  }

  const twitterImage = html.match(/<meta\s+name="twitter:image"\s+content="([^"]*)"/i)?.[1];
  if (!twitterImage) failures.push(`${page}: missing twitter:image.`);
  else if (!resolves(new URL(twitterImage).pathname)) {
    failures.push(`${page}: twitter:image points at ${twitterImage}, which was not built.`);
  }

  const appleTouchTag = html.match(/<link\b[^>]*rel="apple-touch-icon"[^>]*>/i)?.[0];
  const appleTouchIcon = appleTouchTag?.match(/\shref="([^"]+)"/i)?.[1];
  if (!appleTouchTag || !appleTouchIcon) {
    failures.push(`${page}: missing apple-touch-icon.`);
  } else {
    if (!/\ssizes="180x180"/i.test(appleTouchTag)) {
      failures.push(`${page}: apple-touch-icon must declare sizes="180x180".`);
    }
    if (!resolves(appleTouchIcon)) {
      failures.push(`${page}: apple-touch-icon points at ${appleTouchIcon}, which was not built.`);
    }
  }

  /* --------------------------------------------------------------- headings */

  const h1s = [...html.matchAll(/<h1[^>]*>/gi)];
  if (h1s.length !== 1) failures.push(`${page}: expected exactly one <h1>, found ${h1s.length}.`);

  // No skipped heading levels.
  const levels = [...html.matchAll(/<h([1-6])[^>]*>/gi)].map((m) => Number(m[1]));
  let previous = 0;
  for (const level of levels) {
    if (previous && level > previous + 1) {
      failures.push(`${page}: heading order skips a level (h${previous} to h${level}).`);
    }
    previous = level;
  }

  /* ------------------------------------------------------------ duplicate ids */

  // Section heading ids and FAQ entry ids share a namespace, so a collision is
  // easy to introduce and breaks both aria-labelledby and fragment links.
  const seenIds = new Map();
  for (const m of html.matchAll(/\sid="([^"]+)"/g)) {
    seenIds.set(m[1], (seenIds.get(m[1]) ?? 0) + 1);
  }
  for (const [id, count] of seenIds) {
    if (count > 1) failures.push(`${page}: duplicate id "${id}" appears ${count} times.`);
  }

  // Every aria-labelledby / aria-describedby target must exist on the page.
  for (const m of html.matchAll(/aria-(?:labelledby|describedby)="([^"]+)"/g)) {
    for (const target of m[1].split(/\s+/)) {
      if (!seenIds.has(target)) {
        failures.push(`${page}: aria reference "${target}" has no matching element id.`);
      }
    }
  }

  /* ------------------------------------------------------------ structured */

  const structuredData = [];
  for (const block of html.matchAll(
    /<script type="application\/ld\+json">([\s\S]*?)<\/script>/gi,
  )) {
    try {
      const parsed = JSON.parse(block[1]);
      structuredData.push(parsed);
      if (!parsed['@context'] || !parsed['@type']) {
        failures.push(`${page}: a JSON-LD block is missing @context or @type.`);
      }
    } catch (error) {
      failures.push(`${page}: invalid JSON-LD (${error.message}).`);
    }
  }

  if (file === `${DIST}/index.html`) {
    const software = structuredData.find((block) => block['@type'] === 'SoftwareApplication');
    const website = structuredData.find((block) => block['@type'] === 'WebSite');

    if (!software) {
      failures.push(`${page}: missing SoftwareApplication structured data.`);
    } else {
      if (
        typeof software.image !== 'string' ||
        !software.image.startsWith('https://') ||
        !resolves(new URL(software.image).pathname)
      ) {
        failures.push(`${page}: SoftwareApplication image must resolve to a built absolute URL.`);
      }
      if (
        !Array.isArray(software.sameAs) ||
        !software.sameAs.some((value) => typeof value === 'string' && value.startsWith('https://'))
      ) {
        failures.push(`${page}: SoftwareApplication sameAs must name an HTTPS project identity.`);
      }
    }

    if (
      !website ||
      !Array.isArray(website.sameAs) ||
      !website.sameAs.some((value) => typeof value === 'string' && value.startsWith('https://'))
    ) {
      failures.push(`${page}: WebSite sameAs must name an HTTPS project identity.`);
    }
  }

  /* ------------------------------------------------------------------ links */

  for (const match of html.matchAll(/(?:href|src)="([^"]+)"/gi)) {
    const href = match[1];

    if (href.startsWith('http://') || href.startsWith('https://')) {
      if (!href.startsWith(ORIGIN)) externalUrls.add(href);
      continue;
    }
    if (href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('data:')) continue;

    if (!href.startsWith('/')) {
      warnings.push(`${page}: relative link "${href}" - prefer path() so the base path applies.`);
      continue;
    }

    // The load-bearing check: a root-relative link that skips the base path.
    if (BASE && !href.startsWith(`${BASE}/`) && href !== BASE) {
      failures.push(
        `${page}: link "${href}" is missing the ${BASE} base path. ` +
          'It will 404 in production. Build internal URLs with path() from src/site.config.ts.',
      );
      continue;
    }

    if (!resolves(href)) {
      failures.push(`${page}: internal link "${href}" does not resolve to a built file.`);
    }
  }
}

notes.push(`Checked ${htmlFiles.length} page(s) for metadata, headings, JSON-LD, and links.`);

/* -------------------------------------------------------------- sitemap */

const sitemapIndex = `${DIST}/sitemap-index.xml`;
if (!existsSync(sitemapIndex)) {
  failures.push('No sitemap-index.xml was generated.');
} else {
  const sitemaps = allFiles.filter((f) => /sitemap-\d+\.xml$/.test(f));
  const urls = sitemaps.flatMap((f) =>
    [...readFileSync(f, 'utf8').matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]),
  );

  if (!urls.length) failures.push('The sitemap contains no URLs.');

  for (const url of urls) {
    if (!url.startsWith(`${ORIGIN}${BASE}`)) {
      failures.push(`Sitemap URL "${url}" is not absolute under ${ORIGIN}${BASE}.`);
    }
  }

  const expected = ['/', '/stable-codepoints/', '/flutter/', '/vs/icomoon/', '/vs/fluttericon/'];
  for (const route of expected) {
    if (!urls.some((u) => u === `${ORIGIN}${BASE}${route}`)) {
      failures.push(`Sitemap is missing the expected route ${route}.`);
    }
  }

  // Non-pages must stay out of the sitemap.
  for (const url of urls) {
    if (url.includes('/og/') || url.includes('favicon') || url.includes('/404')) {
      failures.push(`Sitemap should not list the asset or error route "${url}".`);
    }
  }

  notes.push(`Sitemap lists ${urls.length} absolute URL(s).`);
}

/* ------------------------------------------------------------- externals */

if (checkExternal) {
  notes.push(`Checking ${externalUrls.size} external URL(s)...`);
  const results = await Promise.all(
    [...externalUrls].map(async (url) => {
      try {
        let res = await fetch(url, { method: 'HEAD', redirect: 'follow' });
        // Some hosts reject HEAD; retry with a ranged GET before believing it.
        if (res.status === 405 || res.status === 403 || res.status === 404) {
          res = await fetch(url, { method: 'GET', redirect: 'follow', headers: { Range: 'bytes=0-2048' } });
        }
        return { url, ok: res.ok || res.status === 206, status: res.status };
      } catch (error) {
        return { url, ok: false, status: error.message };
      }
    }),
  );
  for (const result of results) {
    if (!result.ok) warnings.push(`External link unreachable (${result.status}): ${result.url}`);
  }
  notes.push(`${results.filter((r) => r.ok).length}/${results.length} external URL(s) reachable.`);
} else {
  notes.push(`Found ${externalUrls.size} external URL(s); pass --external to verify them.`);
}

/* ---------------------------------------------------------------- report */

for (const note of notes) console.log(`  ok  ${note}`);
for (const warning of warnings) console.log(`  !   ${warning}`);

if (failures.length) {
  console.error(`\ncheck:links failed with ${failures.length} problem(s):\n`);
  for (const failure of failures) console.error(`  x  ${failure}`);
  console.error('');
  process.exit(1);
}

console.log('\ncheck:links passed.\n');
