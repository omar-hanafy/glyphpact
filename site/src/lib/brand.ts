/**
 * The only module that reads the brand artwork.
 *
 * Both files live in /brand at the repository root, which is the documented
 * source of truth for the identity (see brand/README.md). They are imported
 * as raw strings and inlined at build time, so the mark costs no request and
 * can inherit `currentColor`.
 *
 * Consumers must not pick apart these strings. `BrandMark.astro` wraps the
 * markup untouched and sizes it with CSS, which is what lets the mark be
 * replaced during a rebrand without editing any component.
 */

import markSvg from '../../../brand/glyphpact-mark.svg?raw';
import iconSvg from '../../../brand/glyphpact-icon.svg?raw';

export { markSvg, iconSvg };
