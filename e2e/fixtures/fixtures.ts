import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const FIXTURES_DIR = path.dirname(fileURLToPath(import.meta.url))

function fixture(name: string): string {
  return readFileSync(path.join(FIXTURES_DIR, name), 'utf8')
}

// The journey's lab. Everything the suite creates is e2e- prefixed — the
// stack reset's container/bridge sweep keys on that prefix.
export const E2E_NET_NAME = 'e2e-net'
export const E2E_NET_DEFINITION = fixture('e2e-net.yml')
export const E2E_NET_SUITES = fixture('e2e-net.test-suites.json')

// The node set and named links the definition declares, for canvas/table
// assertions (kept next to the YAML so they cannot silently drift apart).
export const E2E_NET_ROUTERS = ['r1', 'r2', 'r3'] as const
export const E2E_NET_HOSTS = ['h1', 'h2'] as const
export const E2E_NET_NODES = [...E2E_NET_ROUTERS, ...E2E_NET_HOSTS] as const
export const E2E_NET_LINKS = ['core-a', 'core-b', 'core-c', 'services', 'sink'] as const

// The limited second account the role-gating spec signs in as; created via
// the Users UI in 02-users-groups. Password ≥8 chars (the UI's zod floor);
// every user has an email and a display name (delta 33), and the display name
// deliberately differs from the username so a check can tell which one a
// surface shows.
export const VIEWER = {
  username: 'e2e-viewer',
  password: 'e2e-viewer-password',
  email: 'e2e-viewer@e2e.test',
  displayName: 'E2E Viewer',
} as const

// The fast tier's canonical lab: created in 03, built in 04/05, published as
// a template in 06, granted to the viewer in 09.
export const FAST_LAB = 'e2e-build'

// Import wizard sources: two VyOS set-format configs sharing one /30 on eth1
// (the wire the suggestion should propose), a loopback each, an edge segment
// on imp-r1 that becomes a stub, plus carry (static routes) and quarantine
// (ssh service — management class) lines.
export const IMPORT_R1_CONFIG = fixture('import-r1.cfg')
export const IMPORT_R2_CONFIG = fixture('import-r2.cfg')
export const IMPORT_NODES = ['imp-r1', 'imp-r2'] as const
