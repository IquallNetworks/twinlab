import { Check, Minus, TriangleAlert, X } from 'lucide-react'
import type { ComponentType } from 'react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { readStatus, type ResultStatus } from '@/lib/test-results'

/** The tab's colour grammar, in one place.
 *
 * The rule is that ATTENTION goes to what is wrong. The obvious mapping —
 * pass as the "active" variant, fail/error as `destructive` — inverts it,
 * because shadcn's destructive badge is a pale tint while the default one is
 * a solid fill: a suite with 19 passes and one failure rendered as twenty
 * blocks of amber with the failure as the faintest thing in the row. So a
 * pass is QUIET here and a failure is loud.
 *
 * `error` outranks `fail` in the roll-up (an assertion that could not be made
 * at all beats one that came back false), and the styling says so: error is
 * the only solid fill. Every state also carries an icon, so the reading does
 * not depend on colour alone. */
const TONE: Record<ResultStatus, string> = {
  // Definite but recessive — the check does the work, not the fill.
  pass: 'border-primary/40 bg-primary/5 text-foreground',
  fail: 'border-destructive bg-destructive/12 text-destructive font-semibold',
  // Solid, and the only one: white on the light theme's red, near-black on
  // the dark theme's lighter red — the token flips lightness between them.
  error: 'border-transparent bg-destructive text-white dark:text-background',
  skip: 'border-border bg-transparent text-muted-foreground',
}

const ICON: Record<ResultStatus, ComponentType<{ className?: string }>> = {
  pass: Check,
  fail: X,
  error: TriangleAlert,
  skip: Minus,
}

/** The classes for a status, for callers that build their own Badge (the
 * per-node pills wrap a button). Always used with `variant="outline"`, whose
 * border and neutral text these override. */
export function statusTone(status: string): string {
  return TONE[readStatus(status)]
}

export function StatusIcon({ status, className }: { status: string; className?: string }) {
  const Icon = ICON[readStatus(status)]
  return <Icon className={cn('size-3', className)} />
}

/** A result status as a badge: icon + word. */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge variant="outline" className={cn(statusTone(status), className)}>
      <StatusIcon status={status} />
      {status}
    </Badge>
  )
}

/** The suite roll-up, in the same grammar: `failing` is loud, `passing` is
 * not. Not a StatusBadge — a suite's vocabulary is its own. */
export function SuiteStatusBadge({ status }: { status: 'passing' | 'failing' }) {
  return (
    <Badge variant="outline" className={status === 'failing' ? TONE.fail : TONE.pass}>
      {status === 'failing' ? <X className="size-3" /> : <Check className="size-3" />}
      {status}
    </Badge>
  )
}

/** A suite's stage. Quiet on purpose: it was a solid amber block competing
 * with the result badges for the same colour, and a stage is context, not a
 * verdict. `config-time` keeps the accent hue because it GATES a deploy. */
export function StageBadge({ stage }: { stage: string }) {
  return (
    <Badge
      variant="outline"
      className={stage === 'config-time' ? 'border-primary/50 text-primary' : undefined}
    >
      {stage}
    </Badge>
  )
}

