import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MoreVertical } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { NodeAction } from '@/lib/schemas'

import { NodeLogsDialog } from './node-logs-dialog'

/** The menu as two toggles plus restart, not five verbs: a node is either up or
 * down and either frozen or not, so each axis gets ONE entry whose label is the
 * verb that applies right now. Docker would refuse or ignore the other half
 * anyway — `start` on a running container is a silent 304 no-op, `pause`/
 * `unpause` in the wrong state a hard 409.
 *
 * Freezing is the one axis with a state that has no verb at all (nothing to
 * pause on a stopped node), so it is the only entry that can be disabled.
 * `restart` stays available from stopped, since docker starts it from there. */
function nodeActionMenu(
  state: string,
): { action: NodeAction; label: string; disabled: string | null }[] {
  const paused = state === 'paused'
  const transitional = state === 'restarting' || state === 'removing'
  // A paused container is up-but-frozen: stopping it is meaningful, starting it
  // is not — unpause is the way back.
  const up = state === 'running' || paused
  const midFlight = transitional ? `node is ${state}` : null
  return [
    { action: up ? 'stop' : 'start', label: up ? 'Stop' : 'Start', disabled: midFlight },
    {
      action: paused ? 'unpause' : 'pause',
      label: paused ? 'Unpause' : 'Pause',
      disabled: up ? null : `node is ${state}`,
    },
    { action: 'restart', label: 'Restart', disabled: midFlight },
  ]
}

/** Per-node runtime controls for the nodes table: ONE overflow menu carrying
 * the logs viewer (lab:read) and start/stop/restart (lab:configure).
 *
 * Everything here used to be a button of its own, which cost the table three
 * columns' worth of width on the row it can least spare. The console is not
 * here at all — it already lives in the Connect drawer, beside the SSH
 * recipes that are the other way into the same node. */
export function NodeControls({
  name,
  node,
  state,
  canConfigure,
  canRead,
}: {
  name: string
  node: string
  state: string
  canConfigure: boolean
  canRead: boolean
}) {
  const [logsOpen, setLogsOpen] = useState(false)
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
    onError: (err) => toastError(err, 'Action failed'),
  })

  if (!canRead && !canConfigure) return null

  return (
    <div className="flex items-center justify-end">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label="Actions"
            disabled={action.isPending}
          >
            <MoreVertical className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canRead && <DropdownMenuItem onSelect={() => setLogsOpen(true)}>Logs</DropdownMenuItem>}
          {canRead && canConfigure && <DropdownMenuSeparator />}
          {canConfigure &&
            nodeActionMenu(state).map(({ action: verb, label, disabled }) => (
              <DropdownMenuItem
                key={label}
                disabled={disabled !== null}
                title={disabled ?? undefined}
                onSelect={() => action.mutate(verb)}
              >
                {label}
              </DropdownMenuItem>
            ))}
        </DropdownMenuContent>
      </DropdownMenu>
      {/* Outside the menu: radix unmounts the menu's content on close, which
          would take the dialog with it. */}
      {canRead && (
        <NodeLogsDialog name={name} node={node} open={logsOpen} onOpenChange={setLogsOpen} />
      )}
    </div>
  )
}
