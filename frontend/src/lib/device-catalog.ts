// The builder's device catalog SHAPE and module set. Since delta 18 the
// device list itself comes from the server (`GET /catalog` — what THIS
// deployment can run, with live image presence) via use-device-catalog.ts;
// this module keeps the pure pieces: the builder's representable module set,
// the catalog entry shape, list-parameterized lookups, and a static fallback
// used only until the server catalog resolves (or when it errors).
//
// Pure module (no React, no zod) so lib/build-doc.ts stays runnable under a
// plain node bundle.

// The builder's module VOCABULARY: netlab 26.07's full user-module set
// (netsim/modules/*.yml minus `initial`, which is the base every node gets).
// It is deliberately the whole list rather than the modules the inspector has
// dedicated controls for, because `modulesShape` is all-or-nothing — one
// unrepresentable entry used to send the WHOLE `module:` list to extras, and
// the BGP/LDP/VRF controls are gated on the typed list, so a single exotic
// module emptied the protocol UI of an otherwise fully typed lab.
//
// Vocabulary is not a support claim and not the checkbox list: what a device
// can actually run comes from the server catalog's per-device matrix
// (`deviceSupports`), and what gets offered comes from `offeredModules`.
export const BUILDER_MODULES = [
  'bfd',
  'bgp',
  'dhcp',
  'eigrp',
  'evpn',
  'gateway',
  'isis',
  'lag',
  'mpls',
  'ospf',
  'ripv2',
  'routing',
  'sr',
  'srv6',
  'stp',
  'vlan',
  'vrf',
  'vxlan',
] as const
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
// catalog is authoritative the moment it resolves. Mirror the backend's
// SUPPORTED_DEVICES here — module lists included, since the vocabulary no
// longer collapses them to "all four" — and remember that admitting or
// withdrawing a platform edits both (docs/nos-sweep/admitting-a-platform.md,
// step 1). Cisco IOL was withdrawn from both 2026-08-05 on CML licensing
// (ROADMAP 17.1), so an iol node now fails the builder's unknown-device gate
// and its lab edits as text.
export const FALLBACK_DEVICE_CATALOG: readonly CatalogDevice[] = [
  {
    device: 'vyos',
    label: 'VyOS',
    kind: 'router',
    modules: [
      'bfd',
      'bgp',
      'evpn',
      'gateway',
      'isis',
      'lag',
      'mpls',
      'ospf',
      'ripv2',
      'routing',
      'vlan',
      'vrf',
      'vxlan',
    ],
    imagePresent: null,
  },
  {
    device: 'frr',
    label: 'FRRouting',
    kind: 'router',
    modules: [
      'bfd',
      'bgp',
      'evpn',
      'gateway',
      'isis',
      'lag',
      'mpls',
      'ospf',
      'ripv2',
      'routing',
      'sr',
      'srv6',
      'stp',
      'vlan',
      'vrf',
      'vxlan',
    ],
    imagePresent: null,
  },
  {
    device: 'routeros7',
    label: 'MikroTik RouterOS 7 (CHR)',
    kind: 'router',
    modules: ['bfd', 'bgp', 'mpls', 'ospf', 'vlan', 'vrf', 'vxlan'],
    imagePresent: null,
  },
  // bird carries no MPLS in netlab's clab module matrix.
  {
    device: 'bird',
    label: 'BIRD routing daemon',
    kind: 'router',
    modules: [
      'bfd',
      'bgp',
      'evpn',
      'gateway',
      'lag',
      'ospf',
      'routing',
      'vlan',
      'vrf',
      'vxlan',
    ],
    imagePresent: null,
  },
  {
    device: 'dnsmasq',
    label: 'dnsmasq DHCP/DNS server',
    kind: 'host',
    modules: ['dhcp', 'lag', 'routing', 'vlan'],
    imagePresent: null,
  },
  { device: 'linux', label: 'Linux host', kind: 'host', modules: ['lag', 'routing', 'vlan'], imagePresent: null },
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

/** The modules to render checkboxes for, in vocabulary order: those SOME
 * cataloged device can run, plus whatever the document already selects — a
 * module in the vocabulary but not in the offer (today only `eigrp`, which no
 * admitted device supports) must still be removable where it appears. */
export function offeredModules(
  catalog: readonly CatalogDevice[],
  selected: readonly BuilderModule[],
): readonly BuilderModule[] {
  const runnable = new Set(catalog.flatMap((device) => device.modules))
  return BUILDER_MODULES.filter((module) => runnable.has(module) || selected.includes(module))
}
