import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { testSuitesQueryOptions } from '@/lib/queries'
import type { TestSuite } from '@/lib/schemas'

export type Suites = Record<string, TestSuite>

/** Every suite editor saves the same way, because the wire has one verb: the
 * PUT replaces the whole map. So each dialog edits its own slice of the map it
 * was handed and sends the result — there is no partial save to be had, and
 * pretending otherwise would lose whatever another dialog changed. */
export function useSaveSuites(name: string, onSaved?: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Suites) => api.putTestSuites(name, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: testSuitesQueryOptions(name).queryKey })
      toast.success('Saved test suites')
      onSaved?.()
    },
    onError: (err) => toastError(err, 'Failed to save suites'),
  })
}
