import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

// Visual identities as CSS token packs keyed off <html data-identity="...">.
// Bake-off outcome (docs/frontend-rework.md, Phase 1): SCHEMATIC won and is
// the default; Blueprint is shelved but stays selectable for reconsideration
// after the full rework; Control Room and Indigo were cut.
export const IDENTITIES = ['schematic', 'blueprint'] as const
export type Identity = (typeof IDENTITIES)[number]

export const IDENTITY_LABELS: Record<Identity, string> = {
  schematic: 'Schematic',
  blueprint: 'Blueprint',
}

const STORAGE_KEY = 'twinlab.identity'
const DEFAULT_IDENTITY: Identity = 'schematic'

function isIdentity(value: string | null): value is Identity {
  return (IDENTITIES as readonly string[]).includes(value ?? '')
}

/** Resolve the persisted identity and stamp it on <html>. Called from main.tsx
 * BEFORE the first render so the initial paint is already themed. */
export function initIdentity(): Identity {
  const stored = localStorage.getItem(STORAGE_KEY)
  const identity = isIdentity(stored) ? stored : DEFAULT_IDENTITY
  document.documentElement.dataset['identity'] = identity
  return identity
}

interface IdentityContextValue {
  identity: Identity
  setIdentity: (next: Identity) => void
}

const IdentityContext = createContext<IdentityContextValue | null>(null)

export function IdentityProvider({
  initial,
  children,
}: {
  initial: Identity
  children: ReactNode
}) {
  const [identity, setIdentityState] = useState<Identity>(initial)
  const setIdentity = useCallback((next: Identity) => {
    localStorage.setItem(STORAGE_KEY, next)
    document.documentElement.dataset['identity'] = next
    setIdentityState(next)
  }, [])
  return <IdentityContext value={{ identity, setIdentity }}>{children}</IdentityContext>
}

export function useIdentity(): IdentityContextValue {
  const ctx = useContext(IdentityContext)
  if (!ctx) throw new Error('useIdentity requires an IdentityProvider ancestor')
  return ctx
}
