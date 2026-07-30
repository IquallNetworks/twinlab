import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

import { FieldError } from '@/components/field-error'
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
import { rolesQueryOptions, usersQueryOptions } from '@/lib/queries'
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
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not create user'),
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
                  <Input
                    id={field.name}
                    type="password"
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
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not update roles'),
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

export function UsersPage() {
  useDocumentTitle('Users')
  const { data: users, isPending, isError, error } = useQuery(usersQueryOptions)

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
                    <EditRolesDialog user={user} />
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
