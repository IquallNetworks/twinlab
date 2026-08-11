import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from '@tanstack/react-router'
import {
  Boxes,
  KeyRound,
  LayoutDashboard,
  ListTodo,
  LogOut,
  Monitor,
  Moon,
  Plus,
  Search,
  Sun,
  Users,
  UsersRound,
} from 'lucide-react'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { PERM_LAB_EDIT, PERM_LAB_GRANT } from '@/lib/lab-permissions'
import { labQueryOptions, labsQueryOptions, meQueryOptions } from '@/lib/queries'
import { useLogout } from '@/lib/use-logout'

const PERM_USER_MANAGE = 'user:manage'
const PERM_GROUP_MANAGE = 'group:manage'
const PERM_LAB_CREATE = 'lab:create'

/** The current lab's tab shortcuts, gated on the caller's per-lab permissions
 * (same rules as the tab nav). Split out so the lab query only mounts when a
 * lab is actually open. */
function CurrentLabGroup({ name, onDone }: { name: string; onDone: () => void }) {
  const navigate = useNavigate()
  // Already cached by the lab detail layout; this just reads permissions.
  const { data: lab } = useQuery(labQueryOptions(name))
  if (!lab) return null
  const canEdit = lab.permissions.includes(PERM_LAB_EDIT)
  const canGrant = lab.permissions.includes(PERM_LAB_GRANT)
  const go = (fn: () => Promise<void>) => {
    onDone()
    void fn()
  }
  return (
    <CommandGroup heading={name}>
      <CommandItem onSelect={() => go(() => navigate({ to: '/labs/$name/overview', params: { name } }))}>
        Overview
      </CommandItem>
      {canEdit && (
        <CommandItem onSelect={() => go(() => navigate({ to: '/labs/$name/build', params: { name } }))}>
          Build
        </CommandItem>
      )}
      <CommandItem onSelect={() => go(() => navigate({ to: '/labs/$name/nodes', params: { name } }))}>
        Nodes
      </CommandItem>
      <CommandItem onSelect={() => go(() => navigate({ to: '/labs/$name/operations', params: { name } }))}>
        Operations
      </CommandItem>
      {canGrant && (
        <CommandItem onSelect={() => go(() => navigate({ to: '/labs/$name/access', params: { name } }))}>
          Access
        </CommandItem>
      )}
    </CommandGroup>
  )
}

/** Ctrl/Cmd+K palette: navigation, jump-to-lab, theme, session. Lifecycle
 * verbs (deploy/destroy) deliberately stay in their explicit dialogs. */
export function CommandPalette({ className }: { className?: string }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { setTheme } = useTheme()
  const logout = useLogout()
  const { data: me } = useQuery(meQueryOptions)
  // Lazy: only fetched (or refreshed) while the palette is open.
  const { data: labs } = useQuery({ ...labsQueryOptions, enabled: open })
  const params = useParams({ strict: false })
  const currentLab = 'name' in params ? params.name : undefined

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() !== 'k' || !(event.metaKey || event.ctrlKey)) return
      // The web terminal owns its keystrokes (xterm binds Ctrl shortcuts).
      if (event.target instanceof HTMLElement && event.target.closest('.xterm') !== null) return
      event.preventDefault()
      setOpen((value) => !value)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const canManageUsers = me?.permissions.includes(PERM_USER_MANAGE) ?? false
  const canManageGroups = me?.permissions.includes(PERM_GROUP_MANAGE) ?? false
  const canCreate = me?.permissions.includes(PERM_LAB_CREATE) ?? false

  const go = (fn: () => Promise<void>) => {
    setOpen(false)
    void fn()
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className={className}
        onClick={() => setOpen(true)}
        title="Command palette"
        aria-label="Command palette"
      >
        <Search className="size-4" />
        <kbd className="font-mono text-[0.65rem] tracking-wide opacity-70">Ctrl K</kbd>
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Go to a page or lab…" />
        <CommandList>
          <CommandEmpty>Nothing matches.</CommandEmpty>
          <CommandGroup heading="Go to">
            <CommandItem onSelect={() => go(() => navigate({ to: '/' }))}>
              <LayoutDashboard />
              Dashboard
            </CommandItem>
            <CommandItem onSelect={() => go(() => navigate({ to: '/labs' }))}>
              <Boxes />
              Labs
            </CommandItem>
            <CommandItem onSelect={() => go(() => navigate({ to: '/jobs' }))}>
              <ListTodo />
              Jobs
            </CommandItem>
            {canManageUsers && (
              <CommandItem onSelect={() => go(() => navigate({ to: '/users' }))}>
                <Users />
                Users
              </CommandItem>
            )}
            {canManageGroups && (
              <CommandItem onSelect={() => go(() => navigate({ to: '/groups' }))}>
                <UsersRound />
                Groups
              </CommandItem>
            )}
            <CommandItem onSelect={() => go(() => navigate({ to: '/account' }))}>
              <KeyRound />
              Account
            </CommandItem>
          </CommandGroup>
          {currentLab !== undefined && (
            <>
              <CommandSeparator />
              <CurrentLabGroup name={currentLab} onDone={() => setOpen(false)} />
            </>
          )}
          {labs !== undefined && labs.length > 0 && (
            <>
              <CommandSeparator />
              <CommandGroup heading="Labs">
                {labs.map((lab) => (
                  <CommandItem
                    key={lab.name}
                    // The index route redirects to the caller's role-aware tab.
                    onSelect={() => go(() => navigate({ to: '/labs/$name', params: { name: lab.name } }))}
                  >
                    <span className="font-mono">{lab.name}</span>
                    <span className="text-xs text-muted-foreground">{lab.status}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}
          {canCreate && (
            <>
              <CommandSeparator />
              <CommandGroup heading="Actions">
                <CommandItem onSelect={() => go(() => navigate({ to: '/labs', search: { new: true } }))}>
                  <Plus />
                  Create lab
                </CommandItem>
              </CommandGroup>
            </>
          )}
          <CommandSeparator />
          <CommandGroup heading="Theme">
            <CommandItem
              onSelect={() => {
                setOpen(false)
                setTheme('light')
              }}
            >
              <Sun />
              Light
            </CommandItem>
            <CommandItem
              onSelect={() => {
                setOpen(false)
                setTheme('dark')
              }}
            >
              <Moon />
              Dark
            </CommandItem>
            <CommandItem
              onSelect={() => {
                setOpen(false)
                setTheme('system')
              }}
            >
              <Monitor />
              System
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Session">
            <CommandItem
              onSelect={() => {
                setOpen(false)
                logout.mutate()
              }}
            >
              <LogOut />
              Sign out
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </>
  )
}
