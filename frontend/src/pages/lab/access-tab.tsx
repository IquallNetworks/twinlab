import { useQuery } from '@tanstack/react-query'

import { LabAccess } from '@/components/lab/lab-access'
import { PERM_LAB_GRANT } from '@/lib/lab-permissions'
import { labQueryOptions } from '@/lib/queries'

/** Grants and ownership. Self-guards on lab:grant so a hand-typed URL
 * degrades to a note instead of firing forbidden requests. */
export function AccessTab({ name }: { name: string }) {
  const { data: lab } = useQuery(labQueryOptions(name))
  if (!lab) return null

  if (!lab.permissions.includes(PERM_LAB_GRANT)) {
    return (
      <p className="text-sm text-muted-foreground">
        Managing access to this lab requires the grant permission.
      </p>
    )
  }

  return <LabAccess name={lab.name} owner={lab.owner} />
}
