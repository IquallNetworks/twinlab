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
 * open with a manual refresh. */
export function NodeLogsDialog({ name, node }: { name: string; node: string }) {
  const [open, setOpen] = useState(false)
  // Fetch on open, and let the user re-fetch; logs are a point-in-time snapshot.
  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['labs', name, 'logs', node],
    queryFn: () => api.nodeLogs(name, node),
    enabled: open,
    staleTime: 0,
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        Logs
      </Button>
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
