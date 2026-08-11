// The operator guide, compiled into the bundle from docs/guide/.
//
// src/content/guide is a SYMLINK to ../../../docs/guide, so the markdown has
// exactly one home: a page and the behaviour it documents ride the same
// commit, and there is no copy to drift. The compose frontend mounts ./docs at
// /docs so the symlink resolves inside the container too.
//
// Pure module (no React) so the slug/link rules can be reasoned about — and
// tested — on their own.

const RAW = import.meta.glob('../content/guide/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

export interface GuidePage {
  /** URL segment: `03-build-tab.md` -> `build-tab`. The index page is ''. */
  slug: string
  /** Source file name, which is what in-guide links point at. */
  file: string
  /** The `# ` heading, minus its "N. " prefix. */
  title: string
  /** Sort key from the file name's numeric prefix; the index sorts first. */
  order: number
  markdown: string
}

const fileName = (path: string): string => path.slice(path.lastIndexOf('/') + 1)

/** `03-build-tab.md` -> `build-tab`, `README.md` -> '' (the index). */
export function slugFor(file: string): string {
  if (file === 'README.md') return ''
  return file.replace(/\.md$/, '').replace(/^\d+-/, '')
}

const titleOf = (markdown: string, fallback: string): string => {
  const heading = /^#\s+(.+)$/m.exec(markdown)
  if (heading?.[1] === undefined) return fallback
  return heading[1].replace(/^\d+\.\s*/, '').trim()
}

export const GUIDE_PAGES: readonly GuidePage[] = Object.entries(RAW)
  .map(([path, markdown]) => {
    const file = fileName(path)
    const prefix = /^(\d+)-/.exec(file)
    return {
      slug: slugFor(file),
      file,
      title: titleOf(markdown, file),
      // The index has no number and leads; everything else follows its prefix.
      order: prefix?.[1] !== undefined ? Number(prefix[1]) : -1,
      markdown,
    }
  })
  .sort((a, b) => a.order - b.order)

export const guidePage = (slug: string): GuidePage | undefined =>
  GUIDE_PAGES.find((page) => page.slug === slug)

/** GitHub's heading-anchor rule, which is what the pages' own `](#…)` links
 * assume: lowercase, drop anything but letters/digits/space/dash, spaces to
 * dashes. Inline code and emphasis markers are stripped first so a heading
 * like "`prefix: false`" anchors the way its author wrote the link. */
export function headingSlug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`*_]/g, '')
    .replace(/[^a-z0-9 -]/g, '')
    .trim()
    .replace(/\s+/g, '-')
}

/** What a link in the markdown points at, once resolved.
 *
 * A structured result rather than a string because the router's links are
 * typed: a guide page is a route plus params, not a path you can concatenate.
 * `null` means a relative link to a file the guide does not carry, which the
 * renderer degrades to plain text rather than shipping a dead link. */
export type GuideLink =
  | { kind: 'page'; slug: string; hash?: string }
  | { kind: 'anchor'; hash: string }
  | { kind: 'external'; href: string }

export function resolveHref(href: string): GuideLink | null {
  if (href.startsWith('#')) return { kind: 'anchor', hash: href.slice(1) }
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('/')) {
    return { kind: 'external', href }
  }
  const [path, anchor] = href.split('#')
  if (path === undefined || path === '') return { kind: 'external', href }
  const page = GUIDE_PAGES.find((entry) => entry.file === fileName(path))
  if (page === undefined) return null
  return anchor !== undefined && anchor !== ''
    ? { kind: 'page', slug: page.slug, hash: anchor }
    : { kind: 'page', slug: page.slug }
}
