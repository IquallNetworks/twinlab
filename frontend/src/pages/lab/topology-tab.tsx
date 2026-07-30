import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo } from 'react'

import { TopologyCanvas } from '@/components/lab/topology/topology-canvas'
import { Card, CardContent } from '@/components/ui/card'
import { labQueryOptions } from '@/lib/queries'
import { parseTopology } from '@/lib/topology'

function Notice({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

/** The lab drawn from its stored definition, with the live overlay. A lab
 * that isn't deployed still renders (every node "not deployed") — the
 * topology doubles as documentation of the definition. */
export function TopologyTab({ name }: { name: string }) {
  // Same cached query the layout resolved; never pending in practice.
  const { data: lab } = useQuery(labQueryOptions(name))
  const topology = useMemo(
    () => (lab?.definition != null ? parseTopology(lab.definition) : null),
    [lab?.definition],
  )
  if (!lab) return null

  if (lab.definition === null) {
    return (
      <Notice>
        No definition yet — author one on the{' '}
        <Link to="/labs/$name/overview" params={{ name }} className="underline hover:text-foreground">
          Overview
        </Link>{' '}
        tab, and the topology renders here.
      </Notice>
    )
  }

  if (topology === null) {
    return (
      <Notice>
        The stored definition is not valid YAML —{' '}
        <Link to="/labs/$name/overview" params={{ name }} className="underline hover:text-foreground">
          view it on Overview
        </Link>
        .
      </Notice>
    )
  }

  if (topology.nodes.length === 0) {
    return <Notice>The definition declares no nodes.</Notice>
  }

  return (
    <Card className="py-0">
      <CardContent className="p-0">
        <div className="h-[max(28rem,calc(100vh-22rem))]">
          <TopologyCanvas lab={lab} topology={topology} />
        </div>
      </CardContent>
    </Card>
  )
}
