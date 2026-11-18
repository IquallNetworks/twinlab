// @vitest-environment jsdom
//
// Delta 38: a lab whose live state could not be read has an EMPTY node list,
// and the canvas used to read that as "nothing deployed". Unknown must stay
// unknown, or a running lab is drawn as a dashed, undeployed one.
import { expect, it } from 'vitest'

import { parseTopology } from '@/lib/topology'

import { NOT_DEPLOYED, STATE_UNKNOWN } from './flow-types'
import { buildGraph } from './topology-canvas'

const definition = `
nodes:
  r1: {device: frr}
  r2: {device: frr}
links: [r1-r2]
`

function states(lab: Parameters<typeof buildGraph>[0]): Record<string, unknown> {
  const topology = parseTopology(definition)
  if (topology === null) throw new Error('the test definition did not parse')
  const { nodes } = buildGraph(lab, topology, new Map(), null)
  return Object.fromEntries(nodes.map((node) => [node.id, node.data['state']]))
}

it('reads a node without a container as not deployed when live', () => {
  const running = { name: 'r1', container: 'clab-x-r1', image: 'frr', state: 'running', mgmt_ip: '' }
  expect(states({ live: true, nodes: [running] })).toEqual({ r1: 'running', r2: NOT_DEPLOYED })
})

it('reads every node as unknown when live state is unavailable', () => {
  expect(states({ live: false, nodes: [] })).toEqual({ r1: STATE_UNKNOWN, r2: STATE_UNKNOWN })
})
