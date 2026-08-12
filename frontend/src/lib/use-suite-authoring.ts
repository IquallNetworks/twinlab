import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { parseBuildDoc } from '@/lib/build-doc'
import type { CatalogDevice } from '@/lib/device-catalog'
import { labFactsQueryOptions, labQueryOptions } from '@/lib/queries'
import type { SuiteContext } from '@/lib/test-suite-model'
import { useDeviceCatalog } from '@/lib/use-device-catalog'

/** Everything the suite editors need to know about the lab they are authoring
 * against: what it declares, what those nodes are, and what a template may
 * read. Resolved once by the Tests tab and handed down, so a dialog opens with
 * its vocabulary already in hand rather than starting a fetch. */
export interface SuiteAuthoring {
  /** What `validateSuites` gates on. */
  context: SuiteContext
  nodes: readonly string[]
  deviceByNode: ReadonlyMap<string, string>
  groups: ReadonlyMap<string, readonly string[]>
  catalog: readonly CatalogDevice[]
  /** The fact namespace, for command completion and the Try target. Undefined
   * until the query settles, and on a lab with no definition. */
  facts?: Record<string, Record<string, unknown>>
  /** Try and Run need a live lab; authoring does not. */
  deployed: boolean
}

export function useSuiteAuthoring(name: string): SuiteAuthoring {
  const { data: lab } = useQuery(labQueryOptions(name))
  const catalog = useDeviceCatalog()
  // One query, two jobs (delta 32): the resolved groups a test targets by, and
  // the namespace the command field completes against. Only for a lab with a
  // definition to derive them from — a bare record 409s, which is not an error
  // worth retrying or reporting.
  const factsQuery = useQuery({
    ...labFactsQueryOptions(name),
    enabled: lab?.definition != null,
    retry: false,
  })

  const groups = useMemo(
    () => new Map<string, readonly string[]>(Object.entries(factsQuery.data?.groups ?? {})),
    [factsQuery.data],
  )

  // Nodes come from the DEFINITION, not live state: a suite is authored
  // against what the lab declares, and may be written before it is deployed.
  const { nodes, deviceByNode } = useMemo(() => {
    const byNode = new Map<string, string>()
    if (lab?.definition == null) return { nodes: [] as string[], deviceByNode: byNode }
    const parsed = parseBuildDoc(
      lab.definition,
      catalog.devices.map((entry) => entry.device),
    )
    if (!parsed.ok) return { nodes: [] as string[], deviceByNode: byNode }
    for (const node of parsed.doc.nodes) {
      const device = node.device ?? parsed.doc.defaultDevice
      if (device != null) byNode.set(node.name, device)
    }
    return { nodes: parsed.doc.nodes.map((node) => node.name), deviceByNode: byNode }
  }, [lab?.definition, catalog.devices])

  const context: SuiteContext = useMemo(
    () => ({
      nodes,
      deviceByNode,
      capabilities: new Map(
        catalog.devices.map((device) => [
          device.device,
          { cliMode: device.cliMode, textfsm: device.textfsm },
        ]),
      ),
      groups,
    }),
    [nodes, deviceByNode, catalog.devices, groups],
  )

  return {
    context,
    nodes,
    deviceByNode,
    groups,
    catalog: catalog.devices,
    facts: factsQuery.data?.nodes,
    deployed: lab?.status === 'deployed',
  }
}
