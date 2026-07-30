import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'

import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { meQueryOptions } from '@/lib/queries'

/** The one logout path (header button and command palette): end the session,
 * drop the cached identity, land on /login. */
export function useLogout() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.logout(),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: meQueryOptions.queryKey })
      await navigate({ to: '/login' })
    },
    onError: (err) => toastError(err, 'Logout failed'),
  })
}
