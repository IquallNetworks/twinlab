import { execFileSync } from 'node:child_process'
import path from 'node:path'

import { E2E_ROOT, stackEnv } from './lib/env'

// The whole point of the suite: every run opens on a REAL EMPTY backend. The
// reset drops the stack's volumes and brings it back up, so the backend
// entrypoint re-runs migrations, re-seeds RBAC and re-creates the bootstrap
// admin. E2E_SKIP_RESET=1 skips the cycle for local spec iteration — the run
// then starts from whatever state the last one left.
export default async function globalSetup(): Promise<void> {
  const env = stackEnv()
  if (process.env.E2E_SKIP_RESET !== '1') {
    execFileSync(path.join(E2E_ROOT, 'scripts', 'stack.sh'), ['reset'], { stdio: 'inherit' })
  }
  await waitReady(env.baseUrl)
}

// Mirrors blackbox's backend_ready gate, through the frontend origin so it
// also proves the Vite proxy is up: /health/ready checks database + clab-api.
async function waitReady(baseUrl: string): Promise<void> {
  const deadline = Date.now() + 240_000
  let last = 'no response yet'
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/api/v1/health/ready`)
      const body: unknown = await res.json()
      if (
        res.ok &&
        typeof body === 'object' &&
        body !== null &&
        (body as { status?: unknown }).status === 'ready'
      ) {
        return
      }
      last = `HTTP ${res.status} ${JSON.stringify(body)}`
    } catch (err) {
      last = err instanceof Error ? err.message : String(err)
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000))
  }
  throw new Error(`e2e stack did not become ready within 240s (last: ${last})`)
}
