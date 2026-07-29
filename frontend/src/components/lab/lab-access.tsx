import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import {
  labGrantsQueryOptions,
  labQueryOptions,
  labsQueryOptions,
  principalsQueryOptions,
  rolesQueryOptions,
} from '@/lib/queries'
import { labRoles } from '@/lib/roles'
import type { Principal } from '@/lib/schemas'

/** Delegate access to a lab: view/add/remove role grants (to users or groups) and
 * transfer ownership. Shown only when the caller holds lab:grant on the lab; the
 * backend still enforces anti-escalation and owner-equivalence for transfer. */
export function LabAccess({ name, owner }: { name: string; owner: Principal | null }) {
  const queryClient = useQueryClient()
  const { data: grants } = useQuery(labGrantsQueryOptions(name))
  const { data: principals } = useQuery(principalsQueryOptions)
  const { data: roleCatalog } = useQuery(rolesQueryOptions)
  const assignableRoles = labRoles(roleCatalog ?? []).map((r) => r.name)

  const [principalType, setPrincipalType] = useState<'user' | 'group'>('user')
  const [principalId, setPrincipalId] = useState('')
  const [role, setRole] = useState('')
  const [newOwner, setNewOwner] = useState('')

  const principalOptions = principalType === 'user' ? principals?.users : principals?.groups

  const invalidateGrants = () =>
    queryClient.invalidateQueries({ queryKey: labGrantsQueryOptions(name).queryKey })

  const addGrant = useMutation({
    mutationFn: () =>
      api.createGrant(name, { principal_type: principalType, principal_id: principalId, role }),
    onSuccess: async () => {
      await invalidateGrants()
      setPrincipalId('')
      setRole('')
      toast.success('Access granted')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Grant failed'),
  })

  const removeGrant = useMutation({
    mutationFn: (id: string) => api.deleteGrant(name, id),
    onSuccess: async () => {
      await invalidateGrants()
      toast.success('Access removed')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not remove access'),
  })

  const transfer = useMutation({
    mutationFn: () => api.transferOwner(name, newOwner),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: labQueryOptions(name).queryKey }),
        queryClient.invalidateQueries({ queryKey: labsQueryOptions.queryKey }),
      ])
      setNewOwner('')
      toast.success('Ownership transferred')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Transfer failed'),
  })

  const canAdd = principalId !== '' && role !== '' && !addGrant.isPending

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Access</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="text-sm">
          <span className="text-muted-foreground">Owner: </span>
          <span className="font-medium">{owner?.name ?? '—'}</span>
        </div>

        {/* Current grants */}
        {grants && grants.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Principal</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="w-0" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {grants.map((g) => (
                <TableRow key={g.id}>
                  <TableCell className="font-medium">{g.principal_name ?? g.principal_id}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{g.principal_type}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{g.role}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      title="Remove grant"
                      onClick={() => removeGrant.mutate(g.id)}
                      disabled={removeGrant.isPending}
                    >
                      <X className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-muted-foreground text-sm">No grants yet — the owner has full access.</p>
        )}

        {/* Add grant */}
        <div className="flex flex-wrap items-end gap-2">
          <Select
            value={principalType}
            onValueChange={(v) => {
              setPrincipalType(v as 'user' | 'group')
              setPrincipalId('')
            }}
          >
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="user">User</SelectItem>
              <SelectItem value="group">Group</SelectItem>
            </SelectContent>
          </Select>

          <Select value={principalId} onValueChange={setPrincipalId}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder={principalType === 'user' ? 'User' : 'Group'} />
            </SelectTrigger>
            <SelectContent>
              {(principalOptions ?? []).map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={role} onValueChange={setRole}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder="Role" />
            </SelectTrigger>
            <SelectContent>
              {assignableRoles.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button onClick={() => addGrant.mutate()} disabled={!canAdd}>
            {addGrant.isPending ? 'Granting…' : 'Grant'}
          </Button>
        </div>

        {/* Transfer ownership — the backend rejects this unless the caller is
            owner-equivalent, so a plain lab:grant holder will get an error toast. */}
        <div className="flex flex-wrap items-end gap-2 border-t pt-4">
          <div className="flex flex-col gap-1">
            <span className="text-muted-foreground text-xs">Transfer ownership</span>
            <Select value={newOwner} onValueChange={setNewOwner}>
              <SelectTrigger className="w-44">
                <SelectValue placeholder="New owner" />
              </SelectTrigger>
              <SelectContent>
                {(principals?.users ?? []).map((u) => (
                  <SelectItem key={u.id} value={u.id}>
                    {u.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="outline"
            onClick={() => transfer.mutate()}
            disabled={newOwner === '' || transfer.isPending}
          >
            {transfer.isPending ? 'Transferring…' : 'Transfer'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
