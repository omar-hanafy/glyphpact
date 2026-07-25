/**
 * Structured data builders.
 *
 * Every value here is derived from the same modules that render the visible
 * page - site.config.ts and data/faq.ts - so the markup a crawler reads and
 * the text a person reads cannot disagree. Nothing is added for volume: the
 * site emits a software entity, breadcrumbs on subpages, and FAQPage only
 * where a genuine visible FAQ exists.
 */

import { site, absolute, RELEASE, INSTALL_COMMAND, routes, type RouteKey } from '../site.config';
import { faqFor, type FaqEntry } from '../data/faq';

const ORG_ID = absolute('/#project');

/** The software entity. Placed on the homepage only. */
export function softwareSchema(): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    '@id': ORG_ID,
    name: site.name,
    alternateName: 'GlyphPact SVG-to-icon-font compiler',
    description:
      'A deterministic command-line compiler that turns a directory of SVG files into a validated OpenType/CFF icon font, a committed codepoint registry, and a const Flutter IconData API, keeping existing codepoints stable across icon-pack changes.',
    url: absolute('/'),
    softwareVersion: RELEASE.version,
    applicationCategory: 'DeveloperApplication',
    applicationSubCategory: 'Icon font compiler',
    operatingSystem: 'macOS, Linux, Windows',
    softwareRequirements: 'Python 3.10 or newer',
    downloadUrl: site.links.releases,
    codeRepository: site.repo,
    installUrl: absolute('/'),
    license: 'https://opensource.org/licenses/MIT',
    isAccessibleForFree: true,
    author: {
      '@type': 'Person',
      name: site.author.name,
      url: site.author.url,
    },
    maintainer: {
      '@type': 'Person',
      name: site.author.name,
      url: site.author.url,
    },
    // Free and open source. Stating the price explicitly avoids the "missing
    // offers" warning without inventing commercial terms.
    offers: {
      '@type': 'Offer',
      price: 0,
      priceCurrency: 'USD',
    },
    featureList: [
      'Stable codepoints across icon-pack changes via a committed lock file',
      'Validated OpenType/CFF font output',
      'const Flutter IconData provider generation',
      'Byte-identical deterministic rebuilds',
      'Explicit two-axis fidelity policy for unsupported SVG features',
      'CI staleness verification with a dedicated check mode',
      'Generated artwork attribution record',
      'Local Claude Code and Codex plugin over MCP',
    ],
    keywords:
      'svg to icon font, icon font generator, stable codepoints, flutter icon font, svg to otf, iconfont lock, deterministic build',
  };
}

/** Bare software reference used by subpages so they attach to one entity. */
export function softwareReference(): Record<string, unknown> {
  return { '@id': ORG_ID };
}

/** FAQPage. Emitted only where the page actually renders those answers. */
export function faqSchema(page: FaqEntry['pages'][number]): Record<string, unknown> {
  const entries = faqFor(page);
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: entries.map((entry) => ({
      '@type': 'Question',
      name: entry.question,
      acceptedAnswer: {
        '@type': 'Answer',
        // The identical strings the page renders, joined into one text block.
        text: entry.answer.join('\n\n'),
      },
    })),
  };
}

export interface Crumb {
  name: string;
  /** Route path; omitted for the current page. */
  href?: string;
}

/** BreadcrumbList for subpages. */
export function breadcrumbSchema(crumbs: Crumb[]): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: crumbs.map((crumb, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: crumb.name,
      ...(crumb.href ? { item: absolute(crumb.href) } : {}),
    })),
  };
}

/** TechArticle for the explanatory pages, which are genuinely articles. */
export function articleSchema(key: RouteKey): Record<string, unknown> {
  const route = routes[key];
  return {
    '@context': 'https://schema.org',
    '@type': 'TechArticle',
    headline: route.title,
    description: route.description,
    url: absolute(route.href),
    inLanguage: 'en',
    isPartOf: { '@id': ORG_ID },
    about: softwareReference(),
    author: {
      '@type': 'Person',
      name: site.author.name,
      url: site.author.url,
    },
    publisher: {
      '@type': 'Person',
      name: site.author.name,
      url: site.author.url,
    },
    image: absolute(`/og/${key === 'home' ? 'index' : key}.png`),
  };
}

/** WebSite entity so the site itself is addressable. Homepage only. */
export function websiteSchema(): Record<string, unknown> {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    '@id': absolute('/#website'),
    name: site.name,
    description: site.tagline,
    url: absolute('/'),
    inLanguage: 'en',
    about: softwareReference(),
    publisher: {
      '@type': 'Person',
      name: site.author.name,
      url: site.author.url,
    },
  };
}

/** Exposed so /llms.txt and the claims check can read the same command. */
export const installCommand = INSTALL_COMMAND;
