import { cn } from '@/lib/utils'

/** Twin diamonds — two identical nodes, one real and one simulated. */
function TwinGlyph({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <path d="M8 4l7 8-7 8-7-8z" />
      <path d="M16 4l7 8-7 8-7-8z" opacity="0.45" />
    </svg>
  )
}

/** The product wordmark — the twin-diamond glyph is the logo. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <TwinGlyph className="size-4 shrink-0 text-primary" />
      <span className="font-heading font-semibold tracking-[0.18em] uppercase">Twinlab</span>
    </span>
  )
}
