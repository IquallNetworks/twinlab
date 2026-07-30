// The builder's curated device catalog. Deliberately client-side and limited
// to the devices this deployment has actually proven (CLAUDE.md "Current
// State"); a backend catalog endpoint — what can THIS deployment run — is the
// parked replacement (docs/frontend-rework.md).

// The builder's module set: the netlab modules the visual builder can
// represent (enough to build examples/mpls-l3vpn.yml). Everything else is
// text-editor territory.
export const BUILDER_MODULES = ['ospf', 'bgp', 'mpls', 'vrf'] as const
export type BuilderModule = (typeof BUILDER_MODULES)[number]

export interface CatalogDevice {
  device: 'vyos' | 'iol' | 'frr' | 'linux'
  label: string
  kind: 'router' | 'host'
  // Which of the builder's modules the device can run, per
  // `netlab show module-support` — the builder greys out the rest.
  modules: readonly BuilderModule[]
}

export const DEVICE_CATALOG: readonly CatalogDevice[] = [
  { device: 'vyos', label: 'VyOS', kind: 'router', modules: BUILDER_MODULES },
  { device: 'iol', label: 'Cisco IOL', kind: 'router', modules: BUILDER_MODULES },
  { device: 'frr', label: 'FRR', kind: 'router', modules: BUILDER_MODULES },
  { device: 'linux', label: 'Linux host', kind: 'host', modules: [] },
]

export function catalogDevice(device: string): CatalogDevice | undefined {
  return DEVICE_CATALOG.find((entry) => entry.device === device)
}

export function deviceSupports(device: string, module: BuilderModule): boolean {
  return catalogDevice(device)?.modules.includes(module) ?? false
}
