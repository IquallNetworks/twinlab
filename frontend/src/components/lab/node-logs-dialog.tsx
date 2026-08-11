import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { api } from '@/lib/api'

/** Point-in-time container logs for one node (last 200 lines), fetched on
 * open with a manual refresh.
 *
 * Owns its trigger button by default (the Connect drawer uses it that way).
 * Pass `open`/`onOpenChange` to drive it from somewhere a button cannot go —
 * the nodes table opens it from a menu item, where the trigger would be a
 * second, competing button. */
export function NodeLogsDialog({
  name,
  node,
  open: openProp,
  onOpenChange,
}: {
  name: string
  node: string
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
  const controlled = openProp !== undefined
  const open = controlled ? openProp : uncontrolledOpen
  const setOpen = controlled ? (onOpenChange ?? (() => {})) : setUncontrolledOpen
  // Fetch on open, and let the user re-fetch; logs are a point-in-time snapshot.
  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['labs', name, 'logs', node],
    queryFn: () => api.nodeLogs(name, node),
    enabled: open,
    staleTime: 0,
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {!controlled && (
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
          Logs
        </Button>
      )}
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Logs — {node}</DialogTitle>
          <DialogDescription>
            {data ? data.container : `clab node ${node}`} · last 200 lines
          </DialogDescription>
        </DialogHeader>
        <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted p-4 font-mono text-xs">
          {isFetching
            ? 'Loading…'
            : isError
              ? error instanceof Error
                ? error.message
                : 'Failed to load logs'
              : (data?.logs ?? '').trim() || 'No log output.'}
        </pre>
        <div>
          <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            Refresh
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
