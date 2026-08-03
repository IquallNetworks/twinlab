// The builder's device catalog SHAPE and module set. Since delta 18 the
// device list itself comes from the server (`GET /catalog` — what THIS
// deployment can run, with live image presence) via use-device-catalog.ts;
// this module keeps the pure pieces: the builder's representable module set,
// the catalog entry shape, list-parameterized lookups, and a static fallback
// used only until the server catalog resolves (or when it errors).
//
// Pure module (no React, no zod) so lib/build-doc.ts stays runnable under a
// plain node bundle.

// The builder's module set: the netlab modules the visual builder can
// represent (enough to build examples/mpls-l3vpn.yml). Everything else is
// text-editor territory.
export const BUILDER_MODULES = ['ospf', 'bgp', 'mpls', 'vrf'] as const
export type BuilderModule = (typeof BUILDER_MODULES)[number]

export interface CatalogDevice {
  device: string
  label: string
  kind: 'router' | 'host'
  // Which of the builder's modules the device can run (the server catalog's
  // netlab matrix intersected with BUILDER_MODULES) — the builder greys out
  // the rest.
  modules: readonly BuilderModule[]
  // Whether the device's default image exists on the host Docker daemon.
  // null = unknown (catalog not live, or the static fallback).
  imagePresent: boolean | null
}

// Used only until `GET /catalog` answers: the last-known supported set (the
// tested platforms + linux host), with image presence unknown. The server
// catalog is authoritative the moment it resolves.
export const FALLBACK_DEVICE_CATALOG: readonly CatalogDevice[] = [
  { device: 'vyos', label: 'VyOS', kind: 'router', modules: BUILDER_MODULES, imagePresent: null },
  {
    device: 'iol',
    label: 'Cisco IOL',
    kind: 'router',
    modules: BUILDER_MODULES,
    imagePresent: null,
  },
  { device: 'linux', label: 'Linux host', kind: 'host', modules: [], imagePresent: null },
]

export function catalogDevice(
  catalog: readonly CatalogDevice[],
  device: string,
): CatalogDevice | undefined {
  return catalog.find((entry) => entry.device === device)
}

export function deviceSupports(
  catalog: readonly CatalogDevice[],
  device: string,
  module: BuilderModule,
): boolean {
  return catalogDevice(catalog, device)?.modules.includes(module) ?? false
}
