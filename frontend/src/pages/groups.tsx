import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

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
import { groupsQueryOptions, principalsQueryOptions, rolesQueryOptions } from '@/lib/queries'
import { globalRoles } from '@/lib/roles'
import type { GroupSummary } from '@/lib/schemas'

function toggle(list: string[], value: string, checked: boolean): string[] {
  const set = new Set(list)
  if (checked) set.add(value)
  else set.delete(value)
  return [...set]
}

function CreateGroupDialog() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const queryClient = useQueryClient()

  const create = useMutation({
    mutationFn: () => api.createGroup(name, description),
    onSuccess: async (group) => {
      await queryClient.invalidateQueries({ queryKey: groupsQueryOptions.queryKey })
      toast.success(`Created group ${group.name}`)
      setOpen(false)
      setName('')
      setDescription('')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not create group'),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>New group</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New group</DialogTitle>
          <DialogDescription>A named set of users, granted access as a unit.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="group-name">Name</Label>
            <Input id="group-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="group-desc">Description</Label>
            <Input
              id="group-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button onClick={() => create.mutate()} disabled={name === '' || create.isPending}>
            {create.isPending ? 'Creating…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditMembersDialog({ group }: { group: GroupSummary }) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>(group.members.map((m) => m.id))
  const queryClient = useQueryClient()
  const { data: principals } = useQuery(principalsQueryOptions)

  const save = useMutation({
    mutationFn: () => api.setGroupMembers(group.id, selected),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupsQueryOptions.queryKey })
      toast.success(`Updated members of ${group.name}`)
      setOpen(false)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not update members'),
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setSelected(group.members.map((m) => m.id))
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Members
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Members of {group.name}</DialogTitle>
          <DialogDescription>Select the users in this group.</DialogDescription>
        </DialogHeader>
        <div className="flex max-h-72 flex-col gap-2 overflow-y-auto py-4">
          {(principals?.users ?? []).map((u) => {
            const id = `member-${group.id}-${u.id}`
            return (
              <div key={u.id} className="flex items-center gap-2">
                <Checkbox
                  id={id}
                  checked={selected.includes(u.id)}
                  onCheckedChange={(c) => setSelected((prev) => toggle(prev, u.id, c === true))}
                />
                <Label htmlFor={id} className="font-normal">
                  {u.name}
                </Label>
              </div>
            )
          })}
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditGroupRolesDialog({ group }: { group: GroupSummary }) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>(group.roles)
  const queryClient = useQueryClient()
  const { data: roleCatalog } = useQuery(rolesQueryOptions)
  const globalRoleNames = globalRoles(roleCatalog ?? []).map((r) => r.name)

  const save = useMutation({
    mutationFn: () => api.setGroupRoles(group.id, selected),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupsQueryOptions.queryKey })
      toast.success(`Updated roles for ${group.name}`)
      setOpen(false)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not update roles'),
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) setSelected(group.roles)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Roles
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Global roles for {group.name}</DialogTitle>
          <DialogDescription>Roles every member inherits, on every lab.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-4 py-4">
          {globalRoleNames.map((role) => {
            const id = `grouprole-${group.id}-${role}`
            return (
              <div key={role} className="flex items-center gap-2">
                <Checkbox
                  id={id}
                  checked={selected.includes(role)}
                  onCheckedChange={(c) => setSelected((prev) => toggle(prev, role, c === true))}
                />
                <Label htmlFor={id} className="font-normal">
                  {role}
                </Label>
              </div>
            )
          })}
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeleteGroupButton({ group }: { group: GroupSummary }) {
  const queryClient = useQueryClient()
  const del = useMutation({
    mutationFn: () => api.deleteGroup(group.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupsQueryOptions.queryKey })
      toast.success(`Deleted group ${group.name}`)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not delete group'),
  })
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="sm" disabled={del.isPending}>
          Delete
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {group.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            This removes the group and every grant made to it. Members keep their own grants.
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

export function GroupsPage() {
  const { data: groups, isPending, isError, error } = useQuery(groupsQueryOptions)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Groups</h1>
        <CreateGroupDialog />
      </div>

      {isError ? (
        <p className="text-destructive text-sm">
          {error instanceof Error ? error.message : 'Failed to load groups'}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Members</TableHead>
              <TableHead>Roles</TableHead>
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
            ) : groups.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground text-center">
                  No groups yet.
                </TableCell>
              </TableRow>
            ) : (
              groups.map((group) => (
                <TableRow key={group.id}>
                  <TableCell className="font-medium">
                    {group.name}
                    {group.description && (
                      <div className="text-muted-foreground text-xs">{group.description}</div>
                    )}
                  </TableCell>
                  <TableCell>
                    {group.members.length === 0 ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <span className="text-sm">{group.members.map((m) => m.username).join(', ')}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {group.roles.length === 0 ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        group.roles.map((role) => (
                          <Badge key={role} variant="secondary">
                            {role}
                          </Badge>
                        ))
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <EditMembersDialog group={group} />
                      <EditGroupRolesDialog group={group} />
                      <DeleteGroupButton group={group} />
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
