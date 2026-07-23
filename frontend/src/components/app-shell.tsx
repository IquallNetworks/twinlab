import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate } from '@tanstack/react-router'
import { LogOut } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { meQueryOptions } from '@/lib/queries'
import { useLabEvents } from '@/lib/use-lab-events'

const PERM_USER_MANAGE = 'user:manage'

export function AppShell() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // Live lab updates over SSE while authenticated (this shell wraps the auth area).
  useLabEvents()
  // Guaranteed present: the auth route's beforeLoad resolved it before render.
  const { data: me } = useQuery(meQueryOptions)

  const logout = useMutation({
    mutationFn: () => api.logout(),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: meQueryOptions.queryKey })
      await navigate({ to: '/login' })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Logout failed'),
  })

  const canManageUsers = me?.permissions.includes(PERM_USER_MANAGE) ?? false

  return (
    <div className="min-h-screen">
      <header className="border-b">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-6 px-4">
          <Link to="/labs" className="font-semibold">
            Twinlab
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link
              to="/labs"
              className="text-muted-foreground data-[status=active]:text-foreground"
            >
              Labs
            </Link>
            {canManageUsers && (
              <Link
                to="/users"
                className="text-muted-foreground data-[status=active]:text-foreground"
              >
                Users
              </Link>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-muted-foreground">{me?.username}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              <LogOut className="size-4" />
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
