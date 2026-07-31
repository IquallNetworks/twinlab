import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { FreezeAction, LabDetail, LifecycleAction } from '@/lib/schemas'

interface Entry {
  label: string
  disabled: string | null
  run: () => void
}

/** Whole-lab power and save-running-config, as entries for the lab header's
 * action menu (all `lab:configure`). Distinct from redeploy: these operate on
 * the EXISTING containers without rebuilding them from the definition.
 *
 * Offered by context, like the per-node menu. A lab is not one container
 * though, so its power state can be genuinely mixed — a half-stopped lab has
 * something to start AND something to stop, and gets both entries rather than
 * a toggle that hides the one you wanted. A lab that is all up, or all down,
 * sees one.
 *
 * Freeze fans out over the nodes server-side and 409s when none are up; save
 * needs a running node to read a config from. Both say so instead of failing. */
export function LabPowerMenuItems({ lab }: { lab: LabDetail }) {
  const name = lab.name
  const queryClient = useQueryClient()

  async function invalidate() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
      queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
      queryClient.invalidateQueries({ queryKey: labInterfacesQueryOptions(name).queryKey }),
    ])
  }

  const action = useMutation({
    mutationFn: (a: LifecycleAction) => api.labAction(name, a),
    onSuccess: async (result) => {
      await invalidate()
      toast.success(result.message)
    },
    onError: (err) => toastError(err, 'Action failed'),
  })

  // Whole-lab freeze fans pause/unpause out over the nodes (non-atomic).
  const freeze = useMutation({
    mutationFn: (a: FreezeAction) => api.freezeLab(name, a),
    onSuccess: async (result) => {
      await invalidate()
      toast.success(result.message)
    },
    onError: (err) => toastError(err, 'Action failed'),
  })

  const save = useMutation({
    mutationFn: () => api.saveLabConfig(name),
    onSuccess: (result) => toast.success(result.message || `Saved config for ${name}`),
    onError: (err) => toastError(err, 'Save failed'),
  })

  const busy = action.isPending || freeze.isPending || save.isPending
  const running = lab.nodes.filter((node) => node.state === 'running').length
  const paused = lab.nodes.filter((node) => node.state === 'paused').length
  const down = lab.nodes.length - running - paused
  // No containers at all: every verb here acts on containers, so they share one
  // honest reason rather than five variations of "there is nothing to do".
  const bare = lab.nodes.length === 0 ? `lab is ${lab.status}` : null

  const entries: Entry[] = []
  if (bare !== null) {
    entries.push({ label: 'Start', disabled: bare, run: () => undefined })
  } else {
    if (down > 0) entries.push({ label: 'Start', disabled: null, run: () => action.mutate('start') })
    if (running + paused > 0) {
      entries.push({ label: 'Stop', disabled: null, run: () => action.mutate('stop') })
    }
  }
  if (running > 0) {
    entries.push({ label: 'Pause', disabled: null, run: () => freeze.mutate('pause') })
  }
  if (paused > 0) {
    entries.push({ label: 'Unpause', disabled: null, run: () => freeze.mutate('unpause') })
  }
  if (running === 0 && paused === 0) {
    entries.push({ label: 'Pause', disabled: bare ?? 'no running nodes', run: () => undefined })
  }
  entries.push({ label: 'Restart', disabled: bare, run: () => action.mutate('restart') })
  entries.push({
    label: save.isPending ? 'Saving config…' : 'Save config',
    disabled: running > 0 ? null : (bare ?? 'no running nodes'),
    run: () => save.mutate(),
  })

  return (
    <>
      {entries.map((entry) => (
        <DropdownMenuItem
          key={entry.label}
          disabled={busy || entry.disabled !== null}
          title={entry.disabled ?? undefined}
          onSelect={entry.run}
        >
          {entry.label}
        </DropdownMenuItem>
      ))}
    </>
  )
}
