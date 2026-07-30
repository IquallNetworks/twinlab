import { Badge } from '@/components/ui/badge'
import { statusBadgeVariant } from '@/lib/format'
import { cn } from '@/lib/utils'

// Lifecycle glyphs: empty record → in flight → live → torn down. Unknown
// statuses fall back to text-only rather than guessing a symbol.
const STATUS_GLYPHS: Record<string, string> = {
  created: '◌',
  deploying: '◐',
  deployed: '▲',
  destroyed: '■',
}

/** Lab lifecycle status as a glyph-fronted badge (shared across identities;
 * the packs restyle it through the badge tokens). */
export function LabStatusBadge({ status, className }: { status: string; className?: string }) {
  const glyph = STATUS_GLYPHS[status]
  return (
    <Badge variant={statusBadgeVariant(status)} className={cn('gap-1', className)}>
      {glyph && (
        <span aria-hidden="true" className={cn(status === 'deploying' && 'animate-pulse')}>
          {glyph}
        </span>
      )}
      {status}
    </Badge>
  )
}
