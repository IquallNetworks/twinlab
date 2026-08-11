import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
import { PasswordInput } from '@/components/password-input'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import { toastError } from '@/lib/error-toast'
import { meQueryOptions, rolesQueryOptions, usersQueryOptions } from '@/lib/queries'
import { globalRoles } from '@/lib/roles'
import type { UserSummary } from '@/lib/schemas'
import { useDocumentTitle } from '@/lib/use-document-title'

function RoleCheckboxes({
  roles,
  selected,
  onToggle,
  idPrefix,
}: {
  roles: string[]
  selected: string[]
  onToggle: (role: string, checked: boolean) => void
  idPrefix: string
}) {
  return (
    <div className="flex flex-wrap gap-4">
      {roles.map((role) => {
        const id = `${idPrefix}-${role}`
        return (
          <div key={role} className="flex items-center gap-2">
            <Checkbox
              id={id}
              checked={selected.includes(role)}
              onCheckedChange={(c) => onToggle(role, c === true)}
            />
            <Label htmlFor={id} className="font-normal capitalize">
              {role}
            </Label>
          </div>
        )
      })}
    </div>
  )
}

function toggle(list: string[], role: string, checked: boolean): string[] {
  const set = new Set(list)
  if (checked) set.add(role)
  else set.delete(role)
  return [...set]
}

const createUserSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
  roles: z.array(z.string()),
})

function CreateUserDialog() {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const { data: roleCatalog } = useQuery(rolesQueryOptions)
  const globalRoleNames = globalRoles(roleCatalog ?? []).map((r) => r.name)

  const create = useMutation({
    mutationFn: (value: z.infer<typeof createUserSchema>) => api.createUser(value),
    onSuccess: async (user) => {
      await queryClient.invalidateQueries({ queryKey: usersQueryOptions.queryKey })
      toast.success(`Created user ${user.username}`)
      setOpen(false)
    },
    onError: (err) => toastError(err, 'Could not create user'),
  })

  const form = useForm({
    defaultValues: { username: '', password: '', roles: [] as string[] },
    validators: { onSubmit: createUserSchema },
    onSubmit: async ({ value }) => {
      await create.mutateAsync(value)
    },
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) form.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button>New user</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            e.stopPropagation()
            void form.handleSubmit()
          }}
        >
          <DialogHeader>
            <DialogTitle>New user</DialogTitle>
            <DialogDescription>Create an account and assign roles.</DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4 py-4">
            <form.Field name="username">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={field.name}>Username</Label>
                  <Input
                    id={field.name}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>

            <form.Field name="password">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={field.name}>Password</Label>
                  <PasswordInput
                    id={field.name}
                    autoComplete="new-password"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>

            <form.Field name="roles">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label>Roles</Label>
                  <RoleCheckboxes
                    idPrefix="create"
                    roles={globalRoleNames}
                    selected={field.state.value}
                    onToggle={(role, checked) =>
                      field.handleChange(toggle(field.state.value, role, checked))
                    }
                  />
                </div>
              )}
            </form.Field>
          </div>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <form.Subscribe selector={(s) => ({ canSubmit: s.canSubmit, isSubmitting: s.isSubmitting })}>
              {({ canSubmit, isSubmitting }) => (
                <Button type="submit" disabled={!canSubmit || isSubmitting}>
                  {isSubmitting ? 'Creating…' : 'Create'}
                </Button>
              )}
            </form.Subscribe>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function EditRolesDialog({ user }: { user: UserSummary }) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>(user.roles)
  const queryClient = useQueryClient()
  const { data: roleCatalog } = useQuery(rolesQueryOptions)
  const globalRoleNames = globalRoles(roleCatalog ?? []).map((r) => r.name)

  const save = useMutation({
    mutationFn: (roles: string[]) => api.setRoles(user.id, roles),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: usersQueryOptions.queryKey })
      toast.success(`Updated roles for ${user.username}`)
      setOpen(false)
    },
    onError: (err) => toastError(err, 'Could not update roles'),
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        // Reset to the user's current roles whenever the dialog (re)opens.
        if (next) setSelected(user.roles)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Edit roles
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Roles for {user.username}</DialogTitle>
          <DialogDescription>Select the roles this user should hold.</DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <RoleCheckboxes
            idPrefix={`edit-${user.id}`}
            roles={globalRoleNames}
            selected={selected}
            onToggle={(role, checked) => setSelected((prev) => toggle(prev, role, checked))}
          />
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button onClick={() => save.mutate(selected)} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// The 8-character floor mirrors the server's own constraint; confirm-match is
// ours (the wire takes a single password).
const resetPasswordSchema = z
  .object({
    next: z.string().min(8, 'Password must be at least 8 characters'),
    confirm: z.string(),
  })
  .refine((value) => value.next === value.confirm, {
    message: 'Passwords do not match',
    path: ['confirm'],
  })

/** Administrative reset of someone else's password. The current password is
 * not asked for — an admin does not know it — and every one of the target's
 * sessions is signed out, so they are locked out until told the new one.
 *
 * Not offered on the caller's own row: the same route revokes the session
 * making the request, so a self-reset would sign the admin out mid-click. The
 * Account page's self-service change is the one that keeps this session, and
 * is the only place a password change asks for the current one. */
function ResetPasswordDialog({ user, isSelf }: { user: UserSummary; isSelf: boolean }) {
  const [open, setOpen] = useState(false)

  const reset = useMutation({
    mutationFn: (value: z.infer<typeof resetPasswordSchema>) =>
      api.setUserPassword(user.id, value.next),
    onSuccess: () => {
      toast.success(`Password reset for ${user.username}`)
      setOpen(false)
    },
    onError: (err) => toastError(err, 'Could not reset password'),
  })

  const form = useForm({
    defaultValues: { next: '', confirm: '' },
    validators: { onSubmit: resetPasswordSchema },
    onSubmit: ({ value }) => reset.mutate(value),
  })

  if (isSelf) {
    return (
      <Button
        variant="outline"
        size="sm"
        disabled
        title="Change your own password from Account — a reset here would sign you out"
      >
        Reset password
      </Button>
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) form.reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Reset password
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            e.stopPropagation()
            void form.handleSubmit()
          }}
        >
          <DialogHeader>
            <DialogTitle>Reset password for {user.username}</DialogTitle>
            <DialogDescription>
              Set a new password without knowing the current one. Every session {user.username} has
              open is signed out, so tell them the new password. API keys and SSH keys are separate
              credentials and keep working.
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4 py-4">
            <form.Field name="next">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={field.name}>New password</Label>
                  <PasswordInput
                    id={field.name}
                    autoComplete="new-password"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>

            <form.Field name="confirm">
              {(field) => (
                <div className="flex flex-col gap-2">
                  <Label htmlFor={field.name}>Confirm new password</Label>
                  <PasswordInput
                    id={field.name}
                    autoComplete="new-password"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                  />
                  <FieldError errors={field.state.meta.errors} />
                </div>
              )}
            </form.Field>
          </div>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={reset.isPending}>
              {reset.isPending ? 'Resetting…' : 'Reset password'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// The server's own `last_admin` rule (409 on deactivate and on delete): an
// ACTIVE user holding a direct global admin binding, with no OTHER active user
// holding one. A UserSummary's `roles` is exactly that set of direct global
// bindings, so this mirrors the rule rather than approximating it.
function isLastActiveAdmin(user: UserSummary, users: UserSummary[]): boolean {
  if (!user.is_active || !user.roles.includes('admin')) return false
  return !users.some((u) => u.id !== user.id && u.is_active && u.roles.includes('admin'))
}

/** Why a row refuses a lifecycle verb, or null when it allows it.
 *
 * Both rules are the server's — it answers 409 `last_admin`, and either verb
 * aimed at your own account would end the session making the request — but a
 * disabled button carrying the reason beats a toast after the click. */
function blockedReason(
  verb: 'deactivate' | 'delete',
  user: UserSummary,
  isSelf: boolean,
  users: UserSummary[],
): string | null {
  if (isSelf) return `You cannot ${verb} the account you are signed in as`
  if (isLastActiveAdmin(user, users)) {
    return `Twinlab keeps one active administrator — you cannot ${verb} the last one`
  }
  return null
}

/** The reversible half of delete. Deactivating suspends every credential the
 * account has — sessions, API keys, SSH keys — while leaving the record, its
 * roles and its labs alone, so only that direction asks for confirmation;
 * activating again restores exactly what it suspended. */
function SetActiveButton({ user, blocked }: { user: UserSummary; blocked: string | null }) {
  const queryClient = useQueryClient()
  const setActive = useMutation({
    mutationFn: (isActive: boolean) => api.setUserActive(user.id, isActive),
    onSuccess: async (updated) => {
      await queryClient.invalidateQueries({ queryKey: usersQueryOptions.queryKey })
      toast.success(
        updated.is_active ? `Activated ${user.username}` : `Deactivated ${user.username}`,
      )
    },
    onError: (err) => toastError(err, 'Could not change status'),
  })

  if (!user.is_active) {
    return (
      <Button
        variant="outline"
        size="sm"
        disabled={setActive.isPending}
        onClick={() => setActive.mutate(true)}
      >
        Activate
      </Button>
    )
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={blocked !== null || setActive.isPending}
          title={blocked ?? undefined}
        >
          Deactivate
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Deactivate {user.username}?</AlertDialogTitle>
          <AlertDialogDescription>
            Signs out their sessions and stops their API keys and SSH keys authorizing. The
            account, its roles and the labs it owns are untouched — activating again restores
            access.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={() => setActive.mutate(false)}>Deactivate</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** Deletion, which unlike deactivation cannot be undone — and unlike a group's
 * deletion is not only about grants: the account's credentials and role
 * bindings go with it, while the labs it owns SURVIVE with no owner (the
 * server nulls the reference rather than cascading). The dialog says so,
 * because an ownerless lab is a surprise worth not discovering later. */
function DeleteUserButton({ user, blocked }: { user: UserSummary; blocked: string | null }) {
  const queryClient = useQueryClient()
  const del = useMutation({
    mutationFn: () => api.deleteUser(user.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: usersQueryOptions.queryKey })
      toast.success(`Deleted user ${user.username}`)
    },
    onError: (err) => toastError(err, 'Could not delete user'),
  })

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          disabled={blocked !== null || del.isPending}
          title={blocked ?? undefined}
        >
          Delete
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {user.username}?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the account with its sessions, API keys, SSH keys and every role it
            holds. Labs it owns are kept, with no owner. Deactivating instead suspends access and
            can be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={() => del.mutate()}>Delete</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function UsersPage() {
  useDocumentTitle('Users')
  const { data: users, isPending, isError, error } = useQuery(usersQueryOptions)
  // `me` carries no id, but usernames are unique — enough to spot the caller's
  // own row, which must not offer a reset, a deactivation or a delete: all
  // three would act on the session making the request.
  const { data: me } = useQuery(meQueryOptions)
  const isSelf = (user: UserSummary) => user.username === me?.username

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-heading text-2xl font-semibold">Users</h1>
          {users && (
            <span className="font-mono text-xs text-muted-foreground">
              {users.length} {users.length === 1 ? 'account' : 'accounts'}
            </span>
          )}
        </div>
        <CreateUserDialog />
      </div>

      {isError ? (
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : 'Failed to load users'}
        </p>
      ) : (
        <div className="border bg-card/60">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Username</TableHead>
              <TableHead>Roles</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={4}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-10 text-center text-muted-foreground">
                  <span className="font-mono text-xs tracking-wide uppercase">no users</span>
                </TableCell>
              </TableRow>
            ) : (
              users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="font-mono text-sm font-medium">{user.username}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {user.roles.length === 0 ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        user.roles.map((role) => (
                          <Badge
                            key={role}
                            variant={role === 'admin' ? 'default' : 'secondary'}
                            className="capitalize"
                          >
                            {role}
                          </Badge>
                        ))
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={user.is_active ? 'secondary' : 'outline'}>
                      {user.is_active ? 'active' : 'inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <EditRolesDialog user={user} />
                      <ResetPasswordDialog user={user} isSelf={isSelf(user)} />
                      <SetActiveButton
                        user={user}
                        blocked={blockedReason('deactivate', user, isSelf(user), users)}
                      />
                      <DeleteUserButton
                        user={user}
                        blocked={blockedReason('delete', user, isSelf(user), users)}
                      />
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        </div>
      )}
    </div>
  )
}
