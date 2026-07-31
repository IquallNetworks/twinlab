import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Zap } from 'lucide-react'
import { Fragment, useState } from 'react'

import { LinkImpairment, linkImpairmentSummary } from '@/components/lab/link-impairment'
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
import type { LabNodeState } from '@/lib/schemas'

/** The lab's logical link table — the server-derived ground truth (netlab's
 * expanded topology), not the client-side definition sketch. Meaningful for any
 * AUTHORED lab (undeployed labs list links with live state unavailable), so the
 * caller gates on "has a definition", not "is deployed".
 *
 * It is also where a link is impaired BIDIRECTIONALLY: a row expands into the
 * shared editor, which writes the same shaping to every endpoint. Impairing one
 * direction only is the Interfaces card's job — netem is per-interface egress,
 * so an interface IS a direction. */
export function LabLinks({
  name,
  nodes,
  enabled,
  canConfigure,
}: {
  name: string
  nodes: LabNodeState[]
  enabled: boolean
  canConfigure: boolean
}) {
  const { data, isFetching, isError, error, refetch } = useQuery({
    ...labLinksQueryOptions(name),
    enabled,
  })
  // One row at a time: the point of the column is that the editor is out of the
  // way until asked for.
  const [openLink, setOpenLink] = useState<number | null>(null)

  // Shouldn't happen behind the `enabled` gate, but a stale cache can race a
  // definition wipe — render it as the not-authored copy, not as a failure.
  const noDefinition = error instanceof ApiError && error.code === 'no_definition'
  // Impairment needs live state to read (and a running node to write), so the
  // column travels with the State column.
  const live = data?.live ?? false
  const columns = live ? 6 : 4

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
                  {live ? <TableHead>State</TableHead> : null}
                  {live ? <TableHead>Impairment</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.links.map((link) => {
                  const open = openLink === link.index
                  return (
                    <Fragment key={link.index}>
                      <TableRow>
                        <TableCell className="font-medium">
                          {link.name ?? `#${link.index}`}
                        </TableCell>
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
                        <TableCell className="font-mono text-xs">
                          {link.prefix_ipv4 ?? '—'}
                        </TableCell>
                        {live ? (
                          <TableCell>
                            <Badge variant={linkOperBadgeVariant(link.oper_state)}>
                              {link.oper_state}
                            </Badge>
                          </TableCell>
                        ) : null}
                        {live ? (
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs">
                                {linkImpairmentSummary(link)}
                              </span>
                              <Button
                                variant="outline"
                                size="sm"
                                aria-expanded={open}
                                onClick={() => setOpenLink(open ? null : link.index)}
                              >
                                {canConfigure ? 'Impair' : 'Show'}
                                {open ? (
                                  <ChevronUp className="size-3.5" />
                                ) : (
                                  <ChevronDown className="size-3.5" />
                                )}
                              </Button>
                            </div>
                          </TableCell>
                        ) : null}
                      </TableRow>
                      {open ? (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={columns} className="bg-muted/30">
                            <LinkImpairment
                              name={name}
                              link={link}
                              nodes={nodes}
                              canConfigure={canConfigure}
                            />
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  )
                })}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  )
}
