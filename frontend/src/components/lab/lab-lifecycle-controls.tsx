import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { labInterfacesQueryOptions, labQueryOptions, labsQueryOptions } from '@/lib/queries'
import type { FreezeAction, LifecycleAction } from '@/lib/schemas'

const ACTIONS: LifecycleAction[] = ['start', 'stop', 'restart']
const FREEZE_ACTIONS: FreezeAction[] = ['pause', 'unpause']

/** Whole-lab power controls and a save-running-config button (all lab:configure).
 * Distinct from redeploy: these operate on the existing nodes without rebuilding
 * them from the definition. */
export function LabLifecycleControls({ name }: { name: string }) {
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

  return (
    <div className="flex flex-wrap items-center gap-2">
      {ACTIONS.map((a) => (
        <Button
          key={a}
          variant="outline"
          size="sm"
          className="capitalize"
          onClick={() => action.mutate(a)}
          disabled={busy}
        >
          {a}
        </Button>
      ))}
      {FREEZE_ACTIONS.map((a) => (
        <Button
          key={a}
          variant="outline"
          size="sm"
          className="capitalize"
          onClick={() => freeze.mutate(a)}
          disabled={busy}
        >
          {a}
        </Button>
      ))}
      <Button variant="outline" size="sm" onClick={() => save.mutate()} disabled={busy}>
        {save.isPending ? 'Saving…' : 'Save config'}
      </Button>
    </div>
  )
}
