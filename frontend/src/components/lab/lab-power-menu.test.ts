// Delta 38: an empty node list means "no containers" only when the
// containers were read. The power menu and the header's Destroy share this
// reason, so unknown never reads as "lab is deployed" on a running lab.
import { expect, it } from 'vitest'

import { containerlessReason } from './lab-power-menu'

const node = { name: 'r1', container: 'clab-x-r1', image: 'frr', state: 'running', mgmt_ip: '' }

it('offers container verbs when the containers are known', () => {
  expect(containerlessReason({ live: true, nodes: [node], status: 'deployed' })).toBeNull()
})

it('names the status when the lab has no containers', () => {
  expect(containerlessReason({ live: true, nodes: [], status: 'destroyed' })).toBe(
    'lab is destroyed',
  )
})

it('says live state is unavailable rather than naming the status', () => {
  expect(containerlessReason({ live: false, nodes: [], status: 'deployed' })).toBe(
    'live state unavailable',
  )
})
