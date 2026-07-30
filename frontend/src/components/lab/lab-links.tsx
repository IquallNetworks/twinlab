import { useQuery } from '@tanstack/react-query'
import { Zap } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ApiError } from '@/lib/api'
import { linkOperBadgeVariant } from '@/lib/format'
import { labLinksQueryOptions } from '@/lib/queries'

/** The lab's logical link table — the server-derived ground truth (netlab's
 * expanded topology), not the client-side definition sketch. Meaningful for any
 * AUTHORED lab (undeployed labs list links with live state unavailable), so the
 * caller gates on "has a definition", not "is deployed". */
export function LabLinks({ name, enabled }: { name: string; enabled: boolean }) {
  const { data, isFetching, isError, error, refetch } = useQuery({
    ...labLinksQueryOptions(name),
    enabled,
  })

  // Shouldn't happen behind the `enabled` gate, but a stale cache can race a
  // definition wipe — render it as the not-authored copy, not as a failure.
  const noDefinition = error instanceof ApiError && error.code === 'no_definition'
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Links</CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          disabled={!enabled || isFetching}
        >
          {isFetching ? 'Loading…' : 'Refresh'}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!enabled || noDefinition ? (
          <p className="text-muted-foreground text-sm">
            The link table appears once a definition is authored.
          </p>
        ) : isError ? (
          <p className="text-destructive text-sm">
            {error instanceof Error ? error.message : 'Failed to load links'}
          </p>
        ) : !data ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : data.links.length === 0 ? (
          <p className="text-muted-foreground text-sm">The definition declares no links.</p>
        ) : (
          <>
            {!data.live ? (
              <p className="text-muted-foreground text-sm">
                Live state unavailable — link states show while the lab is deployed and reachable.
              </p>
            ) : null}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Link</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Endpoints</TableHead>
                  <TableHead>Prefix</TableHead>
                  {data.live ? <TableHead>State</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.links.map((link) => (
                  <TableRow key={link.index}>
                    <TableCell className="font-medium">{link.name ?? `#${link.index}`}</TableCell>
                    <TableCell className="text-muted-foreground">{link.type}</TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-0.5">
                        {link.endpoints.map((endpoint) => (
                          <span
                            key={`${endpoint.node}:${endpoint.interface}`}
                            className="font-mono text-xs"
                          >
                            {endpoint.node}:{endpoint.interface}
                            {endpoint.ipv4 ? (
                              <span className="text-muted-foreground"> {endpoint.ipv4}</span>
                            ) : null}
                            {endpoint.impairment ? (
                              <Zap
                                className="text-primary ml-1 inline size-3"
                                aria-label="impaired"
                              />
                            ) : null}
                          </span>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{link.prefix_ipv4 ?? '—'}</TableCell>
                    {data.live ? (
                      <TableCell>
                        <Badge variant={linkOperBadgeVariant(link.oper_state)}>
                          {link.oper_state}
                        </Badge>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  )
}
