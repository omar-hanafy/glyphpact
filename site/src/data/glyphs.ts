/**
 * Glyph outlines used in the site's diagrams.
 *
 * These are the actual path data from the SVG fixtures compiled during
 * verification, on a 24x24 viewBox. `back` and `verified` are the checked-in
 * example icons from the repository; the rest were authored as real inputs for
 * the incremental-build run that produced the lock diff on this site.
 *
 * Keeping them here means the diagrams show the same shapes the codepoints in
 * the lock diff actually refer to.
 */

export interface Glyph {
  /** Generated Dart name, as GlyphPact derived it. */
  name: string;
  /** Source path within the pack. */
  source: string;
  /** Codepoint assigned by the observed build. */
  codepoint: string;
  path: string;
  fillRule?: 'evenodd';
  /** Accessible description of the shape. */
  label: string;
}

export const back: Glyph = {
  name: 'back',
  source: 'arrows/back.svg',
  codepoint: 'U+E000',
  path: 'M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.42-1.41L7.83 13H20v-2z',
  label: 'Left-pointing arrow',
};

export const verified: Glyph = {
  name: 'verified',
  source: 'status/verified.svg',
  codepoint: 'U+E001',
  path: 'M12 2l2.08 2.08 2.92-.42.42 2.92L19.5 8.66 18 11.2l1.5 2.54-2.08 2.08-.42 2.92-2.92-.42L12 20.4l-2.08-2.08-2.92.42-.42-2.92-2.08-2.08L6 11.2 4.5 8.66l2.08-2.08L7 3.66l2.92.42L12 2zm-1.2 13.2l5.4-5.4-1.4-1.4-4 4-1.6-1.6-1.4 1.4 3 3z',
  fillRule: 'evenodd',
  label: 'Starburst badge with a check mark',
};

export const add: Glyph = {
  name: 'actionsAdd',
  source: 'actions/add.svg',
  codepoint: 'U+E002',
  path: 'M13 5h-2v6H5v2h6v6h2v-6h6v-2h-6V5z',
  label: 'Plus sign',
};

export const arrowDown: Glyph = {
  name: 'arrowsArrowDown',
  source: 'arrows/arrow_down.svg',
  codepoint: 'U+E004',
  path: 'M11 4v12.17l-5.59-5.58L4 12l8 8 8-8-1.41-1.41L13 16.17V4h-2z',
  label: 'Downward arrow',
};

export const warning: Glyph = {
  name: 'statusWarning',
  source: 'status/warning.svg',
  codepoint: 'U+E005',
  path: 'M12 2l10 18H2L12 2zm-1 6v6h2V8h-2zm0 8v2h2v-2h-2z',
  fillRule: 'evenodd',
  label: 'Triangle containing an exclamation mark',
};

/** The pack before four icons were added. */
export const packBefore: Glyph[] = [back, verified];

/**
 * The same pack afterwards, in the order GlyphPact discovers sources.
 * `actionsAdd` sorts first yet holds a later codepoint, which is the point.
 */
export const packAfter: Glyph[] = [add, arrowDown, back, verified, warning];
