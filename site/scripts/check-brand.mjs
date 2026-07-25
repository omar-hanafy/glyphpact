/**
 * Brand artwork check.
 *
 * The identity is meant to be replaceable (see brand/README.md), which means a
 * future rebrand will edit these files without necessarily re-testing them.
 * This script asserts the contracts the site actually depends on, so a
 * replacement mark that breaks one of them fails loudly instead of shipping.
 *
 * Run: node scripts/check-brand.mjs
 */

import { readFileSync, existsSync } from 'node:fs';
import sharp from 'sharp';

const MARK = '../brand/glyphpact-mark.svg';
const ICON = '../brand/glyphpact-icon.svg';

const failures = [];
const notes = [];

function read(path) {
  if (!existsSync(path)) {
    failures.push(`Missing brand file: ${path}`);
    return null;
  }
  return readFileSync(path, 'utf8');
}

const mark = read(MARK);
const icon = read(ICON);

/* --------------------------------------------------- structural contracts */

if (mark) {
  // BrandMark.astro inlines this and relies on colour inheritance.
  if (!mark.includes('currentColor')) {
    failures.push(
      `${MARK} must paint with currentColor so the inlined mark inherits text colour.`,
    );
  } else {
    notes.push('Mark uses currentColor.');
  }

  // The two-tone treatment keys off this class. Its absence is allowed - the
  // mark then degrades to mono - but it is worth reporting either way.
  if (mark.includes('gp-mark__node')) {
    notes.push('Mark exposes .gp-mark__node for the two-tone treatment.');
  } else {
    notes.push('Mark has no .gp-mark__node; two-tone will degrade to mono (allowed).');
  }

  const viewBox = mark.match(/viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"/);
  if (!viewBox) {
    failures.push(`${MARK} needs a viewBox starting at 0 0 so CSS sizing behaves predictably.`);
  } else if (viewBox[1] !== viewBox[2]) {
    failures.push(
      `${MARK} viewBox must be square (found ${viewBox[1]}x${viewBox[2]}); the site sizes the mark on both axes equally.`,
    );
  } else {
    notes.push(`Mark viewBox is square (${viewBox[1]}x${viewBox[2]}).`);
  }
}

if (icon) {
  // Served as /favicon.svg, where currentColor has nothing to inherit from.
  if (!/fill="#[0-9A-Fa-f]{3,8}"/.test(icon)) {
    failures.push(
      `${ICON} needs explicit fill colours; it is loaded as an image, where currentColor resolves to black.`,
    );
  } else {
    notes.push('Standalone icon uses explicit colours.');
  }

  if (icon.includes('currentColor')) {
    failures.push(
      `${ICON} must not use currentColor: as a favicon it has no inherited colour to resolve against.`,
    );
  }
}

/* ------------------------------------------------- legibility at 16 pixels */

/**
 * Rasterise down to favicon size and confirm the mark still resolves into
 * distinct shapes rather than mush. A mark that collapses to near-uniform
 * pixels is unusable in a browser tab, which is the one place it cannot be
 * substituted.
 */
async function checkLegibility(path, label) {
  if (!existsSync(path)) return;

  const png = await sharp(readFileSync(path), { density: 512 })
    .resize(16, 16, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    // Flatten onto mid-grey before measuring. The mono mark paints with
    // currentColor, which rasterises to black on a transparent ground, so its
    // shape lives entirely in the alpha channel; measuring raw RGB would report
    // a perfectly uniform image for a perfectly legible mark. Compositing over
    // a known mid-tone makes both variants measurable the same way.
    .flatten({ background: { r: 128, g: 128, b: 128 } })
    .raw()
    .toBuffer({ resolveWithObject: true });

  const { data, info } = png;
  const channels = info.channels;
  const luma = [];
  for (let i = 0; i < data.length; i += channels) {
    luma.push(0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]);
  }

  const mean = luma.reduce((a, b) => a + b, 0) / luma.length;
  const variance = luma.reduce((a, b) => a + (b - mean) ** 2, 0) / luma.length;
  const stdDev = Math.sqrt(variance);

  // An unrecognisable 16px render has almost no luminance spread. A mark with
  // real figure/ground separation comfortably clears this.
  const MIN_STDDEV = 12;
  if (stdDev < MIN_STDDEV) {
    failures.push(
      `${label} does not resolve at 16px: luminance standard deviation ${stdDev.toFixed(1)} ` +
        `is below the ${MIN_STDDEV} threshold. Thicken the strokes or simplify the mark.`,
    );
  } else {
    notes.push(`${label} resolves at 16px (luminance spread ${stdDev.toFixed(1)}).`);
  }
}

await checkLegibility(ICON, 'Standalone icon');
await checkLegibility(MARK, 'Mark');

/* ----------------------------------------------------------------- report */

for (const note of notes) console.log(`  ok  ${note}`);

if (failures.length) {
  console.error(`\ncheck:brand failed with ${failures.length} problem(s):\n`);
  for (const failure of failures) console.error(`  x  ${failure}`);
  console.error('');
  process.exit(1);
}

console.log('\ncheck:brand passed.\n');
