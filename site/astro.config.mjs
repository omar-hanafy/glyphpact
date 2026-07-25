// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

/**
 * The production origin and project subpath live here and nowhere else.
 *
 * Everything downstream reads them back through `import.meta.env.SITE` and
 * `import.meta.env.BASE_URL` (see src/site.config.ts), so a custom-domain
 * migration is a two-value change:
 *
 *   SITE_ORIGIN=https://glyphpact.dev SITE_BASE=/ npm run build
 *
 * ...plus a CNAME file and DNS. No template hardcodes either value.
 */
const origin = process.env.SITE_ORIGIN ?? 'https://omar-hanafy.github.io';
const base = process.env.SITE_BASE ?? '/glyphpact';

export default defineConfig({
  site: origin,
  base,
  output: 'static',
  trailingSlash: 'always',
  build: {
    format: 'directory',
    // One stylesheet beats a request chain on a site this small.
    inlineStylesheets: 'always',
  },
  integrations: [
    sitemap({
      // Social preview images and the favicon are assets, not pages.
      filter: (page) => !page.includes('/og/') && !page.includes('/favicon'),
    }),
  ],
  devToolbar: { enabled: false },
  vite: {
    build: {
      // The only shipped script is the ~1KB copy-button enhancement; a
      // separate request for it would cost more than inlining it.
      assetsInlineLimit: 4096,
    },
  },
});
