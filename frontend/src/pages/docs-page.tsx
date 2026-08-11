import { Link } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { Children, isValidElement, type ReactNode } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { ThemeToggle } from '@/components/theme-toggle'
import { Wordmark } from '@/components/wordmark'
import { GUIDE_PAGES, guidePage, headingSlug, resolveHref } from '@/lib/guide'
import { useDocumentTitle } from '@/lib/use-document-title'
import { cn } from '@/lib/utils'

// The operator guide, served by the app itself (docs/guide/, symlinked into
// src/content). Deliberately OUTSIDE the auth gate: the page you most need is
// the troubleshooting index, and needing to sign in to read why you cannot
// sign in would be its own joke.

const DOCS_BASE = '/docs'

/** Flatten a heading's children to text, for its anchor id. */
function textOf(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) => {
      if (typeof child === 'string' || typeof child === 'number') return String(child)
      if (isValidElement<{ children?: ReactNode }>(child)) return textOf(child.props.children)
      return ''
    })
    .join('')
}

/** `<kbd>` is the guide's only raw HTML, and react-markdown does not render
 * raw HTML without another plugin. Inline code carries the same meaning here,
 * so the markdown keeps its real `<kbd>` for repository readers and this site
 * renders it as a key cap. */
const kbdToCode = (markdown: string): string =>
  markdown.replace(/<kbd>(.*?)<\/kbd>/g, (_match, key: string) => `\`${key}\``)

function Heading({ level, children }: { level: 2 | 3 | 4; children: ReactNode }) {
  const id = headingSlug(textOf(children))
  const size =
    level === 2
      ? 'mt-10 border-b pb-1.5 text-[1.43em]'
      : level === 3
        ? 'mt-8 text-[1.14em]'
        : 'mt-6 text-[1em]'
  const Tag = `h${level}` as const
  return (
    <Tag id={id} className={cn('scroll-mt-20 font-medium tracking-tight', size)}>
      {/* The anchor is the heading itself, so a copied link matches the
          `](#…)` links the pages already use between each other. */}
      <a href={`#${id}`} className="no-underline hover:underline">
        {children}
      </a>
    </Tag>
  )
}

/** One link to a guide page, typed the way the router wants it. */
function PageLink({ slug, hash, children }: { slug: string; hash?: string; children: ReactNode }) {
  const className = 'text-primary underline underline-offset-2'
  if (slug === '') {
    return (
      <Link to={DOCS_BASE} hash={hash} className={className}>
        {children}
      </Link>
    )
  }
  return (
    <Link to="/docs/$slug" params={{ slug }} hash={hash} className={className}>
      {children}
    </Link>
  )
}

function markdownComponents(): Components {
  return {
    h1: ({ children }) => (
      <h1 className="mb-6 text-[1.71em] font-semibold tracking-tight">{children}</h1>
    ),
    h2: ({ children }) => <Heading level={2}>{children}</Heading>,
    h3: ({ children }) => <Heading level={3}>{children}</Heading>,
    h4: ({ children }) => <Heading level={4}>{children}</Heading>,
    p: ({ children }) => <p className="mt-4 leading-7">{children}</p>,
    ul: ({ children }) => <ul className="mt-4 ml-5 list-disc space-y-1.5">{children}</ul>,
    ol: ({ children }) => <ol className="mt-4 ml-5 list-decimal space-y-1.5">{children}</ol>,
    li: ({ children }) => <li className="leading-7">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className="mt-4 border-l-2 border-primary/60 pl-4 text-muted-foreground">
        {children}
      </blockquote>
    ),
    hr: () => <hr className="my-8" />,
    strong: ({ children }) => <strong className="font-medium text-foreground">{children}</strong>,
    a: ({ href, children }) => {
      const target = href === undefined ? null : resolveHref(href)
      // A relative link the guide does not carry would be dead — render the
      // words rather than a link that goes nowhere.
      if (target === null) return <span>{children}</span>
      if (target.kind === 'page') {
        return (
          <PageLink slug={target.slug} hash={target.hash}>
            {children}
          </PageLink>
        )
      }
      const href_ = target.kind === 'anchor' ? `#${target.hash}` : target.href
      const external = target.kind === 'external' && /^[a-z][a-z0-9+.-]*:/i.test(href_)
      return (
        <a
          href={href_}
          {...(external && { target: '_blank', rel: 'noreferrer' })}
          className="text-primary underline underline-offset-2"
        >
          {children}
        </a>
      )
    },
    code: ({ className, children }) => {
      // react-markdown marks a fenced block with a language class; anything
      // else is inline.
      const fenced = className?.startsWith('language-') ?? false
      if (fenced) return <code className="font-mono">{children}</code>
      return (
        <code className="rounded-[2px] bg-muted px-1 py-0.5 font-mono text-[0.85em] text-(--id-code-key)">
          {children}
        </code>
      )
    },
    pre: ({ children }) => (
      <pre className="mt-4 overflow-x-auto rounded-[2px] border bg-muted p-3 text-[0.86em] leading-6">
        {children}
      </pre>
    ),
    // Wide tables scroll inside their own box; the page never scrolls sideways.
    table: ({ children }) => (
      <div className="mt-4 overflow-x-auto rounded-[2px] border">
        <table className="w-full border-collapse text-[1em]">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-muted/60">{children}</thead>,
    tr: ({ children }) => <tr className="border-b last:border-0">{children}</tr>,
    th: ({ children }) => (
      <th className="px-3 py-2 text-left font-medium whitespace-nowrap">{children}</th>
    ),
    td: ({ children }) => <td className="px-3 py-2 align-top">{children}</td>,
  }
}

function DocsNav({ slug }: { slug: string }) {
  return (
    <nav aria-label="Guide contents" className="flex flex-col gap-0.5 text-sm">
      {GUIDE_PAGES.map((page) => (
        <PageLink key={page.slug} slug={page.slug}>
          <span
            className={cn(
              'block rounded-[2px] px-2 py-1 no-underline transition-colors hover:bg-accent/60',
              page.slug === slug
                ? 'bg-accent font-medium text-accent-foreground'
                : 'text-muted-foreground',
            )}
          >
            {page.order > 0 && (
              <span className="mr-1.5 font-mono text-xs text-muted-foreground">{page.order}</span>
            )}
            {page.title}
          </span>
        </PageLink>
      ))}
    </nav>
  )
}

export function DocsPage({ slug = '' }: { slug?: string }) {
  const page = guidePage(slug)
  useDocumentTitle(page === undefined ? 'Documentation' : `${page.title} · Guide`)

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-(--id-header-border) bg-(--id-header-bg) text-(--id-header-fg) backdrop-blur">
        <div className="mx-auto flex h-12 max-w-[var(--id-shell-max,72rem)] items-center gap-6 px-4">
          <Link to={DOCS_BASE} aria-label="Twinlab guide">
            <Wordmark />
          </Link>
          <span className="font-mono text-xs tracking-wide text-(--id-header-muted) uppercase">
            operator guide
          </span>
          <div className="ml-auto flex items-center gap-1 text-sm">
            <Link
              to="/"
              className="flex items-center gap-1.5 rounded-[2px] px-2 py-1 text-(--id-header-muted) transition-colors hover:text-(--id-header-fg)"
            >
              <ArrowLeft className="size-4" />
              Back to Twinlab
            </Link>
            <ThemeToggle className="text-(--id-header-muted) hover:text-(--id-header-fg)" />
          </div>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[var(--id-shell-max,72rem)] flex-1 gap-8 px-4 py-8">
        <aside className="hidden w-56 shrink-0 md:block">
          <div className="sticky top-20">
            <DocsNav slug={slug} />
          </div>
        </aside>
        <main className="min-w-0 flex-1">
          {page === undefined ? (
            <div className="mt-8">
              <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
              <p className="mt-4 text-muted-foreground">
                The guide has no page called <code className="font-mono">{slug}</code>.
              </p>
              <Link to={DOCS_BASE} className="mt-4 inline-block text-primary underline">
                Guide contents
              </Link>
            </div>
          ) : (
            /* The one number the page's typography scales from. Every
               heading, table and code block below is sized in `em` at the
               ratio it held against the app's text-sm, so changing this
               scales the whole page and keeps the proportions.
               1.05rem == 0.875rem x 1.20. */
            <article className="max-w-[46rem] text-[1.05rem]">
              <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents()}>
                {kbdToCode(page.markdown)}
              </Markdown>
              {/* The sidebar hides on narrow screens, so the contents stay
                  reachable at the foot of every page. */}
              <div className="mt-12 border-t pt-6 md:hidden">
                <DocsNav slug={slug} />
              </div>
            </article>
          )}
        </main>
      </div>
    </div>
  )
}
