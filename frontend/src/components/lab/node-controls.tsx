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

const ACTIONS: NodeAction[] = ['start', 'stop', 'restart', 'pause', 'unpause']

/** Per-node runtime controls for the nodes table: a start/stop/restart menu
 * (lab:configure), a logs viewer (lab:read), and an interactive console
 * (lab:terminal, only while the node is up). */
export function NodeControls({
  name,
  node,
  running,
  canConfigure,
  canRead,
  canTerminal,
}: {
  name: string
  node: string
  running: boolean
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
      {canTerminal && running && <NodeTerminalDialog name={name} node={node} />}
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
