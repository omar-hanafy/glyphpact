import type { APIRoute } from 'astro';
import { iconSvg } from '../lib/brand';

/**
 * The favicon, served from the canonical brand file rather than a copy in
 * public/. A rebrand touches brand/glyphpact-icon.svg and this follows.
 */
export const GET: APIRoute = () =>
  new Response(iconSvg, {
    headers: {
      'Content-Type': 'image/svg+xml',
      'Cache-Control': 'public, max-age=604800',
    },
  });
