import { Link, type ErrorComponentProps } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'

/** Router-level crash surface: whatever a route render or loader threw, the
 * user gets the message and two exits instead of a white screen. */
export function RouteErrorFallback({ error }: ErrorComponentProps) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-24 text-center">
      <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
        something broke
      </p>
      <p className="text-sm text-destructive">
        {error instanceof Error ? error.message : 'Unexpected error'}
      </p>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
          Reload
        </Button>
        <Link to="/" className="text-sm underline hover:text-foreground">
          Back to dashboard
        </Link>
      </div>
    </div>
  )
}

export function RouteNotFound() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-24 text-center">
      <p className="font-mono text-xs tracking-wide text-muted-foreground uppercase">
        404 — no such page
      </p>
      <p className="text-sm text-muted-foreground">Nothing lives at this address.</p>
      <Link to="/" className="text-sm underline hover:text-foreground">
        Back to dashboard
      </Link>
    </div>
  )
}
