import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// The e2e project root (this file lives in e2e/lib/).
export const E2E_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
export const REPO_ROOT = path.dirname(E2E_ROOT)

export interface StackEnv {
  frontendPort: number
  baseUrl: string
  adminUsername: string
  adminPassword: string
  labFilesDir: string
}

// stack.env is the single source of truth for the e2e stack AND the suite —
// parsing it here (instead of duplicating values) means the config cannot
// drift from what the stack was actually started with.
export function stackEnv(): StackEnv {
  const file = path.join(E2E_ROOT, 'stack.env')
  const values = new Map<string, string>()
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    const trimmed = line.trim()
    if (trimmed === '' || trimmed.startsWith('#')) continue
    const eq = trimmed.indexOf('=')
    if (eq === -1) throw new Error(`stack.env: not a KEY=VALUE line: ${trimmed}`)
    values.set(trimmed.slice(0, eq), trimmed.slice(eq + 1))
  }
  const need = (key: string): string => {
    const value = values.get(key)
    if (value === undefined || value === '') throw new Error(`stack.env: missing ${key}`)
    return value
  }
  const frontendPort = Number(need('FRONTEND_PORT'))
  return {
    frontendPort,
    baseUrl: `http://localhost:${frontendPort}`,
    adminUsername: need('BOOTSTRAP_ADMIN_USERNAME'),
    adminPassword: need('BOOTSTRAP_ADMIN_PASSWORD'),
    labFilesDir: need('LAB_FILES_DIR'),
  }
}
