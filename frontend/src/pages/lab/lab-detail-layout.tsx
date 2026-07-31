import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import { ChevronLeft } from 'lucide-react'

import { LabHeader } from '@/components/lab/lab-header'
import { LabTabNav } from '@/components/lab/lab-tab-nav'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { labQueryOptions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/use-document-title'

function BackLink() {
  return (
    <Link to="/labs" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
      <ChevronLeft className="size-4" />
      Labs
    </Link>
  )
}

/** Layout for /labs/$name: loads the lab, owns the pending/404/error states,
 * and renders the header + tab strip above the active tab's outlet. Tab pages
 * read the same cached query, so the data is already there when they mount.
 *
 * The chrome is deliberately tight — header and tabs read as ONE navigation
 * block (the way back is the header's breadcrumb, not a row of its own), so the
 * tab content starts high on the page. */
export function LabDetailLayout({ name }: { name: string }) {
  useDocumentTitle(name)
  const { data: lab, isPending, isError, error } = useQuery(labQueryOptions(name))

  if (isPending) {
    return (
      <div className="flex flex-col gap-6">
        <BackLink />
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (isError) {
    const notFound = error instanceof ApiError && error.status === 404
    return (
      <div className="flex flex-col gap-6">
        <BackLink />
        <p className="text-sm text-destructive">
          {notFound ? `No lab named ${name}.` : error instanceof Error ? error.message : 'Failed to load lab'}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <LabHeader lab={lab} />
        <LabTabNav name={lab.name} permissions={lab.permissions} />
      </div>
      <Outlet />
    </div>
  )
}
