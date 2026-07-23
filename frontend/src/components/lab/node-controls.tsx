import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { NodeAction } from '@/lib/schemas'

const ACTIONS: NodeAction[] = ['start', 'stop', 'restart', 'pause', 'unpause']

function NodeLogsDialog({ name, node }: { name: string; node: string }) {
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
        <pre className="bg-muted max-h-[60vh] overflow-auto rounded-md p-4 font-mono text-xs">
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

/** Per-node runtime controls for the nodes table: a start/stop/restart menu
 * (lab:configure) and a logs viewer (lab:read). */
export function NodeControls({
  name,
  node,
  canConfigure,
  canRead,
}: {
  name: string
  node: string
  canConfigure: boolean
  canRead: boolean
}) {
  const queryClient = useQueryClient()
  const action = useMutation({
    mutationFn: (a: NodeAction) => api.nodeAction(name, node, a),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
        queryClient.invalidateQueries({ queryKey: labInterfacesQueryOptions(name).queryKey }),
      ])
      toast.success(result.message)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Action failed'),
  })

  return (
    <div className="flex items-center justify-end gap-1">
      {canRead && <NodeLogsDialog name={name} node={node} />}
      {canConfigure && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" disabled={action.isPending}>
              {action.isPending ? '…' : 'Actions'}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {ACTIONS.map((a) => (
              <DropdownMenuItem key={a} onClick={() => action.mutate(a)} className="capitalize">
                {a}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}
