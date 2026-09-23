import { monogram } from '@/lib/oidc'
import { cn } from '@/lib/utils'

/** The glyph before a provider's label: its uploaded icon, or a monogram. The
 * icon is a data: URI rendered through <img>, which runs no script even for an
 * SVG — why the server serves icons inline rather than from a URL. */
export function ProviderGlyph({ displayName, icon }: { displayName: string; icon: string | null }) {
  if (icon !== null) {
    return <img src={icon} alt="" className="size-5 shrink-0 object-contain" />
  }
  return (
    <span
      aria-hidden="true"
      className="grid size-5 shrink-0 place-items-center rounded-full border border-current/40 font-mono text-[0.65rem] font-semibold"
    >
      {monogram(displayName)}
    </span>
  )
}

const BUTTON =
  'inline-flex h-9 w-full items-center justify-center gap-2 rounded-md border bg-background px-4 text-sm font-medium shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground'

/** "Sign in with {display_name}". With `href` it is the real thing — a plain
 * link, because the flow is a chain of top-level redirects, not a fetch;
 * without one it is the admin page's preview of exactly how it will render. */
export function ProviderButton({
  displayName,
  icon,
  href,
  className,
}: {
  displayName: string
  icon: string | null
  href?: string
  className?: string
}) {
  const content = (
    <>
      <ProviderGlyph displayName={displayName} icon={icon} />
      <span>Sign in with {displayName}</span>
    </>
  )
  return href !== undefined ? (
    <a href={href} className={cn(BUTTON, className)}>
      {content}
    </a>
  ) : (
    <div className={cn(BUTTON, 'pointer-events-none', className)} aria-hidden="true">
      {content}
    </div>
  )
}
