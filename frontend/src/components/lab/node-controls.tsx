import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { NodeAction } from '@/lib/schemas'

import { NodeLogsDialog } from './node-logs-dialog'
import { NodeTerminalDialog } from './node-terminal-dialog'

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

/** Per-node runtime controls for the nodes table: a start/stop/restart menu
 * (lab:configure), a logs viewer (lab:read), and an interactive console
 * (lab:terminal, only while the node is up). */
export function NodeControls({
  name,
  node,
  state,
  canConfigure,
  canRead,
  canTerminal,
}: {
  name: string
  node: string
  state: string
  canConfigure: boolean
  canRead: boolean
  canTerminal: boolean
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
    onError: (err) => toastError(err, 'Action failed'),
  })

  return (
    <div className="flex items-center justify-end gap-1">
      {canRead && <NodeLogsDialog name={name} node={node} />}
      {canTerminal && state === 'running' && <NodeTerminalDialog name={name} node={node} />}
      {canConfigure && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" disabled={action.isPending}>
              {action.isPending ? '…' : 'Actions'}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {nodeActionMenu(state).map(({ action: verb, label, disabled }) => (
              <DropdownMenuItem
                key={label}
                disabled={disabled !== null}
                title={disabled ?? undefined}
                onClick={() => action.mutate(verb)}
              >
                {label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}
