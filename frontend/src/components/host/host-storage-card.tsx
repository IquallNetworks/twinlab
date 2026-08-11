import { useQuery } from '@tanstack/react-query'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatBytes } from '@/lib/format'
import { dockerUsageQueryOptions } from '@/lib/queries'

// The daemon's own vocabulary, given the operator's words. An unknown kind
// still renders (the daemon may grow one), just under its raw slug.
const KIND_LABELS: Record<string, string> = {
  images: 'Node & service images',
  containers: 'Container layers',
  volumes: 'Volumes',
  build_cache: 'Build cache',
}

/** What Docker is holding on disk (delta 30), mirroring `docker system df` —
 * the number that actually bites, since node images are large and nothing
 * else in the UI says what they cost. */
export function HostStorageCard() {
  const query = useQuery(dockerUsageQueryOptions)
  const usage = query.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Storage</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {query.isError ? (
          <p className="text-sm text-muted-foreground">
            The container daemon&rsquo;s usage could not be read. {query.error.message}
          </p>
        ) : usage === undefined ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Holding</TableHead>
                  <TableHead className="text-right">In use</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead className="text-right">Reclaimable</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usage.disk.map((entry) => (
                  <TableRow key={entry.kind}>
                    <TableCell>{KIND_LABELS[entry.kind] ?? entry.kind}</TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {entry.active}/{entry.total}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatBytes(entry.size_bytes)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs text-muted-foreground">
                      {formatBytes(entry.reclaimable_bytes)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="font-mono text-[0.65rem] text-muted-foreground">
              {usage.containers_running} of {usage.containers_total} containers running ·{' '}
              {usage.images_total} images · {usage.root_dir}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
