import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, type LinkProps } from '@tanstack/react-router'
import { LogOut } from 'lucide-react'
import { toast } from 'sonner'

import { IdentitySwitcher, ThemeToggle } from '@/components/identity-switcher'
import { Button } from '@/components/ui/button'
import { Wordmark } from '@/components/wordmark'
import { api } from '@/lib/api'
import { meQueryOptions } from '@/lib/queries'
import { useLabEvents } from '@/lib/use-lab-events'

const PERM_USER_MANAGE = 'user:manage'
const PERM_GROUP_MANAGE = 'group:manage'

// Header chrome colors come from the identity's header tokens, not the page
// tokens: a pack may run a dark header over a light body.
const HEADER_GHOST =
  'text-(--id-header-fg) hover:text-(--id-header-fg) hover:bg-[color-mix(in_oklab,var(--id-header-fg)_12%,transparent)]'

function NavLink({ to, children }: { to: LinkProps['to']; children: string }) {
  return (
    <Link
      to={to}
      className="border-b-2 border-transparent pt-0.5 text-(--id-header-muted) transition-colors hover:text-(--id-header-fg) data-[status=active]:border-primary data-[status=active]:text-(--id-header-fg)"
    >
      {children}
    </Link>
  )
}

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
  const canManageGroups = me?.permissions.includes(PERM_GROUP_MANAGE) ?? false

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-(--id-header-border) bg-(--id-header-bg) text-(--id-header-fg) backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[var(--id-shell-max,72rem)] items-center gap-6 px-4">
          <Link to="/labs" aria-label="Twinlab home">
            <Wordmark />
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <NavLink to="/labs">Labs</NavLink>
            {canManageUsers && <NavLink to="/users">Users</NavLink>}
            {canManageGroups && <NavLink to="/groups">Groups</NavLink>}
            {/* Self-service credentials — no permission gate. */}
            <NavLink to="/account">Account</NavLink>
            {import.meta.env.DEV && <NavLink to="/styleguide">Styleguide</NavLink>}
          </nav>
          <div className="ml-auto flex items-center gap-1 text-sm">
            <IdentitySwitcher className={HEADER_GHOST} />
            <ThemeToggle className={HEADER_GHOST} />
            <span className="px-2 font-mono text-xs text-(--id-header-muted)">{me?.username}</span>
            <Button
              variant="ghost"
              size="sm"
              className={HEADER_GHOST}
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              <LogOut className="size-4" />
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[var(--id-shell-max,72rem)] flex-1 px-4 py-8">
        <Outlet />
      </main>
      <footer className="border-t">
        <div className="mx-auto flex h-10 max-w-[var(--id-shell-max,72rem)] items-center justify-between px-4 font-mono text-[0.65rem] tracking-wide text-muted-foreground uppercase">
          <span>Twinlab — network twin laboratory</span>
          <span>declarative · reproducible</span>
        </div>
      </footer>
    </div>
  )
}
