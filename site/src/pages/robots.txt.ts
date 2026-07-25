import type { APIRoute } from 'astro';
import { absolute } from '../site.config';

/**
 * Generated rather than a static file in public/, so the sitemap URL stays
 * correct if the origin or base path changes.
 */
export const GET: APIRoute = () =>
  new Response(
    `User-agent: *
Allow: /

Sitemap: ${absolute('/sitemap-index.xml')}
`,
    { headers: { 'Content-Type': 'text/plain; charset=utf-8' } },
  );
